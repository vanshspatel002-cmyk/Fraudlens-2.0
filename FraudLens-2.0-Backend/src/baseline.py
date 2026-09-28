"""
fraudlens.baseline
====================

The rules-only scorer - the control arm of this project's central
ablation.

The experiment is: does an LLM agent reasoning over check findings beat
a fixed arithmetic rule applied to the same findings? That question is
only worth asking if the control is honest, so this module runs the
*same* checks over the *same* data producing the *same* Finding objects
as the agent arm. The single difference is what happens next: here a
weighted sum, there a language model. Nothing else may differ, or the
comparison measures the difference in inputs instead of the difference
in reasoning.

A weak baseline is the classic way to make an ablation flattering and
meaningless, so a few deliberate choices push the other way:

- Weights come from *measured* per-check performance on this corpus
  (see Check.weight), not from intuition about which check sounds
  important. The baseline is therefore already tuned to the data the
  agent will be tested on - an advantage the agent does not get.
- Thresholds are swept, not guessed. scripts/run_baseline.py sweeps them
  and reports the operating point that minimises false positives subject
  to keeping fraud recall above 80%, which is the same objective the
  agent will be judged on.
- INCONCLUSIVE contributes exactly zero. It is tempting to let a pile of
  inconclusive findings drift a case upward "because something is off",
  but that is precisely the reasoning that manufactures false positives:
  eight checks each saying "I could not tell" is not evidence, and a
  system that treats it as evidence will flag every case with many
  images.

Scoring
-------
    score = sum over CONCERN findings of (check weight x finding confidence)

Two independent factors, because they mean different things.
`Finding.confidence` is the check's claim about *this* image ("the OCR
was crisp", "the hash distance was zero"). `Check.weight` is the
system's claim about *the check* ("this check's CONCERNs have held up
under measurement"). A confident finding from an unreliable check must
not score like a confident finding from a reliable one, and multiplying
is the cheapest honest way to say so. It also means the demoted
ai_generation check (weight 0.0) contributes nothing no matter what it
reports - belt and braces alongside its forced INCONCLUSIVE verdict.

PASS contributes zero rather than a negative amount. Subtracting for
passes would let a case with many images accumulate enough credit to
mask a real CONCERN, which is a bad failure mode in a fraud system, and
it would make the score depend on how many photos a claimant happened to
upload.

Bands
-----
    < 0.3   CLEAR             straight through, no human touches it
    0.3-0.6 REQUEST_EVIDENCE  ask the claimant for specific artifacts
    0.6-1.0 DESK_REVIEW       a handler looks at it
    > 1.0   ESCALATE_SIU      the Special Investigation Unit looks at it

No band denies a claim. Recommendation has no REJECT value, so this is
not a policy that could be relaxed - it is unrepresentable. The ceiling
of this system's authority is "a human looks at it".

The narrative is templated from the concerning findings' own
explanations, never generated. Every check already had to produce one
plain sentence a human can read (see Finding), so the baseline's summary
is those sentences assembled in weight order. This keeps the control arm
genuinely LLM-free - a "baseline" that called a model to write its
summary would contaminate the very comparison it exists to support.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Optional

from .models import AgentDecision, Case, Finding, RiskBand, Verdict

POLICY_VERSION = "baseline-v1"

# Default operating point. scripts/run_baseline.py sweeps these and
# reports the best; these are the swept winners, recorded here so the
# module's own behaviour matches what the report claims.
CLEAR_BELOW = 0.3
REQUEST_EVIDENCE_BELOW = 0.6
DESK_REVIEW_BELOW = 1.0

# Cap on how many finding sentences go into one summary. A case that
# trips six checks does not need six sentences to be actionable, and an
# unbounded summary is unreadable in a queue UI.
MAX_NARRATIVE_FINDINGS = 4

# What to ask a claimant for when the score lands in the REQUEST_EVIDENCE
# band. AgentDecision refuses to be constructed with REQUEST_EVIDENCE and
# no named artifact - "send better photos" is not actionable - so this is
# a real requirement, not decoration. Keyed by the check that raised the
# concern, because what you need next depends on what looked wrong.
REQUESTED_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "internal_duplicate": (
        "a fresh photograph of the damage, taken now, with today's newspaper or a timestamp visible",
    ),
    "external_corpus": (
        "a fresh photograph of the damage, taken now, with today's newspaper or a timestamp visible",
    ),
    "exif_metadata": (
        "the original unedited photograph as it came off the camera or phone",
    ),
    "plate_ocr": (
        "a close-up photograph of the vehicle's number plate, filling the frame and legible",
    ),
    "threshold_gaming": (
        "the itemised repair estimate from the garage, showing parts and labour separately",
    ),
    "c2pa_credentials": (
        "the original unedited photograph as it came off the camera or phone",
    ),
}

# Used when a concerning check has no specific ask registered above. Never
# empty, because an empty list would raise from AgentDecision.
DEFAULT_ARTIFACTS: tuple[str, ...] = (
    "a fresh photograph of the damage, taken now, with today's newspaper or a timestamp visible",
)


def _weight_for(check_id: str) -> float:
    """
    The registered weight for a check, or 0.0 if the check is unknown.

    Unknown means retired or removed, and a finding from a check that is
    no longer in the battery must not move the score - it would let a
    stale findings row from a withdrawn check (vehicle_consistency, say)
    silently keep voting. Imported lazily to keep src.checks' import side
    effects out of module import time here.
    """
    from .checks import REGISTRY

    check = REGISTRY.get(check_id)
    return float(check.weight) if check is not None else 0.0


def score_case(findings: Iterable[Finding]) -> tuple[float, RiskBand]:
    """
    Weighted sum of the CONCERN findings, and the band it falls in.

    CONCERN contributes weight x confidence; INCONCLUSIVE and PASS
    contribute exactly zero. See the module docstring for why zero and
    not something small.
    """
    score = 0.0
    for finding in findings:
        if finding.verdict is Verdict.CONCERN:
            score += _weight_for(finding.check_id) * float(finding.confidence)
    return score, band_for(score)


def band_for(
    score: float,
    clear_below: float = CLEAR_BELOW,
    request_evidence_below: float = REQUEST_EVIDENCE_BELOW,
    desk_review_below: float = DESK_REVIEW_BELOW,
) -> RiskBand:
    """Map a score to a band. Thresholds are parameters so the sweep can vary them."""
    if score < clear_below:
        return RiskBand.CLEAR
    if score < request_evidence_below:
        return RiskBand.REQUEST_EVIDENCE
    if score < desk_review_below:
        return RiskBand.DESK_REVIEW
    return RiskBand.ESCALATE_SIU


def _concerning(findings: Iterable[Finding]) -> list[Finding]:
    """CONCERN findings, heaviest first, so the summary leads with the strongest evidence."""
    concerns = [f for f in findings if f.verdict is Verdict.CONCERN]
    concerns.sort(key=lambda f: _weight_for(f.check_id) * float(f.confidence), reverse=True)
    return concerns


def narrate(band: RiskBand, score: float, concerns: list[Finding]) -> str:
    """
    Assemble a human-readable summary from the findings' own sentences.

    Templated, never generated - see the module docstring. The check
    authors already wrote one plain sentence each; this puts them in
    order behind a lead line that states the routing decision, so a
    handler reads the outcome first and the reasons second.
    """
    if not concerns:
        return (
            f"No check raised a concern (risk score {score:.2f}). "
            "Routing straight through with no manual review."
        )

    lead = {
        RiskBand.CLEAR: (
            f"Minor concerns only (risk score {score:.2f}), below the review threshold. "
            "Routing straight through."
        ),
        RiskBand.REQUEST_EVIDENCE: (
            f"{len(concerns)} check(s) raised a concern (risk score {score:.2f}). "
            "Requesting further evidence from the claimant before assessment."
        ),
        RiskBand.DESK_REVIEW: (
            f"{len(concerns)} check(s) raised a concern (risk score {score:.2f}). "
            "Referring to a claims handler for desk review."
        ),
        RiskBand.ESCALATE_SIU: (
            f"{len(concerns)} check(s) raised a concern (risk score {score:.2f}). "
            "Referring to the Special Investigation Unit."
        ),
    }[band]

    shown = concerns[:MAX_NARRATIVE_FINDINGS]
    reasons = " ".join(f"({i}) {f.explanation}" for i, f in enumerate(shown, start=1))
    if len(concerns) > len(shown):
        reasons += f" (+{len(concerns) - len(shown)} further concern(s) recorded.)"

    # Never an accusation, and never a decision the system is not
    # entitled to make: the summary describes what was observed and where
    # the case is going, and stops there.
    return f"{lead} Reasons: {reasons}"


def _artifacts_for(concerns: list[Finding]) -> list[str]:
    """Named, specific asks - deduplicated, order preserved by finding weight."""
    artifacts: list[str] = []
    for finding in concerns:
        for artifact in REQUESTED_ARTIFACTS.get(finding.check_id, DEFAULT_ARTIFACTS):
            if artifact not in artifacts:
                artifacts.append(artifact)
    return artifacts or list(DEFAULT_ARTIFACTS)


def _confidence_for(band: RiskBand, score: float, concerns: list[Finding]) -> float:
    """
    How sure the baseline is of its own routing, in [0, 1].

    Distinct from the score, which is unbounded. A CLEAR with no concerns
    at all is a confident clear; a CLEAR sitting just under the threshold
    is not, and saying so is what lets a reviewer sort the queue
    sensibly. Kept modest at the top end - this is arithmetic over seven
    checks, and a rules engine claiming 0.99 certainty about fraud would
    be overstating what it knows.
    """
    if band is RiskBand.CLEAR:
        # 0.9 when nothing fired at all, decaying as the score approaches
        # the CLEAR ceiling.
        if not concerns:
            return 0.9
        return max(0.5, 0.9 - score)
    return min(0.85, 0.5 + score / 4.0)


def decide(
    findings: Iterable[Finding],
    case: Case,
    clear_below: float = CLEAR_BELOW,
    request_evidence_below: float = REQUEST_EVIDENCE_BELOW,
    desk_review_below: float = DESK_REVIEW_BELOW,
) -> AgentDecision:
    """
    Turn a case's findings into a routing decision, with no LLM involved.

    Returns an AgentDecision stamped policy_version="baseline-v1" and
    zero tool/iteration/LLM calls, which is both literally true and the
    thing that makes this arm identifiable in the database afterwards.
    """
    findings = list(findings)
    score = 0.0
    for finding in findings:
        if finding.verdict is Verdict.CONCERN:
            score += _weight_for(finding.check_id) * float(finding.confidence)
    band = band_for(score, clear_below, request_evidence_below, desk_review_below)
    concerns = _concerning(findings)

    return AgentDecision(
        case_id=case.case_id,
        recommendation=band.to_recommendation(),
        risk_band=band,
        score=round(score, 4),
        confidence=round(_confidence_for(band, score, concerns), 4),
        summary=narrate(band, score, concerns),
        supporting_finding_ids=[f.finding_id for f in concerns],
        # Only populated in the band that requires it - AgentDecision
        # enforces that REQUEST_EVIDENCE names at least one artifact.
        requested_artifacts=(_artifacts_for(concerns) if band is RiskBand.REQUEST_EVIDENCE else []),
        policy_version=POLICY_VERSION,
        # Zero, and not as a placeholder: this arm calls no tools, runs no
        # agent loop, and makes no LLM requests. These are the numbers the
        # ablation compares the agent's cost against.
        tool_calls_count=0,
        iterations_count=0,
        llm_calls_count=0,
    )


def run_case(conn: sqlite3.Connection, case: Case, check_ids: Optional[list[str]] = None) -> tuple[AgentDecision, list[Finding]]:
    """
    Convenience: run the battery over one case and decide on the result.

    Returns the findings alongside the decision so a caller can persist or
    re-score them without paying for the checks twice.
    """
    from .checks import run_checks

    findings = run_checks(conn, case, check_ids=check_ids)
    return decide(findings, case), findings
