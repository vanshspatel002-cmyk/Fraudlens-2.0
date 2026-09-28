"""
Measure the AI detector against genuinely AI-generated images.

This is the first time ai_generation can be evaluated on its target. Every
previous measurement reported UNMEASURABLE because the AI_GENERATED cases
carried no images at all; the detector's only number was a 76.96% false
positive rate on ordinary claim photographs.

Two things this script is careful about, because either would corrupt the
result:

1. **AI_GENERATED_BASELINE cases contain one synthetic image and one
   genuine one.** The fraud is submitting a fabricated undamaged-vehicle
   photo among honest ones, so scoring the case as a unit would mix a real
   photograph into the synthetic population and drag the detection rate
   toward the middle for reasons that have nothing to do with the
   detector. Images are classified individually, using fraud_metadata's
   ai_image_source to identify which file is the synthetic one.

2. **Resolution is a confound, and it was neutralised at source.** The AI
   images arrived at median 1522px on the short side against the curated
   corpus's 189px. Left alone, any detector could have separated them on
   dimensions and scored near-perfectly while learning nothing about
   synthesis. scripts/normalise_ai_images.py downscales them to match the
   curated distribution; the resolution breakdown below is reported partly
   to confirm that neutralisation held.

Usage:
    python scripts/measure_ai_detector.py
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from PIL import Image as PILImage

from src import db
from src.checks import ai_detection

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")
OUTPUT = Path("outputs/ai_detector_measurement.json")

# Same buckets as the earlier resolution breakdown, so the two compare.
BUCKETS = ((0, 200, "<200px"), (200, 300, "200-299px"), (300, 400, "300-399px"), (400, 10 ** 9, "400px+"))

# The check's own CONCERN threshold. Measured against even though the check
# is demoted and forces INCONCLUSIVE, because the question here is "can
# this model tell synthetic from real", not "what does it currently emit".
CONCERN_AT = ai_detection.AIGenerationCheck.CONCERN_THRESHOLD


def bucket_for(width: int) -> str:
    for low, high, label in BUCKETS:
        if low <= width < high:
            return label
    return "unknown"


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Measure the AI detector on genuinely synthetic images.")
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args(argv)

    with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    archetype = {r["case_id"]: r["archetype"] for r in rows}

    synthetic_names: set[str] = set()
    for r in rows:
        try:
            meta = json.loads(r["fraud_metadata"] or "{}")
        except json.JSONDecodeError:
            continue
        source = meta.get("ai_image_source")
        if source:
            synthetic_names.add(Path(source).name)

    conn = db.connect(args.db_path)
    db.init_db(conn)
    images = db.get_all_images(conn)
    conn.close()

    classifier = ai_detection.get_pipeline()
    if classifier is None:
        print("ERROR: AI detector could not be loaded; aborting")
        return

    records: list[dict[str, Any]] = []
    for i, image in enumerate(images, start=1):
        arch = archetype.get(image.case_id, "UNKNOWN")
        is_synth = Path(image.path).name in synthetic_names

        if arch == "AI_GENERATED" and is_synth:
            population = "AI_GENERATED (synthetic)"
        elif arch == "AI_GENERATED_BASELINE" and is_synth:
            population = "AI_GENERATED_BASELINE (synthetic)"
        elif arch == "AI_GENERATED_BASELINE":
            population = "AI_GENERATED_BASELINE (genuine companion)"
        elif arch == "CLEAN":
            population = "CLEAN (real photo)"
        else:
            population = arch + " (real photo)"

        try:
            predictions = classifier(image.path)
            probability = ai_detection._artificial_probability(predictions)
            with PILImage.open(image.path) as im:
                width = im.width
        except Exception as e:  # noqa: BLE001
            print("  skip " + image.image_id + ": " + type(e).__name__ + ": " + str(e))
            continue
        if probability is None:
            continue

        records.append({
            "case_id": image.case_id, "archetype": arch, "population": population,
            "synthetic": is_synth, "probability": probability,
            "width": width, "bucket": bucket_for(width),
        })
        if i % 200 == 0 or i == len(images):
            print("  [" + str(i) + "/" + str(len(images)) + "]", flush=True)

    by_pop: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_pop[r["population"]].append(r)

    print("\n" + "=" * 78)
    print("AI DETECTOR vs GENUINELY SYNTHETIC IMAGES")
    print("=" * 78)
    header = "population".ljust(42) + "n".rjust(5) + "median p".rjust(11) + "flagged".rjust(10)
    print(header)
    for population in sorted(by_pop, key=lambda k: (not by_pop[k][0]["synthetic"], k)):
        vals = [r["probability"] for r in by_pop[population]]
        flagged = sum(1 for v in vals if v >= CONCERN_AT) / len(vals)
        line = (population.ljust(42) + str(len(vals)).rjust(5)
                + ("%.3f" % statistics.median(vals)).rjust(11)
                + ("%.1f%%" % (100 * flagged)).rjust(10))
        print(line)

    synth = [r["probability"] for r in records if r["synthetic"]]
    clean = [r["probability"] for r in records if r["archetype"] == "CLEAN"]

    print("\n" + "-" * 78)
    verdict = ""
    if synth and clean:
        synth_rate = sum(1 for v in synth if v >= CONCERN_AT) / len(synth)
        clean_rate = sum(1 for v in clean if v >= CONCERN_AT) / len(clean)
        lift = synth_rate - clean_rate
        print("synthetic images flagged:      %.1f%%  (n=%d)" % (100 * synth_rate, len(synth)))
        print("CLEAN real photos flagged:     %.1f%%  (n=%d)" % (100 * clean_rate, len(clean)))
        print("discriminative lift:           %+.1f pp" % (100 * lift))
        print()
        if lift <= 0.0:
            verdict = "negative"
            print("VERDICT: NEGATIVE discriminative value confirmed. The detector flags real")
            print("  claim photographs at least as often as genuinely synthetic ones. Weight")
            print("  stays 0.0 - acting on this signal would be worse than ignoring it.")
        elif lift < 0.20:
            verdict = "marginal"
            print("VERDICT: marginal. The lift is real but far too small to act on at a")
            print("  %.0f%% cost on honest claimants. Weight stays 0.0." % (100 * clean_rate))
        else:
            verdict = "usable"
            print("VERDICT: genuine discriminative power. Revisiting the 0.0 weight is")
            print("  justified - see the report for the recommended operating point.")
    print("-" * 78)

    print("\nSYNTHETIC-IMAGE DETECTION BY RESOLUTION")
    print("  " + "bucket".ljust(12) + "n".rjust(5) + "median p".rjust(11) + "flagged".rjust(10))
    for _, _, label in BUCKETS:
        vals = [r["probability"] for r in records if r["synthetic"] and r["bucket"] == label]
        if not vals:
            continue
        flagged = sum(1 for v in vals if v >= CONCERN_AT) / len(vals)
        print("  " + label.ljust(12) + str(len(vals)).rjust(5)
              + ("%.3f" % statistics.median(vals)).rjust(11)
              + ("%.1f%%" % (100 * flagged)).rjust(10))

    print("\nREAL-PHOTO FALSE POSITIVES BY RESOLUTION (clean cases)")
    print("  " + "bucket".ljust(12) + "n".rjust(5) + "median p".rjust(11) + "flagged".rjust(10))
    for _, _, label in BUCKETS:
        vals = [r["probability"] for r in records if r["archetype"] == "CLEAN" and r["bucket"] == label]
        if not vals:
            continue
        flagged = sum(1 for v in vals if v >= CONCERN_AT) / len(vals)
        print("  " + label.ljust(12) + str(len(vals)).rjust(5)
              + ("%.3f" % statistics.median(vals)).rjust(11)
              + ("%.1f%%" % (100 * flagged)).rjust(10))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"threshold": CONCERN_AT, "verdict": verdict, "records": records}, indent=2),
        encoding="utf-8",
    )
    print("\nper-image results -> " + str(OUTPUT))


if __name__ == "__main__":
    main()
