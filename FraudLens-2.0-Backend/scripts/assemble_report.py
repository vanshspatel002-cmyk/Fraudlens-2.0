"""
Assemble outputs/report_full_draft.md from the section drafts.

Concatenation with structure: the section files are the source of truth, so
editing a section and re-running this is the only way the full draft changes.
Abstract, Future Work, Conclusion and the reference list are written here
because they exist only in the assembled document.

Figure references are inserted at the points where the surrounding text
discusses what the figure shows, and each carries the caption written by
scripts/make_figures.py rather than a second caption written here.

Reports the word count per section and flags any section thin relative to its
importance, since a section's length is a rough but useful proxy for whether it
has been written or merely gestured at.

Usage:
    python scripts/assemble_report.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

OUT = Path("outputs/report_full_draft.md")
FIGURES = Path("outputs/figures")

# (section title, source file, expected minimum words, importance)
# (title, source file, expected minimum words, importance, number mapping)
#
# The mapping renumbers each draft's own sections into the assembled order.
# Written per-section so a draft can be edited without knowing what precedes it.
SECTIONS: tuple[tuple[str, Optional[str], int, str, dict[str, str]], ...] = (
    ("Introduction and Problem Statement", "outputs/report_draft_introduction.md",
     900, "high", {"1": "1", "2": "2"}),
    ("Literature Review", "outputs/report_draft_related_work.md",
     900, "high", {"3": "3"}),
    ("Methodology", "outputs/report_draft_methodology.md",
     1400, "high", {"3": "4"}),
    # This draft carries both Results (its §4) and Discussion (its §5).
    ("Results and Discussion", "outputs/report_draft_results.md",
     1200, "high", {"4": "5", "5": "6"}),
    ("Limitations", "outputs/report_draft_limitations.md",
     800, "high", {"6": "7"}),
)

# Figures placed where the text discusses them.
FIGURE_ANCHORS: dict[str, tuple[str, str]] = {
    "fig2_recall_progression": (
        "outputs/report_draft_methodology.md",
        "### 3.8 Corpus falsifiability as a methodological finding",
    ),
    "fig3_false_positives_by_check": (
        "outputs/report_draft_results.md",
        "### 4.3 Attribution in threshold detection",
    ),
    "fig5_ai_detector_inversion": (
        "outputs/report_draft_results.md",
        "### 4.5 Negative results",
    ),
    "fig1_recall_by_archetype": (
        "outputs/report_draft_results.md",
        "### 4.6 Adjudication: rules versus agent",
    ),
    "fig4_perception_coverage": (
        "outputs/report_draft_limitations.md",
        "### 6.1 Vision-model coverage extends to roughly a tenth of the corpus",
    ),
}


def read(path: str) -> str:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def strip_preamble(text: str) -> str:
    """Drop a draft's own title and generator note; the assembled doc supplies them."""
    lines = text.splitlines()
    out, seen_body = [], False
    for line in lines:
        if not seen_body:
            if line.startswith("# ") or line.startswith("*") or line.strip() in ("", "---"):
                continue
            seen_body = True
        out.append(line)
    return "\n".join(out).strip()


def figure_block(name: str) -> str:
    caption = (FIGURES / f"{name}.txt")
    text = caption.read_text(encoding="utf-8").strip() if caption.exists() else ""
    # The caption files already open with "Figure N." — reuse rather than
    # writing a second caption that could drift from the first.
    return (f"\n![{name}](figures/{name}.png)\n\n"
            f"<sub>{text}</sub>\n\n" if text else
            f"\n![{name}](figures/{name}.png)\n\n")


def insert_figures(source_path: str, body: str) -> str:
    for name, (src, anchor) in FIGURE_ANCHORS.items():
        if src != source_path or anchor not in body:
            continue
        # Place the figure after the anchored subsection's first paragraph, so
        # the reader has the claim before the picture of it.
        idx = body.index(anchor) + len(anchor)
        nxt = body.find("\n### ", idx)
        para_end = body.find("\n\n", idx + 2)
        pos = para_end if (para_end != -1 and (nxt == -1 or para_end < nxt)) else idx
        body = body[:pos] + "\n" + figure_block(name) + body[pos:].lstrip("\n")
    return body



def renumber(body: str, mapping: dict[str, str]) -> str:
    """
    Rewrite section numbers so independently-written drafts compose.

    Each draft numbers its own sections from wherever its author started, so
    concatenating them produced two sections numbered 3 (Related Work and
    Methodology) and skipped 7 entirely. Rather than renumber the source
    drafts — which would force every section to know its neighbours — the
    assembled document renumbers, and the drafts stay independently editable.

    Cross-references of the form "§4.5" are rewritten with the same mapping,
    so a pointer written inside one draft still resolves after assembly.
    """
    def major_of(text: str) -> str:
        m = re.match(r"(\d+)", text)
        return m.group(1) if m else ""

    # "## 3. Related work" -> "## 3. Related work" (or whatever it becomes)
    def fix_h2(m):
        old, rest = m.group(1), m.group(2)
        return f"## {mapping.get(old, old)}.{rest}"

    body = re.sub(r"^## (\d+)\.(.*)$", fix_h2, body, flags=re.M)

    def fix_h3(m):
        old, minor, rest = m.group(1), m.group(2), m.group(3)
        return f"### {mapping.get(old, old)}.{minor}{rest}"

    body = re.sub(r"^### (\d+)\.(\d+)(.*)$", fix_h3, body, flags=re.M)

    def fix_ref(m):
        old, minor = m.group(1), m.group(2)
        new = mapping.get(old, old)
        return f"§{new}.{minor}" if minor else f"§{new}"

    body = re.sub(r"§(\d+)(?:\.(\d+))?", fix_ref, body)
    return body


def words(text: str) -> int:
    stripped = re.sub(r"```.*?```", " ", text, flags=re.S)
    stripped = re.sub(r"[|`*#>_\[\]()-]", " ", stripped)
    return len([w for w in stripped.split() if any(c.isalpha() for c in w)])


ABSTRACT = """
Motor insurance claims in India are increasingly assessed from claimant-supplied
photographs, and the cost of fabricating such a photograph has fallen sharply
with the availability of generative image models. Indian practice compounds the
exposure: claims below a conventional ₹50,000 surveyor threshold are typically
settled without independent inspection, leaving the highest-volume claim band
the least verified, and the IRDAI Fraud Monitoring Framework effective April
2026 requires insurers to document what was checked and why.

This project built and measured an agentic investigation and triage layer for
that setting. Evidence gathering is deterministic — eleven checks emit structured
findings with a three-valued verdict — while adjudication is delegated to a
language model that may call follow-up tools before routing a case to one of four
human actions. The system has no representation for rejecting a claim.

Evaluation used a synthetic corpus of 800 cases across eight fraud archetypes
with ground truth known by construction. Three checks achieved complete recall
on their target archetypes; three were measured to have no usable discriminative
power, including an AI-generation detector that, under a resolution-matched
control, flagged genuine photographs 50.8% of the time against 9.1% for
synthetic images. An ablation compared the agent against a rules-only scorer on
identical findings; on the cases completed under a rate-limited free tier the
paired recall difference favoured the agent but its confidence interval
included zero, and no claim of superiority is made.

Two findings are offered as the substantive contribution. First, two of the
three largest false-positive sources were correct detections attached to the
wrong party, remedied by attribution logic rather than by better detection —
suggesting that false-positive rate conflates two failure modes requiring
different fixes. Second, across five measurement rounds recall improved only
when the evaluation corpus was corrected and never when a detector was added;
three archetypes were initially unfalsifiable by construction. Corpus
construction, not detection logic, was the binding constraint.
""".strip()

FUTURE_WORK = """
### 8.1 Completing the ablation

The agent arm is bound by a free-tier allowance of roughly 100 requests per day
against a measured cost of approximately three model calls per case. Completing
it requires no new work, only quota. Establishing a difference of the magnitude
observed — rather than merely completing the sample — would require several
hundred fraud cases per arm, which is a funding question rather than a research
one.

### 8.2 Attribution as a first-class concern

The two attribution failures found here were discovered by inspection rather
than by any measurement designed to detect them. A system that reported, for
each finding, *whose* conduct it describes would have surfaced both immediately.
This appears generalisable: any detector operating over relationships between
cases — shared images, shared garages, shared claimants — can identify a
relationship correctly while assigning it to the wrong party.

### 8.3 Detecting fabricated absence

The `AI_GENERATED_BASELINE` archetype, in which an applicant submits a synthetic
photograph of an intact vehicle at policy inception, is undetected by anything in
the battery and was shown to be structurally undetectable by the approach
initially taken. The strongest real-world signal is cross-case linkage — a
vehicle inspected as undamaged that claims for damage shortly afterwards — which
this corpus cannot express because every case carries a unique registration and
claimant. A generator modelling repeat customers would make it measurable.

### 8.4 Perception coverage

Vision-model coverage reaches roughly a tenth of the corpus and competes for the
same quota as adjudication. A locally hosted captioning model would remove the
contention entirely and is the single change that would most improve the
measurement of perception-dependent checks.

### 8.5 Presentation of attributed findings

The threshold-band check is correct and its wording is not: it describes a
garage's billing pattern in a sentence whose grammatical subject is the
claimant. Revised text attributing the pattern explicitly to the repairer is
drafted and gated behind completion of the ablation, because both the baseline
narrative and the agent's reasoning consume that text verbatim and altering it
mid-run would leave the arm internally inconsistent. The wider question it
raises — how a system should phrase a finding about an institution when the
subject under review is an individual — applies to any check operating over
relationships rather than over a single case.

### 8.6 Deployment considerations

Nothing here has been exercised at production volume or against an adversary who
knows how it works. Three properties would need establishing before deployment:
behaviour under adversarial pressure once the check battery is known; latency and
cost at realistic claim volumes, where the check battery rather than the agent
dominates wall-clock time; and calibration of the reliability figures embedded in
the adjudication prompt, which were measured on this corpus and would not
transfer unchanged.

### 8.7 Evaluation against real claims

Every figure here describes a synthetic corpus with a measured label-defect rate
of 4.1%. Nothing establishes performance against genuine fraud, whose base rate
and sophistication are unknown to the system. This is the limitation that most
constrains what the work can claim, and the one least resolvable without an
industry partnership.
""".strip()

CONCLUSION = """
This project asked whether an agentic layer reasoning over deterministic check
outputs could produce better-justified triage decisions than a rules-based
scorer applied to the same evidence. The honest answer, on the evidence
gathered, is that the ablation does not establish it. The paired recall
difference favoured the agent and its confidence interval included zero.

Two narrower claims are supported. Where evidence exists in unstructured form
that no rule parses, the agent can act on it and a weighted sum cannot, because
a weighted sum has no term for evidence that produced no finding: `case-0091`
was cleared by the baseline and escalated by the agent, which had read a scene
description placing a Vadodara claim in the Sonoran Desert. The reasoning was
right and the action was wrong — the image was a corpus defect rather than a
fraudulent claimant — and the case is reported because it locates the agent's
advantage precisely while refusing to overstate it. And the four human actions,
the citation of specific findings, and the persisted reasoning trace together
produce the auditable record that a fraud probability cannot.

The more durable findings concern method rather than architecture. Two of the
three largest false-positive sources were correct detections attached to the
wrong party, remedied by attribution rather than by better detection, which
suggests that a single false-positive rate conflates failure modes requiring
different fixes. And across five measurement rounds, recall improved only when
the evaluation corpus was corrected and never when a detector was added — three
archetypes having been unfalsifiable by construction, the generator having
removed the very signal the detector sought. For any work evaluating detection
against synthetic data, treating the benchmark as an object of investigation
rather than as ground truth is not optional.

What is offered, then, is not a fraud detector. It is a triage layer that gathers
evidence reproducibly, reasons over it, routes every case to a human action, and
records why — together with a set of measurements, several of them negative,
about which of the available forensic techniques actually work on this problem.
""".strip()

REFERENCES = """
Attestiv. *Automated Photo and Video Forensic Analysis*. Attestiv Inc.

Coalition for Content Provenance and Authenticity. *C2PA Technical
Specification*, Version 1.3.

FRISS. *Trust Automation for P&C Insurance*. FRISS B.V.

Insurance Regulatory and Development Authority of India. *Fraud Monitoring
Framework*, effective April 2026.

Insurance Regulatory and Development Authority of India. *Protection of
Policyholders' Interests Regulations* — surveyor appointment provisions.

Radford, A., Kim, J. W., Hallacy, C., et al. *Learning Transferable Visual
Models From Natural Language Supervision* (CLIP). Proceedings of the 38th
International Conference on Machine Learning, 2021.

Shift Technology. *AI-Native Decision Automation for Insurance*. Shift
Technology SAS.

Truepic. *Controlled Capture and Content Authenticity*. Truepic Inc.
Integration with Verisk Xactware.

Verisk Analytics. *ClaimSearch Contributory Database*. Verisk Analytics Inc.

Zauner, C. *Implementation and Benchmarking of Perceptual Image Hash
Functions*. Upper Austria University of Applied Sciences, 2010.

Farid, H. *Photo Forensics*. MIT Press, 2016.
""".strip()


def main() -> None:
    parts: list[str] = []
    stats: list[tuple[str, int, int, str]] = []

    parts.append("# FraudLens: An Agentic Investigation and Triage Layer for "
                 "Photograph-Based Motor Insurance Claims")
    parts.append("")
    parts.append("*Full draft, assembled by `scripts/assemble_report.py` from the section "
                 "drafts in `outputs/`. Edit a section file and re-run; do not edit this "
                 "document directly.*")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("## Abstract")
    parts.append("")
    parts.append(ABSTRACT)
    stats.append(("Abstract", words(ABSTRACT), 250, "high"))
    parts.append("")
    parts.append("---")
    parts.append("")

    for title, path, minimum, importance, mapping in SECTIONS:
        raw = read(path) if path else ""
        if not raw:
            parts.append(f"## {title}")
            parts.append("")
            parts.append(f"_MISSING — `{path}` not found._")
            parts.append("")
            stats.append((title, 0, minimum, importance))
            continue
        body = strip_preamble(raw)
        body = insert_figures(path, body)
        body = renumber(body, mapping)
        parts.append(body)
        parts.append("")
        parts.append("---")
        parts.append("")
        stats.append((title, words(body), minimum, importance))

    parts.append("## 8. Future Work")
    parts.append("")
    parts.append(FUTURE_WORK)
    stats.append(("Future Work", words(FUTURE_WORK), 350, "medium"))
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("## 9. Conclusion")
    parts.append("")
    parts.append(CONCLUSION)
    stats.append(("Conclusion", words(CONCLUSION), 300, "high"))
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("## References")
    parts.append("")
    parts.append(REFERENCES)
    parts.append("")

    text = "\n".join(parts)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    total = sum(s[1] for s in stats)
    print(f"-> {OUT}")
    print(f"\n{'section':38s} {'words':>7s} {'min':>7s}  status")
    thin = []
    for title, count, minimum, importance in stats:
        status = "OK"
        if count == 0:
            status = "MISSING"
            thin.append((title, count, minimum, importance))
        elif count < minimum:
            status = f"THIN ({importance} importance)"
            thin.append((title, count, minimum, importance))
        print(f"{title:38s} {count:7d} {minimum:7d}  {status}")
    print(f"{'TOTAL':38s} {total:7d}")

    figs = sorted(p.stem for p in FIGURES.glob("*.png")) if FIGURES.exists() else []
    placed = [n for n in FIGURE_ANCHORS if n in text]
    print(f"\nfigures available: {len(figs)}; referenced in the draft: {len(placed)}")
    unplaced = [f for f in figs if f not in placed]
    if unplaced:
        print(f"NOT REFERENCED: {', '.join(unplaced)}")

    if thin:
        print("\nSECTIONS NEEDING WORK:")
        for title, count, minimum, importance in thin:
            print(f"  {title}: {count} words against an expected {minimum} "
                  f"({importance} importance)")


if __name__ == "__main__":
    main()
