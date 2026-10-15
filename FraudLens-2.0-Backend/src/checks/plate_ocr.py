"""
fraudlens.checks.plate_ocr
============================

Check 7 - does the licence plate in the photo match the policy?

Reads text from the image with EasyOCR, filters for strings shaped like
an Indian registration (two letters, two digits, one-to-three letters,
four digits - e.g. GJ01AB1234), and compares the best candidate against
the case's own vehicle_registration.

--------------------------------------------------------------------
RESOLUTION LIMITATION - read before citing any number this check produces
--------------------------------------------------------------------
This will fail to find a plate on most of this corpus, and that is
expected, not a defect. The curated images are roughly 200-300px on
their short side (see MIN_SIDE_PX in src/generate_dataset.py, lowered to
150 precisely because this dataset's damage crops are natively that
small). A licence plate occupies a small fraction of a vehicle photo, so
at those dimensions the plate region is frequently a few dozen pixels
wide - below what any OCR engine can resolve into characters.

That makes "no plate-shaped text found" the common outcome, and it is
scored INCONCLUSIVE, never CONCERN. Treating an unreadable plate as
suspicious would fire on the majority of honest claims and destroy the
false-positive rate, which is this system's primary metric - the same
reasoning that makes missing EXIF a PASS in src/checks/metadata.py.

The useful output of running this check across the corpus is therefore
not its recall but its *resolution threshold*: the width at which plate
reading becomes viable at all. That is a reportable finding about
minimum capture requirements for a production system - "photograph the
plate close enough that it is at least N pixels wide" is actionable
guidance an insurer can put in a claims app. scripts/evaluate_checks.py
measures exactly that.

Category: IDENTITY. The question is "is this the insured vehicle?", and
OCR is merely how this particular check goes about answering it. The
taxonomy names questions, not techniques - see CheckCategory in
src/models.py.
"""

from __future__ import annotations

import re
import hashlib
import importlib.metadata
import math
from typing import Any, Optional

from .. import db
from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

# Canonical Indian registration: 2 letters, 2 digits, 1-3 letters, 4 digits.
PLATE_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$")

# Common OCR confusions, applied positionally: in a slot that must be a
# letter, a digit that looks like one is coerced to the letter, and vice
# versa. Doing this positionally rather than globally matters - blindly
# mapping every 0 to O would corrupt the four-digit tail.
_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
_TO_DIGIT = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2", "G": "6", "Q": "0", "D": "0"}

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")

# Module-level, lazily built: EasyOCR loads detection and recognition
# models that cost real seconds to initialise, so a batch run over 1,300
# images pays that once. Same pattern as ingest.CLIPEmbedder and
# src/checks/ai_detection.py's pipeline.
_reader: Any = None
_reader_error: Optional[str] = None
_reader_attempted = False
import threading
_reader_lock = threading.Lock()


def get_reader() -> Any:
    """Returns the EasyOCR reader, or None if it could not be loaded."""
    global _reader, _reader_error, _reader_attempted
    with _reader_lock:
        if not _reader_attempted:
            _reader_attempted = True
            try:
                import os
                import torch
                import easyocr
                from ..timing import span

                # A dedicated worker does not load CLIP first. Bound its CPU
                # threads too; changing scheduling does not change OCR inputs.
                torch.set_num_threads(max(1, min(8, int(os.getenv('FRAUDLENS_TORCH_THREADS', '2')))))
                with span('ocr.initialize'):
                    _reader = easyocr.Reader(["en"], gpu=False,
                        download_enabled=os.getenv('HF_HUB_OFFLINE') != '1')
            except Exception as e:  # noqa: BLE001 - explicit unavailable finding
                _reader_error = f"{type(e).__name__}: {e}"
    return _reader


def normalise(text: str) -> str:
    """Uppercase, strip everything that isn't a letter or digit."""
    return _NON_ALNUM.sub("", text or "").upper()


PRODUCTION_COMPARISON_VERSION = 'plate-ocr-observed-prefix-v2'


def coerce_to_plate(text: str, *, observed_prefix: bool = False) -> Optional[str]:
    """
    Try to read `text` as an Indian registration, repairing the common
    OCR confusions positionally. Returns the canonical plate string, or
    None if the text cannot be shaped into one.

    Length determines the split: the format is fixed at 2 + 2 + N + 4
    with N in 1..3, so a 9-11 character string has exactly one possible
    segmentation (N = len - 8) and there is nothing to guess at.
    """
    cleaned = normalise(text)
    if not 9 <= len(cleaned) <= 11:
        return None
    # Production correction: digits in an advert's telephone number cannot
    # establish the two-letter registration prefix. Preserve the historical
    # research interpretation unless explicitly selected by the run policy.
    if observed_prefix and not cleaned[:2].isalpha():
        return None

    middle_len = len(cleaned) - 8
    segments = [
        (cleaned[0:2], "alpha"),
        (cleaned[2:4], "digit"),
        (cleaned[4 : 4 + middle_len], "alpha"),
        (cleaned[4 + middle_len :], "digit"),
    ]

    rebuilt = []
    for segment, kind in segments:
        table = _TO_LETTER if kind == "alpha" else _TO_DIGIT
        rebuilt.append("".join(table.get(ch, ch) for ch in segment))

    candidate = "".join(rebuilt)
    return candidate if PLATE_RE.match(candidate) else None


def edit_distance(a: str, b: str) -> int:
    """Plain Levenshtein - short strings, no need for a dependency."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


class PlateOCRCheck(Check):
    check_id = "plate_ocr"
    category = CheckCategory.IDENTITY
    scope = "image"
    cost_inr = 0.0
    requires_perception = False
    # No archetype in this corpus is built around a mismatched plate -
    # this is an identity check, not an archetype detector. Recall is
    # reported as n/a; see Check.target_archetypes in base.py.
    target_archetypes = ()
    # 0.3 - the mechanism is sound but barely fires, and on this corpus it
    # cannot be right when it does. Only 3/1,361 images (0.2%) yielded
    # plate-shaped text at all, and all 3 mismatched because
    # generate_dataset assigns each case a random_registration() unrelated
    # to the real plate in the stock photo. So its 3 CONCERNs measure the
    # dataset, not the check. A genuine plate mismatch would be strong
    # evidence, which is why this is not 0.0 - but until the check is
    # measured on data where a match is possible, it has not earned the
    # right to move a case on its own, and 0.3 keeps a lone CONCERN below
    # the REQUEST_EVIDENCE line.
    weight = 0.3
    attributed_to = "vehicle"
    limitation = (
        "Registration plates are legible in 3 of 1361 images (0.22%) on this corpus, so its INCONCLUSIVE carries no information."
    )

    # EasyOCR confidences on small, blurry text run low, so this is not a
    # "the model is sure" bar so much as "this was not pure noise".
    # Below it, a mismatch is INCONCLUSIVE rather than CONCERN.
    OCR_CONFIDENCE_CONCERN = 0.50

    def run(self, ctx: CheckContext) -> list[Finding]:
        threshold = ctx.config.get("plate_ocr_confidence_concern", self.OCR_CONFIDENCE_CONCERN)
        reader = get_reader()
        return [self._check_one_image(ctx, image, reader, threshold) for image in ctx.images]

    def _check_one_image(self, ctx: CheckContext, image: Image, reader: Any, threshold: float) -> Finding:
        policy_registration = ctx.case.vehicle_registration
        cache_reused = False
        cache_key = None

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
                    **({'comparison_version':PRODUCTION_COMPARISON_VERSION} if ctx.config.get('plate_ocr_observed_prefix') else {}),
                    "policy_registration": policy_registration,
                    "policy_registration_normalised": normalise(policy_registration or ""),
                    **({'ocr_cache_key':cache_key,'ocr_cache_reused':cache_reused} if cache_key else {}),
                    **evidence,
                },
            )

        if reader is None:
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "Licence plate reading unavailable - the OCR engine could not be loaded.",
                {"reason": _reader_error or "easyocr unavailable", "ocr_status": "engine_unavailable"},
            )

        try:
            if ctx.config.get('cache_ocr'):
                engine='easyocr-'+importlib.metadata.version('easyocr')+'-en-cpu-readtext-default-v1'
                cache_key=hashlib.sha256((engine+':'+image.content_hash).encode()).hexdigest()
                cached=db.cache_get(ctx.conn,'production_plate_ocr',cache_key)
            else:
                cached=None
            if cached is not None:
                raw_results=cached['observations'];cache_reused=True
            else:
                from ..timing import span
                with span('ocr.readtext'):
                    raw_results=reader.readtext(image.path)
                if cache_key:
                    observations=[]
                    for box,text,confidence in raw_results:
                        confidence=float(confidence)
                        if not math.isfinite(confidence) or not 0<=confidence<=1:
                            raise ValueError('Invalid OCR confidence')
                        # Only text/confidence participates in this check. Never
                        # cache a case verdict, policy registration or identity.
                        observations.append([None,str(text),confidence])
                    db.cache_set(ctx.conn,'production_plate_ocr',cache_key,
                                 {'engine':engine,'observations':observations})
                    # Optional cache data precedes the atomic final run result.
                    # Release its writer lock before the next slow OCR call.
                    ctx.conn.commit()
                    raw_results=observations
        except Exception as e:  # noqa: BLE001 - unreadable file; never kill the run
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "Licence plate reading could not run on this image.",
                {"error": f"{type(e).__name__}: {e}", "ocr_status": "execution_failed"},
            )

        raw_strings = []
        candidates: list[tuple[str, float, str]] = []  # (plate, confidence, source text)
        for entry in raw_results:
            # EasyOCR returns (bbox, text, confidence).
            try:
                _, text, ocr_confidence = entry
            except (ValueError, TypeError):
                continue
            raw_strings.append({"text": text, "confidence": round(float(ocr_confidence), 4)})
            plate = coerce_to_plate(text, observed_prefix=bool(ctx.config.get('plate_ocr_observed_prefix')))
            if plate is not None:
                candidates.append((plate, float(ocr_confidence), text))

        if not candidates:
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                ("OCR detected text but no licence-plate-shaped candidate could be read. "
                 if raw_strings else "OCR ran but detected no text. ")
                + "Plate legibility is unverified; this is not itself suspicious.",
                {"raw_ocr_strings": raw_strings, "plate_candidate": None,
                 "ocr_status": "no_plate_candidate" if raw_strings else "no_text_detected",
                 "legibility": "unverified; no readable plate established"},
            )

        plate, ocr_confidence, source_text = max(candidates, key=lambda c: c[1])
        policy_normalised = normalise(policy_registration or "")
        distance = edit_distance(plate, policy_normalised) if policy_normalised else None

        evidence = {
            "ocr_status": "candidate_read",
            "raw_ocr_strings": raw_strings,
            "plate_candidate": plate,
            "plate_candidate_source_text": source_text,
            "ocr_confidence": round(ocr_confidence, 4),
            "edit_distance": distance,
        }

        if not policy_normalised:
            evidence['comparison_status'] = 'declaration_missing'
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                f"Read plate {plate} but this case has no policy registration to compare against.",
                evidence,
            )

        if plate == policy_normalised:
            evidence['comparison_status'] = 'match'
            return finding(
                Verdict.PASS,
                min(0.9, 0.5 + ocr_confidence / 2),
                f"The licence plate read from this image ({plate}) matches the policy registration.",
                evidence,
            )

        if ocr_confidence >= threshold:
            evidence['comparison_status'] = 'mismatch'
            return finding(
                Verdict.CONCERN,
                min(0.85, 0.4 + ocr_confidence / 2),
                f"The licence plate read from this image ({plate}) does not match the policy registration "
                f"({policy_normalised}).",
                evidence,
            )

        evidence['comparison_status'] = 'low_confidence_mismatch'
        return finding(
            Verdict.INCONCLUSIVE,
            0.2,
            f"A possible licence plate ({plate}) differs from the policy registration ({policy_normalised}), "
            f"but OCR confidence was too low ({ocr_confidence:.2f}) to rely on.",
            evidence,
        )


PLATE_OCR_CHECK = register_check(PlateOCRCheck())
