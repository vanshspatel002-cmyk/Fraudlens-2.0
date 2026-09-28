"""
Re-measure internal_duplicate after the submission-order change.

Reports three numbers separately, because collapsing them is what hid the
problem in the first place:

  - recall on REUSE          (must not move; the reuser is still flagged)
  - false positives on clean (should fall; the victim no longer is)
  - victim flags             (the new INCONCLUSIVE class - not a false
                              positive, not a miss, and invisible if you
                              only count CONCERNs)

Writes outputs/duplicate_measurement.json.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import run_checks
from src.models import Verdict

OUT = Path("outputs/duplicate_measurement.json")
CHECK = "internal_duplicate"


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(
                     open("data/generated/ground_truth.csv", encoding="utf-8"))}
    cases = db.get_all_cases(conn)

    concern: set[str] = set()
    victim: dict[str, str] = {}
    per_archetype_concern: Counter = Counter()
    per_archetype_victim: Counter = Counter()
    totals: Counter = Counter()

    for i, case in enumerate(cases, 1):
        arch = archetype.get(case.case_id)
        if arch is None:
            continue
        totals[arch] += 1
        findings = [f for f in run_checks(conn, case, check_ids=[CHECK])
                    if f.check_id == CHECK]
        if any(f.verdict is Verdict.CONCERN for f in findings):
            concern.add(case.case_id)
            per_archetype_concern[arch] += 1
        for f in findings:
            if f.evidence.get("submission_role") == "earlier":
                victim[case.case_id] = f.evidence.get("matched_case_id", "?")
                per_archetype_victim[arch] += 1
                break
        if i % 100 == 0:
            print(f"  {i}/{len(cases)} cases", flush=True)

    reuse_total = totals.get("REUSE", 0)
    clean_total = totals.get("CLEAN", 0)
    result = {
        "check_id": CHECK,
        "recall_on_REUSE": {
            "caught": per_archetype_concern.get("REUSE", 0),
            "total": reuse_total,
            "rate": (per_archetype_concern.get("REUSE", 0) / reuse_total) if reuse_total else None,
        },
        "false_positives_on_clean": {
            "flagged": per_archetype_concern.get("CLEAN", 0),
            "total": clean_total,
            "rate": (per_archetype_concern.get("CLEAN", 0) / clean_total) if clean_total else None,
        },
        "victim_flags": {
            "total": len(victim),
            "on_clean": per_archetype_victim.get("CLEAN", 0),
            "by_archetype": dict(per_archetype_victim),
            "examples": dict(list(victim.items())[:10]),
            "note": (
                "INCONCLUSIVE, contributing zero to the risk score. These cases had "
                "their image reused by a later submission; they are neither fraud nor "
                "a false positive, and counting them as either would misdescribe them."
            ),
        },
        "concern_by_archetype": dict(per_archetype_concern),
        "caveat": (
            "This corpus is generated in blocks - every CLEAN case is created before "
            "every REUSE case - so 'earlier submission = victim' holds by construction "
            "and the false-positive improvement is guaranteed rather than earned. The "
            "rule is correct for production, where ingest time is real evidence, but "
            "this corpus cannot test whether it generalises."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    r, f, v = result["recall_on_REUSE"], result["false_positives_on_clean"], result["victim_flags"]
    rate = result["recall_on_REUSE"]["rate"]
    pretty = "n/a" if rate is None else f"{rate:.1%}"
    print(f"\nrecall on REUSE:       {r['caught']}/{r['total']} ({pretty})")
    print(f"false positives clean: {f['flagged']}/{f['total']}")
    print(f"victim flags:          {v['total']} ({v['on_clean']} on clean)")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
