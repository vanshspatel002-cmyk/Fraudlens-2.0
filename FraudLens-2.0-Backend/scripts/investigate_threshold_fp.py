"""
Why does threshold_gaming flag 22.2% of clean claims?

It is now the dominant false-positive source in the battery, so the question
is whether those flags are wrong or merely *misattributed*.

The check is garage-scoped by design: it fires when a claim sits under the
survey threshold **and** the garage has an unusual concentration of claims in
that band. A clean claimant who happens to use a gaming garage will therefore
be flagged, and correctly so - the finding is about the garage's invoicing,
not the claimant's honesty. That is a presentational problem, not a logical
one, and the fix is wording rather than a threshold.

This measures the split:

  - clean claims flagged at a garage whose in-band concentration is elevated
    ("garage-attributable")
  - clean claims flagged with no such elevation ("unexplained")

If the first dominates, the verdict logic stays exactly as it is and the
explanation text changes to say whose behaviour is being described.

Writes outputs/threshold_fp_investigation.json.
Changes no verdict logic.
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
from src.checks import REGISTRY
from src.checks.base import CheckContext
from src.models import Verdict

OUT = Path("outputs/threshold_fp_investigation.json")
CHECK = "threshold_gaming"


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(
                     open("data/generated/ground_truth.csv", encoding="utf-8"))}
    check = REGISTRY[CHECK]

    clean_claims = [c for c in db.get_all_cases(conn)
                    if c.agent_type == "claims" and archetype.get(c.case_id) == "CLEAN"]

    flagged: list[dict[str, Any]] = []
    garages: Counter = Counter()
    for case in clean_claims:
        ctx = CheckContext(conn=conn, case=case,
                           images=db.get_images_for_case(conn, case.case_id),
                           perception={}, config={})
        try:
            findings = check.run(ctx)
        except Exception:  # noqa: BLE001
            continue
        for f in findings:
            if f.verdict is not Verdict.CONCERN:
                continue
            ev = f.evidence or {}
            garage_pct = ev.get("garage_in_band_pct")
            pop_pct = ev.get("population_in_band_pct")
            elevated = (garage_pct is not None and pop_pct is not None
                        and garage_pct > pop_pct)
            flagged.append({
                "case_id": case.case_id,
                "garage_id": case.garage_id,
                "claim_amount": case.claim_amount,
                "garage_in_band_pct": garage_pct,
                "population_in_band_pct": pop_pct,
                "garage_claim_count": ev.get("garage_claim_count"),
                "garage_attributable": bool(elevated),
            })
            garages[case.garage_id] += 1

    attributable = [r for r in flagged if r["garage_attributable"]]
    unexplained = [r for r in flagged if not r["garage_attributable"]]

    result = {
        "check_id": CHECK,
        "clean_claims_examined": len(clean_claims),
        "flagged": len(flagged),
        "flag_rate": (len(flagged) / len(clean_claims)) if clean_claims else None,
        "garage_attributable": {
            "count": len(attributable),
            "share_of_flags": (len(attributable) / len(flagged)) if flagged else None,
            "note": ("The claim sits under the survey threshold AND the garage's in-band "
                     "concentration exceeds the population average. The finding is about "
                     "the garage's invoicing pattern; the claimant may be entirely "
                     "honest."),
        },
        "unexplained": {
            "count": len(unexplained),
            "share_of_flags": (len(unexplained) / len(flagged)) if flagged else None,
            "examples": unexplained[:10],
        },
        "distinct_garages_involved": len(garages),
        "top_garages": garages.most_common(10),
        "conclusion": None,
    }

    share = result["garage_attributable"]["share_of_flags"]
    if share is not None and share >= 0.9:
        result["conclusion"] = (
            "PRESENTATIONAL. Effectively every flag is garage-attributable: the check is "
            "correctly identifying a garage billing pattern and the explanation text is "
            "what makes it read as an accusation against the claimant. Fix the wording, "
            "not the verdict."
        )
    elif share is not None and share >= 0.5:
        result["conclusion"] = (
            "MOSTLY PRESENTATIONAL, with a real residue. The majority of flags are "
            "garage-attributable, but a meaningful minority are not and need separate "
            "explanation."
        )
    else:
        result["conclusion"] = (
            "NOT MERELY PRESENTATIONAL. Most flags are not explained by an elevated "
            "garage concentration, so re-wording would hide a real problem."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"clean claims examined : {len(clean_claims)}")
    print(f"flagged               : {len(flagged)}"
          + (f" ({result['flag_rate']:.1%})" if result["flag_rate"] else ""))
    print(f"  garage-attributable : {len(attributable)}"
          + (f" ({share:.1%} of flags)" if share is not None else ""))
    print(f"  unexplained         : {len(unexplained)}")
    print(f"distinct garages      : {len(garages)}")
    print(f"\n{result['conclusion']}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
