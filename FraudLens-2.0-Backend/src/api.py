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

from src import db, runtime_store, customer_auth
from src.timing import measured, span
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
DB_PATH = db.configured_target()
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

# Preserved research billing benchmark. Current regulatory applicability and
# insurer procedures have not been established by this software verification.
SURVEY_THRESHOLD_INR = 50_000.0

@asynccontextmanager
async def lifespan(_app):
    if DB_PATH == 'postgresql' and os.environ.get('FRAUDLENS_WORKER_ENABLED','1') == '1':
        ledger = os.environ.get('FRAUDLENS_LIVE_LEDGER')
        if not ledger or not Path(ledger).is_file():
            raise RuntimeError('PostgreSQL pilot workers require the preserved FRAUDLENS_LIVE_LEDGER. Use scripts/start_pilot.ps1; never reset the existing provider stop.')
    if DB_PATH != 'postgresql':
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(DB_PATH)
    try:
        db.init_db(conn)
        if not db.is_postgres(conn):
            conn.execute('PRAGMA journal_mode=WAL')
        runtime_store.init(conn)
        conn.commit()
    finally:
        conn.close()
    if os.environ.get('FRAUDLENS_WARM_MODELS') == '1':
        from src.ingest import _default_embedder
        from src.vehicle_gate import _text_embeddings
        with span('startup.admission_warmup'):
            _default_embedder._ensure_loaded()
            _text_embeddings(_default_embedder)
    from src.durable_worker import DurableWorker
    worker = DurableWorker(DB_PATH, _run_pipeline)
    _app.state.worker = worker
    if os.environ.get('FRAUDLENS_WORKER_ENABLED', '1') == '1':
        worker.start()
    try:
        yield
    finally:
        worker.stop()


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
    allow_headers=['Content-Type','Authorization','X-Admin-Password','X-Applicant-Token','Idempotency-Key'],
    expose_headers=["ETag", "Content-Length"],
)

_JOBS: dict[str, dict[str, Any]] = {}
_ARCHETYPES: Optional[dict[str, str]] = None
_MEASUREMENTS: Optional[dict[str, dict[str, Any]]] = None
_RATE_LIMITS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_HEALTH_GEMINI_CACHE: dict[str, Any] = {"checked_at": 0.0, "reachable": None, "status": "unknown"}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "") if os.environ.get('FRAUDLENS_TRUST_PROXY') == '1' else ''
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request) -> tuple[Optional[str], int]:
    if request.method == "POST" and request.url.path in {"/v1/auth/login", "/v1/customer/auth/login", "/v1/customer/auth/register"}:
        return "login", 5
    if request.method == "POST" and (request.url.path == "/v1/cases" or request.url.path.endswith('/evidence')):
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
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if request.url.path.startswith('/v1/'):
        response.headers['Cache-Control'] = 'no-store'
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
    if isinstance(exc, db.DatabaseError):
        access_log.error('Database operation unavailable: error_type=%s',type(exc).__name__)
        return error(503,'DATABASE_UNAVAILABLE','The database is temporarily unavailable. Keep your submission key and retry; previously accepted evidence is preserved.')
    return error(500, "INTERNAL_ERROR",
                 f"An unexpected error occurred: {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def require_admin(request: Request, authorization: Optional[str] = Header(default=None),
                  x_admin_password: Optional[str] = Header(default=None)) -> str:
    expected = os.environ.get('ADMIN_PASSWORD_SHA256', '').strip().lower()
    service = os.environ.get('EVIDENCE_SERVICE_TOKEN', '').strip()
    scheme, _, value = (authorization or '').partition(' ')
    credential = value.strip() if scheme.lower() == 'bearer' else ''
    if not credential and os.environ.get('FRAUDLENS_ALLOW_LEGACY_AUTH') == '1':
        credential = x_admin_password or ''
    if not credential:
        raise ApiError(401, 'UNAUTHORISED', 'Reviewer authentication is required.')
    if service and hmac.compare_digest(credential, service):
        request.state.admin_actor, request.state.role = 'service', 'service'
        return 'service'
    with runtime_store.connection(DB_PATH) as conn:
        record = runtime_store.session_record(conn, credential, expected)
        if record and not conn.execute('SELECT 1 FROM reviewer_accounts WHERE email=?',(record['actor'],)).fetchone() and record['actor'].lower()!=os.environ.get('ADMIN_EMAIL','').strip().lower():
            record=None
    if record:
        request.state.admin_actor, request.state.role = record['actor'], record['role']
        request.state.expires_at = record['expires_at']
        return record['actor']
    if os.environ.get('FRAUDLENS_ALLOW_LEGACY_AUTH') == '1' and expected and hmac.compare_digest(runtime_store.digest(credential), expected):
        actor = os.environ.get('ADMIN_EMAIL', 'admin')
        request.state.admin_actor, request.state.role = actor, 'admin'
        return actor
    raise ApiError(401, 'UNAUTHORISED', 'Reviewer session is invalid or expired.')


def require_reviewer(request: Request, actor: str = Depends(require_admin)) -> str:
    if request.state.role not in ('admin', 'reviewer', 'service'):
        raise ApiError(403, 'FORBIDDEN', 'This account has read-only access.')
    return actor


def require_owner(request: Request, actor: str = Depends(require_admin)) -> str:
    if request.state.role != 'admin':
        raise ApiError(403, 'FORBIDDEN', 'An administrator account is required.')
    return actor


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class SessionOut(BaseModel):
    user: str
    role: str = 'admin'
    organization_id: str = 'local'
    token: Optional[str] = None
    expires_at: Optional[float] = None


class LogoutOut(BaseModel):
    ok: bool


@app.post("/v1/auth/login", response_model=SessionOut, tags=["auth"])
def login(payload: LoginIn) -> SessionOut:
    email = payload.email.strip().lower()
    actor = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    expected = os.environ.get('ADMIN_PASSWORD_SHA256', '').strip().lower()
    with runtime_store.connection(DB_PATH) as conn:
        account = conn.execute('SELECT * FROM reviewer_accounts WHERE email=?', (email,)).fetchone()
        valid = bool(account and account['enabled'] and runtime_store.password_matches(payload.password, account['password_hash']))
        if account:
            actor, expected, role = email, account['password_hash'], account['role']
        else:
            valid = bool(actor and expected and hmac.compare_digest(email, actor) and hmac.compare_digest(runtime_store.digest(payload.password), expected))
            role = 'admin'
        if not valid:
            raise ApiError(401, 'UNAUTHORISED', 'Email or password is incorrect.')
        token = secrets.token_urlsafe(48)
        expires = time.time() + 8 * 3600
        runtime_store.create_session(conn, token, actor, expected, expires)
    return SessionOut(user=actor, role=role, token=token, expires_at=expires)


@app.get('/v1/auth/session', response_model=SessionOut, tags=['auth'])
def session(request: Request, _admin: str = Depends(require_admin)) -> SessionOut:
    return SessionOut(user=_admin, role=request.state.role, expires_at=getattr(request.state, 'expires_at', None))


@app.post("/v1/auth/logout", response_model=LogoutOut, tags=["auth"])
def logout(authorization: Optional[str] = Header(default=None)) -> LogoutOut:
    scheme, _, value = (authorization or '').partition(' ')
    token = value.strip() if scheme.lower() == 'bearer' else ''
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


CURRENT_FINDINGS = """SELECT f.* FROM findings f WHERE
    NOT EXISTS (SELECT 1 FROM api_jobs j WHERE j.case_id=f.case_id)
    OR EXISTS (SELECT 1 FROM processing_results r JOIN api_jobs j ON j.job_id=r.run_id,
        json_each(r.finding_ids) ids WHERE r.case_id=f.case_id AND ids.value=f.finding_id
        AND j.rowid=(SELECT latest.rowid FROM api_jobs latest WHERE latest.case_id=f.case_id
            ORDER BY latest.rowid DESC LIMIT 1))"""


def current_findings_sql(conn):
    if db.is_postgres(conn):
        return CURRENT_FINDINGS.replace('json_each(r.finding_ids) ids',
            'jsonb_array_elements_text(r.finding_ids::jsonb) ids(value)')
    return CURRENT_FINDINGS


def concerns_by_check(conn):
    return dict(conn.execute('SELECT check_id,COUNT(*) FROM ('+current_findings_sql(conn)+") current_findings WHERE verdict='concern' GROUP BY check_id").fetchall())


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(DB_PATH)
    try:
        db.init_db(conn)
        runtime_store.init(conn)
        conn.commit()
        if request.method == 'GET':
            conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if db.is_postgres(conn) else 'BEGIN')
        yield conn
    except BaseException:
        conn.rollback()
        raise
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
    processing_status: Optional[str] = None
    final_admin_action: Optional[str] = None
    declaration_notes: Optional[str] = None
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
        description="Claim below the preserved ₹50,000 research billing benchmark; "
                    "current survey requirements are unverified.")
    recommendation: Optional[str] = None
    risk_band: Optional[str] = None
    concern_count: int = 0
    image_count: int = 0
    thumbnail_url: Optional[str] = None
    archetype: Optional[str] = Field(
        default=None, description="Evaluation metadata; absent in production traffic.")


class CaseDetail(CaseSummary):
    declaration_notes: Optional[str] = None
    review_revision: int = 0
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
    evidence_request: Optional[dict[str, Any]] = None
    report_history: list[dict[str, Any]] = Field(default_factory=list)


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
    status: Literal['queued', 'running', 'completed', 'done', 'failed', 'interrupted']
    attempts: int = 0
    updated_at: Optional[float] = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: Optional[str] = None
    detail: Optional[str] = None
    provider_unavailable: bool = False
    failures: list[dict[str, Any]] = Field(default_factory=list)
    root_failure_detail: Optional[dict[str, Any]] = None


class SubmitCaseOut(BaseModel):
    applicant_token: Optional[str] = None
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
    reviewed_run_id: Optional[str] = None
    reviewed_decision_id: Optional[str] = None
    reviewed_evidence_ids: list[str] = Field(default_factory=list)
    reviewed_processing_status: Optional[str] = None


class ActionOut(BaseModel):
    case_id: str
    action: Literal["approve", "reject", "request_more_evidence"]
    status: str
    reason: Optional[str] = None
    admin_id: str
    recorded_at: datetime


class HealthOut(BaseModel):
    ablation_verification_status: str = 'not_checked'
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
    expected_revision: Optional[int] = Field(default=None, ge=0)
    expected_run_id: Optional[str] = None
    expected_evidence_ids: Optional[list[str]] = None
    manual_review_override: bool = False
    public_message: Optional[str] = Field(default=None, max_length=3000)
    action: AdminAction
    reason: Optional[str] = None
    admin_id: str = "admin"
    requested_artifacts: list[str] = Field(default_factory=list)


class ReportDeclaration(BaseModel):
    garage_id: Optional[str] = None
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
    declaration_notes: Optional[str] = None
    bank_account_last4: Optional[str] = None


class CaseReportOut(BaseModel):
    assessment_explanation: Optional[dict[str, Any]] = None
    report_template_version: Optional[str] = None
    submitted_at: Optional[str] = None
    evidence_inventory: list[dict[str, Any]] = Field(default_factory=list)
    check_inventory: list[dict[str, Any]] = Field(default_factory=list)
    run_id: Optional[str] = None
    policy_version: Optional[str] = None
    processing: Optional[dict[str, Any]] = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_label: str = 'Heuristic score; not a calibrated fraud probability'
    limitations: list[str] = Field(default_factory=list)
    case_id: str
    declaration: ReportDeclaration
    findings_by_category: dict[str, list[FindingOut]] = Field(default_factory=dict)
    finding_groups: list[FindingGroup] = Field(default_factory=list)
    agent_recommendation: Optional[DecisionOut] = None
    agent_narrative: Optional[str] = None
    admin_action: Optional[AdminActionOut] = None


class TrackOut(BaseModel):
    agent_type: str
    processing_status: Optional[str] = None
    evidence_request: Optional[dict[str, Any]] = None
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
    # A zero concern count says nothing about quota or execution success.
    # Missing perception is reported by the actual inconclusive finding.
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
            if event.event_type == "case_adjudicated" and (event.details.get('decision_id') == d.decision_id or
                (not event.details.get('decision_id') and event.details.get('policy_version') == policy)):
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


def _admin_action_out(action: Optional[AdminActionRecord], conn=None) -> Optional[AdminActionOut]:
    if action is None:
        return None
    context = None
    if conn is not None:
        row=conn.execute("SELECT details FROM audit_log WHERE case_id=? AND event_type='admin_action' AND "
            + db.json_text(conn,'details','recorded_at') + '=? AND ' + db.json_text(conn,'details','admin_id')
            + '=? ORDER BY rowid DESC LIMIT 1',(action.case_id,action.timestamp.isoformat(),action.admin_id)).fetchone()
        context=json.loads(row[0]) if row else None
    return AdminActionOut(
        case_id=action.case_id,
        admin_id=action.admin_id,
        action=action.action.value,
        reason=action.reason,
        timestamp=action.timestamp,
        reviewed_run_id=context.get('run_id') if context else None,
        reviewed_decision_id=context.get('decision_id') if context else None,
        reviewed_evidence_ids=context.get('evidence_ids',[]) if context else [],
        reviewed_processing_status=context.get('processing_status') if context else None,
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


def _current_findings(conn, case_id):
    result = runtime_store.current_result(conn,case_id)
    if runtime_store.latest_job(conn,case_id):
        ids = set(json.loads(result['finding_ids'])) if result else set()
        return [f for f in db.get_findings_for_case(conn,case_id) if f.finding_id in ids]
    return db.get_findings_for_case(conn,case_id)


def _current_decision(conn,case_id):
    result = runtime_store.current_result(conn,case_id)
    decisions = db.get_decisions_for_case(conn,case_id)
    if runtime_store.latest_job(conn,case_id):
        return next((d for d in decisions if result and d.decision_id==result['decision_id']),None)
    return _best_decision(decisions)


def _summaries_for(conn, cases):
    """Four batched reads instead of per-case network round trips.

    Selection matches _current_decision/_current_findings, including legacy
    cases and newly queued runs without results. GET holds one read snapshot.
    """
    if not cases:
        return []
    identifiers=[c.case_id for c in cases]
    marks=','.join('?' for _ in identifiers)
    decisions=defaultdict(list)
    for decision in db.decisions_from_rows(conn.execute('SELECT * FROM agent_decisions WHERE case_id IN ('+marks+') ORDER BY rowid',identifiers).fetchall()):
        decisions[decision.case_id].append(decision)
    latest={r['case_id']:r for r in conn.execute('''SELECT j.case_id,j.status,r.decision_id FROM api_jobs j
        LEFT JOIN processing_results r ON r.run_id=j.job_id
        WHERE j.case_id IN ('''+marks+''') AND j.rowid=(SELECT MAX(x.rowid) FROM api_jobs x WHERE x.case_id=j.case_id)''',identifiers)}
    concerns={r[0]:r[1] for r in conn.execute('SELECT case_id,COUNT(*) FROM ('+current_findings_sql(conn)
        +") cf WHERE verdict='concern' AND case_id IN ("+marks+') GROUP BY case_id',identifiers)}
    images=defaultdict(list)
    for row in conn.execute('SELECT case_id,image_id FROM images WHERE case_id IN ('+marks+') ORDER BY image_id',identifiers):
        images[row[0]].append((row[1],))
    output=[]
    for case in cases:
        history=decisions[case.case_id]
        job=latest.get(case.case_id)
        best=next((d for d in history if d.decision_id==job['decision_id']),None) if job is not None else _best_decision(history)
        output.append(_summary_for(conn,case,{'best':best,'concerns':concerns.get(case.case_id,0),'images':images[case.case_id], 'job': job}))
    return output


def _summary_for(conn: sqlite3.Connection, case: Case, facts=None) -> CaseSummary:
    best = facts['best'] if facts is not None else _current_decision(conn,case.case_id)
    concerns = facts['concerns'] if facts is not None else sum(f.verdict.value == 'concern' for f in _current_findings(conn,case.case_id))
    images = facts['images'] if facts is not None else conn.execute(
        'SELECT image_id FROM images WHERE case_id=? ORDER BY image_id',(case.case_id,)).fetchall()
    return CaseSummary(
        case_id=case.case_id, agent_type=case.agent_type, claim_type=case.claim_type,
        processing_status=(facts['job']['status'] if facts.get('job') is not None else None) if facts is not None else (runtime_store.latest_job(conn,case.case_id) or {}).get('status'),
        final_admin_action='approve' if case.status == 'closed_approved' else 'reject' if case.status == 'closed_rejected' else None,
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
        declaration_notes=case.declaration_notes,
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
        statuses = set(status.split(','))
        cases = [c for c in cases if c.status in statuses]
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
            (c.case_id,c.vehicle_registration,c.claimant_id,c.garage_id,c.person_name,c.policy_number))]

    if not risk_band and not recommendation and has_concerns is None and sort_by in {'created_at','claim_amount'}:
        reverse=sort_dir=='desc'
        if sort_by=='claim_amount':cases.sort(key=lambda c:(c.claim_amount is None,c.claim_amount or 0),reverse=reverse)
        else:cases.sort(key=lambda c:(c.created_at is None,c.created_at or datetime.min.replace(tzinfo=timezone.utc)),reverse=reverse)
        total=len(cases);start=(page-1)*page_size
        items=_summaries_for(conn,cases[start:start+page_size])
        return CaseListOut(total=total,page=page,page_size=page_size,has_more=start+len(items)<total,items=items)
    summaries = _summaries_for(conn,cases)
    if risk_band:
        bands = set(risk_band.split(','))
        summaries = [s for s in summaries if (s.risk_band or 'unrated') in bands]
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
    for f in _current_findings(conn, case_id):
        out = _finding_out(f, case, concerns)
        grouped.setdefault(out.category, []).append(out)
        if out.verdict == "concern":
            attributed[out.attributed_to] += 1

    groups = [FindingGroup(category=cat, findings=fs,
                           concern_count=sum(1 for f in fs if f.verdict == "concern"))
              for cat, fs in grouped.items()]
    decisions = db.get_decisions_for_case(conn, case_id)
    best = _current_decision(conn,case_id)
    base = _summary_for(conn, case)

    return CaseDetail(
        **base.model_dump(),
        review_revision=conn.execute('SELECT COUNT(*) FROM admin_actions WHERE case_id=?',(case_id,)).fetchone()[0],
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
               ],
        processing=runtime_store.job_view(runtime_store.latest_job(conn, case_id)),
        evidence_request=runtime_store.open_request(conn,case_id),
        report_history=[dict(row) for row in conn.execute('SELECT snapshot_id,run_id,created_at FROM report_snapshots WHERE case_id=? ORDER BY rowid DESC',(case_id,))],
    )


def _report_declaration(case: Case) -> ReportDeclaration:
    return ReportDeclaration(
        garage_id=case.garage_id,
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
        declaration_notes=case.declaration_notes,
    )


@app.get("/v1/cases/{case_id}/report", response_model=CaseReportOut, tags=["cases"],
         responses={404: {"model": ErrorResponse}})
def get_case_report(case_id: str, snapshot_id: Optional[str] = Query(default=None),
                    _admin: str = Depends(require_admin), conn: sqlite3.Connection = Depends(get_conn)) -> CaseReportOut:
    if snapshot_id:
        row=conn.execute('SELECT payload FROM report_snapshots WHERE snapshot_id=? AND case_id=?',(snapshot_id,case_id)).fetchone()
        if not row: raise ApiError(404,'REPORT_NOT_FOUND','Report version not found for this case.')
        return CaseReportOut(**json.loads(row[0]))
    return _build_report(conn,case_id)


def _build_report(conn,case_id):
    case=db.get_case(conn,case_id)
    if not case: raise ApiError(404,'CASE_NOT_FOUND','Case not found.')
    concerns=concerns_by_check(conn)
    grouped={c.value:[] for c in CheckCategory}
    for finding in _current_findings(conn,case_id):
        out=_finding_out(finding,case,concerns); grouped.setdefault(out.category,[]).append(out)
    groups=[FindingGroup(category=cat,findings=fs,concern_count=sum(f.verdict=='concern' for f in fs)) for cat,fs in grouped.items()]
    best=_current_decision(conn,case_id); decision=_decision_out(best,conn) if best else None
    result=runtime_store.current_result(conn,case_id); job=runtime_store.latest_job(conn,case_id)
    human=_admin_action_out(db.get_latest_admin_action(conn,case_id),conn)
    limitations=['Scores are heuristic; independent detection accuracy and claimant intent are not established.']
    limitations.append('INR 50,000 is a preserved research billing benchmark; current legal applicability and insurer procedures are unverified.')
    limitations.append('Check findings use local computations and recorded observations; they do not establish successful fresh model adjudication.')
    sources = (job or {}).get('perception_sources')
    if (job or {}).get('checks_revision'):
        limitations.append('Production check implementation revision: ' + job['checks_revision'] + '. This is separate from the recorded agent policy version.')
    if sources:
        limitations.append('Vision sources for this run: ' + ', '.join(f'{name}={count}' for name,count in sources.items()) + '. Cached observations are reused evidence, not new model responses.')
    else:
        limitations.append('Vision freshness was not recorded for this historical run; do not describe its observations as fresh model output.')
    adjudication_sources = (job or {}).get('adjudication_sources')
    if adjudication_sources is None:
        limitations.append('Agent response freshness was not recorded for this run; do not infer fresh model execution from the stored recommendation.')
    else:
        counts = Counter(item.get('source','unrecorded') for item in adjudication_sources)
        limitations.append('Agent response sources for this run: ' + (', '.join(f'{name}={count}' for name,count in counts.items()) or 'no model responses returned') + '. Returned responses alone do not establish completed adjudication; consult processing status.')
    if case.declared_time is None or case.latitude is None or case.longitude is None:
        limitations.append('Scene time/place comparison lacks declared time or coordinates and cannot verify scene consistency.')
    if case.agent_type == 'underwriting':
        limitations.append('Applicant view labels are declarations; same-vehicle identity and six-view coverage have not been independently verified.')
    if not job: limitations.append('Legacy research result: findings and images were not recorded against a processing run.')
    if job and job['status'] not in {'completed','done'}: limitations.append('Current processing is '+job['status']+'. Saved findings do not establish successful model completion.')
    if decision and decision.provider_unavailable: limitations.append('Agent did not converge. Recorded recommendation is a fallback requiring human review.')
    if human and human.reviewed_run_id and job and human.reviewed_run_id != job['job_id']:
        limitations.append('Latest human action reviewed earlier run '+human.reviewed_run_id+'; it is preserved as history.')
    elif human and not human.reviewed_evidence_ids:
        limitations.append('Legacy human action: its processing run and reviewed evidence were not recorded.')
    for fs in grouped.values():
        for finding in fs:
            if finding.check_limitation: limitations.append(finding.check_id+': '+finding.check_limitation)
            if finding.verdict=='inconclusive': limitations.append(finding.check_id+': '+finding.explanation)
            if finding.check_id == 'scene_consistency':
                unavailable = [name for name,value in finding.evidence.items()
                    if name.endswith('_status') and value != 'consistent']
                if unavailable:
                    limitations.append('scene_consistency: partial comparison; these components were not confirmed consistent: ' + ', '.join(unavailable) + '. A PASS covers available comparisons only.')
    evidence_ids=json.loads(result['image_ids']) if result else [i.image_id for i in db.get_images_for_case(conn,case_id)]
    assessment_explanation=None
    if best:
        for event in reversed(db.get_audit_events_for_case(conn,case_id)):
            if (event.event_type=='case_adjudicated' and event.details.get('decision_id')==best.decision_id
                    and (not job or event.details.get('run_id')==job['job_id'])):
                assessment_explanation=event.details.get('assessment_explanation')
                break
    return CaseReportOut(case_id=case_id,declaration=_report_declaration(case),
        assessment_explanation=assessment_explanation,
        findings_by_category=grouped,finding_groups=groups,agent_recommendation=decision,
        agent_narrative=decision.summary if decision else None,
        admin_action=human,
        run_id=job['job_id'] if job else None,policy_version=decision.policy_version if decision else None,
        processing=runtime_store.job_view(job),evidence_ids=evidence_ids,limitations=list(dict.fromkeys(limitations)))


def _snapshot_report(conn,case_id):
    from src.report_pdf import enrich_snapshot,RENDERER_VERSION
    case=db.get_case(conn,case_id)
    if not case:raise ApiError(404,'CASE_NOT_FOUND','Case not found.')
    job=runtime_store.latest_job(conn,case_id)
    decision=_current_decision(conn,case_id)
    basis={'run_id':job['job_id'] if job else None,'processing_status':job['status'] if job else None,
        'decision_id':decision.decision_id if decision else None,
        'human_revision':conn.execute('SELECT COUNT(*) FROM admin_actions WHERE case_id=?',(case_id,)).fetchone()[0],
        'evidence_ids':sorted(image.image_id for image in db.get_images_for_case(conn,case_id)),
        'case_status':case.status,'template_version':RENDERER_VERSION}
    # Opening the same run/review/template must reuse its frozen report, even
    # when unrelated corpus counts or current registry annotations later change.
    for row in conn.execute('SELECT snapshot_id,payload FROM report_snapshots WHERE case_id=? ORDER BY rowid DESC',(case_id,)):
        if json.loads(row['payload']).get('report_basis')==basis:
            return row['snapshot_id']
    report=_build_report(conn,case_id)
    snapshot=enrich_snapshot(conn,report.model_dump(mode='json'))
    snapshot['report_basis']=basis
    payload=json.dumps(snapshot,ensure_ascii=False,separators=(',',':'))
    snapshot_id=runtime_store.digest(payload)
    conn.execute('INSERT INTO report_snapshots(snapshot_id,case_id,run_id,payload,created_at) VALUES (?,?,?,?,?) ON CONFLICT(snapshot_id) DO NOTHING',(snapshot_id,case_id,report.run_id,payload,time.time()))
    return snapshot_id


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

    selected=_current_decision(conn,case_id)
    events = [event for event in db.get_audit_events_for_case(conn, case_id)
              if selected and event.event_type == 'case_adjudicated' and
              (event.details.get('decision_id')==selected.decision_id or
               (not event.details.get('decision_id') and not runtime_store.latest_job(conn,case_id) and event.details.get('policy_version')==selected.policy_version))]
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
    request: Request,
    case_id: str = Query(...),
    x_applicant_token: Optional[str] = Header(default=None),
    registration_number: Optional[str] = Query(None),
    policy_number: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> TrackOut:
    if not runtime_store.applicant_authorized(conn,x_applicant_token,case_id):
        try:
            account = customer_auth.authenticate(conn, request.headers.get('authorization'))
        except ApiError:
            require_admin(request, request.headers.get('authorization'))
        else:
            customer_auth.require_case(conn,account,case_id)
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
        agent_type=case.agent_type,
        case_id=case_id,
        status=case.status,
        final_admin_action=admin_action.action.value if admin_action and case.status != 'evidence_received' else None,
        narrative='Additional evidence received; awaiting a new human review.' if case.status == 'evidence_received' else narrative,
        processing_status=(runtime_store.latest_job(conn,case_id) or {}).get('status'),
        evidence_request=({k:v for k,v in request.items() if k in {'request_id','artifacts','status'}} if (request := runtime_store.open_request(conn,case_id)) else None),
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
    if out.exists() and out.stat().st_size:
        return out
    temporary=None
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            im = im.convert("RGB")
            if im.width > THUMB_WIDTH:
                ratio = THUMB_WIDTH / im.width
                im = im.resize((THUMB_WIDTH, max(1, int(im.height * ratio))))
            temporary=THUMB_DIR/(uuid.uuid4().hex+'.jpg')
            im.save(temporary,'JPEG',quality=82)
            im.close()
        temporary.replace(out)
        return out
    except Exception:  # noqa: BLE001
        return None
    finally:
        if temporary:temporary.unlink(missing_ok=True)


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
        "ETag": f'"{etag}"', "Cache-Control": "private, no-store"})


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
        for r in conn.execute("SELECT check_id, verdict, COUNT(*) FROM ("+current_findings_sql(conn)+") current_findings GROUP BY check_id, verdict")])


@app.get("/v1/stats", response_model=StatsOut, tags=["dashboard"])
def get_stats(_admin: str = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_conn)) -> StatsOut:
    from src.checks import REGISTRY

    def counts(sql: str) -> dict[str, int]:
        return {str(k): int(v) for k, v in conn.execute(sql) if k is not None}

    total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    latest_decisions = """SELECT d.* FROM agent_decisions d WHERE
        (NOT EXISTS (SELECT 1 FROM api_jobs j WHERE j.case_id=d.case_id)
         AND d.rowid=(SELECT latest.rowid FROM agent_decisions latest WHERE latest.case_id=d.case_id ORDER BY latest.created_at DESC,latest.rowid DESC LIMIT 1))
        OR EXISTS (SELECT 1 FROM processing_results r JOIN api_jobs j ON j.job_id=r.run_id
            WHERE r.decision_id=d.decision_id AND j.rowid=(SELECT latest.rowid FROM api_jobs latest
                WHERE latest.case_id=d.case_id ORDER BY latest.rowid DESC LIMIT 1))"""
    by_band = counts(f"SELECT risk_band, COUNT(*) FROM ({latest_decisions}) GROUP BY risk_band")
    decided = conn.execute('SELECT COUNT(*) FROM ('+latest_decisions+')').fetchone()[0]
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
        total_findings=conn.execute('SELECT COUNT(*) FROM ('+current_findings_sql(conn)+') current_findings').fetchone()[0],
        concern_findings=sum(concerns.values()),
        concerns_by_check=concerns, concerns_by_attribution=dict(by_attribution),
        images=conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        images_with_perception=conn.execute(
            "SELECT COUNT(*) FROM images i WHERE EXISTS (SELECT 1 FROM perception_records p WHERE p.content_hash=i.content_hash)").fetchone()[0],
        straight_through_rate=(by_band.get("clear", 0) / decided) if decided else None,
        ablation_arms=arms)


@app.get("/v1/policies", response_model=list[PolicyOut], tags=["config"])
def get_policies(_admin: str = Depends(require_admin)) -> list[PolicyOut]:
    out = []
    from src.agent.production_policy import production_policy
    for agent_type in ('claims','underwriting'):
        p=production_policy(agent_type)
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


def _provider_health(provider_configured):
    return None, 'configured_unverified' if provider_configured else 'not_configured', None


class ReadyOut(BaseModel):
    status: str


@app.get("/ready", response_model=ReadyOut, tags=["config"])
def ready() -> ReadyOut:
    try:
        from src.storage_health import check_storage_ready
        check_storage_ready(UPLOAD_DIR, THUMB_DIR)
    except OSError as exc:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "Evidence storage is unavailable; retry after storage is restored.") from exc
    try:
        with runtime_store.connection(DB_PATH) as conn:
            conn.execute("SELECT 1 FROM cases LIMIT 1")
    except (RuntimeError, *db.DatabaseError) as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "Database is unavailable.") from exc
    return ReadyOut(status="ok")


@app.get("/health", response_model=HealthOut, tags=["config"])
@app.get("/v1/health", response_model=HealthOut, tags=["config"])
def health() -> HealthOut:
    reachable, cases, perception_records, image_records = True, 0, 0, 0
    conn = None
    try:
        conn = db.connect(DB_PATH)
        cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        perception_records = conn.execute("SELECT COUNT(*) FROM perception_records").fetchone()[0]
        image_records = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    except Exception:  # noqa: BLE001
        reachable = False
    finally:
        if conn is not None:conn.close()

    provider_configured = any(os.environ.get(k) for k in
                              ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GOOGLE_API_KEY"))
    provider_reachable, provider_status, provider_checked_at = _provider_health(provider_configured)
    verified_agent_cases = 0
    total = 0
    try:
        from scripts.drive_ablation import total_cases, verify_agent_integrity
        total = total_cases()
        if DB_PATH != 'postgresql':
            integrity = verify_agent_integrity(DB_PATH)
            verified_agent_cases = integrity.verified
    except Exception:  # noqa: BLE001
        total = 0

    try:
        with runtime_store.connection(DB_PATH) as jobs_conn:
            jobs=dict(jobs_conn.execute('SELECT status,COUNT(*) FROM api_jobs GROUP BY status').fetchall())
    except Exception:
        jobs={}
    degraded = (
        not reachable
        or (provider_configured and provider_reachable is False)
    )

    return HealthOut(
        status="degraded" if degraded else "ok",
        database='postgresql' if DB_PATH == 'postgresql' else Path(DB_PATH).name, database_reachable=reachable, cases=cases,
        provider_configured=provider_configured,
        provider_reachable=provider_reachable,
        provider_status=provider_status,
        provider_checked_at=provider_checked_at,
        quota_remaining_estimate=None,
        ablation_verified_agent_cases=verified_agent_cases,
        ablation_verification_status='offline_research_verifier_required' if DB_PATH=='postgresql' else 'checked',
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
        if db.is_postgres(conn):
            conn.execute('BEGIN')
            runtime_store.fence(conn, job_id)
        job = runtime_store.get_job(conn, job_id) or {"job_id": job_id}
        previous_status = job.get('status')
        job.update(fields)
        runtime_store.save_job(conn, job)
        if job.get('status') != previous_status and job.get('status') in {'completed', 'failed', 'interrupted'}:
            db.log_audit_event(conn, AuditEvent(event_type='processing_' + job['status'],
                case_id=job.get('case_id'), details={'run_id':job_id,'status':job['status']}))
    # The selected database is authoritative; do not retain a job cache.


@measured('pipeline.total')
def _run_pipeline(job_id: str, case_id: str) -> None:
    provider = None
    current_stage='initialization'
    failures=[]
    try:
        from src.llm import get_provider, is_rate_limit_error, is_quota_budget_error
        from src.perception import perceive_image, perception_record_usable
        from src.analysis_diagnostics import failure_detail
        from src.orchestrator import process_case
        from src.agent.production_policy import production_policy
        with runtime_store.connection(DB_PATH) as check:
            job = runtime_store.get_job(check, job_id)
            if not job or job['status'] != 'running':
                return
            result = check.execute('SELECT converged FROM processing_results WHERE run_id=?', (job_id,)).fetchone()
            if result:
                complete = bool(result['converged'])
                _set_job(job_id, status='completed' if complete else 'failed',
                         stage='complete' if complete else 'needs_review', progress=1.0,
                         provider_unavailable=not complete)
                return
        conn = db.connect(DB_PATH)
        try:
            provider = get_provider()
            current_stage='evidence_loading'
            images = db.get_images_for_case(conn, case_id)
            if not images: raise ValueError('No indexed evidence available')
            perception_errors = 0
            perception_sources = {'perception_cache': 0, 'request_cache': 0, 'fresh_provider': 0, 'unavailable': 0}
            network_stopped = False
            for index, image in enumerate(images):
                current_stage='perception'
                _set_job(job_id, stage='perception', progress=0.1+0.4*index/len(images))
                if network_stopped:
                    cached = db.get_perception(conn, image.content_hash)
                    if not perception_record_usable(cached):
                        perception_errors += 1
                        perception_sources['unavailable'] += 1
                    else:
                        perception_sources['perception_cache'] += 1
                    continue
                try:
                    provenance = {}
                    with span('pipeline.perception_image'):
                        record = perceive_image(conn, image, provider, retry_attempts=1, provenance=provenance, release_transactions=True)
                    conn.commit()
                    perception_sources[provenance.get('source', 'unavailable')] += 1
                    if not perception_record_usable(record):
                        perception_errors += 1
                        diagnostic=record.raw_response.get('diagnostic')
                        if not diagnostic:
                            unavailable_input=ValueError('The returned vision observations contain no usable visible evidence; request clearer original photographs.')
                            unavailable_input.error_category='required_perception_unavailable'
                            diagnostic=failure_detail(unavailable_input,'perception_inputs',attempt_count=int(provenance.get('source')=='fresh_provider'),
                                attempted_network=provenance.get('source')=='fresh_provider')
                            diagnostic['provider_status']='response_received'
                        failures.append({**diagnostic,'image_id':image.image_id})
                except Exception as exc:
                    conn.rollback(); perception_errors += 1
                    perception_sources['unavailable'] += 1
                    failures.append({**failure_detail(exc,'perception'),'image_id':image.image_id,'worker_attempt':job.get('attempts',0)})
                    access_log.error('Vision unavailable: image=%s error_type=%s', image.image_id, type(exc).__name__)
                    if is_rate_limit_error(exc) or is_quota_budget_error(exc):
                        network_stopped = True
            current_stage='evidence_checks'
            _set_job(job_id, stage='evidence checks', progress=0.6, perception_sources=perception_sources, failures=failures,
                     root_failure_detail=failures[0] if failures else None,
                     provider_request_profile=getattr(provider,'request_profile','unrecorded'),
                     checks_revision='production-checks-2026-10-20-v3')
            adjudicator = provider
            if perception_errors:
                class UnavailableVision:
                    def chat(self, *args, **kwargs):
                        raise RuntimeError('Vision is incomplete; a human must review the saved evidence.')
                adjudicator = UnavailableVision()
            case = db.get_case(conn, case_id)
            last_phase = 'evidence checks'
            def stage_progress(stage, progress):
                nonlocal last_phase,current_stage
                current_stage=stage
                # Keep expensive OCR visible without adding a cloud transaction
                # for every tiny check. All individual timings remain in logs.
                phase = 'plate OCR' if stage == 'check: plate_ocr' else (
                    'agent adjudication' if stage == 'agent adjudication' else 'evidence checks')
                if phase != last_phase:
                    _set_job(job_id, stage=phase, progress=progress)
                    last_phase = phase
            decision = process_case(conn, case_id, provider=adjudicator,
                                    policy=production_policy(case.agent_type), run_id=job_id,
                                    on_stage=stage_progress,
                                    check_config={'evaluation_cutoff':case.created_at.isoformat()} if job.get('retrospective') else None)
            unavailable = _decision_out(decision, conn).provider_unavailable
            for event in reversed(db.get_audit_events_for_case(conn,case_id)):
                if event.event_type=='case_adjudicated' and event.details.get('run_id')==job_id:
                    for item in event.details.get('trace',[]):
                        payload=item.get('payload') or {}
                        diagnostic=payload.get('diagnostic') or (payload.get('observation') or {}).get('diagnostic')
                        if diagnostic and diagnostic not in failures:failures.append(diagnostic)
                    for finding in event.details.get('assessment_explanation',{}).get('findings',[]):
                        diagnostic=finding.get('observed_values',{}).get('diagnostic')
                        if diagnostic and diagnostic not in failures:failures.append(diagnostic)
                    break
            _set_job(job_id, status='failed' if unavailable or perception_errors else 'completed',
                stage='needs_review' if unavailable or perception_errors else 'complete', progress=1.0,
                provider_unavailable=unavailable,
                adjudication_sources=getattr(decision,'_model_response_sources',None),
                failures=failures,
                root_failure_detail=failures[0] if failures else None,
                detail='Automated analysis incomplete. Evidence is saved; fallback requires human review.' if unavailable or perception_errors else None,
                failed_images=perception_errors)
            current_stage='snapshot_persistence'
            conn.execute('BEGIN IMMEDIATE')
            db.lock_case(conn, case_id)
            _snapshot_report(conn, case_id)
            conn.commit()
        finally:
            conn.close()
    except runtime_store.ExecutionLost:
        access_log.warning('Stale processing attempt discarded: case=%s', case_id)
    except Exception as exc:
        from src.analysis_diagnostics import failure_detail
        failures.append(failure_detail(exc,current_stage))
        access_log.error('Analysis failed: case=%s error_type=%s', case_id, type(exc).__name__)
        try:
            _set_job(job_id, status='failed', stage='failed', progress=1.0,
                     error_type=type(exc).__name__, failures=failures, root_failure_detail=failures[0], detail='Analysis could not complete. Evidence is saved. A reviewer can retry after resolving the cause.')
        except runtime_store.ExecutionLost:
            access_log.warning('Recovered job retained its newer state: case=%s', case_id)
    finally:
        if provider and hasattr(provider, 'close'):
            provider.close()


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
                declaration_notes: Optional[str] = None,
                bank_account_last4: Optional[str] = None) -> Case:
    return Case(
        case_id=case_id,
        claimant_id=claimant_id or f"CLM-{uuid.uuid4().hex[:8]}",
        # Case requires a non-blank garage_id. An intake that does not yet know
        # the repairer is ordinary, so record it explicitly as unassigned.
        garage_id=garage_id or "UNASSIGNED",
        claim_type=claim_type or ("underwriting_inspection" if agent_type == "underwriting"
                                  else "motor_claim"),
        declared_time=declared_time,
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
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, min_length=16, max_length=128),
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
    declaration_notes: Optional[str] = Form(default=None,max_length=3500),
    claimant_id: Optional[str] = Form(None),
    garage_id: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    images: Optional[list[UploadFile]] = File(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> SubmitCaseOut:
    account = customer_auth.authenticate(conn, request.headers.get('authorization'), required=False)
    submission_fields = {k: v for k, v in locals().items() if k not in {'conn', 'images', 'background', 'idempotency_key', 'request', 'account'}}
    submission_fields['customer_id'] = account['customer_id'] if account else None
    if idempotency_key:
        try:
            parsed_key=uuid.UUID(idempotency_key)
            if parsed_key.version != 4:raise ValueError('UUID4 required')
        except ValueError as exc:
            raise ApiError(422,'INVALID_SUBMISSION_KEY','Use a random UUID4 submission key.') from exc
    if not (vehicle_registration or policy_number):
        raise ApiError(422, 'TRACKING_IDENTIFIER_REQUIRED', 'Provide a vehicle registration or policy number.')
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
            target = tmp_dir / uuid.uuid4().hex
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
                    extension={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[picture.format]
                    picture.verify()
                decoded_target=target.with_suffix(extension)
                target.rename(decoded_target); target=decoded_target
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

        fingerprint = runtime_store.digest(json.dumps({'fields': submission_fields,
            'images': [hashlib.sha256(path.read_bytes()).hexdigest() for path, _ in staged]}, sort_keys=True, default=str))
        with span('admission.begin_transaction'):
            conn.execute('BEGIN IMMEDIATE')
        receipt_key = runtime_store.digest('submission:' + idempotency_key) if idempotency_key else None
        if receipt_key:
            with span('admission.idempotency_lock'):
                db.lock_key(conn, 'submission:' + receipt_key)
            old = conn.execute('SELECT * FROM submission_receipts WHERE receipt_key=?', (receipt_key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ApiError(409, 'IDEMPOTENCY_CONFLICT', 'This submission key was used with different evidence or details.')
                return SubmitCaseOut(**json.loads(old['response']))
        case.declaration_notes=declaration_notes
        db.insert_case(conn, case)
        if account:
            # Ownership, receipt, evidence, audit and queue entry commit together.
            # Recheck expiry after admission work, before accepting a case.
            customer_auth.authenticate(conn, request.headers.get('authorization'))
            customer_auth.attach(conn, account, case_id)
        db.log_audit_event(conn, AuditEvent(
            event_type="vehicle_image_gate",
            case_id=case_id,
            details={"vehicle_score_threshold": vehicle_gate.VEHICLE_SCORE_THRESHOLD,
                     "declared_time_basis": 'aware_instant' if declared_time is not None and declared_time.utcoffset() is not None else 'unverified',
                     "margin_floor": vehicle_gate.VEHICLE_MARGIN_FLOOR,
                     "scores": [score.to_dict() for score in scores]},
        ))

        upload_dir = UPLOAD_DIR / case_id
        created_upload_dir = False
        saved = 0
        try:
            upload_dir.mkdir(parents=True, exist_ok=False)
            created_upload_dir = True
            from src import ingest
            image_ids = []
            hashes = set()
            for (source, original_name), score in zip(staged,scores):
                content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                if content_hash in hashes:
                    raise ApiError(422, 'DUPLICATE_EVIDENCE', 'The same photograph was attached more than once.')
                hashes.add(content_hash)
                target = upload_dir / f'{uuid.uuid4().hex}{source.suffix.lower()}'
                shutil.copyfile(source, target)
                indexed = ingest.ingest_image(conn, case_id, target,embedding=getattr(score,'embedding',None))
                image_ids.append(indexed.image_id); saved += 1
            token = secrets.token_urlsafe(48)
            conn.execute('INSERT INTO applicant_grants(token_hash,case_id,expires_at) VALUES (?,?,?)', (runtime_store.digest(token),case_id,time.time()+30*86400))
            runtime_store.enqueue(conn, case_id, job_id)
            conn.execute('INSERT INTO evidence_batches(batch_id,case_id,request_id,image_ids,created_at) VALUES (?,?,?,?,?)', (uuid.uuid4().hex,case_id,None,json.dumps(image_ids),time.time()))
            response = SubmitCaseOut(case_id=case_id,job_id=job_id,status='queued',images_received=saved,applicant_token=token)
            if receipt_key:
                # The grant is a high-entropy capability returned only to its submission-key holder.
                conn.execute('INSERT INTO submission_receipts(receipt_key,fingerprint,response,created_at) VALUES (?,?,?,?)', (receipt_key,fingerprint,response.model_dump_json(),time.time()))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            uncertain = getattr(conn,'commit_uncertain',False)
            if not uncertain and created_upload_dir and not upload_dir.is_symlink() and upload_dir.resolve().parent == UPLOAD_DIR.resolve():
                shutil.rmtree(upload_dir, ignore_errors=True)
            if isinstance(exc, ApiError): raise
            if uncertain:
                raise ApiError(503,'SUBMISSION_SAVE_UNCONFIRMED','Save confirmation was interrupted. Keep this submission key and retry the same form; evidence files were preserved.') from exc
            access_log.error('Evidence acceptance failed: %s',type(exc).__name__)
            raise ApiError(503,'EVIDENCE_INGEST_FAILED','Evidence could not be indexed. No case was accepted; please retry.') from exc
    return response


@app.post("/v1/cases/{case_id}/reprocess", response_model=SubmitCaseOut, tags=["cases"],
          responses={404: {"model": ErrorResponse}})
def reprocess_case(case_id: str, background: BackgroundTasks,
                   _admin: str = Depends(require_reviewer), conn: sqlite3.Connection = Depends(get_conn)) -> SubmitCaseOut:
    if db.get_case(conn, case_id) is None:
        raise ApiError(404, 'CASE_NOT_FOUND', 'Case not found.')
    try:
        conn.execute('BEGIN IMMEDIATE')
        db.lock_case(conn, case_id)
        _snapshot_report(conn, case_id)
        job = runtime_store.enqueue(conn, case_id)
        db.log_audit_event(conn, AuditEvent(event_type='analysis_requested',case_id=case_id,
            details={'admin_id':_admin,'run_id':job['job_id']}))
        conn.commit()
    except db.IntegrityError as exc:
        conn.rollback()
        raise ApiError(409,'ANALYSIS_RUNNING','Analysis is already queued or running.') from exc
    return SubmitCaseOut(case_id=case_id,job_id=job['job_id'],status='queued',images_received=len(db.get_images_for_case(conn,case_id)))


@app.get('/v1/jobs/{job_id}', response_model=JobOut, tags=['cases'])
def get_job(job_id: str, request: Request, x_applicant_token: Optional[str] = Header(default=None)) -> JobOut:
    with runtime_store.connection(DB_PATH) as conn:
        job = runtime_store.get_job(conn,job_id)
        if not job:
            raise ApiError(404,'JOB_NOT_FOUND','Job not found.')
        if not runtime_store.applicant_authorized(conn,x_applicant_token,job['case_id']):
            try:
                account = customer_auth.authenticate(conn, request.headers.get('authorization'))
            except ApiError:
                require_admin(request,request.headers.get('authorization'))
            else:
                customer_auth.require_case(conn, account, job['case_id'])
    return JobOut(**{k:v for k,v in job.items() if k in JobOut.model_fields})


@app.post("/v1/cases/{case_id}/action", response_model=ActionOut, tags=["cases"],
          responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def record_action(case_id: str, payload: ActionIn,
                  _admin: str = Depends(require_reviewer),
                  conn: sqlite3.Connection = Depends(get_conn)) -> ActionOut:
    """
    Record what a human admin decided.

    This vocabulary is intentionally not Recommendation. The agent still has no
    rejection member; the human admin action enum does.
    """
    if _admin == 'service':
        raise ApiError(403,'HUMAN_REVIEWER_REQUIRED','Service credentials cannot record human decisions.')
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
        AdminAction.REQUEST_MORE_EVIDENCE: 'awaiting_evidence',
    }[payload.action]
    now = datetime.now(timezone.utc)
    record = AdminActionRecord(
        case_id=case_id,
        admin_id=_admin,
        action=payload.action,
        reason=payload.reason,
        timestamp=now,
    )
    if payload.action == AdminAction.REQUEST_MORE_EVIDENCE:
        artifacts = [a.strip() for a in payload.requested_artifacts if a.strip()]
        if not artifacts or len(artifacts)>12 or any(len(a)>500 for a in artifacts):
            raise ApiError(422,'SPECIFIC_EVIDENCE_REQUIRED','Name 1-12 specific photographs needed, one per item.')
    conn.execute('BEGIN IMMEDIATE')
    db.lock_case(conn, case_id)
    reviewed_job = runtime_store.latest_job(conn, case_id)
    reviewed_images = sorted(image.image_id for image in db.get_images_for_case(conn, case_id))
    if reviewed_job and reviewed_job['status'] in {'queued', 'running'}:
        raise ApiError(409, 'ANALYSIS_RUNNING', 'Wait for analysis to finish before recording a reviewer decision.')
    if reviewed_job and (payload.expected_revision is None or payload.expected_run_id is None or payload.expected_evidence_ids is None):
        raise ApiError(422, 'REVIEW_BASIS_REQUIRED', 'Refresh the case and submit the reviewed revision, analysis run and evidence identifiers.')
    if payload.expected_run_id is not None and payload.expected_run_id != (reviewed_job or {}).get('job_id'):
        raise ApiError(409, 'REVIEW_BASIS_CHANGED', 'The analysis run changed. Refresh and review the current report.')
    if payload.expected_evidence_ids is not None and sorted(payload.expected_evidence_ids) != reviewed_images:
        raise ApiError(409, 'REVIEW_BASIS_CHANGED', 'The evidence changed. Refresh and review all current photographs.')
    if reviewed_job and (reviewed_job['status'] in {'failed', 'interrupted'} or reviewed_job.get('provider_unavailable')) and payload.action != AdminAction.REQUEST_MORE_EVIDENCE:
        if not payload.manual_review_override or not (payload.reason or '').strip():
            raise ApiError(422, 'MANUAL_REVIEW_REQUIRED', 'Explicitly acknowledge incomplete analysis and record your manual-review rationale.')
    if payload.action == AdminAction.REJECT and not (payload.public_message or '').strip():
        raise ApiError(422, 'PUBLIC_REASON_REQUIRED', 'Provide a customer-visible explanation for rejection separately from internal notes.')
    revision=conn.execute('SELECT COUNT(*) FROM admin_actions WHERE case_id=?',(case_id,)).fetchone()[0]
    if payload.expected_revision is not None and payload.expected_revision != revision:
        raise ApiError(409,'REVIEW_CHANGED','Another reviewer changed this case. Refresh before recording a decision.')
    _snapshot_report(conn, case_id)
    conn.execute("UPDATE evidence_requests SET status='superseded' WHERE case_id=? AND status='open'",(case_id,))
    if payload.action == AdminAction.REQUEST_MORE_EVIDENCE:
        conn.execute('INSERT INTO evidence_requests(request_id,case_id,artifacts,actor,status,created_at,fulfilled_at) VALUES (?,?,?,?,?,?,NULL)',
            (uuid.uuid4().hex,case_id,json.dumps(artifacts),_admin,'open',time.time()))
    db.insert_admin_action(conn, record)
    reviewed_job=runtime_store.latest_job(conn,case_id)
    reviewed_result=runtime_store.current_result(conn,case_id)
    conn.execute("UPDATE cases SET status = ? WHERE case_id = ?", (status, case_id))
    db.log_audit_event(conn, AuditEvent(
        event_type="admin_action", case_id=case_id,
        details={"action": payload.action.value, "reason": payload.reason,
                 "admin_id": _admin,
                 'recorded_at':record.timestamp.isoformat(),
                 'run_id':reviewed_job['job_id'] if reviewed_job else None,
                 'decision_id':reviewed_result['decision_id'] if reviewed_result else None,
                 'evidence_ids':[image.image_id for image in db.get_images_for_case(conn,case_id)],
                 'processing_status':reviewed_job['status'] if reviewed_job else None,
                 'manual_review_override': payload.manual_review_override,
                 "requested_artifacts": payload.requested_artifacts,
                 "public_message": payload.public_message,
                 "previous_status": case.status}))
    _snapshot_report(conn,case_id)
    conn.commit()
    return ActionOut(case_id=case_id, action=payload.action.value, status=status,
                     reason=payload.reason, admin_id=_admin, recorded_at=now)


from src.evidence_workflow import install as _install_pilot_extensions
_install_pilot_extensions(app)
from src.report_pdf import install as _install_report_pdf
_install_report_pdf(app)
customer_auth.install(app)


@app.get('/v1/operations',tags=['config'])
def operations(_admin: str=Depends(require_admin),conn: sqlite3.Connection=Depends(get_conn)):
    jobs=[json.loads(row[0]) for row in conn.execute("SELECT payload FROM api_jobs WHERE status IN ('failed','interrupted') ORDER BY rowid DESC LIMIT 10")]
    created = db.json_text(conn,'payload','created_at')
    if db.is_postgres(conn):
        created = '(' + created + ')::double precision'
    oldest=conn.execute('SELECT MIN(COALESCE('+created+",updated_at)) FROM api_jobs WHERE status='queued'").fetchone()[0]
    worker=getattr(app.state,'worker',None)
    return {'organization_id':'local','tenant_isolation':False,
        'database_backend':'postgresql' if db.is_postgres(conn) else 'sqlite',
        'worker_active_in_this_process':bool(worker and worker.thread and worker.thread.is_alive()),
        'worker_leader_in_this_process':bool(worker and worker.lock),
        'database_worker_leader_present':runtime_store.worker_leader_present(conn),
        'jobs_by_status':dict(conn.execute('SELECT status,COUNT(*) FROM api_jobs GROUP BY status').fetchall()),
        'recent_failures':[{k:v for k,v in job.items() if k in {'job_id','case_id','status','stage','error_type','detail','attempts','updated_at'}} for job in jobs if job['status'] in {'failed','interrupted'}][:10],
        'oldest_queued_age_seconds':max(0,time.time()-oldest) if oldest is not None else 0}
