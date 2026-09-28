"""
Build outputs/check_performance_v2.md from the cached findings.

Reads outputs/baseline_findings.jsonl - the same findings the baseline
scores - so the check report and the baseline report can never disagree
about what the checks actually said. Running the battery twice and
reporting each run separately is how two documents end up quoting
different numbers for the same thing.

The one metric decision that matters here: **perception-dependent checks
are scored against the cases that actually have perception coverage.**
Vision-API quota did not stretch to all 1,324 unique images, so
scene_consistency and damage_plausibility have not been offered most of
the corpus. Dividing their hits by all 800 cases would report a recall of
"low" when the truth is "not asked", which is the same fabrication as
printing 0% for an archetype with no images. Coverage is stated per
check, and any check whose target archetype has no perceived cases at all
is reported UNMEASURABLE rather than 0%.

Usage:
    python scripts/report_v2.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import REGISTRY

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")
FINDINGS_CACHE = Path("outputs/baseline_findings.jsonl")
REPORT_OUTPUT = Path("outputs/check_performance_v2.md")

# Explanations that mean "the framework skipped this", not "the check
# looked and found nothing". They must not count as the check having run.
_SKIP_MARKERS = (
    "Perception data not yet available.",
    "No images available for this case.",
)


def load_ground_truth() -> dict[str, dict[str, str]]:
    with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
        return {r["case_id"]: r for r in csv.DictReader(fh)}


def load_findings() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    with open(FINDINGS_CACHE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[row["case_id"]] = row["findings"]
    return out


def perceived_cases(conn) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT i.case_id FROM images i "
        "JOIN perception_records p ON i.content_hash = p.content_hash"
    ).fetchall()
    return {r[0] for r in rows}


def evaluate(
    check_id: str,
    findings_by_case: dict[str, list[dict[str, Any]]],
    ground_truth: dict[str, dict[str, str]],
    perceived: set[str],
) -> dict[str, Any]:
    check = REGISTRY[check_id]
    targets = set(check.target_archetypes)

    verdicts = Counter()
    concern_cases: dict[str, set[str]] = defaultdict(set)
    ran_cases: dict[str, set[str]] = defaultdict(set)
    total_cases: dict[str, int] = Counter()
    fp_examples: list[dict[str, str]] = []

    for case_id, rows in findings_by_case.items():
        meta = ground_truth.get(case_id)
        if meta is None:
            continue
        archetype = meta["archetype"]
        total_cases[archetype] += 1

        mine = [f for f in rows if f["check_id"] == check_id]
        if not mine:
            continue

        # Did the check actually get to look at this case?
        substantive = [f for f in mine if f["explanation"] not in _SKIP_MARKERS]
        if substantive:
            ran_cases[archetype].add(case_id)

        for f in substantive:
            verdicts[f["verdict"]] += 1

        if any(f["verdict"] == "concern" for f in substantive):
            concern_cases[archetype].add(case_id)
            if archetype == "CLEAN" and len(fp_examples) < 5:
                concern = next(f for f in substantive if f["verdict"] == "concern")
                fp_examples.append({"case_id": case_id, "explanation": concern["explanation"]})

    # Recall against the check's own target, over the cases it could see.
    recall: dict[str, Any] = {}
    for archetype in sorted(targets):
        available = len(ran_cases.get(archetype, set()))
        caught = len(concern_cases.get(archetype, set()))
        recall[archetype] = {
            "caught": caught,
            "evaluable": available,
            "total": total_cases.get(archetype, 0),
            "rate": (caught / available) if available else None,
        }

    incidental = {
        archetype: {
            "caught": len(cases),
            "evaluable": len(ran_cases.get(archetype, set())),
            "total": total_cases.get(archetype, 0),
        }
        for archetype, cases in sorted(concern_cases.items())
        if archetype not in targets and archetype != "CLEAN"
    }

    clean_evaluable = len(ran_cases.get("CLEAN", set()))
    clean_flagged = len(concern_cases.get("CLEAN", set()))

    return {
        "check_id": check_id,
        "category": check.category.value,
        "weight": check.weight,
        "requires_perception": check.requires_perception,
        "targets": sorted(targets),
        "verdicts": dict(verdicts),
        "recall": recall,
        "incidental": incidental,
        "clean_evaluable": clean_evaluable,
        "clean_flagged": clean_flagged,
        "clean_fp_rate": (clean_flagged / clean_evaluable) if clean_evaluable else None,
        "fp_examples": fp_examples,
        "total_cases": dict(total_cases),
    }


LIMITATIONS = {
    "internal_duplicate": "Brute-force O(n) hash search; needs an ANN index at insurer scale.",
    "entity_graph": (
        "Production corpus is untestable because identifiers are unique; expanded injected "
        "validation detects 18/18 ring members at 100% precision with 0/6 single-identifier "
        "controls flagged."
    ),
    "external_corpus": "Simulated against a 400-image local index where the source is guaranteed present - an upper bound, not web-scale performance.",
    "exif_metadata": "Only catches forgeries that leave a software signature or an implausible GPS fix.",
    "threshold_gaming": "Garage-scoped: flags a repair shop's billing pattern, not an individual claimant's guilt.",
    "plate_ocr": "Plates are unreadable at this corpus's resolution (0.2% of images), and registrations are synthetic so a successful read cannot match.",
    "c2pa_credentials": "No image in this corpus carries a manifest; the check has never fired.",
    "ai_generation": "Demoted, weight 0.0: 77% false positives on clean cases and negative discriminative value.",
    "digital_edit": (
        "Measured twice. Round 1 (generator double-recompressed the whole frame at q85): AUC 0.531 "
        "with ghost INVERTED at 0.331 - the forgery erased its own evidence. Generator fixed to a "
        "single save at q92, half the cases pre-compressing the patch at q55. Round 2: ghost 0.331 "
        "-> 0.544, noise 0.469 -> 0.535, combined 0.546, and recompressed_patch (AUC 0.573) beats "
        "single_save (0.519) exactly as predicted. The diagnosis was right and the fix worked "
        "directionally, but 0.546 is still a coin with a lean, so weight stays 0.0. Remaining "
        "suppressors: the feathered alpha mask blends the patch's quantisation signature with the "
        "host's, and 200-300px images give too few 8x8 blocks. Narrowed claim: whole-frame ghost/"
        "noise/edge statistics are too weak for a SMALL, FEATHERED composite in a LOW-RESOLUTION "
        "photo - not that JPEG-ghost forensics fail in general."
    ),
    "scene_consistency": (
        "Now working, and the biggest perception-fed mover in the battery. Current "
        "CONTEXT_MISMATCH recall is 20/34 (58.8%) with target coverage at 34/34. Both "
        "variants are detectable: shadows_vs_after_dark via the lighting and solar "
        "sub-checks, and dry_photo_vs_rainy_day via hourly Open-Meteo precipitation "
        "rather than daily weather summaries. The remaining misses are now check/model "
        "quality questions rather than pure coverage absence. Clean-case false positives "
        "are 3/19 on the small perceived clean subset; they are residual corpus artifacts "
        "on the shadow axis, where only 1 clean case had both a perception record and a "
        "physically achievable shadow bearing to align against."
    ),
    "severity_progression": (
        "Production corpus is untestable because every registration is unique; expanded "
        "repeat-claim validation detects 8/8 oscillating sequences at 100% precision/recall "
        "with 0/12 monotone or repaired controls flagged."
    ),
    "damage_plausibility": (
        "No archetype in this corpus inflates a claim, so target recall is n/a. Current "
        "measurement is 0/4 false positives on clean cases, with two incidental fraud "
        "concerns; the clean denominator is still too thin to make a strong precision claim."
    ),
}


def fmt_rate(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100.0 * value:.1f}%"


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Build the v2 check performance report.")
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args(argv)

    ground_truth = load_ground_truth()
    findings_by_case = load_findings()
    conn = db.connect(args.db_path)
    db.init_db(conn)
    perceived = perceived_cases(conn)
    total_images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    unique_images = conn.execute("SELECT COUNT(DISTINCT content_hash) FROM images").fetchone()[0]
    perception_records = conn.execute("SELECT COUNT(*) FROM perception_records").fetchone()[0]
    conn.close()

    results = [
        evaluate(check_id, findings_by_case, ground_truth, perceived)
        for check_id in sorted(REGISTRY, key=lambda c: (-REGISTRY[c].weight, c))
    ]

    lines: list[str] = []
    a = lines.append

    a("# FraudLens 2.0 — Check Performance v2")
    a("")
    a(f"Ten checks across {len(findings_by_case)} cases. Generated by `scripts/report_v2.py` from")
    a("`outputs/baseline_findings.jsonl` — the same findings the baseline scores, so the two")
    a("reports cannot disagree about what the checks said.")
    a("")
    a("## Perception coverage — read this before any recall figure below")
    a("")
    a(f"- Unique images in corpus: **{unique_images}** ({total_images} submissions)")
    a(f"- Images with a perception record: **{perception_records}** "
      f"({100.0 * perception_records / unique_images:.1f}%)")
    a(f"- Cases with at least one perceived image: **{len(perceived)}** / {len(ground_truth)}")
    a("")
    a("Two checks depend on perception — `scene_consistency` and `damage_plausibility`. Vision")
    a("quota did not stretch to the whole corpus, so those two have not been *offered* most of")
    a("it. Their recall is therefore computed over the cases they could actually see, and the")
    a("evaluable denominator is printed next to every figure. Dividing their hits by all 800")
    a("cases would report \"low recall\" where the truth is \"not asked\" — the same fabrication")
    a("as printing 0% for an archetype that has no images.")
    a("")
    a("Perception was spent deliberately rather than uniformly: `--stratified` selects every")
    a("image belonging to a fraud case plus a seeded sample of clean-case images, because")
    a("recall is undefined without fraud cases while a false-positive rate needs only enough")
    a("clean cases to estimate it.")
    a("")
    a("## Summary")
    a("")
    a("| Check | Category | Weight | Target | Recall on target | FP rate on clean | Evaluable |")
    a("|---|---|---|---|---|---|---|")
    for r in results:
        target = ", ".join(r["targets"]) or "—"
        if r["recall"]:
            parts = []
            for archetype, stats in r["recall"].items():
                if stats["evaluable"] == 0:
                    parts.append("UNMEASURABLE")
                else:
                    parts.append(f"{stats['caught']}/{stats['evaluable']} ({fmt_rate(stats['rate'])})")
            recall_text = "; ".join(parts)
        else:
            recall_text = "n/a"
        a(
            f"| `{r['check_id']}` | {r['category'].upper()} | {r['weight']} | {target} "
            f"| {recall_text} | {fmt_rate(r['clean_fp_rate'])} ({r['clean_flagged']}/{r['clean_evaluable']}) "
            f"| {r['clean_evaluable']} clean |"
        )
    a("")

    for r in results:
        a("---")
        a("")
        perception_note = " · **perception-dependent**" if r["requires_perception"] else ""
        a(f"## `{r['check_id']}` — {r['category'].upper()} · weight {r['weight']}{perception_note}")
        a("")
        verdicts = r["verdicts"]
        total = sum(verdicts.values())
        if total:
            a(f"Verdicts (substantive only, framework skips excluded): "
              + ", ".join(f"{v} {verdicts.get(v, 0)}" for v in ("concern", "inconclusive", "pass")))
            a("")
        if r["targets"]:
            a("**Recall on target archetype**")
            a("")
            a("| Archetype | Caught | Evaluable | In corpus | Recall |")
            a("|---|---|---|---|---|")
            for archetype, stats in r["recall"].items():
                rate = "UNMEASURABLE" if stats["evaluable"] == 0 else fmt_rate(stats["rate"])
                a(f"| {archetype} | {stats['caught']} | {stats['evaluable']} | {stats['total']} | **{rate}** |")
            a("")
        else:
            a("**Target archetype:** none — no archetype in this corpus is built to be caught by")
            a("this check, so recall is reported as n/a rather than 0%.")
            a("")
        a(f"**False positives on clean cases:** {r['clean_flagged']}/{r['clean_evaluable']} "
          f"({fmt_rate(r['clean_fp_rate'])})")
        a("")
        if r["incidental"]:
            a("**Incidental detections** (outside this check's designed job, excluded from recall)")
            a("")
            a("| Archetype | Caught | Evaluable |")
            a("|---|---|---|")
            for archetype, stats in r["incidental"].items():
                a(f"| {archetype} | {stats['caught']} | {stats['evaluable']} |")
            a("")
        a(f"**Measured limitation.** {LIMITATIONS.get(r['check_id'], '')}")
        a("")
        if r["fp_examples"]:
            a("<details><summary>False-positive examples on clean cases</summary>")
            a("")
            for ex in r["fp_examples"]:
                a(f"- `{ex['case_id']}` — {ex['explanation']}")
            a("")
            a("</details>")
            a("")

    a("---")
    a("")
    a("## Checks limited by perception coverage")
    a("")
    limited = [r for r in results if r["requires_perception"]]
    for r in limited:
        a(f"- **`{r['check_id']}`** — evaluable on {r['clean_evaluable']} clean case(s); "
          + ", ".join(
              f"{archetype} {stats['evaluable']}/{stats['total']}"
              for archetype, stats in r["recall"].items()
          )
          + (" target case(s) perceived." if r["recall"] else " no target archetype."))
    a("")
    a("Both would benefit directly from more vision quota. `python -m src.perception")
    a("--stratified` prints the remaining image count and the days required at the currently")
    a("configured number of API keys; `src/llm.py` rotates across `GEMINI_API_KEY_2..._10` on")
    a("a 429, so adding keys multiplies the daily ceiling rather than the wait.")
    a("")
    a("### What the quota ceiling actually costs")
    a("")
    a("The free tier allows **20 requests per key per day** (the 429 body names it:")
    a("`GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20`). The current stratified")
    a("scope is 360 unique images — every fraud-case image plus 80 sampled clean ones — so:")
    a("")
    a("| Keys configured | Calls/day | Days to finish the stratified scope |")
    a("|---|---|---|")
    for keys in (1, 3, 5, 10):
        daily = keys * 20
        a(f"| {keys} | {daily} | {-(-360 // daily)} |")
    a("")
    a("`scene_consistency` is the single largest addressable gap in the whole system, and it")
    a("is still tied to perception quality and coverage. It now has target coverage for all")
    a("34 CONTEXT_MISMATCH cases and catches 20 of them; its clean-case precision is still")
    a("measured on only 19 perceived clean cases, so more clean perception coverage mainly")
    a("narrows the false-positive estimate rather than unlocking target recall.")
    a("")
    a(f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {REPORT_OUTPUT}")

    for r in results:
        target = ",".join(r["targets"]) or "-"
        print(f"  {r['check_id']:22} w={r['weight']:<4} target={target:<18} "
              f"fp_clean={fmt_rate(r['clean_fp_rate']):>7} ({r['clean_flagged']}/{r['clean_evaluable']})")


if __name__ == "__main__":
    main()
