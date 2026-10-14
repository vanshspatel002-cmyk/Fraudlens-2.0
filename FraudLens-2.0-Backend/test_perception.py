"""
Test suite for src.perception.

Live integration tests against the real Gemini API for the happy path
(parseable JSON, cache short-circuit, coverage accounting) plus a fully
offline test for the malformed-response fallback, using a fake provider
so that path is deterministic and doesn't depend on ever actually
getting a bad response from the real model. Same minimal, stdlib-only
runner as test_llm.py/test_ingest.py.

Run with:
    python test_perception.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db, ingest, llm, perception
from src.llm import GeminiProvider, LLMProvider, LLMResponse, is_rate_limit_error
from src.models import Case, Image

# ---------------------------------------------------------------------------
# Tiny test runner (same shape as test_llm.py/test_ingest.py)
# ---------------------------------------------------------------------------

_TESTS: list = []


class Skip(Exception):
    """Raise to mark a test skipped rather than failed - same convention as test_llm.py."""


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed, skipped = 0, 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            if os.environ.get('FRAUDLENS_TEST_LIVE') != '1' and fn.__name__ in {
                'test_perceive_image_produces_parseable_json','test_repeated_call_served_from_cache_no_new_api_call','test_perception_coverage_increments'}:
                raise Skip('Live integration disabled; bounded pilot probe records provider results separately.')
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Skip as e:
            skipped += 1
            print(f"SKIP  {fn.__name__}  ->  {e}")
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            # A 429 means the free tier is out of quota for the day, which
            # is an environmental condition, not a defect in this code.
            # Measured at 20 requests/key/day, so a full run of this file
            # can exhaust it outright - and reporting that as a FAIL would
            # train everyone to ignore a red suite. Same reasoning as
            # test_llm.py skipping when Ollama isn't running.
            if is_rate_limit_error(e):
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

_TEST_DB_FD, _TEST_DB_PATH_STR = tempfile.mkstemp(suffix=".db", prefix="fraudlens_test_perception_")
os.close(_TEST_DB_FD)
TEST_DB_PATH = Path(_TEST_DB_PATH_STR)

_provider: Optional[GeminiProvider] = None


def get_provider() -> GeminiProvider:
    global _provider
    if _provider is None:
        _provider = GeminiProvider()
    return _provider


def find_sample_images(n: int) -> list[Path]:
    """First `n` distinct images found under data/raw - whichever ones, they're just probes."""
    root = Path("data/raw")
    found: list[Path] = []
    for suffix in (".jpg", ".jpeg", ".JPEG", ".JPG", ".png"):
        for path in sorted(root.rglob(f"*{suffix}")):
            if path not in found:
                found.append(path)
            if len(found) >= n:
                return found
    raise FileNotFoundError(f"found only {len(found)}/{n} images under data/raw")


# Three distinct images so the cache-hit test and the malformed-response
# test each get a content_hash the perception cache has never seen,
# rather than accidentally reusing one another's already-cached record.
SAMPLE_IMAGES = find_sample_images(3)


def make_case_and_image(conn, case_id: str, path: Path) -> Image:
    """A minimal real Case + Image row, hashed for real but without CLIP (perception doesn't need it)."""
    db.insert_case(conn, Case(case_id=case_id, claimant_id="claimant-1", garage_id="garage-1", claim_type="collision"))
    phash, dhash = ingest.compute_hashes(path)
    image = Image(
        image_id=str(uuid4()),
        case_id=case_id,
        path=str(path),
        content_hash=ingest.compute_sha256(path),
        phash=phash,
        dhash=dhash,
    )
    db.save_image(conn, image)
    return image


class _GarbledProvider(LLMProvider):
    """Returns unparseable text on every call - deterministic stand-in for a model that misbehaves."""

    model = "fake-garbled-provider"

    def chat(self, messages, tools=None, conn=None):
        raise NotImplementedError("not exercised by this test")

    def describe_image(self, image_path, prompt, conn=None):
        return LLMResponse(
            text="Sure! Here you go:\n```\nthis isn't valid json at all {{{",
            tool_call=None,
            raw={},
            model=self.model,
            cached=False,
            latency_ms=0,
        )


# Set by test_perceive_image_produces_parseable_json, reused by the cache test.
_image_a: Optional[Image] = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@test
def test_provider_initializes():
    provider = get_provider()
    assert provider.model


@test
def test_perceive_image_produces_parseable_json():
    global _image_a
    with db.session(TEST_DB_PATH) as conn:
        _image_a = make_case_and_image(conn, "case-perception-a", SAMPLE_IMAGES[0])
        record = perception.perceive_image(conn, _image_a, get_provider())

    assert not (record.anomaly_notes and "perception parse failure" in record.anomaly_notes), (
        f"expected a parseable response, got a parse-failure record: {record.anomaly_notes}"
    )
    assert record.damage_severity in {"none", "minor", "moderate", "severe"}, record.damage_severity
    assert record.shadow_direction in {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "none_visible"}, record.shadow_direction
    assert record.shadow_length in {"none", "short", "medium", "long"}, record.shadow_length
    print(f"  damage_severity={record.damage_severity!r}  shadow_direction={record.shadow_direction!r}  "
          f"weather_observed={record.weather_observed!r}")


@test
def test_repeated_call_served_from_cache_no_new_api_call():
    assert _image_a is not None, "expected test_perceive_image_produces_parseable_json to have run first"

    before = llm.usage_stats()["calls"]
    with db.session(TEST_DB_PATH) as conn:
        record = perception.perceive_image(conn, _image_a, get_provider())
    after = llm.usage_stats()["calls"]

    assert after == before, f"expected zero new llm calls on a cached image, calls went {before} -> {after}"
    assert record.content_hash == _image_a.content_hash
    print(f"  llm.usage_stats()['calls'] unchanged at {after} - served entirely from the perception cache")


@test
def test_perception_coverage_increments():
    with db.session(TEST_DB_PATH) as conn:
        image_b = make_case_and_image(conn, "case-perception-b", SAMPLE_IMAGES[1])
        before = db.perception_coverage(conn)
        perception.perceive_image(conn, image_b, get_provider())
        after = db.perception_coverage(conn)

    assert after["total"] == before["total"], "this test shouldn't change the total unique-image count"
    assert after["covered"] == before["covered"] + 1
    print(f"  coverage {before['covered']}/{before['total']} -> {after['covered']}/{after['total']}")


@test
def test_malformed_response_handled_without_crashing():
    with db.session(TEST_DB_PATH) as conn:
        image_c = make_case_and_image(conn, "case-perception-c", SAMPLE_IMAGES[2])
        record = perception.perceive_image(conn, image_c, _GarbledProvider())
        persisted = db.get_perception(conn, image_c.content_hash)

    assert record.anomaly_notes and "perception parse failure" in record.anomaly_notes, record.anomaly_notes
    assert record.damage_severity is None
    assert persisted is not None, "a failure record must still be saved, not silently dropped"
    assert persisted.anomaly_notes == record.anomaly_notes
    print(f"  anomaly_notes={record.anomaly_notes!r}")


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
