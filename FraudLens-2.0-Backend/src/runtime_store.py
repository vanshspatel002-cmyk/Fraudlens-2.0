"""Additive pilot storage: one organization, durable queue and immutable run history."""
from contextlib import contextmanager
import hashlib
import json
import secrets
import time
import threading
from . import db

_execution = threading.local()


class ExecutionLost(RuntimeError):
    """A recovered attempt must never persist results from its old worker."""


@contextmanager
def execution(job):
    _execution.job = job
    try:
        yield
    finally:
        _execution.job = None


def fence(conn, job_id):
    if not db.is_postgres(conn):
        return
    owner = getattr(_execution, 'job', None)
    row = conn.execute('SELECT payload FROM api_jobs WHERE job_id=? FOR UPDATE', (job_id,)).fetchone()
    current = json.loads(row[0]) if row else {}
    if not owner or owner['job_id'] != job_id or current.get('status') != 'running' or not owner.get('execution_token') or current.get('execution_token') != owner['execution_token']:
        raise ExecutionLost('Processing ownership changed; stale results were discarded.')


def init(conn):
    if db.is_postgres(conn):
        db.init_db(conn)
        return
    statements = [
        '''CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, actor TEXT NOT NULL,
            credential_hash TEXT NOT NULL, expires_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS api_jobs (job_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
            updated_at REAL NOT NULL, payload TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_api_jobs_case ON api_jobs(case_id, updated_at)',
        'CREATE TABLE IF NOT EXISTS organizations (organization_id TEXT PRIMARY KEY, name TEXT NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS reviewer_accounts (email TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','reviewer','viewer')),
            organization_id TEXT NOT NULL DEFAULT 'local' REFERENCES organizations(organization_id),
            enabled INTEGER NOT NULL DEFAULT 1)''',
        '''CREATE TABLE IF NOT EXISTS applicant_grants (token_hash TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(case_id), expires_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS evidence_requests (request_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(case_id), artifacts TEXT NOT NULL, actor TEXT NOT NULL,
            status TEXT NOT NULL, created_at REAL NOT NULL, fulfilled_at REAL)''',
        '''CREATE TABLE IF NOT EXISTS evidence_batches (batch_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(case_id), request_id TEXT, image_ids TEXT NOT NULL, created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS submission_receipts (receipt_key TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL, response TEXT NOT NULL, created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS processing_results (run_id TEXT PRIMARY KEY REFERENCES api_jobs(job_id),
            case_id TEXT NOT NULL, decision_id TEXT NOT NULL REFERENCES agent_decisions(decision_id),
            finding_ids TEXT NOT NULL, image_ids TEXT NOT NULL, policy_version TEXT NOT NULL,
            converged INTEGER NOT NULL, created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS report_snapshots (snapshot_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL, run_id TEXT, payload TEXT NOT NULL, created_at REAL NOT NULL)''',
    ]
    for statement in statements:
        conn.execute(statement)
    if not conn.execute("SELECT 1 FROM organizations WHERE organization_id='local'").fetchone():
        conn.execute("INSERT OR IGNORE INTO organizations VALUES ('local', 'Local FraudLens pilot')")
    cols = {r[1] for r in conn.execute('PRAGMA table_info(api_jobs)')}
    if 'status' not in cols:
        conn.execute("ALTER TABLE api_jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'failed'")
        conn.execute("UPDATE api_jobs SET status = json_extract(payload, '$.status')")
    duplicates = conn.execute("SELECT case_id FROM api_jobs WHERE status IN ('queued','running') GROUP BY case_id HAVING COUNT(*)>1").fetchall()
    for row in duplicates:
        jobs = conn.execute("SELECT payload FROM api_jobs WHERE case_id=? AND status IN ('queued','running') ORDER BY updated_at DESC", (row[0],)).fetchall()
        for old in jobs[1:]:
            job = json.loads(old[0]); job.update(status='interrupted', stage='superseded'); save_job(conn, job)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_job ON api_jobs(case_id) WHERE status IN ('queued','running')")


@contextmanager
def connection(path):
    conn = db.connect(path)
    try:
        init(conn)
        conn.commit()
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${value}'


def password_matches(password, stored):
    import hmac
    try:
        _, rounds, salt, expected = stored.split('$')
        value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(value, expected)
    except (ValueError, TypeError):
        return False


def create_session(conn, token, actor, credential_hash, expires_at):
    conn.execute('DELETE FROM admin_sessions WHERE expires_at<=?', (time.time(),))
    conn.execute('INSERT INTO admin_sessions(token_hash,actor,credential_hash,expires_at) VALUES (?,?,?,?)', (digest(token), actor, credential_hash, expires_at))


def session_record(conn, token, credential_hash):
    row = conn.execute('SELECT * FROM admin_sessions WHERE token_hash=? AND expires_at>?', (digest(token), time.time())).fetchone()
    if not row: return None
    account = conn.execute('SELECT * FROM reviewer_accounts WHERE email=?', (row['actor'],)).fetchone()
    expected = account['password_hash'] if account and account['enabled'] else credential_hash if not account else None
    if expected != row['credential_hash']: return None
    return {'actor':row['actor'], 'role':account['role'] if account else 'admin', 'expires_at':row['expires_at']}


def session_actor(conn, token, credential_hash):
    record = session_record(conn, token, credential_hash)
    return record['actor'] if record else None


def delete_session(conn, token):
    conn.execute('DELETE FROM admin_sessions WHERE token_hash=?', (digest(token),))


def applicant_authorized(conn, token, case_id):
    return bool(token and conn.execute('SELECT 1 FROM applicant_grants WHERE token_hash=? AND case_id=? AND expires_at>?', (digest(token),case_id,time.time())).fetchone())


def save_job(conn, job):
    job['updated_at'] = time.time()
    conn.execute('''INSERT INTO api_jobs(job_id,case_id,updated_at,payload,status) VALUES (?,?,?,?,?)
        ON CONFLICT(job_id) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload,status=excluded.status''',
        (job['job_id'],job['case_id'],job['updated_at'],json.dumps(job),job['status']))


def enqueue(conn, case_id, job_id=None):
    job = {'job_id':job_id or secrets.token_hex(16),'case_id':case_id,'status':'queued','stage':'queued',
           'progress':0.0,'attempts':0,'max_attempts':3,'created_at':time.time()}
    save_job(conn,job)
    return job


def get_job(conn, job_id):
    row = conn.execute('SELECT payload FROM api_jobs WHERE job_id=?',(job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def latest_job(conn, case_id):
    row = conn.execute("SELECT payload FROM api_jobs WHERE case_id=? ORDER BY rowid DESC LIMIT 1",(case_id,)).fetchone()
    return json.loads(row[0]) if row else None


def job_view(job):
    """Execution fencing belongs in storage, never in UI/report payloads."""
    return {k:v for k,v in job.items() if k != 'execution_token'} if job else None


def claim_next(conn):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    suffix = ' FOR UPDATE SKIP LOCKED' if db.is_postgres(conn) else ''
    row=conn.execute("SELECT payload FROM api_jobs WHERE status='queued' ORDER BY rowid LIMIT 1" + suffix).fetchone()
    if not row: conn.commit(); return None
    job=json.loads(row[0]); job.update(status='running',stage='starting',attempts=job.get('attempts',0)+1,started_at=time.time())
    job['execution_token'] = secrets.token_hex(24)
    from .models import AuditEvent
    db.log_audit_event(conn,AuditEvent(event_type='processing_started',case_id=job['case_id'],
        details={'run_id':job['job_id'],'attempt':job['attempts']}))
    save_job(conn,job); conn.commit()
    return job


def interrupt_jobs(conn):
    """Only call under the cluster advisory lock or SQLite OS lock."""
    if db.is_postgres(conn) and not conn.in_transaction:
        conn.execute('BEGIN')
    suffix = ' FOR UPDATE' if db.is_postgres(conn) else ''
    for row in conn.execute("SELECT payload FROM api_jobs WHERE status='running'" + suffix).fetchall():
        job=json.loads(row[0])
        completed=conn.execute('SELECT converged FROM processing_results WHERE run_id=?',(job['job_id'],)).fetchone()
        if completed: job.update(status='completed' if completed[0] else 'failed',stage='complete' if completed[0] else 'needs_review',progress=1.0,provider_unavailable=not bool(completed[0]))
        else:
            job.pop('execution_token', None)
            job.setdefault('interruptions',[]).append(time.time())
            retry=job.get('attempts',0)<job.get('max_attempts',3)
            job.update(status='queued' if retry else 'interrupted',stage='restart_recovery',detail='Previous attempt interrupted; recovery queued.' if retry else 'Restart retry limit reached. Reviewer action required.')
        save_job(conn,job)
        from .models import AuditEvent
        db.log_audit_event(conn,AuditEvent(event_type='processing_restart_recovery',case_id=job['case_id'],
            details={'run_id':job['job_id'],'status':job['status'],'attempt':job.get('attempts',0)}))


def current_result(conn, case_id):
    job=latest_job(conn,case_id)
    return conn.execute('SELECT * FROM processing_results WHERE run_id=?',(job['job_id'],)).fetchone() if job else None


def open_request(conn, case_id):
    row=conn.execute("SELECT * FROM evidence_requests WHERE case_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",(case_id,)).fetchone()
    return {**dict(row),'artifacts':json.loads(row['artifacts'])} if row else None
