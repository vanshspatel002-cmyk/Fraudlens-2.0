"""Persistent sessions and job status for the single-instance SQLite pilot.

This is durable status storage, not a distributed task queue. Sessions contain
only token hashes. Credential rotation invalidates existing sessions.
"""
from contextlib import contextmanager
import hashlib
import json
import time
from . import db


def init(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token_hash TEXT PRIMARY KEY, actor TEXT NOT NULL,
            credential_hash TEXT NOT NULL, expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_jobs (
            job_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
            updated_at REAL NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_jobs_case ON api_jobs(case_id, updated_at);
    ''')


@contextmanager
def connection(path):
    conn = db.connect(path)
    try:
        init(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, token, actor, credential_hash, expires_at):
    conn.execute('DELETE FROM admin_sessions WHERE expires_at <= ?', (time.time(),))
    conn.execute('INSERT INTO admin_sessions VALUES (?, ?, ?, ?)',
                 (digest(token), actor, credential_hash, expires_at))


def session_actor(conn, token, credential_hash):
    row = conn.execute('SELECT actor FROM admin_sessions WHERE token_hash = ? AND credential_hash = ? AND expires_at > ?',
                       (digest(token), credential_hash, time.time())).fetchone()
    return row[0] if row else None


def delete_session(conn, token):
    conn.execute('DELETE FROM admin_sessions WHERE token_hash = ?', (digest(token),))


def save_job(conn, job):
    conn.execute('INSERT OR REPLACE INTO api_jobs VALUES (?, ?, ?, ?)',
                 (job['job_id'], job['case_id'], time.time(), json.dumps(job)))


def get_job(conn, job_id):
    row = conn.execute('SELECT payload FROM api_jobs WHERE job_id = ?', (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def latest_job(conn, case_id):
    row = conn.execute('SELECT payload FROM api_jobs WHERE case_id = ? ORDER BY updated_at DESC LIMIT 1',
                       (case_id,)).fetchone()
    return json.loads(row[0]) if row else None


def interrupt_jobs(conn):
    for row in conn.execute('SELECT payload FROM api_jobs').fetchall():
        job = json.loads(row[0])
        if job.get('status') in {'queued', 'running'}:
            job.update(status='failed', stage='interrupted',
                       detail='Processing was interrupted by a service restart. A reviewer can retry analysis.')
            save_job(conn, job)
    conn.commit()
