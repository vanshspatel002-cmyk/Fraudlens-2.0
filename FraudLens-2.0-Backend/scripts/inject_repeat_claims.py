"""
Inject repeat-claim sequences into a COPY of the database.

The production corpus assigns every case a unique vehicle registration, so
no vehicle ever claims twice and `severity_progression` cannot fire. This
builds the sequences it needs, in the same way the collusion ring was built
for `entity_graph`.

Three groups, and the last two are what make the measurement mean anything:

  **oscillating (positive).** Three claims on one registration whose
  perceived severity goes high -> low -> high with no repair recorded. This
  is the pattern the check exists to catch.

  **monotone (control).** Three claims whose severity only rises. A vehicle
  accumulating damage is ordinary, and a check that fired here would be
  flagging repeat claiming rather than incoherent claiming.

  **repaired (control).** Oscillating severity WITH a repair_completed audit
  event in the interval, which legitimately explains the reset. Without this
  group the check could pass the first two by ignoring repair records
  entirely.

Sequences are built by rewriting registration and declared_time on existing
claims cases chosen for their already-perceived severity, so every case
keeps real images and real findings.

Refuses to write to fraudlens.db.

Usage:
    python scripts/inject_repeat_claims.py --source fraudlens_scenarios.db \\
        --db fraudlens_scenarios.db
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

PRODUCTION = Path("fraudlens.db")
LABELS = Path("outputs/repeat_claim_labels.json")
SEED = 42
BASE_DATE = datetime(2026, 1, 10)


def worst_severity(conn: sqlite3.Connection) -> dict[str, str]:
    order = {"none": 0, "minor": 1, "moderate": 2, "severe": 3}
    best: dict[str, str] = {}
    for case_id, severity in conn.execute(
        "SELECT i.case_id, p.damage_severity FROM perception_records p "
        "JOIN images i ON i.content_hash = p.content_hash"
    ):
        s = (severity or "").strip().lower()
        if s in order and order[s] > order.get(best.get(case_id, "none"), 0):
            best[case_id] = s
    return best


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Its own database by default. Sharing one with the linkage scenario made
    # the two compete for the same perceived-severity cases: linkage consumed
    # 30 of them first and starved the repeat-claim pools, which is a
    # measurement artefact rather than a property of either check.
    parser.add_argument("--source", default="fraudlens.db")
    parser.add_argument("--db", default="fraudlens_repeat.db")
    args = parser.parse_args(argv)

    target = Path(args.db)
    if target.resolve() == PRODUCTION.resolve():
        print("REFUSING: this rewrites registrations and loss dates and must never "
              "touch the production database.", file=sys.stderr)
        return 1
    source = Path(args.source)
    if not source.exists():
        print(f"no source database at {source}", file=sys.stderr)
        return 1
    if target.resolve() != source.resolve():
        shutil.copy(source, target)
    conn = sqlite3.connect(target)

    severity = worst_severity(conn)
    by_severity: dict[str, list[str]] = {"minor": [], "moderate": [], "severe": []}
    # Cases used by the linkage scenario are excluded ONLY when this scenario
    # shares a database with it. On a dedicated database the linkage rewrites
    # do not exist, and excluding them anyway removed 30 of the 37 severe
    # cases from the pool - which is why the repaired control group came out
    # empty while the arithmetic said it should fit.
    shares_db_with_linkage = "scenarios" in str(target)
    linked = set()
    if shares_db_with_linkage and Path("outputs/baseline_linkage_labels.json").exists():
        labels = json.loads(Path("outputs/baseline_linkage_labels.json")
                            .read_text(encoding="utf-8"))
        linked = ({p["claim_case"] for p in labels.get("positives", [])}
                  | {c["claim_case"] for c in labels.get("controls", [])})

    for case_id, sev in severity.items():
        # Do not reuse cases already claimed by the linkage scenario: two
        # scenarios rewriting the same case would make both unmeasurable.
        if sev in by_severity and case_id not in linked:
            row = conn.execute(
                "SELECT agent_type FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if row and row[0] == "claims":
                by_severity[sev].append(case_id)
    for v in by_severity.values():
        v.sort()

    rng = random.Random(SEED)
    for v in by_severity.values():
        rng.shuffle(v)

    def take(sev: str) -> Optional[str]:
        return by_severity[sev].pop() if by_severity[sev] else None

    def build(pattern: list[str], registration: str, gaps: list[int]) -> Optional[list[dict]]:
        picked = [take(s) for s in pattern]
        if any(p is None for p in picked):
            return None
        seq = []
        when = BASE_DATE
        for case_id, sev, gap in zip(picked, pattern, [0] + gaps):
            when = when + timedelta(days=gap)
            conn.execute(
                "UPDATE cases SET vehicle_registration = ?, declared_time = ? "
                "WHERE case_id = ?", (registration, when.isoformat(), case_id))
            seq.append({"case_id": case_id, "severity": sev,
                        "declared_time": when.isoformat()})
        return seq

    oscillating, monotone, repaired = [], [], []

    positive_patterns = [
        (["severe", "moderate", "severe"], "MH01OS", [40, 40], 6),
        (["moderate", "minor", "moderate"], "MH01OL", [20, 70], 2),
    ]
    for pattern, prefix, gaps, count in positive_patterns:
        for i in range(count):
            reg = f"{prefix}{2000 + i}"
            seq = build(pattern, reg, gaps)
            if seq:
                oscillating.append({"vehicle_registration": reg, "pattern": pattern,
                                    "sequence": seq})

    monotone_patterns = [
        (["minor", "moderate", "severe"], "MH01MO", [45, 45], 3),
        (["moderate", "severe", "severe"], "MH01MH", [30, 30], 3),
    ]
    for pattern, prefix, gaps, count in monotone_patterns:
        for i in range(count):
            reg = f"{prefix}{3000 + i}"
            seq = build(pattern, reg, gaps)
            if seq:
                monotone.append({"vehicle_registration": reg, "pattern": pattern,
                                 "sequence": seq})

    print(f"  pools before repaired group: "
          f"{ {k: len(v) for k, v in by_severity.items()} }", flush=True)
    repaired_patterns = [
        (["severe", "moderate", "severe"], "MH01RP", [40, 40], 4),
        (["moderate", "minor", "moderate"], "MH01RL", [25, 55], 2),
    ]
    repair_i = 0
    for pattern, prefix, gaps, count in repaired_patterns:
        for i in range(count):
            reg = f"{prefix}{4000 + i}"
            seq = build(pattern, reg, gaps)
            if not seq:
                continue
            # A recorded repair between the first and second claim
            # legitimately explains the reset.
            first, middle = seq[0], seq[1]
            repair_at = (datetime.fromisoformat(first["declared_time"])
                         + timedelta(days=max(1, gaps[0] // 2)))
            conn.execute(
                "INSERT INTO audit_log (event_id, event_type, case_id, details, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"repair-{repair_i}-{middle['case_id']}", "repair_completed", first["case_id"],
                 json.dumps({"note": "injected control: repair between claim 1 and claim 2 "
                                     "explains the severity reset"}),
                 repair_at.isoformat()),
            )
            repair_i += 1
            repaired.append({"vehicle_registration": reg, "pattern": pattern,
                             "sequence": seq})

    conn.commit()
    conn.close()

    labels_out = {
        "database": str(target),
        "oscillating_positives": oscillating,
        "monotone_controls": monotone,
        "repaired_controls": repaired,
        "note": (
            "Positives oscillate severe->moderate->severe with no repair recorded. "
            "Monotone controls only accumulate damage. Repaired controls oscillate but "
            "carry a repair_completed audit event in the interval. Ground-truth "
            "archetypes in ground_truth.csv are unchanged; membership in these lists is "
            "the label."
        ),
    }
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps(labels_out, indent=2), encoding="utf-8")

    print(f"oscillating positives : {len(oscillating)} sequence(s)")
    print(f"monotone controls     : {len(monotone)}")
    print(f"repaired controls     : {len(repaired)}")
    print(f"-> {target}\n-> {LABELS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
