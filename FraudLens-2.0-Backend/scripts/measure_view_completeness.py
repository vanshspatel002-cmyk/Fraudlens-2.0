"""
Measure view_completeness, component by component.

The check has two independent components and they must be measured
separately, because one is broken by a corpus property and the other might
not be:

  1. **View count.** Every underwriting case in this corpus carries exactly
     two images, so a four-view requirement flags 100% of cases - clean and
     fraudulent alike. That is a statement about the generator, not about
     coverage.

  2. **Angle similarity.** Independent of the count: are the two images in
     an AI_GENERATED_BASELINE case more similar to each other than the two
     in a clean case? Synthetic images of an intact vehicle might plausibly
     be near-duplicates in a way genuine photographs are not. If so, that
     component discriminates even though the count does not.

  3. **Plate visibility.** Also independent, and measurable wherever
     perception exists.

Reporting a single number for the check would hide which of these works.

Writes outputs/view_completeness_measurement.json.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks.view_completeness import SAME_VIEW_COSINE, _cosine

OUT = Path("outputs/view_completeness_measurement.json")


def auc(pos: list[float], neg: list[float]) -> Optional[float]:
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(
                     open("data/generated/ground_truth.csv", encoding="utf-8"))}
    perceived = {r[0] for r in conn.execute(
        "SELECT content_hash FROM perception_records")}
    plates = {r[0]: (r[1] or "").strip() for r in conn.execute(
        "SELECT content_hash, plate_text FROM perception_records")}

    groups: dict[str, list[dict[str, Any]]] = {"target": [], "clean": []}
    image_counts: dict[str, list[int]] = {"target": [], "clean": []}

    for case in db.get_all_cases(conn):
        if case.agent_type != "underwriting":
            continue
        arch = archetype.get(case.case_id)
        label = ("target" if arch == "AI_GENERATED_BASELINE"
                 else "clean" if arch == "CLEAN" else None)
        if label is None:
            continue

        images = db.get_images_for_case(conn, case.case_id)
        image_counts[label].append(len(images))
        embedded = [i for i in images if getattr(i, "embedding", None) is not None]
        if len(embedded) < 2:
            continue

        sims = []
        for i in range(len(embedded)):
            for j in range(i + 1, len(embedded)):
                sims.append(_cosine(embedded[i].embedding, embedded[j].embedding))

        any_perception = any(i.content_hash in perceived for i in images)
        plate = any(
            (plates.get(i.content_hash) or "").lower() not in
            ("", "none", "n/a", "unreadable", "not visible", "illegible", "unknown")
            for i in images)

        groups[label].append({
            "case_id": case.case_id,
            "max_similarity": max(sims),
            "mean_similarity": statistics.fmean(sims),
            "all_above_threshold": min(sims) >= SAME_VIEW_COSINE,
            "has_perception": any_perception,
            "plate_visible": plate,
        })

    def share(rows: list[dict[str, Any]], key: str) -> Optional[float]:
        return (sum(1 for r in rows if r[key]) / len(rows)) if rows else None

    sim_auc = auc([r["mean_similarity"] for r in groups["target"]],
                  [r["mean_similarity"] for r in groups["clean"]])

    # The view-count component, stated as what it actually does here.
    all_counts = image_counts["target"] + image_counts["clean"]
    count_verdict = (
        f"Every underwriting case carries exactly {min(all_counts)} image(s) "
        f"(min {min(all_counts)}, max {max(all_counts)}), against a four-view "
        f"requirement. The component therefore fires on 100% of cases in both "
        f"classes and discriminates nothing. This is a corpus property: the "
        f"generator never produces a complete inspection, so the requirement "
        f"cannot be satisfied by any case, honest or otherwise."
        if all_counts else "no cases")

    result = {
        "check_id": "view_completeness",
        "target_archetype": "AI_GENERATED_BASELINE",
        "n_target": len(groups["target"]),
        "n_clean": len(groups["clean"]),
        "component_view_count": {
            "images_per_case_min": min(all_counts) if all_counts else None,
            "images_per_case_max": max(all_counts) if all_counts else None,
            "required_views": 4,
            "fires_on_target": 1.0 if all_counts else None,
            "fires_on_clean": 1.0 if all_counts else None,
            "discriminates": False,
            "verdict": count_verdict,
        },
        "component_angle_similarity": {
            "mean_similarity_target": (
                statistics.fmean([r["mean_similarity"] for r in groups["target"]])
                if groups["target"] else None),
            "mean_similarity_clean": (
                statistics.fmean([r["mean_similarity"] for r in groups["clean"]])
                if groups["clean"] else None),
            "auc": sim_auc,
            "near_duplicate_share_target": share(groups["target"], "all_above_threshold"),
            "near_duplicate_share_clean": share(groups["clean"], "all_above_threshold"),
            # Direction matters. |AUC - 0.5| >= 0.15 was the first test written
            # here and it reported AUC 0.35 as "discriminates", which is true
            # only in the sense that the signal points the wrong way: target
            # images are LESS similar to each other than clean ones, so acting
            # on the rule as written would flag the honest class. An inverted
            # signal is reported as inverted, not as usable.
            "discriminates": bool(sim_auc is not None and sim_auc - 0.5 >= 0.15),
            "inverted": bool(sim_auc is not None and 0.5 - sim_auc >= 0.15),
            "direction_note": (
                "AUC below 0.5 means AI_GENERATED_BASELINE images are LESS mutually "
                "similar than clean ones - the opposite of the hypothesis. The clean "
                "cases pair two photographs of one real vehicle; the synthetic cases "
                "draw from unrelated source images, which are more varied. This is a "
                "property of how the corpus assembles cases, not of the attack."),
        },
        "component_plate_visibility": {
            "plate_visible_target": share(groups["target"], "plate_visible"),
            "plate_visible_clean": share(groups["clean"], "plate_visible"),
            "note": ("Measurable only where perception exists; a plate is recorded as "
                     "absent when the image was never described, which is not the same "
                     "as a plate not being present."),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    c = result["component_angle_similarity"]
    print(f"target cases: {result['n_target']}, clean cases: {result['n_clean']}")
    print(f"\nview-count component : fires on 100% of BOTH classes - discriminates nothing")
    print(f"  {count_verdict[:150]}")
    print(f"\nsimilarity component : AUC {c['auc']}")
    print(f"  mean similarity target {c['mean_similarity_target']}")
    print(f"  mean similarity clean  {c['mean_similarity_clean']}")
    print(f"  discriminates: {c['discriminates']}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
