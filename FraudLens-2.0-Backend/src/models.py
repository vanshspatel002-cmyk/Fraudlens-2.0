"""
fraudlens.models
=================

Core data model for FraudLens. Every check produces a Finding and nothing
else; the agent and the UI never touch raw check internals.

Design decisions:

- Verdict has three values, not two (PASS / INCONCLUSIVE / CONCERN),
  because most checks genuinely cannot conclude most of the time - EXIF
  is stripped, no C2PA manifest is present, shadows aren't visible.
  Forcing that into PASS/FAIL is exactly how false-positive rates get
  destroyed, and false-positive rate is the system's primary metric.

- Recommendation has no REJECT value. Not a runtime check that could be
  bypassed - the option simply does not exist in the type. It is
  structurally impossible for this codebase to auto-deny a claim.

- PerceptionRecord is keyed by image content hash (sha256 of the file
  bytes), not by image id or case id. The same photo submitted to
  twenty cases costs exactly one vision-model API call, forever.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _new_id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_nonblank(value: Optional[str], field_name: str) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_unit_interval(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be a number, got {type(value).__name__}")
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{field_name} must be in [0, 1], got {value!r}")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CheckCategory(str, Enum):
    """
    Which *question* a check asks - not which technique it uses.

    That distinction is the whole point of the taxonomy and it is easy to
    get wrong. An earlier revision of this enum carried VISUAL and
    DOCUMENT members, which named mechanisms (CLIP similarity, OCR)
    rather than questions, and checks were duly filed by how they worked
    instead of by what they established. A plate reader and a vehicle
    comparator both answer "is this the insured vehicle?" however
    differently they arrive at it, and they belong together under
    IDENTITY; splitting them by technique buried that.

    These five match the PRD, the SRS and the presentation. Adding a
    member here means the system has learned to ask a genuinely new
    question, which should be rare and deliberate.
    """

    IDENTITY = "identity"        # is this the insured vehicle? - plate, vehicle match
    HISTORY = "history"          # has this evidence been seen before? - phash / embedding reuse
    PROVENANCE = "provenance"    # where did this file come from? - EXIF / C2PA / generation
    CONTEXT = "context"          # does the story hold together? - weather, solar geometry, location
    ECONOMIC = "economic"        # do the numbers behave? - threshold gaming, round-number clustering


class Verdict(str, Enum):
    """
    Deliberately three-valued. See module docstring: forcing an
    inconclusive check into PASS/FAIL is how false-positive rates get
    destroyed.
    """

    PASS = "pass"
    INCONCLUSIVE = "inconclusive"
    CONCERN = "concern"


class Recommendation(str, Enum):
    """
    No REJECT value exists, by construction. This is the enforcement
    mechanism for the human-in-the-loop safeguard: it lives in the type
    system, not in a business-logic branch someone could delete.
    """

    APPROVE = "approve"
    REQUEST_EVIDENCE = "request_evidence"
    ESCALATE = "escalate"


class AdminAction(str, Enum):
    """
    Human admin decisions are deliberately separate from agent recommendations.

    The agent still cannot reject by type. A human admin can, and the API stores
    that decision in an audit table instead of overloading Recommendation.
    """

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class RiskBand(str, Enum):
    """
    Where a case lands on the risk scale, and therefore which queue it is
    routed to. Finer-grained than Recommendation on purpose.

    Recommendation answers "what do we do about the claimant?" and has
    three values because there are only three things one can do without
    a human: approve, ask for more, or hand it to a person. RiskBand
    answers "how alarming is this?" and separates the two very different
    populations that both come out as ESCALATE - a case a desk handler
    should look at, and a case that belongs with the Special
    Investigation Unit. Collapsing those would make the ablation's
    confusion matrix unreadable, since the interesting question is
    precisely whether a system sends borderline cases to the cheap queue
    or the expensive one.

    Mapping to Recommendation is total and deliberately many-to-one:

        CLEAR            -> APPROVE
        REQUEST_EVIDENCE -> REQUEST_EVIDENCE
        DESK_REVIEW      -> ESCALATE
        ESCALATE_SIU     -> ESCALATE

    Note what is still absent at both levels: there is no band that
    denies a claim. The escalation ceiling is "a human looks at it".
    """

    CLEAR = "clear"
    REQUEST_EVIDENCE = "request_evidence"
    DESK_REVIEW = "desk_review"
    ESCALATE_SIU = "escalate_siu"

    def to_recommendation(self) -> "Recommendation":
        return {
            RiskBand.CLEAR: Recommendation.APPROVE,
            RiskBand.REQUEST_EVIDENCE: Recommendation.REQUEST_EVIDENCE,
            RiskBand.DESK_REVIEW: Recommendation.ESCALATE,
            RiskBand.ESCALATE_SIU: Recommendation.ESCALATE,
        }[self]


# ---------------------------------------------------------------------------
# Finding - the spine
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """
    The one and only output type every check may produce.

    `evidence` is structured data for machines; `explanation` is one
    plain sentence for a human. Both are mandatory - an unexplainable
    finding is useless in a regulated context.
    """

    check_id: str
    case_id: str
    category: CheckCategory
    verdict: Verdict
    confidence: float
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    finding_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.check_id, "check_id")
        _require_nonblank(self.case_id, "case_id")
        if not isinstance(self.category, CheckCategory):
            raise TypeError(f"category must be a CheckCategory, got {type(self.category).__name__}")
        if not isinstance(self.verdict, Verdict):
            raise TypeError(f"verdict must be a Verdict, got {type(self.verdict).__name__}")
        _require_unit_interval(self.confidence, "confidence")
        _require_nonblank(self.explanation, "explanation")
        if not isinstance(self.evidence, dict):
            raise TypeError(f"evidence must be a dict, got {type(self.evidence).__name__}")

    def for_agent(self) -> dict[str, Any]:
        """
        The view of this finding an LLM should reason over.

        Deliberately narrower than to_dict(). Three things are withheld
        and each omission is a decision:

        - `evidence` is dropped. It carries raw OCR strings, per-class
          model scores and full weather payloads - hundreds of tokens of
          material the agent cannot verify and would be invited to
          rationalise from. The check has already reduced that evidence to
          a verdict and one plain sentence; that reduction is the check's
          job, not the agent's to second-guess.
        - `created_at` and `case_id` are dropped as irrelevant to the
          judgement.
        - `finding_id` is KEPT, because the agent must cite findings by id
          and a decision that cites nothing is unauditable.

        Adding a method rather than a field: this changes no dataclass
        field, no schema and no serialisation, so it does not touch the
        core model the way an extra column would.
        """
        return {
            "finding_id": self.finding_id,
            "check": self.check_id,
            "category": self.category.value,
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 3),
            "explanation": self.explanation,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "check_id": self.check_id,
            "case_id": self.case_id,
            "category": self.category.value,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# AgentDecision - the only thing that may recommend anything
# ---------------------------------------------------------------------------


@dataclass
class AgentDecision:
    """
    The agent's rollup of a case's Findings into one recommendation.

    Guard: REQUEST_EVIDENCE requires at least one named artifact.
    "Send better photos" isn't actionable for a claimant - you must
    name the specific views (e.g. "wide shot of rear bumper", "odometer
    photo").
    """

    case_id: str
    recommendation: Recommendation
    confidence: float
    summary: str
    supporting_finding_ids: list[str] = field(default_factory=list)
    requested_artifacts: list[str] = field(default_factory=list)
    # --- ablation telemetry ---------------------------------------------
    # Which system produced this decision, and what it cost to produce.
    # These exist so the rules-only baseline and the LLM agent can write
    # into the same table and still be told apart afterwards - the whole
    # ablation depends on being able to select one arm's decisions
    # without guessing from timestamps. The baseline writes
    # "baseline-v1" and three zeroes; an agent run writes its own policy
    # version and its real counts, which is also the honest way to
    # report what the LLM arm actually spent.
    policy_version: str = "unversioned"
    risk_band: Optional[RiskBand] = None
    score: Optional[float] = None
    tool_calls_count: int = 0
    iterations_count: int = 0
    llm_calls_count: int = 0
    # Wall-clock the decision took to produce. Zero for the rules-only
    # baseline (arithmetic), real for the agent - which is half of what
    # the ablation is actually comparing: the agent has to buy something
    # with the latency and money it spends, and that trade is invisible
    # unless the cost is recorded next to the outcome.
    latency_ms: int = 0
    decision_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.case_id, "case_id")
        if not isinstance(self.recommendation, Recommendation):
            raise TypeError(
                f"recommendation must be a Recommendation, got {type(self.recommendation).__name__}"
            )
        _require_unit_interval(self.confidence, "confidence")
        _require_nonblank(self.summary, "summary")
        if self.recommendation == Recommendation.REQUEST_EVIDENCE and not self.requested_artifacts:
            raise ValueError(
                "REQUEST_EVIDENCE requires at least one named artifact - "
                "'send better photos' isn't actionable for a claimant; name the "
                "specific views (e.g. 'wide shot of rear bumper', 'odometer photo')"
            )
        if self.risk_band is not None and not isinstance(self.risk_band, RiskBand):
            raise TypeError(f"risk_band must be a RiskBand, got {type(self.risk_band).__name__}")
        if self.risk_band is not None and self.risk_band.to_recommendation() != self.recommendation:
            raise ValueError(
                f"risk_band {self.risk_band.value!r} maps to "
                f"{self.risk_band.to_recommendation().value!r}, not {self.recommendation.value!r}"
            )
        for name in ("tool_calls_count", "iterations_count", "llm_calls_count", "latency_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative int, got {value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "case_id": self.case_id,
            "recommendation": self.recommendation.value,
            "risk_band": self.risk_band.value if self.risk_band is not None else None,
            "score": self.score,
            "confidence": self.confidence,
            "summary": self.summary,
            "supporting_finding_ids": list(self.supporting_finding_ids),
            "requested_artifacts": list(self.requested_artifacts),
            "policy_version": self.policy_version,
            "tool_calls_count": self.tool_calls_count,
            "iterations_count": self.iterations_count,
            "llm_calls_count": self.llm_calls_count,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# PerceptionRecord - the dedup cache
# ---------------------------------------------------------------------------


@dataclass
class PerceptionRecord:
    """
    Cached vision-model output for one image, keyed by the sha256 of its
    bytes rather than by image id or case id.

    The damage_description..anomaly_notes fields are the one-time
    structured perception pass's output (see src/perception.py) - every
    downstream check reads these rather than calling the vision API
    itself, which is what makes the whole project affordable on a free
    tier. They're deliberately plain Optional[str], not enums, even
    though the perception prompt asks for values from a fixed set
    (e.g. damage_severity in none/minor/moderate/severe): an LLM
    occasionally drifts from its own instructions, and a dataclass that
    hard-rejects an unexpected-but-plausible string would turn a
    successful, billable API call into a crash instead of just a value
    a check treats cautiously. Validate the checks' *inputs*, not this
    record's construction.
    """

    content_hash: str
    source: str  # e.g. "clip-vit-b32", "gemini-3.5-flash", "easyocr"
    embedding: Optional[list[float]] = None
    caption: Optional[str] = None
    ocr_text: Optional[str] = None
    damage_description: Optional[str] = None
    damage_severity: Optional[str] = None  # none / minor / moderate / severe
    weather_observed: Optional[str] = None  # clear / overcast / rain / wet_ground / snow / unknown
    road_condition: Optional[str] = None
    shadow_direction: Optional[str] = None  # N/NE/E/SE/S/SW/W/NW / none_visible
    shadow_length: Optional[str] = None  # none / short / medium / long
    lighting: Optional[str] = None  # daylight / dusk / night / artificial / unknown
    plate_text: Optional[str] = None  # "" if unreadable
    scene_context: Optional[str] = None
    anomaly_notes: Optional[str] = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.content_hash, str) or not _HEX64.match(self.content_hash):
            raise ValueError(
                f"content_hash must be a 64-char lowercase hex sha256 digest, got {self.content_hash!r}"
            )
        _require_nonblank(self.source, "source")
        if not isinstance(self.raw_response, dict):
            raise TypeError(f"raw_response must be a dict, got {type(self.raw_response).__name__}")

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        """Content hash used as the cache key. Same photo, same key, forever."""
        return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """
    agent_type routes the case to the right internal pipeline -
    "underwriting" (Agent 1, pre-policy inspection, no incident) or
    "claims" (Agent 2, post-incident). claim_amount is None for
    underwriting cases, which never have one.

    Deliberately absent: any notion of "archetype" or "is this fraud".
    A production Case is exactly what a real claim intake would produce;
    ground truth for the synthetic corpus (src/generate_dataset.py)
    lives only in data/generated/ground_truth.csv, never in this table,
    so nothing downstream can accidentally (or conveniently) read the
    answer key.
    """

    case_id: str
    claimant_id: str
    garage_id: str
    claim_type: str
    declared_time: Optional[datetime] = None
    declared_location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    agent_type: str = "claims"
    claim_amount: Optional[float] = None
    vehicle_registration: Optional[str] = None
    status: str = "open"
    created_at: datetime = field(default_factory=_now)
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_variant: Optional[str] = None
    vehicle_year: Optional[int] = None
    engine_number: Optional[str] = None
    chassis_number: Optional[str] = None
    rto: Optional[str] = None
    fuel_type: Optional[str] = None
    idv: Optional[float] = None
    # Ambiguous intake choice: /v1/track must verify by policy_number, while
    # the requested additive policy fields only name previous_policy_number.
    # Keep both so the public tracker has a current policy identifier without
    # treating the previous policy number as current.
    policy_number: Optional[str] = None
    policy_type: Optional[str] = None
    previous_policy_number: Optional[str] = None
    policy_ncb_percent: Optional[float] = None
    policy_start_date: Optional[date] = None
    policy_end_date: Optional[date] = None
    person_name: Optional[str] = None
    person_dob: Optional[date] = None
    person_address: Optional[str] = None
    person_contact: Optional[str] = None
    driving_license_number: Optional[str] = None
    fir_number: Optional[str] = None
    settlement_preference: Optional[str] = None
    bank_account_last4: Optional[str] = None
    declaration_notes: Optional[str] = None

    def __post_init__(self) -> None:
        _require_nonblank(self.case_id, "case_id")
        _require_nonblank(self.claimant_id, "claimant_id")
        _require_nonblank(self.garage_id, "garage_id")
        _require_nonblank(self.claim_type, "claim_type")
        _require_nonblank(self.agent_type, "agent_type")
        if self.agent_type not in ("claims", "underwriting"):
            raise ValueError(f"agent_type must be 'claims' or 'underwriting', got {self.agent_type!r}")
        _require_nonblank(self.status, "status")
        if self.latitude is not None and not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"latitude must be in [-90, 90], got {self.latitude!r}")
        if self.longitude is not None and not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"longitude must be in [-180, 180], got {self.longitude!r}")
        if self.claim_amount is not None and self.claim_amount <= 0:
            raise ValueError(f"claim_amount must be positive, got {self.claim_amount!r}")
        if self.vehicle_year is not None and not (1900 <= self.vehicle_year <= 2100):
            raise ValueError(f"vehicle_year must be between 1900 and 2100, got {self.vehicle_year!r}")
        if self.idv is not None and self.idv <= 0:
            raise ValueError(f"idv must be positive, got {self.idv!r}")
        if self.policy_ncb_percent is not None and not (0.0 <= self.policy_ncb_percent <= 100.0):
            raise ValueError(
                f"policy_ncb_percent must be in [0, 100], got {self.policy_ncb_percent!r}"
            )
        if self.bank_account_last4 is not None:
            if not isinstance(self.bank_account_last4, str) or not re.fullmatch(r"\d{4}", self.bank_account_last4):
                raise ValueError("bank_account_last4 must be exactly four digits")


@dataclass
class AdminActionRecord:
    """One human admin action, stored separately from agent decisions."""

    case_id: str
    admin_id: str
    action: AdminAction
    reason: Optional[str] = None
    timestamp: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.case_id, "case_id")
        _require_nonblank(self.admin_id, "admin_id")
        if not isinstance(self.action, AdminAction):
            raise TypeError(f"action must be an AdminAction, got {type(self.action).__name__}")
        if self.action == AdminAction.REJECT:
            _require_nonblank(self.reason, "reason")


# ---------------------------------------------------------------------------
# Claimant - a real profile, not fraud signal
#
# Persisted (unlike archetype/fraud_metadata) because a real intake
# system genuinely has this data, and a future pattern-of-life check
# needs to query it - e.g. "how many claims this quarter share this
# phone number or bank account". Such a check would file under HISTORY
# (has this been seen before?) rather than needing a category of its
# own; see CheckCategory on why the taxonomy names questions, not
# techniques.
# ---------------------------------------------------------------------------

_PHONE = re.compile(r"^[6-9]\d{9}$")


@dataclass
class Claimant:
    claimant_id: str
    name: str
    phone: str
    bank_account: str
    address: str
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.claimant_id, "claimant_id")
        _require_nonblank(self.name, "name")
        _require_nonblank(self.bank_account, "bank_account")
        _require_nonblank(self.address, "address")
        if not isinstance(self.phone, str) or not _PHONE.match(self.phone):
            raise ValueError(f"phone must be a 10-digit Indian mobile number starting 6-9, got {self.phone!r}")


# ---------------------------------------------------------------------------
# ImageArtifact - links a submitted photo to a case and to its
# (deduplicated) PerceptionRecord via content_hash
# ---------------------------------------------------------------------------


@dataclass
class ImageArtifact:
    artifact_id: str
    case_id: str
    content_hash: str
    filename: str
    role: str = "unspecified"  # e.g. "damage-wide", "odometer", "invoice"
    uploaded_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.artifact_id, "artifact_id")
        _require_nonblank(self.case_id, "case_id")
        _require_nonblank(self.filename, "filename")
        _require_nonblank(self.role, "role")
        if not isinstance(self.content_hash, str) or not _HEX64.match(self.content_hash):
            raise ValueError(
                f"content_hash must be a 64-char lowercase hex sha256 digest, got {self.content_hash!r}"
            )


# ---------------------------------------------------------------------------
# Image - the ingest pipeline's own record
# ---------------------------------------------------------------------------


@dataclass
class Image:
    """
    Everything the ingest pipeline (src/ingest.py) can learn about one
    photo without running a single check: its content hash, its two
    perceptual hashes, and its CLIP embedding. One row per (case,
    file), saved the moment the image arrives - before any check runs.

    That ordering is the whole point. Duplicate-image and CLIP-
    similarity checks work retroactively only because every image ever
    submitted already has a row here with an embedding sitting in it;
    case #700 can be compared against case #12 because #12 was indexed
    months ago, not because #700's check went looking for it.

    Distinct from PerceptionRecord/ImageArtifact above: those model a
    content-hash-keyed *cache* of vision-model output (one row per
    unique photo, however many cases it appears in). Image is the
    ingest pipeline's per-submission record instead - one row per
    (case, file) - so duplicate-detection and similarity search have
    everything they need (hashes + embedding + case_id) in a single
    table rather than a three-way join.
    """

    image_id: str
    case_id: str
    path: str
    content_hash: str
    phash: str
    dhash: str
    embedding: Optional[list[float]] = None
    exif: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.image_id, "image_id")
        _require_nonblank(self.case_id, "case_id")
        _require_nonblank(self.path, "path")
        _require_nonblank(self.phash, "phash")
        _require_nonblank(self.dhash, "dhash")
        if not isinstance(self.content_hash, str) or not _HEX64.match(self.content_hash):
            raise ValueError(
                f"content_hash must be a 64-char lowercase hex sha256 digest, got {self.content_hash!r}"
            )
        if self.embedding is not None and not isinstance(self.embedding, list):
            raise TypeError(f"embedding must be a list of floats or None, got {type(self.embedding).__name__}")
        if not isinstance(self.exif, dict):
            raise TypeError(f"exif must be a dict, got {type(self.exif).__name__}")


# ---------------------------------------------------------------------------
# AuditEvent - append-only operational log, not evidence about a case
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    """
    "Case ingested, 4 images indexed" is not a Finding - it carries no
    verdict or confidence, and a human reviewer reading the Finding
    history for a case shouldn't have to skip over operational noise
    to find evidence. Kept as its own append-only log for that reason.
    """

    event_type: str
    details: dict[str, Any] = field(default_factory=dict)
    case_id: Optional[str] = None
    event_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_nonblank(self.event_type, "event_type")
        if not isinstance(self.details, dict):
            raise TypeError(f"details must be a dict, got {type(self.details).__name__}")
