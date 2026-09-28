"""
Measure entity_graph on the production corpus and on the injected ring.

Both are needed and they answer different questions.

The production corpus assigns every case a unique claimant and a unique
registration, so there is nothing to join on and the check cannot fire. That
is a corpus property, and reporting it as "the check found no collusion"
would be a category error - the corpus contains none to find, and could not
express any.

The ring database (scripts/inject_collusion_ring.py) contains a labelled
ring, so it answers the question the production corpus cannot: does the
check detect collusion when collusion exists, and does it stay quiet on the
792 cases that are not part of it?

Writes outputs/entity_graph_measurement.json.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import REGISTRY
from src.checks.base import CheckContext
from src.models import Verdict

OUT = Path("outputs/entity_graph_measurement.json")
LABELS = Path("outputs/collusion_ring_labels.json")
CHECK = "entity_graph"


def evaluate(db_path: str, ring_members: set[str], controls: Optional[set[str]] = None) -> dict[str, Any]:
    controls = controls or set()
    conn = db.connect(db_path)
    check = REGISTRY[CHECK]
    fired: list[str] = []
    inconclusive: list[str] = []
    examined = 0

    for case in db.get_all_cases(conn):
        images = db.get_images_for_case(conn, case.case_id)
        ctx = CheckContext(conn=conn, case=case, images=images,
                           perception={}, config={})
        try:
            findings = check.run(ctx)
        except Exception as e:  # noqa: BLE001
            print(f"  {case.case_id}: {type(e).__name__}: {e}")
            continue
        examined += 1
        for f in findings:
            if f.verdict is Verdict.CONCERN:
                fired.append(case.case_id)
            elif f.verdict is Verdict.INCONCLUSIVE and f.confidence > 0:
                inconclusive.append(case.case_id)

    conn.close()
    fired_set = set(fired)
    tp = sorted(fired_set & ring_members)
    fp = sorted(fired_set - ring_members)
    fn = sorted(ring_members - fired_set)
    non_ring = examined - len(ring_members)
    precision = (len(tp) / len(fired_set)) if fired_set else None
    return {
        "database": db_path,
        "cases_examined": examined,
        "ring_members": len(ring_members),
        "single_identifier_controls": len(controls),
        "concerns_raised": len(fired_set),
        "ring_detected": len(tp),
        "ring_missed": len(fn),
        "non_ring_flagged": len(fp),
        "recall_on_ring": (len(tp) / len(ring_members)) if ring_members else None,
        "precision": precision,
        "false_positive_rate": (len(fp) / non_ring) if non_ring > 0 else None,
        "controls_flagged": len(fired_set & controls),
        "detected_cases": tp,
        "missed_cases": fn,
        "false_positive_cases": fp[:20],
        "weak_single_identifier_links": len(set(inconclusive)),
    }


def main() -> None:
    ring_members: set[str] = set()
    controls: set[str] = set()
    if LABELS.exists():
        labels = json.loads(LABELS.read_text(encoding="utf-8"))
        ring_members = {m["case_id"] for m in labels.get("members", [])}
        controls = {m["case_id"] for m in labels.get("single_identifier_controls", [])}

    print("production corpus (expected: nothing to find)")
    production = evaluate("fraudlens.db", set())
    print(f"  {production['cases_examined']} cases, "
          f"{production['concerns_raised']} concern(s)")

    result: dict[str, Any] = {
        "check_id": CHECK,
        "production": production,
        "production_verdict": (
            "UNTESTABLE ON THIS CORPUS. The generator assigns every case a unique "
            "claimant and a unique vehicle registration, and the production schema "
            "carries no phone, bank-account or address fields, so no two cases share "
            "any identifier and the check has nothing to join on. Zero concerns here "
            "is a statement about the corpus, not about collusion detection."
            if production["concerns_raised"] == 0
            else f"{production['concerns_raised']} concern(s) raised - investigate, "
                 "since the corpus was expected to contain no shared identifiers."
        ),
    }

    ring_db = Path("fraudlens_ring.db")
    if ring_db.exists() and ring_members:
        print(f"\nring database ({len(ring_members)} labelled members)")
        ring = evaluate(str(ring_db), ring_members, controls)
        result["ring"] = ring
        rec = ring["recall_on_ring"]
        prec = ring["precision"]
        fpr = ring["false_positive_rate"]
        print(f"  detected {ring['ring_detected']}/{ring['ring_members']}"
              + (f" ({rec:.0%})" if rec is not None else ""))
        print(f"  precision {prec:.0%}" if prec is not None else "  precision n/a")
        print(f"  single-identifier controls flagged {ring['controls_flagged']}/{ring['single_identifier_controls']}")
        print(f"  false positives {ring['non_ring_flagged']}"
              + (f" ({fpr:.2%})" if fpr is not None else ""))
        result["ring_verdict"] = (
            f"Detected {ring['ring_detected']} of {ring['ring_members']} ring members"
            + (f" ({rec:.0%})" if rec is not None else "")
            + (f" at {prec:.0%} precision" if prec is not None else "")
            + f" with {ring['non_ring_flagged']} false positive(s) across "
              f"{ring['cases_examined'] - ring['ring_members']} unrelated cases"
            + (f" ({fpr:.2%})" if fpr is not None else "")
            + f"; {ring['controls_flagged']} of {ring['single_identifier_controls']} "
              "single-identifier controls were flagged. This measures the check against a ring built to be found, so it "
              "verifies the logic rather than establishing field performance."
        )
    else:
        result["ring_verdict"] = ("No ring database. Run "
                                 "scripts/inject_collusion_ring.py first.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['production_verdict'][:120]}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
