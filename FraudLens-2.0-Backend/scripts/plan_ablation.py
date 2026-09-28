"""
Generate outputs/ablation_plan.md from live corpus state.

A plan with hand-typed numbers goes stale the moment perception coverage
moves, and this plan's whole purpose is to be believed about cost. So it is
computed: availability, coverage and budget all come from the database at
the moment of writing.

Nothing is executed here. This produces the design and the bill.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db

OUT = Path("outputs/ablation_plan.md")

# Archetypes whose designated check actually works, with its measured recall
# from outputs/check_performance_v2.md. Only these can support a recall
# claim; the rest have a measured-zero detector and would contribute a row
# of zeroes that says nothing about the adjudicator.
WORKING = {
    "REUSE": ("internal_duplicate", 1.000),
    "EXTERNAL_SOURCING": ("external_corpus", 1.000),
    "METADATA_FORGERY": ("exif_metadata", 0.765),
    "THRESHOLD_GAMING": ("threshold_gaming", 1.000),
    "CONTEXT_MISMATCH": ("scene_consistency", 0.588),
}
NO_WORKING_CHECK = {
    "AI_GENERATED": "ai_generation demoted to weight 0.0 (inverted discriminative value)",
    "DIGITAL_EDIT": "digital_edit measured 0/34 after the generator fix",
    "AI_GENERATED_BASELINE": "no check detects it; see outputs/baseline_signal_measurement.json",
}

FRAUD_PER_ARCHETYPE = 15
CLEAN_TARGET = 25
CALLS_PER_ADJUDICATION = 3.0   # measured mean over the smoke test (10 cases)
DAILY_QUOTA = 100              # 5 keys x 20 requests/key/day, free tier


def wilson_halfwidth(p: float, n: int, z: float = 1.96) -> float:
    """Half-width of a 95% Wilson interval - honest at small n, unlike normal approx."""
    if n == 0:
        return float("nan")
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(centre - (centre - margin), margin)


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(
                     open("data/generated/ground_truth.csv", encoding="utf-8"))}
    cases = {c.case_id: c for c in db.get_all_cases(conn)}
    perceived = {r[0] for r in conn.execute(
        "SELECT DISTINCT i.case_id FROM images i "
        "JOIN perception_records p ON i.content_hash = p.content_hash")}
    images_per_case = dict(conn.execute(
        "SELECT case_id, COUNT(*) FROM images GROUP BY case_id"))

    avail: dict[str, dict[str, int]] = {}
    for case_id, arch in archetype.items():
        if case_id not in cases:
            continue
        row = avail.setdefault(arch, {"total": 0, "perceived": 0, "images": 0,
                                      "unperceived_images": 0})
        row["total"] += 1
        n_img = images_per_case.get(case_id, 0)
        row["images"] += n_img
        if case_id in perceived:
            row["perceived"] += 1
        else:
            row["unperceived_images"] += n_img

    # ---- the sample -------------------------------------------------------
    plan_rows: list[dict[str, Any]] = []
    vision_calls = 0
    for arch, (check_id, recall) in WORKING.items():
        have = avail.get(arch, {"total": 0, "perceived": 0})
        take = min(FRAUD_PER_ARCHETYPE, have["total"])
        # Prefer already-perceived cases; the shortfall needs vision calls.
        need_perception = max(0, take - have["perceived"])
        per_case_images = (have["images"] / have["total"]) if have["total"] else 1
        vision = int(round(need_perception * per_case_images))
        vision_calls += vision
        plan_rows.append({
            "archetype": arch, "check": check_id, "measured_recall": recall,
            "available": have["total"], "perceived_available": have["perceived"],
            "take": take, "vision_calls_needed": vision,
        })

    clean = avail.get("CLEAN", {"total": 0, "perceived": 0, "images": 0})
    clean_take = min(CLEAN_TARGET, clean["total"])
    clean_need = max(0, clean_take - clean["perceived"])
    clean_per_case_images = (clean["images"] / clean["total"]) if clean["total"] else 2
    clean_vision = int(round(clean_need * clean_per_case_images))
    vision_calls += clean_vision

    fraud_take = sum(r["take"] for r in plan_rows)
    total_cases = fraud_take + clean_take
    adjudication_calls = int(round(total_cases * CALLS_PER_ADJUDICATION))
    total_calls = adjudication_calls + vision_calls
    days = math.ceil(total_calls / DAILY_QUOTA)

    write_report(
        plan_rows=plan_rows, avail=avail, clean=clean, clean_take=clean_take,
        clean_vision=clean_vision, fraud_take=fraud_take, total_cases=total_cases,
        adjudication_calls=adjudication_calls, vision_calls=vision_calls,
        total_calls=total_calls, days=days, perceived_total=len(perceived),
        images_total=sum(images_per_case.values()),
    )
    print(f"sample: {total_cases} cases ({fraud_take} fraud + {clean_take} clean)")
    print(f"budget: {adjudication_calls} adjudication + {vision_calls} vision "
          f"= {total_calls} calls ~ {days} day(s) at {DAILY_QUOTA}/day")
    print(f"-> {OUT}")


def write_report(**k: Any) -> None:
    a_ = []
    a = a_.append
    plan_rows = k["plan_rows"]

    a("# Ablation plan — a quota-budgeted experiment")
    a("")
    a("The ablation compares the LLM agent against the rules-only baseline on identical "
      "cases with identical findings. Only the agent arm costs quota: the baseline is "
      "arithmetic and runs the whole corpus in minutes. So the entire budget question is "
      "\"how many cases can the agent adjudicate?\"")
    a("")
    a(f"A full pass is ~{800 * CALLS_PER_ADJUDICATION:.0f} calls at ~{DAILY_QUOTA}/day — "
      f"{math.ceil(800 * CALLS_PER_ADJUDICATION / DAILY_QUOTA)} days, which is not viable. "
      "This is the subset that buys the most defensible claim per call.")
    a("")

    a("## The constraint nobody costed: vision and text share one quota")
    a("")
    a(f"Perception currently covers **{k['perceived_total']} cases** and "
      f"**{k['images_total']} images exist**. Vision calls and adjudication calls draw on "
      "the *same* per-key daily limit, so an unperceived case costs its images in vision "
      "calls **plus** its adjudication calls.")
    a("")
    a("This is not a detail. The agent's one demonstrated advantage over the baseline — "
      "escalating `case-0091` after reading *\"a desert environment with a saguaro cactus\"* "
      "in a scene description — came from reading perception text that no check parses. "
      "Running the ablation on unperceived cases would measure the agent with its only "
      "demonstrated differentiator switched off, and would understate it in a way that "
      "looks like a fair result.")
    a("")

    a("## Current availability")
    a("")
    a("| Archetype | Cases | Perceived | Working check | Measured recall |")
    a("|---|---|---|---|---|")
    for arch in sorted(k["avail"]):
        row = k["avail"][arch]
        if arch in WORKING:
            check, recall = WORKING[arch]
            note = f"`{check}`"
            rec = f"{recall:.1%}"
        elif arch in NO_WORKING_CHECK:
            note = "**none**"
            rec = "—"
        else:
            note = "—"
            rec = "—"
        a(f"| {arch} | {row['total']} | {row['perceived']} | {note} | {rec} |")
    a("")

    a("## The sample")
    a("")
    a(f"All fraud archetypes with a working check, capped at **{FRAUD_PER_ARCHETYPE}** "
      f"cases each, plus **{k['clean_take']}** clean cases. Perceived cases are drawn "
      "first; the shortfall is costed as vision calls below.")
    a("")
    a("| Archetype | Take | Available | Already perceived | Vision calls needed |")
    a("|---|---|---|---|---|")
    for r in plan_rows:
        a(f"| {r['archetype']} | {r['take']} | {r['available']} | "
          f"{r['perceived_available']} | {r['vision_calls_needed']} |")
    a(f"| CLEAN | {k['clean_take']} | {k['clean']['total']} | "
      f"{k['clean']['perceived']} | {k['clean_vision']} |")
    a(f"| **Total** | **{k['total_cases']}** | | | **{k['vision_calls']}** |")
    a("")
    a("Both agent types are represented, but not symmetrically, and the reason is "
      "structural rather than a design choice: the only underwriting *fraud* archetype "
      "is `AI_GENERATED_BASELINE`, which no check detects. Underwriting therefore enters "
      "this sample through its clean cases, and the ablation can say nothing about "
      "underwriting fraud detection. That gap is a corpus property.")
    a("")

    a("## The bill")
    a("")
    a(f"| Item | Calls |")
    a(f"|---|---|")
    a(f"| Adjudication ({k['total_cases']} cases x {CALLS_PER_ADJUDICATION} measured mean) "
      f"| {k['adjudication_calls']} |")
    a(f"| Vision backfill | {k['vision_calls']} |")
    a(f"| **Total** | **{k['total_calls']}** |")
    a(f"| **Days at ~{DAILY_QUOTA}/day** | **{k['days']}** |")
    a("")
    a("The baseline arm adds nothing: it makes no LLM calls.")
    a("")

    a("## What these numbers WILL support")
    a("")
    n = FRAUD_PER_ARCHETYPE
    a(f"- **Per-archetype recall for the five working archetypes**, at n={n} each. "
      f"A 95% Wilson interval at n={n} is roughly "
      f"±{wilson_halfwidth(0.6, n) * 100:.0f}pp near 60% and "
      f"±{wilson_halfwidth(0.9, n) * 100:.0f}pp near 90%. That resolves large "
      "differences between the arms, not small ones.")
    a("- **A direct agent-vs-baseline comparison on identical cases and identical "
      "findings**, which is the actual experiment.")
    a("- **Detection of a gross false-positive regression.** The smoke test's "
      "0/5-cleared result would be unmissable at n="
      f"{k['clean_take']}.")
    a("- **Cost per case**, in calls, tool invocations and latency.")
    a("- **Whether adaptive depth happens**: tool-call rate by evidence strength.")
    a("")

    a("## What they will NOT support — stated before the numbers exist")
    a("")
    a(f"- **The headline false-positive rate.** The baseline's measured 0.56% cannot be "
      f"resolved with {k['clean_take']} clean cases; at that n the 95% interval around a "
      "zero observation still extends past 10%. Distinguishing 0.5% from 2% needs on the "
      "order of a thousand clean cases. **Any FP claim from this run is an upper bound, "
      "not an estimate**, and the two arms' FP rates must not be reported as a difference.")
    a("- **Anything about `AI_GENERATED`, `DIGITAL_EDIT` or `AI_GENERATED_BASELINE`.** "
      "No check detects them, so both arms see the same absence of evidence and the "
      "comparison is vacuous.")
    a("- **Underwriting fraud detection**, for the structural reason above.")
    a("- **Per-garage, per-city or per-amount effects.** n=15 per archetype does not "
      "subdivide.")
    a("- **Generalisation beyond this corpus.** Recall here is recall against archetypes "
      "this project generated, with the defect rate documented in "
      "`outputs/corpus_quality.md`.")
    a("")

    a("## Preconditions")
    a("")
    a("1. **Resolve the clear-rate regression first.** An arm that clears nothing makes "
      "every recall number meaningless; see `outputs/ab_test_prompt.md`. Spending "
      f"{k['total_calls']} calls before that is settled would buy a table that has to be "
      "thrown away.")
    a("2. **Exclude the cases in `data/generated/corpus_exclusions.json`** from the clean "
      "denominator for both arms.")
    a("3. **Draw the sample with `src.sampling.stratified_sample`** at a fixed seed, so "
      "the two arms and any re-run see identical cases.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
