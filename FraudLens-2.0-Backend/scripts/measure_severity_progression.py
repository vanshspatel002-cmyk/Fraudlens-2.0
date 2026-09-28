"""
Measure severity_progression against injected repeat-claim sequences.

Four groups. The two control groups are what make the result meaningful:

  oscillating positives  severe -> moderate -> severe, no repair recorded.
                         The pattern the check exists to catch.
  monotone controls      damage only accumulates. A check firing here would
                         be flagging repeat claiming rather than incoherent
                         claiming, which is a very different and much worse
                         behaviour.
  repaired controls      the same oscillation WITH a repair_completed event
                         in the interval. Without this group, a check that
                         ignored repair records entirely would still score
                         perfectly.
  the rest               single-claim vehicles, which should PASS.

Also measures the production corpus, where every registration is unique and
the check cannot fire at all.

Writes outputs/severity_progression_measurement.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import run_checks

OUT = Path("outputs/severity_progression_measurement.json")
LABELS = Path("outputs/repeat_claim_labels.json")
CHECK = "severity_progression"


def verdicts_for(db_path: str) -> dict[str, str]:
    conn = db.connect(db_path)
    out: dict[str, str] = {}
    for case in db.get_all_cases(conn):
        if case.agent_type != "claims":
            continue
        findings = [f for f in run_checks(conn, case, check_ids=[CHECK])
                    if f.check_id == CHECK]
        if findings:
            out[case.case_id] = findings[0].verdict.value
    conn.close()
    return out


def main() -> None:
    if not LABELS.exists():
        raise SystemExit("run scripts/inject_repeat_claims.py first")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))

    def ids(group: str) -> set[str]:
        return {c["case_id"] for seq in labels.get(group, []) for c in seq["sequence"]}

    positives = ids("oscillating_positives")
    monotone = ids("monotone_controls")
    repaired = ids("repaired_controls")

    print("scenario database")
    verdicts = verdicts_for(labels["database"])
    others = set(verdicts) - positives - monotone - repaired

    def tally(group: set[str]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for case_id in group:
            v = verdicts.get(case_id, "not_run")
            counts[v] = counts.get(v, 0) + 1
        concern = counts.get("concern", 0)
        return {"n": len(group), "concern": concern,
                "rate": (concern / len(group)) if group else None,
                "verdicts": counts}

    pos, mon, rep, oth = (tally(positives), tally(monotone),
                          tally(repaired), tally(others))

    print("\nproduction corpus (expected: no repeat registrations)")
    prod = verdicts_for("fraudlens.db")
    prod_concern = sum(1 for v in prod.values() if v == "concern")

    # A sequence counts as detected if the check fires on any claim in it -
    # the finding is about the sequence, and flagging the last claim is the
    # actionable outcome.
    def sequences_detected(group: str) -> int:
        n = 0
        for seq in labels.get(group, []):
            if any(verdicts.get(c["case_id"]) == "concern" for c in seq["sequence"]):
                n += 1
        return n

    osc_seq = len(labels.get("oscillating_positives", []))
    mon_seq = len(labels.get("monotone_controls", []))
    rep_seq = len(labels.get("repaired_controls", []))
    osc_detected = sequences_detected("oscillating_positives")
    mon_flagged = sequences_detected("monotone_controls")
    rep_flagged = sequences_detected("repaired_controls")
    true_positive_sequences = osc_detected
    false_positive_sequences = mon_flagged + rep_flagged
    precision = (
        true_positive_sequences / (true_positive_sequences + false_positive_sequences)
        if (true_positive_sequences + false_positive_sequences)
        else None
    )
    recall = (osc_detected / osc_seq) if osc_seq else None
    control_total = mon_seq + rep_seq
    control_fp_rate = (false_positive_sequences / control_total) if control_total else None

    result = {
        "check_id": CHECK,
        "scenario_database": labels["database"],
        "by_case": {"oscillating_positives": pos, "monotone_controls": mon,
                    "repaired_controls": rep, "other_claims": oth},
        "by_sequence": {
            "oscillating_detected": osc_detected,
            "oscillating_total": osc_seq,
            "monotone_flagged": mon_flagged,
            "monotone_total": mon_seq,
            "repaired_flagged": rep_flagged,
            "repaired_total": rep_seq,
            "precision": precision,
            "recall": recall,
            "control_false_positive_rate": control_fp_rate,
        },
        "production": {
            "cases_examined": len(prod),
            "concerns": prod_concern,
            "verdict": (
                "UNTESTABLE ON THIS CORPUS. Every case carries a unique vehicle "
                "registration, so no vehicle claims twice and the check has no "
                "sequence to examine. Zero concerns here is a statement about the "
                "corpus, not about repeat-claim fraud."
                if prod_concern == 0 else
                f"{prod_concern} concern(s) on production - unexpected, investigate."),
        },
    }
    discriminates = (
        result["by_sequence"]["oscillating_detected"] >= 0.8 * max(1, osc_seq)
        and result["by_sequence"]["monotone_flagged"] == 0
        and result["by_sequence"]["repaired_flagged"] == 0
    )
    result["discriminates"] = discriminates
    result["verdict"] = (
        "Separates incoherent severity sequences from both coherent accumulation and "
        "from oscillation that a recorded repair explains. Measured against sequences "
        "this project injected, so it verifies the logic rather than establishing field "
        "performance."
        if discriminates else
        "Does not separate the groups cleanly; see by_sequence."
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    s = result["by_sequence"]
    print(f"\noscillating positives : {s['oscillating_detected']}/{s['oscillating_total']} sequences detected")
    print(f"monotone controls     : {s['monotone_flagged']}/{s['monotone_total']} flagged (want 0)")
    print(f"repaired controls     : {s['repaired_flagged']}/{s['repaired_total']} flagged (want 0)")
    print("precision/recall      : "
          f"{s['precision']:.0%}/{s['recall']:.0%}" if s["precision"] is not None and s["recall"] is not None
          else "precision/recall      : n/a")
    print("control FP rate       : "
          f"{s['control_false_positive_rate']:.0%}" if s["control_false_positive_rate"] is not None
          else "control FP rate       : n/a")
    print(f"other claims          : {oth['concern']}/{oth['n']} concern")
    print(f"production corpus     : {prod_concern}/{len(prod)} concern")
    print(f"discriminates         : {discriminates}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
