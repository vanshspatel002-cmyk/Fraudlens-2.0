"""
Regenerate the corpus without throwing away paid-for perception.

Perception records cost real API quota - at 20 requests per key per day
they are the scarcest thing in this project - and they are keyed by image
sha256, not by case id or image id. That means a record stays valid for
any image whose *bytes* are unchanged, however the generator reshuffles
cases around it. A naive regeneration drops the database and loses all of
them; this script exports first, regenerates, and restores every record
whose content hash still appears in the new corpus.

Ordering matters and is the whole point:

  1. export perception (and back up db + ground truth, timestamped)
  2. regenerate into a fresh database
  3. restore every exported record whose content_hash is still present
  4. report how many survived, and why the rest did not

A record is only dropped when its image genuinely left the corpus - a
DIGITAL_EDIT composite regenerated with different bytes, say. That is
correct: the perception describes an image that no longer exists.

Refuses to run while a perception pass is in flight, because regenerating
the database out from under a process that is writing to it would lose
whatever it had just paid for.

Usage:
    python scripts/regenerate_preserving_perception.py --seed 42
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

BACKUP_DIR = Path("data/backups")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")


def perception_pass_running() -> bool:
    """True if any process is mid-perception-pass."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*src.perception*' } | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=60,
        )
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001 - if we cannot tell, assume the worst
        return True


def export_perception(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM perception_records")]
    finally:
        conn.close()


def restore_perception(db_path: str, records: list[dict]) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    try:
        present = {r[0] for r in conn.execute("SELECT DISTINCT content_hash FROM images")}
        cols = [d[1] for d in conn.execute("PRAGMA table_info(perception_records)")]
        kept = 0
        for record in records:
            if record["content_hash"] not in present:
                continue
            conn.execute(
                f"INSERT OR REPLACE INTO perception_records ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [record.get(c) for c in cols],
            )
            kept += 1
        conn.commit()
        return kept, len(records) - kept
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Regenerate the corpus, preserving perception records.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=800)
    parser.add_argument("--db-path", default="fraudlens.db")
    parser.add_argument("--force", action="store_true", help="regenerate even if a perception pass looks active")
    args = parser.parse_args(argv)

    if perception_pass_running() and not args.force:
        print("REFUSING: a perception pass appears to be running.")
        print("  Regenerating now would drop the database it is writing to and lose paid-for quota.")
        print("  Wait for it to finish (it stops itself on quota exhaustion), or pass --force.")
        sys.exit(2)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    print("STEP A - back up and export")
    records: list[dict] = []
    if Path(args.db_path).exists():
        shutil.copy2(args.db_path, BACKUP_DIR / f"fraudlens-{stamp}.db")
        records = export_perception(args.db_path)
        (BACKUP_DIR / f"perception-{stamp}.json").write_text(json.dumps(records), encoding="utf-8")
        # Also park it where generate_dataset can find it: the database is
        # about to be dropped, and align_clean_declarations needs these
        # records DURING generation to align clean cases against what
        # their photographs actually show.
        export = Path("data/cache/perception_export.json")
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(json.dumps(records), encoding="utf-8")
        print(f"  db -> data/backups/fraudlens-{stamp}.db")
        print(f"  perception -> data/backups/perception-{stamp}.json ({len(records)} records)")
    if GROUND_TRUTH.exists():
        shutil.copy2(GROUND_TRUTH, BACKUP_DIR / f"ground_truth-{stamp}.csv")
        print(f"  ground truth -> data/backups/ground_truth-{stamp}.csv")

    print("\nSTEP B - regenerate (fresh database)")
    Path(args.db_path).unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, "-u", "-m", "src.generate_dataset",
         "--seed", str(args.seed), "--count", str(args.count), "--db-path", args.db_path],
        text=True,
    )
    if result.returncode != 0:
        print(f"\nGENERATION FAILED (exit {result.returncode}). Restoring the backup.")
        shutil.copy2(BACKUP_DIR / f"fraudlens-{stamp}.db", args.db_path)
        sys.exit(1)

    print("\nSTEP C - restore perception by content hash")
    kept, dropped = restore_perception(args.db_path, records)
    print(f"  {kept}/{len(records)} records survived; {dropped} dropped (their image left the corpus)")


if __name__ == "__main__":
    main()
