"""
fraudlens.checks.threshold
============================

Check 3 - threshold gaming, and the India-specific differentiator: a
claim amount just under a round survey/inspection threshold is common on
its own (real repair costs cluster near round numbers too), but a garage
whose claims cluster there far more than the population baseline is a
pattern-of-life signal a single claim amount can never be. scripts/
inspect_dataset.py's REPORT 1 found gaming garages at 57-71% of claims
in-band versus <=19% everywhere else - this check is that same
computation, run per-case at evaluation time instead of once as a
diagnostic.

Two independent signals, combined, not two independent checks: the
amount alone (weak - see above) gates whether the garage-level signal is
even computed; the garage-level in-band percentage (the real signal) is
what actually decides CONCERN vs INCONCLUSIVE. A case at a normal
garage that happens to land in-band is INCONCLUSIVE, not PASS, because
the amount itself is still a genuinely ambiguous data point - it's only
the *garage's* out-of-place clustering that turns ambiguous into
concerning.
"""

from __future__ import annotations

from typing import Any

from .. import db
from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check


def _lerp_confidence(value: float, lo: float, hi: float, conf_at_lo: float, conf_at_hi: float) -> float:
    if hi == lo:
        return conf_at_hi
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return conf_at_lo + t * (conf_at_hi - conf_at_lo)


def _in_band_pct(amounts: list[float], band_low: float, band_high: float) -> float:
    if not amounts:
        return 0.0
    return 100.0 * sum(1 for a in amounts if band_low <= a < band_high) / len(amounts)


def _garage_band_stats(conn, garage_id: str, band_low: float, band_high: float) -> dict[str, Any]:
    """
    Brute-force scan of every case, same "not worth indexing at this
    corpus size" reasoning as src.ingest.find_similar and db.get_all_cases
    itself (see that function's docstring) - only claims-type cases with
    an amount count, both for the garage and for the population baseline.
    """
    all_claims = [c for c in db.get_all_cases(conn) if c.agent_type == "claims" and c.claim_amount is not None]
    garage_amounts = [c.claim_amount for c in all_claims if c.garage_id == garage_id]
    population_amounts = [c.claim_amount for c in all_claims]
    return {
        "garage_claim_count": len(garage_amounts),
        "garage_in_band_pct": _in_band_pct(garage_amounts, band_low, band_high),
        "population_in_band_pct": _in_band_pct(population_amounts, band_low, band_high),
    }


class ThresholdGamingCheck(Check):
    check_id = "threshold_gaming"
    category = CheckCategory.ECONOMIC
    scope = "case"
    cost_inr = 0.0
    requires_perception = False
    target_archetypes = ("THRESHOLD_GAMING",)
    # 1.0 - 34/34 recall, and 0/275 false positives among clean claims at
    # ordinary garages. The headline 90/410 looks bad only against the
    # wrong denominator: every one of those 90 was booked at one of the 6
    # gaming garages, and this check is garage-scoped by design. It
    # detects a repair shop's billing pattern, and a claim booked into
    # that pattern genuinely is part of it. Arithmetic over a whole
    # garage's claim history, with no model in the path.
    weight = 1.0
    attributed_to = "garage"

    BAND_LOW = 45000.0
    BAND_HIGH = 50000.0
    GARAGE_CONCERN_PCT = 40.0
    MIN_GARAGE_CLAIMS = 5

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        if case.agent_type != "claims" or case.claim_amount is None:
            return []

        cfg = ctx.config
        band_low = cfg.get("threshold_band_low", self.BAND_LOW)
        band_high = cfg.get("threshold_band_high", self.BAND_HIGH)
        garage_concern_pct = cfg.get("threshold_garage_concern_pct", self.GARAGE_CONCERN_PCT)
        min_garage_claims = cfg.get("threshold_min_garage_claims", self.MIN_GARAGE_CLAIMS)

        amount = case.claim_amount
        in_band = band_low <= amount < band_high

        base_evidence = {
            "amount": amount,
            "band_low": band_low,
            "band_high": band_high,
            "garage_id": case.garage_id,
        }

        if not in_band:
            return [
                Finding(
                    check_id=self.check_id,
                    case_id=case.case_id,
                    category=self.category,
                    verdict=Verdict.PASS,
                    confidence=0.8,
                    explanation=(
                        f"Claim of ₹{amount:,.0f} is outside the ₹{band_low:,.0f}-₹{band_high:,.0f} "
                        "survey-threshold band; no evidence of threshold gaming from amount alone."
                    ),
                    evidence=base_evidence,
                )
            ]

        stats = _garage_band_stats(ctx.conn, case.garage_id, band_low, band_high)
        evidence = {**base_evidence, **stats}

        enough_claims = stats["garage_claim_count"] >= min_garage_claims
        garage_elevated = stats["garage_in_band_pct"] > garage_concern_pct

        if enough_claims and garage_elevated:
            confidence = _lerp_confidence(stats["garage_in_band_pct"], garage_concern_pct, 100.0, 0.6, 0.95)
            explanation = (
                f"Claim of ₹{amount:,.0f} falls below the ₹{band_high:,.0f} survey threshold; "
                f"garage {case.garage_id} has {stats['garage_in_band_pct']:.0f}% of its "
                f"{stats['garage_claim_count']} claims in this band versus a "
                f"{stats['population_in_band_pct']:.0f}% population average."
            )
            return [
                Finding(
                    check_id=self.check_id,
                    case_id=case.case_id,
                    category=self.category,
                    verdict=Verdict.CONCERN,
                    confidence=confidence,
                    explanation=explanation,
                    evidence=evidence,
                )
            ]

        if not enough_claims:
            explanation = (
                f"Claim of ₹{amount:,.0f} falls below the ₹{band_high:,.0f} survey threshold, but "
                f"garage {case.garage_id} has only {stats['garage_claim_count']} claim(s) on record - too few "
                f"to assess a pattern (minimum {min_garage_claims})."
            )
        else:
            explanation = (
                f"Claim of ₹{amount:,.0f} falls below the ₹{band_high:,.0f} survey threshold, but "
                f"garage {case.garage_id} does not show an elevated concentration of claims in this band "
                f"({stats['garage_in_band_pct']:.0f}% of {stats['garage_claim_count']} claims, "
                f"population average {stats['population_in_band_pct']:.0f}%)."
            )

        return [
            Finding(
                check_id=self.check_id,
                case_id=case.case_id,
                category=self.category,
                verdict=Verdict.INCONCLUSIVE,
                confidence=0.4,
                explanation=explanation,
                evidence=evidence,
            )
        ]


THRESHOLD_CHECK = register_check(ThresholdGamingCheck())
