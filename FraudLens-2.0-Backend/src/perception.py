"""
fraudlens.perception
=====================

The one-time vision pass. Every unique image (by sha256, not by
submission) gets exactly one structured vision-model call in its
entire lifetime; the parsed result is cached in perception_records
keyed by that hash, and every downstream check reads from the cache
rather than ever calling the vision API itself. This - not the LLM
provider's own request-level cache in src/llm.py - is what makes an
800-case, ~1,300-image corpus affordable to analyse on a free tier:
llm.py's cache prevents *re-running this script* from re-paying for a
photo it already described; this module's cache is what keeps the
number of calls in the first place down to "one per unique photo"
instead of "one per case that photo happens to appear in".

Run with:
    python -m src.perception --limit 20 --rpm 10        # test run
    python -m src.perception                             # full pass, no limit
    python -m src.perception --provider ollama --limit 5  # local fallback, no quota

--provider overrides LLM_PROVIDER from .env for this run only (gemini or
ollama - see src.llm.get_provider); --model further overrides that
provider's own default model name. Neither ever touches .env.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Literal
from pydantic import ConfigDict, create_model

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, llm
from src.llm import (
    LLM_PROVIDER,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    get_provider,
    is_quota_budget_error,
    is_rate_limit_error,
    is_unavailable_error,
)
from src.models import Image, PerceptionRecord

# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

# Enumerated fields are stated explicitly with their allowed values so the
# model has no ambiguity about the vocabulary; the "report only what is
# visible" instructions are repeated (once generally, once specifically for
# shadows) because shadow_direction/shadow_length feed the solar-geometry
# check, where a confident wrong answer is actively worse than an honest
# "none_visible" - a check can reason about "no signal", it cannot reason
# about a plausible-looking lie.
PERCEPTION_PROMPT = """\
You are a vision system supporting an insurance fraud review. Look at this \
single photo and describe ONLY what is visible in it - never guess, infer, \
or fill in a plausible-sounding answer for anything you cannot actually see.

Respond with STRICT JSON ONLY: a single JSON object, nothing else. No \
markdown code fences, no ```json, no preamble or explanation before or \
after it. Your entire response must start with { and end with }.

Return exactly these fields:

{
  "damage_description": "<one or two plain sentences describing visible vehicle damage, or 'no damage visible'>",
  "damage_severity": "<one of: none, minor, moderate, severe>",
  "weather_observed": "<one of: clear, overcast, rain, wet_ground, snow, unknown>",
  "road_condition": "<short description of the visible road/ground surface, e.g. 'dry asphalt', 'wet gravel'>",
  "shadow_direction": "<one of: N, NE, E, SE, S, SW, W, NW, none_visible>",
  "shadow_length": "<one of: none, short, medium, long>",
  "lighting": "<one of: daylight, dusk, night, artificial, unknown>",
  "plate_text": "<license plate text if legible, or \\"\\" if not visible or not readable>",
  "scene_context": "<one plain sentence describing the overall scene - setting, location type>",
  "anomaly_notes": "<anything visually inconsistent or unusual, or \\"\\" if nothing stands out>"
}

Critical instructions:
- shadow_direction and shadow_length feed a solar-geometry consistency check. \
A confident but wrong answer here is worse than an honest one: if shadows \
are not clearly visible, you MUST answer "none_visible" for direction and \
"none" for length rather than guessing.
- Use "unknown" for weather_observed or lighting whenever you are not \
confident, rather than picking the closest-sounding option.
- Only report what is visible in THIS image. Do not use outside knowledge, \
assumptions about the vehicle model, or general expectations about what \
"usually" happens in a photo like this.
"""

_RETRY_SUFFIX = """

Your previous response could not be parsed as JSON. This is critical: \
respond with ONLY a single valid JSON object. Do not include markdown \
formatting, code fences, backticks, comments, or any text outside the \
JSON object. The very first character of your response must be { and the \
very last character must be }.
"""

_JSON_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|```\s*$")

# Fallback for a response that isn't valid JSON even after fence-stripping -
# grabs everything between the first { and the last } in the (already
# fence-stripped) text. Simple, not a real brace-matching parser: good
# enough for PERCEPTION_PROMPT's flat, single-object schema, where the
# usual failure mode is a smaller model wrapping otherwise-valid JSON in a
# sentence of prose it was explicitly told not to add.
_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

_EXPECTED_FIELDS = (
    "damage_description",
    "damage_severity",
    "weather_observed",
    "road_condition",
    "shadow_direction",
    "shadow_length",
    "lighting",
    "plate_text",
    "scene_context",
    "anomaly_notes",
)
PERCEPTION_SCHEMA_VERSION = 'fraudlens-visible-observations-2026-10-20-v1'
_ENUM_FIELDS = {
    'damage_severity': {'none', 'minor', 'moderate', 'severe', 'unknown'},
    'weather_observed': {'clear', 'overcast', 'rain', 'wet_ground', 'snow', 'unknown'},
    'shadow_direction': {'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'none_visible', 'unknown'},
    'shadow_length': {'none', 'short', 'medium', 'long', 'unknown'},
    'lighting': {'daylight', 'dusk', 'night', 'artificial', 'unknown'},
}

# The probe and production application validator share exactly the same fields
# and enum vocabulary; this does not invent a second observation contract.
PerceptionObservation = create_model('PerceptionObservation',
    __config__=ConfigDict(extra='forbid',strict=True),
    **{key: (Literal[tuple(sorted(_ENUM_FIELDS[key]))] if key in _ENUM_FIELDS else str, ...)
       for key in _EXPECTED_FIELDS})


class PerceptionSchemaError(ValueError):
    """A provider response arrived but did not meet the observation contract."""
    error_category = 'response_schema_invalid'


def _schema_issues(parsed):
    issues = []
    for key in _EXPECTED_FIELDS:
        if key not in parsed:
            issues.append(key + ':missing')
        elif not isinstance(parsed[key], str):
            issues.append(key + ':expected_string')
        elif key in _ENUM_FIELDS and parsed[key] not in _ENUM_FIELDS[key]:
            issues.append(key + ':invalid_enum')
    return issues


def perception_record_usable(record):
    """Failed/invalid cached rows cannot masquerade as successful perception.

    Legacy observations remain usable when their recorded values are valid;
    reuse is attributed to the original record's model, never to a new call.
    """
    if record is None or record.raw_response.get('error'):
        return False
    observed = False
    for key in _EXPECTED_FIELDS:
        value = getattr(record, key, None)
        if value is None:
            continue
        if not isinstance(value, str) or (key in _ENUM_FIELDS and value not in _ENUM_FIELDS[key]):
            return False
        if value.strip() and value != 'unknown':
            observed = True
    return observed

# How long to back off after a call fails all the way through llm.py's own
# retries. That's already 5 attempts of exponential backoff (see
# src/llm.py) - reaching here means something is genuinely rate-limited or
# down, so this run backs off further and moves on rather than hammering it
# again immediately on the very next image.
_ERROR_BACKOFF_SECONDS = 30.0

# 503 UNAVAILABLE gets its own, much shorter schedule, applied per-image
# with llm.py's own retry disabled (see _perceive_with_unavailable_retry).
# A benchmark survey against gemini-flash-latest (outputs/model_survey.json)
# found two-thirds of calls hitting transient "high demand" 503s that
# cleared within seconds - riding those out with a few short retries is far
# cheaper than either llm.py's default 5-attempt/2s-base schedule (2, 4, 8,
# 16, 32s - built for a 429 that genuinely won't clear for a while) or this
# module's own flat _ERROR_BACKOFF_SECONDS. A 429 is not covered by this
# schedule at all: a daily quota reset can't be waited out in tens of
# seconds, so that path is left exactly as it was.
_UNAVAILABLE_BACKOFF_BASE_SECONDS = 5.0
_UNAVAILABLE_MAX_ATTEMPTS = 4

# A 429 surfaced here has already been through src.llm's key rotation. Treat
# it as a daily quota wall and stop immediately; unlike 503, quota does not
# heal over tens of minutes.
_QUOTA_EXHAUSTED_AFTER = 1

# How many consecutive 503s mean "the service is down" rather than
# "briefly busy". Five, because each one has already survived the
# per-image 5/10/20/40s ladder in _perceive_with_unavailable_retry, so
# five in a row is roughly six minutes of sustained unavailability.
_UNAVAILABLE_GIVE_UP_AFTER = 5

# A 503 is a service availability condition, not quota exhaustion. After
# five image-level 503 failures, wait at session level before trying the
# pass again; if the service stays down through these rounds, give up for
# this invocation rather than looping indefinitely.
_SERVICE_UNAVAILABLE_BACKOFF_SECONDS = 15 * 60
_SERVICE_UNAVAILABLE_RETRIES = 4

# Same non-quota failure policy as the ablation arm: a few isolated bad
# records should not kill a resumable pass, but five in a row is a bug or
# misconfiguration, not a quota condition.
ERROR_LOG = Path("outputs/perception_errors.log")
MAX_CONSECUTIVE_NON_QUOTA_FAILURES = 5


def log_failure(image: Image, kind: str, error: Exception) -> None:
    """Append fixed diagnostics, never a raw provider traceback or applicant text."""
    try:
        from .analysis_diagnostics import failure_detail
        record={**failure_detail(error,'perception_batch'),'case_id':image.case_id,'image_id':image.image_id}
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record)+'\n')
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    """Tolerate a model wrapping its JSON in ```json ... ``` despite being told not to."""
    return _JSON_FENCE.sub("", text.strip()).strip()


# How often perception's JSON parsing needed to fall back past a strict,
# whole-response json.loads. Gemini follows PERCEPTION_PROMPT's STRICT
# JSON ONLY instruction reliably; the smaller/local models this project
# can now run via src.llm.OllamaProvider do not, so this is the number
# that actually says whether a given model's output is trustworthy enough
# to build checks on - not just whether every call eventually produced
# *a* dict. Module-level and cumulative for the process, same convention
# as src.llm's usage_stats(); run_perception_pass reports the delta for
# one run via before/after snapshots, same as db.perception_coverage().
_parse_stats = {"strict": 0, "regex_extracted": 0, "failed": 0}


def parse_stats() -> dict[str, int]:
    """Snapshot of how perception's JSON parsing has fared so far this process."""
    return dict(_parse_stats)


def _try_parse(text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Two tiers, strictest first: the whole (fence-stripped) response as
    JSON, then - only if that fails - the first {...} block extracted out
    of it via _JSON_OBJECT_PATTERN, in case the model wrapped otherwise-
    valid JSON in prose despite being told not to. Every call is counted
    into _parse_stats regardless of outcome, so parse_stats() can report
    how often the fallback was actually needed.
    """
    cleaned = _strip_json_fences(text)

    strict_error: Optional[str] = None
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            _parse_stats["strict"] += 1
            return parsed, None
        strict_error = f"expected a JSON object, got {type(parsed).__name__}"
    except json.JSONDecodeError as e:
        strict_error = f"JSONDecodeError: {e}"

    match = _JSON_OBJECT_PATTERN.search(cleaned)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                _parse_stats["regex_extracted"] += 1
                return parsed, None
        except json.JSONDecodeError:
            pass

    _parse_stats["failed"] += 1
    return None, strict_error


def _fill_missing_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    A model can follow STRICT JSON ONLY and still just skip a field -
    smaller/local models do this far more than Gemini. "unknown" for a
    missing field is deliberately distinct from "" (PERCEPTION_PROMPT's
    own "nothing found" answer for plate_text/anomaly_notes) and from a
    parse failure (this dict parsed fine; one key inside it didn't show
    up) - it's a data-quality signal worth keeping visible, not something
    to silently collapse into "found nothing" or crash over.
    """
    filled = dict(parsed)
    for field_name in _EXPECTED_FIELDS:
        filled.setdefault(field_name, "unknown")
    return filled


def _record_from_parsed(content_hash: str, source: str, parsed: dict[str, Any], raw_text: str) -> PerceptionRecord:
    parsed = _fill_missing_fields(parsed)
    return PerceptionRecord(
        content_hash=content_hash,
        source=source,
        damage_description=parsed["damage_description"],
        damage_severity=parsed["damage_severity"],
        weather_observed=parsed["weather_observed"],
        road_condition=parsed["road_condition"],
        shadow_direction=parsed["shadow_direction"],
        shadow_length=parsed["shadow_length"],
        lighting=parsed["lighting"],
        plate_text=parsed["plate_text"],
        scene_context=parsed["scene_context"],
        anomaly_notes=parsed["anomaly_notes"],
        raw_response={"text": raw_text, "parsed": parsed, 'schema_version': PERCEPTION_SCHEMA_VERSION},
    )


# ---------------------------------------------------------------------------
# Single image
# ---------------------------------------------------------------------------


def perceive_image(
    conn,
    image: Image,
    provider: LLMProvider,
    force: bool = False,
    retry_attempts: Optional[int] = None,
    provenance: Optional[dict] = None,
    release_transactions: bool = False,
) -> PerceptionRecord:
    """
    Return the cached PerceptionRecord for image.content_hash, or produce
    and cache one. `force=True` re-runs the parse/save step even if a
    record already exists - it does not force a fresh API call, because
    the vision call itself is still deduplicated by src/llm.py's own
    content-hash cache; the whole point of this project's caching is that
    an unchanged (image, prompt, model) triple never pays twice.

    `retry_attempts` is left at its default (None) for every normal
    caller, which means "let the provider use its own default retry
    policy" - GeminiProvider.describe_image() only accepts this kwarg, so
    it's forwarded rather than always passed, keeping this compatible with
    any LLMProvider that doesn't have it (e.g. test_perception.py's fake
    provider). run_perception_pass is the one caller that overrides it, to
    take retry policy into its own hands (see
    _perceive_with_unavailable_retry).
    """
    if not force:
        cached = db.get_perception(conn, image.content_hash)
        if perception_record_usable(cached):
            if provenance is not None:
                provenance['source'] = 'perception_cache'
                provenance['source_model'] = cached.source
                provenance['schema_version'] = cached.raw_response.get('schema_version', 'legacy_record')
            return cached

    model = getattr(provider, "model", "unknown")

    def _describe(prompt: str):
        if release_transactions:
            # The durable worker owns this connection; only optional
            # observation/request-cache writes exist before its final result.
            conn.commit()
        options = {'response_schema': PerceptionObservation} if isinstance(provider, GeminiProvider) else {}
        if retry_attempts is None:
            return provider.describe_image(image.path, prompt, conn=conn, **options)
        return provider.describe_image(image.path, prompt, conn=conn, retry_attempts=retry_attempts, **options)

    response = _describe(PERCEPTION_PROMPT)
    responses = [response]
    parsed, error = _try_parse(response.text)
    schema_issues = _schema_issues(parsed) if parsed is not None else []
    if schema_issues:
        parsed, error = None, 'Structured observation schema validation failed.'

    if parsed is None:
        # One retry, stricter instruction, same image. This is a genuinely
        # new (image, prompt, model) key so it is a real second call - an
        # accepted exception to "one call per image ever", made only when
        # the first response was too malformed to use at all.
        response = _describe(PERCEPTION_PROMPT + _RETRY_SUFFIX)
        responses.append(response)
        parsed, error = _try_parse(response.text)
        schema_issues = _schema_issues(parsed) if parsed is not None else []
        if schema_issues:
            parsed, error = None, 'Structured observation schema validation failed.'

    if parsed is not None:
        if provenance is not None:
            provenance['source'] = 'request_cache' if getattr(response, 'cached', False) else 'fresh_provider'
        record = _record_from_parsed(image.content_hash, getattr(response, 'model', None) or model, parsed, response.text)
    else:
        if provenance is not None:
            provenance['source'] = 'unavailable'
        # Never crash a batch job over one unparseable response - save what
        # we know (the failure itself) and move on. anomaly_notes carries
        # the parse error so it's visible to a human, not silently dropped.
        from .analysis_diagnostics import failure_detail
        network_attempts = sum(not bool(getattr(value, 'cached', False)) for value in responses)
        diagnostic = failure_detail(PerceptionSchemaError(error or 'Unusable structured observations.'),
                                    'perception_schema', attempt_count=network_attempts,
                                    attempted_network=network_attempts > 0, model=model)
        diagnostic['response_count'] = len(responses)
        diagnostic.update({key:value for key,value in ((getattr(response,'raw',None) or {}).get('request_provenance') or {}).items()
                           if key in {'finish_reason','block_reason','provider_request_id'}})
        record = PerceptionRecord(
            content_hash=image.content_hash,
            source=getattr(response, 'model', None) or model,
            anomaly_notes=f"perception parse failure: {error}",
            raw_response={"error": error, 'schema_issues': schema_issues,
                          'schema_version': PERCEPTION_SCHEMA_VERSION, 'diagnostic': diagnostic},
        )

    request_provenance = (getattr(response, 'raw', None) or {}).get('request_provenance')
    if isinstance(request_provenance, dict):
        record.raw_response['request_provenance'] = {key: request_provenance[key] for key in
            ('session_attempt', 'requested_model', 'serving_model', 'timestamp','finish_reason','block_reason','provider_request_id',
             'token_usage','http_status','latency_ms','started_at','source','schema_version','schema','run_id','case_id') if key in request_provenance}
    db.save_perception(conn, record)
    if provenance is not None:
        provenance['source_model'] = record.source
        provenance['schema_version'] = record.raw_response.get('schema_version', 'legacy_record')
    return record


# ---------------------------------------------------------------------------
# Batch pass
# ---------------------------------------------------------------------------


def _unique_images(conn) -> list[Image]:
    """One Image per distinct content_hash - the same photo in three cases is one call."""
    seen: set[str] = set()
    unique: list[Image] = []
    for image in db.get_all_images(conn):
        if image.content_hash in seen:
            continue
        seen.add(image.content_hash)
        unique.append(image)
    return unique


# Ground truth lives outside the database on purpose (see models.py), so
# stratification reads the CSV directly. This is the one place in the
# runtime that touches the answer key, and it is doing scheduling, not
# scoring: which images to spend quota on is an operational decision, and
# nothing derived from it reaches a Finding.
GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")

# Free-tier requests per day, per key, at the time of writing. Used only
# for the "how many days will this take" estimate.
FREE_TIER_DAILY_QUOTA = 20


def _archetype_by_case() -> dict[str, str]:
    try:
        with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
            return {row["case_id"]: row["archetype"] for row in csv.DictReader(fh)}
    except OSError:
        return {}


def select_stratified(conn, clean_sample: int, seed: int = 20260821) -> list[Image]:
    """
    Every image belonging to a fraud case, plus a random sample of
    clean-case images.

    The point is that a full pass costs more quota than exists. Fraud
    cases are the ones a check can be *measured* against - recall is
    undefined without them - while clean cases are needed only in enough
    number to estimate a false-positive rate, and 80 of them estimates it
    to within a few percentage points. Spending equal quota on all 560
    clean cases would buy a slightly tighter error bar on the number we
    already know is small, at the cost of never measuring recall at all.

    Sampling is seeded so a resumed or repeated run selects the same
    images - otherwise each attempt would scatter quota across a
    different subset and none of them would ever complete.
    """
    archetypes = _archetype_by_case()
    unique = _unique_images(conn)

    fraud, clean = [], []
    for image in unique:
        archetype = archetypes.get(image.case_id, "CLEAN")
        (clean if archetype == "CLEAN" else fraud).append(image)

    rng = random.Random(seed)
    sampled_clean = rng.sample(clean, min(clean_sample, len(clean)))

    # Ordering is load-bearing rather than cosmetic. The free tier
    # measured out at 20 requests per key per day, so a run is far more
    # likely to stop partway than to finish, and whatever it got through
    # is the whole measurement.
    #
    # Two rules, in order:
    #
    # 1. Fraud before clean. Sorting the combined list by case_id put the
    #    low-numbered clean cases at the front, which spent an entire
    #    day's quota on 20 clean images and perceived not one fraud case -
    #    leaving recall unmeasurable, the one thing stratifying was
    #    supposed to protect. Recall is undefined without fraud cases; a
    #    false-positive rate merely gets a wider error bar with fewer
    #    clean ones.
    #
    # 2. Within fraud, archetypes whose check *needs perception* first.
    #    Perception only unblocks checks that consume it, and only one
    #    archetype in this corpus is targeted by a perception-dependent
    #    check. Spending a scarce day's quota on EXTERNAL_SOURCING images
    #    buys nothing, because external_corpus reads hashes and
    #    embeddings and would return the same answer either way. Spending
    #    it on CONTEXT_MISMATCH is the difference between scene_consistency
    #    having a measured recall and reporting UNMEASURABLE.
    priority = _perception_blocked_archetypes()

    def fraud_key(image: Image) -> tuple[int, str, str]:
        archetype = archetypes.get(image.case_id, "")
        return (0 if archetype in priority else 1, image.case_id, image.image_id)

    return sorted(fraud, key=fraud_key) + sorted(sampled_clean, key=lambda i: (i.case_id, i.image_id))


def _perception_blocked_archetypes() -> set[str]:
    """
    Archetypes targeted by a check that cannot run without perception.

    Derived from the registry rather than hard-coded, so adding a
    perception-dependent check automatically promotes its archetype up
    the queue instead of needing someone to remember to edit a list here.
    """
    from src.checks import REGISTRY

    return {
        archetype
        for check in REGISTRY.values()
        if check.requires_perception
        for archetype in check.target_archetypes
    }


def _perceive_with_unavailable_retry(conn, image: Image, provider: LLMProvider) -> PerceptionRecord:
    """
    Calls perceive_image with llm.py's own retry disabled (retry_attempts=1)
    so a 503 surfaces immediately instead of after llm.py's default
    5-attempt/2s-base backoff, then applies our own short schedule
    (_UNAVAILABLE_BACKOFF_BASE_SECONDS, doubling, _UNAVAILABLE_MAX_ATTEMPTS
    attempts) - and only for a 503. Anything else (a 429, a genuine
    failure) is raised straight through on the first try; run_perception_pass
    still owns backing off and moving on for those.
    """
    delay = _UNAVAILABLE_BACKOFF_BASE_SECONDS
    last_error: Optional[Exception] = None
    for attempt in range(1, _UNAVAILABLE_MAX_ATTEMPTS + 1):
        try:
            return perceive_image(conn, image, provider, retry_attempts=1, release_transactions=True)
        except Exception as e:  # noqa: BLE001 - only a 503 is handled here, everything else re-raises below
            if not is_unavailable_error(e):
                raise
            last_error = e
            if attempt == _UNAVAILABLE_MAX_ATTEMPTS:
                break
            print(
                f"[perception] 503 UNAVAILABLE on {image.content_hash[:12]}... "
                f"(attempt {attempt}/{_UNAVAILABLE_MAX_ATTEMPTS}), retrying in {delay:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
    assert last_error is not None
    raise last_error


def run_perception_pass(
    conn,
    provider: LLMProvider,
    limit: Optional[int] = None,
    sleep_between: Optional[float] = None,
    stratified: bool = False,
    clean_sample: int = 80,
    service_unavailable_retries: int = _SERVICE_UNAVAILABLE_RETRIES,
    service_unavailable_backoff_seconds: float = _SERVICE_UNAVAILABLE_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """
    Commits after every single image, not once at the end. This is a
    long-running, must-be-resumable-overnight process: each successful
    call is real money/quota spent, and a single final commit would mean
    a crash (or the process being killed) at image 900 of 1,300 loses
    the other 899 already-paid-for results right along with it. A commit
    per image costs nothing worth worrying about next to a network round
    trip to the vision API.

    Failures are bucketed into three kinds, not one, because they mean
    three different things for scheduling an overnight run: rate_limited
    (429 - a daily quota, won't clear again until it resets, no point
    retrying this image soon), transient_unavailable (503 - exhausted
    _perceive_with_unavailable_retry's own short backoff; genuinely
    struggling, not just a one-off blip), and failed (anything else -
    auth, a malformed request, something worth actually looking at).
    """
    before = db.perception_coverage(conn)
    print(f"coverage before: {before['covered']}/{before['total']} unique images ({before['pct']:.1f}%)")
    parse_before = parse_stats()

    if stratified:
        images = select_stratified(conn, clean_sample)
        remaining = [i for i in images if not perception_record_usable(db.get_perception(conn, i.content_hash))]
        keys = max(1, len(llm._discover_keys()))
        daily = keys * FREE_TIER_DAILY_QUOTA
        days = math.ceil(len(remaining) / daily) if daily else float("inf")
        fraud_count = len(images) - min(clean_sample, len(images))
        print(
            f"stratified scope: {len(images)} images "
            f"(all fraud-case images + {min(clean_sample, len(images))} sampled clean)"
        )
        print(f"  already perceived: {len(images) - len(remaining)}   remaining: {len(remaining)}")
        print(
            f"  {keys} API key(s) configured x {FREE_TIER_DAILY_QUOTA}/day "
            f"= {daily} calls/day -> approximately {days} day(s) to finish"
        )
    else:
        images = _unique_images(conn)
    if limit is not None:
        images = images[:limit]

    succeeded = 0
    calls_skipped = 0
    rate_limited = 0
    transient_unavailable = 0
    failed = 0
    consecutive_rate_limits = 0
    consecutive_unavailable = 0
    consecutive_non_quota_failures = 0
    service_unavailable_rounds = 0
    end_reason = "completed"
    success_seconds: list[float] = []

    start = time.monotonic()

    def _postfix() -> dict[str, int]:
        return {
            "ok": succeeded,
            "skip": calls_skipped,
            "429": rate_limited,
            "503": transient_unavailable,
            "fail": failed,
        }

    progress = tqdm(images, desc="perception pass", unit="image")
    for image in progress:
        if perception_record_usable(db.get_perception(conn, image.content_hash)):
            calls_skipped += 1
            progress.set_postfix(_postfix())
            continue

        call_start = time.monotonic()
        try:
            record = _perceive_with_unavailable_retry(conn, image, provider)
        except Exception as e:  # noqa: BLE001 - a partial pass must survive to resume overnight
            if is_rate_limit_error(e) or is_quota_budget_error(e):
                rate_limited += 1
                kind = "LOCAL_QUOTA_BUDGET" if is_quota_budget_error(e) else "429 RESOURCE_EXHAUSTED"
                consecutive_rate_limits += 1
                consecutive_non_quota_failures = 0
                if is_quota_budget_error(e):
                    end_reason = "local_quota_budget_exhausted"
                    print(
                        f"\n[perception] local shared quota budget exhausted. Stopping early "
                        f"with {succeeded} image(s) perceived this run; re-run after the next "
                        f"quota day or adjust {os.getenv('GEMINI_QUOTA_BUDGET', 'outputs/quota_budget.json')}.",
                        file=sys.stderr,
                    )
                    conn.commit()
                    break
                # A 429 that survives src.llm's key rotation means every
                # configured key is spent, and a *daily* quota does not
                # come back within this run. Continuing would spend hours
                # sleeping 30s per remaining image to collect nothing:
                # measured at 20 requests/day/key, a 284-image stratified
                # pass would burn ~2 hours of backoff after the 20th call.
                # Stop, report honestly, and let the operator resume
                # tomorrow or add keys - the pass is resumable by design,
                # so stopping early costs nothing already paid for.
                if consecutive_rate_limits >= _QUOTA_EXHAUSTED_AFTER:
                    end_reason = "remote_429_quota_exhausted"
                    print(
                        f"\n[perception] {consecutive_rate_limits} consecutive 429s - every configured "
                        f"API key is out of daily quota. Stopping early with {succeeded} image(s) "
                        "perceived this run.\n"
                        "  Resume tomorrow, or add GEMINI_API_KEY_2..._10 to .env: src/llm.py "
                        "rotates on a 429, so each extra key multiplies the daily ceiling.",
                        file=sys.stderr,
                    )
                    conn.commit()
                    break
            elif is_unavailable_error(e):
                transient_unavailable += 1
                kind = f"503 UNAVAILABLE (exhausted {_UNAVAILABLE_MAX_ATTEMPTS} retries)"
                consecutive_unavailable += 1
                consecutive_non_quota_failures = 0
                # 503 is nominally transient, and for a handful of images
                # it is. But the service can also stay unavailable for
                # hours, and each image then costs the full 5/10/20/40s
                # retry ladder plus this 30s backoff before the next one
                # fails identically. Measured the hard way: a run sat for
                # 14.5 hours and completed 10 of 284 images that way,
                # which is worse than useless because it also looks like
                # progress. Same reasoning as the 429 guard - the pass is
                # resumable, so stopping costs nothing already paid for.
                if consecutive_unavailable >= _UNAVAILABLE_GIVE_UP_AFTER:
                    if service_unavailable_rounds < service_unavailable_retries:
                        service_unavailable_rounds += 1
                        print(
                            f"\n[perception] {consecutive_unavailable} consecutive 503s - the vision "
                            f"service is unavailable. Backing off "
                            f"{service_unavailable_backoff_seconds / 60:.0f} min before retry "
                            f"{service_unavailable_rounds}/{service_unavailable_retries}.",
                            file=sys.stderr,
                        )
                        conn.commit()
                        time.sleep(service_unavailable_backoff_seconds)
                        consecutive_unavailable = 0
                        progress.set_postfix(_postfix())
                        continue
                    end_reason = "service_503_unavailable_give_up"
                    print(
                        f"\n[perception] {consecutive_unavailable} consecutive 503s after "
                        f"{service_unavailable_rounds} service backoff(s). Giving up for this "
                        f"session with {succeeded} image(s) perceived; re-run to resume.",
                        file=sys.stderr,
                    )
                    conn.commit()
                    break
            else:
                failed += 1
                kind = type(e).__name__
                consecutive_non_quota_failures += 1
                log_failure(image, kind, e)
                if consecutive_non_quota_failures >= MAX_CONSECUTIVE_NON_QUOTA_FAILURES:
                    conn.commit()
                    raise RuntimeError(
                        f"{consecutive_non_quota_failures} consecutive non-quota perception "
                        f"failures; see {ERROR_LOG}"
                    ) from e
            if is_rate_limit_error(e) or is_quota_budget_error(e) or is_unavailable_error(e):
                log_failure(image, kind, e)
            print(
                f"\n[perception] {kind} ({type(e).__name__}) on {image.content_hash[:12]}... - "
                f"backing off {_ERROR_BACKOFF_SECONDS:.0f}s and continuing "
                "(this image stays uncached; re-run to retry it)",
                file=sys.stderr,
            )
            conn.commit()
            time.sleep(_ERROR_BACKOFF_SECONDS)
            progress.set_postfix(_postfix())
            continue

        if not perception_record_usable(record):
            failed += 1
            conn.commit()
            progress.set_postfix(_postfix())
            continue
        succeeded += 1
        consecutive_rate_limits = 0
        consecutive_unavailable = 0
        consecutive_non_quota_failures = 0
        success_seconds.append(time.monotonic() - call_start)
        conn.commit()
        progress.set_postfix(_postfix())
        if sleep_between:
            time.sleep(sleep_between)

    elapsed = time.monotonic() - start
    avg_success_seconds = statistics.mean(success_seconds) if success_seconds else 0.0

    parse_after = parse_stats()
    parse_delta = {k: parse_after[k] - parse_before[k] for k in parse_after}
    parse_total = sum(parse_delta.values())

    after = db.perception_coverage(conn)
    print(f"coverage after:  {after['covered']}/{after['total']} unique images ({after['pct']:.1f}%)")
    print(
        f"this run: {succeeded} succeeded, {calls_skipped} skipped (cached), "
        f"{rate_limited} rate-limited (429), {transient_unavailable} transient-unavailable (503), "
        f"{failed} failed"
    )
    if end_reason == 'completed' and failed:
        end_reason = 'completed_with_failures'
    print(f"end reason: {end_reason}")
    print(f"elapsed: {elapsed:.1f}s wall-clock, {avg_success_seconds:.2f}s/image average over {succeeded} success(es)")
    if parse_total:
        # The number that actually says whether this model's JSON is
        # trustworthy: how often the strict parse alone was enough versus
        # how often _try_parse had to fall back to regex extraction (or
        # gave up) - see parse_stats()'s docstring.
        print(
            f"parsing: {parse_delta['strict']}/{parse_total} strict, "
            f"{parse_delta['regex_extracted']}/{parse_total} needed fallback extraction, "
            f"{parse_delta['failed']}/{parse_total} failed to parse at all"
        )

    return {
        "succeeded": succeeded,
        "calls_skipped": calls_skipped,
        "rate_limited": rate_limited,
        "transient_unavailable": transient_unavailable,
        "failed": failed,
        "elapsed_seconds": elapsed,
        "avg_seconds_per_success": avg_success_seconds,
        "parse_stats": parse_delta,
        "end_reason": end_reason,
        "service_unavailable_rounds": service_unavailable_rounds,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the one-time vision perception pass.")
    parser.add_argument("--limit", type=int, default=None, help="only consider the first N unique images (test run)")
    parser.add_argument("--rpm", type=int, default=10, help="throttle to this many vision calls per minute (default 10)")
    parser.add_argument("--db-path", default="fraudlens.db", help="sqlite database path")
    parser.add_argument(
        "--stratified",
        action="store_true",
        help=(
            "spend quota where it can be measured: every image belonging to a fraud case, "
            "plus a seeded random sample of clean-case images (see --clean-sample)"
        ),
    )
    parser.add_argument(
        "--clean-sample",
        type=int,
        default=80,
        help="how many clean-case images to include under --stratified (default 80)",
    )
    parser.add_argument(
        "--service-retries",
        type=int,
        default=_SERVICE_UNAVAILABLE_RETRIES,
        help="session-level retries after five consecutive 503s (default 4)",
    )
    parser.add_argument(
        "--service-backoff-minutes",
        type=float,
        default=_SERVICE_UNAVAILABLE_BACKOFF_SECONDS / 60,
        help="minutes to wait between session-level 503 retries (default 15)",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "ollama"],
        default=None,
        help="override LLM_PROVIDER for this run only; default is .env's LLM_PROVIDER (gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "override the chosen provider's default model for this run only "
            "(e.g. gemini-flash-latest, or moondream for --provider ollama)"
        ),
    )
    return parser.parse_args(argv)


def _build_provider(provider_name: Optional[str], model: Optional[str]) -> LLMProvider:
    """
    get_provider() only chooses gemini vs ollama (from --provider or
    LLM_PROVIDER) - it doesn't take a model name, so --model is handled
    here: if given, it constructs that provider's class directly with the
    override (the same one-off pattern scripts/benchmark_perception.py
    and scripts/find_working_model.py use for Gemini specifically),
    otherwise get_provider() is exactly the right call.
    """
    if model is None:
        return get_provider(provider_name)

    choice = (provider_name or LLM_PROVIDER).strip().lower()
    if choice == "gemini":
        return GeminiProvider(model=model)
    if choice == "ollama":
        return OllamaProvider(model=model)
    raise ValueError(f"unknown provider {choice!r} - --provider (or LLM_PROVIDER) must be 'gemini' or 'ollama'")


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    os.environ.setdefault("GEMINI_QUOTA_CONSUMER", "perception")
    sleep_between = 60.0 / args.rpm if args.rpm > 0 else None

    provider = _build_provider(args.provider, args.model)
    print(f"provider: {type(provider).__name__}  model: {provider.model}")

    # Not db.session(): that only commits once, at the very end. This
    # process manages its own commits (one per image, inside
    # run_perception_pass) precisely so it survives being interrupted.
    conn = db.connect(args.db_path)
    db.init_db(conn)
    try:
        run_perception_pass(
            conn,
            provider,
            limit=args.limit,
            sleep_between=sleep_between,
            stratified=args.stratified,
            clean_sample=args.clean_sample,
            service_unavailable_retries=args.service_retries,
            service_unavailable_backoff_seconds=args.service_backoff_minutes * 60,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
