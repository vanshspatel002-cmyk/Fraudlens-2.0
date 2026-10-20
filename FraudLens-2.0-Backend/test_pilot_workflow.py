"""Offline workflow regressions. Vision is mocked; detector accuracy is not tested."""
import hashlib
import io
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from src import api, db, ingest, runtime_store, vehicle_gate

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAUDLENS_WORKER_ENABLED','0')
    monkeypatch.setenv('FRAUDLENS_WARM_MODELS','0')
    monkeypatch.setattr(api, 'DB_PATH', str(tmp_path / 'pilot.db'))
    monkeypatch.setattr(api, 'UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setenv('ADMIN_EMAIL', 'reviewer@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD_SHA256', hashlib.sha256(b'correct-password').hexdigest())
    monkeypatch.delenv('EVIDENCE_SERVICE_TOKEN', raising=False)
    monkeypatch.setattr(api, 'RATE_LIMIT_SUBMIT_MAX', 100)
    api._RATE_LIMITS.clear()
    api._JOBS.clear()
    monkeypatch.setattr(api, '_run_pipeline', lambda *args: None)
    score = SimpleNamespace(accepted=True, to_dict=lambda: {'accepted': True})
    monkeypatch.setattr(vehicle_gate, 'classify_uploads', lambda paths, names: [score for p in paths])
    monkeypatch.setattr(ingest, '_default_embedder', SimpleNamespace(embed=lambda path: [1.0, 0.0]))
    with TestClient(api.app) as c:
        yield c

def photo(color='red'):
    buf = io.BytesIO()
    PILImage.new('RGB', (32, 32), color).save(buf, format='PNG')
    return buf.getvalue()

def submit(client, kind='claims', files=None):
    return client.post('/v1/cases', data={'agent_type': kind, 'vehicle_registration': 'MH12AB1234',
        'policy_number': 'POL-123', 'person_name': 'Test applicant'},
        files=files or [('images', ('photo.png', photo(), 'image/png'))])

def auth(client):
    response = client.post('/v1/auth/login', json={'email': 'reviewer@example.com', 'password': 'correct-password'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def complete_for_review(client, case_id, headers):
    """Explicit controlled worker completion for HTTP decision-contract tests."""
    with runtime_store.connection(api.DB_PATH) as conn:
        job = runtime_store.latest_job(conn,case_id)
        job.update(status='completed',stage='complete')
        runtime_store.save_job(conn,job)
    return review_basis(client,case_id,headers)


def review_basis(client, case_id, headers):
    detail=client.get('/v1/cases/'+case_id,headers=headers).json()
    return {'expected_revision':detail['review_revision'],
            'expected_run_id':detail['processing']['job_id'],
            'expected_evidence_ids':[image['image_id'] for image in detail['images']]}

def test_login_email_expiry_revocation(client):
    assert client.post('/v1/auth/login', json={'email': 'other@example.com', 'password': 'correct-password'}).status_code == 401
    headers = auth(client)
    assert client.get('/v1/auth/session', headers=headers).json()['user'] == 'reviewer@example.com'
    assert client.post('/v1/auth/logout', headers=headers).status_code == 200
    assert client.get('/v1/auth/session', headers=headers).status_code == 401
    headers = auth(client)
    with runtime_store.connection(api.DB_PATH) as conn:
        conn.execute('UPDATE admin_sessions SET expires_at = ?', (time.time() - 1,))
    assert client.get('/v1/auth/session', headers=headers).status_code == 401

def test_password_rotation(client, monkeypatch):
    headers = auth(client)
    monkeypatch.setenv('ADMIN_PASSWORD_SHA256', hashlib.sha256(b'new-password').hexdigest())
    assert client.get('/v1/auth/session', headers=headers).status_code == 401

@pytest.mark.parametrize('kind', ['claims', 'underwriting'])
def test_applicant_admin_workflow(client, kind):
    response = submit(client, kind)
    assert response.status_code == 201, response.text
    case_id = response.json()['case_id']
    assert response.json()['images_received'] == 1
    assert client.get('/v1/cases').status_code == 401
    headers = auth(client)
    assert client.get('/v1/cases', headers=headers).json()['items'][0]['case_id'] == case_id
    action = client.post(f'/v1/cases/{case_id}/action', headers=headers, json={
        **complete_for_review(client,case_id,headers),
        'action': 'approve', 'admin_id': 'forged', 'reason': 'Internal assessment',
        'public_message': 'Your application is approved.'})
    assert action.status_code == 200, action.text
    assert action.json()['admin_id'] == 'reviewer@example.com'
    tracked = client.get('/v1/track', headers=headers, params={'case_id': case_id, 'registration_number': 'MH12AB1234'}).json()
    assert tracked['status'] == 'closed_approved'
    assert tracked['narrative'] == 'Your application is approved.'
    assert 'Internal assessment' not in str(tracked)
    detail = client.get(f'/v1/cases/{case_id}', headers=headers).json()
    assert next(e for e in detail['audit'] if e['event']=='admin_action')['actor']=='reviewer@example.com'
    assert client.get(f'/v1/cases/{case_id}/report', headers=headers).json()['admin_action']['admin_id'] == 'reviewer@example.com'

def test_duplicate_filenames(client):
    r = submit(client, files=[('images', ('same.png', photo('red'), 'image/png')),
                             ('images', ('same.png', photo('blue'), 'image/png'))])
    assert r.status_code == 201, r.text
    conn = db.connect(api.DB_PATH)
    try:
        images = db.get_images_for_case(conn, r.json()['case_id'])
        assert len(images) == 2
        assert len({i.path for i in images}) == 2
        assert len({Path(i.path).read_bytes() for i in images}) == 2
    finally: conn.close()

def test_ingestion_rollback(client, monkeypatch):
    def fail(*args): raise RuntimeError('embedding unavailable')
    monkeypatch.setattr(ingest, 'ingest_image', fail)
    r = submit(client)
    assert r.status_code == 503
    assert r.json()['code'] == 'EVIDENCE_INGEST_FAILED'
    conn = db.connect(api.DB_PATH)
    try: assert conn.execute('SELECT count(*) FROM cases').fetchone()[0] == 0
    finally: conn.close()
    assert not list(api.UPLOAD_DIR.glob('*'))

def test_invalid_uploads(client):
    for content in [b'not an image', b'x' * (5 * 1024 * 1024 + 1)]:
        assert submit(client, files=[('images', ('bad.png', content, 'image/png'))]).status_code == 422

def test_job_persistence_restart(client):
    r = submit(client).json()
    api._JOBS.clear()
    assert client.get('/v1/jobs/' + r['job_id'],headers={'X-Applicant-Token':r['applicant_token']}).json()['status'] == 'queued'
    with runtime_store.connection(api.DB_PATH) as conn: runtime_store.interrupt_jobs(conn)
    assert client.get('/v1/jobs/' + r['job_id'],headers={'X-Applicant-Token':r['applicant_token']}).json()['status'] == 'queued'

def test_reprocess_conflict(client):
    r = submit(client).json()
    assert client.post('/v1/cases/' + r['case_id'] + '/reprocess', headers=auth(client)).status_code == 409

def test_private_narrative_and_fallback_disclosure(client):
    from src.models import AgentDecision, Recommendation, RiskBand
    from src.orchestrator import adjudication_event
    r = submit(client).json()
    conn = db.connect(api.DB_PATH)
    try:
        d = AgentDecision(case_id=r['case_id'], recommendation=Recommendation.ESCALATE,
            risk_band=RiskBand.DESK_REVIEW, confidence=0.3, summary='Private garage investigation',
            supporting_finding_ids=[], requested_artifacts=['original photo'], policy_version='agent-test', llm_calls_count=2)
        db.insert_agent_decision(conn, d)
        db.log_audit_event(conn, adjudication_event(r['case_id'], 'agent', 'agent-test', d, False, []))
        conn.execute('INSERT INTO processing_results(run_id,case_id,decision_id,finding_ids,image_ids,policy_version,converged,created_at) VALUES (?,?,?,?,?,?,?,?)',(r['job_id'],r['case_id'],d.decision_id,'[]','[]','agent-test',0,time.time()))
        conn.commit()
    finally: conn.close()
    tracked = client.get('/v1/track', headers={'X-Applicant-Token':r['applicant_token']}, params={'case_id': r['case_id'], 'policy_number': 'POL-123'})
    assert 'Private garage' not in tracked.text
    assert client.get('/v1/cases/' + r['case_id'], headers=auth(client)).json()['decision']['provider_unavailable'] is True

def test_statistics_count_latest_decision_only(client):
    from datetime import datetime, timedelta, timezone
    from src.models import AgentDecision, Recommendation, RiskBand
    case_id = submit(client).json()['case_id']
    conn = db.connect(api.DB_PATH)
    try:
        for i, (band, recommendation) in enumerate([(RiskBand.ESCALATE_SIU, Recommendation.ESCALATE), (RiskBand.CLEAR, Recommendation.APPROVE)]):
            db.insert_agent_decision(conn, AgentDecision(case_id=case_id, recommendation=recommendation,
                risk_band=band, confidence=0.7, summary='Recorded test assessment',
                supporting_finding_ids=[], requested_artifacts=[], policy_version='agent-test',
                created_at=datetime.now(timezone.utc) + timedelta(seconds=i)))
        decision = db.get_decisions_for_case(conn,case_id)[-1]
        job = runtime_store.latest_job(conn,case_id)
        conn.execute('INSERT INTO processing_results(run_id,case_id,decision_id,finding_ids,image_ids,policy_version,converged,created_at) VALUES (?,?,?,?,?,?,?,?)',(job['job_id'],case_id,decision.decision_id,'[]','[]','agent-test',1,time.time()))
        conn.commit()
    finally: conn.close()
    stats = client.get('/v1/stats', headers=auth(client)).json()
    assert stats['decided_cases'] == 1
    assert stats['by_risk_band'] == {'clear': 1}
    assert stats['by_recommendation'] == {'approve': 1}
