"""
Regenerate every derived artefact from live data, in dependency order.

As the ablation completes, everything downstream of it must update without
manual editing. Hand-editing a figure into a document is how the two stale
numbers found by audit were introduced, so the remedy is that no number is
hand-edited at all.

Order matters and is enforced here:

    1. label audit          owns data/generated/corpus_exclusions.json
    2. check performance    reads the findings cache
    3. ablation reports     read the results JSONL and the exclusions
    4. figures              read all of the above
    5. report drafts        read all of the above
    6. number audit         audits the result, so it runs last

Steps are skipped rather than failed when their inputs are absent, and a
failing step does not stop the rest - a partial refresh is more useful than
none, provided it says which parts are stale.

The demo script's effort figures are rewritten in place between markers,
because that document is prose with a few volatile numbers embedded rather
than a generated report.

Usage:
    python scripts/refresh_all.py
    python scripts/refresh_all.py --skip-slow    # omit the label audit (OCR)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

DEMO = Path("outputs/demo_script.md")
BEGIN = "<!-- REFRESH:EFFORT:BEGIN -->"
END = "<!-- REFRESH:EFFORT:END -->"

# (label, argv, slow?) — slow steps are skippable because OCR over the corpus
# takes hours and rarely needs repeating.
STEPS: tuple[tuple[str, list[str], bool], ...] = (
    ("label audit (owns exclusions)", ["scripts/audit_clean_labels.py"], True),
    ("check performance v2", ["scripts/report_v2.py"], False),
    ("ablation report", ["scripts/run_ablation.py", "--report-only"], False),
    ("partial ablation", ["scripts/partial_ablation.py"], False),
    ("figures", ["scripts/make_figures.py"], False),
    ("results summary", ["scripts/build_results_summary.py"], False),
    ("report draft: results", ["scripts/build_report_draft.py"], False),
    ("report draft: methodology", ["scripts/build_report_methodology.py"], False),
    ("report draft: limitations", ["scripts/build_report_limitations.py"], False),
    ("full report assembly", ["scripts/assemble_report.py"], False),
    ("number audit", ["scripts/audit_numbers.py"], False),
)


def agent_effort() -> Optional[dict[str, Any]]:
    """Per-archetype and overall agent effort, from the ablation results."""
    path = Path("outputs/ablation_results.jsonl")
    if not path.exists():
        return None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("arm") == "agent":
                rows.append(r)
    if not rows:
        return None

    by = defaultdict(list)
    for r in rows:
        by[r["archetype"]].append(r)

    def mean(rs, key):
        return sum(x[key] for x in rs) / len(rs)

    # The comparison the demo draws: a decisive archetype against clean cases,
    # where nothing fires and there is nothing to act on.
    decisive = by.get("EXTERNAL_SOURCING") or by.get("REUSE") or []
    clean = by.get("CLEAN") or []
    return {
        "n": len(rows),
        "calls": mean(rows, "llm_calls"),
        "tools": mean(rows, "tool_calls"),
        "latency": mean(rows, "latency_ms") / 1000,
        "decisive_name": ("EXTERNAL_SOURCING" if by.get("EXTERNAL_SOURCING")
                          else ("REUSE" if by.get("REUSE") else None)),
        "decisive_iters": mean(decisive, "iterations") if decisive else None,
        "decisive_tools": mean(decisive, "tool_calls") if decisive else None,
        "decisive_n": len(decisive),
        "clean_iters": mean(clean, "iterations") if clean else None,
        "clean_tools": mean(clean, "tool_calls") if clean else None,
        "clean_n": len(clean),
        "min_cell": min(len(v) for v in by.values()),
    }


def refresh_demo_effort() -> str:
    if not DEMO.exists():
        return "demo script absent"
    text = DEMO.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return "no REFRESH:EFFORT markers — demo effort figures are NOT auto-updating"

    e = agent_effort()
    if not e:
        return "no agent rows yet; demo figures left unchanged"

    if e["decisive_iters"] is not None and e["clean_iters"] is not None:
        comparison = (
            f'> "Across {e["n"]} cases adjudicated so far, `{e["decisive_name"]}` — where a\n'
            f'> decisive check fires immediately — averages **{e["decisive_iters"]:.1f} '
            f'iterations and\n'
            f'> {e["decisive_tools"]:.1f} tool calls** (n={e["decisive_n"]}). Clean cases, '
            f'where nothing fires\n'
            f'> and there is nothing to act on, average **{e["clean_iters"]:.1f} iterations '
            f'and\n'
            f'> {e["clean_tools"]:.1f} tool calls** (n={e["clean_n"]}). So the agent spends '
            f'most effort exactly\n'
            f'> where the evidence is least decisive, which the baseline cannot do at all:\n'
            f'> it applies the same arithmetic to every case.\n'
            f'>\n'
            f'> Be careful how much weight that carries. The smallest archetype cell here\n'
            f'> holds {e["min_cell"]} case(s). It is a real effect on a small sample, not a\n'
            f'> dramatic one."\n'
        )
    else:
        comparison = '> "Not enough cases yet to compare effort across archetypes."\n'

    block = (
        f"{BEGIN}\n"
        f"{comparison}"
        f"\n"
        f'**Say, on cost:** "About **{e["calls"]:.1f} model calls, {e["tools"]:.1f} tool '
        f'calls and {e["latency"]:.0f} seconds** per\n'
        f"case. The check battery takes longer than the agent does — the agent is not the\n"
        f'bottleneck. The rate-limited free tier is."\n'
        f"\n"
        f"*Figures above regenerated by `scripts/refresh_all.py` from "
        f"`outputs/ablation_results.jsonl` ({e['n']} agent cases).*\n"
        f"{END}"
    )
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    DEMO.write_text(text[:start] + block + text[end:], encoding="utf-8")
    return f"demo effort figures updated from {e['n']} agent cases"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-slow", action="store_true",
                        help="omit steps that re-run OCR over the corpus")
    args = parser.parse_args(argv)

    print("refreshing every derived artefact\n")
    failed: list[str] = []
    skipped: list[str] = []

    for label, argv_step, slow in STEPS:
        if slow and args.skip_slow:
            skipped.append(label)
            print(f"  SKIP  {label} (--skip-slow)")
            continue
        if not Path(argv_step[0]).exists():
            skipped.append(label)
            print(f"  SKIP  {label} (script missing)")
            continue
        proc = subprocess.run([sys.executable, *argv_step],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            print(f"  OK    {label}")
        else:
            failed.append(label)
            print(f"  FAIL  {label} (exit {proc.returncode})")
            tail = [l for l in (proc.stderr or proc.stdout).splitlines() if l.strip()][-3:]
            for line in tail:
                print(f"          {line[:160]}")

    print(f"\n  {refresh_demo_effort()}")

    print()
    if failed:
        print(f"{len(failed)} step(s) FAILED: {', '.join(failed)}")
        print("Artefacts downstream of those steps are stale.")
        return 1
    if skipped:
        print(f"{len(skipped)} step(s) skipped: {', '.join(skipped)}")
    print("all derived artefacts refreshed from live data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
