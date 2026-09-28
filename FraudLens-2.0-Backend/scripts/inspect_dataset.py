"""
scripts.inspect_dataset
========================

Diagnostic script for the synthetic case corpus, run once before any
check gets built. Its only job is to answer "did generate_dataset.py
actually produce the signals the checks are supposed to find, cleanly,
or did something silently go wrong?" - a check built against a corrupt
corpus will look correct in code review and be meaningless in
evaluation.

Reads data/generated/ground_truth.csv and the sqlite database. The
task that commissioned this script named the database data/fraudlens.db;
it actually lives at the project root (see db.py's own default and
generate_dataset.py's --db-path default) - resolve_db_path() checks
both locations so this keeps working if that ever changes.

Run with:
    python scripts/inspect_dataset.py
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image as PILImage

from src import db

DB_CANDIDATES = [Path("data/fraudlens.db"), Path("fraudlens.db")]
GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")

GAMING_BAND = (45000, 50000)  # the round-number band a real check would look for
MIN_GARAGE_CLAIMS = 5

WIDTH_BUCKET_LABELS = ["<200px", "200-299px", "300-399px", "400-599px", "600px+"]


def resolve_db_path() -> Path:
    for candidate in DB_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"no database found at any of: {', '.join(str(c) for c in DB_CANDIDATES)} - "
        "run `python -m src.generate_dataset` first"
    )


def load_ground_truth() -> list[dict[str, Any]]:
    if not GROUND_TRUTH_CSV.exists():
        raise FileNotFoundError(f"{GROUND_TRUTH_CSV} not found - run `python -m src.generate_dataset` first")
    with open(GROUND_TRUTH_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
# Report 1 - garage threshold-gaming separation
# ---------------------------------------------------------------------------


def report_garage_gaming(conn) -> None:
    _header("REPORT 1 - Garage threshold-gaming separation")
    lo, hi = GAMING_BAND

    rows = conn.execute(
        "SELECT garage_id, claim_amount FROM cases WHERE agent_type = 'claims' AND claim_amount IS NOT NULL"
    ).fetchall()
    by_garage: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_garage[row["garage_id"]].append(row["claim_amount"])

    stats = []
    for garage_id, amounts in by_garage.items():
        if len(amounts) < MIN_GARAGE_CLAIMS:
            continue
        band_count = sum(1 for a in amounts if lo <= a <= hi)
        stats.append({
            "garage_id": garage_id,
            "count": len(amounts),
            "avg": statistics.mean(amounts),
            "band_count": band_count,
            "pct": 100.0 * band_count / len(amounts),
        })
    stats.sort(key=lambda s: s["pct"], reverse=True)

    band_label = f"in {lo:,}-{hi:,}"
    print(f"{'garage_id':<14} {'claims':>7} {'avg amount':>12} {band_label:>18} {'pct':>7}")
    for s in stats:
        print(f"{s['garage_id']:<14} {s['count']:>7} {s['avg']:>12,.0f} {s['band_count']:>18} {s['pct']:>6.1f}%")

    if len(stats) < 7:
        print(f"\nNote: only {len(stats)} garage(s) meet the >= {MIN_GARAGE_CLAIMS}-claims threshold - "
              "not enough to assess a top-six/rest split")
        return

    gaps = [stats[i]["pct"] - stats[i + 1]["pct"] for i in range(len(stats) - 1)]
    rank6_rank7_gap = gaps[5]
    is_largest_gap = rank6_rank7_gap >= max(gaps) - 1e-9
    print(f"\nNote: rank 6 ({stats[5]['garage_id']}, {stats[5]['pct']:.1f}%) vs "
          f"rank 7 ({stats[6]['garage_id']}, {stats[6]['pct']:.1f}%) -> gap = {rank6_rank7_gap:.1f} pp")
    if is_largest_gap:
        print("      top six ARE visibly separated from the rest - this is the single largest "
              "adjacent gap anywhere in the ranking")
    else:
        print(f"      top six are NOT clearly separated - a larger gap ({max(gaps):.1f} pp) exists "
              "elsewhere in the ranking, so a simple top-6 cut would misclassify some garages")


# ---------------------------------------------------------------------------
# Report 2 - archetype health
# ---------------------------------------------------------------------------


def report_archetype_health(conn, ground_truth: list[dict]) -> None:
    _header("REPORT 2 - Archetype health")

    images_per_case = Counter(row["case_id"] for row in conn.execute("SELECT case_id FROM images").fetchall())

    by_archetype: dict[str, dict] = defaultdict(lambda: {"cases": 0, "images": 0, "zero_image_cases": 0, "amounts": []})
    for row in ground_truth:
        bucket = by_archetype[row["archetype"]]
        bucket["cases"] += 1
        bucket["images"] += images_per_case.get(row["case_id"], 0)
        if images_per_case.get(row["case_id"], 0) == 0:
            bucket["zero_image_cases"] += 1
        if row["amount"]:
            bucket["amounts"].append(float(row["amount"]))

    print(f"{'archetype':<20}{'cases':>7}{'images':>8}{'zero-img':>10}{'avg amount':>14}")
    for archetype in sorted(by_archetype):
        b = by_archetype[archetype]
        avg_str = f"{statistics.mean(b['amounts']):,.0f}" if b["amounts"] else "n/a"
        print(f"{archetype:<20}{b['cases']:>7}{b['images']:>8}{b['zero_image_cases']:>10}{avg_str:>14}")

    print()
    any_unexpected = False
    for archetype in sorted(by_archetype):
        zero = by_archetype[archetype]["zero_image_cases"]
        if not zero:
            continue
        if archetype == "AI_GENERATED":
            print(f"FLAG  {archetype}: {zero} case(s) with zero images - expected, pending "
                  "data/ai_generated/ backfill (see generate_dataset.py's warning)")
        else:
            any_unexpected = True
            print(f"FLAG  {archetype}: {zero} case(s) with zero images - UNEXPECTED, investigate")
    if not any_unexpected:
        print("(no unexpected zero-image archetypes)")


# ---------------------------------------------------------------------------
# Report 3 - image integrity
# ---------------------------------------------------------------------------


def report_image_integrity(conn, ground_truth: list[dict]) -> None:
    _header("REPORT 3 - Image integrity")

    rows = conn.execute("SELECT content_hash, case_id FROM images").fetchall()
    by_hash: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_hash[row["content_hash"]].append(row["case_id"])
    duplicate_groups = {h: cids for h, cids in by_hash.items() if len(cids) > 1}

    print(f"total images:     {len(rows)}")
    print(f"unique sha256:    {len(by_hash)}")
    print(f"duplicate hashes: {len(duplicate_groups)}")

    archetype_by_case = {row["case_id"]: row["archetype"] for row in ground_truth}

    all_ok = True
    if duplicate_groups:
        print(f"\n{'content_hash':<14}{'case_ids':<28}{'archetypes'}")
        for content_hash, case_ids in duplicate_groups.items():
            archetypes = [archetype_by_case.get(c, "?") for c in case_ids]
            ok = "REUSE" in archetypes
            all_ok = all_ok and ok
            marker = "" if ok else "  <-- NO REUSE CASE IN THIS GROUP"
            print(f"{content_hash[:12]:<14}{', '.join(case_ids):<28}{', '.join(archetypes)}{marker}")

    verdict = "PASS" if all_ok else "FAIL"
    print(f"\n{verdict} - every duplicate hash includes at least one REUSE case"
          + ("" if duplicate_groups else " (no duplicates found)"))


# ---------------------------------------------------------------------------
# Report 4 - resolution distribution
# ---------------------------------------------------------------------------


def _width_bucket(width: int) -> str:
    if width < 200:
        return WIDTH_BUCKET_LABELS[0]
    if width < 300:
        return WIDTH_BUCKET_LABELS[1]
    if width < 400:
        return WIDTH_BUCKET_LABELS[2]
    if width < 600:
        return WIDTH_BUCKET_LABELS[3]
    return WIDTH_BUCKET_LABELS[4]


def report_resolution_distribution(conn) -> None:
    _header("REPORT 4 - Resolution distribution (image width)")
    print("Why this matters: plate OCR accuracy depends on resolution - we plan to report it "
          "as a covariate, not pretend every image gives OCR an equal chance.\n")

    paths = [row["path"] for row in conn.execute("SELECT path FROM images").fetchall()]
    buckets: Counter = Counter()
    unreadable = 0
    for path in paths:
        try:
            with PILImage.open(path) as img:
                buckets[_width_bucket(img.size[0])] += 1
        except Exception:
            unreadable += 1

    total = sum(buckets.values())
    print(f"{'bucket':<12}{'count':>8}{'pct':>9}")
    for label in WIDTH_BUCKET_LABELS:
        n = buckets.get(label, 0)
        pct = 100.0 * n / total if total else 0.0
        print(f"{label:<12}{n:>8}{pct:>8.1f}%")
    if unreadable:
        print(f"\n({unreadable} image path(s) could not be opened and were excluded)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    db_path = resolve_db_path()
    ground_truth = load_ground_truth()
    print(f"Inspecting {db_path} and {GROUND_TRUTH_CSV} ({len(ground_truth)} ground-truth rows)")

    conn = db.connect(db_path)
    try:
        report_garage_gaming(conn)
        report_archetype_health(conn, ground_truth)
        report_image_integrity(conn, ground_truth)
        report_resolution_distribution(conn)
    finally:
        conn.close()
    print()


if __name__ == "__main__":
    main()
