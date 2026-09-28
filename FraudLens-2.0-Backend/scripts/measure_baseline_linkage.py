"""
Measure baseline_linkage against the linked scenario database.

Three groups, and the second is what makes the measurement mean anything:

  positives  a claim linked to an AI_GENERATED_BASELINE inspection within the
             check's window, with moderate-or-worse perceived damage
  controls   linked identically but 60-120 days out, so the ONLY difference
             is the interval. Without these, a check that fired on any link
             at all would look perfect.
  the rest   claims with no inspection on record, which should PASS

Writes outputs/baseline_linkage_measurement.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import REGISTRY
from src.checks.base import CheckContext
from src.models import Verdict

OUT = Path("outputs/baseline_linkage_measurement.json")
LABELS = Path("outputs/baseline_linkage_labels.json")
DB = "fraudlens_scenarios.db"
CHECK = "baseline_linkage"


def main() -> None:
    if not LABELS.exists():
        raise SystemExit("run scripts/inject_baseline_linkage.py first")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    positives = {p["claim_case"] for p in labels["positives"]}
    controls = {c["claim_case"] for c in labels["controls"]}

    conn = db.connect(DB)
    check = REGISTRY[CHECK]
    perception = {r[0]: r for r in ()}  # populated per case below via run_checks

    from src.checks import run_checks

    verdicts: dict[str, str] = {}
    for i, case in enumerate(db.get_all_cases(conn), 1):
        if case.agent_type != "claims":
            continue
        findings = [f for f in run_checks(conn, case, check_ids=[CHECK])
                    if f.check_id == CHECK]
        if not findings:
            continue
        v = findings[0].verdict
        verdicts[case.case_id] = v.value
        if i % 200 == 0:
            print(f"  {i} cases", flush=True)
    conn.close()

    def tally(ids: set[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for case_id in ids:
            v = verdicts.get(case_id, "not_run")
            out[v] = out.get(v, 0) + 1
        return out

    others = set(verdicts) - positives - controls
    pos_concern = sum(1 for c in positives if verdicts.get(c) == "concern")
    ctl_concern = sum(1 for c in controls if verdicts.get(c) == "concern")
    oth_concern = sum(1 for c in others if verdicts.get(c) == "concern")

    result = {
        "check_id": CHECK,
        "database": DB,
        "positives": {
            "n": len(positives), "concern": pos_concern,
            "recall": pos_concern / len(positives) if positives else None,
            "verdicts": tally(positives),
        },
        "long_interval_controls": {
            "n": len(controls), "concern": ctl_concern,
            "false_positive_rate": ctl_concern / len(controls) if controls else None,
            "verdicts": tally(controls),
            "note": ("Linked to an inspection but outside the 30-day window. A concern "
                     "here would mean the check fires on the link rather than on the "
                     "interval."),
        },
        "unlinked_claims": {
            "n": len(others), "concern": oth_concern,
            "false_positive_rate": oth_concern / len(others) if others else None,
        },
    }
    discriminates = (
        result["positives"]["recall"] is not None
        and result["positives"]["recall"] >= 0.8
        and (result["long_interval_controls"]["false_positive_rate"] or 0) <= 0.2
        and (result["unlinked_claims"]["false_positive_rate"] or 0) <= 0.05
    )
    result["discriminates"] = discriminates
    result["verdict"] = (
        "The check separates short-interval claims on a certified-undamaged vehicle "
        "from both long-interval linked claims and unlinked claims. Measured against "
        "links this project created, so it verifies the logic rather than establishing "
        "field performance - in production, honest short-interval claims are far more "
        "common than in any generated corpus."
        if discriminates else
        "Does not separate the groups cleanly; see the per-group verdict counts."
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    p, c, o = (result["positives"], result["long_interval_controls"],
               result["unlinked_claims"])
    print(f"\npositives (5-25d)   : {p['concern']}/{p['n']} concern  {p['verdicts']}")
    print(f"controls (60-120d)  : {c['concern']}/{c['n']} concern  {c['verdicts']}")
    print(f"unlinked claims     : {o['concern']}/{o['n']} concern")
    print(f"discriminates       : {discriminates}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
