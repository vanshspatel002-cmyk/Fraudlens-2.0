"""Offline regressions for queue, run history, applicant capabilities and roles.

Model replies and embeddings are mocked here. These tests establish contracts,
transaction boundaries and privacy, not detection accuracy or live reliability.
"""
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
import uuid
import pytest
from src import api, db, ingest, runtime_store, session_budget
from src.models import AgentDecision, Finding, PerceptionRecord, Recommendation, RiskBand, CheckCategory, Verdict
from test_pilot_workflow import client, auth, photo, submit, complete_for_review, review_basis, initial_files
from src.photo_admission import SLOTS
REAL_PIPELINE = api._run_pipeline


def offline_perception(image):
    """Explicit valid observations; no provider or authenticity claim."""
    return PerceptionRecord(content_hash=image.content_hash,source='offline-cache-fixture',
        damage_description='A small visible bumper dent.',damage_severity='minor',
        weather_observed='unknown',road_condition='Not visible',shadow_direction='none_visible',
        shadow_length='none',lighting='daylight',plate_text='',
        scene_context='A parked vehicle.',anomaly_notes='',raw_response={})


def finish(case_id):
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.latest_job(conn,case_id)
        job.update(status='completed',stage='complete'); runtime_store.save_job(conn,job)


def request_evidence(client, case_id, headers):
    response=client.post(f'/v1/cases/{case_id}/action',headers=headers,json={
        **review_basis(client,case_id,headers),
        'action':'request_more_evidence','reason':'Internal reviewer rationale',
        'public_message':'Please upload the original rear view.',
        'requested_artifacts':['Original rear view including the registration plate']})
    assert response.status_code==200,response.text
    tracked=client.get('/v1/track',headers=headers,params={'case_id':case_id,'policy_number':'POL-123'}).json()
    assert 'Internal reviewer rationale' not in str(tracked)
    return tracked['evidence_request']['request_id']


def test_evidence_resubmission_and_history(client):
    receipt=submit(client).json(); case_id=receipt['case_id']; headers=auth(client)
    finish(case_id); request_id=request_evidence(client,case_id,headers)
    original=client.get(f'/v1/cases/{case_id}',headers=headers).json()
    response=client.post(f'/v1/cases/{case_id}/evidence',headers={'X-Applicant-Token':receipt['applicant_token']},
        data={'request_id':request_id},files={'images':('rear.png',photo('blue'),'image/png')})
    assert response.status_code==200,response.text
    updated=client.get(f'/v1/cases/{case_id}',headers=headers).json()
    assert updated['status']=='evidence_received'
    assert len(updated['images'])==5 and updated['processing']['status']=='queued'
    assert updated['decision'] is None and updated['total_concerns']==0
    assert updated['report_history']
    current_report=client.get(f'/v1/cases/{case_id}/report',headers=headers).json()
    human=current_report['admin_action']
    assert human['reviewed_run_id']==receipt['job_id']
    assert len(human['reviewed_evidence_ids'])==4
    assert current_report['run_id']!=human['reviewed_run_id']
    saved=client.get(f'/v1/cases/{case_id}/report',params={'snapshot_id':original['report_history'][0]['snapshot_id']},headers=headers).json()
    assert len(saved['evidence_ids'])==4
    assert saved['admin_action']['action']=='request_more_evidence'
    assert client.get('/v1/track',headers=headers,params={'case_id':case_id,'policy_number':'POL-123'}).json()['evidence_request'] is None
    assert any(a['event']=='additional_evidence_received' for a in updated['audit'])
    assert client.post(f'/v1/cases/{case_id}/evidence',headers={'X-Applicant-Token':receipt['applicant_token']},
        data={'request_id':request_id},files={'images':('rear.png',photo('blue'),'image/png')}).status_code==409


@pytest.mark.parametrize('token_kind',['missing','other_case','expired'])
def test_evidence_capability_scope(client,token_kind):
    receipt=submit(client).json(); case_id=receipt['case_id']; finish(case_id)
    request_id=request_evidence(client,case_id,auth(client))
    token=receipt['applicant_token']
    if token_kind=='missing': token=''
    if token_kind=='other_case': token=submit(client).json()['applicant_token']
    if token_kind=='expired':
        with runtime_store.connection(api.DB_PATH) as conn: conn.execute('UPDATE applicant_grants SET expires_at=0')
    assert client.post(f'/v1/cases/{case_id}/evidence',headers={'X-Applicant-Token':token},
        data={'request_id':request_id},files={'images':('rear.png',photo('blue'),'image/png')}).status_code==401


@pytest.mark.parametrize('fault',['duplicate','invalid','ingestion','copy','queue'])
def test_supplementary_failure_is_atomic(client,monkeypatch,fault):
    receipt=submit(client).json();case_id=receipt['case_id'];finish(case_id)
    request_id=request_evidence(client,case_id,auth(client))
    content=photo('red' if fault=='duplicate' else 'blue') if fault!='invalid' else b'invalid'
    def fail(*args,**kwargs): raise OSError('isolated simulated failure')
    if fault=='ingestion': monkeypatch.setattr(ingest,'ingest_image',fail)
    if fault=='copy': monkeypatch.setattr(__import__('shutil'),'copyfile',fail)
    if fault=='queue': monkeypatch.setattr(runtime_store,'enqueue',fail)
    r=client.post(f'/v1/cases/{case_id}/evidence',headers={'X-Applicant-Token':receipt['applicant_token']},
        data={'request_id':request_id},files={'images':('rear.png',content,'image/png')})
    assert r.status_code==({'duplicate':409,'invalid':422}.get(fault,503)),r.text
    with runtime_store.connection(api.DB_PATH) as conn:
        assert len(db.get_images_for_case(conn,case_id))==4
        assert runtime_store.open_request(conn,case_id)['request_id']==request_id
        assert runtime_store.latest_job(conn,case_id)['status']=='completed'
    assert not list((api.UPLOAD_DIR/case_id).glob('supplement-*'))


def test_specific_request_and_stale_human_decision(client):
    case_id=submit(client).json()['case_id'];headers=auth(client)
    assert client.post(f'/v1/cases/{case_id}/action',headers=headers,json={
        'action':'request_more_evidence','reason':'Please provide evidence'}).status_code==422
    base=complete_for_review(client,case_id,headers)
    first=client.post(f'/v1/cases/{case_id}/action',headers=headers,json={**base,'action':'approve','expected_revision':0})
    assert first.status_code==200
    assert client.post(f'/v1/cases/{case_id}/action',headers=headers,json={**base,'action':'reject','reason':'Another outcome','public_message':'A separate sample reason','expected_revision':0}).status_code==409


def test_idempotent_submission(client):
    key=str(uuid.uuid4()); payload={'agent_type':'claims','vehicle_registration':'MH12AB1234','policy_number':'POL-123','photo_slots':list(SLOTS['claims'])}
    def send(color):
        files=initial_files();files[0]=('images',('vehicle.png',photo(color),'image/png'))
        return client.post('/v1/cases',headers={'Idempotency-Key':key},data=payload,files=files)
    one=send('red');two=send('red')
    assert one.status_code==two.status_code==201
    assert one.json()==two.json()
    assert send('blue').status_code==409
    with runtime_store.connection(api.DB_PATH) as conn: assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==1


def test_initial_copy_and_enqueue_rollback(client,monkeypatch):
    def fail(*args,**kwargs): raise OSError('disk unavailable')
    monkeypatch.setattr(runtime_store,'enqueue',fail)
    assert submit(client).status_code==503
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM applicant_grants').fetchone()[0]==0
    assert not list(api.UPLOAD_DIR.glob('*'))


def test_jobs_are_private(client):
    one=submit(client).json(); two=submit(client).json(); url='/v1/jobs/'+one['job_id']
    assert client.get(url).status_code==401
    assert client.get(url,headers={'X-Applicant-Token':two['applicant_token']}).status_code==401
    assert client.get(url,headers={'X-Applicant-Token':one['applicant_token']}).status_code==200
    assert client.get(url,headers=auth(client)).status_code==200


@pytest.mark.parametrize('route',['','/report','/trace','/similar'])
def test_private_routes_reject_applicant(client,route):
    one=submit(client).json()
    assert client.get('/v1/cases/'+one['case_id']+route,headers={'X-Applicant-Token':one['applicant_token']}).status_code==401


def test_reviewer_roles_rotation_and_disable(client):
    owner=auth(client)
    def account(role='viewer',enabled=True): return client.put('/v1/accounts',headers=owner,json={
        'email':'individual@example.com','password':'individual-test-password','role':role,'enabled':enabled})
    assert account().status_code==200
    token=client.post('/v1/auth/login',json={'email':'individual@example.com','password':'individual-test-password'}).json()['token']
    viewer={'Authorization':'Bearer '+token};receipt=submit(client).json()
    assert client.get('/v1/cases',headers=viewer).status_code==200
    assert client.post('/v1/cases/'+receipt['case_id']+'/reprocess',headers=viewer).status_code==403
    assert client.post('/v1/cases/'+receipt['case_id']+'/action',headers=viewer,json={'action':'approve'}).status_code==403
    assert client.put('/v1/accounts',headers=viewer,json={'email':'forged@example.com','password':'irrelevant-password'}).status_code==403
    assert account('reviewer').status_code==200
    assert client.get('/v1/auth/session',headers=viewer).status_code==401
    assert account(enabled=False).status_code==200
    assert client.post('/v1/auth/login',json={'email':'individual@example.com','password':'individual-test-password'}).status_code==401


def test_raw_password_disabled(client):
    assert client.get('/v1/cases',headers={'Authorization':'Bearer correct-password'}).status_code==401


def test_concurrent_reprocess_only_one_job(client):
    case_id=submit(client).json()['case_id'];finish(case_id);headers=auth(client)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(f'/v1/cases/{case_id}/reprocess',headers=headers).status_code,range(2)))
    assert sorted(results)==[200,409]
    with runtime_store.connection(api.DB_PATH) as conn: assert conn.execute("SELECT count(*) FROM api_jobs WHERE status='queued'").fetchone()[0]==1


def test_restart_recovery_bounded_and_queued_preserved(client):
    receipt=submit(client).json()
    with runtime_store.connection(api.DB_PATH) as conn:
        runtime_store.interrupt_jobs(conn)
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='queued'
        job=runtime_store.claim_next(conn);assert job['attempts']==1
        runtime_store.interrupt_jobs(conn)
        assert runtime_store.get_job(conn,receipt['job_id'])['stage']=='restart_recovery'
        conn.commit()
        runtime_store.claim_next(conn);runtime_store.interrupt_jobs(conn);conn.commit()
        runtime_store.claim_next(conn);runtime_store.interrupt_jobs(conn);conn.commit()
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='interrupted'


def test_exclusive_worker_execution_and_shutdown(client):
    from src.durable_worker import DurableWorker
    receipt=submit(client).json(); seen=[]; done=threading.Event()
    def execute(job_id,case_id):
        seen.append(job_id)
        with runtime_store.connection(api.DB_PATH) as conn:
            job=runtime_store.get_job(conn,job_id);job['status']='completed';runtime_store.save_job(conn,job)
        done.set()
    one=DurableWorker(api.DB_PATH,execute);two=DurableWorker(api.DB_PATH,execute)
    try:
        assert one.start() is True
        assert two.start() is False
        assert done.wait(10)
        assert seen==[receipt['job_id']]
    finally: one.stop();two.stop()


def test_processing_runs_never_mix(client,monkeypatch):
    from src import orchestrator
    from src.agent.engine import AdjudicationResult
    from src.agent.production_policy import production_policy
    receipt=submit(client).json();case_id=receipt['case_id'];headers=auth(client)
    monkeypatch.setattr(orchestrator,'run_checks',lambda conn,case,check_ids,**kw:[Finding(check_id='exif_metadata',case_id=case.case_id,
        category=CheckCategory.PROVENANCE,verdict=Verdict.CONCERN,confidence=.5,explanation='Isolated test finding')])
    def adjudicate(conn,case,findings,policy,provider,*,check_config=None,release_transactions=False):
        decision=AgentDecision(case_id=case.case_id,recommendation=Recommendation.ESCALATE,risk_band=RiskBand.DESK_REVIEW,
            confidence=.5,summary='Isolated mocked adjudication',supporting_finding_ids=[findings[0].finding_id],
            requested_artifacts=[],policy_version=policy.policy_version,llm_calls_count=1)
        return AdjudicationResult(decision,[],converged=True)
    monkeypatch.setattr(orchestrator,'adjudicate',adjudicate)
    def process(run_id):
        with runtime_store.connection(api.DB_PATH) as conn:
            job=runtime_store.claim_next(conn)
            assert job['job_id']==run_id
            with runtime_store.execution(job):
                orchestrator.process_case(conn,case_id,policy=production_policy('claims'),provider=object(),run_id=run_id)
            job=runtime_store.get_job(conn,run_id);job['status']='completed';runtime_store.save_job(conn,job)
            api._snapshot_report(conn,case_id)
    process(receipt['job_id'])
    first=client.get(f'/v1/cases/{case_id}/report',headers=headers).json()
    second_job=client.post(f'/v1/cases/{case_id}/reprocess',headers=headers).json()['job_id']
    assert client.get(f'/v1/cases/{case_id}',headers=headers).json()['decision'] is None
    process(second_job)
    current=client.get(f'/v1/cases/{case_id}',headers=headers).json()
    assert current['total_concerns']==1 and len(current['decisions'])==2
    assert current['decision']['decision_id']!=first['agent_recommendation']['decision_id']
    old_id=next(r['snapshot_id'] for r in current['report_history'] if r['run_id']==receipt['job_id'])
    assert client.get(f'/v1/cases/{case_id}/report',headers=headers,params={'snapshot_id':old_id}).json()['run_id']==receipt['job_id']


def test_session_request_cap_and_failure_stop(tmp_path,monkeypatch):
    from src.quota_budget import QuotaBudgetExhausted
    ledger=tmp_path/'ledger.json';monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER',str(ledger));monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','2')
    for _ in range(2): session_budget.reserve('offline-test');session_budget.outcome()
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('offline-test')
    assert json.loads(ledger.read_text())['attempts']==2
    ledger.unlink();session_budget.reserve('offline-test');session_budget.outcome(SimpleNamespace(code=429))
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('offline-test')


def test_health_and_ready_never_contact_provider(client,monkeypatch):
    from src import llm
    monkeypatch.setattr(llm,'get_provider',lambda *a:pytest.fail('Health spent model quota'))
    assert client.get('/ready').status_code==503
    assert client.get('/ready').json()['capabilities']['validator']=='lazy'
    api.app.state.capabilities['validator']='ready'  # Controlled model fixture is ready.
    from src import runtime_readiness
    monkeypatch.setattr(runtime_readiness,'provider_status',lambda configured=None:{'state':'locally_enabled_unverified','ready':True})
    assert client.get('/ready').status_code==200
    monkeypatch.setattr(runtime_readiness,'provider_status',lambda configured=None:{'state':'paused','ready':False})
    assert client.get('/ready').status_code==503
    assert client.get('/ready').json()['code']=='PROVIDER_NOT_READY'
    assert client.get('/health').status_code==200


def test_out_of_order_provider_outcomes_are_attributed(tmp_path,monkeypatch):
    ledger=tmp_path/'ledger.json';monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER',str(ledger))
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','15')
    first=session_budget.reserve('first');second=session_budget.reserve('second')
    session_budget.outcome(SimpleNamespace(code=503),attempt=second)
    session_budget.outcome(attempt=first)
    events=json.loads(ledger.read_text())['events']
    assert [event['outcome'] for event in events]==['success','failure:503']
    with pytest.raises(RuntimeError):session_budget.outcome(attempt=first)


def test_declaration_notes_and_missing_time_are_preserved(client):
    response=client.post('/v1/cases',data={'agent_type':'claims','vehicle_registration':'MH12AB1234',
        'declaration_notes':'A specific applicant observation, not a model instruction.','photo_slots':list(SLOTS['claims'])},
        files=initial_files())
    assert response.status_code==201,response.text
    report=client.get('/v1/cases/'+response.json()['case_id']+'/report',headers=auth(client)).json()
    assert report['declaration']['declaration_notes']=='A specific applicant observation, not a model instruction.'
    assert report['declaration']['incident_date'] is None


@pytest.mark.parametrize('provider_failure',[False,True])
def test_pipeline_persists_run_and_closes_provider(client,monkeypatch,provider_failure):
    from src import llm, perception, orchestrator
    receipt=submit(client).json();closed=[]
    class OfflineProvider:
        def chat(self,*args,**kwargs):
            if provider_failure:raise RuntimeError('Explicit isolated offline provider failure')
            return llm.LLMResponse(text=json.dumps({'recommendation':'escalate','risk_band':'desk_review',
                'narrative':'Explicit mocked regression response; requires human review.',
                'findings_cited':[],'requested_artifacts':[]}),tool_call=None,raw={},model='offline-regression',cached=False,latency_ms=1)
        def close(self):closed.append(True)
    monkeypatch.setattr(llm,'get_provider',lambda:OfflineProvider())
    monkeypatch.setattr(perception,'perceive_image',lambda conn,image,*a,**kw:offline_perception(image))
    monkeypatch.setattr(orchestrator,'run_checks',lambda conn,case,check_ids,**kw:[Finding(check_id='exif_metadata',case_id=case.case_id,
        category=CheckCategory.PROVENANCE,verdict=Verdict.INCONCLUSIVE,confidence=0,explanation='Isolated mocked finding'),
        Finding(check_id='ai_generation',case_id=case.case_id,category=CheckCategory.PROVENANCE,
        verdict=Verdict.CONCERN,confidence=0.9,explanation='Isolated mocked experimental observation')])
    with runtime_store.connection(api.DB_PATH) as conn: claimed=runtime_store.claim_next(conn)
    with runtime_store.execution(claimed):
        REAL_PIPELINE(receipt['job_id'],receipt['case_id'])
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id'])
        assert job['status']==('failed' if provider_failure else 'completed')
        assert runtime_store.current_result(conn,receipt['case_id'])
        assert len(db.get_images_for_case(conn,receipt['case_id']))==4
        experimental=next(f for f in db.get_findings_for_case(conn,receipt['case_id']) if f.check_id=='ai_generation')
        assert experimental.verdict==Verdict.INCONCLUSIVE and experimental.confidence==0
        assert experimental.evidence['experimental_verdict']=='concern'
    assert closed==[True]
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id']);job['status']='running';runtime_store.save_job(conn,job)
    with runtime_store.execution(claimed):
        REAL_PIPELINE(receipt['job_id'],receipt['case_id'])
    with runtime_store.connection(api.DB_PATH) as conn:
        assert runtime_store.get_job(conn,receipt['job_id'])['status']==('failed' if provider_failure else 'completed')
        assert conn.execute('SELECT count(*) FROM processing_results').fetchone()[0]==1
    assert closed==[True]


def test_pipeline_preserves_later_cached_vision_after_stop(client,monkeypatch):
    from src import llm,perception,orchestrator
    from src.quota_budget import QuotaBudgetExhausted
    receipt=submit(client,files=initial_files()).json()
    with runtime_store.connection(api.DB_PATH) as conn:
        images=db.get_images_for_case(conn,receipt['case_id']);claimed=runtime_store.claim_next(conn)
    cached={image.content_hash:offline_perception(image) for image in images[1:]}
    monkeypatch.setattr(db,'get_perception',lambda conn,h:cached.get(h))
    calls=[];closed=[]
    def stop(conn,image,*a,**kw):
        calls.append(image.image_id);raise QuotaBudgetExhausted('Explicit offline session stop')
    monkeypatch.setattr(perception,'perceive_image',stop)
    monkeypatch.setattr(llm,'get_provider',lambda:SimpleNamespace(close=lambda:closed.append(True)))
    monkeypatch.setattr(orchestrator,'run_checks',lambda *a,**kw:[])
    with runtime_store.execution(claimed):
        REAL_PIPELINE(receipt['job_id'],receipt['case_id'])
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id'])
        assert job['failed_images']==1 and job['status']=='failed'
        assert runtime_store.current_result(conn,receipt['case_id'])
    assert calls==[images[0].image_id] and closed==[True]


def test_pipeline_progress_releases_ocr_cache_and_records_sources(client,monkeypatch):
    from dataclasses import replace
    from src import llm,perception
    from src.agent import production_policy as policies
    from src.checks import plate_ocr
    from src.quota_budget import QuotaBudgetExhausted
    receipt=submit(client).json()
    monkeypatch.setattr(llm,'get_provider',lambda:SimpleNamespace(close=lambda:None))
    def stopped(*a,**kw):raise QuotaBudgetExhausted('Offline test stop')
    monkeypatch.setattr(perception,'perceive_image',stopped)
    policy=replace(policies.production_policy('claims'),check_ids=('plate_ocr','exif_metadata'))
    monkeypatch.setattr(policies,'production_policy',lambda kind:policy)
    monkeypatch.setattr(plate_ocr,'get_reader',lambda:SimpleNamespace(readtext=lambda path:[(None,'MH12AB1234',.95)]))
    with runtime_store.connection(api.DB_PATH) as conn:claimed=runtime_store.claim_next(conn)
    with runtime_store.execution(claimed):REAL_PIPELINE(receipt['job_id'],receipt['case_id'])
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id'])
        assert job['status']=='failed' and job['stage']=='needs_review'
        assert job['perception_sources']=={'perception_cache':0,'request_cache':0,'fresh_provider':0,'unavailable':4}
        assert conn.execute("SELECT COUNT(*) FROM cache_entries WHERE namespace='production_plate_ocr'").fetchone()[0]==4
        result=runtime_store.current_result(conn,receipt['case_id'])
        assert result and not result['converged']
        report=api._build_report(conn,receipt['case_id'])
        assert any('unavailable=4' in limitation for limitation in report.limitations)
        assert any('legal applicability' in limitation for limitation in report.limitations)
        assert job['adjudication_sources']==[]


@pytest.mark.parametrize('cached',[True,False])
def test_run_audit_records_adjudication_response_source(client,monkeypatch,cached):
    from src import orchestrator
    from src.agent.engine import AdjudicationResult
    from src.agent.production_policy import production_policy
    receipt=submit(client).json();case_id=receipt['case_id']
    monkeypatch.setattr(orchestrator,'run_checks',lambda *a,**kw:[])
    def adjudicate(conn,case,findings,policy,provider,*,check_config=None,release_transactions=False):
        provider.chat([])
        decision=AgentDecision(case_id=case.case_id,recommendation=Recommendation.ESCALATE,
            risk_band=RiskBand.DESK_REVIEW,confidence=.3,summary='Explicit offline response fixture',
            supporting_finding_ids=[],requested_artifacts=[],policy_version=policy.policy_version,llm_calls_count=1)
        return AdjudicationResult(decision,[],converged=True)
    monkeypatch.setattr(orchestrator,'adjudicate',adjudicate)
    provider=SimpleNamespace(chat=lambda *a,**kw:SimpleNamespace(cached=cached,model='offline-fixture'))
    with runtime_store.connection(api.DB_PATH) as conn:
        claimed=runtime_store.claim_next(conn)
        with runtime_store.execution(claimed):
            decision=orchestrator.process_case(conn,case_id,provider=provider,policy=production_policy('claims'),run_id=receipt['job_id'])
        sources=[{'source':'request_cache' if cached else 'fresh_provider','model':'offline-fixture',
            'request_provenance':{}}]
        assert decision._model_response_sources==sources
        event=next(e for e in db.get_audit_events_for_case(conn,case_id) if e.event_type=='case_adjudicated')
        assert event.details['run_id']==receipt['job_id'] and event.details['model_response_sources']==sources


@pytest.mark.parametrize('timestamp,basis',[
    ('2026-10-13T06:30:00Z','aware_instant'),('2026-10-13T12:00:00+05:30','aware_instant')])
def test_intake_records_trusted_time_basis_for_production_checks(client,monkeypatch,timestamp,basis):
    from src import orchestrator
    from src.agent.engine import AdjudicationResult
    from src.agent.production_policy import production_policy
    receipt=client.post('/v1/cases',data={'agent_type':'claims','vehicle_registration':'MH12AB1234',
        'declared_time':timestamp,'latitude':'22.3','longitude':'73.2','photo_slots':list(SLOTS['claims'])},
        files=initial_files()).json()
    captured=[]
    monkeypatch.setattr(orchestrator,'run_checks',lambda *a,**kw:captured.append(kw['config']) or [])
    def adjudicate(conn,case,findings,policy,provider,*,check_config=None,release_transactions=False):
        decision=AgentDecision(case_id=case.case_id,recommendation=Recommendation.ESCALATE,
            risk_band=RiskBand.DESK_REVIEW,confidence=.3,summary='Offline time-basis fixture',
            supporting_finding_ids=[],requested_artifacts=[],policy_version=policy.policy_version)
        return AdjudicationResult(decision,[],converged=False)
    monkeypatch.setattr(orchestrator,'adjudicate',adjudicate)
    with runtime_store.connection(api.DB_PATH) as conn:
        orchestrator.process_case(conn,receipt['case_id'],provider=object(),
            policy=production_policy('claims'),run_id=receipt['job_id'],persist=False)
        gate=next(e for e in db.get_audit_events_for_case(conn,receipt['case_id']) if e.event_type=='vehicle_image_gate')
        assert gate.details['declared_time_basis']==basis
        assert captured[0]['scene_time_basis']==basis


def test_job_order_does_not_depend_on_wall_clock(client,monkeypatch):
    first=submit(client).json();finish(first['case_id'])
    monkeypatch.setattr(runtime_store.time,'time',lambda:1)
    with runtime_store.connection(api.DB_PATH) as conn:
        second=runtime_store.enqueue(conn,first['case_id'])
        assert runtime_store.latest_job(conn,first['case_id'])['job_id']==second['job_id']


def test_bootstrap_email_rotation_invalidates_sessions(client,monkeypatch):
    headers=auth(client);monkeypatch.setenv('ADMIN_EMAIL','rotated@example.com')
    assert client.get('/v1/auth/session',headers=headers).status_code==401


@pytest.mark.parametrize('method,path,header',[
    ('POST','/v1/cases','idempotency-key'),
    ('POST','/v1/cases/placeholder/evidence','x-applicant-token'),
    ('GET','/v1/jobs/placeholder','x-applicant-token'),
    ('PUT','/v1/accounts','authorization'),
])
def test_browser_preflight_supports_authorized_workflows(client,method,path,header):
    response=client.options(path,headers={'Origin':'http://localhost:5173',
        'Access-Control-Request-Method':method,'Access-Control-Request-Headers':header+',content-type'})
    assert response.status_code==200,response.text
    assert response.headers['access-control-allow-origin']=='http://localhost:5173'


def test_admission_embedding_is_reused(client,monkeypatch):
    from src import vehicle_gate
    score=SimpleNamespace(accepted=True,embedding=[1.,0.],to_dict=lambda:{'accepted':True})
    monkeypatch.setattr(vehicle_gate,'classify_uploads',lambda paths,names:[score for _ in paths])
    monkeypatch.setattr(ingest,'_default_embedder',SimpleNamespace(embed=lambda path:pytest.fail('Admission encoded the same photo twice')))
    assert submit(client).status_code==201


def test_service_cannot_record_human_decisions(client,monkeypatch):
    monkeypatch.setenv('EVIDENCE_SERVICE_TOKEN','isolated-test-service-token')
    receipt=submit(client).json();headers={'Authorization':'Bearer isolated-test-service-token'}
    assert client.get('/v1/cases',headers=headers).status_code==200
    assert client.post('/v1/cases/'+receipt['case_id']+'/action',headers=headers,json={'action':'approve'}).status_code==403
    assert client.get('/v1/accounts',headers=headers).status_code==403


def test_submission_key_must_be_unguessable(client):
    response=client.post('/v1/cases',headers={'Idempotency-Key':'guessable-test-key'},
        data={'vehicle_registration':'MH12AB1234'},files={'images':('vehicle.png',photo(),'image/png')})
    assert response.status_code==422 and response.json()['code']=='INVALID_SUBMISSION_KEY'


def test_queue_filters_include_resubmissions_and_unrated_work(client):
    one=submit(client).json();two=submit(client).json();headers=auth(client)
    with runtime_store.connection(api.DB_PATH) as conn:
        conn.execute("UPDATE cases SET status='evidence_received' WHERE case_id=?",(one['case_id'],))
        conn.execute("UPDATE cases SET status='closed_approved' WHERE case_id=?",(two['case_id'],))
    waiting=client.get('/v1/cases',params={'status':'open,evidence_received'},headers=headers).json()
    assert [r['case_id'] for r in waiting['items']]==[one['case_id']]
    decided=client.get('/v1/cases',params={'status':'closed_approved,closed_rejected'},headers=headers).json()
    assert [r['case_id'] for r in decided['items']]==[two['case_id']]
    assert client.get('/v1/cases',params={'risk_band':'unrated'},headers=headers).json()['total']==2


def test_ocr_cache_reuses_observations_and_rechecks_current_identity(client):
    from src.checks.plate_ocr import PLATE_OCR_CHECK
    from src.checks.base import CheckContext
    receipt=submit(client).json();calls=[]
    reader=SimpleNamespace(readtext=lambda path:calls.append(path) or [(None,'MH12AB1234',0.99)])
    with runtime_store.connection(api.DB_PATH) as conn:
        case=db.get_case(conn,receipt['case_id']);image=db.get_images_for_case(conn,case.case_id)[0]
        ctx=CheckContext(conn=conn,case=case,images=[image],perception={},config={'cache_ocr':True})
        first=PLATE_OCR_CHECK._check_one_image(ctx,image,reader,0.8)
        assert first.verdict==Verdict.PASS and not first.evidence['ocr_cache_reused']
        other=db.connect(api.DB_PATH)
        try:
            other.execute('BEGIN IMMEDIATE');other.rollback()
        finally:other.close()
        case.vehicle_registration='MH12ZZ9999'
        second=PLATE_OCR_CHECK._check_one_image(ctx,image,reader,0.8)
        assert second.verdict==Verdict.CONCERN and second.evidence['ocr_cache_reused']
        assert second.evidence['policy_registration']=='MH12ZZ9999'
        assert calls==[image.path]


def test_operations_does_not_hide_old_queued_work(client):
    receipt=submit(client).json()
    with runtime_store.connection(api.DB_PATH) as conn:
        oldest=runtime_store.get_job(conn,receipt['job_id']);oldest['created_at']=1;runtime_store.save_job(conn,oldest)
        for index in range(110):
            runtime_store.save_job(conn,{'job_id':'finished-'+str(index),'case_id':receipt['case_id'],
                'status':'completed','created_at':time.time(),'stage':'complete'})
    assert client.get('/v1/operations').status_code==401
    info=client.get('/v1/operations',headers=auth(client)).json()
    assert info['jobs_by_status']=={'completed':110,'queued':1}
    assert info['oldest_queued_age_seconds']>3600 and info['tenant_isolation'] is False


def test_duplicate_pool_count_avoids_decoding_corpus(client,monkeypatch):
    from src.checks.duplicate import DUPLICATE_CHECK
    from src.checks.base import CheckContext
    one=submit(client).json();two=submit(client).json()
    monkeypatch.setattr(db,'get_all_images',lambda conn:pytest.fail('Count hydrated every corpus embedding'))
    with runtime_store.connection(api.DB_PATH) as conn:
        case=db.get_case(conn,one['case_id'])
        ctx=CheckContext(conn=conn,case=case,images=[],perception={},config={})
        assert DUPLICATE_CHECK._compared_count(ctx)==4
        conn.execute('UPDATE images SET embedding=NULL WHERE case_id=?',(two['case_id'],))
        assert DUPLICATE_CHECK._compared_count(ctx)==0
