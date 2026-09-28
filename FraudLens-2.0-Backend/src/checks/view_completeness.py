"""
fraudlens.checks.view_completeness
====================================

"Did this inspection actually photograph the whole vehicle?"

A break-in inspection at policy inception is supposed to establish the
vehicle's condition on all sides: four corners, the odometer, and a legible
registration plate. The fraud this check targets is not a manipulated
photograph but an *omitted* one — the applicant submits three convenient
angles and quietly leaves out the corner with the existing damage.

That is a different shape of attack from everything else in this battery.
There is nothing wrong with any individual image; the deception is in the
set. No per-image forensic check can see it, because each photograph is a
perfectly honest photograph of an undamaged part of a damaged car.

--------------------------------------------------------------------------
How coverage is estimated without a view classifier
--------------------------------------------------------------------------
The system has no model that names which corner of a vehicle an image
shows, and training one is out of scope. What it does have is a CLIP
embedding per image, and the useful property is comparative rather than
absolute: **four genuine views of a car are mutually dissimilar, and four
photographs taken from nearly the same angle are mutually similar.**

So the check computes pairwise cosine similarity across the case's images
and counts how many are mutually near-duplicate above a threshold. A set
whose images all sit above it is not coverage; it is one angle photographed
several times. Distinct views are counted by greedy clustering: an image
starts a new view if it is dissimilar to every view already seen.

This measures angle *diversity*, which is a proxy for coverage and not the
same thing. A set could show four genuinely different views and still omit
the damaged corner. The check is therefore evidence that an inspection is
incomplete, never evidence that one is complete, and its PASS wording says
so.

--------------------------------------------------------------------------
MEASURED NON-DISCRIMINATING ON THIS CORPUS - weight 0.0
--------------------------------------------------------------------------
All three components were measured separately against AI_GENERATED_BASELINE
(20 cases) and clean underwriting cases (130), and all three fail
(`outputs/view_completeness_measurement.json`):

**View count.** Every underwriting case in this corpus carries exactly two
images. A four-view requirement therefore fires on 100% of cases in both
classes and separates nothing. This is a property of the generator, which
never produces a complete inspection, so no case - honest or fraudulent -
can satisfy the requirement.

**Angle similarity.** AUC 0.35, which is inverted. Target images are LESS
mutually similar (mean 0.285) than clean ones (0.343), the opposite of the
hypothesis. The reason is how the corpus assembles cases: a clean case pairs
two photographs of one real vehicle, while a synthetic case draws from
unrelated source images that happen to be more varied. Acting on the rule as
written would flag the honest class.

**Plate visibility.** Plates are legible in 0% of target cases and 2.3% of
clean ones - both effectively zero, because plates are readable in only
0.22% of images corpus-wide. The component flags almost everything.

The check is kept rather than retired because the requirement it encodes is
real: a break-in inspection that photographs two angles has not established
the condition of the vehicle, and an insurer would want to know. What this
corpus cannot do is distinguish an applicant hiding a damaged corner from a
generator that simply never produced four photographs. Re-measure against
inspection data with genuine multi-view coverage before assigning weight.

--------------------------------------------------------------------------
Requested artifacts name the missing views
--------------------------------------------------------------------------
The underwriting policy's bias is toward requesting further evidence rather
than escalating, so this check's output is most useful when it says exactly
what to ask for. Where perception has read a plate the check knows the plate
is covered; where it has not, "a photograph showing the registration plate"
is a specific, actionable request rather than a general demand for "more
photographs".
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

# Above this cosine similarity two images are treated as the same view. 0.85
# is deliberately permissive: the cost of calling two genuinely different
# angles "the same" is a false CONCERN against an honest applicant, so the
# bar for merging views is set high enough that only near-duplicates merge.
SAME_VIEW_COSINE = 0.85

# A break-in inspection should cover four corners at minimum.
REQUIRED_VIEWS = 4

# The named views an inspection is expected to carry, used to phrase requests.
EXPECTED_ARTIFACTS = (
    "front three-quarter view showing the front bumper and both headlamps",
    "rear three-quarter view showing the rear bumper and tailgate",
    "full driver-side profile",
    "full passenger-side profile",
)
ODOMETER_ARTIFACT = "dashboard photograph showing the odometer reading"
PLATE_ARTIFACT = "photograph in which the registration plate is legible"


def _cosine(a: Any, b: Any) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return dot / (na * nb)


class ViewCompletenessCheck(Check):
    check_id = "view_completeness"
    category = CheckCategory.IDENTITY
    scope = "case"
    cost_inr = 0.0
    requires_perception = True
    # Deliberately empty. Measured against AI_GENERATED_BASELINE, all three
    # of this check's components fire on 100% of clean underwriting cases as
    # well - see the module docstring. Naming a target it cannot separate
    # would credit it with coverage it does not have.
    target_archetypes = ()
    # 0.0 - a MEASURED NEGATIVE on this corpus, recorded the way
    # vehicle_consistency's was. See the module docstring for what was
    # measured. The logic is retained because it encodes a genuine production
    # requirement, and because the reason it fails here is a corpus property
    # that a real inspection corpus would not share. It contributes nothing to
    # any score until measured against data that can test it.
    weight = 0.0
    attributed_to = "vehicle"
    limitation = (
        "Every underwriting case carries exactly two images against a four-view requirement, so it fires on 100% of both classes."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        # A claims case documents one incident and has no reason to show every
        # side of the vehicle; requiring it there would flag honest claims.
        if case.agent_type != "underwriting":
            return []

        images = list(ctx.images)
        evidence: dict[str, Any] = {
            "images_submitted": len(images),
            "required_views": REQUIRED_VIEWS,
            "same_view_cosine": SAME_VIEW_COSINE,
        }

        if not images:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                "This inspection has no photographs, so its coverage cannot be assessed.",
                evidence, artifacts=list(EXPECTED_ARTIFACTS) + [ODOMETER_ARTIFACT])]

        embedded = [i for i in images if getattr(i, "embedding", None) is not None]
        perceived = [i for i in images if i.content_hash in ctx.perception]
        evidence["images_with_embedding"] = len(embedded)
        evidence["images_with_perception"] = len(perceived)

        if not perceived and not embedded:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                "Neither image descriptions nor embeddings are available for this "
                "inspection, so the range of views it covers cannot be assessed.",
                evidence)]

        distinct, similarities = self._distinct_views(embedded)
        evidence["distinct_views_estimated"] = distinct
        if similarities:
            evidence["max_pairwise_cosine"] = round(max(similarities), 4)
            evidence["min_pairwise_cosine"] = round(min(similarities), 4)
            evidence["all_mutually_similar"] = bool(
                min(similarities) >= SAME_VIEW_COSINE)

        plate_seen = self._plate_visible(ctx, images)
        evidence["plate_visible"] = plate_seen

        missing: list[str] = []
        if distinct < REQUIRED_VIEWS:
            # Name the shortfall rather than the specific corners: without a
            # view classifier the check knows how many distinct angles exist,
            # not which ones are absent, and inventing names would be a guess
            # presented as a finding.
            shortfall = REQUIRED_VIEWS - distinct
            missing.extend(list(EXPECTED_ARTIFACTS)[:shortfall])
        if not plate_seen:
            missing.append(PLATE_ARTIFACT)

        if not embedded:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                "Image embeddings are unavailable, so the number of distinct views in "
                "this inspection could not be estimated."
                + ("" if plate_seen else " No registration plate was legible in any "
                   "photograph that was read."),
                evidence, artifacts=[PLATE_ARTIFACT] if not plate_seen else [])]

        if missing:
            reasons = []
            if distinct < REQUIRED_VIEWS:
                if evidence.get("all_mutually_similar"):
                    reasons.append(
                        f"all {len(embedded)} photographs are near-duplicates of one "
                        f"another (minimum pairwise similarity "
                        f"{evidence.get('min_pairwise_cosine')}), so they document one "
                        f"angle rather than several")
                else:
                    reasons.append(
                        f"only {distinct} distinct view(s) are present across "
                        f"{len(embedded)} photograph(s), against the {REQUIRED_VIEWS} a "
                        f"break-in inspection requires")
            if not plate_seen:
                reasons.append("no registration plate is legible in any photograph")
            confidence = 0.75 if distinct < REQUIRED_VIEWS and not plate_seen else 0.6
            return [self._finding(
                case.case_id, Verdict.CONCERN, confidence,
                "This inspection does not cover the vehicle: "
                + "; and ".join(reasons)
                + ". An incomplete set cannot establish the condition of the parts it "
                  "omits, which is what a baseline is for.",
                evidence, artifacts=missing)]

        return [self._finding(
            case.case_id, Verdict.PASS, 0.7,
            f"The inspection covers {distinct} distinct view(s) with a legible "
            f"registration plate. This confirms the photographs span the vehicle; it "
            f"does not confirm that any particular panel is undamaged.",
            evidence)]

    # -- helpers ---------------------------------------------------------

    def _finding(self, case_id: str, verdict: Verdict, confidence: float,
                 explanation: str, evidence: dict[str, Any],
                 artifacts: Optional[list[str]] = None) -> Finding:
        if artifacts:
            evidence["requested_artifacts"] = artifacts
        return Finding(
            check_id=self.check_id, case_id=case_id, category=self.category,
            verdict=verdict, confidence=confidence, explanation=explanation,
            evidence=evidence,
        )

    @staticmethod
    def _distinct_views(images: list) -> tuple[int, list[float]]:
        """
        Greedy clustering: an image opens a new view if it is dissimilar to
        every view already opened. Greedy rather than exhaustive because the
        sets are tiny - a handful of images - and the ordering effects that
        would matter at scale cannot bite here.
        """
        if not images:
            return 0, []
        similarities: list[float] = []
        for i in range(len(images)):
            for j in range(i + 1, len(images)):
                similarities.append(_cosine(images[i].embedding, images[j].embedding))

        representatives: list[Any] = []
        for image in images:
            if all(_cosine(image.embedding, r.embedding) < SAME_VIEW_COSINE
                   for r in representatives):
                representatives.append(image)
        return len(representatives), similarities

    @staticmethod
    def _plate_visible(ctx: CheckContext, images: list) -> bool:
        for image in images:
            record = ctx.perception.get(image.content_hash)
            if record is None:
                continue
            plate = (getattr(record, "plate_text", None) or "").strip()
            if plate and plate.lower() not in (
                    "none", "n/a", "unreadable", "not visible", "illegible", "unknown"):
                return True
        return False


VIEW_COMPLETENESS_CHECK = register_check(ViewCompletenessCheck())
