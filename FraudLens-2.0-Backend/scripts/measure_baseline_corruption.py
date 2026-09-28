"""
Measure `baseline_corruption` against its target archetype only.

Separate from report_v2.py because that report is regenerated from a stored
findings JSONL produced by the ten-check battery; re-running 800 cases to
add one check would cost hours for twenty relevant cases. This measures the
check where it is meant to fire (AI_GENERATED_BASELINE) and where it must
not (clean underwriting cases), and refuses to divide by cases the vision
pass never reached.

Writes outputs/baseline_corruption_measurement.json.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import run_checks
from src.models import Verdict

OUT = Path("outputs/baseline_corruption_measurement.json")
CHECK_ID = "baseline_corruption"


def main() -> None:
    conn = db.connect("fraudlens.db")
    gt = {r["case_id"]: r["archetype"]
          for r in csv.DictReader(open("data/generated/ground_truth.csv", encoding="utf-8"))}
    perceived = {r[0] for r in conn.execute(
        "SELECT DISTINCT i.case_id FROM images i "
        "JOIN perception_records p ON i.content_hash = p.content_hash")}

    cases = [c for c in db.get_all_cases(conn) if c.agent_type == "underwriting"]
    target = [c for c in cases if gt.get(c.case_id) == "AI_GENERATED_BASELINE"]
    clean = [c for c in cases if gt.get(c.case_id) == "CLEAN"]

    def evaluate(pool, label):
        fired, ran, skipped = set(), set(), set()
        for case in pool:
            findings = [f for f in run_checks(conn, case, check_ids=[CHECK_ID])
                        if f.check_id == CHECK_ID]
            if not findings:
                continue
            # A case the vision pass never reached yields INCONCLUSIVE. It is
            # not a miss - the check was never given the input it needs - so
            # it belongs outside the denominator, not inside it as a zero.
            if case.case_id not in perceived:
                skipped.add(case.case_id)
                continue
            ran.add(case.case_id)
            if any(f.verdict is Verdict.CONCERN for f in findings):
                fired.add(case.case_id)
        print(f"{label}: fired {len(fired)}/{len(ran)} evaluable "
              f"({len(skipped)} unperceived, excluded; {len(pool)} total)")
        return {"pool": len(pool), "evaluable": len(ran), "fired": len(fired),
                "unperceived_excluded": len(skipped),
                "rate": (len(fired) / len(ran)) if ran else None,
                "fired_cases": sorted(fired)}

    from src.checks import REGISTRY
    targets = REGISTRY[CHECK_ID].target_archetypes

    # AI_GENERATED_BASELINE is measured here as a *diagnostic*, not as
    # recall. The check no longer claims it as a target, because it
    # cannot fire on it: that archetype fabricates the absence of damage,
    # so its photographs agree with the declaration by construction.
    # Reporting this as "0% recall" would imply a detector that is merely
    # weak, when in fact nothing in the battery detects the archetype at
    # all - a distinction the reports have to preserve.
    diagnostic = evaluate(target, "AI_GENERATED_BASELINE (diagnostic, not a target)")
    fp = evaluate(clean, "false positives on CLEAN underwriting")

    result = {
        "check_id": CHECK_ID,
        "declared_target_archetypes": list(targets),
        # No target archetype exists in this corpus that can make the check
        # reach CONCERN, so recall is UNMEASURABLE rather than zero.
        "headline_recall": "UNMEASURABLE (no target archetype in corpus)" if not targets else None,
        "ai_generated_baseline_diagnostic": diagnostic,
        "false_positives": fp,
        "note": (
            "AI_GENERATED_BASELINE is undetected by every check in the battery. "
            "It is not credited to this check."
        ),
    }
    assert "AI_GENERATED_BASELINE" not in targets, (
        "this check cannot fire on AI_GENERATED_BASELINE; it must not claim it"
    )
    verdict = result["headline_recall"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nheadline recall: {verdict}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
