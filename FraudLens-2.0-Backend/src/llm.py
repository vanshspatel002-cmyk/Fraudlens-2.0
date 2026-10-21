"""
fraudlens.llm
=============

Single abstraction over whichever model actually answers a `chat()` or
`describe_image()` call. Every check, the agent, and the UI talk to an
LLMProvider via get_provider() - none of them import google.genai,
requests-to-Ollama, or anything else provider-specific directly. That is
the whole point: GeminiProvider and OllamaProvider are fully
interchangeable, selected by LLM_PROVIDER in .env, so failing over to a
local model when Gemini's free-tier quota runs out mid-session (a real,
repeated problem - see outputs/model_survey.json) is a one-line .env
change, not a code change. It's also what made migrating off the
deprecated google.generativeai SDK onto google.genai a one-file change:
GeminiProvider's internals moved, LLMProvider's interface, the caching
layer, the retry policy, and usage_stats() did not.

Caching is not an optimisation here, it's survival. The Gemini free
tier has a low daily request ceiling, and this project gets re-run -
notebooks re-executed, evaluation scripts re-run after a code change -
far more often than any individual prompt actually changes. So both
chat() and describe_image() hash their inputs and check the cache
(src.db.cache_get/cache_set) before making a network call, the same
way PerceptionRecord dedupes vision output by content hash rather than
by image id (see models.py). describe_image() in particular hashes
the image *bytes*, not the path, so the same photo submitted under
twenty different filenames across twenty cases still costs exactly one
API call, ever.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
import os
import sqlite3
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import logging

from dotenv import load_dotenv

from . import db
from . import quota_budget

load_dotenv()

# Debug-level only: which key served which call is useful when a
# multi-key run behaves oddly, and pure noise otherwise. Enable with
# logging.getLogger("fraudlens.llm").setLevel(logging.DEBUG), or
# LLM_DEBUG=1 in .env for a run-wide switch.
_log = logging.getLogger("fraudlens.llm")
if (os.getenv("LLM_DEBUG") or "").strip() in {"1", "true", "yes"}:
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    _log.setLevel(logging.DEBUG)


def _debug(message: str) -> None:
    _log.debug("[llm] %s", message)

# gemini-2.0-flash and gemini-2.5-flash are closed to new free-tier keys
# (429 "limit: 0", or 404 "no longer available to new users"), so the
# model name is a knob, not a literal buried in call sites - override
# with GEMINI_MODEL in .env the next time Google reshuffles free-tier
# access.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Which provider get_provider() hands back by default - "gemini" or
# "ollama". Local Ollama has no daily quota, so it's the fallback for
# whenever Gemini's free tier runs dry mid-session (see both providers'
# docstrings below).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "moondream")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_CHAT_NAMESPACE = "llm_chat"
_VISION_NAMESPACE = "llm_vision"

# Retry policy for rate-limit / transient failures. 5 attempts, 2s
# doubling to 4/8/16/32s, so one flaky call costs at most ~62s instead
# of aborting a long batch job outright.
_RETRY_ATTEMPTS = 5
_RETRY_BASE_SECONDS = 2.0

# Ollama runs locally and has no rate limit to back off from - the only
# failures worth retrying are "server still starting up" or "this one
# request timed out under CPU load", both of which usually clear within
# a few seconds, so this schedule is shorter than Gemini's.
_OLLAMA_RETRY_ATTEMPTS = 3
_OLLAMA_RETRY_BASE_SECONDS = 2.0
# CPU vision inference on a local model may take minutes. Gemini has an
# explicit 60-second per-request timeout below; Ollama uses this local limit.
_OLLAMA_TIMEOUT_SECONDS = 180.0


# ---------------------------------------------------------------------------
# Usage counters - feeds the cost-per-case metric in evaluation.
#
# Module-level, not per-provider-instance, because the evaluation
# script cares about total spend across an entire run regardless of
# how many GeminiProvider objects got constructed along the way.
# ---------------------------------------------------------------------------

_usage = {
    "calls": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_latency_ms": 0,
}

# Per-key call counts and exhaustion state, keyed by key *label*
# ("GEMINI_API_KEY", "GEMINI_API_KEY_2", ...) rather than by the secret
# itself - so this dict, and anything that prints it, never holds a
# credential.
_key_usage: dict[str, dict[str, Any]] = {}


def usage_stats() -> dict[str, Any]:
    """Snapshot of call volume and cache effectiveness so far this process."""
    calls = _usage["calls"]
    hits = _usage["cache_hits"]
    try:
        budget = quota_budget.remaining_summary(len(_discover_keys()))
    except Exception as e:  # noqa: BLE001 - usage reporting must never break callers
        budget = {"error": f"{type(e).__name__}: {e}"}
    return {
        "calls": calls,
        "cache_hits": hits,
        "cache_misses": _usage["cache_misses"],
        "cache_hit_rate": (hits / calls) if calls else 0.0,
        "total_latency_ms": _usage["total_latency_ms"],
        "keys": {
            label: dict(stats) for label, stats in sorted(_key_usage.items())
        },
        "keys_configured": len(_key_usage),
        "keys_exhausted": sum(1 for s in _key_usage.values() if s["exhausted"]),
        "quota_budget": budget,
    }


def _record_usage(*, cache_hit: bool, latency_ms: int) -> None:
    _usage["calls"] += 1
    _usage["cache_hits" if cache_hit else "cache_misses"] += 1
    _usage["total_latency_ms"] += latency_ms


def _record_key_call(label: str, *, ok: bool) -> None:
    stats = _key_usage.setdefault(label, {"calls": 0, "rate_limited": 0, "exhausted": False})
    stats["calls"] += 1
    if not ok:
        stats["rate_limited"] += 1


def reset_key_state() -> None:
    """
    Clear every key's exhaustion flag and counters.

    Free-tier quotas are per-day, so a process that outlives a quota
    reset (or a test that wants a clean slate) needs a way to un-exhaust
    the pool without restarting.
    """
    _key_usage.clear()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A function/tool invocation the model asked the caller to perform."""

    name: str
    args: dict[str, Any]
    id: Optional[str] = None


@dataclass
class LLMResponse:
    """
    What every provider method returns, cache hit or not, chat or
    vision. Uniform shape means a check can call either method and
    handle the result the same way.
    """

    text: str
    tool_call: Optional[ToolCall]
    raw: dict[str, Any]
    model: str
    cached: bool
    latency_ms: int
    model_content: Optional[dict[str, Any]] = None
    tool_calls: Optional[list[ToolCall]] = None


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """
    Abstract base for every model backend. `conn` is an optional sqlite3
    connection (see src/db.py) - pass one to get caching, omit it (or
    pass None) to bypass the cache entirely, which is what the test
    suite does when it wants to force a real call.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> LLMResponse:
        """Text-only reasoning turn. `messages` is OpenAI-style [{"role", "content"}, ...]."""
        raise NotImplementedError

    @abstractmethod
    def describe_image(
        self,
        image_path: str,
        prompt: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> LLMResponse:
        """One vision call over a single image on disk."""
        raise NotImplementedError


def get_provider(name: Optional[str] = None) -> LLMProvider:
    """
    The one place the rest of the project should get an LLMProvider from,
    rather than importing and constructing GeminiProvider or OllamaProvider
    directly - that's what makes failing over to the local Ollama fallback
    when Gemini's free-tier quota runs out (a real, repeated problem this
    session - see scripts/find_working_model.py and outputs/model_survey.json)
    a matter of setting LLM_PROVIDER=ollama in .env, not editing call sites.

    `name` overrides LLM_PROVIDER for this call only, the same one-off
    pattern as GeminiProvider(model=...) elsewhere in this project -
    neither ever gets written back to .env.
    """
    choice = (name or LLM_PROVIDER).strip().lower()
    if choice == "gemini":
        return GeminiProvider()
    if choice == "ollama":
        return OllamaProvider()
    raise ValueError(f"unknown provider {choice!r} - LLM_PROVIDER (or name=) must be 'gemini' or 'ollama'")


# ---------------------------------------------------------------------------
# Gemini implementation
#
# This is the only place in the codebase allowed to `import google.genai`.
# If you find yourself wanting that import anywhere else, add a method
# to LLMProvider instead.
# ---------------------------------------------------------------------------


def _chat_cache_key(messages: list[dict], tools: Optional[list[dict]], model: str) -> str:
    payload = json.dumps(
        {"messages": messages, "tools": tools or [], "model": model},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _vision_cache_key(image_bytes: bytes, prompt: str, model: str) -> str:
    """
    Content-hashed, deliberately not path-hashed: the same photo
    attached to twenty different cases (or renamed, or re-uploaded)
    still hits the same cache entry, so it costs one vision call ever.
    """
    hasher = hashlib.sha256()
    hasher.update(image_bytes)
    hasher.update(b"\0")
    hasher.update(prompt.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(model.encode("utf-8"))
    return hasher.hexdigest()


class GeminiProvider(LLMProvider):
    """LLMProvider backed by Google's Gemini API via google-genai."""

    def __init__(self, model: str = GEMINI_MODEL, api_key: Optional[str] = None,
                 request_profile: Optional[str] = None) -> None:
        # Imported here, not at module scope, so importing src.llm never
        # requires google-genai to be installed unless a GeminiProvider
        # is actually constructed - handy for the day a second provider
        # shows up and most of the test suite doesn't need Gemini at all.
        from google import genai

        if api_key:
            # An explicit key bypasses discovery entirely: callers that
            # pass one (tests, the model survey) mean that key and no
            # other, and silently rotating away from it would be a
            # surprise.
            self._pool = KeyPool([("explicit", api_key)])
        else:
            self._pool = KeyPool()

        self._genai = genai
        self._clients: dict[str, Any] = {}
        self.http_attempts = 0
        self.http_statuses = []
        self.model = model
        # Compatibility correction, separate from historical research policy.
        # Old perception_records remain legitimate reusable observations; raw
        # request caches for a changed sampling configuration need distinct keys.
        self.request_profile = request_profile or os.getenv('FRAUDLENS_GEMINI_REQUEST_PROFILE', 'legacy')
        if self.request_profile not in {'legacy', 'gemini3_defaults_v2'}:
            raise ValueError('Unknown Gemini request profile')
        self._request_cache_suffix = '_gemini3_defaults_v2' if model.startswith('gemini-3') and self.request_profile == 'gemini3_defaults_v2' else ''

    def close(self):
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    # -- key rotation -----------------------------------------------------

    def _client_for(self, label: str, secret: str):
        """One cached Client per key - constructing them is not free."""
        if label not in self._clients:
            self._clients[label] = self._genai.Client(api_key=secret, http_options=self._genai.types.HttpOptions(
                timeout=60000,retry_options=self._genai.types.HttpRetryOptions(attempts=1),
                client_args={'follow_redirects':False,'event_hooks':{'request':[self._http_attempt],'response':[self._http_response]}}))
        return self._clients[label]

    def _http_attempt(self, request):
        # Counter only: never retain URLs, headers, prompts or image bodies.
        self.http_attempts += 1

    def _http_response(self, response):
        self.http_statuses.append(response.status_code)

    def model_metadata(self,*,operator,reason):
        """One operator-authorized GET; no inference, retries, rotation or caches."""
        from . import session_budget
        from .analysis_diagnostics import failure_detail
        label,secret=self._pool.current()
        # Session reservation first fails closed at the original lifetime cap.
        attempt=session_budget.reserve_model_metadata(self.model,operator,reason)
        http_before=self.http_attempts
        try:
            quota_budget.reserve_call(quota_budget.infer_consumer(),label,keys_configured=len(self._pool),model=self.model,kind='model_metadata')
            metadata=self._client_for(label,secret).models.get(model=self.model)
        except Exception as exc:
            session_budget.model_metadata_outcome(attempt,exc)
            exc.analysis_failure=failure_detail(exc,'model_metadata',attempt_count=1,
                attempted_network=self.http_attempts>http_before,model=self.model)
            raise
        session_budget.model_metadata_outcome(attempt)
        return {'requested_model':self.model,'supported_actions':getattr(metadata,'supported_actions',None),
            'input_token_limit':getattr(metadata,'input_token_limit',None),'output_token_limit':getattr(metadata,'output_token_limit',None)}

    @property
    def _client(self):
        """The client for the currently-selected key."""
        label, secret = self._pool.current()
        return self._client_for(label, secret)

    def _call_rotating(self, make_call, attempts: int = _RETRY_ATTEMPTS):
        """
        Run `make_call(client)` against the key pool.

        On a 429 the current key is marked exhausted and the next key is
        tried *immediately* - no sleep, because a per-day quota does not
        recover in seconds and sleeping on it wastes the whole point of
        having several keys. Only once every key has returned 429 does
        this fall back to exponential backoff, and after a completed
        backoff cycle the exhaustion flags are cleared so a quota
        rollover mid-run is picked up.

        Non-429 errors keep the existing behaviour exactly: retryable
        ones (503 and friends) back off through _call_with_retry, and
        everything else raises straight away.
        """
        from google.genai import errors as genai_errors

        recovery_mode=bool(os.environ.get('FRAUDLENS_RECOVERY_ID'))
        request_attempts = 0
        attempt_history = []
        if recovery_mode:attempts=1
        while True:
            label, secret = self._pool.current()
            client = self._client_for(label, secret)
            consumer = quota_budget.infer_consumer()

            def _budgeted_call():
                nonlocal request_attempts
                from . import session_budget
                from .analysis_diagnostics import failure_detail
                try:
                    session_budget.check()
                    quota_budget.reserve_call(consumer,label,keys_configured=len(self._pool),model=self.model,kind="gemini")
                    attempt = session_budget.reserve(self.model)
                    self._last_attempt=attempt
                except Exception as exc:
                    exc.analysis_failure=failure_detail(exc,'provider_control',attempt_count=request_attempts,attempted_network=request_attempts > 0,model=self.model)
                    exc.analysis_failure['attempt_history'] = list(attempt_history)
                    if request_attempts:
                        exc.analysis_failure['provider_status'] = 'locally_blocked_after_attempts'
                    raise
                request_attempts += 1
                try:
                    result = make_call(client)
                except Exception as exc:
                    session_budget.outcome(exc, attempt=attempt)
                    detail=failure_detail(exc,'provider_request',attempt_count=request_attempts,attempted_network=True,model=self.model)
                    attempt_history.append({key:detail[key] for key in ('error_category','http_status','provider_error_code','provider_request_id','finish_reason','block_reason') if key in detail})
                    exc.analysis_failure={**detail,'session_attempt':attempt,'attempt_history':list(attempt_history)}
                    raise
                session_budget.outcome(attempt=attempt)
                return result

            try:
                # 503/transient handling stays inside _call_with_retry;
                # 429 is caught here so it can rotate instead of sleep.
                # retry_rate_limits=False only while another key remains:
                # 429 should rotate at once, 503 should still back off.
                has_spare_key = not self._pool.all_exhausted() and len(self._pool) > 1
                result = _call_with_retry(
                    _budgeted_call, attempts=attempts,
                    retry_rate_limits=not has_spare_key,
                )
                _record_key_call(label, ok=True)
                _debug(f"call served by {label}")
                return result
            except genai_errors.APIError as e:
                if recovery_mode:
                    raise  # No key rotation or repeated automatic recovery probes.
                if not is_rate_limit_error(e):
                    raise
                _record_key_call(label, ok=False)
                self._pool.mark_exhausted(label)
                _debug(f"{label} rate-limited (HTTP 429) - marking exhausted")

                nxt = self._pool.advance()
                if nxt is not None:
                    print(
                        f"[llm] {label} hit its quota; rotating to {nxt[0]} "
                        f"({self._pool.labels.index(nxt[0]) + 1}/{len(self._pool)})",
                        file=sys.stderr,
                    )
                    continue

                # Every key is spent. Now - and only now - backing off is
                # the right move rather than a stall.
                if len(self._pool) > 1:
                    print(
                        f"[llm] all {len(self._pool)} keys are rate-limited; "
                        "backing off before retrying the pool",
                        file=sys.stderr,
                    )
                raise

    def _config(self, tools: Optional[list[dict]] = None, response_schema=None):
        from google.genai import types

        # Google recommends default sampling for Gemini 3.x. This is a request
        # compatibility correction, not evidence that temperature caused 503.
        # tools lives on the config object in
        # this SDK (there's no separate `tools=` kwarg on
        # generate_content), so a fresh config is built per call rather
        # than cached on self the way the old GenerationConfig was.
        sampling = {} if self._request_cache_suffix else {'temperature': 0}
        # Pydantic extra='forbid' includes additionalProperties. In this pinned
        # SDK, response_schema converts it to unsupported additional_properties
        # in the legacy Schema proto. JSON Schema belongs in response_json_schema.
        structured = {'response_mime_type':'application/json','response_json_schema':response_schema.model_json_schema()} if response_schema is not None else {}
        return types.GenerateContentConfig(**sampling, **structured, tools=tools or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))

    # -- chat -----------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> LLMResponse:
        key = _chat_cache_key(messages, tools, self.model)

        if conn is not None:
            lookup_start = time.monotonic()
            hit = db.cache_get(conn, _CHAT_NAMESPACE + self._request_cache_suffix, key)
            if hit is not None and _cached_generation_usable(hit):
                latency_ms = int((time.monotonic() - lookup_start) * 1000)
                _record_usage(cache_hit=True, latency_ms=latency_ms)
                return _response_from_cache(hit, self.model, latency_ms)

        start = time.monotonic()
        contents = _to_gemini_contents(messages)
        config = self._config(tools)

        def _call(client):
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            _validate_generation_response(response)
            return response

        response = self._call_rotating(_call)
        latency_ms = int((time.monotonic() - start) * 1000)

        result = LLMResponse(
            text=_extract_text(response),
            tool_call=_extract_tool_call(response),
            raw=_response_to_dict(response),
            model=self.model,
            cached=False,
            latency_ms=latency_ms,
            model_content=_extract_model_content(response),
            tool_calls=_extract_tool_calls(response),
        )
        result.raw['request_provenance']=_request_provenance(response,self)

        if conn is not None:
            db.cache_set(conn, _CHAT_NAMESPACE + self._request_cache_suffix, key, _response_to_cache_entry(result))
        _record_usage(cache_hit=False, latency_ms=latency_ms)

        return result

    # -- vision -----------------------------------------------------------

    def describe_image(
        self,
        image_path: str,
        prompt: str,
        conn: Optional[sqlite3.Connection] = None,
        retry_attempts: int = _RETRY_ATTEMPTS,
        response_schema=None,
    ) -> LLMResponse:
        # retry_attempts defaults to the normal policy - it only exists so
        # scripts/benchmark_perception.py can pass 1 and get the *raw*
        # per-call latency back, with a 429 raised immediately instead of
        # sleeping through 5 attempts of exponential backoff first. Every
        # normal caller (src/perception.py included) gets the same
        # retry/backoff behaviour as before.
        image_bytes = Path(image_path).read_bytes()
        key = _vision_cache_key(image_bytes, prompt, self.model)
        if response_schema is not None:
            key = hashlib.sha256(json.dumps({'vision_key':key,'response_schema':response_schema.model_json_schema(),'wire_contract':'json_schema_v1'},sort_keys=True).encode()).hexdigest()

        if conn is not None:
            lookup_start = time.monotonic()
            hit = db.cache_get(conn, _VISION_NAMESPACE + self._request_cache_suffix, key)
            if hit is not None and _cached_generation_usable(hit):
                latency_ms = int((time.monotonic() - lookup_start) * 1000)
                _record_usage(cache_hit=True, latency_ms=latency_ms)
                return _response_from_cache(hit, self.model, latency_ms)

        start = time.monotonic()
        # Validate before reserving a request; use the actual decoded format,
        # not a filename suffix. Send the same immutable bytes that were hashed.
        from PIL import Image
        from google.genai import types
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            mime = Image.MIME.get(image.format)
            if mime not in {'image/jpeg','image/png','image/webp','image/heic','image/heif'}:
                raise ValueError('Unsupported evidence image format; no provider request attempted.')
            contents = [prompt, types.Part.from_bytes(data=image_bytes,mime_type=mime)]
        config = self._config(response_schema=response_schema)

        def _call(client):
            response = client.models.generate_content(model=self.model,contents=contents,config=config)
            _validate_generation_response(response, structured=response_schema is not None, schema=response_schema)
            return response

        response = self._call_rotating(_call, attempts=retry_attempts)
        latency_ms = int((time.monotonic() - start) * 1000)

        result = LLMResponse(
            text=_extract_text(response),
            tool_call=_extract_tool_call(response),
            raw=_response_to_dict(response),
            model=self.model,
            cached=False,
            latency_ms=latency_ms,
            model_content=_extract_model_content(response),
            tool_calls=_extract_tool_calls(response),
        )
        result.raw['request_provenance']=_request_provenance(response,self)

        if conn is not None:
            db.cache_set(conn, _VISION_NAMESPACE + self._request_cache_suffix, key, _response_to_cache_entry(result))
        _record_usage(cache_hit=False, latency_ms=latency_ms)

        return result


# ---------------------------------------------------------------------------
# Gemini response helpers
# ---------------------------------------------------------------------------


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    """
    OpenAI-style [{"role": "user"/"assistant"/"system", "content": str}]
    to Gemini-style [{"role": "user"/"model", "parts": [{"text": str}]}].
    System messages fold into the following user turn (or the first
    turn, if there is none) since generate_content has no separate
    system slot on this call path. Parts must be {"text": ...} dicts,
    not bare strings - google.genai validates contents strictly and
    rejects a plain string inside "parts" (the old google.generativeai
    SDK was more forgiving here).
    """
    contents: list[dict] = []
    pending_system: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        text = message.get("content", "")
        if role == "system":
            pending_system.append(text)
            continue
        if message.get('provider_content'):
            contents.append(message['provider_content'])
            continue
        if role == 'tool':
            try:result=json.loads(text) if isinstance(text,str) else text
            except (ValueError,TypeError):result={'result':str(text)}
            response={'name':message['name'],'response':result if isinstance(result,dict) else {'result':result}}
            if message.get('tool_call_id') is not None:
                response['id']=message['tool_call_id']
            part={'function_response':response}
            if contents and contents[-1]['role']=='user' and all('function_response' in item for item in contents[-1]['parts']):
                contents[-1]['parts'].append(part)
            else:
                contents.append({'role':'user','parts':[part]})
            continue
        if pending_system:
            text = "\n\n".join(pending_system) + "\n\n" + text
            pending_system = []
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
    if pending_system:
        # Nothing but system messages were given - still send something.
        contents.append({"role": "user", "parts": [{"text": "\n\n".join(pending_system)}]})
    return contents


class GenerationResponseError(ValueError):
    error_category = 'response_schema_invalid'


def _cached_generation_usable(entry):
    """Reject saved empty/blocked/truncated generations without altering history."""
    if not (str(entry.get('text') or '').strip() or entry.get('tool_call') or entry.get('tool_calls')):
        return False
    raw=entry.get('raw') or {}
    feedback=raw.get('prompt_feedback') or raw.get('promptFeedback') or {}
    if (feedback.get('block_reason') or feedback.get('blockReason')) not in {None,'BLOCK_REASON_UNSPECIFIED'}:
        return False
    if 'candidates' in raw:
        candidates=raw['candidates'] or []
        if not candidates or (candidates[0].get('finish_reason') or candidates[0].get('finishReason')) != 'STOP':
            return False
    return True


def _validate_generation_response(response, structured=False, schema=None):
    """Do not cache or use truncated, blocked, empty or malformed generations."""
    from .analysis_diagnostics import response_metadata
    metadata = response_metadata(response)
    candidates = getattr(response, 'candidates', None) or []
    finish = metadata.get('finish_reason')
    blocked = metadata.get('block_reason') not in {None, 'BLOCK_REASON_UNSPECIFIED'}
    unusable = blocked or not candidates or finish != 'STOP'
    unusable |= not bool(_extract_text(response).strip() or _extract_tool_calls(response))
    if structured:
        if schema is not None:
            try:schema.model_validate_json(_extract_text(response))
            except (ValueError,TypeError):unusable=True
        else:unusable |= getattr(response,'parsed',None) is None
    if unusable:
        error = GenerationResponseError('The generation was blocked, incomplete or empty; private response content omitted.')
        error.response_metadata = metadata
        raise error


def _extract_text(response: Any) -> str:
    try:
        return response.text or ""
    except Exception:
        return ""


def _extract_tool_call(response: Any) -> Optional[ToolCall]:
    calls = _extract_tool_calls(response)
    return calls[0] if calls else None


def _extract_tool_calls(response: Any) -> list[ToolCall]:
    try:
        calls = response.function_calls
        if calls:
            return [ToolCall(name=fc.name, args=dict(fc.args) if fc.args else {}, id=getattr(fc,'id',None)) for fc in calls]
    except Exception:
        pass
    return []


def _response_to_dict(response: Any) -> dict[str, Any]:
    model_dump=getattr(response,'model_dump',None)
    if callable(model_dump):
        try:return model_dump(mode='json',exclude_none=True)
        except Exception:pass
    to_json_dict = getattr(response, "to_json_dict", None)
    if callable(to_json_dict):
        try:
            return to_json_dict()
        except Exception:
            pass
    return {"text": _extract_text(response)}


def _extract_model_content(response):
    """Preserve opaque provider signatures for the next function-calling turn."""
    try:
        content=response.candidates[0].content
        return content.model_dump(mode='json',exclude_none=True)
    except (AttributeError,IndexError,TypeError):
        return None


def _request_provenance(response,provider):
    from datetime import datetime,timezone
    from .analysis_diagnostics import response_metadata
    return {'session_attempt':getattr(provider,'_last_attempt',None),
        'requested_model':provider.model,'serving_model':getattr(response,'model_version',None),
        'timestamp':datetime.now(timezone.utc).isoformat(), **response_metadata(response)}


def _response_to_cache_entry(result: LLMResponse) -> dict[str, Any]:
    # latency_ms is deliberately not stored: on a hit it must reflect
    # the cost of the cache lookup that just happened, not the API
    # latency of the original call that populated the entry.
    return {
        "text": result.text,
        "tool_call": {"name": result.tool_call.name, "args": result.tool_call.args,
                      **({"id":result.tool_call.id} if result.tool_call.id is not None else {})}
        if result.tool_call
        else None,
        "raw": result.raw,
        "model_content":result.model_content,
        "tool_calls":[{"name":call.name,"args":call.args,"id":call.id} for call in result.tool_calls] if result.tool_calls is not None else None,
    }


def _response_from_cache(entry: dict[str, Any], model: str, latency_ms: int) -> LLMResponse:
    tool_call = entry.get("tool_call")
    tool_calls = entry.get('tool_calls')
    if tool_calls is None and entry.get('model_content'):
        # Older cache entries retained the full provider turn but exposed only
        # its first call. Recover every call before replaying that turn.
        tool_calls = [part['function_call'] for part in entry['model_content'].get('parts', []) if part.get('function_call')]
    return LLMResponse(
        text=entry.get("text", ""),
        tool_call=ToolCall(**tool_call) if tool_call else None,
        raw=entry.get("raw", {}),
        model=model,
        cached=True,
        latency_ms=latency_ms,
        model_content=entry.get('model_content'),
        tool_calls=[ToolCall(name=call['name'], args=call.get('args') or {}, id=call.get('id')) for call in tool_calls] if tool_calls is not None else None,
    )


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------


def _is_retryable_error(error: Exception, genai_errors: Any) -> bool:
    """
    google.genai collapses everything into APIError, split into
    ClientError (4xx) and ServerError (5xx) with the real HTTP status on
    `.code`. ServerError is always worth retrying (transient); ClientError
    is only worth retrying at 429 (rate limit) - a 400/401/403/404 will
    never succeed no matter how many times it's retried, and backing off
    on one just hides a real misconfiguration for a minute before it
    fails anyway.
    """
    if isinstance(error, genai_errors.ServerError):
        return True
    if isinstance(error, genai_errors.ClientError):
        return getattr(error, "code", None) == 429
    return False


def is_rate_limit_error(error: Exception) -> bool:
    """
    True if `error` is a 429 from the Gemini API. Exists so code outside
    this file - scripts/benchmark_perception.py needs to tell "rate
    limited" apart from "actually broken" - doesn't have to import
    google.genai itself just to catch its error types (see the class
    docstring above: this is the only place that import is allowed).
    """
    from google.genai import errors as genai_errors

    return isinstance(error, genai_errors.ClientError) and getattr(error, "code", None) == 429


def is_not_found_error(error: Exception) -> bool:
    """
    True if `error` is a 404 from the Gemini API - a model name that's
    been retired or renamed, not a quota problem. Model names churn (see
    scripts/find_working_model.py, which surveys several at once because
    some of them are expected to already be gone); this is what lets that
    survey tell "doesn't exist" apart from "exists but exhausted" without
    importing google.genai itself, same reasoning as is_rate_limit_error.
    """
    from google.genai import errors as genai_errors

    return isinstance(error, genai_errors.ClientError) and getattr(error, "code", None) == 404


def is_unavailable_error(error: Exception) -> bool:
    """
    True if `error` is a 503 UNAVAILABLE from the Gemini API - transient
    "high demand" server-side congestion, not a quota problem or a dead
    model name. src/perception.py's run_perception_pass gives this its own
    short backoff schedule separate from the 429 rate-limit path (a
    quota's daily reset can't be waited out in seconds; a demand spike
    usually clears in a few), so it needs to tell the two apart the same
    way is_rate_limit_error/is_not_found_error do, without importing
    google.genai itself.
    """
    from google.genai import errors as genai_errors

    return isinstance(error, genai_errors.ServerError) and getattr(error, "code", None) == 503


def is_quota_budget_error(error: Exception) -> bool:
    """True when the local shared budget blocks a Gemini call before the network."""
    return isinstance(error, quota_budget.QuotaBudgetExhausted)


# ---------------------------------------------------------------------------
# API key pool
#
# The free tier caps requests per project per day, and this project needs
# roughly an order of magnitude more calls than one key allows. Several
# keys multiply the effective daily quota, but only if a 429 moves to the
# next key *immediately* rather than sleeping - backing off on an
# exhausted daily quota is waiting for tomorrow, which is not a retry
# policy, it is a stall. So: rotate first, back off only when every key
# has been tried and failed.
#
# Discovery is by convention rather than configuration: GEMINI_API_KEY,
# then GEMINI_API_KEY_2 .. GEMINI_API_KEY_10. Blanks and duplicates are
# dropped, so a half-filled .env behaves sensibly, and the
# single-key case is exactly the old behaviour - one key, no rotation
# possible, back off as before.
# ---------------------------------------------------------------------------

_MAX_NUMBERED_KEYS = 10


def _discover_keys() -> list[tuple[str, str]]:
    """
    Returns [(label, secret), ...] in priority order, de-duplicated.

    The label is the environment variable name and is what gets logged;
    the secret never is.
    """
    names = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{n}" for n in range(2, _MAX_NUMBERED_KEYS + 1)]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        value = (os.getenv(name) or "").strip()
        # A duplicated key is not a second quota - it is the same project
        # counted twice, and rotating onto it would burn a retry for
        # nothing.
        if value and value not in seen:
            seen.add(value)
            found.append((name, value))
    return found


class KeyPool:
    """
    A rotating pool of API keys with per-key exhaustion tracking.

    Deliberately not a generic round-robin: keys are tried in
    configuration order and a key is only skipped once it has actually
    returned a 429 this session. That keeps behaviour predictable
    (key 1 does the work until it runs dry) and makes the usage_stats()
    breakdown legible afterwards.
    """

    def __init__(self, keys: Optional[list[tuple[str, str]]] = None) -> None:
        self._keys = keys if keys is not None else _discover_keys()
        if not self._keys:
            raise ValueError(
                "No Gemini API key found - set GEMINI_API_KEY in .env "
                "(see .env.example), optionally with GEMINI_API_KEY_2..._10 "
                "for more daily quota"
            )
        self._index = 0
        for label, _ in self._keys:
            _key_usage.setdefault(label, {"calls": 0, "rate_limited": 0, "exhausted": False})

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self._keys]

    def current(self) -> tuple[str, str]:
        return self._keys[self._index]

    def all_exhausted(self) -> bool:
        return all(_key_usage[label]["exhausted"] for label in self.labels)

    def mark_exhausted(self, label: str) -> None:
        _key_usage[label]["exhausted"] = True

    def advance(self) -> Optional[tuple[str, str]]:
        """
        Move to the next key that has not been exhausted this session.
        Returns None when every key is spent - the caller's signal to
        stop rotating and start backing off.
        """
        for step in range(1, len(self._keys) + 1):
            candidate = (self._index + step) % len(self._keys)
            label = self._keys[candidate][0]
            if not _key_usage[label]["exhausted"]:
                self._index = candidate
                return self._keys[candidate]
        return None

    def reset_exhaustion(self) -> None:
        """Called after a full backoff cycle - the quota may have rolled over."""
        for label in self.labels:
            _key_usage[label]["exhausted"] = False


def _call_with_retry(fn, attempts: int = _RETRY_ATTEMPTS, base_seconds: float = _RETRY_BASE_SECONDS,
                     retry_rate_limits: bool = True):
    """
    Retry `fn` on rate-limit / transient API errors, doubling the delay
    each time, starting at `base_seconds`. Non-retryable errors (auth,
    bad request, ...) are re-raised immediately. Every retry prints to
    stderr so a long batch job's progress bar (stdout) stays readable
    while still showing that it's alive, not hung.
    """
    from google.genai import errors as genai_errors

    delay = base_seconds
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except genai_errors.APIError as e:
            if not _is_retryable_error(e, genai_errors):
                raise
            if is_rate_limit_error(e) and not retry_rate_limits:
                # The caller has other keys to try. Backing off here would
                # defeat the entire point of having them: a per-day quota
                # does not clear in 30 seconds, so sleeping 2+4+8+16s
                # before rotating just adds half a minute of dead time per
                # key. Surface it immediately and let _call_rotating move
                # on; the backoff still applies once every key is spent.
                raise
            last_error = e
            if attempt == attempts:
                break
            print(
                f"[llm] {type(e).__name__} (HTTP {e.code}, attempt {attempt}/{attempts}), "
                f"retrying in {delay:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Ollama implementation
#
# This is the only place in the codebase allowed to talk HTTP to Ollama
# directly, same rule as GeminiProvider and google.genai above. Talks to
# Ollama's own HTTP API (http://localhost:11434/api/chat) with `requests`
# (already in requirements.txt for everything else) rather than pulling in
# an Ollama SDK - the surface this needs is one endpoint and a base64
# image field, not worth a new dependency for.
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    """
    LLMProvider backed by a local Ollama server - the offline fallback for
    when Gemini's free-tier daily quota is exhausted (a real, repeated
    problem this session; see GeminiProvider's docstring and
    outputs/model_survey.json). Reuses the exact same cache keys
    (_chat_cache_key/_vision_cache_key already fold in self.model, so a
    Gemini entry and an Ollama entry for the same prompt never collide),
    the same LLMResponse shape, and the same usage_stats() counters as
    GeminiProvider - nothing outside this file can tell the two apart.

    No rate limit exists to retry around, so unlike GeminiProvider's
    _call_with_retry (built for 429s and 5xxs), this one only retries
    connection errors and timeouts - see _call_ollama_with_retry.
    """

    def __init__(self, model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> None:
        import requests

        self.model = model
        self._host = host.rstrip("/")
        self._session = requests.Session()

        # Fail fast and clearly at construction time, not on the first
        # chat() call buried inside a batch job - "connection refused"
        # three hours into an overnight perception pass is a much worse
        # way to learn Ollama was never started.
        try:
            response = self._session.get(f"{self._host}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(
                f"Ollama is not reachable at {self._host} ({type(e).__name__}: {e}). "
                "Install it from https://ollama.com/download, start it "
                "(`ollama serve`, or launch the Ollama app), then pull a vision "
                f"model with `ollama pull {model}`."
            ) from e

    # -- chat -----------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> LLMResponse:
        # tools is accepted for interface compatibility but not sent to
        # Ollama: nothing in this project calls chat(tools=...) against a
        # local model today (moondream and similar small vision models
        # don't follow function-calling reliably anyway), and it's
        # folded into the cache key regardless so a future tool-using
        # call here would still get its own cache entry rather than
        # silently reusing a tool-less one.
        key = _chat_cache_key(messages, tools, self.model)

        if conn is not None:
            lookup_start = time.monotonic()
            hit = db.cache_get(conn, _CHAT_NAMESPACE, key)
            if hit is not None:
                latency_ms = int((time.monotonic() - lookup_start) * 1000)
                _record_usage(cache_hit=True, latency_ms=latency_ms)
                return _response_from_cache(hit, self.model, latency_ms)

        # messages is already OpenAI-style [{"role", "content"}, ...],
        # which is exactly what Ollama's /api/chat expects - no
        # conversion needed, unlike Gemini's contents shape.
        start = time.monotonic()
        payload = self._post_chat(messages)
        latency_ms = int((time.monotonic() - start) * 1000)

        result = LLMResponse(
            text=_ollama_text(payload),
            tool_call=None,
            raw=payload,
            model=self.model,
            cached=False,
            latency_ms=latency_ms,
        )

        if conn is not None:
            db.cache_set(conn, _CHAT_NAMESPACE, key, _response_to_cache_entry(result))
        _record_usage(cache_hit=False, latency_ms=latency_ms)

        return result

    # -- vision -----------------------------------------------------------

    def describe_image(
        self,
        image_path: str,
        prompt: str,
        conn: Optional[sqlite3.Connection] = None,
        retry_attempts: int = _OLLAMA_RETRY_ATTEMPTS,
    ) -> LLMResponse:
        # retry_attempts mirrors GeminiProvider.describe_image()'s same
        # kwarg, for the same reason: src/perception.py's
        # run_perception_pass calls describe_image with retry_attempts=1
        # on every provider uniformly (see _perceive_with_unavailable_retry)
        # to take retry policy into its own hands, so both providers need
        # to accept it even though only Gemini's 503 path actually uses
        # the override today.
        image_bytes = Path(image_path).read_bytes()
        key = _vision_cache_key(image_bytes, prompt, self.model)

        if conn is not None:
            lookup_start = time.monotonic()
            hit = db.cache_get(conn, _VISION_NAMESPACE, key)
            if hit is not None:
                latency_ms = int((time.monotonic() - lookup_start) * 1000)
                _record_usage(cache_hit=True, latency_ms=latency_ms)
                return _response_from_cache(hit, self.model, latency_ms)

        start = time.monotonic()
        # Ollama takes the image as base64 in the message's own "images"
        # array, not as a separate part the way Gemini's contents list
        # works.
        messages = [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }
        ]
        payload = self._post_chat(messages, retry_attempts=retry_attempts)
        latency_ms = int((time.monotonic() - start) * 1000)

        result = LLMResponse(
            text=_ollama_text(payload),
            tool_call=None,
            raw=payload,
            model=self.model,
            cached=False,
            latency_ms=latency_ms,
        )

        if conn is not None:
            db.cache_set(conn, _VISION_NAMESPACE, key, _response_to_cache_entry(result))
        _record_usage(cache_hit=False, latency_ms=latency_ms)

        return result

    # -- shared HTTP call -------------------------------------------------

    def _post_chat(self, messages: list[dict], retry_attempts: int = _OLLAMA_RETRY_ATTEMPTS) -> dict[str, Any]:
        def _call():
            response = self._session.post(
                f"{self._host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0},
                },
                timeout=_OLLAMA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()

        return _call_ollama_with_retry(_call, attempts=retry_attempts)


def _ollama_text(payload: dict[str, Any]) -> str:
    return payload.get("message", {}).get("content", "") or ""


def _call_ollama_with_retry(
    fn, attempts: int = _OLLAMA_RETRY_ATTEMPTS, base_seconds: float = _OLLAMA_RETRY_BASE_SECONDS
):
    """
    Retry `fn` only on connection errors and timeouts. A local server has
    no rate limit to back off from - the only failures worth retrying are
    "hasn't finished starting yet" or "this one request timed out under
    CPU load"; an HTTP error status (bad model name, malformed request)
    means the same thing on every retry, so raise_for_status()'s
    HTTPError is deliberately not caught here and propagates immediately.
    """
    import requests

    delay = base_seconds
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            if attempt == attempts:
                break
            print(
                f"[llm] Ollama {type(e).__name__} (attempt {attempt}/{attempts}), "
                f"retrying in {delay:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
    assert last_error is not None
    raise last_error
