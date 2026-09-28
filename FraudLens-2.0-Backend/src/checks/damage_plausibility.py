"""
fraudlens.checks.damage_plausibility
======================================

"Does the money asked for match the damage in the photographs?"

A scuffed bumper and a ₹180,000 claim is the oldest inflation pattern in
motor insurance, and it is one of the few fraud signals that needs no
forensics at all - just the severity a competent observer would assign to
the picture, set against the amount on the form.

Severity to plausible claim range, in rupees:

    none        0 -   2,000     (no visible damage - a claim needs a reason)
    minor    2,000 -  25,000     (scuffs, small dents, a light or mirror)
    moderate 20,000 -  70,000    (panel replacement, bumper, door)
    severe  50,000 -  no ceiling (structural, multiple panels, write-off)

The bands overlap deliberately. Real repair costs do not partition
cleanly at a rupee boundary - a "minor" dent on a luxury door can cost
more than a "moderate" one on a hatchback - and overlapping bands make
the check refuse to split hairs at the edges, which is where a
false positive would come from.

Two design decisions worth stating:

**Most severe wins.** A case's severity is the worst finding across all
its images, not the average. A claim showing one wrecked quarter panel
and three photographs of undamaged bodywork is a severe claim; averaging
would let a claimant dilute the assessment by uploading more pictures of
intact car, which is both gameable and wrong.

**Only the ceiling is enforced, and only past a margin.** The check fires
when the amount exceeds the band's ceiling by more than 50%, and never
when it falls below the floor. Under-claiming is not fraud this system
needs to find - a claimant asking for less than the damage warrants is
not defrauding the insurer - and the 50% margin absorbs the genuine
spread of parts prices, labour rates and vehicle values that a severity
label cannot capture. The result is a check that only speaks when the gap
is too large to be explained by any of that.

INCONCLUSIVE when severity is unknown or absent. Skipped entirely for
underwriting cases, which have no claim amount to test.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

# (floor, ceiling) in INR. None means no ceiling.
SEVERITY_RANGES: dict[str, tuple[float, Optional[float]]] = {
    "none": (0.0, 2_000.0),
    "minor": (2_000.0, 25_000.0),
    "moderate": (20_000.0, 70_000.0),
    "severe": (50_000.0, None),
}

# Ordered worst-last, so max() over this ordering picks the most severe
# finding across a case's images.
SEVERITY_ORDER = ("none", "minor", "moderate", "severe")

# How far past the ceiling the claim must sit before this check speaks.
# 1.5 = "more than 50% above the plausible maximum for this severity".
CEILING_TOLERANCE = 1.5


def normalise_severity(value: Optional[str]) -> Optional[str]:
    """Map a perception severity string onto the known bands, or None."""
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in SEVERITY_RANGES else None


def worst_severity(values: list[Optional[str]]) -> Optional[str]:
    """The most severe recognised severity in the list, or None."""
    ranks = [SEVERITY_ORDER.index(s) for s in (normalise_severity(v) for v in values) if s is not None]
    return SEVERITY_ORDER[max(ranks)] if ranks else None


class DamagePlausibilityCheck(Check):
    check_id = "damage_plausibility"
    category = CheckCategory.ECONOMIC
    scope = "case"
    cost_inr = 0.0
    requires_perception = True
    # No archetype in this corpus inflates a claim beyond what its
    # photographs show - THRESHOLD_GAMING moves amounts *down*, under a
    # survey threshold, which is the opposite pattern. So there is
    # nothing here to measure recall against, and it is reported as n/a
    # rather than 0%. See Check.target_archetypes in base.py.
    target_archetypes = ()
    # 0.7 - the arithmetic is sound and the bands are defensible, but the
    # severity label underneath comes from a vision model's one-word
    # judgement of a photograph, and that is a softer input than a hash
    # match or a garage's billing history. Below the 1.0 checks, above
    # the ones that have never fired.
    weight = 0.7
    attributed_to = "claimant"
    limitation = (
        "No archetype in this corpus inflates a claim amount, so it has never had a target to be right about."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case

        # Underwriting cases are pre-policy inspections: no incident, no
        # claim amount, nothing to compare. Returning [] rather than an
        # INCONCLUSIVE keeps them out of the denominator entirely, the
        # same way threshold.py handles them.
        if case.agent_type != "claims" or case.claim_amount is None:
            return []

        severities = [
            ctx.perception[img.content_hash].damage_severity
            for img in ctx.images
            if img.content_hash in ctx.perception
        ]
        severity = worst_severity(severities)

        evidence: dict[str, Any] = {
            "claim_amount_inr": case.claim_amount,
            "observed_severities": severities,
            "severity_used": severity,
            "ceiling_tolerance": CEILING_TOLERANCE,
        }

        def finding(verdict: Verdict, confidence: float, explanation: str) -> list[Finding]:
            return [
                Finding(
                    check_id=self.check_id,
                    case_id=case.case_id,
                    category=self.category,
                    verdict=verdict,
                    confidence=confidence,
                    explanation=explanation,
                    evidence=evidence,
                )
            ]

        if severity is None:
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                "Damage severity could not be read from the photographs, so the claimed amount "
                "could not be assessed against them.",
            )

        floor, ceiling = SEVERITY_RANGES[severity]
        evidence["plausible_range_inr"] = [floor, ceiling]

        if ceiling is None:
            # "severe" has no upper bound: a written-off vehicle can cost
            # whatever the vehicle was worth, and this check has no way to
            # know that. It abstains rather than guessing a ceiling.
            evidence["ratio_to_ceiling"] = None
            return finding(
                Verdict.PASS,
                0.5,
                f"The photographs show severe damage, which is consistent with a claim of "
                f"₹{case.claim_amount:,.0f}.",
            )

        ratio = case.claim_amount / ceiling
        evidence["ratio_to_ceiling"] = round(ratio, 3)

        if ratio > CEILING_TOLERANCE:
            # Confidence grows with the size of the gap, capped well
            # short of certainty: the severity label is one model's read
            # of a photograph, and an unusual vehicle or an expensive
            # part can legitimately stretch a band.
            confidence = min(0.8, 0.45 + (ratio - CEILING_TOLERANCE) / 4.0)
            return finding(
                Verdict.CONCERN,
                confidence,
                f"The claim is for ₹{case.claim_amount:,.0f}, but the photographs show "
                f"{severity} damage, which typically costs up to about ₹{ceiling:,.0f} to repair "
                f"- the claim is {ratio:.1f}x that figure.",
            )

        return finding(
            Verdict.PASS,
            min(0.75, 0.45 + (1.0 - min(ratio, 1.0)) / 2.0),
            f"The claim of ₹{case.claim_amount:,.0f} is consistent with the {severity} damage "
            f"visible in the photographs.",
        )


DAMAGE_PLAUSIBILITY_CHECK = register_check(DamagePlausibilityCheck())
