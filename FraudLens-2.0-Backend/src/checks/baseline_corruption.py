"""
fraudlens.checks.baseline_corruption
======================================

"The break-in inspection says this vehicle is undamaged. Is it?"

Every other check in this battery asks about a *claim*. This one asks
about a policy application, and it is the only check that looks for fraud
which fabricates the **absence** of damage rather than its presence.

The attack it targets (AI_GENERATED_BASELINE) works like this: the
applicant's vehicle is already damaged, so at policy inception they
submit a synthetic image of an undamaged vehicle of the same make and
colour. That buys two things at once - a higher insured declared value
than the real vehicle supports, and a clean pre-existing-condition record
that later legitimises a claim for damage the car already had. The fraud
is committed months before any claim exists, which is precisely why no
claims-side check can see it.

The test is deliberately simple, because the contradiction is simple. The
inspection asserts "no damage". Perception looked at the photographs and
reported a severity per image. If any image shows minor damage or worse,
the declaration and the evidence disagree, and a human should look before
the policy is written.

--------------------------------------------------------------------
What this check does NOT detect, and why that had to be corrected
--------------------------------------------------------------------
This check was built to target AI_GENERATED_BASELINE and **it cannot
detect it**. Measuring it against its own target archetype is what
surfaced the error: 0/3 evaluable cases, and not by accident.

The reasoning failure is worth recording, because it is easy to repeat.
AI_GENERATED_BASELINE fabricates the *absence* of damage: the applicant's
real vehicle is damaged, so they submit a synthetic photograph of an
intact one. The submitted photographs therefore show an undamaged
vehicle, the declaration says "undamaged", and the two agree perfectly.
Perception confirms it - all 5 perceived images across those cases come
back `none` / "no damage visible". A check that fires on *disagreement*
between declaration and photograph is structurally blind to an attack
whose entire method is manufacturing agreement.

Worse than blind: pointed the wrong way. Before this correction the check
returned **PASS at up to 0.8 confidence** on those cases. The rules-only
baseline ignores PASS, so its score was unaffected - but the agent reads
finding explanations, so the treatment arm of the ablation was being
handed a sentence stating the fraudulent baseline was consistent with its
evidence. A check that endorses its own target archetype is worse than no
check, and the PASS wording below now says what was actually verified
instead of implying the baseline is sound.

`target_archetypes` is therefore empty. It is not a placeholder to be
filled in later: no check in this battery detects AI_GENERATED_BASELINE,
and the honest detector for it - "is this photograph synthetic?" - is
exactly the question `ai_generation` was demoted to weight 0.0 for
answering worse than chance (77% false positives, inverted by
resolution). Until there is a measured way to answer it, those 20 cases
are undetected, and the reports say so rather than crediting them to a
check that returns PASS on them.

The check is kept, rather than retired, because the contradiction it does
test for is a genuine underwriting control: a break-in inspection whose
own photographs show damage is a policy about to be written on a false
baseline, whichever way the falsehood runs. That direction simply does
not occur in this corpus, so its recall is UNMEASURABLE rather than 0%.

One consequence to note: because `target_archetypes` is now empty,
src/perception.py's _perception_blocked_archetypes() no longer promotes
AI_GENERATED_BASELINE up the stratified vision queue. That is correct.
Promoting cases so that a check which cannot use them may run is a way to
spend the scarcest resource in this project - 20 vision requests per key
per day - on cases no check can act upon.

--------------------------------------------------------------------
Scope and abstention
--------------------------------------------------------------------
Underwriting only. A claims case has an incident and is *expected* to
show damage, so running this there would flag every honest claim ever
filed - it returns [] rather than an INCONCLUSIVE, so claims cases stay
out of the denominator entirely, the same way threshold.py handles them.

Unknown severity, or no perception at all, is INCONCLUSIVE and never
CONCERN. The same rule as missing EXIF in metadata.py: an honest "I
cannot tell" must not be scored as suspicion, or the false-positive rate
- this system's primary metric - is destroyed by the cases the vision
pass has not reached yet.
"""

from __future__ import annotations

from typing import Any

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

# Severities that contradict a "no damage" declaration. "none" agrees with
# it; anything at or past "minor" does not.
CONTRADICTING_SEVERITIES = ("minor", "moderate", "severe")

# Ordered worst-last, so the most severe contradiction is the one reported.
SEVERITY_ORDER = ("none", "minor", "moderate", "severe")

# What an underwriting inspection asserts by existing at all. Recorded in
# evidence so the finding is self-contained: a reviewer should not have to
# know how underwriting works to read it.
DECLARED_CONDITION = "undamaged (break-in inspection)"


class BaselineCorruptionCheck(Check):
    check_id = "baseline_corruption"
    category = CheckCategory.IDENTITY
    scope = "case"
    cost_inr = 0.0
    requires_perception = True
    # Deliberately empty. See the module docstring: this check cannot
    # detect AI_GENERATED_BASELINE, and naming it here would credit the
    # check with a target it returns PASS on.
    target_archetypes = ()
    # 1.0 - a direct contradiction between a written declaration and what
    # the submitted photographs show. Like internal_duplicate's hash
    # match, this is closer to fact than to inference: either the picture
    # shows a dented panel or it does not.
    #
    # 0.0 - a MEASURED NEGATIVE RESULT, recorded the same way
    # vehicle_consistency's was rather than quietly left at a flattering
    # default. Two detection routes were built and measured against this
    # check's target archetype
    # (scripts/measure_baseline_signals.py, outputs/baseline_signal_measurement.json):
    #
    #   (a) cross-case linkage - UNAVAILABLE. Implemented below and
    #       correct against production data, but all 800 cases carry a
    #       unique registration AND a unique claimant, so there is nothing
    #       to join on. A corpus property, not a signal failure.
    #   (b) synthetic-image forensics - CANDIDATE, BUT CONFOUNDED.
    #       ai_generation separates the archetype at AUC 0.26 (inverted;
    #       0.74 with the sign flipped) and resolution IS matched this
    #       time - but JPEG quantisation is not, because every AI image
    #       was re-encoded by normalise_ai_images.py and the curated ones
    #       were not. This check has already produced one confounded
    #       result in this project; it does not get the benefit of the
    #       doubt twice. Not adopted.
    #
    # So the check has no demonstrated detection capability on this
    # corpus, and 0.0 says so. The contradiction logic below is retained
    # because it is a genuine underwriting control that this corpus simply
    # never exercises - not because it is expected to earn its weight back.
    weight = 0.0
    attributed_to = "vehicle"
    limitation = (
        "Cannot detect its target archetype: AI_GENERATED_BASELINE fabricates the absence of damage, so the declaration and the photographs agree by construction."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case

        # Claims cases have an incident and are supposed to show damage.
        # Returning [] keeps them out of the denominator entirely.
        if case.agent_type != "underwriting":
            return []

        observed: list[dict[str, Any]] = []
        worst_rank = -1
        worst_image = None
        for image in ctx.images:
            record = ctx.perception.get(image.content_hash)
            severity = (record.damage_severity or "").strip().lower() if record else None
            observed.append({
                "image_id": image.image_id,
                "damage_severity": severity or "unknown",
                "damage_description": (record.damage_description if record else None),
            })
            if severity in CONTRADICTING_SEVERITIES:
                rank = SEVERITY_ORDER.index(severity)
                if rank > worst_rank:
                    worst_rank, worst_image = rank, observed[-1]

        evidence: dict[str, Any] = {
            "declared_condition": DECLARED_CONDITION,
            "observed_severities": observed,
            "images_examined": len(observed),
        }

        def finding(verdict: Verdict, confidence: float, explanation: str) -> list[Finding]:
            return [Finding(
                check_id=self.check_id,
                case_id=case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence=evidence,
            )]

        # --------------------------------------------------------------
        # Cross-case linkage: the attack's real-world signature.
        #
        # A vehicle inspected as undamaged at inception that files a
        # damage claim shortly afterwards is the whole point of corrupting
        # a baseline. This is the strongest available signal against the
        # attack and it needs no pixels at all - which is exactly why it
        # is worth having even though this corpus cannot exercise it.
        #
        # Measured on this corpus: zero hits, because all 800 cases carry
        # a unique registration and a unique claimant, so there is nothing
        # to join on. The generator would have to model repeat customers
        # before this could fire. Kept because it is correct against
        # production data, where policies and claimants recur.
        # --------------------------------------------------------------
        linked = self._linked_later_claims(ctx)
        if linked:
            evidence["linked_later_claims"] = linked
            return finding(
                Verdict.CONCERN,
                0.8,
                f"This vehicle was inspected as undamaged, and {len(linked)} damage "
                f"claim(s) were subsequently filed against the same vehicle or "
                f"claimant ({', '.join(l['case_id'] for l in linked[:3])}). A baseline "
                "recorded as undamaged is what makes such a claim payable, so the "
                "inspection should be reviewed before the policy is relied upon.",
            )

        if worst_image is not None:
            severity = worst_image["damage_severity"]
            evidence["contradicting_image_id"] = worst_image["image_id"]
            evidence["contradicting_severity"] = severity
            # Confidence rises with how far past "no damage" the evidence
            # goes: a "severe" reading is much harder to explain away as a
            # vision model over-reading a scuff than a "minor" one.
            confidence = {"minor": 0.6, "moderate": 0.75, "severe": 0.85}[severity]
            description = (worst_image.get("damage_description") or "").strip()
            detail = f" ({description})" if description else ""
            return finding(
                Verdict.CONCERN,
                confidence,
                f"This inspection declares the vehicle undamaged, but one of the submitted "
                f"photographs shows {severity} damage{detail}. A policy written on this baseline "
                f"would record pre-existing damage as absent.",
            )

        known = [o for o in observed if o["damage_severity"] != "unknown"]
        if not known:
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                "The vehicle's condition could not be read from the inspection photographs, so "
                "the declared undamaged condition could not be checked against them.",
            )

        # Deliberately narrow wording. A synthetic photograph of an intact
        # vehicle produces this exact result, so "no contradiction found"
        # must not be reported as "the baseline is sound" - the agent reads
        # these explanations, and the stronger sentence was previously
        # telling it that a fabricated baseline checked out.
        return finding(
            Verdict.PASS,
            min(0.8, 0.5 + 0.1 * len(known)),
            f"All {len(known)} legible inspection photograph(s) show an undamaged vehicle, so "
            "nothing in them contradicts the declared condition. This does not establish that "
            "the baseline is genuine: an image showing an intact vehicle looks the same whether "
            "the vehicle is intact or the photograph was manufactured to say so.",
        )


    # Window within which a later claim is suspicious. 180 days is a
    # judgement call, not a measured threshold - long enough to cover the
    # "wait a bit so it looks unrelated" pattern, short enough that
    # ordinary wear does not dominate. Ambiguous by nature; noted here
    # rather than presented as derived.
    LINKAGE_WINDOW_DAYS = 180

    def _linked_later_claims(self, ctx: CheckContext) -> list[dict[str, Any]]:
        """Claims filed against the same vehicle or claimant after this inspection."""
        case = ctx.case
        try:
            rows = ctx.conn.execute(
                """
                SELECT case_id, claim_type, declared_time, vehicle_registration,
                       claimant_id, claim_amount
                FROM cases
                WHERE case_id != ?
                  AND agent_type = 'claims'
                  AND (vehicle_registration = ? OR claimant_id = ?)
                """,
                (case.case_id, case.vehicle_registration, case.claimant_id),
            ).fetchall()
        except Exception:  # noqa: BLE001 - a query failure must not crash the battery
            return []

        out: list[dict[str, Any]] = []
        for row in rows:
            declared = row[2]
            # Only claims *after* the inspection matter; an earlier claim
            # says nothing about a baseline established later.
            if declared and case.declared_time and str(declared) <= str(case.declared_time):
                continue
            out.append({
                "case_id": row[0],
                "claim_type": row[1],
                "declared_time": str(declared),
                "matched_on": ("vehicle_registration"
                               if row[3] == case.vehicle_registration else "claimant_id"),
                "claim_amount": row[5],
            })
        return out


BASELINE_CORRUPTION_CHECK = register_check(BaselineCorruptionCheck())
