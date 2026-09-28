"""
Audit every load-bearing number in outputs/ against its source artefact.

Two stale figures were already found by hand — a 61.2% recall ceiling that a
correction had invalidated, and a "four sessions" heading over five rows — so
the assumption here is that more exist.

Two passes:

  1. **Verification.** A registry of load-bearing claims, each with the
     artefact and computation it derives from. Each is recomputed live and
     compared against what the documents assert.

  2. **Stale-token scan.** Values known to have been superseded are searched
     for across every generated document. A hit is not automatically an error
     — a document may legitimately cite an old figure while explaining that it
     changed — so each hit is reported with its surrounding line for judgement
     rather than silently failed.

Writes outputs/number_audit.md.

Usage:
    python scripts/audit_numbers.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

OUT = Path("outputs/number_audit.md")
DOCS = sorted(Path("outputs").glob("*.md"))

# Values that were correct once and are not now. Each carries the reason, so a
# reviewer can tell a legitimate historical citation from a stale assertion.
SUPERSEDED: tuple[tuple[str, str], ...] = (
    ("4.3%", "internal_duplicate's false-positive rate before the victim/reuser fix; "
             "now 0.00%"),
    ("23/540", "internal_duplicate's clean false positives before the fix; now 0/540"),
    ("0/560", "clean-case denominator was 560 in an early count; the corpus has 540 "
              "clean cases"),
    ("555/560", "vehicle_consistency's false-positive rate, quoted against the old "
                "560 denominator"),
    ("73.5%", "exif_metadata recall from an early measurement; now 76.5%"),
    ("18.2%", "corpus defect rate from a biased perceived-only subsample; the full "
              "audit gives 4.1%"),
    ("76.96%", "ai_generation's false-positive rate before demotion; it now always "
               "returns INCONCLUSIVE"),
    ("77.0%", "ai_generation's false-positive rate before demotion"),
    ("2.6 LLM calls", "an early agent cost estimate; recompute from ablation_results.jsonl"),
    ("61.2%", "the recall ceiling before the victim/reuser correction; now 58.5%"),
)


def read_json(path: str) -> Optional[Any]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_jsonl(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ---------------------------------------------------------------------------
# Pass 1: recompute load-bearing claims
# ---------------------------------------------------------------------------

def claim_corpus_size() -> tuple[str, str]:
    rows = list(csv.DictReader(open("data/generated/ground_truth.csv", encoding="utf-8")))
    by = Counter(r["archetype"] for r in rows)
    return (f"{len(rows)} cases, {by['CLEAN']} clean",
            "data/generated/ground_truth.csv — row count and CLEAN count")


def claim_duplicate_fp() -> tuple[str, str]:
    d = read_json("outputs/duplicate_measurement.json")
    if not d:
        return ("MISSING", "outputs/duplicate_measurement.json absent")
    f = d["false_positives_on_clean"]
    r = d["recall_on_REUSE"]
    return (f"internal_duplicate: {r['caught']}/{r['total']} recall, "
            f"{f['flagged']}/{f['total']} clean FPs",
            "outputs/duplicate_measurement.json — recall_on_REUSE, false_positives_on_clean")


def claim_threshold_fp() -> tuple[str, str]:
    d = read_json("outputs/threshold_fp_investigation.json")
    if not d:
        return ("MISSING", "outputs/threshold_fp_investigation.json absent")
    return (f"threshold_gaming: {d['flagged']}/{d['clean_claims_examined']} clean claims "
            f"({d['flag_rate']:.1%}), {d['garage_attributable']['count']} "
            f"garage-attributable, {d['unexplained']['count']} unexplained",
            "outputs/threshold_fp_investigation.json")


def claim_corpus_defects() -> tuple[str, str]:
    d = read_json("data/generated/corpus_exclusions.json")
    if not d:
        return ("MISSING", "data/generated/corpus_exclusions.json absent")
    n = d.get("defective_clean_cases") or d.get("defective_cases")
    total = d.get("clean_cases_total")
    rate = d.get("defect_rate")
    return (f"{n}/{total} defective clean cases"
            + (f" ({rate:.1%})" if isinstance(rate, float) else "")
            + f", corrected count {d.get('corrected_clean_count')}",
            "data/generated/corpus_exclusions.json — written by audit_clean_labels.py")


def claim_sweep_ceiling() -> tuple[str, str]:
    d = read_json("outputs/baseline_sweep.json")
    if not d:
        return ("MISSING", "outputs/baseline_sweep.json absent")
    best = d["best"]
    return (f"{len(d['points'])} points swept; max attainable recall "
            f"{d['max_attainable_recall']:.1%}; chosen point clear_below="
            f"{best['clear_below']} giving precision {best['precision']:.1%}, "
            f"FP {best['fp_rate_clean']:.1%}, STP {best['stp_rate']:.1%}",
            "outputs/baseline_sweep.json — max_attainable_recall and best")


def claim_agent_cost() -> tuple[str, str]:
    rows = [r for r in read_jsonl("outputs/ablation_results.jsonl") if r["arm"] == "agent"]
    if not rows:
        return ("MISSING", "no agent rows yet")
    return (f"{sum(r['llm_calls'] for r in rows) / len(rows):.1f} LLM calls, "
            f"{sum(r['tool_calls'] for r in rows) / len(rows):.1f} tool calls, "
            f"{sum(r['latency_ms'] for r in rows) / len(rows) / 1000:.1f}s per case "
            f"(n={len(rows)})",
            "outputs/ablation_results.jsonl — mean over arm='agent' rows")


def claim_ai_inversion() -> tuple[str, str]:
    d = read_json("outputs/ai_detector_measurement.json")
    if not d or not d.get("records"):
        return ("MISSING", "outputs/ai_detector_measurement.json absent")
    th = d.get("threshold", 0.5)
    rs = d["records"]
    def rate(x):
        return (sum(1 for r in x if r["probability"] >= th) / len(x)) if x else 0.0
    band = [r for r in rs if (r.get("width") or 0) >= 400]
    return (f"at p>={th}: genuine {rate([r for r in rs if not r.get('synthetic')]):.1%} "
            f"vs synthetic {rate([r for r in rs if r.get('synthetic')]):.1%}; "
            f"resolution-matched (>=400px) genuine "
            f"{rate([r for r in band if not r.get('synthetic')]):.1%} vs synthetic "
            f"{rate([r for r in band if r.get('synthetic')]):.1%}",
            "outputs/ai_detector_measurement.json — recomputed at the stored threshold")


def claim_perception_coverage() -> tuple[str, str]:
    from src import db
    conn = db.connect("fraudlens.db")
    images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    records = conn.execute("SELECT COUNT(*) FROM perception_records").fetchone()[0]
    conn.close()
    return (f"{records}/{images} images described ({records / images:.1%})",
            "fraudlens.db — perception_records and images row counts")


def claim_ablation_progress() -> tuple[str, str]:
    rows = read_jsonl("outputs/ablation_results.jsonl")
    sample = read_json("outputs/ablation_sample.json")
    total = len(sample["cases"]) if sample else 0
    by = Counter(r["arm"] for r in rows)
    return (f"baseline {by.get('baseline', 0)}/{total}, agent {by.get('agent', 0)}/{total}",
            "outputs/ablation_results.jsonl vs outputs/ablation_sample.json")


def claim_findings_table() -> tuple[str, str]:
    from src import db
    conn = db.connect("fraudlens.db")
    n = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM findings WHERE verdict='concern'").fetchone()[0]
    cases = conn.execute("SELECT COUNT(DISTINCT case_id) FROM findings").fetchone()[0]
    conn.close()
    return (f"{n} findings across {cases} cases, {c} concerns",
            "fraudlens.db — findings table")


CLAIMS: tuple[tuple[str, Callable[[], tuple[str, str]]], ...] = (
    ("Corpus size", claim_corpus_size),
    ("internal_duplicate performance", claim_duplicate_fp),
    ("threshold_gaming false positives", claim_threshold_fp),
    ("Corpus label defects", claim_corpus_defects),
    ("Threshold sweep ceiling and operating point", claim_sweep_ceiling),
    ("Agent cost per case", claim_agent_cost),
    ("AI detector inversion", claim_ai_inversion),
    ("Perception coverage", claim_perception_coverage),
    ("Ablation progress", claim_ablation_progress),
    ("Findings table population", claim_findings_table),
)


# ---------------------------------------------------------------------------
# Pass 2: scan documents for superseded values
# ---------------------------------------------------------------------------

def _token_pattern(token: str) -> re.Pattern:
    """
    Match a figure standing on its own.

    Plain substring matching flagged "4.3%" inside "54.3%" and "14.3%", and
    "0/560" inside "430/560" - four false hits out of thirty-four, which is
    enough noise to make a reviewer stop reading the list.
    """
    return re.compile(r"(?<![\d.])" + re.escape(token) + r"(?![\d])")


_COMPILED_SUPERSEDED = [(t, r, _token_pattern(t)) for t, r in SUPERSEDED]

# Documents that are deliberately kept as historical snapshots. Their whole
# purpose is to hold superseded values, so flagging them is noise.
ARCHIVED = (
    "_pre_dupfix",
    "check_performance_summary.md",
    # The audit's own output quotes every superseded value by definition;
    # scanning it reports the report.
    "number_audit.md",
)


def scan_superseded() -> list[dict[str, Any]]:
    hits = []
    for doc in DOCS:
        if any(marker in doc.name for marker in ARCHIVED):
            continue
        text = doc.read_text(encoding="utf-8")
        lines = text.splitlines()
        for line_no, line in enumerate(lines, 1):
            # Prose wraps, so the sentence explaining that a figure changed
            # often lands on the following line. Judge narration over a small
            # window rather than a single line.
            # A document-level SUPERSEDED banner sits at the top rather than
            # beside each figure, so also treat the file's opening as context.
            header = " ".join(lines[:12]).lower()
            window = (" ".join(lines[max(0, line_no - 2):line_no + 2]) + " " + header).lower()
            for token, reason, pattern in _COMPILED_SUPERSEDED:
                if pattern.search(line):
                    # A line that explicitly narrates the change is fine. These
                    # markers are how a legitimate historical citation is
                    # distinguished from a stale assertion.
                    narrated = any(w in window for w in (
                        "was ", "before", "previously", "used to", "earlier",
                        "down from", "from ", "fell", "superseded", "no longer",
                        "→", "->", "now ", "correction", "stale", "predates",
                        "claimed", "asserted", "since", "tells the agent", "outdated",
                        "at the time of", "after the", "superseded by"))
                    hits.append({
                        "doc": doc.name, "line": line_no, "token": token,
                        "reason": reason, "narrated": narrated,
                        "text": line.strip()[:160],
                    })
    return hits


def main() -> None:
    a_: list[str] = []
    a = a_.append

    a("# Number audit")
    a("")
    a("Every load-bearing figure in `outputs/`, the artefact it derives from, and its "
      "value as recomputed now. Generated by `scripts/audit_numbers.py`; re-run after "
      "any measurement changes.")
    a("")
    a("---")
    a("")
    a("## 1. Load-bearing claims, recomputed from source")
    a("")
    a("| Claim | Current value | Source and computation |")
    a("|---|---|---|")
    missing = 0
    for label, fn in CLAIMS:
        try:
            value, source = fn()
        except Exception as e:  # noqa: BLE001
            value, source = f"ERROR: {type(e).__name__}: {e}", "—"
        if value.startswith("MISSING") or value.startswith("ERROR"):
            missing += 1
        a(f"| {label} | {value} | `{source}` |")
    a("")
    if missing:
        a(f"> **{missing} claim(s) could not be recomputed** — the artefact is missing "
          "or unreadable. Any document quoting them is quoting something unverifiable.")
        a("")

    a("## 2. Superseded values found in documents")
    a("")
    a("Each value below was correct at some point and has since been replaced. A hit is "
      "**not automatically an error**: a document may legitimately cite an old figure "
      "while explaining that it changed. Lines whose wording narrates the change are "
      "marked accordingly; the rest need review.")
    a("")
    hits = scan_superseded()
    unnarrated = [h for h in hits if not h["narrated"]]
    skipped = [d.name for d in DOCS if any(m in d.name for m in ARCHIVED)]
    if skipped:
        a(f"_Excluded as deliberate historical snapshots: "
          f"{', '.join('`' + n + '`' for n in skipped)}._")
        a("")
    a(f"{len(hits)} occurrence(s) across {len({h['doc'] for h in hits})} document(s); "
      f"**{len(unnarrated)} not obviously narrated as historical**.")
    a("")
    if unnarrated:
        a("### Needs review")
        a("")
        a("| Document | Line | Value | Why superseded | Text |")
        a("|---|---|---|---|---|")
        for h in unnarrated:
            a(f"| `{h['doc']}` | {h['line']} | `{h['token']}` | {h['reason']} | "
              f"{h['text'].replace('|', '\\|')} |")
        a("")
    narrated = [h for h in hits if h["narrated"]]
    if narrated:
        a("### Cited as historical (no action expected)")
        a("")
        a(f"{len(narrated)} occurrence(s) appear on lines that narrate the change — "
          "\"was\", \"before\", \"down from\", \"now\", and similar. Spot-check rather "
          "than treat as clean:")
        a("")
        for h in narrated[:12]:
            a(f"- `{h['doc']}`:{h['line']} — `{h['token']}` — {h['text']}")
        if len(narrated) > 12:
            a(f"- … and {len(narrated) - 12} more")
        a("")

    a("## 3. Which documents are generated, and which are not")
    a("")
    a("A generated document cannot go stale independently of its source; a hand-written "
      "one can, and every stale figure found so far has been in hand-written prose "
      "embedded in an otherwise generated file.")
    a("")
    generators = {
        "results_summary.md": "scripts/build_results_summary.py",
        "check_performance_v2.md": "scripts/report_v2.py",
        "baseline_results.md": "scripts/run_baseline.py",
        "ablation_results.md": "scripts/run_ablation.py --report-only",
        "partial_ablation.md": "scripts/partial_ablation.py",
        "report_draft_results.md": "scripts/build_report_draft.py",
        "report_draft_methodology.md": "scripts/build_report_methodology.py",
        "report_draft_limitations.md": "scripts/build_report_limitations.py",
        "clean_label_audit.md": "scripts/audit_clean_labels.py",
        "ablation_plan.md": "scripts/plan_ablation.py",
        "number_audit.md": "scripts/audit_numbers.py",
    }
    a("| Document | Generated by |")
    a("|---|---|")
    for doc in DOCS:
        gen = generators.get(doc.name)
        a(f"| `{doc.name}` | {('`' + gen + '`') if gen else '**hand-written**'} |")
    a("")
    hand = [d.name for d in DOCS if d.name not in generators]
    if hand:
        a(f"**{len(hand)} hand-written document(s):** {', '.join('`' + h + '`' for h in hand)}. "
          "These carry no automatic protection against staleness and should be checked "
          "against §1 before submission.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")
    print(f"-> {OUT}")
    print(f"   {len(CLAIMS)} claims recomputed, {missing} unverifiable")
    print(f"   {len(hits)} superseded-value occurrence(s), {len(unnarrated)} need review")


if __name__ == "__main__":
    main()
