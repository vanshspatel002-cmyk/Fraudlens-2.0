"""
Move superseded documents into outputs/archive/ with a header saying so.

An unlabelled stale document in outputs/ is a trap: a reader picking up
check_performance_summary.md finds a coherent, confidently-written report
whose numbers were replaced weeks ago, with nothing on the page to say so.

Archiving rather than deleting, because several of these are the evidence
for how a figure changed - the pre-fix snapshots in particular are what make
the victim/reuser correction checkable rather than merely asserted.

Idempotent: a file already archived is left alone.

Usage:
    python scripts/archive_superseded.py
    python scripts/archive_superseded.py --list    # report only
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

OUTPUTS = Path("outputs")
ARCHIVE = OUTPUTS / "archive"

# filename -> (what superseded it, why it is kept rather than deleted)
SUPERSEDED: dict[str, tuple[str, str]] = {
    "check_performance_summary.md": (
        "outputs/check_performance_v2.md",
        "The v1 report, covering 7 checks against a 560-case clean denominator. The "
        "battery now has 11 checks and 540 clean cases, and several figures here "
        "(exif_metadata at 73.5%, ai_generation at 77.0% false positives) were "
        "superseded by later measurement. Kept because it records the reasoning that "
        "retired vehicle_consistency.",
    ),
    "check_performance_v2_pre_dupfix.md": (
        "outputs/check_performance_v2.md",
        "Snapshot taken immediately before the victim/reuser fix, showing "
        "internal_duplicate at 4.3% (23/540) false positives. Kept as the evidence "
        "that the fix changed what it is claimed to have changed.",
    ),
    "corpus_quality.md": (
        "outputs/clean_label_audit.md",
        "The perception-only geographic scan, covering just the 22 clean cases that "
        "already had vision coverage. Its 18.2% defect rate was reported as a lower "
        "bound and proved to be an overestimate: the full OCR audit of all 540 clean "
        "cases measured 4.1%. Kept because it is the record of that error.",
    ),
    "agent_smoke_test.md": (
        "outputs/ablation_results.md and outputs/partial_ablation.md",
        "The initial 10-case smoke test, run before the ablation existed. Its "
        "conclusions about adaptive depth were drawn from a sample small enough to "
        "mislead - it reported REUSE cases closing in one iteration with zero tools, "
        "which the ablation did not reproduce. Kept as the origin of the tool-use "
        "question the ablation went on to measure.",
    ),
    "ablation_results_pre_dupfix.jsonl": (
        "outputs/ablation_results.jsonl",
        "Baseline-arm results from before the victim/reuser fix. Kept because the "
        "before/after comparison in the ablation report is computed from it.",
    ),
    "baseline_findings_pre_dupfix.jsonl": (
        "outputs/baseline_findings.jsonl",
        "The findings cache from before the victim/reuser fix. Kept because the "
        "analysis showing which seven fraud cases lost accidental credit is computed "
        "by diffing it against the current cache.",
    ),
}

HEADER = """<!--
ARCHIVED — SUPERSEDED DOCUMENT. DO NOT QUOTE FIGURES FROM THIS FILE.

Superseded by: {replacement}

{why}

Archived by scripts/archive_superseded.py
-->

> **⚠ ARCHIVED — superseded by `{replacement}`.**
> Figures in this document are out of date and are retained only as a record.
> {why}

---

"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="report only, change nothing")
    args = parser.parse_args(argv)

    moved, already, missing = [], [], []

    for name, (replacement, why) in SUPERSEDED.items():
        src = OUTPUTS / name
        dst = ARCHIVE / name
        if dst.exists() and not src.exists():
            already.append(name)
            continue
        if not src.exists():
            missing.append(name)
            continue
        if args.list:
            moved.append(name)
            continue

        ARCHIVE.mkdir(parents=True, exist_ok=True)
        if name.endswith(".md"):
            text = src.read_text(encoding="utf-8")
            if "ARCHIVED — SUPERSEDED DOCUMENT" not in text:
                text = HEADER.format(replacement=replacement, why=why) + text
            dst.write_text(text, encoding="utf-8")
            src.unlink()
        else:
            # Data files cannot carry a header without corrupting them; the
            # directory README records their status instead.
            shutil.move(str(src), str(dst))
        moved.append(name)

    if not args.list and (moved or already):
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Archived artefacts",
            "",
            "Superseded documents and data snapshots. **Nothing here should be quoted "
            "as a current figure.** They are retained because several are the evidence "
            "that a measurement changed — a correction that cannot be checked is only "
            "an assertion.",
            "",
            "| File | Superseded by | Why kept |",
            "|---|---|---|",
        ]
        for name, (replacement, why) in sorted(SUPERSEDED.items()):
            if (ARCHIVE / name).exists():
                lines.append(f"| `{name}` | `{replacement}` | {why} |")
        (ARCHIVE / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    verb = "would archive" if args.list else "archived"
    print(f"{verb}: {len(moved)}")
    for n in moved:
        print(f"  {n}")
    if already:
        print(f"already archived: {', '.join(already)}")
    if missing:
        print(f"not found: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
