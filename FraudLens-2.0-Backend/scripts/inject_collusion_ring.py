"""
Inject a labelled collusion ring into a COPY of the database.

--------------------------------------------------------------------------
Why a copy, always
--------------------------------------------------------------------------
This writes fabricated relationships into case records. Doing that to the
production corpus would corrupt every measurement taken against it and, more
immediately, would poison the ablation currently running. The script refuses
to write to fraudlens.db.

--------------------------------------------------------------------------
What it builds
--------------------------------------------------------------------------
Three claimants sharing a phone number and a bank account across eight cases
at two garages - the shape of an organised motor-fraud ring in this market:
a small group of individuals, a shared payout channel, and a cooperative
repairer. One claimant additionally appears with three distinct
registrations at a single garage, which is the vehicle-cycling pattern.

The ring is written over existing CLEAN cases rather than as new rows, so
every case retains real images, real findings and a real ground-truth label.
Only the identifiers change. The affected case ids are recorded so the
measurement knows exactly which cases are ring members.

--------------------------------------------------------------------------
Additive schema
--------------------------------------------------------------------------
The linking columns (phone, bank_account, address) do not exist on `cases`
in the production schema. They are added here with ALTER TABLE ... ADD
COLUMN, which is additive and leaves existing rows untouched. This mirrors
what a production deployment would carry, where contact and payout details
are part of the claim record.

Usage:
    python scripts/inject_collusion_ring.py                 # writes fraudlens_ring.db
    python scripts/inject_collusion_ring.py --db out.db
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

SOURCE = Path("fraudlens.db")
DEFAULT_TARGET = Path("fraudlens_ring.db")
LABELS = Path("outputs/collusion_ring_labels.json")

LINKING_COLUMNS = {
    "phone": "TEXT",
    "bank_account": "TEXT",
    "address": "TEXT",
}

# The positive set now covers several shapes, not one tiny ring:
#
# * RING-A/B/C: phone+bank overlap with partial address overlap.
# * RING-D/E/F: bank+address overlap without shared phone.
# * RING-V: one claimant cycling several vehicles through one garage.
#
# Controls share exactly one identifier, which should produce at most
# INCONCLUSIVE and must not count as a collusion concern.
RING_PHONE = "+91-98200-41155"
RING_ACCOUNT = "HDFC-0041-772915"
RING_ADDRESS = "Flat 4B, Shivaji Nagar, Pune"
RING2_ACCOUNT = "ICICI-7719-004212"
RING2_ADDRESS = "Unit 9, Market Road, Surat"
CONTROL_PHONE = "+91-98200-49999"
CONTROL_ADDRESS = "Shared Hostel Block C, Pune"

RING_PLAN = [
    # (claimant, garage, phone, account, address, positive)
    ("RING-A", "GAR-RING-1", RING_PHONE, RING_ACCOUNT, RING_ADDRESS, True),
    ("RING-A", "GAR-RING-1", RING_PHONE, RING_ACCOUNT, RING_ADDRESS, True),
    ("RING-A", "GAR-RING-1", RING_PHONE, RING_ACCOUNT, None, True),
    ("RING-B", "GAR-RING-1", RING_PHONE, RING_ACCOUNT, None, True),
    ("RING-B", "GAR-RING-2", RING_PHONE, None, RING_ADDRESS, True),
    ("RING-C", "GAR-RING-2", RING_PHONE, RING_ACCOUNT, None, True),
    ("RING-C", "GAR-RING-2", None, RING_ACCOUNT, RING_ADDRESS, True),
    ("RING-C", "GAR-RING-1", RING_PHONE, RING_ACCOUNT, None, True),
    ("RING-D", "GAR-RING-3", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-D", "GAR-RING-4", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-E", "GAR-RING-3", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-E", "GAR-RING-4", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-F", "GAR-RING-3", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-F", "GAR-RING-4", None, RING2_ACCOUNT, RING2_ADDRESS, True),
    ("RING-V", "GAR-RING-5", None, None, None, True),
    ("RING-V", "GAR-RING-5", None, None, None, True),
    ("RING-V", "GAR-RING-5", None, None, None, True),
    ("RING-V", "GAR-RING-5", None, None, None, True),
    ("CTRL-P1", "GAR-CTRL-1", CONTROL_PHONE, None, None, False),
    ("CTRL-P2", "GAR-CTRL-2", CONTROL_PHONE, None, None, False),
    ("CTRL-P3", "GAR-CTRL-3", CONTROL_PHONE, None, None, False),
    ("CTRL-A1", "GAR-CTRL-4", None, None, CONTROL_ADDRESS, False),
    ("CTRL-A2", "GAR-CTRL-5", None, None, CONTROL_ADDRESS, False),
    ("CTRL-A3", "GAR-CTRL-6", None, None, CONTROL_ADDRESS, False),
]


def add_columns(conn: sqlite3.Connection) -> list[str]:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
    added = []
    for name, sql_type in LINKING_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {sql_type}")
            added.append(name)
    conn.commit()
    return added


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_TARGET))
    args = parser.parse_args(argv)

    target = Path(args.db)
    if target.resolve() == SOURCE.resolve():
        print("REFUSING: this writes fabricated relationships and must never touch "
              "the production database. Choose another --db.", file=sys.stderr)
        return 1
    if not SOURCE.exists():
        print(f"no source database at {SOURCE}", file=sys.stderr)
        return 1

    shutil.copy(SOURCE, target)
    conn = sqlite3.connect(target)

    added = add_columns(conn)
    if added:
        print(f"added columns: {', '.join(added)}")

    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open("data/generated/ground_truth.csv",
                                              encoding="utf-8"))}
    # Ring members are written over CLEAN claims cases: they keep real images
    # and real findings, so every other check behaves normally on them.
    candidates = [
        r[0] for r in conn.execute(
            "SELECT case_id FROM cases WHERE agent_type = 'claims' ORDER BY case_id")
        if archetype.get(r[0]) == "CLEAN"
    ][: len(RING_PLAN)]

    if len(candidates) < len(RING_PLAN):
        print(f"only {len(candidates)} clean claims cases available; need "
              f"{len(RING_PLAN)}", file=sys.stderr)
        return 1

    members = []
    controls = []
    for case_id, (claimant, garage, phone, account, address, positive) in zip(candidates, RING_PLAN):
        conn.execute(
            "UPDATE cases SET claimant_id = ?, garage_id = ?, phone = ?, "
            "bank_account = ?, address = ? WHERE case_id = ?",
            (claimant, garage, phone, account, address, case_id),
        )
        record = {
            "case_id": case_id, "claimant_id": claimant, "garage_id": garage,
            "phone": phone, "bank_account": account, "address": address,
        }
        (members if positive else controls).append(record)
    conn.commit()

    # Give RING-A and RING-V distinct registrations at one garage, so the
    # vehicle-cycling branch is exercised across two ring sizes.
    cycling_cases = [
        m["case_id"] for m in members if m["claimant_id"] in {"RING-A", "RING-V"}
    ]
    for i, case_id in enumerate(cycling_cases):
        conn.execute("UPDATE cases SET vehicle_registration = ? WHERE case_id = ?",
                     (f"MH12RG{1000 + i}", case_id))
    conn.commit()

    labels = {
        "database": str(target),
        "ring_size_cases": len(members),
        "distinct_claimants": len({m["claimant_id"] for m in members}),
        "distinct_garages": len({m["garage_id"] for m in members}),
        "shared_phone": RING_PHONE,
        "shared_bank_account": RING_ACCOUNT,
        "members": members,
        "single_identifier_controls": controls,
        "note": (
            "Ring members were written over existing CLEAN claims cases, so their "
            "ground-truth archetype in ground_truth.csv is still CLEAN. For any "
            "measurement against this database, membership in this list is the label, "
            "not the CSV."
        ),
    }
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    conn.close()

    print(f"injected {len(members)} positive ring case(s), "
          f"{labels['distinct_claimants']} claimants, {labels['distinct_garages']} garages")
    print(f"injected {len(controls)} single-identifier control case(s)")
    for m in members:
        print(f"  {m['case_id']} -> {m['claimant_id']} @ {m['garage_id']}")
    print(f"-> {target}\n-> {LABELS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
