"""
fraudlens.checks.base
=======================

The check framework every concrete check (src/checks/duplicate.py,
metadata.py, threshold.py, and whatever comes after them) plugs into.
Nothing outside this package builds a Finding by hand from a check - it
calls run_checks(conn, case), which is the single place that loads a
case's images and perception records, wraps every check in a try/except,
and applies the two universal skip rules (no images / no perception yet)
so an individual Check subclass only has to write its own detection
logic, never its own error handling or "do I even have the data I need"
boilerplate.

Package layout note: this module defines Check, CheckContext, the
REGISTRY dict, and register_check() (the decorator-like function concrete
checks call at import time to add themselves to REGISTRY) - but NOT
ALL_CHECKS. ALL_CHECKS has to be built after every concrete check module
has actually been imported and has registered itself, which base.py
itself can't do without importing its own subclasses (duplicate.py,
metadata.py, threshold.py all `from .base import Check, ...`, so the
reverse import would be circular). src/checks/__init__.py is what imports
every concrete module and then sets ALL_CHECKS = list(REGISTRY) - the
standard place for that in a plugin-registry package. Import
`from src.checks import ALL_CHECKS` (or REGISTRY, or run_checks), not
`from src.checks.base import ALL_CHECKS` - it isn't defined here.
"""

from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from .. import db
from ..models import Case, CheckCategory, Finding, Image, PerceptionRecord, Verdict

# ---------------------------------------------------------------------------
# Context every check runs against
# ---------------------------------------------------------------------------


@dataclass
class CheckContext:
    """
    Everything a Check's run() needs, pre-loaded by run_checks() so no
    individual check has to know how to query the database for its own
    inputs. `perception` is keyed by content_hash (sha256), matching
    PerceptionRecord's own key (see models.py) - not by image_id - so a
    check looks a perception record up as
    ctx.perception.get(image.content_hash), same lookup shape as
    db.get_perception(). It may be empty (perception hasn't run yet, or
    this image's photo genuinely has none) or only partially cover
    ctx.images; run_checks() enforces the requires_perception contract
    around that, individual checks don't have to.
    """

    conn: sqlite3.Connection
    case: Case
    images: list[Image]
    perception: dict[str, PerceptionRecord]
    config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The Check interface
# ---------------------------------------------------------------------------


class Check(ABC):
    """
    Abstract base for every check. A subclass sets the class attributes
    below and implements run() - everything else (loading data, catching
    crashes, the two universal skip rules) is run_checks()'s job, not
    the check's.

    scope is "image" (run_checks emits one INCONCLUSIVE per image when
    there are zero images, rather than one for the whole case - see
    _run_one) or "case" (the check reasons over the case as a whole, e.g.
    ThresholdGamingCheck's claim amount). cost_inr is the marginal INR
    cost of one run() call - 0.0 for a check that only reads data already
    in the database (every check in this file, today); nonzero for a
    future check that calls a paid API per case/image, so a cost-per-case
    evaluation metric can sum it without re-deriving it from call counts.

    target_archetypes names the fraud archetypes this check is actually
    designed to catch, and exists so the evaluation harness
    (scripts/evaluate_checks.py) can score each check against its own
    job. It lives here, on the check, rather than in a lookup table in
    the harness: the check's author is the one who knows what it was
    built to detect, and a table maintained elsewhere silently goes stale
    the moment a check is added or its scope changes.

    Firings outside this set are real detections and are reported - as
    "incidental detections" - but they must never be averaged into the
    check's recall. Doing so produces a number that means nothing: it
    blends the check's designed job with jobs it was never meant to do,
    so a check that is perfect at its own task looks mediocre purely
    because the corpus contains archetypes it makes no claim about.
    InternalDuplicateCheck measured 100% on REUSE and 8.6% on
    EXTERNAL_SOURCING (an externally-sourced photo is by definition not
    in the internal corpus); the pooled 54.29% describes nothing that
    exists. Pooled figures are meaningful only at the whole-system level,
    once the agent has combined findings from every check into one
    decision - that is the level at which "did we catch this case" is a
    coherent question.

    An empty target_archetypes means no archetype in the corpus targets
    this check (C2PACheck, which expects to find nothing - see its
    docstring). Recall is then reported as n/a, never as 0%.

    weight is how much a CONCERN from this check is allowed to move the
    rules-only score in src/baseline.py, and it is set from *measured*
    performance on this corpus rather than from how important the check
    sounds. A check with a high false-positive rate earns a low weight no
    matter how clever its mechanism, and a check whose measurement says it
    carries no usable signal earns 0.0 - which lets it keep running and
    keep recording evidence without being able to influence a decision.
    Each concrete check states the measurement behind its own number in a
    comment; the values are collected in outputs/check_performance_summary.md.

    Weight is deliberately separate from Finding.confidence. Confidence is
    the check's own statement about *this* image ("the OCR was crisp");
    weight is the system's statement about *the check* ("this check's
    CONCERNs have been right before"). The baseline multiplies them, so a
    confident finding from an unreliable check still scores low.

    attributed_to names WHOSE conduct a CONCERN from this check describes,
    and it is the check's own statement rather than something a consumer
    infers. This exists because getting it wrong is not a cosmetic error:
    threshold_gaming raises 91 of the corpus's clean-case concerns and every
    one of them was measured to be about the repairing garage's billing
    pattern, not the claimant's conduct
    (outputs/threshold_fp_investigation.json). An interface rendering that
    finding beside a claimant's name accuses the wrong party, and no amount
    of careful wording downstream fixes a field that says "claimant".

    One of "claimant", "garage", "vehicle", "image".

    limitation is a single sentence saying why this check is not currently
    contributing, for checks that are demoted, retired, or untestable on
    this corpus. Empty for a check that is working. It lives here for the
    same reason target_archetypes does: the check's author knows why it is
    not firing, and a table maintained elsewhere goes stale.
    """

    check_id: str
    category: CheckCategory
    scope: str  # "image" or "case"
    cost_inr: float = 0.0
    requires_perception: bool = False
    target_archetypes: tuple[str, ...] = ()
    weight: float = 1.0
    attributed_to: str = "claimant"
    limitation: str = ""
    agent_types: tuple[str, ...] = ('claims', 'underwriting')

    @abstractmethod
    def run(self, ctx: CheckContext) -> list[Finding]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Registry - concrete check modules call register_check() at import time
# ---------------------------------------------------------------------------

REGISTRY: dict[str, Check] = {}


def register_check(check: Check) -> Check:
    """
    Adds `check` to REGISTRY under its own check_id and returns it
    unchanged, so a concrete module can write
    `MY_CHECK = register_check(MyCheck())` as a plain module-level
    statement - no decorator gymnastics, no separate registration step
    for someone to forget.
    """
    if check.check_id in REGISTRY:
        raise ValueError(f"check_id {check.check_id!r} is already registered")
    REGISTRY[check.check_id] = check
    return check


# ---------------------------------------------------------------------------
# Running checks
# ---------------------------------------------------------------------------


def _inconclusive(check: Check, case_id: str, explanation: str, evidence: Optional[dict[str, Any]] = None) -> Finding:
    """
    The one shape every framework-generated (as opposed to check-authored)
    Finding takes: confidence 0.0, because a skip or a crash carries no
    actual signal about the case - it's the framework saying "this check
    didn't get to render a verdict," not the check saying "I looked and
    I'm not sure."
    """
    return Finding(
        check_id=check.check_id,
        case_id=case_id,
        category=check.category,
        verdict=Verdict.INCONCLUSIVE,
        confidence=0.0,
        explanation=explanation,
        evidence=evidence or {},
    )


def _run_one(check: Check, ctx: CheckContext) -> list[Finding]:
    """
    Applies, in order: the zero-images rule, the requires_perception
    rule, then the check itself inside a try/except. A crash - anything
    from a check's own bug to a transient DB error - becomes one
    INCONCLUSIVE finding with the error captured in evidence rather than
    aborting the rest of the pipeline; the whole point of routing every
    check through this function instead of calling check.run() directly
    is that one broken check must never take down every other check for
    a case, let alone the batch run across every case.
    """
    if ctx.case.agent_type not in check.agent_types:
        if not ctx.config.get('execution_states'):
            return []
        return [_inconclusive(check, ctx.case.case_id, 'This check does not apply to this application type.',
                             {'execution_state': 'not_applicable', 'applicable_case_types': list(check.agent_types)})]
    if check.scope == "image" and not ctx.images:
        return [_inconclusive(check, ctx.case.case_id, "No images available for this case.",
            {'execution_state':'not_run','missing_requirements':['images']} if ctx.config.get('execution_states') else None)]
    if check.check_id=='ai_generation' and ctx.config.get('skip_experimental_models'):
        return [_inconclusive(check,ctx.case.case_id,
            'Experimental zero-weight model not run in normal operation; it cannot contribute to routing.',
            {'execution_state':'not_run','reason':'zero_weight_experiment_disabled','weight':check.weight,
             'image_ids':[image.image_id for image in ctx.images]})]

    run_ctx = ctx
    prefix_findings: list[Finding] = []

    if check.requires_perception:
        if check.scope == "image":
            # Per-image, not per-check: an image whose perception record
            # exists still gets checked even if a sibling image in the
            # same case doesn't - "the relevant image" in the spec means
            # exactly that granularity, not an all-or-nothing skip.
            covered = [img for img in ctx.images if img.content_hash in ctx.perception]
            missing = [img for img in ctx.images if img.content_hash not in ctx.perception]
            prefix_findings = [
                _inconclusive(
                    check, ctx.case.case_id, "Perception data not yet available.", evidence={"image_id": img.image_id,
                        **({'execution_state':'not_run','missing_requirements':['perception']} if ctx.config.get('execution_states') else {})}
                )
                for img in missing
            ]
            if not covered:
                return prefix_findings
            run_ctx = replace(ctx, images=covered)
        else:
            # Case-scoped: there's no single "relevant image" to check
            # perception for, so the rule collapses to "has perception
            # run for this case at all" - a case-scoped check that needs
            # more granular perception coverage than that can still
            # inspect ctx.perception itself inside run().
            if not ctx.perception:
                return [_inconclusive(check, ctx.case.case_id, "Perception data not yet available.",
                    {'execution_state':'not_run','missing_requirements':['perception']} if ctx.config.get('execution_states') else None)]

    try:
        return prefix_findings + list(check.run(run_ctx))
    except Exception as e:  # noqa: BLE001 - one check's bug must never kill the run
        from ..analysis_diagnostics import failure_detail
        return prefix_findings + [
            _inconclusive(
                check,
                ctx.case.case_id,
                "This check could not complete due to an internal error.",
                evidence={"error_type": type(e).__name__, 'execution_state': 'failed',
                          'diagnostic': failure_detail(e, 'check:' + check.check_id)},
            )
        ]


def run_checks(conn: sqlite3.Connection, case: Case, check_ids: Optional[list[str]] = None,
               config: Optional[dict[str, Any]] = None, on_check=None) -> list[Finding]:
    """
    Load this case's images and whatever perception records already
    exist for them, build one CheckContext, and run every check in
    `check_ids` (default: every registered check, in registration order)
    against it. Each check is independent - one crashing or skipping
    never affects another - see _run_one.
    """
    images = db.get_images_for_case(conn, case.case_id)

    perception: dict[str, PerceptionRecord] = {}
    from ..perception import perception_record_usable
    for image in images:
        if image.content_hash in perception:
            continue
        record = db.get_perception(conn, image.content_hash)
        if perception_record_usable(record):
            perception[image.content_hash] = record

    ctx = CheckContext(conn=conn, case=case, images=images, perception=perception, config=config or {})

    ids = list(dict.fromkeys(check_ids if check_ids is not None else list(REGISTRY.keys())))
    for check_id in ids:
        if check_id not in REGISTRY:
            raise KeyError(f"unknown check_id {check_id!r} - registered checks: {sorted(REGISTRY)}")
    findings: list[Finding] = []
    from ..timing import span
    for index, check_id in enumerate(ids):
        if on_check:
            on_check(check_id, index, len(ids))
        with span('check.' + check_id):
            started = time.monotonic()
            results = _run_one(REGISTRY[check_id], ctx)
            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            if not results and ctx.config.get('execution_states'):
                results = [_inconclusive(REGISTRY[check_id], case.case_id,
                    'No comparison result was produced because the required case inputs or context were unavailable.',
                    {'execution_state': 'not_run', 'reason': 'required_inputs_unavailable'})]
            for result in results:
                result.evidence.setdefault('execution_state', 'inconclusive' if result.verdict is Verdict.INCONCLUSIVE else 'completed')
                result.evidence.setdefault('execution_ms', elapsed_ms)
            findings.extend(results)
    return findings
