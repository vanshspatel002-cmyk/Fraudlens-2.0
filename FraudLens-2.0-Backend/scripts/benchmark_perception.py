"""
scripts.benchmark_perception
=============================

Times the vision API on a handful of never-before-perceived images to find
the real achievable throughput, before src/perception.py's full ~1,326-image
pass gets scheduled. Two things distinguish this from a normal perception
run:

- No throttling and no sleep. src/perception.py's --rpm flag and
  src/llm.py's exponential backoff both exist to be gentle with the API;
  this script deliberately switches both off (conn=None bypasses the cache
  so every call is real, retry_attempts=1 disables the backoff so a 429
  surfaces immediately instead of after 2+4+8+16s of sleeping) because the
  whole point is to find the ceiling the API itself imposes, not the one we
  impose on ourselves.
- A rate limit is not a failure to be retried past, it's the answer to the
  question this script exists to ask. It's caught separately from real
  errors and reported first, because "how many calls before the ceiling,
  and how long did the API ask us to wait" is the single number the full
  pass's schedule depends on.

Every call made here is a real, billed API call, so its result is still
parsed and saved to perception_records exactly like a normal perception
pass would - a benchmark run must not be a wasted run.

Run with:
    python scripts/benchmark_perception.py
    python scripts/benchmark_perception.py --model gemini-2.0-flash --limit 3

--model overrides GEMINI_MODEL from .env for this run only (same one-off
pattern as the earlier GEMINI_MODEL=... override used to verify the
google-genai migration) - handy for comparing which free-tier model has
quota headroom without touching the project's configured default.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src.llm import GeminiProvider, is_rate_limit_error
from src.models import Image, PerceptionRecord
from src.perception import PERCEPTION_PROMPT, _record_from_parsed, _try_parse, _unique_images

DB_CANDIDATES = [Path("data/fraudlens.db"), Path("fraudlens.db")]
OUTPUT_DIR = Path("outputs")

DEFAULT_SAMPLE_SIZE = 10
FULL_CORPUS_SIZE = 1_326

# Rough single-session/overnight/multi-day cutoffs for the verdict line.
# Not precise budgets - just enough to tell "run it now", "kick it off
# tonight", and "this needs a schedule spanning days" apart at a glance.
SINGLE_SESSION_HOURS = 2.0
OVERNIGHT_HOURS = 16.0


def resolve_db_path() -> Path:
    for candidate in DB_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"no database found at any of: {', '.join(str(c) for c in DB_CANDIDATES)} - "
        "run `python -m src.generate_dataset` first"
    )


# ---------------------------------------------------------------------------
# Image selection
# ---------------------------------------------------------------------------


def _images_without_perception(conn, limit: int) -> list[Image]:
    """
    Up to `limit` images whose content hash has no perception_records row
    yet - the distinct-sha256-left-joined-against-perception set, built
    from the same one-Image-per-hash dedup src/perception.py's own batch
    pass uses (_unique_images), so this benchmark never pays twice for a
    photo that already has a cached perception result.
    """
    return [img for img in _unique_images(conn) if db.get_perception(conn, img.content_hash) is None][:limit]


# ---------------------------------------------------------------------------
# Error inspection - no google.genai import needed, just the plain
# attributes APIError already exposes (code/message/details) on whatever
# exception is_rate_limit_error() told us is a 429.
# ---------------------------------------------------------------------------


def _extract_retry_delay_seconds(error: Exception) -> Optional[float]:
    """
    Pull the server-suggested backoff out of a 429's error body, if it sent
    one. Gemini's RESOURCE_EXHAUSTED responses usually attach a RetryInfo
    with a retryDelay like "37s" among the error's `details` list. Returns
    None rather than a guess if the shape isn't there - a benchmark that
    invents a number the API never gave us is worse than one that admits
    it doesn't know.
    """
    body = getattr(error, "details", None)
    if not isinstance(body, dict):
        return None
    error_body = body.get("error", body)
    for item in error_body.get("details") or []:
        delay = item.get("retryDelay") if isinstance(item, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                continue
    return None


def _extract_quota_info(error: Exception) -> Optional[dict[str, Any]]:
    """
    Pull the named quota out of a 429's error body - the whole reason this
    script is being pointed at four different models is to read this field
    off each one and see which allowance is largest. Gemini attaches a
    QuotaFailure with a quotaId (e.g. "GenerateRequestsPerDayPerProjectPer
    Model-FreeTier") and a quotaValue (e.g. "20") among the error's
    `details` list; returns None if that shape isn't there rather than
    guessing.
    """
    body = getattr(error, "details", None)
    if not isinstance(body, dict):
        return None
    error_body = body.get("error", body)
    for item in error_body.get("details") or []:
        if not isinstance(item, dict):
            continue
        violations = item.get("violations")
        if not violations:
            continue
        v = violations[0]
        return {
            "quota_id": v.get("quotaId"),
            "quota_metric": v.get("quotaMetric"),
            "quota_value": v.get("quotaValue"),
        }
    return None


# ---------------------------------------------------------------------------
# One timed call
# ---------------------------------------------------------------------------


def _time_one_call(conn, provider: GeminiProvider, image: Image) -> dict[str, Any]:
    """
    Time a single, uncached, unretried vision call. On success the parsed
    result is saved to perception_records via the same parse path
    src/perception.py's perceive_image() uses, so this call counts toward
    real coverage even though it's also a timing sample.
    """
    start = time.perf_counter()
    try:
        response = provider.describe_image(image.path, PERCEPTION_PROMPT, conn=None, retry_attempts=1)
    except Exception as e:  # noqa: BLE001 - classify below, never crash the benchmark
        seconds = time.perf_counter() - start
        if is_rate_limit_error(e):
            return {
                "content_hash": image.content_hash,
                "seconds": seconds,
                "outcome": "rate_limited",
                "error": str(e),
                "retry_delay_seconds": _extract_retry_delay_seconds(e),
                "quota": _extract_quota_info(e),
            }
        return {
            "content_hash": image.content_hash,
            "seconds": seconds,
            "outcome": "failed",
            "error": str(e),
            "retry_delay_seconds": None,
            "quota": None,
        }

    seconds = time.perf_counter() - start

    parsed, parse_error = _try_parse(response.text)
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
        "content_hash": image.content_hash,
        "seconds": seconds,
        "outcome": "success",
        "error": None,
        "retry_delay_seconds": None,
        "quota": None,
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _format_hm(hours: float) -> str:
    total_minutes = round(hours * 60)
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m}m"


def _verdict(projected_hours: float, hit_rate_limit: bool, sample_size: int) -> str:
    if hit_rate_limit:
        return (
            "NEEDS TO BE SPLIT ACROSS MULTIPLE DAYS - a rate limit fired inside a "
            f"{sample_size}-image sample, so the full pass's real duration is bounded "
            "by the API's quota resets, not by per-call latency; the per-call "
            "projection below is optimistic and should not be used to schedule this."
        )
    if projected_hours <= SINGLE_SESSION_HOURS:
        return "FEASIBLE IN A SINGLE SESSION at the observed per-call rate."
    if projected_hours <= OVERNIGHT_HOURS:
        return "NEEDS AN OVERNIGHT RUN at the observed per-call rate."
    return "NEEDS TO BE SPLIT ACROSS MULTIPLE DAYS at the observed per-call rate."


def summarize(timings: list[dict[str, Any]], sample_size: int) -> dict[str, Any]:
    successes = [t for t in timings if t["outcome"] == "success"]
    failures = [t for t in timings if t["outcome"] == "failed"]
    rate_limited = [t for t in timings if t["outcome"] == "rate_limited"]

    success_seconds = [t["seconds"] for t in successes]
    calls_before_rate_limit = 0
    for t in timings:
        if t["outcome"] == "rate_limited":
            break
        calls_before_rate_limit += 1

    first_retry_delay = next((t["retry_delay_seconds"] for t in rate_limited if t["retry_delay_seconds"]), None)
    named_quota = next((t["quota"] for t in rate_limited if t["quota"]), None)

    if success_seconds:
        avg_seconds = statistics.mean(success_seconds)
        images_per_minute = 60.0 / avg_seconds
        projected_hours = FULL_CORPUS_SIZE * avg_seconds / 3600.0
    else:
        avg_seconds = 0.0
        images_per_minute = 0.0
        projected_hours = float("inf")

    return {
        "successful_calls": len(successes),
        "failed_calls": len(failures),
        "rate_limited_calls": len(rate_limited),
        "calls_before_first_rate_limit": calls_before_rate_limit if rate_limited else None,
        "first_rate_limit_retry_delay_seconds": first_retry_delay,
        "named_quota": named_quota,
        "min_seconds": min(success_seconds) if success_seconds else None,
        "median_seconds": statistics.median(success_seconds) if success_seconds else None,
        "max_seconds": max(success_seconds) if success_seconds else None,
        "avg_seconds_per_image": avg_seconds if success_seconds else None,
        "effective_images_per_minute": images_per_minute if success_seconds else None,
        "projected_full_pass_hours": projected_hours if success_seconds else None,
        "full_corpus_size": FULL_CORPUS_SIZE,
        "verdict": _verdict(projected_hours, hit_rate_limit=bool(rate_limited), sample_size=sample_size)
        if success_seconds
        else "INCONCLUSIVE - no call succeeded, see failures/rate limits above.",
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(
        f"successful: {summary['successful_calls']}   "
        f"failed: {summary['failed_calls']}   "
        f"rate-limited: {summary['rate_limited_calls']}"
    )

    if summary["rate_limited_calls"]:
        wait = summary["first_rate_limit_retry_delay_seconds"]
        wait_str = f"{wait:.0f}s" if wait is not None else "unspecified (API gave no retryDelay)"
        print(
            f"\n*** rate limit fired after {summary['calls_before_first_rate_limit']} "
            f"successful call(s) - API asked us to wait {wait_str} ***"
        )
        quota = summary["named_quota"]
        if quota:
            print(f"*** quota named in the 429: {quota['quota_id']} = {quota['quota_value']} ***")

    if summary["avg_seconds_per_image"] is not None:
        print(
            f"\nmin / median / max seconds per call: "
            f"{summary['min_seconds']:.2f} / {summary['median_seconds']:.2f} / {summary['max_seconds']:.2f}"
        )
        print(f"average seconds per image:  {summary['avg_seconds_per_image']:.2f}s")
        print(f"effective images/minute:    {summary['effective_images_per_minute']:.2f}")
        print(
            f"projected full pass ({summary['full_corpus_size']} images): "
            f"{_format_hm(summary['projected_full_pass_hours'])}"
        )

    print(f"\nverdict: {summary['verdict']}")


# ---------------------------------------------------------------------------
# CLI / Main
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(model: str) -> str:
    return _SLUG_RE.sub("-", model.lower()).strip("-")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark raw vision-API throughput per model.")
    parser.add_argument(
        "--model",
        default=None,
        help="override GEMINI_MODEL for this run only (e.g. gemini-2.0-flash); default is .env's GEMINI_MODEL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help=f"how many never-before-perceived images to time (default {DEFAULT_SAMPLE_SIZE})",
    )
    parser.add_argument("--db-path", default=None, help="sqlite database path (default: auto-detect)")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else resolve_db_path()
    conn = db.connect(db_path)
    db.init_db(conn)

    try:
        images = _images_without_perception(conn, args.limit)
        if not images:
            print("no images without a perception record - nothing to benchmark")
            return
        if len(images) < args.limit:
            print(f"only {len(images)} image(s) without a perception record available (wanted {args.limit})")

        provider = GeminiProvider(model=args.model) if args.model else GeminiProvider()
        print(f"model: {provider.model}")
        timings: list[dict[str, Any]] = []

        for i, image in enumerate(images, start=1):
            result = _time_one_call(conn, provider, image)
            timings.append(result)

            prefix = image.content_hash[:12]
            if result["outcome"] == "success":
                label = "OK"
            elif result["outcome"] == "rate_limited":
                label = "RATE LIMITED"
            else:
                label = f"FAILED ({result['error']})"
            print(f"[{i}/{len(images)}] {prefix}...  {result['seconds']:.2f}s  {label}")

        summary = summarize(timings, sample_size=len(images))
        print_summary(summary)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"perception_benchmark_{_slugify(provider.model)}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"model": provider.model, "timings": timings, "summary": summary}, f, indent=2)
        print(f"\nraw timings saved to {output_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
