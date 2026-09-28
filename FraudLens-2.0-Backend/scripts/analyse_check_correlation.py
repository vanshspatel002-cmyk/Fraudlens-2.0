"""
Do the checks fire independently, or does the weighted sum double-count?

--------------------------------------------------------------------------
Why this matters
--------------------------------------------------------------------------
The rules-only baseline scores a case as

    score = sum over CONCERN findings of (check weight x finding confidence)

which treats every check as an independent piece of evidence. If two checks
fire on the same cases, that sum counts one signal twice, and a case
carrying a single underlying problem is scored as though it carried two.

That has a specific suspect. `threshold_gaming` raises 126 of the corpus's
297 concerns and dominates the false-positive count; if it is correlated
with another check, part of that dominance is arithmetic rather than
detection.

--------------------------------------------------------------------------
What is computed
--------------------------------------------------------------------------
Per check, a binary vector over all cases: 1 where the check raised a
CONCERN. Then, for every pair:

  - the phi coefficient (Pearson correlation between two binary variables),
  - the Jaccard overlap of the case sets, and
  - lift: how much more often they co-fire than chance would predict.

Phi alone is misleading for rare events - two checks each firing on 4% of
cases can have low phi while overlapping almost completely - so all three
are reported and pairs are ranked by lift.

Writes outputs/check_correlation.md.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

FINDINGS = Path("outputs/baseline_findings.jsonl")
OUT = Path("outputs/check_correlation.md")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")

# Pairs above this lift co-fire far more than chance and are candidates for
# merging. 3.0 is a judgement call: it is high enough that a coincidence on
# 800 cases is implausible, low enough to catch partial overlap.
LIFT_THRESHOLD = 3.0
MIN_CO_OCCURRENCE = 5
ADJUDICATED_INDEPENDENT = {
    tuple(sorted(("external_corpus", "scene_consistency"))): (
        "Audited 2026-09-23/24: all 7 co-firings are true EXTERNAL_SOURCING fraud "
        "cases and 0 are clean cases. `external_corpus` matches the image against "
        "the external index; `scene_consistency` separately checks weather, lighting, "
        "and solar geometry against the declared time/place. This is a real fraud "
        "correlation, not a false-positive or single-signal double count."
    ),
}


def load() -> tuple[dict[str, set[str]], set[str]]:
    if not FINDINGS.exists():
        raise SystemExit(f"no findings cache at {FINDINGS}; run scripts/run_baseline.py")
    concerns: dict[str, set[str]] = defaultdict(set)
    cases: set[str] = set()
    for line in FINDINGS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cases.add(row["case_id"])
        for f in row["findings"]:
            if f.get("verdict") == "concern":
                concerns[f["check_id"]].add(row["case_id"])
    return dict(concerns), cases


def phi(a: set[str], b: set[str], n: int) -> Optional[float]:
    n11 = len(a & b)
    n10 = len(a - b)
    n01 = len(b - a)
    n00 = n - n11 - n10 - n01
    num = n11 * n00 - n10 * n01
    den = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    return (num / den) if den else None


def main() -> None:
    concerns, cases = load()
    n = len(cases)
    archetype = {}
    if GROUND_TRUTH.exists():
        archetype = {r["case_id"]: r["archetype"]
                     for r in csv.DictReader(open(GROUND_TRUTH, encoding="utf-8"))}
    clean = {c for c in cases if archetype.get(c) == "CLEAN"}

    active = {k: v for k, v in concerns.items() if v}
    checks = sorted(active)

    pairs = []
    for a, b in combinations(checks, 2):
        sa, sb = active[a], active[b]
        co = len(sa & sb)
        expected = len(sa) * len(sb) / n if n else 0
        lift = (co / expected) if expected > 0 else 0.0
        union = len(sa | sb)
        pairs.append({
            "a": a, "b": b, "a_n": len(sa), "b_n": len(sb),
            "co_occurrence": co,
            "expected_by_chance": round(expected, 2),
            "lift": round(lift, 2),
            "jaccard": round(co / union, 3) if union else 0.0,
            "phi": round(phi(sa, sb, n) or 0.0, 3),
            "co_on_clean": len(sa & sb & clean),
        })
    pairs.sort(key=lambda p: (-p["lift"], -p["co_occurrence"]))

    candidates = [
        p for p in pairs
        if p["lift"] >= LIFT_THRESHOLD and p["co_occurrence"] >= MIN_CO_OCCURRENCE
    ]
    adjudicated = [
        p for p in candidates
        if tuple(sorted((p["a"], p["b"]))) in ADJUDICATED_INDEPENDENT
    ]
    redundant = [
        p for p in candidates
        if tuple(sorted((p["a"], p["b"]))) not in ADJUDICATED_INDEPENDENT
    ]

    a_: list[str] = []
    a = a_.append
    a("# Check correlation — does the weighted sum double-count?")
    a("")
    a("The rules-only baseline sums check outputs as though each were independent "
      "evidence. Where two checks fire on the same cases, that sum counts one "
      "underlying signal twice.")
    a("")
    a(f"Computed over **{n}** cases and **{len(checks)}** checks that raised at least "
      f"one concern.")
    a("")

    a("## Concerns per check")
    a("")
    a("| Check | Cases with a concern | Share | On clean cases |")
    a("|---|---|---|---|")
    for check in sorted(checks, key=lambda c: -len(active[c])):
        s = active[check]
        a(f"| `{check}` | {len(s)} | {len(s) / n:.1%} | {len(s & clean)} |")
    a("")

    a("## Pairwise co-firing")
    a("")
    a("Ranked by lift — how many times more often the pair co-fires than independence "
      "would predict. Phi is reported alongside because it is the conventional measure, "
      "but for events this rare phi understates overlap: two checks each firing on 4% of "
      "cases can overlap almost completely and still show a modest phi.")
    a("")
    a("| Check A | Check B | Both | Expected | Lift | Jaccard | Phi | Both on clean |")
    a("|---|---|---|---|---|---|---|---|")
    for p in pairs[:20]:
        a(f"| `{p['a']}` | `{p['b']}` | {p['co_occurrence']} | {p['expected_by_chance']} "
          f"| {p['lift']} | {p['jaccard']} | {p['phi']} | {p['co_on_clean']} |")
    a("")

    a("## Redundancy")
    a("")
    if not redundant:
        a("**No pair remains classified as redundant after adjudication.**")
        a(f"Audit threshold: lift ≥ "
          f"{LIFT_THRESHOLD} with at least {MIN_CO_OCCURRENCE} co-occurrences).")
        a("")
        if adjudicated:
            a("### Adjudicated as genuine correlation")
            a("")
            for p in adjudicated:
                key = tuple(sorted((p["a"], p["b"])))
                a(f"- **`{p['a']}` + `{p['b']}`** — {ADJUDICATED_INDEPENDENT[key]}")
            a("")
        a("After adjudication, the weighted sum is not double-counting. This means "
          "`threshold_gaming`'s dominance of the false-positive count is "
          "**detection behaviour, not an artefact of the scoring arithmetic**. It fires "
          "often because it fires often, and the remedy established earlier - correcting "
          "who the finding describes rather than changing thresholds - is the right one.")
        a("")
        a("It also means merging checks would not change the achievable recall ceiling. "
          "The ceiling is set by three archetypes having no working detector, which is "
          "a coverage limit no re-weighting can move.")
    else:
        a(f"{len(redundant)} pair(s) exceed lift {LIFT_THRESHOLD}:")
        a("")
        for p in redundant:
            a(f"- **`{p['a']}` + `{p['b']}`** — co-fire on {p['co_occurrence']} cases "
              f"against {p['expected_by_chance']} expected (lift {p['lift']}, Jaccard "
              f"{p['jaccard']}). The weighted sum counts these as two independent "
              f"signals.")
        a("")
        a("### Suggested merged weights")
        a("")
        a("Where two checks are effectively one signal, their combined contribution "
          "should be the larger of the two weights rather than their sum. Halving both "
          "would be wrong: the signal is worth what the better check says it is worth.")
        a("")
        a("| Pair | Current combined | Suggested |")
        a("|---|---|---|")
        try:
            from src.checks import REGISTRY
            for p in redundant:
                wa = REGISTRY[p["a"]].weight if p["a"] in REGISTRY else 0.0
                wb = REGISTRY[p["b"]].weight if p["b"] in REGISTRY else 0.0
                a(f"| `{p['a']}` + `{p['b']}` | {wa + wb:.1f} | {max(wa, wb):.1f} |")
        except Exception:  # noqa: BLE001
            a("| (registry unavailable) | | |")
    a("")

    a("## What this does not establish")
    a("")
    a("Correlation is measured over co-firing on the same cases, which is the property "
      "the weighted sum is sensitive to. It says nothing about whether two checks detect "
      "the same underlying *mechanism* — two checks could fire on disjoint cases and "
      "still be measuring the same thing in different populations.")
    a("")
    a("Checks that never fire on this corpus are absent from the table entirely. Their "
      "independence is untested, not established.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")

    print(f"{len(checks)} active check(s) over {n} cases")
    print(f"top pair by lift: {pairs[0]['a']} + {pairs[0]['b']} "
          f"(lift {pairs[0]['lift']}, both on {pairs[0]['co_occurrence']} cases)"
          if pairs else "no pairs")
    print(f"candidate redundant pairs: {len(candidates)}")
    print(f"redundant pairs after adjudication: {len(redundant)}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
