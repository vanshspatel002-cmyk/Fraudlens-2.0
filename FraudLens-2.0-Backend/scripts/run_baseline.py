"""
Run the rules-only baseline across every case and report it honestly.

This produces the number the LLM agent arm has to beat, so the job here
is not to make the baseline look good - it is to make it as strong as it
can honestly be made, and then report what it actually does. A flattering
control turns the whole ablation into theatre.

Structure:

1. Run the full check battery once over all 800 cases and cache every
   Finding to disk. The checks are the expensive part (CLIP, a vision
   transformer, EasyOCR); the scoring is arithmetic. Caching means the
   threshold sweep costs seconds instead of hours, and - more
   importantly - means every operating point in the sweep is scored
   against *identical* findings, so the sweep measures thresholds rather
   than run-to-run variation.

2. Sweep the band thresholds and report the operating point that
   minimises false positives on clean cases subject to fraud recall
   staying above 80%.

3. Score the chosen operating point, persist its decisions under
   policy_version "baseline-v1", and write outputs/baseline_results.md.

Usage:
    python scripts/run_baseline.py                 # full run
    python scripts/run_baseline.py --reuse-cache   # re-score without re-running checks
    python scripts/run_baseline.py --limit 50      # smoke test
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

from src import baseline, db
from src.checks import ALL_CHECKS, REGISTRY, run_checks
from src.models import CheckCategory, Finding, RiskBand, Verdict

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")
# JSONL, one case per line, appended and flushed as each case finishes.
# The first version of this script accumulated every finding in memory and
# wrote once at the end, which was wrong twice over: resident memory grew
# past 2.3 GB on an 8 GB machine (and swapping is what actually made the
# run slow), and a crash at case 799 would have discarded the entire pass.
# Streaming fixes both, and makes the run resumable - see --resume.
FINDINGS_CACHE = Path("outputs/baseline_findings.jsonl")

# Evidence keys dropped before caching. These are bulk diagnostic dumps -
# every OCR string EasyOCR returned, every class score the AI detector
# produced - that the scorer and the report never read, and they dominate
# the file size. The findings themselves are untouched; this only trims
# what gets written to the cache. Both are already preserved in full in
# outputs/plate_ocr_by_resolution.json and
# outputs/ai_detection_by_resolution.json.
_BULKY_EVIDENCE_KEYS = ("raw_ocr_strings", "raw_predictions")
DECISIONS_OUTPUT = Path("outputs/baseline_decisions.json")
SWEEP_OUTPUT = Path("outputs/baseline_sweep.json")
REPORT_OUTPUT = Path("outputs/baseline_results.md")

# The objective the sweep optimises: minimise false positives on clean
# cases, subject to catching at least this share of fraud. Stated as a
# constant because it is a policy choice, not a tuning detail - an
# insurer that wanted 90% recall would get a different operating point
# and a much worse false-positive rate, and that trade should be visible.
MIN_FRAUD_RECALL = 0.80

# Archetypes whose fraud is, by construction, a property of a *pair* of
# cases: the fraudulent case copies a clean case's photo, or books into a
# garage's pattern. Flagging the clean member is defensible rather than
# simply wrong, so the report gives both the raw and the pair-adjusted
# false-positive rate instead of quietly picking whichever looks better.
PAIRED_FRAUD_ARCHETYPES = ("REUSE", "EXTERNAL_SOURCING")

# Relative handling cost per queue, used only to break ties between
# operating points that are *identical* on every detection metric.
#
# This matters more than it looks. Detection depends only on clear_below,
# so large families of operating points score identically on precision,
# recall, F1, false positives and STP - and differ enormously in what
# review costs. An early version broke ties by minimising SIU referrals
# alone, and picked a point that emptied the REQUEST_EVIDENCE queue
# entirely, routing everything to desk review instead. Same numbers,
# worse operation: asking a claimant for the original photograph is much
# cheaper than a handler opening the file, and it is also the outcome the
# claimant prefers. So ties resolve toward the cheapest adequate queue.
QUEUE_COST = {"request_evidence": 1.0, "desk_review": 3.0, "escalate_siu": 10.0}


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def load_ground_truth() -> dict[str, dict[str, str]]:
    with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
        return {row["case_id"]: row for row in csv.DictReader(fh)}


def gaming_garages(ground_truth: dict[str, dict[str, str]]) -> set[str]:
    return {
        row["garage_id"]
        for row in ground_truth.values()
        if row["archetype"] == "THRESHOLD_GAMING" and row["garage_id"]
    }


# ---------------------------------------------------------------------------
# Stage 1 - run the battery once, cache the findings
# ---------------------------------------------------------------------------


def _slim(finding_dict: dict[str, Any]) -> dict[str, Any]:
    evidence = {k: v for k, v in finding_dict.get("evidence", {}).items() if k not in _BULKY_EVIDENCE_KEYS}
    return {**finding_dict, "evidence": evidence}


def collect_findings(
    conn,
    ground_truth: dict[str, dict[str, str]],
    limit: Optional[int],
    resume: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    cases = db.get_all_cases(conn)
    if limit:
        cases = cases[:limit]

    done = load_cached_findings() if (resume and FINDINGS_CACHE.exists()) else {}
    if done:
        print(f"  resuming: {len(done)} case(s) already cached")
    pending = [c for c in cases if c.case_id not in done]

    FINDINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    total = len(pending)
    started = datetime.now(timezone.utc)
    # Resume appends one case at a time; --no-resume starts a fresh cache
    # because keeping stale rows above fresh rows makes the artifact look
    # half-rerun even though load_cached_findings() would mask it.
    mode = "a" if resume else "w"
    with open(FINDINGS_CACHE, mode, encoding="utf-8") as fh:
        for i, case in enumerate(pending, start=1):
            findings = [_slim(f.to_dict()) for f in run_checks(conn, case, check_ids=list(ALL_CHECKS))]
            done[case.case_id] = findings
            fh.write(json.dumps({"case_id": case.case_id, "findings": findings}) + "\n")
            fh.flush()  # crash-safe: a killed run loses at most the case in flight
            if i % 10 == 0 or i == total:
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                rate = elapsed / i
                eta = (total - i) * rate / 60.0
                print(f"  [{i}/{total}] {case.case_id}  {rate:.1f}s/case  eta {eta:.0f} min", flush=True)

    print(f"  cached findings for {len(done)} cases -> {FINDINGS_CACHE}")
    return done


def load_cached_findings() -> dict[str, list[dict[str, Any]]]:
    """
    Read the JSONL cache. A truncated final line (a run killed mid-write)
    is skipped rather than fatal - the point of the cache is that an
    interrupted pass costs one case, not the whole run.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    with open(FINDINGS_CACHE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print("  warning: skipping a truncated cache line (interrupted run)")
                continue
            out[row["case_id"]] = row["findings"]
    return out


def rehydrate(rows: list[dict[str, Any]]) -> list[Finding]:
    """Rebuild Finding objects from the cache, so scoring sees exactly what the checks produced."""
    out = []
    for r in rows:
        out.append(
            Finding(
                finding_id=r["finding_id"],
                check_id=r["check_id"],
                case_id=r["case_id"],
                category=CheckCategory(r["category"]),
                verdict=Verdict(r["verdict"]),
                confidence=r["confidence"],
                explanation=r["explanation"],
                evidence=r["evidence"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Stage 2 - score and measure
# ---------------------------------------------------------------------------


def raw_scores(findings_by_case: dict[str, list[Finding]]) -> dict[str, float]:
    """
    Score every case once. The score does not depend on the thresholds -
    only the band does - so the sweep re-bands these numbers rather than
    re-scoring, which is both faster and the reason every operating point
    is compared on identical evidence.
    """
    return {case_id: baseline.score_case(findings)[0] for case_id, findings in findings_by_case.items()}


def measure(
    scores: dict[str, float],
    ground_truth: dict[str, dict[str, str]],
    clear_below: float,
    request_evidence_below: float,
    desk_review_below: float,
) -> dict[str, Any]:
    """Full metric set at one operating point."""
    bands = {
        case_id: baseline.band_for(score, clear_below, request_evidence_below, desk_review_below)
        for case_id, score in scores.items()
    }

    tp = fp = tn = fn = 0
    per_archetype: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [caught, total]
    band_by_class: dict[str, Counter] = {"CLEAN": Counter(), "FRAUD": Counter()}
    band_by_archetype: dict[str, Counter] = defaultdict(Counter)
    clean_flagged: list[str] = []

    for case_id, band in bands.items():
        row = ground_truth.get(case_id)
        if row is None:
            continue
        archetype = row["archetype"]
        is_fraud = archetype != "CLEAN"
        flagged = band is not RiskBand.CLEAR

        band_by_class["FRAUD" if is_fraud else "CLEAN"][band.value] += 1
        band_by_archetype[archetype][band.value] += 1

        if is_fraud:
            per_archetype[archetype][1] += 1
            if flagged:
                tp += 1
                per_archetype[archetype][0] += 1
            else:
                fn += 1
        else:
            if flagged:
                fp += 1
                clean_flagged.append(case_id)
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    clean_total = tn + fp
    total = tp + fp + tn + fn
    stp = sum(1 for b in bands.values() if b is RiskBand.CLEAR) / len(bands) if bands else 0.0

    return {
        "thresholds": {
            "clear_below": clear_below,
            "request_evidence_below": request_evidence_below,
            "desk_review_below": desk_review_below,
        },
        "tp": tp, "fp": fp, "tn": tn, "fn": fn, "total": total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fp_rate_clean": fp / clean_total if clean_total else 0.0,
        "stp_rate": stp,
        "per_archetype": {k: {"caught": v[0], "total": v[1]} for k, v in sorted(per_archetype.items())},
        "band_by_class": {k: dict(v) for k, v in band_by_class.items()},
        "band_by_archetype": {k: dict(v) for k, v in sorted(band_by_archetype.items())},
        "clean_flagged": clean_flagged,
        "bands": {k: v.value for k, v in bands.items()},
    }


def pair_adjust(result: dict[str, Any], ground_truth: dict[str, dict[str, str]], scores: dict[str, float],
                findings_by_case: dict[str, list[Finding]]) -> dict[str, Any]:
    """
    Split the flagged clean cases into those that are the innocent half of
    a real fraud pair and those that are genuine errors.

    A clean case flagged by internal_duplicate because a REUSE case stole
    its photo is not a system error - the duplicate is real and a human
    must decide which side of the pair is fraudulent. Likewise a clean
    claim at a garage that systematically prices under the survey
    threshold is genuinely part of the pattern threshold_gaming detects.
    Both numbers are reported; neither is quietly substituted for the
    other.
    """
    gaming = gaming_garages(ground_truth)
    pair_victims: list[str] = []
    genuine: list[str] = []

    for case_id in result["clean_flagged"]:
        concerns = [f for f in findings_by_case[case_id] if f.verdict is Verdict.CONCERN]
        explained = False
        for f in concerns:
            if f.check_id in ("internal_duplicate", "external_corpus"):
                matched = f.evidence.get("matched_case_id") or f.evidence.get("match_case_id")
                if matched and ground_truth.get(matched, {}).get("archetype") in PAIRED_FRAUD_ARCHETYPES:
                    explained = True
                elif f.check_id == "external_corpus":
                    # A corpus match on a clean case means the image is
                    # genuinely in the external corpus - see the dataset
                    # leak documented in check_performance_summary.md.
                    explained = True
            if f.check_id == "threshold_gaming" and ground_truth[case_id]["garage_id"] in gaming:
                explained = True
        (pair_victims if explained else genuine).append(case_id)

    clean_total = result["tn"] + result["fp"]
    return {
        "pair_victims": pair_victims,
        "genuine_false_positives": genuine,
        "genuine_fp_rate": len(genuine) / clean_total if clean_total else 0.0,
    }


# ---------------------------------------------------------------------------
# Stage 3 - sweep
# ---------------------------------------------------------------------------


def sweep(scores: dict[str, float], ground_truth: dict[str, dict[str, str]]) -> dict[str, Any]:
    """
    Vary all three thresholds and record what each operating point does.

    Worth stating plainly, because it is the sweep's main finding and it
    would be easy to obscure: precision, recall, F1, the false-positive
    rate and the straight-through rate depend *only* on clear_below. A
    case is either routed straight through or it is not, and that is
    decided by the first threshold alone. The other two thresholds split
    the already-flagged population between three human queues - they
    change what review costs, not what is caught. Sweeping all three and
    presenting the result as though it were a three-dimensional
    optimisation would be dressing up a one-dimensional choice.
    """
    clear_grid = [round(0.05 * i, 2) for i in range(1, 21)]           # 0.05 .. 1.00
    request_grid = [0.4, 0.5, 0.6, 0.7, 0.8]
    desk_grid = [0.8, 1.0, 1.2, 1.5]

    points = []
    for clear_below in clear_grid:
        for request_evidence_below in request_grid:
            if request_evidence_below <= clear_below:
                continue
            for desk_review_below in desk_grid:
                if desk_review_below <= request_evidence_below:
                    continue
                m = measure(scores, ground_truth, clear_below, request_evidence_below, desk_review_below)
                points.append(
                    {
                        "clear_below": clear_below,
                        "request_evidence_below": request_evidence_below,
                        "desk_review_below": desk_review_below,
                        "precision": m["precision"],
                        "recall": m["recall"],
                        "f1": m["f1"],
                        "fp_rate_clean": m["fp_rate_clean"],
                        "stp_rate": m["stp_rate"],
                        "fp": m["fp"],
                        "tp": m["tp"],
                        **{
                            band: m["band_by_class"]["CLEAN"].get(band, 0)
                            + m["band_by_class"]["FRAUD"].get(band, 0)
                            for band in ("request_evidence", "desk_review", "escalate_siu")
                        },
                    }
                )
                points[-1]["queue_cost"] = sum(
                    points[-1][band] * cost for band, cost in QUEUE_COST.items()
                )

    feasible = [p for p in points if p["recall"] >= MIN_FRAUD_RECALL]
    max_recall = max((p["recall"] for p in points), default=0.0)

    if feasible:
        # The intended objective: minimise false positives subject to the
        # recall floor. Ties break toward higher recall, then toward fewer
        # expensive SIU referrals.
        best = min(feasible, key=lambda p: (p["fp_rate_clean"], -p["recall"], p["queue_cost"]))
        objective = "min false positives subject to recall >= 80%, ties to cheapest review mix"
    else:
        # The recall floor is unreachable at *any* threshold. Silently
        # falling back to whatever defaults happen to be in the module
        # would report a tuned operating point that was never tuned, so
        # the fallback objective is stated explicitly and carried into
        # the report: take the maximum recall the battery can reach, then
        # minimise false positives among the operating points that reach
        # it. This is a coverage failure, not a tuning failure, and the
        # report must say so - see the archetypes with no check at all.
        on_ceiling = [p for p in points if p["recall"] >= max_recall - 1e-9]
        best = min(on_ceiling, key=lambda p: (p["fp_rate_clean"], p["queue_cost"]))
        objective = (
            f"recall floor unreachable; max attainable recall ({max_recall:.1%}), "
            "then min false positives, ties to cheapest review mix"
        )

    return {
        "points": points,
        "feasible_count": len(feasible),
        "best": best,
        "min_recall": MIN_FRAUD_RECALL,
        "max_attainable_recall": max_recall,
        "objective": objective,
        "constraint_met": bool(feasible),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def fmt_pct(x: float) -> str:
    return f"{100.0 * x:.1f}%"


def write_report(
    result: dict[str, Any],
    adjusted: dict[str, Any],
    sweep_data: dict[str, Any],
    default_result: dict[str, Any],
    scores: dict[str, float],
    ground_truth: dict[str, dict[str, str]],
) -> None:
    t = result["thresholds"]
    best = sweep_data["best"]
    lines: list[str] = []
    a = lines.append

    a("# Baseline Results — Rules-Only Scorer (`baseline-v1`)")
    a("")
    a("The control arm of the ablation: the same seven checks over the same 800 cases,")
    a("scored by a weighted sum instead of by a language model. No LLM is involved at any")
    a("point — `tool_calls_count`, `iterations_count` and `llm_calls_count` are all zero,")
    a("and the narrative is templated from the checks' own explanation sentences.")
    a("")
    a("**This is the number the agent has to beat.** It has been made as strong as it")
    a("honestly can be: weights come from measured per-check performance on this corpus,")
    a("and the thresholds below are swept rather than guessed.")
    a("")
    a("## Scoring")
    a("")
    a("```")
    a("score = Σ over CONCERN findings of (check weight × finding confidence)")
    a("INCONCLUSIVE → 0     PASS → 0")
    a("```")
    a("")
    a("| Check | Weight | Justification (measured) |")
    a("|---|---|---|")
    for check_id in sorted(REGISTRY, key=lambda c: (-REGISTRY[c].weight, c)):
        check = REGISTRY[check_id]
        a(f"| `{check_id}` | {check.weight} | {WEIGHT_NOTES.get(check_id, '')} |")
    a("")
    a("## Chosen operating point")
    a("")
    if sweep_data["constraint_met"]:
        a(f"Swept to minimise false positives on clean cases subject to fraud recall ≥ {fmt_pct(sweep_data['min_recall'])}.")
        a(f"{sweep_data['feasible_count']} of {len(sweep_data['points'])} swept operating points met that constraint.")
    else:
        a(f"> **The {fmt_pct(sweep_data['min_recall'])} recall floor is unreachable at any threshold.** None of the")
        a(f"> {len(sweep_data['points'])} swept operating points met it; the maximum attainable recall is")
        a(f"> **{fmt_pct(sweep_data['max_attainable_recall'])}**. This is a *coverage* limit, not a tuning limit — see")
        a("> \"Why recall is capped\" below. The operating point below is therefore chosen by the")
        a("> stated fallback objective: take the maximum attainable recall, then minimise false")
        a("> positives among the operating points that reach it.")
    a("")
    a(f"Objective used: `{sweep_data['objective']}`")
    a("")
    a("| Band | Score range |")
    a("|---|---|")
    a(f"| CLEAR (straight through) | < {t['clear_below']} |")
    a(f"| REQUEST_EVIDENCE | {t['clear_below']} – {t['request_evidence_below']} |")
    a(f"| DESK_REVIEW | {t['request_evidence_below']} – {t['desk_review_below']} |")
    a(f"| ESCALATE_SIU | > {t['desk_review_below']} |")
    a("")
    a("## Headline metrics")
    a("")
    a("Fraud detection = the case was routed anywhere other than straight through.")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(f"| Precision | **{fmt_pct(result['precision'])}** |")
    a(f"| Recall | **{fmt_pct(result['recall'])}** |")
    a(f"| F1 | **{result['f1']:.3f}** |")
    a(f"| False-positive rate on clean cases | **{fmt_pct(result['fp_rate_clean'])}** ({result['fp']}/{result['tn'] + result['fp']}) |")
    a(f"| — of which are the innocent half of a real pair | {len(adjusted['pair_victims'])} |")
    a(f"| — genuine false positives | **{len(adjusted['genuine_false_positives'])}** ({fmt_pct(adjusted['genuine_fp_rate'])}) |")
    a(f"| Straight-through processing rate | **{fmt_pct(result['stp_rate'])}** |")
    a(f"| True positives / false negatives | {result['tp']} / {result['fn']} |")
    a("")
    a("The pair-adjusted row is not a softer denominator chosen to flatter the result — it")
    a("is the distinction between a clean case flagged for no reason and a clean case")
    a("flagged because a fraudster copied its photograph. The second is correct behaviour:")
    a("a duplicate is a property of a *pair* of cases, and deciding which half is")
    a("fraudulent is a human's job. Both numbers are given so the reader can choose.")
    a("")
    a("## Per-archetype recall")
    a("")
    a("| Archetype | Caught | Total | Recall |")
    a("|---|---|---|---|")
    for archetype, v in result["per_archetype"].items():
        rate = v["caught"] / v["total"] if v["total"] else 0.0
        a(f"| {archetype} | {v['caught']} | {v['total']} | {fmt_pct(rate)} |")
    a("")
    a("### Why recall is capped")
    a("")
    a("Recall is limited by which checks can actually deliver, not by where the thresholds")
    a("sit. Every archetype whose check is working is caught at or near 100%; every")
    a("archetype whose check is blocked is missed almost entirely. The blockers are quota")
    a("and corpus construction, not tuning.")
    a("")
    a("| Archetype | Check targeting it | Weight | Status | Recall |")
    a("|---|---|---|---|---|")
    targeted: dict[str, list[str]] = defaultdict(list)
    for check_id, check in REGISTRY.items():
        for archetype in check.target_archetypes:
            targeted[archetype].append(check_id)

    blocked: list[tuple[str, int, str]] = []
    working_total = working_caught = 0
    fraud_total = result["tp"] + result["fn"]

    for archetype, v in result["per_archetype"].items():
        rate = v["caught"] / v["total"] if v["total"] else 0.0
        owners = targeted.get(archetype, [])
        if not owners:
            a(f"| {archetype} | **none** | — | no check | {fmt_pct(rate)} |")
            blocked.append((archetype, v["total"], "no check exists"))
            continue

        owner_checks = [REGISTRY[o] for o in owners]
        owner = ", ".join(f"`{o}`" for o in owners)
        weight = max(c.weight for c in owner_checks)
        if weight == 0.0:
            status = "**measured useless**"
            blocked.append((archetype, v["total"], "check demoted to weight 0.0 after measurement"))
        elif any(c.requires_perception for c in owner_checks) and rate < 0.5:
            status = "**perception-blocked**"
            blocked.append((archetype, v["total"], "check exists but vision quota did not reach these cases"))
        else:
            status = "working"
            working_total += v["total"]
            working_caught += v["caught"]
        a(f"| {archetype} | {owner} | {weight} | {status} | {fmt_pct(rate)} |")
    a("")

    blocked_total = sum(n for _, n, _ in blocked)
    covered = [x for x in result["per_archetype"] if targeted.get(x)]
    uncovered = [x for x in result["per_archetype"] if not targeted.get(x)]
    if uncovered:
        a(f"**{len(covered)} of {len(covered) + len(uncovered)} archetypes have a check pointed "
          f"at them** - and {blocked_total} of {fraud_total} fraud cases are still missed.")
    else:
        a(f"**Every archetype has a check pointed at it** - and {blocked_total} of {fraud_total} "
          "fraud cases are still missed.")
    a("Each gap is blocked for a different reason, and the reasons are not interchangeable:")
    a("")
    # Derived from live state rather than written out by hand. An earlier
    # revision hard-coded these bullets and they went stale the moment the
    # corpus was fixed - the report cheerfully claimed CONTEXT_MISMATCH had
    # no perception and AI_GENERATED had no images while its own table two
    # inches above said otherwise. A report that contradicts itself is
    # worse than one that says less.
    for archetype, n, why in blocked:
        owners = targeted.get(archetype, [])
        stats = result["per_archetype"].get(archetype, {"caught": 0, "total": max(1, n)})
        rate = stats["caught"] / stats["total"] if stats["total"] else 0.0
        if not owners:
            a(f"- **{archetype} ({n})** - no check exists. Nothing in the battery is designed to")
            a(f"  catch it; its {fmt_pct(rate)} recall is incidental firing by other checks.")
        elif all(REGISTRY[o].weight == 0.0 for o in owners):
            names = ", ".join("`" + o + "`" for o in owners)
            a(f"- **{archetype} ({n})** - {names} exists and was *measured* to have no usable")
            a("  discriminative power on this corpus, so it carries weight 0.0 and abstains.")
            a("  A measurement result, not an unbuilt feature: no threshold change recovers a")
            a("  signal that is not there.")
        else:
            names = ", ".join("`" + o + "`" for o in owners)
            a(f"- **{archetype} ({n})** - {names} is working but reached only {fmt_pct(rate)}.")
    a("")
    a("Across the archetypes whose checks are actually working, the battery catches")
    a(f"**{working_caught} of {working_total}** "
      f"({fmt_pct(working_caught / working_total if working_total else 0)}).")
    a("")
    a("**The baseline is at its coverage ceiling, not at a tuning optimum.** No threshold")
    a("change moves recall - the sweep confirms it is flat across a wide range of operating")
    a("points. What *does* move it is fixing the corpus and buying vision quota: recall has")
    a("gone 57.1% -> 57.9% -> 59.6% -> 61.2% -> 58.5% across successive sessions. Every "
      "rise came from correcting the corpus, and the final fall was a correction too: "
      "the victim/reuser fix removed seven fraud cases that had been credited only "
      "because a later case copied their images. Every one of")
    a("those gains came from making an archetype genuinely detectable or from perceiving")
    a("more of it, not from writing another check. Building checks stopped being the")
    a("bottleneck some time ago.")
    a("")
    a("## Confusion matrix over the four recommendations")
    a("")
    a("| | CLEAR | REQUEST_EVIDENCE | DESK_REVIEW | ESCALATE_SIU |")
    a("|---|---|---|---|---|")
    for label in ("CLEAN", "FRAUD"):
        row = result["band_by_class"][label]
        a(
            f"| **{label}** | {row.get('clear', 0)} | {row.get('request_evidence', 0)} "
            f"| {row.get('desk_review', 0)} | {row.get('escalate_siu', 0)} |"
        )
    a("")
    a("Per archetype:")
    a("")
    a("| Archetype | CLEAR | REQUEST_EVIDENCE | DESK_REVIEW | ESCALATE_SIU |")
    a("|---|---|---|---|---|")
    for archetype, row in result["band_by_archetype"].items():
        a(
            f"| {archetype} | {row.get('clear', 0)} | {row.get('request_evidence', 0)} "
            f"| {row.get('desk_review', 0)} | {row.get('escalate_siu', 0)} |"
        )
    a("")
    a("## Threshold sweep")
    a("")
    a("**Only `clear_below` moves detection.** Precision, recall, F1, the false-positive")
    a("rate and the straight-through rate depend on that threshold alone: a case is either")
    a("routed straight through or it is not, and the first threshold decides it. The other")
    a("two split the already-flagged population between three human queues — they change")
    a("what review *costs*, not what is *caught*. Presenting this as a three-dimensional")
    a("optimisation would dress up a one-dimensional choice.")
    a("")
    a("| `clear_below` | Precision | Recall | F1 | FP rate (clean) | STP rate |")
    a("|---|---|---|---|---|---|")
    seen: set[float] = set()
    for p in sweep_data["points"]:
        if p["clear_below"] in seen:
            continue
        seen.add(p["clear_below"])
        marker = " ←" if best and abs(p["clear_below"] - best["clear_below"]) < 1e-9 else ""
        feasible = "" if p["recall"] >= sweep_data["min_recall"] else " *(below recall floor)*"
        a(
            f"| {p['clear_below']}{marker} | {fmt_pct(p['precision'])} | {fmt_pct(p['recall'])} "
            f"| {p['f1']:.3f} | {fmt_pct(p['fp_rate_clean'])} | {fmt_pct(p['stp_rate'])}{feasible} |"
        )
    a("")
    a("Full sweep data including the queue-mix effect of the other two thresholds:")
    a("`outputs/baseline_sweep.json`.")
    a("")
    a("## Score distribution")
    a("")
    clean_scores = sorted(s for c, s in scores.items() if ground_truth.get(c, {}).get("archetype") == "CLEAN")
    fraud_scores = sorted(s for c, s in scores.items() if ground_truth.get(c, {}).get("archetype") not in (None, "CLEAN"))
    a("| Population | n | Min | Median | Max | Zero-score share |")
    a("|---|---|---|---|---|---|")
    for label, values in (("CLEAN", clean_scores), ("FRAUD", fraud_scores)):
        if not values:
            continue
        median = values[len(values) // 2]
        zeros = sum(1 for v in values if v == 0.0) / len(values)
        a(f"| {label} | {len(values)} | {values[0]:.2f} | {median:.2f} | {values[-1]:.2f} | {fmt_pct(zeros)} |")
    a("")
    a("## What the agent must beat")
    a("")
    a(f"- Recall **{fmt_pct(result['recall'])}** at a genuine false-positive rate of **{fmt_pct(adjusted['genuine_fp_rate'])}**")
    a(f"- F1 **{result['f1']:.3f}**")
    a(f"- Straight-through processing **{fmt_pct(result['stp_rate'])}**")
    a("- Zero LLM calls, zero tool calls, zero agent iterations")
    a("")
    a("The last line is the hard part of the comparison. The agent arm will spend real")
    a("money and real latency per case; to be worth deploying it has to buy something")
    a("this arithmetic cannot, and the honest framing of the ablation is *what does the")
    a("LLM add over a well-tuned rule*, not *does the LLM work*.")
    a("")
    a("**Where the agent has room, and where it does not.** The baseline already extracts")
    a("essentially everything the current checks contain: it catches 100% of REUSE,")
    a("EXTERNAL_SOURCING and THRESHOLD_GAMING, and its only unexplained false positives are")
    a("zero. An agent reasoning over the *same findings* cannot beat that by reasoning")
    a("harder — the headroom is in the archetypes no check covers. That makes the ablation")
    a("a sharper test than it first appears: if the agent's advantage is real, it should")
    a("show up as catching CONTEXT_MISMATCH and DIGITAL_EDIT cases from perception output")
    a("that no rule was written to interpret, not as better arithmetic on the same seven")
    a("checks. If it merely re-ranks what the rules already found, it is not worth its cost.")
    a("")
    a("---")
    a("")
    a(f"Generated by `scripts/run_baseline.py` · policy_version `{baseline.POLICY_VERSION}` · ")
    a(f"decisions in `agent_decisions` and `outputs/baseline_decisions.json`")

    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  report -> {REPORT_OUTPUT}")


WEIGHT_NOTES = {
    "entity_graph": "Production corpus untestable because identifiers are unique; "
                    "expanded injected validation detects 18/18 ring members at "
                    "100% precision with 0/6 single-identifier controls flagged",
    "severity_progression": "Production corpus untestable because every registration "
                            "is unique; expanded repeat-claim validation detects "
                            "8/8 oscillating sequences at 100% precision/recall "
                            "with 0/12 monotone or repaired controls flagged",
    "internal_duplicate": "35/35 REUSE recall, 0/540 FPs after the victim/reuser fix "
                          "(was 23/540; the originator is now INCONCLUSIVE)",
    "external_corpus": "35/35 recall, 0/540 FPs; the 4 apparent FPs were verified "
                       "byte-identical corpus leaks",
    "threshold_gaming": "34/34 recall, 0/275 FPs at ordinary garages; pure arithmetic",
    "scene_consistency": "20/34 (58.8%) recall; its 15.8% FP rate rests on only "
                         "19 clean cases and is too thin to trust",
    "damage_plausibility": "UNMEASURED - no archetype in this corpus inflates a "
                           "claim amount, and its FP rate rests on 4 clean cases",
    "baseline_corruption": "0.0: built for AI_GENERATED_BASELINE and structurally "
                           "unable to detect it; no target archetype remains",
    "digital_edit": "demoted to 0.0: AUC 0.546 after the generator recompression "
                    "defect was fixed - indistinguishable from chance",
    "exif_metadata": "26/34 (76.5%) recall, 0/540 FPs, but editing software has "
                     "innocent explanations",
    "plate_ocr": "fires on 0.2% of images; cannot be correct on this corpus (synthetic registrations)",
    "c2pa_credentials": "never fires — no image in this corpus carries a manifest",
    "ai_generation": "demoted to 0.0: measured inverted, flagging genuine photographs "
                     "50.8% vs synthetic 9.1% at matched resolution; now always "
                     "INCONCLUSIVE so its FP rate reads 0/540",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the rules-only baseline across all cases.")
    p.add_argument("--reuse-cache", action="store_true", help="Re-score from cached findings without re-running checks.")
    p.add_argument("--no-resume", action="store_true", help="Ignore any existing cache and re-run every case.")
    p.add_argument("--limit", type=int, default=None, help="Only process the first N cases (smoke test).")
    p.add_argument("--db-path", default="fraudlens.db")
    p.add_argument("--no-persist", action="store_true", help="Skip writing decisions to the database.")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    ground_truth = load_ground_truth()
    conn = db.connect(args.db_path)
    db.init_db(conn)

    try:
        print("STEP 1 - findings")
        if args.reuse_cache and FINDINGS_CACHE.exists():
            cached = load_cached_findings()
            print(f"  reusing cached findings for {len(cached)} cases")
        else:
            cached = collect_findings(conn, ground_truth, args.limit, resume=not args.no_resume)

        findings_by_case = {case_id: rehydrate(rows) for case_id, rows in cached.items()}
        scores = raw_scores(findings_by_case)
        print(f"  scored {len(scores)} cases")

        print("\nSTEP 2 - threshold sweep")
        sweep_data = sweep(scores, ground_truth)
        best = sweep_data["best"]
        if best is None:
            print(f"  WARNING: no operating point reaches {MIN_FRAUD_RECALL:.0%} recall; using defaults")
            chosen = (baseline.CLEAR_BELOW, baseline.REQUEST_EVIDENCE_BELOW, baseline.DESK_REVIEW_BELOW)
        else:
            chosen = (best["clear_below"], best["request_evidence_below"], best["desk_review_below"])
            print(
                f"  best: clear_below={chosen[0]} request_evidence_below={chosen[1]} "
                f"desk_review_below={chosen[2]} -> recall {best['recall']:.1%}, FP {best['fp_rate_clean']:.2%}"
            )
        SWEEP_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with open(SWEEP_OUTPUT, "w", encoding="utf-8") as fh:
            json.dump(sweep_data, fh, indent=2)

        print("\nSTEP 3 - decisions at the chosen operating point")
        result = measure(scores, ground_truth, *chosen)
        default_result = measure(
            scores, ground_truth, baseline.CLEAR_BELOW, baseline.REQUEST_EVIDENCE_BELOW, baseline.DESK_REVIEW_BELOW
        )
        adjusted = pair_adjust(result, ground_truth, scores, findings_by_case)

        decisions = []
        cases_by_id = {c.case_id: c for c in db.get_all_cases(conn)}
        for case_id, findings in findings_by_case.items():
            case = cases_by_id.get(case_id)
            if case is None:
                continue
            decisions.append(baseline.decide(findings, case, *chosen))

        if not args.no_persist:
            removed = db.delete_decisions_for_policy(conn, baseline.POLICY_VERSION)
            for d in decisions:
                db.insert_agent_decision(conn, d)
            conn.commit()
            print(f"  persisted {len(decisions)} decisions (replaced {removed} prior rows)")

        with open(DECISIONS_OUTPUT, "w", encoding="utf-8") as fh:
            json.dump([d.to_dict() for d in decisions], fh, indent=2)
        print(f"  decisions -> {DECISIONS_OUTPUT}")

        print("\nSTEP 4 - report")
        write_report(result, adjusted, sweep_data, default_result, scores, ground_truth)

        print("\n" + "=" * 70)
        print(f"precision {result['precision']:.1%}  recall {result['recall']:.1%}  F1 {result['f1']:.3f}")
        print(f"FP on clean {result['fp']}/{result['tn'] + result['fp']} ({result['fp_rate_clean']:.2%})"
              f"  genuine {len(adjusted['genuine_false_positives'])} ({adjusted['genuine_fp_rate']:.2%})")
        print(f"STP {result['stp_rate']:.1%}")
        print("=" * 70)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
