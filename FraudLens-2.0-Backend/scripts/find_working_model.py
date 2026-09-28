"""
scripts.find_working_model
============================

Surveys several Gemini model names in one pass to find which one actually
has usable free-tier quota today, before src/perception.py's full ~1,326-
image pass gets scheduled against whichever model .env happens to name.
Model names on the free tier churn - see the 404s scripts/benchmark_
perception.py turned up for gemini-2.0-flash, gemini-2.5-flash, and
gemini-1.5-flash on 2026-08-18 - so "does this model still exist" and
"does it have quota" both need answering, and they're different questions:
a 404 means the name is dead, a 429 means the name is alive but exhausted,
and only a 429's error body actually names the daily limit we're trying to
learn.

3 calls per model, retry_attempts=1 (see scripts/benchmark_perception.py's
module docstring for why - a 429 must surface immediately, not after 2s+
of src/llm.py's own backoff, or a 7-model x 3-call survey turns into
minutes of pure sleeping for no new information). This script is a fast
survey, not an accurate per-call timing instrument - that's what
benchmark_perception.py --model is for, once this has picked a winner.

A model having quota isn't enough on its own: perception depends on the
model actually returning parseable structured JSON (src/perception.py's
PERCEPTION_PROMPT), so every successful call here is also checked against
that same parse path before being counted as genuinely usable. And since
every successful call is a real, billed API call, its result is saved to
perception_records exactly like a normal perception pass would - a survey
run must not be a wasted run either.

Run with:
    python scripts/find_working_model.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src.llm import GeminiProvider, is_not_found_error, is_rate_limit_error
from src.models import Image, PerceptionRecord
from src.perception import PERCEPTION_PROMPT, _record_from_parsed, _try_parse, _unique_images
from scripts.benchmark_perception import (
    _extract_quota_info,
    _extract_retry_delay_seconds,
    _images_without_perception,
    resolve_db_path,
)

# Order matters only for the printed log, not the ranking - oldest/most
# likely-retired first, newest/most-likely-to-work last, so a human
# skimming the live output sees the interesting result near the end.
MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-flash-latest",
]

CALLS_PER_MODEL = 3
FULL_CORPUS_SIZE = 1_326
OUTPUT_PATH = Path("outputs/model_survey.json")


# ---------------------------------------------------------------------------
# One call, one model
# ---------------------------------------------------------------------------


def _call_once(conn, provider: GeminiProvider, image: Image) -> dict[str, Any]:
    """
    One uncached (conn=None), unretried (retry_attempts=1) vision call,
    classified into exactly one of: success / rate_limited / not_found /
    error. On success the response is run through the same parse path
    src/perception.py's perceive_image() uses, both to decide json_valid
    and so the paid call still lands in perception_records.
    """
    start = time.perf_counter()
    try:
        response = provider.describe_image(image.path, PERCEPTION_PROMPT, conn=None, retry_attempts=1)
    except Exception as e:  # noqa: BLE001 - classified below, never crash the survey
        seconds = time.perf_counter() - start
        if is_not_found_error(e):
            return {"outcome": "not_found", "seconds": seconds, "error": str(e), "quota": None}
        if is_rate_limit_error(e):
            return {
                "outcome": "rate_limited",
                "seconds": seconds,
                "error": str(e),
                "quota": _extract_quota_info(e),
                "retry_delay_seconds": _extract_retry_delay_seconds(e),
            }
        return {"outcome": "error", "seconds": seconds, "error": str(e), "quota": None}

    seconds = time.perf_counter() - start
    parsed, parse_error = _try_parse(response.text)
    json_valid = parsed is not None

    if parsed is not None:
        record = _record_from_parsed(image.content_hash, provider.model, parsed, response.text)
    else:
        record = PerceptionRecord(
            content_hash=image.content_hash,
            source=provider.model,
            anomaly_notes=f"perception parse failure: {parse_error}",
            raw_response={"text": response.text, "error": parse_error},
        )
    db.save_perception(conn, record)
    conn.commit()

    return {
        "outcome": "success",
        "seconds": seconds,
        "error": None,
        "quota": None,
        "json_valid": json_valid,
        "parse_error": parse_error,
    }


def survey_model(conn, model: str, images: list[Image]) -> dict[str, Any]:
    print(f"\n--- {model} ---")
    attempts: list[dict[str, Any]] = []
    for i, image in enumerate(images, start=1):
        provider = GeminiProvider(model=model)
        result = _call_once(conn, provider, image)
        attempts.append(result)

        if result["outcome"] == "success":
            valid = "valid JSON" if result["json_valid"] else f"INVALID JSON ({result['parse_error']})"
            label = f"OK ({valid})"
        elif result["outcome"] == "not_found":
            label = "NOT FOUND (model retired/renamed)"
        elif result["outcome"] == "rate_limited":
            quota = result["quota"]
            quota_str = f", {quota['quota_id']}={quota['quota_value']}" if quota else ""
            label = f"RATE LIMITED{quota_str}"
        else:
            label = f"ERROR ({result['error']})"
        print(f"  [{i}/{len(images)}] {image.content_hash[:12]}...  {result['seconds']:.2f}s  {label}")

    return _summarize_model(model, attempts)


def _summarize_model(model: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [a for a in attempts if a["outcome"] == "success"]
    not_found = [a for a in attempts if a["outcome"] == "not_found"]
    rate_limited = [a for a in attempts if a["outcome"] == "rate_limited"]
    errors = [a for a in attempts if a["outcome"] == "error"]

    if successes:
        status = "success"
    elif not_found and len(not_found) == len(attempts):
        status = "not_found"
    elif rate_limited:
        status = "rate_limited"
    else:
        status = "error"

    success_seconds = [a["seconds"] for a in successes]
    valid_count = sum(1 for a in successes if a["json_valid"])

    quota = next((a["quota"] for a in rate_limited if a["quota"]), None)

    return {
        "model": model,
        "status": status,
        "successful_calls": len(successes),
        "not_found_calls": len(not_found),
        "rate_limited_calls": len(rate_limited),
        "error_calls": len(errors),
        "avg_seconds": statistics.mean(success_seconds) if success_seconds else None,
        "json_valid_count": valid_count,
        "json_valid_of": len(successes),
        "quota_id": quota["quota_id"] if quota else None,
        "quota_value": quota["quota_value"] if quota else None,
        "attempts": attempts,
    }


# ---------------------------------------------------------------------------
# Ranking, report, recommendation
# ---------------------------------------------------------------------------

_STATUS_RANK = {"success": 0, "rate_limited": 1, "error": 2, "not_found": 3}


def _sort_key(result: dict[str, Any]) -> tuple:
    status_rank = _STATUS_RANK[result["status"]]
    # Within "success", prefer fully-JSON-valid models, then higher known
    # daily quota (only known if a 429 happened to fire after some
    # successes used it up), then lower latency.
    json_ok = 0 if (result["json_valid_of"] and result["json_valid_count"] == result["json_valid_of"]) else 1
    quota_value = result["quota_value"]
    try:
        quota_rank = -int(quota_value) if quota_value is not None else 0
    except ValueError:
        quota_rank = 0
    avg = result["avg_seconds"] if result["avg_seconds"] is not None else float("inf")
    return (status_rank, json_ok, quota_rank, avg)


def print_table(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 92)
    print("RESULTS (ranked)")
    print("=" * 92)
    header = f"{'model':<26}{'status':<14}{'daily limit':<14}{'avg sec':<10}{'json valid':<12}"
    print(header)
    print("-" * 92)
    for r in results:
        limit = r["quota_value"] if r["quota_value"] is not None else ("-" if r["status"] != "success" else "unknown")
        avg = f"{r['avg_seconds']:.2f}" if r["avg_seconds"] is not None else "-"
        if r["json_valid_of"]:
            valid = f"{r['json_valid_count']}/{r['json_valid_of']}"
        else:
            valid = "n/a"
        print(f"{r['model']:<26}{r['status']:<14}{str(limit):<14}{avg:<10}{valid:<12}")


def _projected_days(quota_per_day: int, keys: int) -> float:
    calls_per_day = quota_per_day * keys
    return FULL_CORPUS_SIZE / calls_per_day if calls_per_day else float("inf")


def print_recommendation(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 92)
    usable = [
        r for r in results if r["status"] == "success" and r["json_valid_count"] == r["json_valid_of"]
    ]
    if not usable:
        # No model both succeeded and produced fully valid JSON on every
        # call - fall back to any model that at least succeeded, so the
        # recommendation isn't silent just because one sample call had
        # noisy JSON.
        usable = [r for r in results if r["status"] == "success"]

    if not usable:
        print("RECOMMENDATION: none of the surveyed models have usable free-tier quota right now.")
        return

    best = usable[0]
    quota_value = best["quota_value"]

    if quota_value is None:
        print(
            f"RECOMMENDATION: {best['model']} - all {best['successful_calls']} call(s) succeeded with valid "
            f"JSON, but its daily cap was never observed in this {CALLS_PER_MODEL}-call sample (no 429 fired). "
            "Cannot project full-pass duration without a known limit - check "
            "https://ai.dev/rate-limit for the real number, or run scripts/benchmark_perception.py "
            f"--model {best['model']} with a higher --limit to try to surface it."
        )
        return

    try:
        limit = int(quota_value)
    except ValueError:
        print(f"RECOMMENDATION: {best['model']} - quota value '{quota_value}' wasn't a plain integer, can't project.")
        return

    one_key_days = _projected_days(limit, keys=1)
    three_key_days = _projected_days(limit, keys=3)
    print(
        f"RECOMMENDATION: {best['model']} - daily limit {limit} ({best['quota_id']}), "
        f"avg {best['avg_seconds']:.2f}s/call, {best['json_valid_count']}/{best['json_valid_of']} valid JSON.\n"
        f"  Full {FULL_CORPUS_SIZE}-image pass: ~{one_key_days:.1f} day(s) on one API key, "
        f"~{three_key_days:.1f} day(s) split across three."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    db_path = resolve_db_path()
    conn = db.connect(db_path)
    db.init_db(conn)

    try:
        results: list[dict[str, Any]] = []
        for model in MODELS:
            images = _images_without_perception(conn, CALLS_PER_MODEL)
            if not images:
                print(f"\n--- {model} ---\nno images without a perception record left - skipping")
                continue
            if len(images) < CALLS_PER_MODEL:
                print(f"only {len(images)} unperceived image(s) left (wanted {CALLS_PER_MODEL})")
            results.append(survey_model(conn, model, images))

        ranked = sorted(results, key=_sort_key)
        print_table(ranked)
        print_recommendation(ranked)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"models": results, "ranked_order": [r["model"] for r in ranked]}, f, indent=2)
        print(f"\nraw results saved to {OUTPUT_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
