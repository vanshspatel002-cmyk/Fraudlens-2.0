"""
fraudlens.checks.duplicate
============================

Check 1 - internal duplicate detection, and the strongest signal in this
system: a photo genuinely cannot appear in two unrelated real incidents.
Every image submitted to a case is compared against every other image
ever ingested (src.ingest.find_similar already scans the whole corpus,
not just a sample) on two independent metrics - pHash Hamming distance
(near-identical bytes/crop/recompression) and CLIP cosine similarity
(same content, possibly a different photo of it) - because either one
alone has a failure mode the other doesn't: two different photos of the
same rare/distinctive vehicle can be CLIP-similar without being anywhere
near byte-identical, and a screenshot-of-a-screenshot can drift far
enough on CLIP to look unrelated while still hashing close on pHash.

--------------------------------------------------------------------------
Who copied whom: submission order
--------------------------------------------------------------------------
A duplicate is symmetric; blame is not. When two cases share a photograph,
one of them submitted it first and the other reused it. Flagging both is
what this check used to do, and it produced the ablation's only two clean
false positives: `case-0153` and `case-0162` were flagged because their
images had been copied *by* REUSE cases `case-0797` and `case-0776`. The
detection was correct and attached to the wrong party - the honest
claimant was being routed to the Special Investigation Unit for having
been robbed.

So the earlier submission now yields INCONCLUSIVE, naming the later case,
and only the later submission yields CONCERN. Recall on the fraud case is
untouched: the reuser is still flagged exactly as before.

**Caveat, stated because the measurement will look better than it is.**
This corpus is generated in blocks - every CLEAN case is written before
every REUSE case (creation ranks 20-559 versus 765-799) - so on this data
"earlier = victim" is true by construction, and the false-positive
improvement below is guaranteed rather than earned. The rule is right for
production, where submission time is real evidence, but this corpus cannot
test whether it generalises. Do not read the improved number as validation
of the heuristic.

Ties and unknown timestamps fall back to CONCERN. If order cannot be
established the safe direction is to flag rather than to excuse, since an
unflagged reuse is the more expensive error.
"""

from __future__ import annotations

from .. import db, ingest
from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check


def _lerp_confidence(value: float, lo: float, hi: float, conf_at_lo: float, conf_at_hi: float) -> float:
    """
    Linear interpolation of confidence between two anchor points, clamped
    to the [lo, hi] span regardless of whether lo < hi or lo > hi - used
    both for "confidence rises as hamming distance shrinks toward 0" and
    "confidence rises as cosine climbs toward 1.0", which run in opposite
    directions on their own axes.
    """
    if hi == lo:
        return conf_at_hi
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return conf_at_lo + t * (conf_at_hi - conf_at_lo)


class InternalDuplicateCheck(Check):
    """
    Thresholds live in ctx.config (overridable), with the defaults below.
    CONCERN needs CLIP to agree the two images are related at all -
    cosine >= COSINE_FLOOR - and then either metric to be damning:
    hamming <= HAMMING_CONCERN or cosine >= COSINE_CONCERN. Confidence is
    computed per-metric and the higher of the two kept, so a match that's
    extreme on one axis isn't dragged down by being merely borderline on
    the other.

    The COSINE_FLOOR veto is not a guess. Without it, this check fired
    CONCERN on 30 of 560 clean cases in this project's corpus, and 3 of
    those 30 were pure pHash coincidences - unrelated photos landing at
    hamming <= 8 with CLIP cosine as low as 0.55, which is CLIP saying
    plainly that they are not the same scene. Requiring cosine >= 0.90
    costs nothing on a genuine duplicate (a real reuse scores ~1.00 on
    cosine and 0 on hamming, clearing both bars by a wide margin) and
    removes that entire error class. src/checks/external_corpus.py's
    ExternalCorpusCheck applies the identical rule against the external
    index, for the identical reason.
    """

    check_id = "internal_duplicate"
    category = CheckCategory.HISTORY
    scope = "image"
    cost_inr = 0.0
    requires_perception = False
    # 1.0 - the strongest measurement in the battery: 35/35 REUSE recall
    # at 0/560 false positives on clean cases, after the CLIP veto removed
    # the last 3 pHash coincidences without costing any recall. A CONCERN
    # here is a near-exact image match, which is closer to fact than to
    # inference, so it is allowed to carry full weight.
    weight = 1.0
    attributed_to = "image"
    # REUSE only. EXTERNAL_SOURCING images come from outside the corpus,
    # so this check cannot see them by construction - the handful it does
    # hit are corpus/pool overlaps and are reported as incidental.
    target_archetypes = ("REUSE",)

    HAMMING_CONCERN = 8
    COSINE_CONCERN = 0.95
    COSINE_FLOOR = 0.90
    COSINE_INCONCLUSIVE = 0.88
    TOP_K = 10

    def run(self, ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        hamming_concern = cfg.get("duplicate_hamming_concern", self.HAMMING_CONCERN)
        cosine_concern = cfg.get("duplicate_cosine_concern", self.COSINE_CONCERN)
        cosine_floor = cfg.get("duplicate_cosine_floor", self.COSINE_FLOOR)
        cosine_inconclusive = cfg.get("duplicate_cosine_inconclusive", self.COSINE_INCONCLUSIVE)
        top_k = cfg.get("duplicate_top_k", self.TOP_K)

        # Computed once per case, not once per image: it depends only on
        # ctx.case.case_id (the exclusion), which every image in this
        # run() call shares. find_similar() already re-scans the whole
        # images table internally on every call it makes (one per image);
        # doing this same scan again per image on top of that would
        # double this check's cost against the corpus for no reason.
        compared = self._compared_count(ctx)

        findings: list[Finding] = []
        for image in ctx.images:
            findings.append(
                self._check_one_image(
                    ctx, image, compared, hamming_concern, cosine_concern, cosine_floor, cosine_inconclusive, top_k
                )
            )
        return findings

    def _check_one_image(
        self,
        ctx: CheckContext,
        image: Image,
        compared: int,
        hamming_concern: int,
        cosine_concern: float,
        cosine_floor: float,
        cosine_inconclusive: float,
        top_k: int,
    ) -> Finding:
        if image.embedding is None:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=Verdict.INCONCLUSIVE,
                confidence=0.0,
                explanation="This image has no CLIP embedding to compare against the rest of the corpus.",
                evidence={"image_id": image.image_id},
            )

        matches = ingest.find_similar(ctx.conn, image.embedding, exclude_case=ctx.case.case_id, top_k=top_k)

        if not matches:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=Verdict.INCONCLUSIVE,
                confidence=0.0,
                explanation="No other images exist in the corpus yet to compare against.",
                evidence={"image_id": image.image_id, "images_compared": compared},
            )

        candidates = [
            (other, cosine, ingest.hamming_distance(image.phash, other.phash)) for other, cosine in matches
        ]

        verdict, confidence, best = self._verdict_for(
            candidates, hamming_concern, cosine_concern, cosine_floor, cosine_inconclusive
        )
        best_image, best_cosine, best_hamming = best

        evidence = {
            "image_id": image.image_id,
            "matched_image_id": best_image.image_id,
            "matched_case_id": best_image.case_id,
            "hamming_distance": best_hamming,
            "cosine_similarity": round(best_cosine, 4),
            "images_compared": compared,
        }

        # A duplicate is symmetric; blame is not. Only the later submission
        # can have reused the earlier one.
        if verdict is Verdict.CONCERN:
            role = self._submission_role(ctx, best_image.case_id)
            evidence["submission_role"] = role
            if role == "earlier":
                return Finding(
                    check_id=self.check_id,
                    case_id=ctx.case.case_id,
                    category=self.category,
                    verdict=Verdict.INCONCLUSIVE,
                    confidence=0.0,
                    explanation=(
                        f"This image was submitted here first and later resubmitted in "
                        f"{best_image.case_id} (perceptual distance {best_hamming}, "
                        f"semantic similarity {best_cosine:.2f}). The duplication is "
                        f"evidence against {best_image.case_id}, not against this case."
                    ),
                    evidence=evidence,
                )

        explanation = self._explanation_for(verdict, best_image, best_hamming, best_cosine)

        return Finding(
            check_id=self.check_id,
            case_id=ctx.case.case_id,
            category=self.category,
            verdict=verdict,
            confidence=confidence,
            explanation=explanation,
            evidence=evidence,
        )

    @staticmethod
    def _submission_role(ctx: CheckContext, matched_case_id: str) -> str:
        """
        "earlier", "later", or "unknown" for this case against the match.

        Uses created_at - ingest time - rather than declared_time. The
        declared incident date is chosen by the claimant and a fraudster can
        put theirs anywhere; on the two known pairs in this corpus the
        REUSE case actually declares the *earlier* incident, so ordering on
        declared_time would invert the answer. Ingest time is the one
        timestamp the claimant does not control.
        """
        from .. import db

        try:
            mine = ctx.case.created_at
            other = db.get_case(ctx.conn, matched_case_id)
        except Exception:  # noqa: BLE001 - ordering is an refinement, never fatal
            return "unknown"
        if other is None or mine is None or other.created_at is None:
            return "unknown"
        if mine < other.created_at:
            return "earlier"
        if mine > other.created_at:
            return "later"
        return "unknown"  # exact tie: cannot apportion, so fall through to CONCERN

    @staticmethod
    def _compared_count(ctx: CheckContext) -> int:
        # This metric needs neither decoded embeddings nor hydrated Image
        # objects. Keep the comparison pool identical to find_similar().
        nonnull = "jsonb_typeof(embedding::jsonb)<>'null'" if db.is_postgres(ctx.conn) else "json_type(embedding)<>'null'"
        return ctx.conn.execute("""SELECT COUNT(*) FROM images
            WHERE case_id<>? AND embedding IS NOT NULL AND """ + nonnull,
            (ctx.case.case_id,)).fetchone()[0]

    def _verdict_for(
        self,
        candidates: list[tuple[Image, float, int]],
        hamming_concern: int,
        cosine_concern: float,
        cosine_floor: float,
        cosine_inconclusive: float,
    ) -> tuple[Verdict, float, tuple[Image, float, int]]:
        """
        Picks the single most concerning candidate and the verdict/
        confidence that goes with it. Priority: any candidate crossing
        the CONCERN bar beats any that only crosses the INCONCLUSIVE one,
        which beats plain PASS - a priority order, not independent votes.

        The CONCERN bar is "cosine >= cosine_floor AND (hamming <=
        hamming_concern OR cosine >= cosine_concern)" - see the class
        docstring for the measured reason CLIP gets a veto over the pHash
        path. Note the floor gates CONCERN only: a candidate that fails
        it can still land INCONCLUSIVE on the cosine >= cosine_inconclusive
        rule below, which is the correct outcome for "similar, but not
        conclusively the same photo".
        """
        concern_candidates = [
            c for c in candidates if c[1] >= cosine_floor and (c[2] <= hamming_concern or c[1] >= cosine_concern)
        ]
        if concern_candidates:
            best = min(concern_candidates, key=lambda c: (c[2], -c[1]))
            _, cosine, hamming = best
            hamming_conf = (
                _lerp_confidence(hamming, hamming_concern, 0, 0.6, 0.99) if hamming <= hamming_concern else 0.0
            )
            cosine_conf = _lerp_confidence(cosine, cosine_concern, 1.0, 0.6, 0.99) if cosine >= cosine_concern else 0.0
            return Verdict.CONCERN, max(hamming_conf, cosine_conf), best

        inconclusive_candidates = [c for c in candidates if c[1] >= cosine_inconclusive]
        if inconclusive_candidates:
            best = max(inconclusive_candidates, key=lambda c: c[1])
            _, cosine, _ = best
            confidence = _lerp_confidence(cosine, cosine_inconclusive, cosine_concern, 0.35, 0.6)
            return Verdict.INCONCLUSIVE, confidence, best

        best = max(candidates, key=lambda c: c[1])
        _, cosine, _ = best
        confidence = _lerp_confidence(cosine, 0.0, cosine_inconclusive, 0.95, 0.6)
        return Verdict.PASS, confidence, best

    @staticmethod
    def _explanation_for(verdict: Verdict, matched: Image, hamming: int, cosine: float) -> str:
        if verdict == Verdict.CONCERN:
            return (
                f"This image matches an image submitted in {matched.case_id} "
                f"(perceptual distance {hamming}, semantic similarity {cosine:.2f})."
            )
        if verdict == Verdict.INCONCLUSIVE:
            return (
                f"This image is visually similar to one submitted in {matched.case_id} "
                f"(perceptual distance {hamming}, semantic similarity {cosine:.2f}) - "
                "likely the same vehicle model, not conclusive evidence of reuse."
            )
        return (
            f"No matching image found elsewhere in the corpus (closest: {matched.case_id}, "
            f"perceptual distance {hamming}, semantic similarity {cosine:.2f})."
        )


DUPLICATE_CHECK = register_check(InternalDuplicateCheck())
