"""
Per-check marginal contribution: what does each check add that the others do not?

Standalone performance overstates a check's value. A check with 100% recall on
its archetype contributes nothing if a second check already catches every one
of those cases. The question that matters for a battery is marginal: **remove
this check and re-score — what changes?**

Method: re-score the cached findings with one check's contributions dropped,
at the operating point the sweep chose, and compare against the full battery.
No checks are re-run, so this costs seconds rather than hours and every
variant is scored against identical findings.

Writes outputs/marginal_contribution.md.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src.checks import REGISTRY

FINDINGS = Path("outputs/baseline_findings.jsonl")
SWEEP = Path("outputs/baseline_sweep.json")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")
OUT = Path("outputs/marginal_contribution.md")


def load_findings() -> dict[str, list[dict[str, Any]]]:
    if not FINDINGS.exists():
        raise SystemExit(f"no findings cache at {FINDINGS}")
    out: dict[str, list[dict[str, Any]]] = {}
    for line in FINDINGS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[row["case_id"]] = row["findings"]
    return out


def operating_point() -> dict[str, float]:
    if SWEEP.exists():
        best = json.loads(SWEEP.read_text(encoding="utf-8"))["best"]
        return {"clear_below": best["clear_below"],
                "request_evidence_below": best["request_evidence_below"],
                "desk_review_below": best["desk_review_below"]}
    return {"clear_below": 0.3, "request_evidence_below": 0.8, "desk_review_below": 1.0}


def score(findings: list[dict[str, Any]], drop: Optional[str]) -> float:
    """Weighted sum over CONCERN findings, exactly as the baseline computes it."""
    total = 0.0
    for f in findings:
        if f.get("verdict") != "concern":
            continue
        check_id = f["check_id"]
        if drop is not None and check_id == drop:
            continue
        check = REGISTRY.get(check_id)
        weight = check.weight if check else 0.0
        total += weight * float(f.get("confidence") or 0.0)
    return total


def evaluate(cache: dict[str, list[dict[str, Any]]], archetype: dict[str, str],
             point: dict[str, float], drop: Optional[str]) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    cleared_clean = 0
    for case_id, findings in cache.items():
        arch = archetype.get(case_id)
        if arch is None:
            continue
        s = score(findings, drop)
        flagged = s >= point["clear_below"]
        is_fraud = arch != "CLEAN"
        if is_fraud and flagged:
            tp += 1
        elif is_fraud:
            fn += 1
        elif flagged:
            fp += 1
        else:
            tn += 1
            cleared_clean += 1
    fraud = tp + fn
    clean = fp + tn
    return {
        "recall": tp / fraud if fraud else None,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "fp_rate": fp / clean if clean else None,
        "clean_clear_rate": cleared_clean / clean if clean else None,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def main() -> None:
    cache = load_findings()
    point = operating_point()
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open(GROUND_TRUTH, encoding="utf-8"))}

    full = evaluate(cache, archetype, point, None)

    # Only checks that actually raise concerns can have a marginal effect;
    # the rest are reported separately rather than padding the table with
    # rows of zeros.
    firing = sorted({f["check_id"] for fs in cache.values() for f in fs
                     if f.get("verdict") == "concern"})
    silent = sorted(set(REGISTRY) - set(firing))

    rows = []
    for check_id in firing:
        without = evaluate(cache, archetype, point, check_id)
        rows.append({
            "check": check_id,
            "weight": REGISTRY[check_id].weight if check_id in REGISTRY else None,
            "recall_without": without["recall"],
            "d_recall": (full["recall"] - without["recall"])
            if full["recall"] is not None and without["recall"] is not None else None,
            "d_precision": (full["precision"] - without["precision"])
            if full["precision"] is not None and without["precision"] is not None else None,
            "d_fp": (full["fp_rate"] - without["fp_rate"])
            if full["fp_rate"] is not None and without["fp_rate"] is not None else None,
            "d_clean_clear": (full["clean_clear_rate"] - without["clean_clear_rate"])
            if full["clean_clear_rate"] is not None
            and without["clean_clear_rate"] is not None else None,
            "fraud_lost": without["fn"] - full["fn"],
            "fp_avoided": full["fp"] - without["fp"],
        })
    rows.sort(key=lambda r: -(r["d_recall"] or 0))

    def pct(x: Optional[float]) -> str:
        return "—" if x is None else f"{x:+.2%}"

    a_: list[str] = []
    a = a_.append
    a("# Marginal contribution — what each check adds that the others do not")
    a("")
    a("Standalone recall overstates a check's value: a check catching every case of "
      "its archetype contributes nothing if another check already catches the same "
      "cases. This removes one check at a time, re-scores the cached findings at the "
      "sweep's chosen operating point, and reports what changes.")
    a("")
    a("Note: the clean-case clear rate below is the share of CLEAN cases cleared, "
      "not the corpus-wide straight-through rate the baseline report quotes (69.2%) - "
      "same idea, different denominator, and the clean-case figure is the one a "
      "false-positive analysis needs.")
    a("")
    a(f"Full battery: recall **{full['recall']:.1%}**, precision "
      f"**{full['precision']:.1%}**, false positives on clean **{full['fp_rate']:.1%}**, "
      f"clean-case clear rate **{full['clean_clear_rate']:.1%}**.")
    a("")
    a(f"Operating point: clear below {point['clear_below']}.")
    a("")

    a("## Removing one check at a time")
    a("")
    a("Δ is full battery minus the battery without that check, so a positive Δrecall "
      "means the check is carrying that much recall on its own. Δfp positive means "
      "removing the check would *reduce* false positives.")
    a("")
    a("| Check | Weight | Δ recall | Δ precision | Δ FP rate | Fraud lost | FPs it causes |")
    a("|---|---|---|---|---|---|---|")
    for r in rows:
        a(f"| `{r['check']}` | {r['weight']} | {pct(r['d_recall'])} | "
          f"{pct(r['d_precision'])} | {pct(r['d_fp'])} | {r['fraud_lost']} | "
          f"{r['fp_avoided']} |")
    a("")

    carrying = [r for r in rows if (r["d_recall"] or 0) > 0]
    free = [r for r in rows if (r["d_recall"] or 0) == 0 and (r["d_fp"] or 0) == 0]
    costly = [r for r in rows if (r["d_recall"] or 0) <= 0 and (r["d_fp"] or 0) > 0]

    a("## Reading")
    a("")
    if carrying:
        a("**Checks carrying unique recall.** Removing any of these loses fraud cases "
          "no other check catches:")
        a("")
        for r in carrying:
            a(f"- `{r['check']}` — {r['fraud_lost']} fraud case(s), "
              f"{pct(r['d_recall'])} recall")
        a("")
    if costly:
        a("**Checks costing more than they contribute.** These lose no recall when "
          "removed and their removal reduces false positives:")
        a("")
        for r in costly:
            a(f"- `{r['check']}` — removing it would cut the false-positive rate by "
              f"{abs(r['d_fp'] or 0):.2%} ({r['fp_avoided']} case(s)) at no cost to "
              f"recall.")
        a("")
        a("That is not automatically an argument for removal. A check earning its place "
          "on this corpus is a different question from a check earning its place in "
          "production, and a finding that is *correct but attributed to the wrong "
          "party* — which is what the threshold-band concerns were shown to be — is "
          "fixed by changing what the finding says, not by deleting the detection.")
        a("")
    if free:
        a("**Checks with no marginal effect at this operating point.** They neither "
          "carry recall nor cause false positives here: "
          + ", ".join(f"`{r['check']}`" for r in free) + ".")
        a("")
    if silent:
        a(f"**Checks raising no concerns at all on this corpus** ({len(silent)}): "
          + ", ".join(f"`{c}`" for c in silent) + ".")
        a("")
        a("Their marginal contribution is necessarily zero here, and that is a statement "
          "about the corpus rather than about the checks. Several of them "
          "(`entity_graph`, `severity_progression`, `baseline_linkage`) detect "
          "relationships between cases that this corpus does not contain, and were "
          "measured against injected scenarios instead.")
        a("")

    a("## What this does not establish")
    a("")
    a("Marginal contribution is measured at one operating point. A check contributing "
      "nothing at this threshold could contribute at another, and a check whose recall "
      "overlaps another's here might not overlap on different data.")
    a("")
    a("Removing two checks together is not the sum of removing each alone. Where two "
      "checks cover the same cases, each shows zero marginal contribution "
      "individually while removing both would lose those cases entirely — see "
      "`outputs/check_correlation.md` for which pairs overlap.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")

    print(f"full battery: recall {full['recall']:.1%}, FP {full['fp_rate']:.1%}, "
          f"clean-clear {full['clean_clear_rate']:.1%}")
    for r in rows:
        print(f"  {r['check']:22s} Δrecall {pct(r['d_recall'])}  Δfp {pct(r['d_fp'])}  "
              f"fraud lost {r['fraud_lost']}")
    print(f"silent on this corpus: {', '.join(silent) if silent else 'none'}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
