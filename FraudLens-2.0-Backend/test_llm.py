"""
Test suite for src.llm.

Live integration tests against the real Gemini API - not mocked - because
the entire point of this module is caching and retry behaviour against
the actual free-tier API, and a mock can't tell us whether that works.
Same minimal, stdlib-only runner as test_models.py: no framework, plain
English summary, run anywhere the project's own dependencies are
installed.

The Ollama section near the bottom is the same idea applied to
OllamaProvider, with one difference: Ollama is a local, optional
dependency (see .env.example), not something every environment running
this suite necessarily has running. Those tests SKIP - a third outcome
alongside PASS/FAIL - rather than failing the whole suite when Ollama
isn't reachable, the same way test_provider_initializes_and_finds_api_key
would rather explain a missing GEMINI_API_KEY than crash confusingly.
Where Ollama IS running, expect its tests to take noticeably longer than
Gemini's: CPU vision inference on a local model is minutes, not seconds,
for the first (cold) call.

Requires GEMINI_API_KEY in .env and at least one .jpg/.jpeg/.png under
data/raw.

Run with:
    python test_llm.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db
from src.llm import GeminiProvider, OllamaProvider, get_provider as llm_get_provider, usage_stats

# ---------------------------------------------------------------------------
# Tiny test runner (same shape as test_models.py, plus a PASS/FAIL/SKIP
# line per test - these are slow live API calls, so seeing progress as
# each one finishes matters more here than it does for the in-memory
# model tests.)
# ---------------------------------------------------------------------------

_TESTS: list = []


class Skip(Exception):
    """Raise from a test to mark it skipped, not failed - e.g. Ollama isn't running."""


def _is_quota_error(error: Exception) -> bool:
    """True for a 429 from Gemini, imported lazily so this file still runs without google-genai."""
    try:
        from src.llm import is_rate_limit_error
    except ImportError:
        return False
    return is_rate_limit_error(error)


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed, skipped = 0, 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Skip as e:
            skipped += 1
            print(f"SKIP  {fn.__name__}  ->  {e}")
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            # Out of free-tier quota for the day is an environmental
            # condition, not a defect - measured at 20 requests/key/day,
            # which a single run of this file can exhaust on its own. It
            # skips for the same reason the Ollama tests below skip when
            # Ollama isn't running: a suite that goes red for reasons
            # unrelated to the code trains people to ignore it.
            if _is_quota_error(e):
                skipped += 1
                print(f"SKIP  {fn.__name__}  ->  free-tier quota exhausted (429); re-run after it resets")
                continue
            failed += 1
            failures.append((fn.__name__, e, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}  ->  {type(e).__name__}: {e}")
    if failures:
        print("\n" + "=" * 70)
        for name, e, tb in failures:
            print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_DB_FD, _TEST_DB_PATH_STR = tempfile.mkstemp(suffix=".db", prefix="fraudlens_test_llm_")
os.close(_TEST_DB_FD)
TEST_DB_PATH = Path(_TEST_DB_PATH_STR)

_provider: Optional[GeminiProvider] = None


def get_provider() -> GeminiProvider:
    """Lazily construct the one provider instance every test shares."""
    global _provider
    if _provider is None:
        _provider = GeminiProvider()
    return _provider


def find_sample_image() -> Path:
    """First image found under data/raw - whichever one, it's just a probe."""
    root = Path("data/raw")
    for suffix in (".jpg", ".jpeg", ".png", ".JPEG", ".JPG", ".PNG"):
        for path in root.rglob(f"*{suffix}"):
            return path
    raise FileNotFoundError("no .jpg/.jpeg/.png found under data/raw")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@test
def test_provider_initializes_and_finds_api_key():
    assert os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY missing from .env"
    provider = get_provider()
    assert provider.model, "provider has no model name configured"
    print(f"  model = {provider.model}")


@test
def test_chat_returns_nonempty_response():
    provider = get_provider()
    response = provider.chat(
        [{"role": "user", "content": "Reply with exactly one word: ready"}],
        conn=None,  # no conn: force a real call, never a cache hit
    )
    assert response.text.strip(), "chat() returned empty text"
    assert response.cached is False
    print(f"  response.text = {response.text.strip()!r}  ({response.latency_ms}ms)")


@test
def test_repeated_chat_hits_the_cache():
    messages = [{"role": "user", "content": "Name one primary color. One word only."}]
    with db.session(TEST_DB_PATH) as conn:
        first = get_provider().chat(messages, conn=conn)
        second = get_provider().chat(messages, conn=conn)

    assert first.cached is False, "first call should be a cache miss"
    assert second.cached is True, "second identical call should be a cache hit"
    assert second.text == first.text
    print(f"  first call (miss):  {first.latency_ms}ms")
    print(f"  second call (hit):  {second.latency_ms}ms")


@test
def test_usage_stats_reports_correctly():
    stats = usage_stats()
    assert stats["calls"] == stats["cache_hits"] + stats["cache_misses"]
    if stats["calls"] == 0:
        # Every earlier live-API test skipped on 429, so there is nothing
        # to summarise. That is a quota condition, not a defect in the
        # counters - failing here would make a red suite mean "the free
        # tier is out" rather than "something is broken".
        raise Skip("no API calls were made this run (earlier tests skipped on quota)")
    assert stats["cache_hits"] >= 1, "expected the cache-hit test to have registered a hit"
    assert 0.0 <= stats["cache_hit_rate"] <= 1.0
    print(f"  {stats}")


@test
def test_vision_call_on_sample_image():
    image_path = find_sample_image()
    with db.session(TEST_DB_PATH) as conn:
        response = get_provider().describe_image(
            str(image_path),
            "Describe this image in one short sentence.",
            conn=conn,
        )
    assert response.text.strip(), "describe_image() returned empty text"
    print(f"  image = {image_path}")
    print(f"  response.text = {response.text.strip()!r}")
    print(f"  took {response.latency_ms}ms")


@test
def test_get_provider_factory_dispatches_and_validates():
    """
    get_provider() is what perception.py (and every future caller) uses
    instead of constructing GeminiProvider/OllamaProvider directly - this
    only checks the dispatch logic itself (name -> class, bad name ->
    ValueError), not either provider's own behaviour, which the rest of
    this file and the Ollama section below already cover.
    """
    assert isinstance(llm_get_provider("gemini"), GeminiProvider)
    try:
        llm_get_provider("not-a-real-provider")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown provider name")
    print("  get_provider('gemini') -> GeminiProvider, get_provider('not-a-real-provider') -> ValueError")


# ---------------------------------------------------------------------------
# API key rotation
#
# Offline and free: these drive the pool directly rather than burning real
# quota, which matters because the whole point of the feature is that
# quota is the scarce resource. The one thing they cannot test without
# spending a day's allowance is a genuine 429 round trip, so the rotation
# path is exercised through a fake client that raises one.
# ---------------------------------------------------------------------------


@test
def test_key_discovery_dedupes_and_orders():
    import os

    from src.llm import _discover_keys

    # Every numbered slot must be isolated, not just the four this test
    # sets. Written when the .env held one key, it saved only _1.._4 - so
    # once five real keys were configured, GEMINI_API_KEY_5 leaked out of
    # the environment and into the assertion. The range is taken from the
    # module's own constant so adding slots cannot silently break it again.
    from src.llm import _MAX_NUMBERED_KEYS

    slots = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{n}" for n in range(2, _MAX_NUMBERED_KEYS + 1)]
    saved = {name: os.environ.get(name) for name in slots}
    for name in slots:
        os.environ.pop(name, None)
    try:
        os.environ["GEMINI_API_KEY"] = "alpha"
        os.environ["GEMINI_API_KEY_2"] = "beta"
        # A duplicate is the same project's quota counted twice, not a
        # second allowance - rotating onto it would waste a retry.
        os.environ["GEMINI_API_KEY_3"] = "alpha"
        os.environ["GEMINI_API_KEY_4"] = "   "  # blank/whitespace must be ignored
        found = _discover_keys()
        assert [label for label, _ in found] == ["GEMINI_API_KEY", "GEMINI_API_KEY_2"], found
        assert [secret for _, secret in found] == ["alpha", "beta"]
        print(f"  discovered {[l for l, _ in found]} (duplicate and blank dropped)")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@test
def test_single_key_behaves_exactly_as_before():
    """A lone key must not gain rotation behaviour it cannot support."""
    from src.llm import KeyPool, reset_key_state

    reset_key_state()
    pool = KeyPool([("only", "k")])
    assert len(pool) == 1
    assert pool.current()[0] == "only"

    # advance() is only ever called after the current key has been marked
    # exhausted (see GeminiProvider._call_rotating), and that ordering is
    # what guarantees the loop can never hand the failed key straight
    # back and spin forever. Asserted in the real sequence rather than in
    # isolation, because in isolation "give me a usable key" legitimately
    # returns the only key there is.
    pool.mark_exhausted("only")
    assert pool.advance() is None, "with one exhausted key there is nowhere to rotate to"
    assert pool.all_exhausted()
    print("  one key: exhausting it yields no rotation target, so backoff applies as before")


@test
def test_rotation_moves_to_the_next_key_and_tracks_exhaustion():
    from src.llm import KeyPool, reset_key_state, usage_stats

    reset_key_state()
    pool = KeyPool([("K1", "a"), ("K2", "b"), ("K3", "c")])
    assert pool.current()[0] == "K1"

    pool.mark_exhausted("K1")
    assert pool.advance()[0] == "K2"
    pool.mark_exhausted("K2")
    assert pool.advance()[0] == "K3"
    pool.mark_exhausted("K3")
    assert pool.advance() is None, "exhausting every key must signal 'now back off'"
    assert pool.all_exhausted()

    stats = usage_stats()
    assert stats["keys_configured"] == 3
    assert stats["keys_exhausted"] == 3

    # A daily quota rolls over; a long-running process must be able to
    # pick the pool back up without restarting.
    pool.reset_exhaustion()
    assert pool.advance()[0] == "K1"
    assert usage_stats()["keys_exhausted"] == 0
    print("  K1->K2->K3->backoff, then reset re-enables the pool")


@test
def test_usage_stats_reports_per_key_counts_without_leaking_secrets():
    from src.llm import KeyPool, _record_key_call, reset_key_state, usage_stats

    reset_key_state()
    KeyPool([("GEMINI_API_KEY", "super-secret-value"), ("GEMINI_API_KEY_2", "another-secret")])
    _record_key_call("GEMINI_API_KEY", ok=True)
    _record_key_call("GEMINI_API_KEY", ok=True)
    _record_key_call("GEMINI_API_KEY", ok=False)

    stats = usage_stats()
    assert stats["keys"]["GEMINI_API_KEY"]["calls"] == 3
    assert stats["keys"]["GEMINI_API_KEY"]["rate_limited"] == 1
    assert stats["keys"]["GEMINI_API_KEY_2"]["calls"] == 0

    # Counters are keyed by env-var name, never by the credential.
    blob = repr(stats)
    assert "super-secret-value" not in blob and "another-secret" not in blob, "usage_stats leaked a key"
    print(f"  per-key counts: {stats['keys']}")


@test
def test_a_429_rotates_immediately_rather_than_sleeping():
    """
    The behavioural core of the feature: a rate limit must move to the
    next key at once. Backing off on a per-day quota is waiting for
    tomorrow, which is a stall rather than a retry - and with 20
    requests/key/day measured on this tier, sleeping instead of rotating
    would waste the entire benefit of configuring more keys.
    """
    import time

    from src.llm import GeminiProvider, reset_key_state, usage_stats

    try:
        from google.genai import errors as genai_errors
    except ImportError as e:
        raise Skip(f"google-genai not installed: {e}")

    reset_key_state()
    provider = GeminiProvider.__new__(GeminiProvider)  # bypass __init__'s real Client
    from src.llm import KeyPool

    provider._pool = KeyPool([("K1", "a"), ("K2", "b")])
    provider._clients = {}
    provider._genai = None
    provider.model = "test-model"

    served_by: list[str] = []

    class FakeClient:
        def __init__(self, label: str) -> None:
            self.label = label

    def fake_client_for(label, secret):
        return FakeClient(label)

    provider._client_for = fake_client_for  # type: ignore[assignment]

    def make_call(client):
        served_by.append(client.label)
        if client.label == "K1":
            raise genai_errors.ClientError(
                429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
            )
        return "ok"

    started = time.monotonic()
    result = provider._call_rotating(make_call, attempts=1)
    elapsed = time.monotonic() - started

    assert result == "ok"
    assert served_by == ["K1", "K2"], f"expected K1 then K2, got {served_by}"
    assert elapsed < 1.0, f"rotation must not sleep; took {elapsed:.1f}s"
    stats = usage_stats()
    assert stats["keys"]["K1"]["rate_limited"] == 1
    assert stats["keys"]["K1"]["exhausted"] is True
    assert stats["keys"]["K2"]["calls"] == 1
    assert stats["keys"]["K2"]["exhausted"] is False
    print(f"  K1 429 -> K2 served the call in {elapsed * 1000:.0f}ms, no backoff")


# ---------------------------------------------------------------------------
# Ollama section
#
# OllamaProvider must be fully interchangeable with GeminiProvider - same
# LLMResponse shape, same cache, same usage_stats() counters - so these
# tests reuse TEST_DB_PATH rather than standing up a second fixture:
# _vision_cache_key/_chat_cache_key already fold the model name in, so a
# Gemini cache entry and an Ollama cache entry for the same prompt can't
# collide even sharing one db.
# ---------------------------------------------------------------------------

_ollama_provider: Optional[OllamaProvider] = None
_ollama_unavailable_reason: Optional[str] = None


def get_ollama_provider() -> OllamaProvider:
    """
    Lazily construct the one OllamaProvider every Ollama test shares, or
    raise Skip once (and remember why) so every Ollama test after the
    first unreachable check skips immediately instead of each re-trying
    the connection and re-printing the same reason.
    """
    global _ollama_provider, _ollama_unavailable_reason
    if _ollama_provider is None and _ollama_unavailable_reason is None:
        try:
            _ollama_provider = OllamaProvider()
        except ConnectionError as e:
            _ollama_unavailable_reason = str(e)
    if _ollama_provider is None:
        raise Skip(_ollama_unavailable_reason)
    return _ollama_provider


@test
def test_ollama_provider_initializes_or_skips():
    provider = get_ollama_provider()
    assert provider.model, "provider has no model name configured"
    print(f"  model = {provider.model}")


@test
def test_ollama_vision_call_and_cache_hit():
    """
    One live call, not two: CPU inference on a local model is slow (see
    the module docstring), so the first describe_image() below both
    proves the call works (nonempty text, right shape) and serves as the
    cache-miss half of the cache-hit check - the second call should
    return instantly from src/llm.py's own cache, same as GeminiProvider.
    """
    provider = get_ollama_provider()
    image_path = find_sample_image()
    with db.session(TEST_DB_PATH) as conn:
        first = provider.describe_image(str(image_path), "Describe this image in one short sentence.", conn=conn)
        second = provider.describe_image(str(image_path), "Describe this image in one short sentence.", conn=conn)

    assert first.text.strip(), "describe_image() returned empty text"
    assert first.model == provider.model
    assert first.cached is False, "first call should be a cache miss"
    assert second.cached is True, "second identical call should be a cache hit"
    assert second.text == first.text
    print(f"  image = {image_path}")
    print(f"  response.text = {first.text.strip()!r}")
    print(f"  first call (miss): {first.latency_ms}ms   second call (hit): {second.latency_ms}ms")


@test
def test_ollama_chat_returns_llmresponse():
    """
    Structural only, not a content assertion: moondream (the default
    OLLAMA_MODEL) is a vision-captioning model first, and its plain-text
    chat() replies are not reliably nonempty the way describe_image()'s
    are - that's the model's own limitation, not this provider's. What
    this project actually needs from chat() over Ollama is the same
    LLMResponse shape and cache/usage_stats() wiring GeminiProvider has;
    this checks exactly that, by running after the vision test above has
    already warmed the model.
    """
    provider = get_ollama_provider()
    before = usage_stats()["calls"]
    response = provider.chat([{"role": "user", "content": "Reply with one word: ok"}], conn=None)
    after = usage_stats()["calls"]

    assert response.model == provider.model
    assert response.cached is False
    assert isinstance(response.text, str)
    assert after == before + 1, "expected exactly one new usage_stats() call to be recorded"
    print(f"  response.text = {response.text!r}  ({response.latency_ms}ms)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        ok = run_all()
    finally:
        try:
            TEST_DB_PATH.unlink(missing_ok=True)
        except OSError as e:
            print(f"  (cleanup) could not remove {TEST_DB_PATH}: {e}", file=sys.stderr)
    sys.exit(0 if ok else 1)
