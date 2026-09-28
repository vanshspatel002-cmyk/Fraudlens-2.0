"""
Link underwriting inspections to later claims, in a COPY of the database.

--------------------------------------------------------------------------
Why this is needed
--------------------------------------------------------------------------
The AI_GENERATED_BASELINE attack's real signature is temporal: a vehicle
certified undamaged at policy inception that claims for damage weeks later.
`src/checks/baseline_linkage.py` detects exactly that, and the production
corpus cannot express it - every case carries a unique registration, so no
inspection can ever be joined to a claim.

This creates those joins so the check is measurable. It writes to a copy;
it refuses to touch fraudlens.db, because rewriting registrations and loss
dates in the production corpus would invalidate every measurement taken
against it and corrupt the ablation currently running.

--------------------------------------------------------------------------
What it builds
--------------------------------------------------------------------------
**Positives.** Each AI_GENERATED_BASELINE inspection is paired with a claims
case whose images perception has already read as moderate or severe damage,
with the loss dated 5-25 days after the inspection. Those are the cases the
check should catch.

**Long-interval controls.** A second group is linked identically but with
the loss dated 60-120 days after inspection - outside the window. These test
that the check is discriminating on the interval rather than merely on the
existence of a link, which a measurement using positives alone could not
distinguish.

Everything else in the corpus is an implicit negative: no inspection exists
for those vehicles, so the check should return PASS.

Usage:
    python scripts/inject_baseline_linkage.py
    python scripts/inject_baseline_linkage.py --source fraudlens_ring.db \\
        --db fraudlens_scenarios.db
"""

from __future__ import annotations

import argparse
import csv
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
LABELS = Path("outputs/baseline_linkage_labels.json")
SEED = 42

WINDOW = (5, 25)          # positives: inside the check's 30-day window
CONTROL_WINDOW = (60, 120)  # controls: comfortably outside it
N_CONTROLS = 10
SERIOUS = ("moderate", "severe")


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
    parser.add_argument("--source", default=str(PRODUCTION))
    parser.add_argument("--db", default="fraudlens_linked.db")
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
    shutil.copy(source, target)
    conn = sqlite3.connect(target)

    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open("data/generated/ground_truth.csv",
                                              encoding="utf-8"))}
    severity = worst_severity(conn)

    inspections = [
        r[0] for r in conn.execute(
            "SELECT case_id FROM cases WHERE agent_type = 'underwriting' ORDER BY case_id")
        if archetype.get(r[0]) == "AI_GENERATED_BASELINE"
    ]
    candidates = sorted(
        r[0] for r in conn.execute(
            "SELECT case_id FROM cases WHERE agent_type = 'claims' ORDER BY case_id")
        if severity.get(r[0]) in SERIOUS
    )

    if not inspections or not candidates:
        print(f"nothing to link: {len(inspections)} inspection(s), "
              f"{len(candidates)} candidate claim(s)", file=sys.stderr)
        return 1

    rng = random.Random(SEED)
    rng.shuffle(candidates)

    positives, controls = [], []
    used: set[str] = set()

    def link(inspection_id: str, claim_id: str, low: int, high: int) -> Optional[dict]:
        row = conn.execute(
            "SELECT declared_time, vehicle_registration FROM cases WHERE case_id = ?",
            (inspection_id,)).fetchone()
        if not row or not row[0]:
            return None
        try:
            inspected = datetime.fromisoformat(str(row[0]))
        except ValueError:
            return None
        gap = rng.randint(low, high)
        loss = inspected + timedelta(days=gap)
        registration = row[1] or f"LINK{inspection_id[-4:]}"
        conn.execute(
            "UPDATE cases SET vehicle_registration = ?, declared_time = ? "
            "WHERE case_id = ?",
            (registration, loss.isoformat(), claim_id))
        return {"inspection_case": inspection_id, "claim_case": claim_id,
                "vehicle_registration": registration,
                "inspected_at": inspected.isoformat(), "loss_at": loss.isoformat(),
                "gap_days": gap, "claim_severity": severity.get(claim_id)}

    for inspection_id in inspections:
        claim_id = next((c for c in candidates if c not in used), None)
        if claim_id is None:
            break
        used.add(claim_id)
        made = link(inspection_id, claim_id, *WINDOW)
        if made:
            positives.append(made)

    # Controls reuse the same inspections with different claims, so the only
    # difference between the groups is the interval.
    for inspection_id in inspections[:N_CONTROLS]:
        claim_id = next((c for c in candidates if c not in used), None)
        if claim_id is None:
            break
        used.add(claim_id)
        made = link(inspection_id, claim_id, *CONTROL_WINDOW)
        if made:
            controls.append(made)

    conn.commit()
    conn.close()

    labels = {
        "database": str(target),
        "source": str(source),
        "window_days_positive": list(WINDOW),
        "window_days_control": list(CONTROL_WINDOW),
        "positives": positives,
        "controls": controls,
        "note": (
            "Positives are claims linked to an AI_GENERATED_BASELINE inspection within "
            "the check's 30-day window with moderate-or-worse perceived damage. "
            "Controls are linked identically but outside the window, so the check is "
            "tested on the interval rather than on the mere existence of a link. Their "
            "ground-truth archetype in ground_truth.csv is unchanged; membership in "
            "these lists is the label."
        ),
    }
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps(labels, indent=2), encoding="utf-8")

    print(f"linked {len(positives)} positive pair(s) at {WINDOW[0]}-{WINDOW[1]} days")
    print(f"linked {len(controls)} control pair(s) at {CONTROL_WINDOW[0]}-{CONTROL_WINDOW[1]} days")
    for p in positives[:5]:
        print(f"  {p['inspection_case']} -> {p['claim_case']} "
              f"({p['gap_days']}d, {p['claim_severity']})")
    print(f"-> {target}\n-> {LABELS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
