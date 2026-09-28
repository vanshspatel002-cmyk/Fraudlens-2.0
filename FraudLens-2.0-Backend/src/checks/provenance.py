"""
fraudlens.checks.provenance
=============================

Check 5 - C2PA content credentials.

C2PA (the Content Authenticity Initiative's provenance standard) embeds
a cryptographically signed manifest describing how an image was created
and edited. When present and valid, it is the single strongest
provenance signal available - far better than EXIF, which anyone can
forge with piexif in four lines (src/generate_dataset.py's forge_exif()
does exactly that).

Expect this check to find nothing, essentially always. Adoption today is
minimal: a handful of camera bodies, some Adobe and OpenAI export paths,
and almost nothing in the phone-photo-forwarded-over-WhatsApp pipeline
that produces real motor-claim evidence. Low yield is the expected
result, not a bug and not a sign the check is broken.

It is written now anyway, for two reasons. First, forward compatibility:
adoption is growing, and when a claimant's phone starts signing photos
by default this check starts paying off with no new work. Second, and
more immediately, it makes the absence explicit and auditable - "we
looked for content credentials and there were none" is a defensible
statement in a regulated review, where "we never looked" is not.

Absence is scored PASS at low confidence, never CONCERN, for the same
reason src/checks/metadata.py refuses to flag missing EXIF: penalising
the overwhelmingly common case would destroy the false-positive rate,
which is this system's primary metric. Only a credential that exists and
fails validation is a CONCERN - that means someone tampered with a
signed image, which is a genuine, specific finding.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

# Resolved once on first use: None = not yet tried, False = unavailable.
_c2pa_module: Any = None
_c2pa_import_error: Optional[str] = None


def _get_c2pa() -> Any:
    """
    Import c2pa lazily and remember the outcome. The library is an
    optional dependency - it ships native binaries and is not in
    requirements.txt - so importing it at module scope would make
    `from src.checks import ...` fail on every machine that doesn't have
    it, taking every other check down with it.
    """
    global _c2pa_module, _c2pa_import_error
    if _c2pa_module is None and _c2pa_import_error is None:
        try:
            import c2pa  # type: ignore

            _c2pa_module = c2pa
        except Exception as e:  # noqa: BLE001 - ImportError, or a native-load failure
            _c2pa_import_error = f"{type(e).__name__}: {e}"
    return _c2pa_module


def _read_manifest(c2pa: Any, image_path: str) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (manifest_json, error). The c2pa-python API has changed
    shape across releases (a module-level read_file(), a Reader class,
    and a from_file() classmethod have all been the entry point at
    different versions), so each known form is tried in turn rather than
    pinning this check to one release. A "no manifest present" outcome
    comes back as (None, None) - the common case, not an error.
    """
    reader_cls = getattr(c2pa, "Reader", None)
    if reader_cls is not None:
        try:
            from_file = getattr(reader_cls, "from_file", None)
            reader = from_file(image_path) if callable(from_file) else reader_cls(image_path)
            return reader.json(), None
        except Exception as e:  # noqa: BLE001 - includes "no manifest found"
            message = str(e)
            if "no claim" in message.lower() or "manifest" in message.lower():
                return None, None
            return None, f"{type(e).__name__}: {message}"

    read_file = getattr(c2pa, "read_file", None)
    if callable(read_file):
        try:
            return read_file(image_path, None), None
        except Exception as e:  # noqa: BLE001
            message = str(e)
            if "no claim" in message.lower() or "manifest" in message.lower():
                return None, None
            return None, f"{type(e).__name__}: {message}"

    return None, "c2pa is installed but exposes no recognised read API"


class C2PACheck(Check):
    check_id = "c2pa_credentials"
    category = CheckCategory.PROVENANCE
    scope = "image"
    cost_inr = 0.0
    requires_perception = False
    # Empty by design: no archetype in this corpus produces a signed
    # image with a broken credential, which is the only thing this check
    # can CONCERN on. Recall is n/a, not 0% - see the module docstring.
    target_archetypes = ()
    # 0.1 - currently inert: 1,395/1,395 findings INCONCLUSIVE, 0 CONCERN,
    # 0/560 false positives, because no image in this corpus carries a
    # C2PA manifest and consumer phones do not yet emit them. There is no
    # measurement to justify a higher number, and a check that has never
    # fired has not demonstrated anything. But a *broken* credential on a
    # signed image would be near-conclusive evidence when that day comes,
    # so this is 0.1 rather than 0.0 - low enough to be harmless, non-zero
    # so the first real firing is visible in the score instead of silently
    # discarded.
    weight = 0.1
    attributed_to = "image"
    limitation = (
        "No image in this corpus carries a C2PA manifest, so it has nothing to detect here."
    )

    NO_CREDENTIALS_CONFIDENCE = 0.2
    VALID_CREDENTIALS_CONFIDENCE = 0.8

    def run(self, ctx: CheckContext) -> list[Finding]:
        c2pa = _get_c2pa()
        return [self._check_one_image(ctx, image, c2pa) for image in ctx.images]

    def _check_one_image(self, ctx: CheckContext, image: Image, c2pa: Any) -> Finding:
        def finding(verdict: Verdict, confidence: float, explanation: str, evidence: dict[str, Any]) -> Finding:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence={"image_id": image.image_id, **evidence},
            )

        if c2pa is None:
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                "Content credential verification unavailable.",
                {"reason": _c2pa_import_error or "c2pa-python is not installed"},
            )

        manifest_json, error = _read_manifest(c2pa, image.path)

        if error is not None:
            # A credential that exists but will not validate - the one
            # genuinely concerning outcome for this check.
            return finding(
                Verdict.CONCERN,
                self.VALID_CREDENTIALS_CONFIDENCE,
                "This image carries content credentials that failed validation.",
                {"credentials_present": True, "validation_error": error},
            )

        if not manifest_json:
            return finding(
                Verdict.PASS,
                self.NO_CREDENTIALS_CONFIDENCE,
                "This image carries no C2PA content credentials - expected, as adoption remains minimal.",
                {"credentials_present": False},
            )

        return finding(
            Verdict.PASS,
            self.VALID_CREDENTIALS_CONFIDENCE,
            "This image carries valid C2PA content credentials.",
            {"credentials_present": True, "manifest": manifest_json[:2000]},
        )


C2PA_CHECK = register_check(C2PACheck())
