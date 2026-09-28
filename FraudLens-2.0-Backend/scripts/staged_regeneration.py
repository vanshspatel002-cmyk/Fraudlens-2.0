"""
Regenerate the production corpus — gated, backed up, and verified.

--------------------------------------------------------------------------
Why this is gated rather than just run
--------------------------------------------------------------------------
`baseline_linkage` needs underwriting inspections joined to later claims on
the same vehicle, and those links exist only in database copies. Getting
them into production requires regenerating the corpus, which rewrites case
ids, registrations and loss dates.

The ablation's agent arm is mid-flight against the production database, with
a frozen sample naming specific case ids. Regenerating underneath it would
not corrupt the experiment loudly; it would corrupt it silently, because the
already-completed rows would remain readable while describing cases that no
longer mean the same thing. So this refuses to run until the arm reports its
full sample.

--------------------------------------------------------------------------
What it does, in order
--------------------------------------------------------------------------
 1. **Gate.** Refuses unless the agent arm is complete (or --force).
 2. **Back up** the database, ground-truth CSV and perception table under a
    single timestamp, so one directory restores a consistent set.
 3. **Export perception** keyed by image content hash.
 4. **Regenerate** the corpus.
 5. **Restore perception** by content hash — an image whose bytes are
    unchanged keeps its description, which matters because vision quota is
    the scarcest resource in the project.
 6. **Re-assert the corpus guarantees**: external-corpus disjointness, and
    absence of unintended near-duplicates among clean cases.
 7. **Report what changed**, per archetype and per guarantee.

Any failure after step 4 leaves the backup untouched and prints the restore
command, because a half-regenerated corpus is worse than an old one.

Usage:
    python scripts/staged_regeneration.py --check       # gate status only
    python scripts/staged_regeneration.py --dry-run     # verify against a copy
    python scripts/staged_regeneration.py               # the real thing
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

PRODUCTION = Path("fraudlens.db")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")
BACKUP_ROOT = Path("backups")
REPORT = Path("outputs/regeneration_report.md")
RESULTS = Path("outputs/ablation_results.jsonl")
SAMPLE = Path("outputs/ablation_sample.json")

# pHash Hamming distance below which two clean images are an unintended
# near-duplicate. Matches the duplicate check's own CONCERN bar.
NEAR_DUPLICATE_HAMMING = 8


def agent_progress() -> tuple[int, int]:
    done = 0
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    if json.loads(line)["arm"] == "agent":
                        done += 1
                except (json.JSONDecodeError, KeyError):
                    continue
    total = 0
    if SAMPLE.exists():
        total = len(json.loads(SAMPLE.read_text(encoding="utf-8"))["cases"])
    return done, total


def snapshot(db_path: Path) -> dict[str, Any]:
    """The facts a before/after comparison needs."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    out: dict[str, Any] = {}
    for table in ("cases", "images", "findings", "perception_records",
                  "agent_decisions", "audit_log"):
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            out[table] = None
    try:
        out["linked_registrations"] = conn.execute(
            "SELECT COUNT(*) FROM (SELECT vehicle_registration FROM cases "
            "WHERE vehicle_registration IS NOT NULL "
            "GROUP BY vehicle_registration HAVING COUNT(DISTINCT agent_type) > 1)"
        ).fetchone()[0]
    except sqlite3.Error:
        out["linked_registrations"] = None
    conn.close()
    if GROUND_TRUTH.exists():
        rows = list(csv.DictReader(open(GROUND_TRUTH, encoding="utf-8")))
        out["archetypes"] = dict(Counter(r["archetype"] for r in rows))
    return out


def export_perception(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM perception_records")]
    except sqlite3.Error:
        rows = []
    conn.close()
    return rows


def restore_perception(db_path: Path, records: list[dict[str, Any]]) -> int:
    """Re-insert by content hash. Images whose bytes changed simply find no row."""
    if not records:
        return 0
    conn = sqlite3.connect(db_path)
    hashes = {r[0] for r in conn.execute("SELECT DISTINCT content_hash FROM images")}
    restored = 0
    for record in records:
        if record.get("content_hash") not in hashes:
            continue
        columns = ", ".join(record.keys())
        placeholders = ", ".join("?" * len(record))
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO perception_records ({columns}) "
                f"VALUES ({placeholders})", tuple(record.values()))
            restored += 1
        except sqlite3.Error:
            continue
    conn.commit()
    conn.close()
    return restored


def assert_guarantees(db_path: Path) -> dict[str, Any]:
    """
    Re-check the two properties the corpus is supposed to hold.

    Both are checked rather than assumed, because a regeneration is exactly
    the moment they could silently stop holding.
    """
    conn = sqlite3.connect(db_path)
    results: dict[str, Any] = {}

    # 1. External-corpus disjointness: no image path is shared between the
    #    external pool and the main case pool.
    try:
        rows = conn.execute("SELECT case_id, path FROM images").fetchall()
    except sqlite3.Error:
        rows = []
    external = {p for _c, p in rows if p and "external" in str(p).replace("\\", "/")}
    main = {p for _c, p in rows if p and "external" not in str(p).replace("\\", "/")}
    overlap = external & main
    results["external_disjoint"] = {
        "external_images": len(external), "main_images": len(main),
        "overlap": len(overlap), "holds": len(overlap) == 0,
    }

    # 2. No unintended near-duplicates among clean cases.
    archetype: dict[str, str] = {}
    if GROUND_TRUTH.exists():
        archetype = {r["case_id"]: r["archetype"]
                     for r in csv.DictReader(open(GROUND_TRUTH, encoding="utf-8"))}
    try:
        phash_rows = conn.execute(
            "SELECT case_id, phash FROM images WHERE phash IS NOT NULL").fetchall()
    except sqlite3.Error:
        phash_rows = []
    clean = [(c, h) for c, h in phash_rows if archetype.get(c) == "CLEAN"]

    def hamming(a: str, b: str) -> int:
        try:
            return bin(int(a, 16) ^ int(b, 16)).count("1")
        except ValueError:
            return 64

    collisions = []
    for i in range(len(clean)):
        for j in range(i + 1, len(clean)):
            if clean[i][0] == clean[j][0]:
                continue
            if hamming(clean[i][1], clean[j][1]) <= NEAR_DUPLICATE_HAMMING:
                collisions.append((clean[i][0], clean[j][0]))
                if len(collisions) >= 20:
                    break
        if len(collisions) >= 20:
            break
    results["clean_near_duplicates"] = {
        "clean_images_compared": len(clean),
        "collisions_found": len(collisions),
        "examples": collisions[:5],
        "holds": len(collisions) == 0,
    }
    conn.close()
    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="gate status only")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the whole sequence against a copy, touching nothing")
    parser.add_argument("--force", action="store_true",
                        help="regenerate even though the ablation is incomplete")
    args = parser.parse_args(argv)

    done, total = agent_progress()
    ready = total > 0 and done >= total
    print(f"agent arm: {done}/{total or '?'}")

    if args.check:
        print("READY" if ready else "NOT READY — regeneration is gated")
        return 0 if ready else 1

    if not ready and not args.force and not args.dry_run:
        print(
            "\nREFUSING TO REGENERATE.\n"
            "The ablation's agent arm is incomplete and its frozen sample names "
            "specific case ids. Regenerating would not break it loudly - the completed "
            "rows would stay readable while describing cases that no longer mean the "
            "same thing. Wait for the arm, or pass --force having decided to discard "
            "it.\n"
            "Use --dry-run to verify this script end to end against a copy.",
            file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    target = PRODUCTION
    if args.dry_run:
        target = Path("fraudlens_regen_dryrun.db")
        shutil.copy(PRODUCTION, target)
        print(f"dry run: operating on {target}, production untouched")

    print(f"\n1. backing up -> {backup_dir}")
    shutil.copy(target, backup_dir / "fraudlens.db")
    if GROUND_TRUTH.exists():
        shutil.copy(GROUND_TRUTH, backup_dir / "ground_truth.csv")
    before = snapshot(target)
    (backup_dir / "snapshot_before.json").write_text(
        json.dumps(before, indent=2), encoding="utf-8")

    print("2. exporting perception records")
    records = export_perception(target)
    (backup_dir / "perception_records.json").write_text(
        json.dumps(records, indent=2, default=str), encoding="utf-8")
    print(f"   {len(records)} record(s) exported")

    if args.dry_run:
        # The point of a dry run is to prove backup, export, restore and the
        # guarantee assertions work. Actually regenerating would spend an hour
        # rebuilding images to prove something the real run will prove anyway.
        print("3. (dry run) skipping regeneration")
        restored = restore_perception(target, records)
        print(f"4. restored {restored}/{len(records)} perception record(s) by content hash")
        guarantees = assert_guarantees(target)
    else:
        print("3. regenerating the corpus")
        proc = subprocess.run([sys.executable, "-m", "src.generate_dataset"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print("REGENERATION FAILED - production left as the generator left it.",
                  file=sys.stderr)
            print((proc.stderr or proc.stdout)[-2000:], file=sys.stderr)
            print(f"\nRestore with:\n  copy {backup_dir / 'fraudlens.db'} {PRODUCTION}",
                  file=sys.stderr)
            return 1
        restored = restore_perception(target, records)
        print(f"4. restored {restored}/{len(records)} perception record(s) by content hash")
        guarantees = assert_guarantees(target)

    after = snapshot(target)
    write_report(backup_dir, before, after, len(records),
                 restored if "restored" in dir() else 0, guarantees, args.dry_run)

    print("\n5. guarantees")
    for name, data in guarantees.items():
        print(f"   {name}: {'HOLDS' if data.get('holds') else 'VIOLATED'}")
        if not data.get("holds"):
            print(f"     {json.dumps(data)[:220]}")

    print("\n6. changes")
    for key in ("cases", "images", "perception_records", "linked_registrations"):
        print(f"   {key:22s} {before.get(key)} -> {after.get(key)}")

    if args.dry_run:
        Path(target).unlink(missing_ok=True)
        print(f"\ndry run complete; {target} removed. Production untouched.")
    print(f"-> {REPORT}")
    return 0 if all(g.get("holds") for g in guarantees.values()) else 1


def write_report(backup_dir: Path, before: dict, after: dict, exported: int,
                 restored: int, guarantees: dict, dry_run: bool) -> None:
    a_: list[str] = []
    a = a_.append
    a("# Corpus regeneration report")
    a("")
    a(f"{'**DRY RUN** — production was not modified.' if dry_run else 'Live run.'}")
    a("")
    a(f"Backup: `{backup_dir}`")
    a("")
    a("## Changes")
    a("")
    a("| Item | Before | After |")
    a("|---|---|---|")
    for key in ("cases", "images", "findings", "perception_records",
                "agent_decisions", "audit_log", "linked_registrations"):
        a(f"| {key} | {before.get(key)} | {after.get(key)} |")
    a("")
    a(f"Perception: **{exported} exported, {restored} restored** by content hash. "
      "An image whose bytes changed finds no matching record and is simply "
      "undescribed again; vision quota is the scarcest resource here, so preserving "
      "what survives matters more than the count matching.")
    a("")
    if before.get("archetypes") or after.get("archetypes"):
        a("### Archetypes")
        a("")
        a("| Archetype | Before | After |")
        a("|---|---|---|")
        keys = sorted(set(before.get("archetypes", {})) | set(after.get("archetypes", {})))
        for k in keys:
            a(f"| {k} | {before.get('archetypes', {}).get(k, 0)} | "
              f"{after.get('archetypes', {}).get(k, 0)} |")
        a("")
    a("## Guarantees re-asserted")
    a("")
    for name, data in guarantees.items():
        a(f"- **{name}**: {'HOLDS' if data.get('holds') else '**VIOLATED**'} — "
          f"`{json.dumps({k: v for k, v in data.items() if k != 'examples'})}`")
    a("")
    a("`linked_registrations` counts registrations appearing on both an underwriting "
      "inspection and a claim. It is the property `baseline_linkage` needs and the "
      "reason this regeneration exists; a value of 0 after a live run means the "
      "generator's linkage pass did not fire.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(a_) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
