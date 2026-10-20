"""Customer access using the pilot's existing password and bearer-session primitives.

Accounts never inherit cases by email. Ownership is created at intake, or by an
explicit unexpired case receipt. Reviewer and customer tokens have separate
server-side stores and cannot be substituted for one another.
"""
import json
import re
import secrets
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, Header, Request
from pydantic import BaseModel, Field

from . import db, runtime_store
from .models import AuditEvent


SQLITE_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS customer_accounts (
        customer_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS customer_sessions (
        token_hash TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customer_accounts(customer_id),
        credential_hash TEXT NOT NULL, expires_at REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS case_owners (
        case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
        customer_id TEXT NOT NULL REFERENCES customer_accounts(customer_id), created_at REAL NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_customer_cases ON case_owners(customer_id, created_at)',
    'CREATE INDEX IF NOT EXISTS idx_customer_sessions ON customer_sessions(customer_id)',
)


def init_sqlite(conn):
    for statement in SQLITE_SCHEMA:
        conn.execute(statement)


def bearer(authorization):
    scheme, _, value = (authorization or '').partition(' ')
    return value.strip() if scheme.lower() == 'bearer' else ''


def authenticate(conn, authorization, required=True):
    from .api import ApiError
    token = bearer(authorization)
    row = conn.execute('''SELECT a.*,s.expires_at,s.credential_hash FROM customer_sessions s
        JOIN customer_accounts a ON a.customer_id=s.customer_id
        WHERE s.token_hash=? AND s.expires_at>?''', (runtime_store.digest(token), time.time())).fetchone() if token else None
    if row and row['enabled'] and secrets.compare_digest(row['password_hash'], row['credential_hash']):
        return dict(row)
    if required or token:
        raise ApiError(401, 'CUSTOMER_UNAUTHORISED', 'Your customer session is invalid or expired. Sign in again.')
    return None


def owns(conn, account, case_id):
    return bool(account and conn.execute('SELECT 1 FROM case_owners WHERE case_id=? AND customer_id=?',
                                        (case_id, account['customer_id'])).fetchone())


def require_case(conn, account, case_id):
    from .api import ApiError
    if not owns(conn, account, case_id):
        raise ApiError(404, 'CASE_NOT_FOUND', 'No matching case was found in your account.')


def attach(conn, account, case_id):
    conn.execute('INSERT INTO case_owners(case_id,customer_id,created_at) VALUES (?,?,?)',
                 (case_id, account['customer_id'], time.time()))


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def case_view(conn, case, detail=False):
    """Only public reviewer messages and safe recorded timeline events leave here."""
    job = runtime_store.latest_job(conn, case.case_id) or {}
    events = db.get_audit_events_for_case(conn, case.case_id)
    actions = [event for event in events if event.event_type == 'admin_action']
    latest = actions[-1].details if actions else {}
    outcome = 'approve' if case.status == 'closed_approved' else 'reject' if case.status == 'closed_rejected' else None
    narrative = 'Your case has been received and is awaiting human review.'
    if outcome or case.status == 'awaiting_evidence':
        narrative = latest.get('public_message') or {
            'approve': 'A reviewer has approved your application.',
            'reject': 'A reviewer has declined your application. Contact the review team for details.',
        }.get(outcome, 'Please provide the photographs requested by your reviewer.')
    if case.status == 'evidence_received':
        narrative = 'Your additional evidence was received. A new review is pending.'
    request = runtime_store.open_request(conn, case.case_id)
    result = {
        'id': case.case_id, 'kind': case.agent_type, 'status': case.status,
        'submittedAt': case.created_at.isoformat(),
        'updatedAt': events[-1].created_at.isoformat() if events else case.created_at.isoformat(),
        'processingStatus': job.get('status', 'not_started'), 'processingStage': job.get('stage'),
        'processingDetail': job.get('detail') if job.get('status') in {'failed', 'interrupted'} else None,
        'outcome': outcome, 'publicNarrative': narrative,
        'evidenceRequest': {key: request[key] for key in ('request_id', 'artifacts', 'status')} if request else None,
        'registration': case.vehicle_registration, 'policy': case.policy_number,
    }
    if detail:
        titles = {
            'vehicle_image_gate': 'Application and photographs received',
            'additional_evidence_received': 'Additional photographs received',
            'processing_started': 'Analysis started', 'processing_completed': 'Analysis completed',
            'processing_failed': 'Analysis incomplete; human review required',
            'processing_interrupted': 'Analysis interrupted', 'reprocess_requested': 'New analysis requested',
            'analysis_requested': 'New analysis requested', 'processing_finished': 'Analysis finished',
            'processing_restart_recovery': 'Analysis recovered after interruption',
            'case_submitted': 'Application submitted', 'job_recovered': 'Analysis recovered after interruption',
        }
        timeline = [{'id': 'submitted', 'at': case.created_at.isoformat(), 'title': 'Application submitted', 'message': ''}]
        history = []
        for index, event in enumerate(events):
            if event.event_type == 'admin_action':
                action = event.details.get('action')
                title = {'approve': 'Approved by a reviewer', 'reject': 'Declined by a reviewer',
                         'request_more_evidence': 'Additional photographs requested'}.get(action, 'Reviewer update')
                item = {'id': str(index), 'at': event.created_at.isoformat(), 'title': title,
                        'message': event.details.get('public_message') or ''}
                timeline.append(item)
                history.append({**item, 'action': action, 'runId': event.details.get('run_id')})
            elif event.event_type in titles:
                timeline.append({'id': str(index), 'at': event.created_at.isoformat(),
                                 'title': titles[event.event_type], 'message': ''})
        result.update(
            application={key: value for key, value in json.loads(json.dumps(asdict(case), default=str)).items()
                         if key not in {'claimant_id', 'garage_id'}},
            timeline=timeline, decisionHistory=history,
            images=[{'id': image.image_id, 'label': 'Photograph ' + str(index + 1),
                     'url': '/v1/customer/images/' + image.image_id}
                    for index, image in enumerate(db.get_images_for_case(conn, case.case_id))],
        )
    return result


class CustomerCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class Registration(CustomerCredentials):
    name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=1024)


class ReceiptLink(BaseModel):
    case_id: str = Field(min_length=1, max_length=64)
    receipt: str = Field(min_length=16, max_length=256)


class CustomerEvidenceRequest(BaseModel):
    request_id: str
    artifacts: list[str]
    status: str


class CustomerTimelineEvent(BaseModel):
    id: str
    at: str
    title: str
    message: str
    action: str | None = None
    runId: str | None = None


class CustomerImage(BaseModel):
    id: str
    label: str
    url: str


class CustomerCaseOut(BaseModel):
    id: str
    kind: Literal['claims', 'underwriting']
    status: str
    submittedAt: str
    updatedAt: str
    processingStatus: str
    processingStage: str | None = None
    processingDetail: str | None = None
    outcome: Literal['approve', 'reject'] | None = None
    publicNarrative: str
    evidenceRequest: CustomerEvidenceRequest | None = None
    registration: str | None = None
    policy: str | None = None
    application: dict[str, Any] | None = None
    timeline: list[CustomerTimelineEvent] | None = None
    decisionHistory: list[CustomerTimelineEvent] | None = None
    images: list[CustomerImage] | None = None


class CustomerCasesOut(BaseModel):
    items: list[CustomerCaseOut]


def install(app):
    from .api import ApiError, SessionOut, LogoutOut, get_conn

    def customer(request: Request, conn=Depends(get_conn)):
        account = authenticate(conn, request.headers.get('authorization'))
        request.state.customer_id = account['customer_id']
        return account

    def new_session(conn, account):
        token = secrets.token_urlsafe(48)
        expires = time.time() + 8 * 3600
        conn.execute('DELETE FROM customer_sessions WHERE expires_at<=?', (time.time(),))
        conn.execute('INSERT INTO customer_sessions(token_hash,customer_id,credential_hash,expires_at) VALUES (?,?,?,?)',
                     (runtime_store.digest(token), account['customer_id'], account['password_hash'], expires))
        conn.commit()
        return SessionOut(user=account['email'], role='customer', token=token, expires_at=expires)

    @app.post('/v1/customer/auth/register', response_model=SessionOut, status_code=201, tags=['customer'])
    def register(payload: Registration, conn=Depends(get_conn)):
        email = payload.email.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or not payload.name.strip():
            raise ApiError(422, 'VALIDATION_FAILED', 'Enter your name and a valid email address.')
        account = {'customer_id': uuid.uuid4().hex, 'email': email,
                   'password_hash': runtime_store.password_hash(payload.password), 'name': payload.name.strip()}
        try:
            conn.execute('INSERT INTO customer_accounts(customer_id,email,password_hash,name,created_at) VALUES (?,?,?,?,?)',
                         (*account.values(), time.time()))
        except db.IntegrityError as exc:
            conn.rollback()
            raise ApiError(409, 'ACCOUNT_EXISTS', 'An account with that email already exists. Sign in instead.') from exc
        db.log_audit_event(conn, AuditEvent(event_type='customer_registered', details={'customer_id': account['customer_id']}))
        return new_session(conn, account)

    @app.post('/v1/customer/auth/login', response_model=SessionOut, tags=['customer'])
    def login(payload: CustomerCredentials, conn=Depends(get_conn)):
        row = conn.execute('SELECT * FROM customer_accounts WHERE email=?', (payload.email.strip().lower(),)).fetchone()
        stored = row['password_hash'] if row else 'pbkdf2_sha256$600000$00000000000000000000000000000000$' + '0' * 64
        valid = runtime_store.password_matches(payload.password, stored)
        if not valid or not row or not row['enabled']:
            raise ApiError(401, 'CUSTOMER_UNAUTHORISED', 'Email or password is incorrect.')
        return new_session(conn, dict(row))

    @app.get('/v1/customer/auth/session', response_model=SessionOut, tags=['customer'])
    def session(account=Depends(customer)):
        return SessionOut(user=account['email'], role='customer', expires_at=account['expires_at'])

    @app.post('/v1/customer/auth/logout', response_model=LogoutOut, tags=['customer'])
    def logout(authorization: str = Header(default=''), conn=Depends(get_conn)):
        conn.execute('DELETE FROM customer_sessions WHERE token_hash=?', (runtime_store.digest(bearer(authorization)),))
        conn.commit()
        return {'ok': True}

    @app.get('/v1/customer/cases', response_model=CustomerCasesOut, tags=['customer'])
    def cases(account=Depends(customer), conn=Depends(get_conn)):
        ids = conn.execute('SELECT case_id FROM case_owners WHERE customer_id=? ORDER BY created_at DESC',
                           (account['customer_id'],)).fetchall()
        return {'items': [case_view(conn, db.get_case(conn, row[0])) for row in ids]}

    @app.post('/v1/customer/cases/link', response_model=CustomerCaseOut, tags=['customer'])
    def link(payload: ReceiptLink, account=Depends(customer), conn=Depends(get_conn)):
        conn.execute('BEGIN IMMEDIATE')
        db.lock_case(conn, payload.case_id)
        if not runtime_store.applicant_authorized(conn, payload.receipt, payload.case_id):
            raise ApiError(404, 'CASE_NOT_FOUND', 'A valid unexpired private receipt for this case is required.')
        owner = conn.execute('SELECT customer_id FROM case_owners WHERE case_id=?', (payload.case_id,)).fetchone()
        if owner and owner[0] != account['customer_id']:
            raise ApiError(409, 'CASE_ALREADY_LINKED', 'This case already belongs to another account.')
        if not owner:
            attach(conn, account, payload.case_id)
            db.log_audit_event(conn, AuditEvent(event_type='customer_case_linked', case_id=payload.case_id,
                                               details={'customer_id': account['customer_id']}))
        conn.commit()
        return case_view(conn, db.get_case(conn, payload.case_id), detail=True)

    @app.get('/v1/customer/cases/{case_id}', response_model=CustomerCaseOut, tags=['customer'])
    def detail(case_id: str, account=Depends(customer), conn=Depends(get_conn)):
        require_case(conn, account, case_id)
        return case_view(conn, db.get_case(conn, case_id), detail=True)

    @app.get('/v1/customer/images/{image_id}', tags=['customer'])
    def image(image_id: str, request: Request, account=Depends(customer), conn=Depends(get_conn)):
        from fastapi.responses import FileResponse
        row = conn.execute('SELECT case_id,path FROM images WHERE image_id=?', (image_id,)).fetchone()
        if not row:
            raise ApiError(404, 'IMAGE_NOT_FOUND', 'Photograph not found.')
        require_case(conn, account, row['case_id'])
        from .api import _resolve_data_path
        path = _resolve_data_path(row['path'])
        if path is None or not path.is_file():
            raise ApiError(503, 'EVIDENCE_UNAVAILABLE', 'This photograph is temporarily unavailable. Please retry later.')
        return FileResponse(path, headers={'Cache-Control': 'no-store'})
