"""
fraudlens.api
===============

The HTTP contract. A separately-built React frontend is designed against
`/openapi.json` and has no other view of this system: it cannot read the
database, cannot read the filesystem, and cannot import a single symbol from
this package. Every decision here favours that reader.

Three consequences shape the whole module.

**Every response is a declared Pydantic model.** An endpoint returning a bare
dict is invisible to the contract - it appears in the schema as "object" and a
frontend developer has to guess. Guessing is how the trace screen came to read
a `content` key that no producer ever wrote, so the endpoint silently rendered
nothing.

**A screen should cost one request.** `GET /v1/cases/{id}` returns the
declaration, the images, every finding grouped by category, the decision and
the per-category counts, because a detail screen that needs five round trips is
a detail screen that renders in pieces.

**Findings carry attribution.** `threshold_gaming` produces 91 of the corpus's
clean-case concerns and every one was measured to be about the repairing
garage's billing pattern rather than the claimant's conduct. A UI that renders
that beside a claimant's name accuses the wrong party, so `attributed_to`,
`subject_id` and `subject_url` travel with every finding and come from the
check itself rather than being inferred here.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import shutil
import secrets
from contextlib import asynccontextmanager
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, Header,
                     HTTPException, Query, Request, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src import db, runtime_store
from src.agent.policy import CLAIMS_POLICY, UNDERWRITING_POLICY
from src.models import AdminAction, AdminActionRecord, AuditEvent, Case, CheckCategory, Recommendation, RiskBand


def _load_dotenv(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv([Path(".env"), Path("../FraudLens-2.0-Frontend/.env")])

DATA_DIR = Path(os.environ.get("FRAUDLENS_DATA_DIR", "data"))
DB_PATH = os.environ.get("FRAUDLENS_DB", "fraudlens.db")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")
UPLOAD_DIR = Path(os.environ.get("FRAUDLENS_UPLOAD_DIR", str(DATA_DIR / "uploads")))
THUMB_DIR = Path(os.environ.get("FRAUDLENS_THUMB_DIR", "outputs/.thumbnails"))
THUMB_WIDTH = 400
LOG_LEVEL = os.environ.get("FRAUDLENS_LOG_LEVEL", "INFO").upper()
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("FRAUDLENS_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_SUBMIT_MAX = int(os.environ.get("FRAUDLENS_RATE_LIMIT_SUBMIT_MAX", "6"))
RATE_LIMIT_TRACK_MAX = int(os.environ.get("FRAUDLENS_RATE_LIMIT_TRACK_MAX", "30"))
HEALTH_GEMINI_TTL_SECONDS = int(os.environ.get("FRAUDLENS_HEALTH_GEMINI_TTL_SECONDS", "900"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(message)s",
)
access_log = logging.getLogger("fraudlens.access")

# The survey threshold below which Indian motor claims are typically settled
# without an independent surveyor. Exposed per case because it is the
# structural fact the whole threshold-gaming archetype turns on.
SURVEY_THRESHOLD_INR = 50_000.0

@asynccontextmanager
async def lifespan(_app):
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(DB_PATH)
    try:
        db.init_db(conn)
        runtime_store.init(conn)
        # A single API process owns BackgroundTasks. Never leave interrupted
        # work looking live after a restart; reviewers can explicitly retry it.
        runtime_store.interrupt_jobs(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="FraudLens API",
    version="2.1",
    description=(
        "Investigation and triage for photograph-based Indian motor claims. "
        "The agent can approve, request evidence, or escalate; a separate human "
        "admin action can approve, reject with a reason, or request more evidence."
    ),
)

def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8787")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Password"],
    expose_headers=["ETag", "Content-Length"],
)

_JOBS: dict[str, dict[str, Any]] = {}
_ARCHETYPES: Optional[dict[str, str]] = None
_MEASUREMENTS: Optional[dict[str, dict[str, Any]]] = None
_RATE_LIMITS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_HEALTH_GEMINI_CACHE: dict[str, Any] = {"checked_at": 0.0, "reachable": None, "status": "unknown"}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request) -> tuple[Optional[str], int]:
    if request.method == "POST" and request.url.path == "/v1/auth/login":
        return "login", 5
    if request.method == "POST" and request.url.path == "/v1/cases":
        return "submit", RATE_LIMIT_SUBMIT_MAX
    if request.method == "GET" and request.url.path == "/v1/track":
        return "track", RATE_LIMIT_TRACK_MAX
    return None, 0


def _rate_limited(request: Request) -> tuple[bool, int]:
    bucket, limit = _rate_limit_key(request)
    if bucket is None:
        return False, 0
    now = time.monotonic()
    key = (bucket, _client_ip(request))
    window = _RATE_LIMITS[key]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= limit:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - window[0])))
        return True, retry_after
    window.append(now)
    return False, 0


@app.middleware("http")
async def _ops_middleware(request: Request, call_next):
    start = time.perf_counter()
    limited, retry_after = _rate_limited(request)
    if limited:
        response = error(
            429,
            "RATE_LIMITED",
            "Too many requests from this client. Please wait and try again.",
        )
        response.headers["Retry-After"] = str(retry_after)
    else:
        response = await call_next(request)

    latency_ms = int((time.perf_counter() - start) * 1000)
    admin_actor = getattr(request.state, "admin_actor", None)
    access_log.info(json.dumps({
        "event": "http_request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "latency_ms": latency_ms,
        "client_ip": _client_ip(request),
        "admin": admin_actor,
    }, sort_keys=True))
    response.headers["X-Request-Latency-Ms"] = str(latency_ms)
    return response


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    field: Optional[str] = Field(default=None, description="The offending field, where one applies.")
    reason: str


class ErrorResponse(BaseModel):
    """
    One shape for every failure.

    A frontend must be able to branch on `code` without parsing prose, so the
    code is a stable machine token and the message is for humans.
    """

    status: int
    code: str = Field(description="Stable machine-readable token, e.g. CASE_NOT_FOUND.")
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


def error(status: int, code: str, message: str,
          details: Optional[list[ErrorDetail]] = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(status=status, code=code, message=message,
                              details=details or []).model_dump(),
    )


class ApiError(HTTPException):
    """An HTTPException carrying a machine code, so handlers can render the envelope."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: Optional[list[ErrorDetail]] = None) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.details = details or []


@app.exception_handler(ApiError)
async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return error(exc.status_code, exc.code, str(exc.detail), exc.details)


@app.exception_handler(HTTPException)
async def _http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    codes = {400: "BAD_REQUEST", 401: "UNAUTHORISED", 403: "FORBIDDEN",
             404: "NOT_FOUND", 409: "CONFLICT", 422: "VALIDATION_FAILED"}
    return error(exc.status_code, codes.get(exc.status_code, "ERROR"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default 422 body is a nested dump of pydantic internals. This
    # names the field and says what was wrong with it, which is what a form
    # needs in order to highlight an input.
    details = [
        ErrorDetail(field=".".join(str(p) for p in e.get("loc", []) if p != "body"),
                    reason=e.get("msg", "invalid"))
        for e in exc.errors()
    ]
    return error(422, "VALIDATION_FAILED",
                 "One or more parameters were rejected.", details)


@app.exception_handler(Exception)
async def _unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
    # A stack trace in a browser console helps nobody and leaks internals.
    return error(500, "INTERNAL_ERROR",
                 f"An unexpected error occurred: {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def require_admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_password: Optional[str] = Header(default=None),
) -> str:
    """
    Browser admin auth for the FastAPI deployment.

    The frontend sends the admin password as a bearer token; the server compares
    only its SHA-256 digest with ADMIN_PASSWORD_SHA256 from the environment.
    EVIDENCE_SERVICE_TOKEN is also accepted for server-to-server callers.
    """
    expected_hash = (os.environ.get("ADMIN_PASSWORD_SHA256") or "").strip().lower()
    service_token = (os.environ.get("EVIDENCE_SERVICE_TOKEN") or "").strip()
    if not expected_hash and not service_token:
        raise ApiError(503, "ADMIN_AUTH_NOT_CONFIGURED",
                       "Admin access has not been configured.")

    credential = x_admin_password or ""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        credential = value if scheme.lower() == "bearer" and value else authorization
    credential = credential.strip()
    if not credential:
        raise ApiError(401, "UNAUTHORISED", "Admin credentials are required.")

    if service_token and hmac.compare_digest(credential, service_token):
        request.state.admin_actor = "service"
        return "service"

    with runtime_store.connection(DB_PATH) as conn:
        actor = runtime_store.session_actor(conn, credential, expected_hash)
    if actor:
        request.state.admin_actor = actor
        return actor

    supplied_hash = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    if expected_hash and hmac.compare_digest(supplied_hash, expected_hash):
        actor = os.environ.get("ADMIN_EMAIL", "admin")
        request.state.admin_actor = actor
        return actor
    raise ApiError(401, "UNAUTHORISED", "Admin credentials are invalid.")

class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class SessionOut(BaseModel):
    user: str
    token: Optional[str] = None
    expires_at: Optional[float] = None


class LogoutOut(BaseModel):
    ok: bool


@app.post("/v1/auth/login", response_model=SessionOut, tags=["auth"])
def login(payload: LoginIn) -> SessionOut:
    actor = os.environ.get("ADMIN_EMAIL", "").strip()
    expected = os.environ.get("ADMIN_PASSWORD_SHA256", "").strip().lower()
    if not actor or not expected:
        raise ApiError(503, "ADMIN_AUTH_NOT_CONFIGURED", "Admin access has not been configured.")
    supplied = hashlib.sha256(payload.password.encode()).hexdigest()
    if not (hmac.compare_digest(payload.email.strip().lower(), actor.lower())
            and hmac.compare_digest(supplied, expected)):
        raise ApiError(401, "UNAUTHORISED", "Email or password is incorrect.")
    token = secrets.token_urlsafe(48)
    expires = time.time() + 8 * 3600
    with runtime_store.connection(DB_PATH) as conn:
        runtime_store.create_session(conn, token, actor, expected, expires)
    return SessionOut(user=actor, token=token, expires_at=expires)


@app.get("/v1/auth/session", response_model=SessionOut, tags=["auth"])
def session(_admin: str = Depends(require_admin)) -> SessionOut:
    return SessionOut(user=_admin)


@app.post("/v1/auth/logout", response_model=LogoutOut, tags=["auth"])
def logout(authorization: Optional[str] = Header(default=None)) -> LogoutOut:
    token = (authorization or "").removeprefix("Bearer ")
    with runtime_store.connection(DB_PATH) as conn:
        runtime_store.delete_session(conn, token)
    return LogoutOut(ok=True)


def archetypes() -> dict[str, str]:
    global _ARCHETYPES
    if _ARCHETYPES is None:
        if GROUND_TRUTH.exists():
            with open(GROUND_TRUTH, encoding="utf-8") as fh:
                _ARCHETYPES = {r["case_id"]: r["archetype"] for r in csv.DictReader(fh)}
        else:
            _ARCHETYPES = {}
    return _ARCHETYPES


def measurements() -> dict[str, dict[str, Any]]:
    """
    Per-check measured performance, read from the measurement artefacts.

    Read rather than hardcoded so these stay current as refresh_all.py runs. A
    hardcoded reliability figure in an API is a figure that will be wrong
    within a week and will still look authoritative.
    """
    global _MEASUREMENTS
    if _MEASUREMENTS is not None:
        return _MEASUREMENTS

    out: dict[str, dict[str, Any]] = defaultdict(dict)

    v2 = Path("outputs/check_performance_v2.md")
    if v2.exists():
        for line in v2.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            check_id = cells[0].strip("`")
            out[check_id]["target_archetype"] = None if cells[3] == "—" else cells[3]
            out[check_id]["recall"] = None if cells[4] in ("n/a", "—") else cells[4]
            out[check_id]["fp_rate"] = None if cells[5] in ("n/a", "—") else cells[5]

    marginal = Path("outputs/marginal_contribution.md")
    if marginal.exists():
        for line in marginal.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 7:
                continue
            check_id = cells[0].strip("`")
            out[check_id]["marginal_recall"] = cells[2]
            out[check_id]["marginal_fp"] = cells[4]

    _MEASUREMENTS = dict(out)
    return _MEASUREMENTS


def concerns_by_check(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT check_id, COUNT(*) FROM findings WHERE verdict = 'concern' "
        "GROUP BY check_id")}


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(DB_PATH)
    db.init_db(conn)
    runtime_store.init(conn)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

AttributedTo = Literal["claimant", "garage", "vehicle", "image"]
CheckStatus = Literal["active", "quota_blocked", "corpus_untestable", "retired", "demoted"]


class ImageOut(BaseModel):
    image_id: str
    case_id: str
    content_hash: Optional[str] = None
    url: str = Field(description="Full-size bytes. The frontend cannot read the disk.")
    thumbnail_url: str = Field(description="400px-wide version, cached on first request.")
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: Optional[int] = None
    has_perception: bool = False
    scene_context: Optional[str] = None
    damage_severity: Optional[str] = None
    damage_description: Optional[str] = None
    anomaly_notes: Optional[str] = None


class FindingOut(BaseModel):
    finding_id: str
    check_id: str
    category: str
    verdict: Literal["pass", "inconclusive", "concern"]
    confidence: float
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)

    # Whose conduct this finding describes. Comes from the check, not from
    # anything inferred here. See the module docstring.
    attributed_to: AttributedTo
    subject_id: Optional[str] = Field(
        default=None,
        description="The specific entity the finding is about - a garage id for a "
                    "garage-attributed finding, a registration for a vehicle one.")
    subject_url: Optional[str] = Field(
        default=None, description="Where to look that entity up, where an endpoint exists.")

    check_weight: float = Field(description="How much this check moves the rules-only score.")
    check_status: CheckStatus
    check_limitation: Optional[str] = Field(
        default=None,
        description="One sentence on why this check is not contributing, when it is not.")


class FindingGroup(BaseModel):
    category: str
    findings: list[FindingOut] = Field(default_factory=list)
    concern_count: int = 0


class DecisionOut(BaseModel):
    decision_id: str
    case_id: str
    recommendation: Literal["approve", "request_evidence", "escalate"]
    risk_band: Optional[Literal["clear", "request_evidence", "desk_review", "escalate_siu"]] = None
    confidence: float
    summary: str = Field(description="The narrative a claims handler reads.")
    supporting_finding_ids: list[str] = Field(default_factory=list)
    requested_artifacts: list[str] = Field(default_factory=list)
    policy_version: Optional[str] = None
    score: Optional[float] = None
    tool_calls_count: int = 0
    iterations_count: int = 0
    llm_calls_count: int = 0
    latency_ms: int = 0
    provider_unavailable: bool = Field(
        default=False,
        description="True when adjudication did not converge, including provider or parsing failures.")
    created_at: Optional[datetime] = None


class CaseSummary(BaseModel):
    """One queue row. Carries everything a table renders, so no second request."""

    case_id: str
    agent_type: str
    claim_type: Optional[str] = None
    status: Optional[str] = None
    vehicle_registration: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_variant: Optional[str] = None
    vehicle_year: Optional[int] = None
    engine_number: Optional[str] = None
    chassis_number: Optional[str] = None
    rto: Optional[str] = None
    fuel_type: Optional[str] = None
    idv: Optional[float] = None
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
    bank_account_last4: Optional[str] = Field(
        default=None, description="Only the last four bank-account digits are stored.")
    claimant_id: Optional[str] = None
    garage_id: Optional[str] = None
    declared_location: Optional[str] = None
    incident_date: Optional[datetime] = Field(default=None, description="Declared time of loss.")
    created_at: Optional[datetime] = None
    claim_amount: Optional[float] = None
    below_survey_threshold: Optional[bool] = Field(
        default=None,
        description="Claim below the ₹50,000 surveyor threshold - the band settled "
                    "without independent inspection.")
    recommendation: Optional[str] = None
    risk_band: Optional[str] = None
    concern_count: int = 0
    image_count: int = 0
    thumbnail_url: Optional[str] = None
    archetype: Optional[str] = Field(
        default=None, description="Evaluation metadata; absent in production traffic.")


class CaseDetail(CaseSummary):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    images: list[ImageOut] = Field(default_factory=list)
    finding_groups: list[FindingGroup] = Field(default_factory=list)
    findings_by_category: dict[str, list[FindingOut]] = Field(
        default_factory=dict, description="Same findings keyed by category, for convenience.")
    decision: Optional[DecisionOut] = None
    decisions: list[DecisionOut] = Field(default_factory=list)
    concern_counts_by_category: dict[str, int] = Field(default_factory=dict)
    attributed_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Concerns by whose conduct they describe, so a screen can say "
                    "'2 concerns about this garage, 0 about this claimant'.")
    total_concerns: int = 0
    audit: list[dict[str, Any]] = Field(default_factory=list)
    processing: Optional[dict[str, Any]] = None


class CaseListOut(BaseModel):
    total: int
    page: int
    page_size: int
    has_more: bool
    items: list[CaseSummary] = Field(default_factory=list)


class TraceStepOut(BaseModel):
    index: int
    step: Optional[int] = None
    type: Literal["reasoning", "tool_call", "conclusion", "guard", "parse_failure", "other"]
    kind: str = Field(description="The producer's own label, before normalisation.")
    content: Optional[str] = Field(default=None, description="What this step said or did.")
    tool_name: Optional[str] = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0


class TraceOut(BaseModel):
    case_id: str
    policy_version: Optional[str] = None
    converged: Optional[bool] = None
    steps: list[TraceStepOut] = Field(default_factory=list)
    excluded_outage_steps: int = Field(
        default=0,
        description="Provider-outage steps withheld. A 429 is not reasoning and must "
                    "not be shown as though it were.")


class CheckMeta(BaseModel):
    check_id: str
    category: str
    scope: str
    weight: float
    requires_perception: bool
    target_archetypes: list[str] = Field(default_factory=list)
    attributed_to: AttributedTo
    status: CheckStatus
    measured_recall: Optional[str] = None
    measured_fp_rate: Optional[str] = None
    marginal_recall_contribution: Optional[str] = None
    marginal_fp_contribution: Optional[str] = None
    concerns_fired: int = 0
    limitation: Optional[str] = None


class CheckDetail(CheckMeta):
    description: Optional[str] = Field(default=None, description="The check's own docstring.")
    measurement_history: list[str] = Field(
        default_factory=list, description="Artefacts recording how this check was measured.")


class GarageSummary(BaseModel):
    garage_id: str
    case_count: int
    total_claimed_inr: float
    mean_claim_inr: Optional[float] = None
    median_claim_inr: Optional[float] = None
    below_threshold_count: int = 0
    below_threshold_pct: Optional[float] = None
    population_below_threshold_pct: Optional[float] = None
    claim_value_histogram: list[dict[str, Any]] = Field(
        default_factory=list, description="Claim-value buckets, for a distribution chart.")
    linked_case_ids: list[str] = Field(default_factory=list)
    concern_count: int = 0


class SimilarCase(BaseModel):
    case_id: str
    shared_via: Literal["image", "claimant", "garage", "vehicle_registration"]
    shared_value: Optional[str] = None
    detail: Optional[str] = None
    risk_band: Optional[str] = None
    archetype: Optional[str] = None


class SimilarCasesOut(BaseModel):
    case_id: str
    items: list[SimilarCase] = Field(default_factory=list)


class ArmSummary(BaseModel):
    arm: str
    cases: int
    fraud_caught: Optional[str] = None
    clean_flagged: Optional[str] = None
    mean_llm_calls: Optional[float] = None
    mean_tool_calls: Optional[float] = None
    mean_latency_s: Optional[float] = None


class StatsOut(BaseModel):
    total_cases: int
    by_agent_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_risk_band: dict[str, int] = Field(default_factory=dict)
    by_recommendation: dict[str, int] = Field(default_factory=dict)
    decided_cases: int = 0
    undecided_cases: int = 0
    total_findings: int = 0
    concern_findings: int = 0
    concerns_by_check: dict[str, int] = Field(default_factory=dict)
    concerns_by_attribution: dict[str, int] = Field(default_factory=dict)
    images: int = 0
    images_with_perception: int = 0
    straight_through_rate: Optional[float] = Field(
        default=None, description="Share of decided cases cleared with no human touch.")
    ablation_arms: list[ArmSummary] = Field(default_factory=list)


class PolicyOut(BaseModel):
    policy_version: str
    agent_type: str
    check_ids: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    max_iterations: int
    max_tool_calls: int
    bias: Optional[str] = None
    system_prompt: str


class JobOut(BaseModel):
    job_id: str
    case_id: Optional[str] = None
    status: Literal["queued", "running", "done", "failed"]
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: Optional[str] = None
    detail: Optional[str] = None
    provider_unavailable: bool = False


class SubmitCaseOut(BaseModel):
    case_id: str
    job_id: str
    status: str
    images_received: int = 0


class AdminActionOut(BaseModel):
    case_id: str
    admin_id: str
    action: Literal["approve", "reject", "request_more_evidence"]
    reason: Optional[str] = None
    timestamp: datetime


class ActionOut(BaseModel):
    case_id: str
    action: Literal["approve", "reject", "request_more_evidence"]
    status: str
    reason: Optional[str] = None
    admin_id: str
    recorded_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    database_reachable: bool
    cases: int = 0
    provider_configured: bool = False
    provider_reachable: Optional[bool] = None
    provider_status: str = "unknown"
    provider_checked_at: Optional[datetime] = None
    quota_remaining_estimate: Optional[int] = None
    ablation_verified_agent_cases: int = 0
    ablation_total_cases: int = 0
    ablation_complete: bool = False
    ablation_driver_status: str = "unknown"
    perception_records: int = 0
    image_records: int = 0
    active_api_jobs: dict[str, int] = Field(default_factory=dict)


class ActionIn(BaseModel):
    public_message: Optional[str] = Field(default=None, max_length=3000)
    action: AdminAction
    reason: Optional[str] = None
    admin_id: str = "admin"
    requested_artifacts: list[str] = Field(default_factory=list)


class ReportDeclaration(BaseModel):
    case_id: str
    agent_type: str
    claim_type: Optional[str] = None
    status: Optional[str] = None
    declared_location: Optional[str] = None
    incident_date: Optional[datetime] = None
    claim_amount: Optional[float] = None
    vehicle_registration: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_variant: Optional[str] = None
    vehicle_year: Optional[int] = None
    engine_number: Optional[str] = None
    chassis_number: Optional[str] = None
    rto: Optional[str] = None
    fuel_type: Optional[str] = None
    idv: Optional[float] = None
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


class CaseReportOut(BaseModel):
    case_id: str
    declaration: ReportDeclaration
    findings_by_category: dict[str, list[FindingOut]] = Field(default_factory=dict)
    finding_groups: list[FindingGroup] = Field(default_factory=list)
    agent_recommendation: Optional[DecisionOut] = None
    agent_narrative: Optional[str] = None
    admin_action: Optional[AdminActionOut] = None


class TrackOut(BaseModel):
    case_id: str
    status: str
    final_admin_action: Optional[Literal["approve", "reject", "request_more_evidence"]] = None
    narrative: Optional[str] = None


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _check_status(check: Any, concerns: int) -> str:
    """Derived, so it cannot disagree with the weights and measurements behind it."""
    if check.weight == 0.0:
        return "demoted"
    if concerns == 0 and getattr(check, "limitation", ""):
        return "corpus_untestable"
    if concerns == 0:
        return "quota_blocked" if check.requires_perception else "corpus_untestable"
    return "active"


def _subject_for(check: Any, case: Optional[Case],
                 evidence: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    attribution = getattr(check, "attributed_to", "claimant")
    if attribution == "garage":
        gid = (case.garage_id if case else None) or evidence.get("garage_id")
        return (gid, f"/v1/garages/{gid}" if gid else None)
    if attribution == "vehicle":
        return ((case.vehicle_registration if case else None), None)
    if attribution == "image":
        return (evidence.get("image_id"), None)
    return ((case.claimant_id if case else None), None)


def _finding_out(f: Any, case: Optional[Case], concerns: dict[str, int]) -> FindingOut:
    from src.checks import REGISTRY

    check = REGISTRY.get(f.check_id)
    evidence = f.evidence or {}
    attribution = getattr(check, "attributed_to", "claimant") if check else "claimant"
    subject_id, subject_url = (_subject_for(check, case, evidence) if check else (None, None))
    return FindingOut(
        finding_id=f.finding_id, check_id=f.check_id, category=f.category.value,
        verdict=f.verdict.value, confidence=f.confidence, explanation=f.explanation,
        evidence=evidence, attributed_to=attribution,
        subject_id=subject_id, subject_url=subject_url,
        check_weight=check.weight if check else 0.0,
        check_status=_check_status(check, concerns.get(f.check_id, 0)) if check else "retired",
        check_limitation=(getattr(check, "limitation", "") or None) if check else None,
    )


def _decision_out(d: Any, conn: Optional[sqlite3.Connection] = None) -> DecisionOut:
    llm_calls = getattr(d, "llm_calls_count", 0) or 0
    policy = str(getattr(d, "policy_version", "") or "")
    fallback = llm_calls == 0 and policy.startswith("agent")
    if conn is not None:
        for event in reversed(db.get_audit_events_for_case(conn, d.case_id)):
            if event.event_type == "case_adjudicated" and event.details.get("policy_version") == policy:
                fallback = event.details.get("converged") is False
                break
    return DecisionOut(
        decision_id=d.decision_id, case_id=d.case_id,
        recommendation=d.recommendation.value if hasattr(d.recommendation, "value")
        else str(d.recommendation),
        risk_band=d.risk_band.value if getattr(d, "risk_band", None) else None,
        confidence=d.confidence, summary=d.summary,
        supporting_finding_ids=list(d.supporting_finding_ids or []),
        requested_artifacts=list(d.requested_artifacts or []),
        policy_version=getattr(d, "policy_version", None),
        score=getattr(d, "score", None),
        tool_calls_count=getattr(d, "tool_calls_count", 0) or 0,
        iterations_count=getattr(d, "iterations_count", 0) or 0,
        llm_calls_count=llm_calls,
        latency_ms=getattr(d, "latency_ms", 0) or 0,
        provider_unavailable=fallback,
        created_at=getattr(d, "created_at", None),
    )


def _admin_action_out(action: Optional[AdminActionRecord]) -> Optional[AdminActionOut]:
    if action is None:
        return None
    return AdminActionOut(
        case_id=action.case_id,
        admin_id=action.admin_id,
        action=action.action.value,
        reason=action.reason,
        timestamp=action.timestamp,
    )


def _best_decision(decisions: list[Any]) -> Optional[Any]:
    if not decisions:
        return None
    return sorted(decisions, key=lambda d: (getattr(d, "created_at", None)
                                            or datetime.min.replace(tzinfo=timezone.utc)))[-1]


def _resolve_data_path(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    raw = Path(path)
    candidates = [raw]
    if not raw.is_absolute():
        parts = raw.parts
        if parts and parts[0] == "data":
            candidates.append(DATA_DIR.joinpath(*parts[1:]))
        else:
            candidates.append(DATA_DIR / raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return raw


def _image_dimensions(path: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    resolved = _resolve_data_path(path)
    if resolved is None or not resolved.exists():
        return None, None, None
    try:
        from PIL import Image as PILImage
        with PILImage.open(resolved) as im:
            return im.size[0], im.size[1], resolved.stat().st_size
    except Exception:  # noqa: BLE001
        return None, None, None


def _perception_by_hash(conn: sqlite3.Connection, hashes: list[str]) -> dict[str, dict[str, Any]]:
    if not hashes:
        return {}
    marks = ",".join("?" * len(hashes))
    rows = conn.execute(
        f"SELECT content_hash, scene_context, damage_severity, damage_description, "
        f"anomaly_notes FROM perception_records WHERE content_hash IN ({marks})", hashes
    ).fetchall()
    return {r[0]: {"scene_context": r[1], "damage_severity": r[2],
                   "damage_description": r[3], "anomaly_notes": r[4]} for r in rows}


def _summary_for(conn: sqlite3.Connection, case: Case) -> CaseSummary:
    decisions = db.get_decisions_for_case(conn, case.case_id)
    best = _best_decision(decisions)
    concerns = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE case_id = ? AND verdict = 'concern'",
        (case.case_id,)).fetchone()[0]
    images = conn.execute(
        "SELECT image_id FROM images WHERE case_id = ? ORDER BY image_id",
        (case.case_id,)).fetchall()
    return CaseSummary(
        case_id=case.case_id, agent_type=case.agent_type, claim_type=case.claim_type,
        status=case.status, vehicle_registration=case.vehicle_registration,
        vehicle_make=case.vehicle_make, vehicle_model=case.vehicle_model,
        vehicle_variant=case.vehicle_variant, vehicle_year=case.vehicle_year,
        engine_number=case.engine_number, chassis_number=case.chassis_number,
        rto=case.rto, fuel_type=case.fuel_type, idv=case.idv,
        policy_number=case.policy_number, policy_type=case.policy_type,
        previous_policy_number=case.previous_policy_number,
        policy_ncb_percent=case.policy_ncb_percent,
        policy_start_date=case.policy_start_date, policy_end_date=case.policy_end_date,
        person_name=case.person_name, person_dob=case.person_dob,
        person_address=case.person_address, person_contact=case.person_contact,
        driving_license_number=case.driving_license_number,
        fir_number=case.fir_number, settlement_preference=case.settlement_preference,
        bank_account_last4=case.bank_account_last4,
        claimant_id=case.claimant_id, garage_id=case.garage_id,
        declared_location=case.declared_location, incident_date=case.declared_time,
        created_at=case.created_at, claim_amount=case.claim_amount,
        below_survey_threshold=(case.claim_amount < SURVEY_THRESHOLD_INR)
        if case.claim_amount is not None else None,
        recommendation=(best.recommendation.value
                        if best and hasattr(best.recommendation, "value") else None),
        risk_band=best.risk_band.value if best and getattr(best, "risk_band", None) else None,
        concern_count=concerns, image_count=len(images),
        thumbnail_url=(f"/v1/images/{images[0][0]}?thumb=1" if images else None),
        archetype=archetypes().get(case.case_id),
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

SORTABLE = ("created_at", "claim_amount", "risk_band", "concern_count")
BAND_ORDER = {"clear": 0, "request_evidence": 1, "desk_review": 2, "escalate_siu": 3}


@app.get("/v1/cases", response_model=CaseListOut, tags=["cases"],
         responses={422: {"model": ErrorResponse}})
def list_cases(
    risk_band: Optional[str] = Query(None, description="clear | request_evidence | desk_review | escalate_siu"),
    agent_type: Optional[str] = Query(None, description="claims | underwriting"),
    status: Optional[str] = None,
    recommendation: Optional[str] = Query(None, description="approve | request_evidence | escalate"),
    archetype: Optional[str] = Query(None, description="Evaluation metadata, e.g. CLEAN, REUSE"),
    garage_id: Optional[str] = None,
    date_from: Optional[datetime] = Query(None, description="Incident date lower bound."),
    date_to: Optional[datetime] = Query(None, description="Incident date upper bound."),
    amount_min: Optional[float] = Query(None, ge=0),
    amount_max: Optional[float] = Query(None, ge=0),
    has_concerns: Optional[bool] = Query(None, description="Only cases with at least one CONCERN."),
    search: Optional[str] = Query(None, description="Matches registration, claimant id, garage id or case id."),
    sort_by: str = Query("created_at", description="created_at | claim_amount | risk_band | concern_count"),
    sort_dir: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _admin: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
) -> CaseListOut:
    if sort_by not in SORTABLE:
        raise ApiError(422, "INVALID_SORT_FIELD",
                       f"sort_by must be one of {', '.join(SORTABLE)}.",
                       [ErrorDetail(field="sort_by", reason=f"unknown field {sort_by!r}")])
    if sort_dir not in ("asc", "desc"):
        raise ApiError(422, "INVALID_SORT_DIRECTION", "sort_dir must be 'asc' or 'desc'.",
                       [ErrorDetail(field="sort_dir", reason=f"got {sort_dir!r}")])

    arche = archetypes()
    cases = db.get_all_cases(conn)

    if agent_type:
        cases = [c for c in cases if c.agent_type == agent_type]
    if status:
        cases = [c for c in cases if c.status == status]
    if garage_id:
        cases = [c for c in cases if c.garage_id == garage_id]
    if archetype:
        cases = [c for c in cases if arche.get(c.case_id) == archetype]
    if date_from:
        cases = [c for c in cases if c.declared_time and c.declared_time >= date_from]
    if date_to:
        cases = [c for c in cases if c.declared_time and c.declared_time <= date_to]
    if amount_min is not None:
        cases = [c for c in cases if (c.claim_amount or 0) >= amount_min]
    if amount_max is not None:
        cases = [c for c in cases if (c.claim_amount or 0) <= amount_max]
    if search:
        needle = search.strip().lower()
        cases = [c for c in cases if needle in " ".join(
            str(x or "").lower() for x in
            (c.case_id, c.vehicle_registration, c.claimant_id, c.garage_id))]

    summaries = [_summary_for(conn, c) for c in cases]
    if risk_band:
        summaries = [s for s in summaries if s.risk_band == risk_band]
    if recommendation:
        summaries = [s for s in summaries if s.recommendation == recommendation]
    if has_concerns is not None:
        summaries = [s for s in summaries if (s.concern_count > 0) == has_concerns]

    reverse = sort_dir == "desc"
    if sort_by == "risk_band":
        summaries.sort(key=lambda s: BAND_ORDER.get(s.risk_band or "", -1), reverse=reverse)
    elif sort_by == "concern_count":
        summaries.sort(key=lambda s: s.concern_count, reverse=reverse)
    elif sort_by == "claim_amount":
        summaries.sort(key=lambda s: (s.claim_amount is None, s.claim_amount or 0),
                       reverse=reverse)
    else:
        summaries.sort(key=lambda s: (s.created_at is None,
                                      s.created_at or datetime.min.replace(tzinfo=timezone.utc)),
                       reverse=reverse)

    total = len(summaries)
    start = (page - 1) * page_size
    items = summaries[start:start + page_size]
    return CaseListOut(total=total, page=page, page_size=page_size,
                       has_more=start + len(items) < total, items=items)


@app.get("/v1/cases/{case_id}", response_model=CaseDetail, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_case_detail(case_id: str,
                    _admin: str = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_conn)) -> CaseDetail:
    case = db.get_case(conn, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")

    perceived = {r[0] for r in conn.execute("SELECT content_hash FROM perception_records")}
    raw_images = db.get_images_for_case(conn, case_id)
    perception = _perception_by_hash(conn, [i.content_hash for i in raw_images])
    images = []
    for i in raw_images:
        w, h, size = _image_dimensions(getattr(i, "path", None))
        images.append(ImageOut(
            image_id=i.image_id, case_id=i.case_id, content_hash=i.content_hash,
            url=f"/v1/images/{i.image_id}",
            thumbnail_url=f"/v1/images/{i.image_id}?thumb=1",
            width=w, height=h, bytes=size,
            has_perception=i.content_hash in perceived,
            **perception.get(i.content_hash, {})))

    concerns = concerns_by_check(conn)
    grouped: dict[str, list[FindingOut]] = {c.value: [] for c in CheckCategory}
    attributed: Counter = Counter()
    for f in db.get_findings_for_case(conn, case_id):
        out = _finding_out(f, case, concerns)
        grouped.setdefault(out.category, []).append(out)
        if out.verdict == "concern":
            attributed[out.attributed_to] += 1

    groups = [FindingGroup(category=cat, findings=fs,
                           concern_count=sum(1 for f in fs if f.verdict == "concern"))
              for cat, fs in grouped.items()]
    decisions = db.get_decisions_for_case(conn, case_id)
    best = _best_decision(decisions)
    base = _summary_for(conn, case)

    return CaseDetail(
        **base.model_dump(),
        latitude=case.latitude, longitude=case.longitude,
        images=images, finding_groups=groups, findings_by_category=grouped,
        decision=_decision_out(best, conn) if best else None,
        decisions=[_decision_out(d, conn) for d in decisions],
        concern_counts_by_category={g.category: g.concern_count for g in groups},
        attributed_counts=dict(attributed),
        total_concerns=sum(attributed.values()),
        audit=[{"created_at": e.created_at, "event": e.event_type,
                "actor": e.details.get("admin_id", "system"), "detail": e.details}
               for e in db.get_audit_events_for_case(conn, case_id)
               if e.event_type == "admin_action"],
        processing=runtime_store.latest_job(conn, case_id),
    )


def _report_declaration(case: Case) -> ReportDeclaration:
    return ReportDeclaration(
        case_id=case.case_id,
        agent_type=case.agent_type,
        claim_type=case.claim_type,
        status=case.status,
        declared_location=case.declared_location,
        incident_date=case.declared_time,
        claim_amount=case.claim_amount,
        vehicle_registration=case.vehicle_registration,
        vehicle_make=case.vehicle_make,
        vehicle_model=case.vehicle_model,
        vehicle_variant=case.vehicle_variant,
        vehicle_year=case.vehicle_year,
        engine_number=case.engine_number,
        chassis_number=case.chassis_number,
        rto=case.rto,
        fuel_type=case.fuel_type,
        idv=case.idv,
        policy_number=case.policy_number,
        policy_type=case.policy_type,
        previous_policy_number=case.previous_policy_number,
        policy_ncb_percent=case.policy_ncb_percent,
        policy_start_date=case.policy_start_date,
        policy_end_date=case.policy_end_date,
        person_name=case.person_name,
        person_dob=case.person_dob,
        person_address=case.person_address,
        person_contact=case.person_contact,
        driving_license_number=case.driving_license_number,
        fir_number=case.fir_number,
        settlement_preference=case.settlement_preference,
        bank_account_last4=case.bank_account_last4,
    )


@app.get("/v1/cases/{case_id}/report", response_model=CaseReportOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_case_report(case_id: str,
                    _admin: str = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_conn)) -> CaseReportOut:
    case = db.get_case(conn, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")

    concerns = concerns_by_check(conn)
    grouped: dict[str, list[FindingOut]] = {c.value: [] for c in CheckCategory}
    for finding in db.get_findings_for_case(conn, case_id):
        out = _finding_out(finding, case, concerns)
        grouped.setdefault(out.category, []).append(out)
    groups = [
        FindingGroup(
            category=category,
            findings=findings,
            concern_count=sum(1 for f in findings if f.verdict == "concern"),
        )
        for category, findings in grouped.items()
    ]
    best = _best_decision(db.get_decisions_for_case(conn, case_id))
    decision = _decision_out(best, conn) if best else None
    return CaseReportOut(
        case_id=case_id,
        declaration=_report_declaration(case),
        findings_by_category=grouped,
        finding_groups=groups,
        agent_recommendation=decision,
        agent_narrative=decision.summary if decision else None,
        admin_action=_admin_action_out(db.get_latest_admin_action(conn, case_id)),
    )


@app.get("/v1/cases/{case_id}/trace", response_model=TraceOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_trace(case_id: str,
              _admin: str = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_conn)) -> TraceOut:
    """
    The ordered reasoning steps behind the decision.

    Read from the audit trail rather than a dedicated table, so the reasoning
    and the decision cannot drift apart. Provider-outage steps are withheld: a
    429 is not reasoning and a demonstration must not present it as such.
    """
    if db.get_case(conn, case_id) is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")

    type_map = {"llm_call": "reasoning", "tool_call": "tool_call",
                "decision": "conclusion", "guard": "guard",
                "parse_failure": "parse_failure", "fallback": "other"}
    steps: list[TraceStepOut] = []
    policy_version = None
    converged = None
    excluded = 0

    events = [event for event in db.get_audit_events_for_case(conn, case_id)
              if event.event_type == "case_adjudicated"]
    for event in events[-1:]:
        details = event.details or {}
        policy_version = details.get("policy_version", policy_version)
        converged = details.get("converged", converged)
        for raw in details.get("trace") or []:
            kind = str(raw.get("kind", "step"))
            detail = raw.get("detail") or ""
            if kind == "fallback" and "provider error" in detail:
                excluded += 1
                continue
            # payload is what TraceStep.to_dict() writes. An earlier version of
            # this endpoint read a "content" key no producer emits, so every
            # tool input and result was silently dropped.
            payload = raw.get("payload") or {}
            args = payload.get("args")
            steps.append(TraceStepOut(
                index=len(steps), step=raw.get("step"),
                type=type_map.get(kind, "other"), kind=kind,
                content=detail or None,
                tool_name=detail if kind == "tool_call" else None,
                tool_input=args if isinstance(args, dict) else {},
                tool_output={k: v for k, v in payload.items() if k != "args"},
                latency_ms=int(raw.get("latency_ms") or 0)))

    return TraceOut(case_id=case_id, policy_version=policy_version,
                    converged=converged, steps=steps, excluded_outage_steps=excluded)


@app.get("/v1/track", response_model=TrackOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def track_case(
    case_id: str = Query(...),
    registration_number: Optional[str] = Query(None),
    policy_number: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> TrackOut:
    if not registration_number and not policy_number:
        raise ApiError(422, "VALIDATION_FAILED",
                       "Provide registration_number or policy_number with case_id.",
                       [ErrorDetail(field="registration_number",
                                    reason="required when policy_number is absent")])
    case = db.get_case(conn, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "No matching case was found.")

    reg_ok = bool(registration_number and case.vehicle_registration
                  and registration_number.strip().lower() == case.vehicle_registration.lower())
    policy_ok = bool(policy_number and case.policy_number
                     and policy_number.strip().lower() == case.policy_number.lower())
    if not (reg_ok or policy_ok):
        raise ApiError(404, "CASE_NOT_FOUND", "No matching case was found.")

    admin_action = db.get_latest_admin_action(conn, case_id)
    narrative = "Your case has been received and is awaiting review."
    if admin_action:
        narrative = {
            "approve": "Your application has been approved by a reviewer.",
            "reject": "A reviewer has declined your application. Contact the review team for details.",
            "request_more_evidence": "The reviewer needs additional evidence. Please contact the review team.",
        }[admin_action.action.value]
        events = [e for e in db.get_audit_events_for_case(conn, case_id) if e.event_type == "admin_action"]
        if events:
            public_message = events[-1].details.get("public_message")
            if public_message:
                narrative = public_message
    return TrackOut(
        case_id=case_id,
        status=case.status,
        final_admin_action=admin_action.action.value if admin_action else None,
        narrative=narrative,
    )


@app.get("/v1/cases/{case_id}/similar", response_model=SimilarCasesOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_similar(case_id: str,
                _admin: str = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_conn)) -> SimilarCasesOut:
    case = db.get_case(conn, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")

    arche = archetypes()
    found: dict[str, SimilarCase] = {}

    hashes = [i.content_hash for i in db.get_images_for_case(conn, case_id) if i.content_hash]
    if hashes:
        marks = ",".join("?" * len(hashes))
        for other, content_hash in conn.execute(
            f"SELECT case_id, content_hash FROM images WHERE content_hash IN ({marks}) "
            f"AND case_id != ?", (*hashes, case_id)
        ):
            found[other] = SimilarCase(
                case_id=other, shared_via="image", shared_value=content_hash,
                detail="An identical image appears in both cases.")

    for field, via in (("claimant_id", "claimant"), ("garage_id", "garage"),
                       ("vehicle_registration", "vehicle_registration")):
        value = getattr(case, field, None)
        if not value:
            continue
        for (other,) in conn.execute(
            f"SELECT case_id FROM cases WHERE {field} = ? AND case_id != ? LIMIT 50",
            (value, case_id)
        ):
            if other not in found:
                found[other] = SimilarCase(
                    case_id=other, shared_via=via, shared_value=str(value),
                    detail=f"Both cases share {field.replace('_', ' ')} {value}.")

    for item in found.values():
        item.archetype = arche.get(item.case_id)
        best = _best_decision(db.get_decisions_for_case(conn, item.case_id))
        item.risk_band = best.risk_band.value if best and getattr(best, "risk_band", None) else None

    return SimilarCasesOut(case_id=case_id, items=list(found.values()))


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def _thumbnail(path: str, image_id: str) -> Optional[Path]:
    """Generate on first request, cache to disk. The queue asks for dozens at once."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    out = THUMB_DIR / f"{image_id}.jpg"
    if out.exists():
        return out
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            im = im.convert("RGB")
            if im.width > THUMB_WIDTH:
                ratio = THUMB_WIDTH / im.width
                im = im.resize((THUMB_WIDTH, max(1, int(im.height * ratio))))
            im.save(out, "JPEG", quality=82)
        return out
    except Exception:  # noqa: BLE001
        return None


@app.get("/v1/images/{image_id}", tags=["images"], response_class=FileResponse,
         responses={200: {"content": {"image/jpeg": {}}}, 404: {"model": ErrorResponse}})
def get_image(image_id: str,
              thumb: int = Query(0, description="1 for a 400px-wide cached version."),
              _admin: str = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    image = db.get_image(conn, image_id)
    if image is None:
        raise ApiError(404, "IMAGE_NOT_FOUND", f"No image with id {image_id!r}.")
    path = _resolve_data_path(getattr(image, "path", None))
    if path is None or not path.exists():
        # The row exists and the file does not. That is a genuinely absent
        # resource, not a broken server.
        raise ApiError(404, "IMAGE_FILE_MISSING",
                       f"The file for image {image_id!r} is not on disk.")

    served = str(path)
    media_type = mimetypes.guess_type(served)[0] or "application/octet-stream"
    if thumb:
        generated = _thumbnail(served, image_id)
        if generated is not None:
            served, media_type = str(generated), "image/jpeg"

    etag = hashlib.sha256(f"{image.content_hash or image_id}:{thumb}".encode()).hexdigest()[:32]
    return FileResponse(served, media_type=media_type, headers={
        "ETag": f'"{etag}"', "Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------------------
# Checks, garages, policies, stats, health
# ---------------------------------------------------------------------------

def _check_meta(check: Any, concerns: dict[str, int]) -> CheckMeta:
    m = measurements().get(check.check_id, {})
    fired = concerns.get(check.check_id, 0)
    return CheckMeta(
        check_id=check.check_id, category=check.category.value, scope=check.scope,
        weight=check.weight, requires_perception=check.requires_perception,
        target_archetypes=list(check.target_archetypes),
        attributed_to=getattr(check, "attributed_to", "claimant"),
        status=_check_status(check, fired),
        measured_recall=m.get("recall"), measured_fp_rate=m.get("fp_rate"),
        marginal_recall_contribution=m.get("marginal_recall"),
        marginal_fp_contribution=m.get("marginal_fp"),
        concerns_fired=fired,
        limitation=(getattr(check, "limitation", "") or None))


@app.get("/v1/checks", response_model=list[CheckMeta], tags=["config"])
def list_checks(_admin: str = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_conn)) -> list[CheckMeta]:
    from src.checks import REGISTRY

    concerns = concerns_by_check(conn)
    return [_check_meta(REGISTRY[k], concerns) for k in sorted(REGISTRY)]


@app.get("/v1/checks/{check_id}", response_model=CheckDetail, tags=["config"],
         responses={404: {"model": ErrorResponse}})
def get_check(check_id: str,
              _admin: str = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_conn)) -> CheckDetail:
    from src.checks import REGISTRY

    check = REGISTRY.get(check_id)
    if check is None:
        raise ApiError(404, "CHECK_NOT_FOUND", f"No check with id {check_id!r}.")
    base = _check_meta(check, concerns_by_check(conn))
    artefacts = [str(p) for p in (
        Path("outputs/check_performance_v2.md"),
        Path("outputs/marginal_contribution.md"),
        Path(f"outputs/{check_id}_measurement.json"),
    ) if p.exists()]
    # Most checks put their reasoning in the module docstring rather than on
    # the class, so a class-only lookup returned nothing for them.
    import inspect
    description = (type(check).__doc__ or "").strip()
    if not description:
        module = inspect.getmodule(type(check))
        description = ((module.__doc__ or "").strip() if module else "")
    return CheckDetail(**base.model_dump(),
                       description=description or None,
                       measurement_history=artefacts)


@app.get("/v1/garages/{garage_id}", response_model=GarageSummary, tags=["entities"],
         responses={404: {"model": ErrorResponse}})
def get_garage(garage_id: str,
               _admin: str = Depends(require_admin),
               conn: sqlite3.Connection = Depends(get_conn)) -> GarageSummary:
    """
    A garage's claim-value distribution.

    Exists because `threshold_gaming` is garage-scoped: its finding describes
    the repairer's billing pattern, and a UI needs somewhere to show that
    rather than rendering it beside a claimant's name.
    """
    rows = conn.execute(
        "SELECT case_id, claim_amount FROM cases WHERE garage_id = ?", (garage_id,)).fetchall()
    if not rows:
        raise ApiError(404, "GARAGE_NOT_FOUND", f"No cases for garage {garage_id!r}.")

    amounts = sorted(a for _c, a in rows if a is not None)
    below = [a for a in amounts if a < SURVEY_THRESHOLD_INR]
    all_amounts = [r[0] for r in conn.execute(
        "SELECT claim_amount FROM cases WHERE claim_amount IS NOT NULL")]
    population_below = ((sum(1 for a in all_amounts if a < SURVEY_THRESHOLD_INR)
                         / len(all_amounts) * 100) if all_amounts else None)

    buckets: Counter = Counter()
    for a in amounts:
        buckets[int(a // 10_000) * 10_000] += 1
    histogram = [{"lower_inr": k, "upper_inr": k + 10_000, "count": v}
                 for k, v in sorted(buckets.items())]

    case_ids = [c for c, _a in rows]
    concern_count = 0
    if case_ids:
        marks = ",".join("?" * len(case_ids))
        concern_count = conn.execute(
            f"SELECT COUNT(*) FROM findings WHERE verdict = 'concern' "
            f"AND case_id IN ({marks})", case_ids).fetchone()[0]

    return GarageSummary(
        garage_id=garage_id, case_count=len(rows), total_claimed_inr=float(sum(amounts)),
        mean_claim_inr=(sum(amounts) / len(amounts)) if amounts else None,
        median_claim_inr=(amounts[len(amounts) // 2] if amounts else None),
        below_threshold_count=len(below),
        below_threshold_pct=(len(below) / len(amounts) * 100) if amounts else None,
        population_below_threshold_pct=population_below,
        claim_value_histogram=histogram,
        linked_case_ids=case_ids[:200], concern_count=concern_count)


class FindingCount(BaseModel):
    name: str
    verdict: str
    count: int


class FindingCountsOut(BaseModel):
    counts: list[FindingCount]


@app.get("/v1/finding-counts", response_model=FindingCountsOut, tags=["stats"])
def finding_counts(_admin: str = Depends(require_admin), conn: sqlite3.Connection = Depends(get_conn)):
    return FindingCountsOut(counts=[FindingCount(name=r[0], verdict=r[1], count=r[2])
        for r in conn.execute("SELECT check_id, verdict, COUNT(*) FROM findings GROUP BY check_id, verdict")])


@app.get("/v1/stats", response_model=StatsOut, tags=["dashboard"])
def get_stats(_admin: str = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_conn)) -> StatsOut:
    from src.checks import REGISTRY

    def counts(sql: str) -> dict[str, int]:
        return {str(k): int(v) for k, v in conn.execute(sql) if k is not None}

    total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    latest_decisions = """SELECT d.* FROM agent_decisions d WHERE d.rowid = (
        SELECT latest.rowid FROM agent_decisions latest WHERE latest.case_id = d.case_id
        ORDER BY latest.created_at DESC, latest.rowid DESC LIMIT 1)"""
    by_band = counts(f"SELECT risk_band, COUNT(*) FROM ({latest_decisions}) GROUP BY risk_band")
    decided = conn.execute("SELECT COUNT(DISTINCT case_id) FROM agent_decisions").fetchone()[0]
    concerns = concerns_by_check(conn)

    by_attribution: Counter = Counter()
    for check_id, n in concerns.items():
        check = REGISTRY.get(check_id)
        by_attribution[getattr(check, "attributed_to", "claimant") if check else "claimant"] += n

    arms: list[ArmSummary] = []
    results = Path("outputs/ablation_results.jsonl")
    if results.exists():
        rows_by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line in results.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows_by_arm[r.get("arm", "?")].append(r)
        for arm, rows in sorted(rows_by_arm.items()):
            fraud = [r for r in rows if r.get("is_fraud")]
            clean = [r for r in rows if not r.get("is_fraud")]
            arms.append(ArmSummary(
                arm=arm, cases=len(rows),
                fraud_caught=(f"{sum(1 for r in fraud if r['risk_band'] != 'clear')}/{len(fraud)}"
                              if fraud else None),
                clean_flagged=(f"{sum(1 for r in clean if r['risk_band'] != 'clear')}/{len(clean)}"
                               if clean else None),
                mean_llm_calls=round(sum(r.get("llm_calls", 0) for r in rows) / len(rows), 2),
                mean_tool_calls=round(sum(r.get("tool_calls", 0) for r in rows) / len(rows), 2),
                mean_latency_s=round(sum(r.get("latency_ms", 0) for r in rows) / len(rows) / 1000, 1)))

    return StatsOut(
        total_cases=total_cases,
        by_agent_type=counts("SELECT agent_type, COUNT(*) FROM cases GROUP BY agent_type"),
        by_status=counts("SELECT status, COUNT(*) FROM cases GROUP BY status"),
        by_risk_band=by_band,
        by_recommendation=counts(f"SELECT recommendation, COUNT(*) FROM ({latest_decisions}) GROUP BY recommendation"),
        decided_cases=decided, undecided_cases=max(0, total_cases - decided),
        total_findings=conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0],
        concern_findings=sum(concerns.values()),
        concerns_by_check=concerns, concerns_by_attribution=dict(by_attribution),
        images=conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        images_with_perception=conn.execute(
            "SELECT COUNT(*) FROM perception_records").fetchone()[0],
        straight_through_rate=(by_band.get("clear", 0) / decided) if decided else None,
        ablation_arms=arms)


@app.get("/v1/policies", response_model=list[PolicyOut], tags=["config"])
def get_policies(_admin: str = Depends(require_admin)) -> list[PolicyOut]:
    out = []
    for agent_type, p in (("claims", CLAIMS_POLICY), ("underwriting", UNDERWRITING_POLICY)):
        bias = next((l.strip() for l in p.system_prompt.splitlines()
                     if l.strip().startswith("Bias:")), None)
        out.append(PolicyOut(
            policy_version=p.policy_version, agent_type=agent_type,
            check_ids=list(p.check_ids), tool_names=list(p.tool_names),
            max_iterations=p.max_iterations, max_tool_calls=p.max_tool_calls,
            bias=bias, system_prompt=p.system_prompt))
    return out


def _background_status(log_path: str) -> str:
    path = Path(log_path)
    if not path.exists():
        return "not_observed"
    age = time.time() - path.stat().st_mtime
    if age < 20 * 60:
        return "recent_activity"
    if age < 3 * 3600:
        return "idle_or_sleeping"
    return "stale"


def _provider_health(provider_configured: bool) -> tuple[Optional[bool], str, Optional[datetime]]:
    if not provider_configured:
        return None, "not_configured", None
    now = time.monotonic()
    if now - float(_HEALTH_GEMINI_CACHE.get("checked_at") or 0.0) < HEALTH_GEMINI_TTL_SECONDS:
        checked = _HEALTH_GEMINI_CACHE.get("checked_datetime")
        return (
            _HEALTH_GEMINI_CACHE.get("reachable"),
            str(_HEALTH_GEMINI_CACHE.get("status") or "unknown"),
            checked if isinstance(checked, datetime) else None,
        )
    checked_at = datetime.now(timezone.utc)
    previous_consumer = os.environ.get("GEMINI_QUOTA_CONSUMER")
    os.environ["GEMINI_QUOTA_CONSUMER"] = "health"
    try:
        from src.llm import GeminiProvider, _to_gemini_contents, is_rate_limit_error, is_unavailable_error
        provider = GeminiProvider()
        messages = [{"role": "user", "content": "Reply with exactly: ready"}]
        response = provider._call_rotating(
            lambda client: client.models.generate_content(
                model=provider.model,
                contents=_to_gemini_contents(messages),
            ),
            attempts=1,
        )
        text = getattr(response, "text", "").strip().lower()
        reachable = text == "ready" or bool(text)
        status = "ok" if reachable else "empty_response"
    except Exception as exc:  # noqa: BLE001
        reachable = False
        if "QuotaBudgetExhausted" in type(exc).__name__:
            status = "local_quota_budget_exhausted"
        elif "is_rate_limit_error" in locals() and is_rate_limit_error(exc):
            status = "rate_limited"
        elif "is_unavailable_error" in locals() and is_unavailable_error(exc):
            status = "gemini_503_unavailable"
        else:
            status = f"{type(exc).__name__}: {str(exc)[:180]}"
    finally:
        if previous_consumer is None:
            os.environ.pop("GEMINI_QUOTA_CONSUMER", None)
        else:
            os.environ["GEMINI_QUOTA_CONSUMER"] = previous_consumer
    _HEALTH_GEMINI_CACHE.update({
        "checked_at": now,
        "checked_datetime": checked_at,
        "reachable": reachable,
        "status": status,
    })
    return reachable, status, checked_at


class ReadyOut(BaseModel):
    status: str


@app.get("/ready", response_model=ReadyOut, tags=["config"])
def ready() -> ReadyOut:
    try:
        with runtime_store.connection(DB_PATH) as conn:
            conn.execute("SELECT 1 FROM cases LIMIT 1")
    except sqlite3.Error as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "Database is unavailable.") from exc
    return ReadyOut(status="ok")


@app.get("/health", response_model=HealthOut, tags=["config"])
@app.get("/v1/health", response_model=HealthOut, tags=["config"])
def health() -> HealthOut:
    reachable, cases, perception_records, image_records = True, 0, 0, 0
    try:
        conn = db.connect(DB_PATH)
        cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        perception_records = conn.execute("SELECT COUNT(*) FROM perception_records").fetchone()[0]
        image_records = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        conn.close()
    except Exception:  # noqa: BLE001
        reachable = False

    provider_configured = any(os.environ.get(k) for k in
                              ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GOOGLE_API_KEY"))
    provider_reachable, provider_status, provider_checked_at = _provider_health(provider_configured)
    verified_agent_cases = 0
    total = 0
    try:
        from scripts.drive_ablation import total_cases, verify_agent_integrity
        integrity = verify_agent_integrity(DB_PATH)
        verified_agent_cases = integrity.verified
        total = total_cases()
    except Exception:  # noqa: BLE001
        total = 0

    jobs = Counter(str(job.get("status", "unknown")) for job in _JOBS.values())
    degraded = (
        not reachable
        or (provider_configured and provider_reachable is False)
    )

    return HealthOut(
        status="degraded" if degraded else "ok",
        database=DB_PATH, database_reachable=reachable, cases=cases,
        provider_configured=provider_configured,
        provider_reachable=provider_reachable,
        provider_status=provider_status,
        provider_checked_at=provider_checked_at,
        quota_remaining_estimate=None,
        ablation_verified_agent_cases=verified_agent_cases,
        ablation_total_cases=total,
        ablation_complete=bool(total and verified_agent_cases >= total),
        ablation_driver_status=_background_status("outputs/.drive_ablation.session.log"),
        perception_records=perception_records,
        image_records=image_records,
        active_api_jobs=dict(jobs),
    )


# ---------------------------------------------------------------------------
# Submission, reprocessing, adjuster action
# ---------------------------------------------------------------------------

def _set_job(job_id: str, **fields: Any) -> None:
    with runtime_store.connection(DB_PATH) as conn:
        job = runtime_store.get_job(conn, job_id) or {"job_id": job_id}
        job.update(fields)
        runtime_store.save_job(conn, job)
    _JOBS[job_id] = job


def _run_pipeline(job_id: str, case_id: str) -> None:
    """
    Checks and adjudication for one case.

    When the provider is unreachable the orchestrator's documented fallback
    applies, and the job records `provider_unavailable` so the interface can
    say the band came from an outage rather than from the agent's judgement.
    Submission never fails for want of quota.
    """
    _set_job(job_id, status="running", stage="checks", progress=0.3, case_id=case_id)
    try:
        from src.orchestrator import process_case
        conn = db.connect(DB_PATH)
        try:
            from src.llm import get_provider
            from src.perception import perceive_image
            provider = get_provider()
            images = db.get_images_for_case(conn, case_id)
            if not images:
                raise ValueError("No indexed evidence is available for analysis")
            perception_errors = 0
            for index, image in enumerate(images):
                _set_job(job_id, stage="perception", progress=0.1 + 0.4 * index / len(images))
                try:
                    perceive_image(conn, image, provider)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    perception_errors += 1
                    access_log.exception("Perception failed for image %s", image.image_id)
            _set_job(job_id, stage="checks_and_adjudication", progress=0.6)
            decision = process_case(conn, case_id, provider=provider)
            unavailable = _decision_out(decision, conn).provider_unavailable
            if perception_errors:
                db.log_audit_event(conn, AuditEvent(event_type="perception_incomplete", case_id=case_id,
                    details={"failed_images": perception_errors, "total_images": len(images)}))
                conn.commit()
        finally:
            conn.close()
        _set_job(job_id, status="done", stage="complete", progress=1.0,
                 provider_unavailable=unavailable,
                 detail=("Automated adjudication did not converge. This decision is the documented "
                         "fallback rather than the agent's judgement."
                         if unavailable else
                         f"Vision analysis was unavailable for {perception_errors} image(s). Review check limitations."
                         if perception_errors else None))
    except Exception as e:  # noqa: BLE001
        access_log.exception("Analysis failed for case %s", case_id)
        _set_job(job_id, status="failed", stage="failed", progress=1.0,
                 detail="Automated analysis could not complete. Your evidence is saved. A reviewer can retry analysis.")


def _build_case(case_id: str, agent_type: str, claim_type: Optional[str],
                declared_location: Optional[str], declared_time: Optional[datetime],
                claim_amount: Optional[float], vehicle_registration: Optional[str],
                claimant_id: Optional[str], garage_id: Optional[str],
                latitude: Optional[float], longitude: Optional[float],
                vehicle_make: Optional[str] = None, vehicle_model: Optional[str] = None,
                vehicle_variant: Optional[str] = None, vehicle_year: Optional[int] = None,
                engine_number: Optional[str] = None, chassis_number: Optional[str] = None,
                rto: Optional[str] = None, fuel_type: Optional[str] = None,
                idv: Optional[float] = None, policy_number: Optional[str] = None,
                policy_type: Optional[str] = None, previous_policy_number: Optional[str] = None,
                policy_ncb_percent: Optional[float] = None,
                policy_start_date: Optional[date] = None, policy_end_date: Optional[date] = None,
                person_name: Optional[str] = None, person_dob: Optional[date] = None,
                person_address: Optional[str] = None, person_contact: Optional[str] = None,
                driving_license_number: Optional[str] = None, fir_number: Optional[str] = None,
                settlement_preference: Optional[str] = None,
                bank_account_last4: Optional[str] = None) -> Case:
    return Case(
        case_id=case_id,
        claimant_id=claimant_id or f"CLM-{uuid.uuid4().hex[:8]}",
        # Case requires a non-blank garage_id. An intake that does not yet know
        # the repairer is ordinary, so record it explicitly as unassigned.
        garage_id=garage_id or "UNASSIGNED",
        claim_type=claim_type or ("underwriting_inspection" if agent_type == "underwriting"
                                  else "motor_claim"),
        declared_time=declared_time or datetime.now(timezone.utc),
        declared_location=declared_location, latitude=latitude, longitude=longitude,
        agent_type=agent_type, claim_amount=claim_amount,
        vehicle_registration=vehicle_registration, status="open",
        vehicle_make=vehicle_make, vehicle_model=vehicle_model,
        vehicle_variant=vehicle_variant, vehicle_year=vehicle_year,
        engine_number=engine_number, chassis_number=chassis_number,
        rto=rto, fuel_type=fuel_type, idv=idv,
        policy_number=policy_number, policy_type=policy_type,
        previous_policy_number=previous_policy_number,
        policy_ncb_percent=policy_ncb_percent,
        policy_start_date=policy_start_date, policy_end_date=policy_end_date,
        person_name=person_name, person_dob=person_dob,
        person_address=person_address, person_contact=person_contact,
        driving_license_number=driving_license_number,
        fir_number=fir_number, settlement_preference=settlement_preference,
        bank_account_last4=bank_account_last4)


@app.post("/v1/cases", response_model=SubmitCaseOut, status_code=201, tags=["cases"],
          responses={422: {"model": ErrorResponse}})
def submit_case(
    background: BackgroundTasks,
    agent_type: str = Form("claims"),
    claim_type: Optional[str] = Form(None),
    declared_location: Optional[str] = Form(None),
    declared_time: Optional[datetime] = Form(None),
    claim_amount: Optional[float] = Form(None),
    vehicle_registration: Optional[str] = Form(None),
    vehicle_make: Optional[str] = Form(None),
    vehicle_model: Optional[str] = Form(None),
    vehicle_variant: Optional[str] = Form(None),
    vehicle_year: Optional[int] = Form(None),
    engine_number: Optional[str] = Form(None),
    chassis_number: Optional[str] = Form(None),
    rto: Optional[str] = Form(None),
    fuel_type: Optional[str] = Form(None),
    idv: Optional[float] = Form(None),
    policy_number: Optional[str] = Form(None),
    policy_type: Optional[str] = Form(None),
    previous_policy_number: Optional[str] = Form(None),
    policy_ncb_percent: Optional[float] = Form(None),
    policy_start_date: Optional[date] = Form(None),
    policy_end_date: Optional[date] = Form(None),
    person_name: Optional[str] = Form(None),
    person_dob: Optional[date] = Form(None),
    person_address: Optional[str] = Form(None),
    person_contact: Optional[str] = Form(None),
    driving_license_number: Optional[str] = Form(None),
    fir_number: Optional[str] = Form(None),
    settlement_preference: Optional[str] = Form(None),
    bank_account_last4: Optional[str] = Form(None),
    claimant_id: Optional[str] = Form(None),
    garage_id: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    images: Optional[list[UploadFile]] = File(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> SubmitCaseOut:
    if agent_type not in ("claims", "underwriting"):
        raise ApiError(422, "VALIDATION_FAILED",
                       "agent_type must be 'claims' or 'underwriting'.",
                       [ErrorDetail(field="agent_type", reason=f"got {agent_type!r}")])

    if len(images or []) > 12:
        raise ApiError(422, "TOO_MANY_IMAGES", "Upload at most 12 photographs.")
    with tempfile.TemporaryDirectory(prefix="fraudlens_upload_gate_") as tmp:
        tmp_dir = Path(tmp)
        staged: list[tuple[Path, str]] = []
        for upload in images or []:
            if not upload.filename:
                continue
            safe_name = Path(upload.filename).name
            target = tmp_dir / f"{uuid.uuid4().hex}_{safe_name}"
            # Sync read: this endpoint is deliberately not async, so the
            # request's sqlite connection stays on one thread.
            content = upload.file.read(5 * 1024 * 1024 + 1)
            if not content or len(content) > 5 * 1024 * 1024:
                raise ApiError(422, "INVALID_IMAGE_SIZE", "Each photograph must be nonempty and at most 5 MB.")
            target.write_bytes(content)
            try:
                from PIL import Image as PILImage
                with PILImage.open(target) as picture:
                    if picture.format not in {"JPEG", "PNG", "WEBP"} or picture.width * picture.height > 25_000_000:
                        raise ValueError("unsupported image format or dimensions")
                    picture.verify()
            except Exception as exc:
                raise ApiError(422, "INVALID_IMAGE", "Upload valid JPEG, PNG or WebP photographs up to 25 megapixels.") from exc
            staged.append((target, safe_name))

        if not staged:
            raise ApiError(422, "VEHICLE_IMAGE_REQUIRED",
                           "At least one vehicle image must be uploaded before a case can be created.",
                           [ErrorDetail(field="images", reason="no uploaded image files")])

        from src import vehicle_gate

        try:
            scores = vehicle_gate.classify_uploads(
                [path for path, _name in staged],
                [name for _path, name in staged],
            )
        except Exception as first_error:  # noqa: BLE001 - retry once, then report and move on
            try:
                scores = vehicle_gate.classify_uploads(
                    [path for path, _name in staged],
                    [name for _path, name in staged],
                )
            except Exception as second_error:  # noqa: BLE001
                raise ApiError(
                    422,
                    "VEHICLE_IMAGE_VALIDATION_FAILED",
                    f"Could not validate the uploaded images as vehicle photos: {type(second_error).__name__}.",
                    [ErrorDetail(field="images",
                                 reason=f"first attempt {type(first_error).__name__}; retry {type(second_error).__name__}")],
                ) from second_error

        if not any(score.accepted for score in scores):
            best = max(scores, key=lambda s: s.margin)
            raise ApiError(
                422,
                "VEHICLE_IMAGE_REQUIRED",
                "Upload at least one image that clearly shows a vehicle.",
                [ErrorDetail(
                    field="images",
                    reason=(f"best vehicle margin {best.margin:.3f} is below "
                            f"floor {vehicle_gate.VEHICLE_MARGIN_FLOOR:.3f} or vehicle score "
                            f"{best.vehicle_score:.3f} is below threshold "
                            f"{vehicle_gate.VEHICLE_SCORE_THRESHOLD:.3f}"),
                )],
            )

        case_id = f"case-{uuid.uuid4().hex[:12]}"
        job_id = uuid.uuid4().hex
        try:
            case = _build_case(
                case_id, agent_type, claim_type, declared_location,
                declared_time, claim_amount, vehicle_registration,
                claimant_id, garage_id, latitude, longitude,
                vehicle_make=vehicle_make, vehicle_model=vehicle_model,
                vehicle_variant=vehicle_variant, vehicle_year=vehicle_year,
                engine_number=engine_number, chassis_number=chassis_number,
                rto=rto, fuel_type=fuel_type, idv=idv,
                policy_number=policy_number, policy_type=policy_type,
                previous_policy_number=previous_policy_number,
                policy_ncb_percent=policy_ncb_percent,
                policy_start_date=policy_start_date, policy_end_date=policy_end_date,
                person_name=person_name, person_dob=person_dob,
                person_address=person_address, person_contact=person_contact,
                driving_license_number=driving_license_number,
                fir_number=fir_number, settlement_preference=settlement_preference,
                bank_account_last4=bank_account_last4,
            )
        except ValueError as e:
            # models.Case is the authority on validity; surface its complaint as a
            # 422 rather than letting it become a 500.
            raise ApiError(422, "VALIDATION_FAILED", str(e)) from e

        db.insert_case(conn, case)
        db.log_audit_event(conn, AuditEvent(
            event_type="vehicle_image_gate",
            case_id=case_id,
            details={"vehicle_score_threshold": vehicle_gate.VEHICLE_SCORE_THRESHOLD,
                     "margin_floor": vehicle_gate.VEHICLE_MARGIN_FLOOR,
                     "scores": [score.to_dict() for score in scores]},
        ))

        upload_dir = UPLOAD_DIR / case_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for source, original_name in staged:
            target = upload_dir / f"{uuid.uuid4().hex}_{original_name}"
            shutil.copyfile(source, target)
            paths.append(str(target))

        saved = 0
        try:
            from src import ingest
            for path in paths:
                ingest.ingest_image(conn, case_id, path)
                saved += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            shutil.rmtree(upload_dir, ignore_errors=True)
            access_log.exception("Evidence ingestion failed for %s", case_id)
            raise ApiError(503, "EVIDENCE_INGEST_FAILED",
                           "Evidence could not be indexed. No case was accepted; please retry.") from exc

    _set_job(job_id, status="queued", stage="queued", progress=0.0, case_id=case_id)
    background.add_task(_run_pipeline, job_id, case_id)
    return SubmitCaseOut(case_id=case_id, job_id=job_id, status="queued",
                         images_received=saved)


@app.post("/v1/cases/{case_id}/reprocess", response_model=SubmitCaseOut, tags=["cases"],
          responses={404: {"model": ErrorResponse}})
def reprocess_case(case_id: str, background: BackgroundTasks,
                   _admin: str = Depends(require_admin),
                   conn: sqlite3.Connection = Depends(get_conn)) -> SubmitCaseOut:
    if db.get_case(conn, case_id) is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")
    active = runtime_store.latest_job(conn, case_id)
    if active and active.get("status") in {"queued", "running"}:
        raise ApiError(409, "ANALYSIS_RUNNING", "Analysis is already queued or running.")
    job_id = uuid.uuid4().hex
    _set_job(job_id, status="queued", stage="queued", progress=0.0, case_id=case_id)
    background.add_task(_run_pipeline, job_id, case_id)
    images = conn.execute("SELECT COUNT(*) FROM images WHERE case_id = ?",
                          (case_id,)).fetchone()[0]
    return SubmitCaseOut(case_id=case_id, job_id=job_id, status="queued",
                         images_received=images)


@app.get("/v1/jobs/{job_id}", response_model=JobOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_job(job_id: str) -> JobOut:
    with runtime_store.connection(DB_PATH) as conn:
        job = runtime_store.get_job(conn, job_id)
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", f"No job with id {job_id!r}.")
    return JobOut(**{k: v for k, v in job.items() if k in JobOut.model_fields})


@app.post("/v1/cases/{case_id}/action", response_model=ActionOut, tags=["cases"],
          responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def record_action(case_id: str, payload: ActionIn,
                  _admin: str = Depends(require_admin),
                  conn: sqlite3.Connection = Depends(get_conn)) -> ActionOut:
    """
    Record what a human admin decided.

    This vocabulary is intentionally not Recommendation. The agent still has no
    rejection member; the human admin action enum does.
    """
    case = db.get_case(conn, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", f"No case with id {case_id!r}.")

    if payload.action in (AdminAction.REJECT, AdminAction.REQUEST_MORE_EVIDENCE) and not (payload.reason or "").strip():
        raise ApiError(422, "VALIDATION_FAILED",
                       "A reason is required for rejection or an evidence request.",
                       [ErrorDetail(field="reason", reason="required for REJECT")])

    status = {
        AdminAction.APPROVE: "closed_approved",
        AdminAction.REJECT: "closed_rejected",
        AdminAction.REQUEST_MORE_EVIDENCE: "open",
    }[payload.action]
    now = datetime.now(timezone.utc)
    record = AdminActionRecord(
        case_id=case_id,
        admin_id=_admin,
        action=payload.action,
        reason=payload.reason,
        timestamp=now,
    )
    db.insert_admin_action(conn, record)
    conn.execute("UPDATE cases SET status = ? WHERE case_id = ?", (status, case_id))
    db.log_audit_event(conn, AuditEvent(
        event_type="admin_action", case_id=case_id,
        details={"action": payload.action.value, "reason": payload.reason,
                 "admin_id": _admin,
                 "requested_artifacts": payload.requested_artifacts,
                 "public_message": payload.public_message,
                 "previous_status": case.status}))
    conn.commit()
    return ActionOut(case_id=case_id, action=payload.action.value, status=status,
                     reason=payload.reason, admin_id=_admin, recorded_at=now)
