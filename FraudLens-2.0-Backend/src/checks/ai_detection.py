"""
fraudlens.checks.ai_detection
===============================

Check 6 - "was this image synthesised rather than photographed?"

Runs umm-maybe/AI-image-detector, a Hugging Face image-classification
model, locally via transformers. No API, no per-call cost, hence
cost_inr = 0.

====================================================================
DEMOTED - and now measured against genuinely synthetic images
====================================================================
Every earlier measurement of this check reported UNMEASURABLE on its own
target, because the AI_GENERATED cases carried no images at all. Its only
number was a 76.96% false-positive rate on ordinary claim photographs.

Real AI-generated images now exist in the corpus (40 damaged, 20
undamaged), normalised to JPEG and downscaled to match the curated
resolution distribution so the detector cannot separate them on file
format or image size instead of on synthesis. The result:

    synthetic images flagged        40.4%   (n=57)
    CLEAN real photographs flagged  51.7%   (n=1080)
    discriminative lift            -11.3 pp

**The detector flags real claim photographs MORE often than genuinely
synthetic ones.** Negative discriminative value is no longer an inference
from cross-archetype rates; it is a direct measurement against the thing
the check exists to find.

Two controls, because a single pooled number invites the objection that
the populations differ in some other way:

1. Resolution-matched. Within the 400px+ bucket, synthetic images are
   flagged 9.1% and clean real photographs 50.5% - a 41.5 pp gap in the
   wrong direction at equal size.

2. Within-case. AI_GENERATED_BASELINE cases contain one synthetic image
   and one genuine one, at near-identical widths (median 577px vs 630px).
   The detector flags the synthetic image 10.0% of the time and the
   genuine photograph beside it 45.0% - it is 4.5x more likely to accuse
   the honest half of the same case.

So the earlier compression hypothesis was too kind. The model is not
merely insensitive to synthesis; on this domain its ranking is actively
inverted, and it responds to resolution far more than to provenance
(synthetic detection falls from 66.7% at 200-299px to 9.1% at 400px+
while the images get *more* synthetic, not less).

Conclusion, unchanged in direction and now much better evidenced:
**general-purpose AI-image detectors are unusable on low-quality
real-world claim photographs.** Weight stays 0.0, the verdict stays
forced to INCONCLUSIVE, and the check continues to run purely to record
the probability - the measurement is the contribution.

Re-promotion requires a detector that, on this corpus, flags synthetic
images materially MORE often than real ones. This one does the opposite.

--------------------------------------------------------------------
Why this check's confidence was capped even before demotion
--------------------------------------------------------------------
Published AI-image detectors generalise badly outside the generator and
image distribution they were trained on. A detector trained largely on
2022-2023 diffusion output, evaluated on photographs of damaged cars
that have been JPEG-recompressed by a claims pipeline, is being asked a
question well outside its training distribution - and these models fail
in both directions there: confidently labelling real photos artificial
(the failure that costs us, since it fires on honest claimants) and
missing current-generation synthetic images entirely.

So this check's confidence is capped at MAX_CONFIDENCE (0.6) no matter
how certain the model reports itself to be. That cap is not timidity, it
is calibration: the model's own probability is a statement about its
training distribution, not about this corpus, and propagating a 0.99
into a claim decision would give a downstream reviewer a false
impression of how much evidence actually exists. A CONCERN here should
mean "worth a human look alongside other signals", never "this is
synthetic".

evidence records the raw, uncapped probability and the exact model name,
so measured accuracy on this project's own dataset can be reported as a
finding in its own right rather than inherited from the model card.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

MODEL_NAME = "umm-maybe/AI-image-detector"

# Label strings vary by model revision; match case-insensitively on any
# of these rather than pinning to one exact spelling.
_ARTIFICIAL_LABELS = ("artificial", "ai", "fake", "generated", "synthetic")

# Module-level and lazily built: loading a vision transformer costs real
# seconds, and a batch run over 1,300 images must pay that once, not
# once per image (let alone once per case). Same pattern as
# ingest.CLIPEmbedder's module-global embedder.
_pipeline: Any = None
_load_error: Optional[str] = None
_load_attempted = False


def get_pipeline() -> Any:
    """Returns the classification pipeline, or None if it could not be loaded."""
    global _pipeline, _load_error, _load_attempted
    if not _load_attempted:
        _load_attempted = True
        try:
            from transformers import pipeline

            _pipeline = pipeline("image-classification", model=MODEL_NAME, device=-1)
        except Exception as e:  # noqa: BLE001 - missing model, no network, incompatible transformers
            _load_error = type(e).__name__  # Never persist cache paths, URLs or credential-bearing exceptions.
    return _pipeline


def _artificial_probability(predictions: list[dict[str, Any]]) -> Optional[float]:
    """
    Pull the artificial-class probability out of the pipeline's
    [{"label": ..., "score": ...}, ...] output. Returns None if no label
    looks like an artificial class, rather than guessing - silently
    treating an unrecognised label set as "0% artificial" would turn a
    model swap into a check that quietly always passes.
    """
    for prediction in predictions:
        label = str(prediction.get("label", "")).lower()
        if any(token in label for token in _ARTIFICIAL_LABELS):
            return float(prediction["score"])
    return None


class AIGenerationCheck(Check):
    check_id = "ai_generation"
    category = CheckCategory.PROVENANCE
    scope = "image"
    cost_inr = 0.0  # runs locally; no API call to pay for
    requires_perception = False
    target_archetypes = ("AI_GENERATED",)

    # 0.0 - demoted. Measured 76.96% false positives on clean cases, and
    # clean cases flagged more often than any fraud archetype (negative
    # discriminative value). The check runs for its measurement only and
    # must not be able to move a decision. See the module docstring.
    weight = 0.0
    attributed_to = "image"
    limitation = (
        "Measured inverted: at matched resolution it flags genuine photographs 50.8% of the time against 9.1% for synthetic ones."
    )

    # Retained as *reporting* bands, not verdict thresholds - run() no
    # longer branches on them. They label the probability in evidence so
    # the historical distribution stays reconstructible from stored
    # findings.
    CONCERN_THRESHOLD = 0.80
    INCONCLUSIVE_THRESHOLD = 0.60
    MAX_CONFIDENCE = 0.6

    def run(self, ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        concern_threshold = cfg.get("ai_concern_threshold", self.CONCERN_THRESHOLD)
        inconclusive_threshold = cfg.get("ai_inconclusive_threshold", self.INCONCLUSIVE_THRESHOLD)

        classifier = get_pipeline()
        return [
            self._check_one_image(ctx, image, classifier, concern_threshold, inconclusive_threshold)
            for image in ctx.images
        ]

    def _check_one_image(
        self,
        ctx: CheckContext,
        image: Image,
        classifier: Any,
        concern_threshold: float,
        inconclusive_threshold: float,
    ) -> Finding:
        def finding(verdict: Verdict, confidence: float, explanation: str, evidence: dict[str, Any]) -> Finding:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence={"image_id": image.image_id, "model": MODEL_NAME, **evidence},
            )

        if classifier is None:
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "AI-generation detection unavailable - the detector model could not be loaded.",
                {"reason": _load_error or "model unavailable"},
            )

        try:
            predictions = classifier(image.path)
        except Exception as e:  # noqa: BLE001 - unreadable file, unexpected mode; never kill the run
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "AI-generation detection could not run on this image.",
                {"error": f"{type(e).__name__}: {e}"},
            )

        probability = _artificial_probability(predictions)
        if probability is None:
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "AI-generation detector returned no recognisable artificial-class label.",
                {"raw_predictions": predictions},
            )

        # The band this probability *would* have fallen in before
        # demotion. Recorded so the measured distribution can be rebuilt
        # from stored findings; it drives nothing.
        if probability >= concern_threshold:
            band = "high"
        elif probability >= inconclusive_threshold:
            band = "elevated"
        else:
            band = "low"

        evidence = {
            "artificial_probability": round(probability, 4),
            "reporting_band": band,
            "demoted": True,
            "weight": self.weight,
            "raw_predictions": [
                {"label": p.get("label"), "score": round(float(p.get("score", 0.0)), 4)} for p in predictions
            ],
        }

        # Always INCONCLUSIVE. There is deliberately no branch here: at a
        # measured 76.96% false-positive rate on clean cases, with clean
        # cases flagged more often than fraudulent ones, no probability
        # this model reports is evidence about a claim. Confidence is 0.0
        # for the same reason - the check ran, and learned nothing usable.
        # See the DEMOTED section of the module docstring before changing
        # any of this.
        return finding(
            Verdict.INCONCLUSIVE,
            0.0,
            f"An AI-image detector scored this image {probability:.2f} on its artificial class. "
            "This detector is recorded for measurement only and does not contribute to the "
            "assessment: on this corpus it flags honest claims more often than fraudulent ones.",
            evidence,
        )


AI_GENERATION_CHECK = register_check(AIGenerationCheck())
