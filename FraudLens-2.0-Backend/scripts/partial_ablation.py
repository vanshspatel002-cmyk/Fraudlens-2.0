"""
Partial ablation — a defensible comparison from an incomplete agent arm.

--------------------------------------------------------------------------
What this is, and what it is not
--------------------------------------------------------------------------
The agent arm is quota-bound and may not finish. This is **insurance**, not a
substitute: it reports both arms on exactly the cases where *both* have run,
so the comparison is paired and honest, and it states plainly what that
sample can and cannot establish.

The full ablation, if it completes, supersedes this entirely. The report
should say which one it is quoting.

--------------------------------------------------------------------------
Three rules it enforces
--------------------------------------------------------------------------
1. **Paired only.** A case counts only if both arms adjudicated it.
   Comparing a 12-case agent arm against a 99-case baseline measures which
   cases were sampled, not which adjudicator is better.

2. **Cells below n=10 support no inference.** They are printed - hiding a
   thin cell is worse than showing it - but marked, and no percentage from
   them is quoted as a finding. This is the discipline the smoke test
   lacked when it drew five clean cases that were all underwriting.

3. **A difference gets an interval.** The recall difference is reported with
   a bootstrap 95% CI over the paired cases. On samples this size the
   interval will usually straddle zero, and saying so is the point: "the
   agent scored higher on these n cases, and this sample cannot establish
   that the difference is real" is a defensible sentence. "The agent beat
   the baseline by 12 points" is not.

Provider-outage rows are excluded, using the same rule as the full report: a
case cut off mid-reasoning by the free tier took a fallback band that belongs
to the outage, not the agent.

Usage:
    python scripts/partial_ablation.py
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

RESULTS = Path("outputs/ablation_results.jsonl")
EXCLUSIONS = Path("data/generated/corpus_exclusions.json")
REPORT = Path("outputs/partial_ablation.md")

MIN_CELL = 10          # below this, a cell is reported but not interpreted
BOOTSTRAP_SAMPLES = 10_000
SEED = 42


def load_rows() -> list[dict[str, Any]]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_exclusions() -> set[str]:
    if not EXCLUSIONS.exists():
        return set()
    try:
        return set(json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
                   .get("excluded_case_ids", []))
    except json.JSONDecodeError:
        return set()


def is_outage(row: dict[str, Any]) -> bool:
    for step in row.get("trace") or []:
        if step.get("kind") == "fallback" and "provider error" in (step.get("detail") or ""):
            return True
    return False


def flagged(row: dict[str, Any]) -> bool:
    """Anything other than CLEAR costs a human touch."""
    return row.get("risk_band") != "clear"


def bootstrap_recall_difference(
    paired: list[tuple[dict[str, Any], dict[str, Any]]],
    rng: random.Random,
) -> Optional[dict[str, float]]:
    """
    95% CI on (agent recall − baseline recall), resampling *cases*.

    Paired resampling, not two independent draws: both arms saw the same
    cases and the same findings, so the pairing is real information and
    throwing it away would widen the interval for no reason.
    """
    fraud = [(b, a) for b, a in paired if b["is_fraud"]]
    if len(fraud) < 2:
        return None

    def recall_diff(sample: list[tuple[dict, dict]]) -> float:
        n = len(sample)
        base = sum(1 for b, _ in sample if flagged(b)) / n
        agent = sum(1 for _, a in sample if flagged(a)) / n
        return agent - base

    observed = recall_diff(fraud)
    diffs = []
    for _ in range(BOOTSTRAP_SAMPLES):
        draw = [fraud[rng.randrange(len(fraud))] for _ in range(len(fraud))]
        diffs.append(recall_diff(draw))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return {"observed": observed, "lo": lo, "hi": hi, "n": len(fraud)}


def cell_stats(pairs: list[tuple[dict, dict]]) -> dict[str, Any]:
    fraud = [(b, a) for b, a in pairs if b["is_fraud"]]
    clean = [(b, a) for b, a in pairs if not b["is_fraud"]]
    def rate(rows, idx):
        return (sum(1 for p in rows if flagged(p[idx])) / len(rows)) if rows else None
    return {
        "n": len(pairs), "fraud_n": len(fraud), "clean_n": len(clean),
        "baseline_recall": rate(fraud, 0), "agent_recall": rate(fraud, 1),
        "baseline_fp": rate(clean, 0), "agent_fp": rate(clean, 1),
        # Judged per metric, not on the cell total. Recall depends only on the
        # fraud rows and the false-positive rate only on the clean ones, so a
        # cell can easily be large enough for one and useless for the other.
        "recall_interpretable": len(fraud) >= MIN_CELL,
        "fp_interpretable": len(clean) >= MIN_CELL,
    }


def pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.0%}"


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    rows = load_rows()
    excluded = load_exclusions()
    baseline = {r["case_id"]: r for r in rows if r["arm"] == "baseline"}
    agent = {r["case_id"]: r for r in rows if r["arm"] == "agent" and not is_outage(r)}
    outages = sum(1 for r in rows if r["arm"] == "agent" and is_outage(r))

    shared = sorted(set(baseline) & set(agent) - excluded)
    paired = [(baseline[c], agent[c]) for c in shared]

    rng = random.Random(SEED)
    ci = bootstrap_recall_difference(paired, rng)

    cells: dict[str, dict[str, Any]] = {}
    for agent_type in ("claims", "underwriting"):
        subset = [(b, a) for b, a in paired if b["agent_type"] == agent_type]
        if subset:
            cells[agent_type] = cell_stats(subset)

    lines: list[str] = []
    a = lines.append
    a("# Partial ablation — paired comparison on completed cases")
    a("")
    a("**This is insurance, not the experiment.** The full ablation "
      "(`outputs/ablation_results.md`) supersedes this the moment the agent arm "
      "completes. It exists so the report has a defensible result even if the free "
      "tier never allows the arm to finish.")
    a("")
    a(f"- Baseline arm: **{len(baseline)}** case(s)")
    a(f"- Agent arm: **{len(agent)}** case(s)"
      + (f" (plus {outages} excluded as provider outages)" if outages else ""))
    a(f"- **Paired and scored: {len(paired)}**"
      + (f", after dropping {len(set(baseline) & set(agent) & excluded)} "
         "case(s) flagged by the label audit"
         if (set(baseline) & set(agent) & excluded) else ""))
    a("")
    a("Only cases **both** arms adjudicated are counted. Scoring a partial agent arm "
      "against a complete baseline would measure which cases happened to be sampled, "
      "not which adjudicator is better.")
    a("")

    if not paired:
        a("_No paired cases yet._")
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"no paired cases yet -> {REPORT}")
        return

    a("## By agent type")
    a("")
    a("Each figure is marked usable only if the rows it actually rests on reach "
      f"n={MIN_CELL}: recall on the fraud rows, false positives on the clean rows.")
    a("")
    a("| Agent type | Paired | Baseline recall | Agent recall | Recall usable? | "
      "Baseline FP | Agent FP | FP usable? |")
    a("|---|---|---|---|---|---|---|---|")
    for name, st in cells.items():
        rec_ok = ("yes" if st["recall_interpretable"]
                  else f"**NO — {st['fraud_n']} fraud case(s)**")
        fp_ok = ("yes" if st["fp_interpretable"]
                 else f"**NO — {st['clean_n']} clean case(s)**")
        a(f"| {name} | {st['n']} | {pct(st['baseline_recall'])} | "
          f"{pct(st['agent_recall'])} | {rec_ok} | "
          f"{pct(st['baseline_fp'])} | {pct(st['agent_fp'])} | {fp_ok} |")
    a("")
    unusable = []
    for name, st in cells.items():
        if not st["recall_interpretable"]:
            unusable.append(f"{name} recall ({st['fraud_n']} fraud case(s))")
        if not st["fp_interpretable"]:
            unusable.append(f"{name} false positives ({st['clean_n']} clean case(s))")
    if unusable:
        a(f"> **Below n={MIN_CELL} and therefore not interpretable: "
          f"{'; '.join(unusable)}.** The numbers are shown because hiding a thin cell "
          "is worse than showing it, but none of them should be quoted as a finding.")
        a("")

    a("## Archetype coverage of the paired set")
    a("")
    counts = Counter(b["archetype"] for b, _ in paired)
    a("| Archetype | Paired cases |")
    a("|---|---|")
    for arch, n in counts.most_common():
        a(f"| {arch} | {n} |")
    a("")
    if len(counts) < 3:
        a("> The paired set covers too few archetypes to say anything about relative "
          "strength across fraud types. Recall here describes these archetypes only.")
        a("")

    a("## Recall difference, with a confidence interval")
    a("")
    if ci is None:
        a("_Too few paired fraud cases to bootstrap._")
    else:
        a(f"Over **{ci['n']}** paired fraud case(s), agent recall minus baseline recall:")
        a("")
        a(f"- Observed difference: **{ci['observed']:+.1%}**")
        a(f"- Bootstrap 95% CI: **[{ci['lo']:+.1%}, {ci['hi']:+.1%}]** "
          f"({BOOTSTRAP_SAMPLES:,} paired resamples, seed {SEED})")
        a("")
        if ci["lo"] <= 0 <= ci["hi"]:
            a("**The interval contains zero.** On this sample the difference between the "
              "two adjudicators is not distinguishable from noise. The honest sentence "
              "for the report is that the agent scored "
              f"{'higher' if ci['observed'] > 0 else 'lower'} on these cases and that "
              "this sample does not establish the difference is real — not that one arm "
              "beat the other.")
        else:
            a(f"**The interval excludes zero**, so on this sample the difference is "
              f"unlikely to be noise. It remains a statement about {ci['n']} cases from "
              "the archetypes listed above, not about the corpus.")
    a("")

    a("## What this cannot establish")
    a("")
    a("- **False-positive rates.** The clean cells are far too small; any FP figure "
      "here is an upper bound and the two arms' FP rates must not be reported as a "
      "difference.")
    a("- **Per-archetype strength**, unless an archetype has its own n≥10 above.")
    a("- **Anything about underwriting fraud**, which has no working detector and is "
      "absent from the ablation sample by design.")
    a("- **Cost comparison beyond these cases** — latency and call counts are in the "
      "full report and scale with the arm, not with this subset.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"paired: {len(paired)} case(s)")
    for name, st in cells.items():
        flags = []
        if not st["recall_interpretable"]:
            flags.append("recall n<%d" % MIN_CELL)
        if not st["fp_interpretable"]:
            flags.append("fp n<%d" % MIN_CELL)
        mark = ("  [" + ", ".join(flags) + "]") if flags else ""
        print(f"  {name}: n={st['n']} fraud={st['fraud_n']} clean={st['clean_n']}{mark}")
    if ci:
        print(f"recall diff {ci['observed']:+.1%}, 95% CI [{ci['lo']:+.1%}, {ci['hi']:+.1%}]")
    print(f"-> {REPORT}")


if __name__ == "__main__":
    main()
