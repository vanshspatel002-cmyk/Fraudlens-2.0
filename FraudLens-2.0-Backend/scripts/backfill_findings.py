"""
Load the cached findings into the database.

The `findings` table was empty for all 800 cases, so the interface's Findings
panel - the thing a reviewer actually reads a case through - rendered blank
everywhere, and /v1/stats reported zero concerns.

Nothing had gone wrong at compute time; the findings simply had no writer.
`run_baseline.py --no-persist` skips the database by design, and
`run_ablation.py` writes decisions and traces but not findings. So they were
computed correctly, cached to outputs/baseline_findings.jsonl, and never
stored.

This loads that cache. It is not a recompute: the cache was produced by the
current check logic in this session's full battery run, so it is exactly what
the checks say today.

Idempotent - existing rows are left alone.

Usage:
    python scripts/backfill_findings.py
    python scripts/backfill_findings.py --replace     # drop and reload
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.models import CheckCategory, Finding, Verdict

CACHE = Path("outputs/baseline_findings.jsonl")


def parse_dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="delete existing findings first")
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args(argv)

    if not CACHE.exists():
        raise SystemExit(f"no findings cache at {CACHE}; run scripts/run_baseline.py first")

    conn = db.connect(args.db_path)
    db.init_db(conn)

    if args.replace:
        removed = conn.execute("DELETE FROM findings").rowcount
        conn.commit()
        print(f"removed {removed} existing finding(s)")

    existing = {r[0] for r in conn.execute("SELECT finding_id FROM findings")}
    inserted = skipped = failed = 0

    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for raw in row.get("findings", []):
            if raw.get("finding_id") in existing:
                skipped += 1
                continue
            try:
                finding = Finding(
                    check_id=raw["check_id"],
                    case_id=raw["case_id"],
                    category=CheckCategory(raw["category"]),
                    verdict=Verdict(raw["verdict"]),
                    confidence=float(raw["confidence"]),
                    explanation=raw["explanation"],
                    evidence=raw.get("evidence") or {},
                    finding_id=raw["finding_id"],
                )
                created = parse_dt(raw.get("created_at"))
                if created is not None:
                    finding.created_at = created
                db.insert_finding(conn, finding)
                inserted += 1
            except (KeyError, ValueError, sqlite3.IntegrityError) as e:
                failed += 1
                if failed <= 3:
                    print(f"  skipped a malformed finding: {type(e).__name__}: {e}")

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    concerns = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE verdict = 'concern'").fetchone()[0]
    cases = conn.execute("SELECT COUNT(DISTINCT case_id) FROM findings").fetchone()[0]
    print(f"inserted {inserted}, skipped {skipped} already present, {failed} malformed")
    print(f"findings table: {total} row(s) across {cases} case(s); {concerns} concern(s)")
    conn.close()


if __name__ == "__main__":
    main()
