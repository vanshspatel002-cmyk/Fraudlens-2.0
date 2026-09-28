"""
scripts.evaluate_checks
========================

Scores src/checks against the synthetic corpus's ground truth. Reads
data/generated/ground_truth.csv (the answer key) and fraudlens.db (what
the checks actually see) - see src/generate_dataset.py's module
docstring for why those are kept strictly separate.

--------------------------------------------------------------------
Why a duplicate is scored on the PAIR, not on one case
--------------------------------------------------------------------
InternalDuplicateCheck answers "does this image appear in another case
in the corpus?". That is a property of a *pair* of cases, and it is
symmetric: if case A and case B share a photo, the check fires on A
when scoring A, and on B when scoring B. Both firings are correct - the
image genuinely does appear twice, and that is a fact a human reviewer
needs in front of them regardless of which case they are looking at.

What the check cannot answer, and must not pretend to, is *which member
of the pair is the fraudulent one*. When a REUSE case steals a photo
from an earlier legitimate claim, the honest claimant's case is flagged
too - not because the check is wrong, but because their photo really is
now in two claims. Deciding that the earlier case is the victim and the
later one is the fraud requires context the check has no access to
(claim timing, claimant history, adjuster judgement). That determination
is a human decision, by design: see models.py's Recommendation enum,
which structurally cannot auto-deny a claim.

Scoring that treats the victim's flag as a false positive would
therefore be measuring the wrong thing - it would penalise the check for
correctly reporting a true fact, and would push toward "fixes" that
suppress real duplicate evidence. So this script splits flags on clean
cases into two buckets by looking up the *matched* case's archetype:

  - matched case is REUSE / EXTERNAL_SOURCING -> pair_victim_flag.
    Correct behaviour. The clean case is the other half of a genuine
    duplicate pair; a human decides which half is fraudulent.
  - matched case is anything else -> false_positive. Two unrelated
    cases got linked, which is the error rate that actually matters.

Run with:
    python scripts/evaluate_checks.py
    python scripts/evaluate_checks.py --limit 50   # quick smoke run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import db
from src.checks import REGISTRY, run_checks
from src.models import Verdict

DB_CANDIDATES = [Path("data/fraudlens.db"), Path("fraudlens.db")]
GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")

DUPLICATE_CHECK_ID = "internal_duplicate"

# Width buckets, matching the convention scripts/inspect_dataset.py's
# resolution report already uses (WIDTH_BUCKET_LABELS there), so the two
# reports describe the corpus the same way. Width specifically, not min
# side - stated explicitly because MIN_SIDE_PX governs curation and the
# two are easy to conflate.
RESOLUTION_BUCKETS = ((0, 200, "<200px"), (200, 300, "200-299px"), (300, 400, "300-399px"), (400, 10 ** 9, "400px+"))
AI_RESOLUTION_OUTPUT = Path("outputs/ai_detection_by_resolution.json")
PLATE_RESOLUTION_OUTPUT = Path("outputs/plate_ocr_by_resolution.json")

# Minimum images in a bucket before it is allowed to carry a trend
# claim, and the percentage-point spread required to call a trend real.
# Same guard for every resolution breakdown - a 2-image bucket swinging
# 50% is noise, and saying otherwise in a report is worse than saying
# nothing.
MIN_BUCKET_FOR_TREND = 10
TREND_DELTA_PP = 10.0

# Archetypes that, by construction, place the same (or a near-identical)
# image into a second case - so a clean case matching one of these is the
# innocent half of a real duplicate pair, not a spurious link. See the
# module docstring.
PAIRED_FRAUD_ARCHETYPES = ("REUSE", "EXTERNAL_SOURCING")


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


def _concern_findings(conn, case_id: str) -> list:
    case = db.get_case(conn, case_id)
    if case is None:
        return []
    findings = run_checks(conn, case, check_ids=[DUPLICATE_CHECK_ID])
    return [f for f in findings if f.verdict == Verdict.CONCERN]


def evaluate_duplicate(conn, ground_truth: list[dict[str, Any]], limit: Optional[int] = None) -> dict[str, Any]:
    archetype_by_case = {row["case_id"]: row["archetype"] for row in ground_truth}

    clean_ids = [row["case_id"] for row in ground_truth if row["archetype"] == "CLEAN"]
    paired_fraud_ids = [row["case_id"] for row in ground_truth if row["archetype"] in PAIRED_FRAUD_ARCHETYPES]
    if limit is not None:
        clean_ids = clean_ids[:limit]
        paired_fraud_ids = paired_fraud_ids[:limit]

    false_positives: list[dict[str, Any]] = []
    pair_victim_flags: list[dict[str, Any]] = []

    for case_id in clean_ids:
        for finding in _concern_findings(conn, case_id):
            matched_id = finding.evidence.get("matched_case_id")
            matched_archetype = archetype_by_case.get(matched_id, "UNKNOWN")
            record = {
                "case_id": case_id,
                "matched_case_id": matched_id,
                "matched_archetype": matched_archetype,
                "hamming_distance": finding.evidence.get("hamming_distance"),
                "cosine_similarity": finding.evidence.get("cosine_similarity"),
            }
            if matched_archetype in PAIRED_FRAUD_ARCHETYPES:
                pair_victim_flags.append(record)
            else:
                false_positives.append(record)

    # The other half of the same pairs: the fraud case itself. Scored
    # separately from the victim flags above precisely because these are
    # the ones a reviewer would (with the ground truth in hand) call the
    # fraudulent member - but the check makes no such claim on its own.
    fraud_caught: list[str] = []
    fraud_missed: list[str] = []
    caught_by_archetype: Counter = Counter()
    total_by_archetype: Counter = Counter()
    for case_id in paired_fraud_ids:
        archetype = archetype_by_case[case_id]
        total_by_archetype[archetype] += 1
        if _concern_findings(conn, case_id):
            fraud_caught.append(case_id)
            caught_by_archetype[archetype] += 1
        else:
            fraud_missed.append(case_id)

    return {
        "clean_evaluated": len(clean_ids),
        "paired_fraud_evaluated": len(paired_fraud_ids),
        "false_positives": false_positives,
        "pair_victim_flags": pair_victim_flags,
        "fraud_caught": fraud_caught,
        "fraud_missed": fraud_missed,
        "caught_by_archetype": caught_by_archetype,
        "total_by_archetype": total_by_archetype,
        "archetype_by_case": archetype_by_case,
    }


def print_report(results: dict[str, Any]) -> None:
    clean_n = results["clean_evaluated"]
    fraud_n = results["paired_fraud_evaluated"]
    fp = results["false_positives"]
    victims = results["pair_victim_flags"]
    caught = results["fraud_caught"]

    print("\n" + "=" * 78)
    print(f"INTERNAL DUPLICATE CHECK - evaluated {clean_n} clean, {fraud_n} paired-fraud cases")
    print("=" * 78)

    fp_pct = 100.0 * len(fp) / clean_n if clean_n else 0.0
    victim_pct = 100.0 * len(victims) / clean_n if clean_n else 0.0

    print(f"{'false positives (unrelated match)':<44}{len(fp):>6}  ({fp_pct:.2f}% of clean)")
    print(f"{'pair-victim flags (correct - image stolen)':<44}{len(victims):>6}  ({victim_pct:.2f}% of clean)")
    print(f"{'true positives on the fraud case itself':<44}{len(caught):>6}")

    # No pooled recall across PAIRED_FRAUD_ARCHETYPES, deliberately - see
    # Check.target_archetypes in src/checks/base.py. Pooling REUSE (this
    # check's actual job) with EXTERNAL_SOURCING (an image from outside
    # the corpus, which this check cannot see by construction) produced a
    # "54.29% recall" that described nothing real and understated a check
    # measuring 100% on the archetype it was built for.
    targets = target_archetypes_for(DUPLICATE_CHECK_ID)
    print("\nRECALL (this check's designed job):")
    for archetype in targets:
        total = results["total_by_archetype"].get(archetype, 0)
        got = results["caught_by_archetype"].get(archetype, 0)
        if total:
            print(f"  {archetype:<20}{got:>4}/{total:<5}({100.0 * got / total:5.1f}%)")
        else:
            print(f"  {archetype:<20} UNMEASURABLE - 0 cases with images in this corpus")

    incidental = [a for a in PAIRED_FRAUD_ARCHETYPES if a not in targets]
    if incidental:
        print("\nINCIDENTAL DETECTIONS (outside this check's designed job, excluded from recall):")
        for archetype in incidental:
            total = results["total_by_archetype"].get(archetype, 0)
            if not total:
                continue
            got = results["caught_by_archetype"].get(archetype, 0)
            print(
                f"  {archetype:<20}{got:>4}/{total:<5}({100.0 * got / total:5.1f}%)"
                "   <- corpus/pool overlap; needs reverse-image search, not internal matching"
            )

    if victims:
        by_archetype = Counter(v["matched_archetype"] for v in victims)
        print(f"\npair-victim flags by matched archetype: {dict(by_archetype)}")
        print("  (a clean case flagged because a fraud case took its photo - the check is")
        print("   reporting a real duplicate; which half is fraudulent is a human decision)")

    if fp:
        print(f"\nfalse positives - genuinely unrelated matches:")
        print(f"  {'clean case':<14}{'matched':<14}{'archetype':<20}{'hamming':>8}{'cosine':>9}")
        for record in fp[:15]:
            print(
                f"  {record['case_id']:<14}{str(record['matched_case_id']):<14}"
                f"{record['matched_archetype']:<20}{record['hamming_distance']:>8}"
                f"{record['cosine_similarity']:>9}"
            )
        if len(fp) > 15:
            print(f"  ... and {len(fp) - 15} more")
    else:
        print("\nfalse positives: none - no clean case was linked to an unrelated case")


# ---------------------------------------------------------------------------
# Generic per-check scoring (checks 4-6)
#
# Unlike internal_duplicate above, these checks don't produce pair-shaped
# findings - a match against the external corpus, a missing content
# credential, or a detector score is a statement about one image, not
# about a relationship between two cases. So they get the ordinary
# accounting: verdict distribution, recall against the archetype the
# check is meant to catch, and false positives on clean cases.
# ---------------------------------------------------------------------------

def _resolution_bucket(image_path: str) -> tuple[Optional[int], str]:
    """
    (width, bucket_label) for one image, or (None, "unreadable"). Uses
    PIL's lazy .size, which reads the header only - no pixel decode - so
    tagging every image in the corpus costs milliseconds, not minutes.
    """
    try:
        from PIL import Image as PILImage

        with PILImage.open(image_path) as img:
            width = img.size[0]
    except Exception:  # noqa: BLE001 - a missing/corrupt file must not stop the evaluation
        return None, "unreadable"
    for low, high, label in RESOLUTION_BUCKETS:
        if low <= width < high:
            return width, label
    return width, "unknown"


def target_archetypes_for(check_id: str) -> tuple[str, ...]:
    """
    Read from the Check itself (see Check.target_archetypes in
    src/checks/base.py), never from a table maintained here - a mapping
    kept in the harness goes stale the moment a check is added or its
    scope changes, and a stale mapping silently mis-scores a check
    rather than failing loudly.
    """
    return tuple(getattr(REGISTRY[check_id], "target_archetypes", ()))


def evaluate_check(
    conn, ground_truth: list[dict[str, Any]], check_id: str, limit: Optional[int] = None
) -> dict[str, Any]:
    targets = target_archetypes_for(check_id)
    by_archetype: dict[str, Counter] = {}
    case_level_concern: Counter = Counter()
    case_totals: Counter = Counter()
    no_image_cases: Counter = Counter()
    fp_examples: list[dict[str, Any]] = []
    probabilities: list[float] = []
    ai_records: list[dict[str, Any]] = []
    plate_records: list[dict[str, Any]] = []

    rows = ground_truth if limit is None else ground_truth[:limit]
    for row in rows:
        case_id, archetype = row["case_id"], row["archetype"]
        case = db.get_case(conn, case_id)
        if case is None:
            continue
        findings = run_checks(conn, case, check_ids=[check_id])
        if not findings:
            continue

        # A case with no images still produces a finding - run_checks
        # emits INCONCLUSIVE "No images available for this case." - so
        # counting it in the recall denominator would manufacture a miss
        # out of a case the check was never given anything to inspect.
        # AI_GENERATED is exactly this: 34 cases, zero images, because
        # data/ai_generated/ was never populated. Only cases the check
        # could actually act on belong in the denominator.
        if not db.get_images_for_case(conn, case_id):
            counter = by_archetype.setdefault(archetype, Counter())
            for f in findings:
                counter[f.verdict.value] += 1
            no_image_cases[archetype] += 1
            continue

        counter = by_archetype.setdefault(archetype, Counter())
        images_by_id = {img.image_id: img for img in db.get_images_for_case(conn, case_id)}
        for f in findings:
            counter[f.verdict.value] += 1

            probability = f.evidence.get("artificial_probability")
            if probability is not None:
                image = images_by_id.get(f.evidence.get("image_id"))
                width, bucket = _resolution_bucket(image.path) if image is not None else (None, "unknown")
                probabilities.append(probability)
                ai_records.append(
                    {
                        "case_id": case_id,
                        "archetype": archetype,
                        "probability": probability,
                        "verdict": f.verdict.value,
                        "width": width,
                        "bucket": bucket,
                    }
                )

            # A plate finding is identifiable by carrying the
            # plate_candidate key at all - present (possibly None) on
            # every finding PlateOCRCheck emits once OCR actually ran.
            if "plate_candidate" in f.evidence:
                image = images_by_id.get(f.evidence.get("image_id"))
                width, bucket = _resolution_bucket(image.path) if image is not None else (None, "unknown")
                plate_records.append(
                    {
                        "case_id": case_id,
                        "archetype": archetype,
                        "verdict": f.verdict.value,
                        "plate_candidate": f.evidence.get("plate_candidate"),
                        "policy_registration": f.evidence.get("policy_registration_normalised"),
                        "ocr_confidence": f.evidence.get("ocr_confidence"),
                        "edit_distance": f.evidence.get("edit_distance"),
                        "raw_string_count": len(f.evidence.get("raw_ocr_strings") or []),
                        "width": width,
                        "bucket": bucket,
                    }
                )

        case_totals[archetype] += 1
        if any(f.verdict == Verdict.CONCERN for f in findings):
            case_level_concern[archetype] += 1
            if archetype == "CLEAN" and len(fp_examples) < 10:
                concern = next(f for f in findings if f.verdict == Verdict.CONCERN)
                fp_examples.append({"case_id": case_id, "explanation": concern.explanation})

    return {
        "check_id": check_id,
        "target_archetypes": targets,
        "by_archetype": by_archetype,
        "case_level_concern": case_level_concern,
        "case_totals": case_totals,
        "no_image_cases": no_image_cases,
        "false_positive_examples": fp_examples,
        "artificial_probabilities": probabilities,
        "ai_records": ai_records,
        "plate_records": plate_records,
    }


def print_check_report(results: dict[str, Any]) -> None:
    check_id = results["check_id"]
    targets = results["target_archetypes"]
    totals: Counter = Counter()
    for counter in results["by_archetype"].values():
        totals.update(counter)

    print("\n" + "=" * 78)
    print(f"{check_id.upper()}")
    print("=" * 78)

    grand = sum(totals.values())
    print(f"findings: {grand} across {sum(results['case_totals'].values())} cases")
    for verdict in ("concern", "inconclusive", "pass"):
        n = totals.get(verdict, 0)
        pct = 100.0 * n / grand if grand else 0.0
        print(f"  {verdict:<14}{n:>6}  ({pct:5.1f}%)")

    clean_total = results["case_totals"].get("CLEAN", 0)
    clean_fp = results["case_level_concern"].get("CLEAN", 0)
    fp_pct = 100.0 * clean_fp / clean_total if clean_total else 0.0
    print(f"\nfalse positives on clean cases: {clean_fp}/{clean_total}  ({fp_pct:.2f}%)")

    # Headline: recall against the archetypes this check was built for,
    # reported per archetype. Deliberately never summed into one figure
    # across a check's whole corpus - see Check.target_archetypes in
    # src/checks/base.py for why a pooled per-check recall is a number
    # that describes nothing.
    print("\nRECALL (this check's designed job):")
    if not targets:
        print("  n/a - no archetype in this corpus targets this check")
    for archetype in targets:
        total = results["case_totals"].get(archetype, 0)
        hit = results["case_level_concern"].get(archetype, 0)
        skipped = results["no_image_cases"].get(archetype, 0)
        if total == 0:
            # Distinguishes "the check missed them" from "there was
            # nothing to find" - a 0% here would be a fabricated number,
            # not a measurement.
            reason = (
                f"all {skipped} case(s) carry zero images"
                if skipped
                else "0 cases of this archetype were evaluated"
            )
            print(f"  {archetype:<20} UNMEASURABLE - {reason}")
        else:
            note = f"   ({skipped} further case(s) skipped: no images)" if skipped else ""
            print(f"  {archetype:<20}{hit:>4}/{total:<5}({100.0 * hit / total:5.1f}%){note}")

    # Everything else this check happened to fire on. Real detections,
    # reported so they aren't lost - but kept out of the recall figure
    # above, because the check makes no claim about these archetypes.
    incidental = {
        archetype: count
        for archetype, count in sorted(results["case_level_concern"].items())
        if archetype not in targets and archetype != "CLEAN" and count
    }
    if incidental:
        print("\nINCIDENTAL DETECTIONS (outside this check's designed job, excluded from recall):")
        for archetype, count in incidental.items():
            total = results["case_totals"].get(archetype, 0)
            print(f"  {archetype:<20}{count:>4}/{total:<5}({100.0 * count / total:5.1f}%)" if total else f"  {archetype}: {count}")

    probabilities = results["artificial_probabilities"]
    if probabilities:
        ordered = sorted(probabilities)
        mid = ordered[len(ordered) // 2]
        print(
            f"\nartificial-class probability over {len(ordered)} images: "
            f"min {ordered[0]:.3f}, median {mid:.3f}, max {ordered[-1]:.3f}"
        )

    if results.get("ai_records"):
        print_ai_resolution_breakdown(results["ai_records"])
    if results.get("plate_records"):
        print_plate_resolution_breakdown(results["plate_records"])

    if results["false_positive_examples"]:
        print("\nfalse-positive examples on clean cases:")
        for example in results["false_positive_examples"][:5]:
            print(f"  {example['case_id']}: {example['explanation']}")


def print_ai_resolution_breakdown(records: list[dict[str, Any]]) -> None:
    """
    Artificial-class probability bucketed by image width, and - the
    number that actually matters - the CONCERN rate on CLEAN images
    within each bucket.

    The hypothesis this tests: if the detector's false-positive rate
    climbs as resolution falls, it is responding to compression and
    upscaling artifacts rather than to generation artifacts. That would
    be a substantive limit on these tools for real claim photos, which
    arrive small and heavily recompressed far more often than they arrive
    pristine - a detector that fires on "this image is low quality" is
    not detecting synthesis, it is detecting the ordinary condition of
    evidence in this domain, and would penalise exactly the honest
    claimants who photograph a bumper on an old phone over patchy data.
    """
    import statistics

    clean = [r for r in records if r["archetype"] == "CLEAN"]
    print("\nAI PROBABILITY BY IMAGE RESOLUTION (clean-case images only):")
    print(f"  {'bucket':<12}{'images':>8}{'median p':>11}{'mean p':>9}{'CONCERN':>9}{'FP rate':>10}")

    labels = [label for _, _, label in RESOLUTION_BUCKETS] + ["unreadable", "unknown"]
    rows: list[tuple[str, int, float]] = []
    for label in labels:
        bucket = [r for r in clean if r["bucket"] == label]
        if not bucket:
            continue
        probs = [r["probability"] for r in bucket]
        concerns = sum(1 for r in bucket if r["verdict"] == "concern")
        fp_rate = 100.0 * concerns / len(bucket)
        rows.append((label, len(bucket), fp_rate))
        print(
            f"  {label:<12}{len(bucket):>8}{statistics.median(probs):>11.3f}"
            f"{statistics.mean(probs):>9.3f}{concerns:>9}{fp_rate:>9.1f}%"
        )

    # State the conclusion the table supports, rather than leaving the
    # reader to infer it - but only when there is enough spread to say
    # anything, and only comparing the real resolution buckets.
    real = [r for r in rows if r[0] not in ("unreadable", "unknown") and r[1] >= MIN_BUCKET_FOR_TREND]
    if len(real) >= 2:
        lowest, highest = real[0], real[-1]
        delta = lowest[2] - highest[2]
        print()
        if delta >= TREND_DELTA_PP:
            print(
                f"  -> FP rate is {delta:.1f} pp HIGHER on {lowest[0]} than on {highest[0]}. This is evidence the "
                "detector is responding to compression/resolution artifacts, not generation artifacts."
            )
        elif delta <= -TREND_DELTA_PP:
            print(
                f"  -> FP rate is {-delta:.1f} pp higher on {highest[0]} than on {lowest[0]} - the opposite of the "
                "compression-artifact hypothesis; resolution alone does not explain the errors."
            )
        else:
            print(
                f"  -> FP rate varies by only {abs(delta):.1f} pp across resolution buckets - no strong evidence "
                "that resolution alone drives the detector's errors."
            )

    AI_RESOLUTION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(AI_RESOLUTION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, indent=2)
    print(f"\n  per-image probabilities saved to {AI_RESOLUTION_OUTPUT}")


def print_plate_resolution_breakdown(records: list[dict[str, Any]]) -> None:
    """
    Plate-reading viability against image width - the deliberate
    experiment this check exists to run, not a footnote.

    Per bucket: how many images yielded plate-shaped text at all, how
    many of those matched the policy registration, and median OCR
    confidence. The question being answered is "at what resolution does
    reading a plate become possible?", because the answer is actionable
    guidance for a production system - a claims app can require the
    claimant to photograph the plate closely enough to clear that bar,
    and no amount of model choice substitutes for pixels that were never
    captured.
    """
    import statistics

    print("\nPLATE OCR BY IMAGE RESOLUTION (all archetypes):")
    print(f"  {'bucket':<12}{'images':>8}{'plate found':>13}{'find rate':>11}{'matched':>9}{'median conf':>13}")

    labels = [label for _, _, label in RESOLUTION_BUCKETS] + ["unreadable", "unknown"]
    rows: list[tuple[str, int, float]] = []
    for label in labels:
        bucket = [r for r in records if r["bucket"] == label]
        if not bucket:
            continue
        found = [r for r in bucket if r["plate_candidate"]]
        matched = [r for r in found if r["plate_candidate"] == r["policy_registration"]]
        confidences = [r["ocr_confidence"] for r in found if r["ocr_confidence"] is not None]
        find_rate = 100.0 * len(found) / len(bucket)
        rows.append((label, len(bucket), find_rate))
        median_conf = f"{statistics.median(confidences):.3f}" if confidences else "n/a"
        print(
            f"  {label:<12}{len(bucket):>8}{len(found):>13}{find_rate:>10.1f}%"
            f"{len(matched):>9}{median_conf:>13}"
        )

    total = len(records)
    found_total = sum(1 for r in records if r["plate_candidate"])
    print(f"\n  overall: {found_total}/{total} images yielded plate-shaped text ({100.0 * found_total / total:.1f}%)")

    # Same guard as the AI breakdown: only buckets with enough images may
    # carry a claim, and only a real spread counts as a trend.
    real = [r for r in rows if r[0] not in ("unreadable", "unknown") and r[1] >= MIN_BUCKET_FOR_TREND]
    print()
    if len(real) < 2:
        print(
            f"  -> too few populated resolution buckets (>= {MIN_BUCKET_FOR_TREND} images) to say anything "
            "about a resolution threshold."
        )
    else:
        lowest, highest = real[0], real[-1]
        delta = highest[2] - lowest[2]
        if delta >= TREND_DELTA_PP:
            print(
                f"  -> plate-find rate rises {delta:.1f} pp from {lowest[0]} ({lowest[2]:.1f}%) to "
                f"{highest[0]} ({highest[2]:.1f}%). Plate reading is resolution-limited on this corpus; "
                "capture guidance should specify a minimum plate width, not just a minimum image width."
            )
        elif delta <= -TREND_DELTA_PP:
            print(
                f"  -> plate-find rate FALLS {-delta:.1f} pp as resolution rises, which is the opposite of "
                "expectation - investigate before reporting; this suggests something other than resolution "
                "is driving the result."
            )
        else:
            print(
                f"  -> plate-find rate varies by only {abs(delta):.1f} pp across resolution buckets. "
                "On this corpus resolution alone does not explain plate-reading success"
                + (" - and the overall rate is so low that the check is simply not viable here."
                   if found_total * 10 < total else ".")
            )

    PLATE_RESOLUTION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(PLATE_RESOLUTION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, indent=2)
    print(f"\n  per-image plate results saved to {PLATE_RESOLUTION_OUTPUT}")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate FraudLens checks against ground truth.")
    parser.add_argument("--limit", type=int, default=None, help="only evaluate the first N cases of each group")
    parser.add_argument("--db-path", default=None, help="sqlite database path (default: auto-detect)")
    parser.add_argument(
        "--checks",
        default="internal_duplicate",
        help="comma-separated check ids to evaluate, or 'new' for the three added in check batch 2",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else resolve_db_path()
    ground_truth = load_ground_truth()

    requested = args.checks.strip()
    check_ids = (
        ["external_corpus", "c2pa_credentials", "ai_generation"]
        if requested == "new"
        else [c.strip() for c in requested.split(",") if c.strip()]
    )

    conn = db.connect(db_path)
    db.init_db(conn)
    try:
        for check_id in check_ids:
            if check_id == DUPLICATE_CHECK_ID:
                print_report(evaluate_duplicate(conn, ground_truth, limit=args.limit))
            else:
                print_check_report(evaluate_check(conn, ground_truth, check_id, limit=args.limit))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
