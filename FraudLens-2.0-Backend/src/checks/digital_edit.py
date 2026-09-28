"""
fraudlens.checks.digital_edit
===============================

"Has this photograph been spliced, cloned, or otherwise edited?"

Pure image forensics - OpenCV and numpy only, no API, no model weights,
no perception record. That matters here: DIGITAL_EDIT was one of the two
archetypes with no check at all (8.8% recall, entirely incidental), and
unlike CONTEXT_MISMATCH it needs nothing this project does not already
have on disk.

Three independent signals, chosen because they fail differently. A
convincing paste has to survive all three, and an editor who defeats one
usually worsens another - flattening noise to hide a splice makes the
noise map *more* uniform than a real sensor produces, which the same
statistic detects from the other side.

(a) JPEG ghost / double compression
    A region pasted from another JPEG carries that image's compression
    history. Re-saving the whole image across a ladder of qualities and
    recording, per 8x8 block, which quality minimises reconstruction
    error produces a "ghost map". An unedited JPEG yields a spatially
    coherent map - every block agrees, because every block shares one
    history. A splice leaves a patch that disagrees with its
    surroundings. The statistic is the share of blocks disagreeing with
    the image's own modal quality.

(b) Noise inconsistency
    Sensor noise is a property of the camera and the exposure, so it is
    near-uniform across a genuine photograph. A pasted region brings its
    own. High-pass the image, take the local standard deviation over a
    grid, and measure how much those cell noise levels disagree - by
    median absolute deviation rather than variance, so one bright window
    or dark shadow does not masquerade as a splice.

(c) Edge / gradient discontinuity
    A paste boundary is a step in image statistics even when it is a
    smooth step in colour. Feathering hides it from the eye but leaves
    gradient energy concentrated along a contour that is straighter and
    more sustained than natural object edges. The statistic is the share
    of strong-gradient pixels that are *unnaturally sharp* - a real lens
    blurs edges across two or three pixels, a composite often does not.

====================================================================
MEASURED TWICE: still no usable power - weight 0.0
====================================================================
This check has now been measured against two different corpora, and the
second measurement is the interesting one because the first one's
diagnosis was acted on.

Round 1, against a generator that re-saved the whole composite at q85
TWICE:

    ghost 0.331 (INVERTED)  noise 0.469 (INVERTED)  edge 0.531
    combined AUC 0.531

Two signals came out *backwards*: edited images looked MORE internally
consistent than honest ones. The diagnosis was that re-encoding the
entire frame at one quality gives every 8x8 block the same most-recent
compression history, which is precisely what ghost analysis tests for the
absence of - the forgery was ironing its own evidence flat.

The generator was then fixed (src/generate_dataset.py): one save at q92
instead of two at q85, and for half the cases the pasted patch is pushed
through its own q55 cycle first so the spliced region genuinely carries a
different history from its host.

Round 2, against the fixed corpus:

    ghost 0.544  noise 0.535  edge 0.516
    combined AUC 0.546

    per variant:
      recompressed_patch  n=17  AUC 0.573  detected 5.9%
      single_save         n=17  AUC 0.519  detected 0.0%

**The diagnosis was right and the fix worked directionally.** Both
inverted signals flipped to the correct side of 0.5, and the variant
built to carry a distinct compression history is the more detectable of
the two, by 5.4 AUC points - exactly the predicted ordering. The
mechanism behaves the way the theory says it should.

**It is still not usable.** 0.546 is a coin with a slight lean; at the
operating point costing 5% false positives on clean images, recall is
2.9%. Weight stays 0.0 and the check keeps abstaining.

Why the signal stays weak, now that global recompression is ruled out:

  1. **The feathered mask.** The patch is composited under a Gaussian-
     blurred elliptical alpha, so its pixels are *blended* with the host
     rather than replacing them. A blend of two quantisation signatures
     is neither, and the distinctive history survives only near the
     centre of the ellipse where alpha is ~1.
  2. **Image size.** These photographs are 200-300px on the short side,
     so the whole frame is only ~30x40 blocks and the patch a few dozen.
     Block-level statistics need more blocks than that to separate
     populations.

So the corrected, narrower claim - and it is narrower than round 1's:

    **Not that JPEG-ghost forensics do not work, and no longer that this
    corpus cannot test them at all: they do respond correctly here once
    the global re-encode is removed. The claim is that whole-frame ghost,
    noise and edge statistics are too weak to detect a SMALL, FEATHERED
    composite in a LOW-RESOLUTION photograph - which is what a motor
    claim actually contains.**

What would be required: localise the analysis to candidate regions
instead of averaging over the frame (block-level ghost maps scored for
spatial clustering rather than global modal share), or copy-move
detection by keypoint matching, which is unaffected by both feathering
and compression history. Full write-up in outputs/retired_checks.md.

--------------------------------------------------------------------------
LOCALISATION WAS TESTED AND DOES NOT WORK - weight stays 0.0
--------------------------------------------------------------------------
The obvious objection to the whole-frame statistics below is that they
average away the discontinuity they seek: a composited patch occupying a
median 4.4% of frame area moves a frame-wide modal share by at most 4.4%,
and sensor noise moves it by more. That objection was tested directly
(scripts/measure_digital_edit_localised.py,
outputs/digital_edit_localised.json).

Sliding-window region proposals at two sets of scales, with per-region
ghost, noise and edge statistics scored as robust deviation from the frame's
own median:

    windows 0.25/0.40 of the shorter side  ->  combined AUC 0.532
    windows 0.07/0.12/0.22 (patch-matched) ->  combined AUC 0.565
    whole-frame (this module, unchanged)   ->  combined AUC 0.546

The second attempt used scales bracketing the generator's recorded
patch_box sizes, because the first used windows larger than the patch itself
and so reproduced the averaging problem at a smaller scale.

**The AUC is not the informative number here.** The generator records the
exact pixel box of every composite, so the measurement also asked whether the
highest-scoring region *overlaps the actual patch*. It does not:

    top-scoring region overlaps patch_box (IoU > 0.1):  0 of 34  (0%)

Zero. At the coarser scale it was 2 of 34, which is chance. The localised
detector therefore does not find the composite, and the modest AUC lift it
does show comes almost entirely from the noise term (fitted weight 0.95)
while the ghost term is strongly **inverted** (AUC 0.29). Whatever the
combined score is separating, it is not the edit.

Per construction variant, combined AUC was 0.557 (single_save) and 0.573
(recompressed_patch). Even the variant carrying a genuine double-compression
discontinuity - a patch saved at quality 55 placed into a frame saved at 92 -
is barely above chance.

**What this does and does not establish.** It establishes that *these three
statistics*, computed either frame-wide or over sliding-window regions, do
not detect *these composites* on *this corpus* - where images have a median
width of 635px and have been through the corpus's own JPEG pipeline. It does
not establish that image forensics fails in general. Untested here and
plausibly better: error-level analysis against a known-quality reference,
CFA/demosaicing inconsistency (requires the original sensor mosaic, which
this corpus does not preserve), lighting and shadow-direction consistency, and
learned localisation models trained on composite datasets. The honest summary
is that three classical statistics were implemented, localised, and measured
to fail, not that the problem is unsolvable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

# Written by scripts/measure_digital_edit.py. Kept on disk rather than
# hard-coded so the threshold and the measurement that justifies it can
# never drift apart - if the file is missing the check falls back to the
# defaults below and says so in its evidence.
CALIBRATION_PATH = Path("outputs/digital_edit_calibration.json")

# Quality ladder for the ghost analysis. Coarse on purpose: the point is
# to find *disagreement* between regions, not to recover the exact
# original quality, and every extra rung costs a full re-encode of every
# image in the corpus.
GHOST_QUALITIES = (55, 65, 75, 85, 95)

# Grid for the noise analysis. 8x8 cells over a ~250px image is ~30px per
# cell - large enough for a stable variance estimate, small enough that a
# pasted bumper occupies more than one cell.
NOISE_GRID = 8

# Defaults, overridden by CALIBRATION_PATH when present.
_DEFAULT_CONCERN = 0.60
_DEFAULT_INCONCLUSIVE = 0.45

_calibration: Optional[dict[str, Any]] = None


def get_calibration() -> dict[str, Any]:
    """Load the measured thresholds, or fall back to defaults."""
    global _calibration
    if _calibration is None:
        try:
            with open(CALIBRATION_PATH, encoding="utf-8") as fh:
                _calibration = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _calibration = {
                "concern_threshold": _DEFAULT_CONCERN,
                "inconclusive_threshold": _DEFAULT_INCONCLUSIVE,
                "calibrated": False,
            }
    return _calibration


def _to_gray(bgr: "np.ndarray") -> "np.ndarray":
    import cv2

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)


def ghost_score(bgr: "np.ndarray") -> float:
    """
    Share of 8x8 blocks whose best-matching re-encode quality disagrees
    with the image's modal quality. 0 = perfectly coherent compression
    history, 1 = every block disagrees.
    """
    import cv2

    gray = _to_gray(bgr)
    h, w = gray.shape
    bh, bw = h // 8, w // 8
    if bh < 2 or bw < 2:
        return 0.0

    # Per-quality, per-block mean squared reconstruction error.
    errors = np.empty((len(GHOST_QUALITIES), bh, bw), dtype=np.float32)
    for qi, quality in enumerate(GHOST_QUALITIES):
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return 0.0
        recoded = _to_gray(cv2.imdecode(buf, cv2.IMREAD_COLOR))
        diff = (gray - recoded) ** 2
        trimmed = diff[: bh * 8, : bw * 8]
        # Mean over each 8x8 block, vectorised.
        errors[qi] = trimmed.reshape(bh, 8, bw, 8).mean(axis=(1, 3))

    best = errors.argmin(axis=0)
    counts = np.bincount(best.ravel(), minlength=len(GHOST_QUALITIES))
    modal_share = counts.max() / best.size
    return float(1.0 - modal_share)


def noise_score(bgr: "np.ndarray") -> float:
    """
    Disagreement between local noise levels, as a robust coefficient of
    variation (MAD / median) over grid cells. 0 = uniform sensor noise.
    """
    import cv2

    gray = _to_gray(bgr)
    # High-pass: what the median filter removes is texture and noise; the
    # residual's local spread is a usable noise proxy without needing a
    # calibrated sensor model.
    residual = gray - cv2.medianBlur(gray.astype(np.uint8), 3).astype(np.float32)

    h, w = residual.shape
    ch, cw = h // NOISE_GRID, w // NOISE_GRID
    if ch < 4 or cw < 4:
        return 0.0

    cells = residual[: ch * NOISE_GRID, : cw * NOISE_GRID]
    cells = cells.reshape(NOISE_GRID, ch, NOISE_GRID, cw)
    levels = cells.std(axis=(1, 3)).ravel()

    median = float(np.median(levels))
    if median <= 1e-6:
        return 0.0
    mad = float(np.median(np.abs(levels - median)))
    # Scale into roughly [0,1]; 0.5 relative MAD is already extreme for a
    # single-sensor photograph.
    return float(min(1.0, (mad / median) / 0.5))


def edge_score(bgr: "np.ndarray") -> float:
    """
    Share of strong-gradient pixels that are unnaturally sharp - a real
    lens spreads an edge over 2-3 pixels, a hard composite does not.
    """
    import cv2

    gray = _to_gray(bgr)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.sqrt(gx * gx + gy * gy)

    strong_cut = float(np.percentile(magnitude, 98))
    if strong_cut <= 1e-6:
        return 0.0
    strong = magnitude >= strong_cut
    if strong.sum() < 20:
        return 0.0

    # A blurred copy re-measures the same edges; a naturally soft edge
    # barely changes, a 1-pixel step collapses. The ratio is the
    # sharpness signature.
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.0)
    bx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    by = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    blurred_magnitude = np.sqrt(bx * bx + by * by)

    ratio = blurred_magnitude[strong] / (magnitude[strong] + 1e-6)
    # ratio near 1 => edge survives blurring => naturally soft.
    # ratio near 0 => edge vanishes => a hard, synthetic step.
    return float(np.mean(ratio < 0.35))


def analyse(path: str) -> Optional[dict[str, float]]:
    """
    Run all three signals on one image. Returns None if the file cannot
    be read - never raises, because one unreadable file must not end a
    1,300-image pass.
    """
    import cv2

    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None

    ghost = ghost_score(bgr)
    noise = noise_score(bgr)
    edge = edge_score(bgr)
    cal = get_calibration()
    weights = cal.get("signal_weights", {"ghost": 1 / 3, "noise": 1 / 3, "edge": 1 / 3})
    combined = ghost * weights["ghost"] + noise * weights["noise"] + edge * weights["edge"]

    return {
        "ghost": round(ghost, 4),
        "noise": round(noise, 4),
        "edge": round(edge, 4),
        "combined": round(float(combined), 4),
    }


class DigitalEditCheck(Check):
    check_id = "digital_edit"
    category = CheckCategory.PROVENANCE
    scope = "image"
    cost_inr = 0.0
    requires_perception = False
    target_archetypes = ("DIGITAL_EDIT",)
    # 0.0 - measured, not guessed. Combined AUC 0.531 against the 34
    # DIGITAL_EDIT images (a coin is 0.5), with two of three signals
    # inverted because the forgery recipe recompresses the whole frame
    # and thereby erases the artifacts being looked for. The check runs
    # for its measurement only. See the MEASURED RESULT section of the
    # module docstring before changing this, and re-run
    # scripts/measure_digital_edit.py rather than editing the number.
    weight = 0.0
    attributed_to = "image"
    limitation = (
        "AUC 0.546 whole-frame and 0.565 localised, with the top-scoring region overlapping the actual composite in 0 of 34 cases."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        cal = get_calibration()
        concern_at = ctx.config.get("digital_edit_concern", cal["concern_threshold"])
        inconclusive_at = ctx.config.get("digital_edit_inconclusive", cal["inconclusive_threshold"])
        return [self._check_one_image(ctx, image, concern_at, inconclusive_at) for image in ctx.images]

    def _check_one_image(
        self, ctx: CheckContext, image: Image, concern_at: float, inconclusive_at: float
    ) -> Finding:
        cal = get_calibration()

        def finding(verdict: Verdict, confidence: float, explanation: str, evidence: dict[str, Any]) -> Finding:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence={
                    "image_id": image.image_id,
                    "calibrated": cal.get("calibrated", False),
                    "concern_threshold": concern_at,
                    **evidence,
                },
            )

        try:
            scores = analyse(image.path)
        except Exception as e:  # noqa: BLE001 - never kill a batch run on one file
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "Digital-edit analysis could not run on this image.",
                {"error": f"{type(e).__name__}: {e}"},
            )

        if scores is None:
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "Digital-edit analysis could not read this image.",
                {"reason": "unreadable"},
            )

        # A check whose threshold has never been measured must not accuse
        # anyone. Without calibration it reports its numbers and abstains.
        if not cal.get("calibrated", False):
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "Digital-edit analysis ran but has not been calibrated against this corpus, "
                "so its score is recorded without a verdict.",
                {"signals": scores},
            )

        combined = scores["combined"]
        loudest = max(("ghost", "noise", "edge"), key=lambda k: scores[k])
        reason = {
            "ghost": "its compression history is not uniform across the frame",
            "noise": "sensor noise differs between regions of the frame",
            "edge": "some edges are sharper than a camera lens produces",
        }[loudest]

        if combined >= concern_at:
            confidence = min(0.75, 0.4 + (combined - concern_at) * 2.0)
            return finding(
                Verdict.CONCERN, confidence,
                f"Image forensics suggest this photograph may have been edited: {reason} "
                f"(score {combined:.2f} against a measured threshold of {concern_at:.2f}).",
                {"signals": scores, "dominant_signal": loudest},
            )

        if combined >= inconclusive_at:
            return finding(
                Verdict.INCONCLUSIVE, 0.25,
                f"Image forensics are mildly elevated (score {combined:.2f}) but below the level "
                "that distinguishes edited from ordinary claim photographs on this corpus.",
                {"signals": scores, "dominant_signal": loudest},
            )

        return finding(
            Verdict.PASS, min(0.7, 0.4 + (concern_at - combined)),
            f"Image forensics found no sign of splicing or recompression inconsistency "
            f"(score {combined:.2f}).",
            {"signals": scores},
        )


DIGITAL_EDIT_CHECK = register_check(DigitalEditCheck())
