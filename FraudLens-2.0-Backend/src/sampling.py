"""
fraudlens.sampling
====================

Stratified case sampling, shared by every experiment that cannot afford to
run the whole corpus.

Why this exists as a module rather than a helper inside one script: the
agent smoke test drew its own sample, and drew it badly. It guaranteed one
underwriting case per side and then filled the rest by shuffling the whole
pool, which on that seed produced **five clean cases that were all
underwriting**. The claims policy was therefore never exercised on a clean
case, and the run could say nothing at all about claims-side false
positives - the single number the product cares most about. That is a
sampling bug, not a modelling one, and it invalidated a result that had
already cost a day of quota.

The fix is to stratify on the two axes that actually change the agent's
behaviour and then fill cells explicitly:

    agent_type  x  {CLEAN, FRAUD}

Both axes matter. `agent_type` selects an entirely different system prompt,
check list and tool set, so mixing the two and reporting one number hides
the thing under test. CLEAN vs FRAUD is the outcome axis: a sample without
clean cases measures recall with no false-positive denominator, which is
how a detector that flags everything looks perfect.

--------------------------------------------------------------------------
The cells are not equally deep, and the caller has to know that
--------------------------------------------------------------------------
In this corpus:

    claims       / CLEAN   410 cases, but only   4 perceived
    claims       / FRAUD   240 cases,           73 perceived
    underwriting / CLEAN   130 cases,           15 perceived
    underwriting / FRAUD    20 cases,            3 perceived

Two consequences worth stating rather than discovering later:

1. Vision quota, not case count, is the binding limit. Asking for four
   perceived claims-clean cases already exhausts that cell.
2. `underwriting / FRAUD` is a single archetype - AI_GENERATED_BASELINE -
   so any per-cell number for it is a statement about that one attack, not
   about underwriting fraud in general.

`sample_report()` prints the realised cell counts so a shortfall is visible
in the experiment's own output instead of silently skewing it.
"""

from __future__ import annotations

import csv
import random
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from src import db

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")

# The four strata. Ordered so output is stable across runs.
CELLS: tuple[tuple[str, str], ...] = (
    ("claims", "CLEAN"),
    ("claims", "FRAUD"),
    ("underwriting", "CLEAN"),
    ("underwriting", "FRAUD"),
)


def load_archetypes(path: Path = GROUND_TRUTH_CSV) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return {r["case_id"]: r["archetype"] for r in csv.DictReader(fh)}


def perceived_cases(conn: sqlite3.Connection) -> set[str]:
    """Cases with at least one image the vision pass has actually described."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT i.case_id FROM images i "
            "JOIN perception_records p ON i.content_hash = p.content_hash"
        )
    }


def cell_of(agent_type: str, archetype: str) -> tuple[str, str]:
    return (agent_type, "CLEAN" if archetype == "CLEAN" else "FRAUD")


def stratified_sample(
    conn: sqlite3.Connection,
    n: int,
    seed: int = 42,
    prefer_perceived: bool = True,
    archetypes: Optional[dict[str, str]] = None,
    restrict_archetypes: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """
    Draw `n` cases spread as evenly as possible over the four cells.

    Deterministic for a given (n, seed): every variant of an A/B test must
    see the *same* cases, or the comparison measures the sample rather than
    the change. Each cell is shuffled with its own seed so that growing `n`
    or exhausting one cell does not reshuffle the others.

    Cases with perception are preferred but not required. A case the vision
    pass never reached hands the agent a wall of INCONCLUSIVEs, which tests
    the fallback path rather than the reasoning - useful to include
    occasionally, misleading as a majority.

    Returns dicts, not Case objects, so callers get the archetype and cell
    alongside without a second lookup.
    """
    archetype = archetypes if archetypes is not None else load_archetypes()
    perceived = perceived_cases(conn) if prefer_perceived else set()
    wanted = set(restrict_archetypes) if restrict_archetypes else None

    cases = {c.case_id: c for c in db.get_all_cases(conn)}
    pools: dict[tuple[str, str], list[str]] = {c: [] for c in CELLS}
    for case_id, case in cases.items():
        arch = archetype.get(case_id)
        if arch is None:
            continue
        if wanted is not None and arch not in wanted and arch != "CLEAN":
            continue
        cell = cell_of(case.agent_type, arch)
        if cell in pools:
            pools[cell].append(case_id)

    ordered: dict[tuple[str, str], list[str]] = {}
    for index, cell in enumerate(CELLS):
        rng = random.Random(seed + index * 1000)
        with_p = sorted(c for c in pools[cell] if c in perceived)
        without = sorted(c for c in pools[cell] if c not in perceived)
        rng.shuffle(with_p)
        rng.shuffle(without)
        ordered[cell] = with_p + without

    # Round-robin rather than n//4 each: when a cell is shallower than its
    # share - underwriting/FRAUD has only 20 cases - the remainder has to
    # go somewhere, and spreading it over the deeper cells beats silently
    # returning fewer cases than asked for.
    chosen: list[str] = []
    cursors = {cell: 0 for cell in CELLS}
    while len(chosen) < n:
        progressed = False
        for cell in CELLS:
            if len(chosen) >= n:
                break
            pool = ordered[cell]
            i = cursors[cell]
            if i < len(pool):
                chosen.append(pool[i])
                cursors[cell] = i + 1
                progressed = True
        if not progressed:
            break  # every cell exhausted

    return [
        {
            "case_id": case_id,
            "archetype": archetype[case_id],
            "agent_type": cases[case_id].agent_type,
            "cell": "/".join(cell_of(cases[case_id].agent_type, archetype[case_id])),
            "perceived": case_id in perceived,
        }
        for case_id in chosen
    ]


def sample_report(sample: list[dict[str, Any]]) -> str:
    """One-line-per-cell summary, for printing into an experiment's output."""
    counts: dict[str, int] = {}
    perceived: dict[str, int] = {}
    for row in sample:
        counts[row["cell"]] = counts.get(row["cell"], 0) + 1
        if row["perceived"]:
            perceived[row["cell"]] = perceived.get(row["cell"], 0) + 1
    lines = [f"{len(sample)} case(s) across {len(counts)} cell(s):"]
    for cell in sorted(counts):
        lines.append(f"  {cell:24s} {counts[cell]:3d} ({perceived.get(cell, 0)} perceived)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The ablation sample
# ---------------------------------------------------------------------------

# Archetypes whose designated check actually works. Only these can support a
# recall claim; see outputs/ablation_plan.md. The others have a measured-zero
# detector, so both arms would see the same absence of evidence and the
# comparison would be vacuous.
WORKING_ARCHETYPES: tuple[str, ...] = (
    "REUSE", "EXTERNAL_SOURCING", "METADATA_FORGERY",
    "THRESHOLD_GAMING", "CONTEXT_MISMATCH",
)


def ablation_sample(
    conn: sqlite3.Connection,
    fraud_per_archetype: int = 15,
    clean_total: int = 25,
    seed: int = 42,
    archetypes: Optional[dict[str, str]] = None,
    exclude: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """
    The sample described in outputs/ablation_plan.md.

    Deliberately NOT `stratified_sample(100)`. That helper round-robins the
    four cells and would return 25 cases per cell - 50 clean, and fraud split
    by agent type rather than by archetype. This experiment needs the
    opposite shape: an equal number of cases from each *working fraud
    archetype*, because per-archetype recall is the claim being made, plus a
    smaller clean sample for the false-positive bound.

    Clean cases are drawn from the same seeded per-cell ordering that
    `stratified_sample` uses, so the clean half of this sample is always a
    prefix-subset of that helper's clean draw. That is what lets the label
    audit prioritise the right cases without the two ever disagreeing.

    `exclude` drops cases the label audit found defective - a clean case
    carrying a stock-agency watermark is not clean, and scoring against it
    penalises the arm that can read the watermark.
    """
    archetype = archetypes if archetypes is not None else load_archetypes()
    exclude = exclude or set()
    cases = {c.case_id: c for c in db.get_all_cases(conn)}
    perceived = perceived_cases(conn)

    def ordered_pool(candidates: list[str], salt: int) -> list[str]:
        rng = random.Random(seed + salt)
        with_p = sorted(c for c in candidates if c in perceived)
        without = sorted(c for c in candidates if c not in perceived)
        rng.shuffle(with_p)
        rng.shuffle(without)
        return with_p + without

    chosen: list[str] = []

    # Fraud: equal depth per working archetype.
    for index, arch in enumerate(WORKING_ARCHETYPES):
        pool = [c for c, a in archetype.items()
                if a == arch and c in cases and c not in exclude]
        chosen += ordered_pool(pool, 500 + index)[:fraud_per_archetype]

    # Clean: same per-cell ordering as stratified_sample, so this is a subset.
    clean_cells = [("claims", "CLEAN"), ("underwriting", "CLEAN")]
    per_cell = max(1, clean_total // len(clean_cells))
    for cell in clean_cells:
        salt = CELLS.index(cell) * 1000
        pool = [c for c, a in archetype.items()
                if a == "CLEAN" and c in cases
                and cases[c].agent_type == cell[0] and c not in exclude]
        chosen += ordered_pool(pool, salt)[:per_cell]

    return [
        {
            "case_id": case_id,
            "archetype": archetype[case_id],
            "agent_type": cases[case_id].agent_type,
            "cell": "/".join(cell_of(cases[case_id].agent_type, archetype[case_id])),
            "perceived": case_id in perceived,
        }
        for case_id in chosen
    ]
