"""
fraudlens.checks.metadata
===========================

Check 2 - EXIF provenance. Reads image.exif (populated once, at ingest
time, by src.ingest.extract_exif - see that function's docstring), never
re-derives it and never touches the file on disk itself.

The single most important thing this check gets right is what it does
NOT flag: absence of EXIF. Upload pipelines strip it routinely - a
WhatsApp forward, a browser re-encode, most phones' own "share" sheet -
so a photo with no EXIF at all is the overwhelmingly common case in this
corpus, not an unusual one. Scoring that CONCERN, or even INCONCLUSIVE,
would make this check fire on most legitimate submissions and destroy
the system's false-positive rate, which is its primary metric (see
models.py's module docstring). PASS, low confidence, is the only verdict
that's both honest ("I have no reason to doubt this photo") and safe
("I also have almost no signal either way").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..models import Case, CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

_EDIT_SIGNATURES = ("photoshop", "gimp", "snapseed", "lightroom")
_EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"


def _lerp_confidence(value: float, lo: float, hi: float, conf_at_lo: float, conf_at_hi: float) -> float:
    if hi == lo:
        return conf_at_hi
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return conf_at_lo + t * (conf_at_hi - conf_at_lo)


def _find_software_signature(exif: dict[str, Any], signatures: tuple[str, ...]) -> Optional[str]:
    """
    Scans every IFD's Software field, not just "0th" (where piexif
    conventionally puts it) - cheap, and this check has no other reason
    to assume any particular camera/tool always places it there.
    """
    for ifd in exif.values():
        if not isinstance(ifd, dict):
            continue
        software = ifd.get("Software")
        if isinstance(software, str):
            lowered = software.lower()
            for sig in signatures:
                if sig in lowered:
                    return software
    return None


def _ratio(pair: Any) -> float:
    try:
        num, denom = pair
        return float(num) / float(denom) if denom else 0.0
    except (TypeError, ValueError):
        return 0.0


def _dms_to_decimal(dms: Any, ref: Any) -> Optional[float]:
    try:
        degrees, minutes, seconds = dms
    except (TypeError, ValueError):
        return None
    value = _ratio(degrees) + _ratio(minutes) / 60.0 + _ratio(seconds) / 3600.0
    if isinstance(ref, str) and ref.upper() in ("S", "W"):
        value = -value
    return value


def _exif_gps(exif: dict[str, Any]) -> Optional[tuple[float, float]]:
    gps = exif.get("GPS")
    if not isinstance(gps, dict):
        return None
    lat = _dms_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    lon = _dms_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    if lat is None or lon is None:
        return None
    return lat, lon


def _exif_capture_time(exif: dict[str, Any]) -> Optional[datetime]:
    for ifd_name in ("Exif", "0th"):
        ifd = exif.get(ifd_name)
        if not isinstance(ifd, dict):
            continue
        for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            raw = ifd.get(key)
            if isinstance(raw, str):
                try:
                    return datetime.strptime(raw, _EXIF_TIME_FORMAT)
                except ValueError:
                    continue
    return None


class MetadataCheck(Check):
    """
    CONCERN only for editing-software signatures in the Software field or
    a GPS fix more than gps_concern_km from the declared incident
    location; INCONCLUSIVE only for an EXIF capture timestamp more than
    timestamp_inconclusive_hours away from the declared incident time.
    Both CONCERN paths are evaluated together and combined if both fire;
    the timestamp check only runs (and only matters) if neither CONCERN
    path already fired - a forged GPS fix is a more specific claim than
    "the clock looks off by a couple of days".
    """

    check_id = "exif_metadata"
    category = CheckCategory.PROVENANCE
    scope = "image"
    cost_inr = 0.0
    requires_perception = False
    target_archetypes = ("METADATA_FORGERY",)
    # 0.7 - 0/560 false positives, which is as clean as the top three, but
    # recall is 25/34 (73.5%) and the CONCERN itself is weaker evidence.
    # "Photoshop appears in the Software field" has innocent explanations
    # a duplicate image match does not: people legitimately crop, rotate
    # and brighten a photo before sending it. So a CONCERN here is a real
    # signal that should not on its own carry a case, and 0.7 keeps one
    # such finding below the 1.0 ESCALATE_SIU line while letting it
    # combine with anything else.
    weight = 0.7
    attributed_to = "image"

    GPS_CONCERN_KM = 100.0
    TIMESTAMP_INCONCLUSIVE_HOURS = 48.0
    NO_EXIF_CONFIDENCE = 0.3
    CLEAN_EXIF_CONFIDENCE = 0.6

    def run(self, ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        gps_concern_km = cfg.get("metadata_gps_concern_km", self.GPS_CONCERN_KM)
        timestamp_hours = cfg.get("metadata_timestamp_inconclusive_hours", self.TIMESTAMP_INCONCLUSIVE_HOURS)
        return [self._check_one_image(ctx.case, image, gps_concern_km, timestamp_hours) for image in ctx.images]

    def _check_one_image(self, case: Case, image: Image, gps_concern_km: float, timestamp_hours: float) -> Finding:
        exif = image.exif
        if not exif:
            return Finding(
                check_id=self.check_id,
                case_id=case.case_id,
                category=self.category,
                verdict=Verdict.PASS,
                confidence=self.NO_EXIF_CONFIDENCE,
                explanation=(
                    "This image has no EXIF metadata - common for uploads via WhatsApp, a browser, or a "
                    "phone's default sharing pipeline, not itself suspicious."
                ),
                evidence={"image_id": image.image_id, "exif_present": False},
            )

        reasons: list[str] = []
        evidence: dict[str, Any] = {"image_id": image.image_id, "exif_present": True}
        concern_confidences: list[float] = []

        software = _find_software_signature(exif, _EDIT_SIGNATURES)
        if software:
            reasons.append(f"EXIF Software field indicates editing with {software!r}.")
            evidence["software"] = software
            concern_confidences.append(0.85)

        gps = _exif_gps(exif)
        if gps is not None and case.latitude is not None and case.longitude is not None:
            from geopy.distance import geodesic

            distance_km = geodesic((gps[0], gps[1]), (case.latitude, case.longitude)).km
            evidence["exif_gps"] = {"lat": gps[0], "lon": gps[1]}
            evidence["declared_gps"] = {"lat": case.latitude, "lon": case.longitude}
            evidence["gps_distance_km"] = round(distance_km, 1)
            if distance_km > gps_concern_km:
                reasons.append(
                    f"EXIF GPS location is {distance_km:.0f}km from the declared incident location."
                )
                concern_confidences.append(_lerp_confidence(distance_km, gps_concern_km, gps_concern_km * 5, 0.6, 0.95))

        if reasons:
            return Finding(
                check_id=self.check_id,
                case_id=case.case_id,
                category=self.category,
                verdict=Verdict.CONCERN,
                confidence=max(concern_confidences),
                explanation=" ".join(reasons),
                evidence=evidence,
            )

        capture_time = _exif_capture_time(exif)
        if capture_time is not None and case.declared_time is not None:
            declared_naive = case.declared_time.replace(tzinfo=None)
            hours_apart = abs((capture_time - declared_naive).total_seconds()) / 3600.0
            evidence["exif_capture_time"] = capture_time.isoformat()
            evidence["declared_time"] = case.declared_time.isoformat()
            evidence["hours_apart"] = round(hours_apart, 1)
            if hours_apart > timestamp_hours:
                confidence = _lerp_confidence(hours_apart, timestamp_hours, timestamp_hours * 5, 0.4, 0.6)
                return Finding(
                    check_id=self.check_id,
                    case_id=case.case_id,
                    category=self.category,
                    verdict=Verdict.INCONCLUSIVE,
                    confidence=confidence,
                    explanation=(
                        f"EXIF capture timestamp differs from the declared incident time by {hours_apart:.0f} hours."
                    ),
                    evidence=evidence,
                )

        return Finding(
            check_id=self.check_id,
            case_id=case.case_id,
            category=self.category,
            verdict=Verdict.PASS,
            confidence=self.CLEAN_EXIF_CONFIDENCE,
            explanation="EXIF metadata is present and shows no editing signature, GPS mismatch, or timestamp discrepancy.",
            evidence=evidence,
        )


METADATA_CHECK = register_check(MetadataCheck())
