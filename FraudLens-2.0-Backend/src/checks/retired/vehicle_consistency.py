"""
fraudlens.checks.retired.vehicle_consistency
==============================================

RETIRED - measured, found to carry no usable signal, withdrawn from the
battery. This module is not imported by src/checks/__init__.py and does
not register itself; see the RETIREMENT NOTICE below and the write-up in
outputs/retired_checks.md.

--------------------------------------------------------------------
RETIREMENT NOTICE
--------------------------------------------------------------------
Measured across all 800 cases (560 CLEAN, 595 with >=2 images):

    CLEAN              n=560   median minimum pairwise similarity 0.301
    EXTERNAL_SOURCING  n= 35   median minimum pairwise similarity 0.587

    false positives on clean cases: 555/560 (99.11%)
    EXTERNAL_SOURCING flagged:       19/35  (54.3%)

The signal runs *backwards*. Clean cases are less internally consistent
than fraud cases, so the check flags honest claims at nearly double the
rate it flags sourced ones. Clean-case minimum similarity spans
0.078-0.654, meaning the entire clean population sits below the 0.70
INCONCLUSIVE ceiling this check was given; no threshold separates the
populations. At 0.30 it would still flag 49.5% of honest claims.

The cause is mechanical, not a tuning error. CLIP compares *scene
semantics*, not vehicle identity. A legitimate claim pairs a tight crop
of crumpled metal with a wide shot of a car in a street - two
semantically distant scenes of one vehicle. A fraudulent case built from
a single substituted stock photo is *more* internally coherent than an
honest one. The check was therefore not retuned: tuning presumes a
separable signal, and the measurement says there is not one.

What would be required instead: vehicle re-identification models trained
for identity rather than scene similarity - detect and crop the vehicle
first, then compare make/model/colour/plate. See outputs/retired_checks.md.

--------------------------------------------------------------------

Original design intent follows, preserved unchanged.

Check 8 - do all the photos in this case actually show the same vehicle?

Compares every image in a case against every other by CLIP cosine
similarity. A genuine claim's photos are of one car from several angles,
which stays semantically close; a case assembled from photos of two
different vehicles - one borrowed to pad out the evidence, or a damage
shot lifted from elsewhere and mixed with the claimant's own car - shows
up as a pair that CLIP scores far apart.

Case-scoped rather than image-scoped, unlike most checks here: the
finding is about a *relationship between* a case's images, so there is
no single image it belongs to. A case with fewer than two images has no
pair to compare and returns no findings at all - an empty list, not an
INCONCLUSIVE, because "one photo" is not an inconclusive answer to this
question, it is the absence of the question.

Threshold caveat worth stating: 0.60 is a judgement about CLIP's
similarity scale, not a measured operating point on this corpus. Two
photos of the same car at different angles and crops routinely land
around 0.7-0.9; genuinely different vehicles usually fall below 0.6. But
a tight damage crop and a wide establishing shot of the *same* car can
score lower than intuition suggests, because CLIP is comparing scene
semantics, not vehicle identity. That is why the band 0.60-0.70 is
INCONCLUSIVE rather than being split down the middle, and why this check
is one signal for a human rather than a verdict on its own.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from ...models import CheckCategory, Finding, Verdict
from ..base import Check, CheckContext


class VehicleConsistencyCheck(Check):
    check_id = "vehicle_consistency"
    category = CheckCategory.IDENTITY  # "is this the insured vehicle?" - the
    # question this check asked, even though it answered it badly.
    scope = "case"
    cost_inr = 0.0
    requires_perception = False
    # No archetype in this corpus is built by mixing two vehicles' photos
    # into one case, so there is nothing to measure recall against.
    target_archetypes = ()

    CONCERN_BELOW = 0.60
    INCONCLUSIVE_BELOW = 0.70

    def run(self, ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        concern_below = cfg.get("vehicle_concern_below", self.CONCERN_BELOW)
        inconclusive_below = cfg.get("vehicle_inconclusive_below", self.INCONCLUSIVE_BELOW)

        usable = [img for img in ctx.images if img.embedding is not None]
        if len(usable) < 2:
            return []

        matrix = np.asarray([img.embedding for img in usable], dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        normalised = matrix / norms
        similarities = normalised @ normalised.T

        pairwise = []
        for i, j in combinations(range(len(usable)), 2):
            pairwise.append(
                {
                    "image_a": usable[i].image_id,
                    "image_b": usable[j].image_id,
                    "cosine_similarity": round(float(similarities[i, j]), 4),
                }
            )

        worst = min(pairwise, key=lambda p: p["cosine_similarity"])
        minimum = worst["cosine_similarity"]

        evidence = {
            "image_count": len(usable),
            "pair_count": len(pairwise),
            "pairwise_similarities": pairwise,
            "minimum_pair": worst,
            "minimum_similarity": minimum,
        }

        if minimum < concern_below:
            verdict = Verdict.CONCERN
            # Confidence grows as the pair falls further below the bar,
            # saturating at 0.85 - CLIP disagreement is strong evidence
            # but not proof of two vehicles, per the module docstring.
            confidence = min(0.85, 0.5 + (concern_below - minimum) * 2.0)
            explanation = (
                f"Two images in this case are visually dissimilar (semantic similarity {minimum:.2f}), "
                "suggesting they may show different vehicles."
            )
        elif minimum < inconclusive_below:
            verdict = Verdict.INCONCLUSIVE
            confidence = 0.3
            explanation = (
                f"The least similar pair of images in this case scores {minimum:.2f} - low enough to note, "
                "but consistent with the same vehicle shot at different angles or crops."
            )
        else:
            verdict = Verdict.PASS
            confidence = min(0.8, 0.4 + (minimum - inconclusive_below))
            explanation = (
                f"All images in this case are mutually consistent (lowest pair similarity {minimum:.2f}), "
                "consistent with a single vehicle."
            )

        return [
            Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence=evidence,
            )
        ]


# Deliberately NOT registered. The import of register_check is gone and
# this module is absent from src/checks/__init__.py, so a retired check
# cannot re-enter the battery by accident - it would take two separate
# edits, both of them obvious in review.
