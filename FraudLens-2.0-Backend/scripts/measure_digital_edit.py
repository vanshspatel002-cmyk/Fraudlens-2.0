"""
Measure the digital-edit forensics against ground truth, then set the
threshold from what was measured.

The check ships uncalibrated and abstains until this script has run. That
is deliberate: a forensic score with a guessed threshold is an accusation
with no evidence behind it, and this project's primary metric is the
false-positive rate on honest claimants.

What this does:

1. Score every image in the corpus on all three signals.
2. Compare the DIGITAL_EDIT population against the CLEAN population, per
   signal and combined, and report AUC for each.
3. Choose signal weights and a threshold from the data - not from
   intuition about which signal ought to matter.
4. Write outputs/digital_edit_calibration.json, which the check reads.

If the measurement shows no discriminative power (AUC at or below ~0.6),
this script says so plainly, writes calibrated=false, and recommends
weight 0.0 plus a write-up in outputs/retired_checks.md. A measured
negative result is a legitimate outcome - vehicle_consistency already
went that way, and it cost far less than shipping a check nobody checked.

Usage:
    python scripts/measure_digital_edit.py            # full corpus
    python scripts/measure_digital_edit.py --limit 60 # smoke test
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

import numpy as np

from src import db
from src.checks import digital_edit

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")
SCORES_OUTPUT = Path("outputs/digital_edit_scores.json")
CALIBRATION_OUTPUT = Path("outputs/digital_edit_calibration.json")

SIGNALS = ("ghost", "noise", "edge")

# Below this, the signal is not telling us anything a coin could not.
# 0.60 is deliberately unambitious - a check has to clear a low bar to be
# worth *any* weight, and anything near 0.5 is noise.
MIN_USEFUL_AUC = 0.60

# Target false-positive rate on clean cases when picking the operating
# point. The check is one signal among several, so it is allowed to miss
# rather than to accuse: at 5% it can contribute without dominating.
TARGET_FP_RATE = 0.05


def load_ground_truth() -> dict[str, str]:
    with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
        return {r["case_id"]: r["archetype"] for r in csv.DictReader(fh)}


def auc(positive: list[float], negative: list[float]) -> float:
    """
    Probability a random positive scores above a random negative.
    Computed by rank-sum rather than by sweeping thresholds, so ties are
    handled correctly - and ties matter here, since several signals
    return exactly 0.0 on small images.
    """
    if not positive or not negative:
        return 0.5
    combined = np.concatenate([np.asarray(positive), np.asarray(negative)])
    order = combined.argsort()
    ranks = np.empty(len(combined), dtype=np.float64)
    ranks[order] = np.arange(1, len(combined) + 1)
    # Average ranks within tied groups.
    _, inverse, counts = np.unique(combined, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inverse, ranks)
    ranks = (sums / counts)[inverse]
    n_pos = len(positive)
    rank_sum = ranks[:n_pos].sum()
    return float((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * len(negative)))


def threshold_at_fp_rate(negative: list[float], rate: float) -> float:
    """The score exceeded by exactly `rate` of the clean population."""
    if not negative:
        return 1.0
    return float(np.quantile(np.asarray(negative), 1.0 - rate))


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Calibrate the digital-edit check against ground truth.")
    parser.add_argument("--limit", type=int, default=None, help="Only score the first N images.")
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args(argv)

    ground_truth = load_ground_truth()
    conn = db.connect(args.db_path)
    db.init_db(conn)

    images = db.get_all_images(conn)
    if args.limit:
        images = images[: args.limit]

    print(f"scoring {len(images)} images")
    records: list[dict[str, Any]] = []
    for i, image in enumerate(images, start=1):
        scores = digital_edit.analyse(image.path)
        if scores is None:
            continue
        records.append(
            {
                "case_id": image.case_id,
                "image_id": image.image_id,
                "archetype": ground_truth.get(image.case_id, "UNKNOWN"),
                **scores,
            }
        )
        if i % 100 == 0 or i == len(images):
            print(f"  [{i}/{len(images)}]", flush=True)

    conn.close()

    by_archetype: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_archetype[r["archetype"]].append(r)

    edited = by_archetype.get("DIGITAL_EDIT", [])
    clean = by_archetype.get("CLEAN", [])
    print(f"\nDIGITAL_EDIT images: {len(edited)}   CLEAN images: {len(clean)}")

    if not edited or not clean:
        print("ERROR: need both populations to calibrate; aborting")
        return

    # --- per-signal discriminative power -------------------------------
    print("\nPER-SIGNAL AUC (0.5 = useless, 1.0 = perfect)")
    print(f"  {'signal':<10}{'AUC':>8}{'edited median':>16}{'clean median':>15}")
    aucs: dict[str, float] = {}
    for signal in SIGNALS:
        pos = [r[signal] for r in edited]
        neg = [r[signal] for r in clean]
        a = auc(pos, neg)
        aucs[signal] = a
        print(f"  {signal:<10}{a:>8.3f}{np.median(pos):>16.4f}{np.median(neg):>15.4f}")

    # --- weight the signals by measured usefulness ----------------------
    # Weight proportional to how far each signal beats chance, so a
    # signal that carries nothing contributes nothing. Guessing equal
    # thirds would let the two useless signals dilute the one that works.
    lift = {s: max(0.0, aucs[s] - 0.5) for s in SIGNALS}
    total_lift = sum(lift.values())
    if total_lift <= 0:
        weights = {s: 1 / 3 for s in SIGNALS}
    else:
        weights = {s: lift[s] / total_lift for s in SIGNALS}
    print("\nSIGNAL WEIGHTS (proportional to measured lift over chance)")
    for s in SIGNALS:
        print(f"  {s:<10}{weights[s]:>8.3f}")

    def combine(r: dict[str, Any]) -> float:
        return sum(r[s] * weights[s] for s in SIGNALS)

    pos_combined = [combine(r) for r in edited]
    neg_combined = [combine(r) for r in clean]
    combined_auc = auc(pos_combined, neg_combined)
    best_single = max(aucs, key=lambda s: aucs[s])
    print(f"\nCOMBINED AUC: {combined_auc:.3f}   (best single signal: {best_single} at {aucs[best_single]:.3f})")

    # --- verdict on the check itself ------------------------------------
    usable = combined_auc >= MIN_USEFUL_AUC
    concern = threshold_at_fp_rate(neg_combined, TARGET_FP_RATE)
    inconclusive = threshold_at_fp_rate(neg_combined, TARGET_FP_RATE * 3)
    recall_at_concern = float(np.mean([p >= concern for p in pos_combined]))
    fp_at_concern = float(np.mean([n >= concern for n in neg_combined]))

    print("\nOPERATING POINT (threshold set at the score exceeded by "
          f"{TARGET_FP_RATE:.0%} of clean images)")
    print(f"  concern threshold: {concern:.4f}")
    print(f"  recall on DIGITAL_EDIT images: {recall_at_concern:.1%}")
    print(f"  false-positive rate on CLEAN images: {fp_at_concern:.1%}")

    print("\n" + "=" * 70)
    if usable:
        recommended_weight = 0.5 if combined_auc < 0.75 else 0.7
        print(f"VERDICT: usable. AUC {combined_auc:.3f} >= {MIN_USEFUL_AUC}.")
        print(f"  recommended weight: {recommended_weight}")
    else:
        recommended_weight = 0.0
        print(f"VERDICT: NO DISCRIMINATIVE POWER. AUC {combined_auc:.3f} < {MIN_USEFUL_AUC}.")
        print("  This check cannot separate edited images from ordinary claim photographs")
        print("  on this corpus. Recommended: weight 0.0, and document it in")
        print("  outputs/retired_checks.md the way vehicle_consistency was documented.")
        print("  The measurement is the result; do not ship the threshold.")
    print("=" * 70)

    # --- per-variant detection -------------------------------------------
    # The generator now builds DIGITAL_EDIT two ways and records which in
    # fraud_metadata: "recompressed_patch" pre-compresses the pasted region
    # so it carries a different compression history from its host, while
    # "single_save" only pastes and saves once. Ghost analysis should find
    # the first and not the second, and a single pooled recall would hide
    # exactly that distinction - which is the whole reason the variants
    # exist.
    import csv as _csv

    variants: dict[str, str] = {}
    try:
        with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                if row["archetype"] != "DIGITAL_EDIT":
                    continue
                try:
                    variants[row["case_id"]] = json.loads(row["fraud_metadata"] or "{}").get("variant", "unknown")
                except json.JSONDecodeError:
                    variants[row["case_id"]] = "unknown"
    except OSError:
        pass

    calibration_variants: dict[str, Any] = {}
    if variants:
        print("\nPER-VARIANT DETECTION (DIGITAL_EDIT only)")
        print(f"  {'variant':<22}{'n':>5}{'median':>10}{'AUC vs clean':>15}{'detected':>11}")
        by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in edited:
            by_variant[variants.get(r["case_id"], "unknown")].append(r)
        for variant in sorted(by_variant):
            vals = [combine(r) for r in by_variant[variant]]
            v_auc = auc(vals, neg_combined)
            detected = float(np.mean([v >= concern for v in vals]))
            print(f"  {variant:<22}{len(vals):>5}{np.median(vals):>10.4f}{v_auc:>15.3f}{detected:>10.1%}")
            calibration_variants[variant] = {
                "n": len(vals),
                "median": float(np.median(vals)),
                "auc": v_auc,
                "detected_at_threshold": detected,
            }


    # Cross-archetype behaviour, for the record.
    print("\nCOMBINED SCORE BY ARCHETYPE")
    for archetype in sorted(by_archetype):
        vals = [combine(r) for r in by_archetype[archetype]]
        flagged = float(np.mean([v >= concern for v in vals]))
        print(f"  {archetype:<20} n={len(vals):>4}  median={np.median(vals):.4f}  flagged={flagged:>6.1%}")

    calibration = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # calibrated=false makes the check abstain entirely - it will
        # report its scores as INCONCLUSIVE and never accuse. That is the
        # correct behaviour for a signal measured to be uninformative.
        "calibrated": bool(usable),
        "concern_threshold": concern,
        "inconclusive_threshold": inconclusive,
        "signal_weights": weights,
        "signal_auc": aucs,
        "combined_auc": combined_auc,
        "recall_at_threshold": recall_at_concern,
        "fp_rate_at_threshold": fp_at_concern,
        "recommended_weight": recommended_weight,
        "n_edited_images": len(edited),
        "n_clean_images": len(clean),
        "per_variant": calibration_variants,
    }
    CALIBRATION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(calibration, fh, indent=2)
    with open(SCORES_OUTPUT, "w", encoding="utf-8") as fh:
        json.dump({"records": records}, fh)
    print(f"\ncalibration -> {CALIBRATION_OUTPUT}")
    print(f"per-image scores -> {SCORES_OUTPUT}")


if __name__ == "__main__":
    main()
