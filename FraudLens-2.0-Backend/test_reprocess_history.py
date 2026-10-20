"""Controlled ledger/worker fixtures only: no live calls or application DB writes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time

import pytest
from PIL import Image as PILImage
from scripts import reprocess_history as batch
from src import db,runtime_store
from src.models import AdminAction,AdminActionRecord,Case,Image


def ledger():
    return {'attempts':7,'stopped':'original stop retained','recoveries':[{'recovery_id':'fixture-recovery','status':'validation_authorized','allowance':12,'reserved':5,'validation_authorized_at':100.0}],
            'events':[{'attempt':index,'outcome':'success','recovery_id':'fixture-recovery','time':100.0+index,'completed_at':100.5+index} for index in range(4,8)]}


def validation(path):
    return {'ledger':str(path),'recovery_id':'fixture-recovery','observations':[
        {'workflow':'claims','case_id':'claims-fixture','run_id':'claims-fixture-run','status':'completed','converged':True,'vision_status':'parsed','vision_source':'fresh_provider','vision_attempt':4,'vision_attempts':[4],'agent_attempts':[5]},
        {'workflow':'underwriting','case_id':'underwriting-fixture','run_id':'underwriting-fixture-run','status':'completed','converged':True,'vision_status':'parsed','vision_source':'fresh_provider','vision_attempt':6,'vision_attempts':[6],'agent_attempts':[7]}]}


def audit_row(case_id='fixture-case',content_hash='a'*64):
    return {'case_id':case_id,'case_type':'claims','eligible_evidence':True,'blockers':[],'human_actions_preserved':1,
            'submitted_at':'2026-10-20T06:00:00+00:00','evidence':[{'content_hash':content_hash,'cache_compatibility':'requires_current_schema_validation'}]}


@pytest.fixture
def isolated(tmp_path):
    path=tmp_path/'batch.db';conn=db.connect(path);db.init_db(conn);runtime_store.init(conn);conn.commit()
    picture=tmp_path/'photo.png';buffer=BytesIO();PILImage.new('RGB',(32,32),'red').save(buffer,'PNG');picture.write_bytes(buffer.getvalue())
    content_hash=hashlib.sha256(picture.read_bytes()).hexdigest()
    for index in range(2):
        case_id='fixture-'+str(index)
        db.insert_case(conn,Case(case_id=case_id,claimant_id='fictional',garage_id='UNASSIGNED',claim_type='claims',status='closed_rejected'))
        db.save_image(conn,Image(image_id='image-'+str(index),case_id=case_id,path=str(picture),content_hash=content_hash,phash='a'*16,dhash='b'*16))
        db.insert_admin_action(conn,AdminActionRecord(case_id=case_id,admin_id='reviewer-fixture',action=AdminAction.REJECT,reason='Preserved original decision'))
    conn.commit()
    yield conn,content_hash
    conn.close()


def test_explicit_scope_and_budget_defer_all_822_without_modifying_ledger():
    records=[audit_row('case-'+str(index),hashlib.sha256(str(index).encode()).hexdigest()) for index in range(822)]
    state=ledger();before=json.dumps(state,sort_keys=True)
    plan=batch.make_plan(records,'bounded-fixture',scope='all',ledger=state,recovery_id='fixture-recovery')
    assert len(plan['cases'])==822 and plan['minimum_requests']==1644
    assert plan['budget_sufficient'] is False and all(row['outcome']=='budget_deferred' for row in plan['cases'])
    assert json.dumps(state,sort_keys=True)==before
    with pytest.raises(ValueError):batch.make_plan(records,'batch')
    with pytest.raises(ValueError):batch.make_plan(records,'batch',['not-audited-case'])


def test_unique_missing_vision_and_current_compatibility_estimates():
    records=[audit_row('one'),audit_row('two')]
    plan=batch.make_plan(records,'tiny-fixture',case_ids=['one','two'],ledger=ledger(),recovery_id='fixture-recovery')
    assert plan['minimum_requests']==3
    cached=batch.make_plan(records,'tiny-fixture',case_ids=['one','two'],ledger=ledger(),recovery_id='fixture-recovery',compatible={'a'*64:True})
    assert cached['minimum_requests']==2


def test_apply_refuses_822_before_loading_models_or_touching_cases(isolated,tmp_path,monkeypatch):
    conn,_content_hash=isolated;path=tmp_path/'original-ledger.json';batch.write_json(path,ledger())
    records=[audit_row('large-scope-'+str(index)) for index in range(822)]
    plan=batch.make_plan(records,'explicit-large-fixture',scope='all',ledger=ledger(),recovery_id='fixture-recovery')
    def forbidden(*args):raise AssertionError('Budget refusal must happen before cache/model work')
    monkeypatch.setattr(batch,'current_compatibility',forbidden)
    result=batch.supervise(conn,plan,tmp_path/'checkpoint.json',path,validation(path),'fixture-recovery')
    assert result['state']=='blocked_budget' and conn.execute('SELECT COUNT(*) FROM api_jobs').fetchone()[0]==0


def test_live_validation_gate_rejects_missing_workflow_cached_or_unrecorded_attempts(tmp_path):
    path=tmp_path/'original-ledger.json';proof=validation(path)
    batch.validation_gate(proof,ledger(),path,'fixture-recovery')
    for field,value in [('vision_source','request_cache'),('converged',False),('agent_attempts',[999])]:
        invalid=validation(path);invalid['observations'][1][field]=value
        with pytest.raises(ValueError):batch.validation_gate(invalid,ledger(),path,'fixture-recovery')
    proof['observations'].pop()
    with pytest.raises(ValueError):batch.validation_gate(proof,ledger(),path,'fixture-recovery')
    with pytest.raises(ValueError):batch.validation_gate(validation(path),ledger(),tmp_path/'replacement-ledger.json','fixture-recovery')
    assert batch.budget_remaining(ledger(),'wrong-recovery')==0


@pytest.mark.parametrize('status',['failed','probe_succeeded','probing','authorized'])
def test_saved_successful_proof_cannot_reopen_a_stopped_recovery(tmp_path,status):
    path=tmp_path/'original-ledger.json';state=ledger();state['recoveries'][0]['status']=status
    before=json.dumps(state,sort_keys=True)
    with pytest.raises(ValueError,match='not currently authorized'):
        batch.validation_gate(validation(path),state,path,'fixture-recovery')
    assert batch.budget_remaining(state,'fixture-recovery')==0
    assert json.dumps(state,sort_keys=True)==before


@pytest.mark.parametrize('invalid',['foreign_recovery','duplicate_event','historical_probe','missing_completion','timezone_missing','nonfinite_time'])
def test_validation_requests_require_current_recovery_success_and_fresh_times(tmp_path,invalid):
    path=tmp_path/'original-ledger.json';state=ledger()
    if invalid=='foreign_recovery':state['events'][0]['recovery_id']='unrelated-recovery'
    elif invalid=='duplicate_event':state['events'].append(dict(state['events'][0]))
    elif invalid=='historical_probe':state['events'][0]['time']=99.0
    elif invalid=='missing_completion':del state['events'][0]['completed_at']
    elif invalid=='timezone_missing':state['events'][0]['time']='2026-10-20T00:00:00'
    else:state['events'][0]['time']=float('nan')
    with pytest.raises(ValueError):batch.validation_gate(validation(path),state,path,'fixture-recovery')


def test_all_vision_attempts_are_validated_without_ignoring_extra_failed_request(tmp_path):
    path=tmp_path/'original-ledger.json';state=ledger();proof=validation(path)
    proof['observations'][0]['vision_attempts']=[4,8]
    with pytest.raises(ValueError):batch.validation_gate(proof,state,path,'fixture-recovery')
    state['events'].append({'attempt':8,'outcome':'failure:503','recovery_id':'fixture-recovery','time':108.0,'completed_at':108.5})
    with pytest.raises(ValueError):batch.validation_gate(proof,state,path,'fixture-recovery')
    state['events'][-1]['outcome']='success'
    with pytest.raises(ValueError):batch.validation_gate(proof,state,path,'fixture-recovery')
    state['attempts']=8
    batch.validation_gate(proof,state,path,'fixture-recovery')


@pytest.mark.parametrize('invalid',['shared_vision','shared_case','shared_run','duplicate_workflow','mismatched_first','boolean_attempt','missing_vision_list'])
def test_workflows_must_name_distinct_cases_runs_and_every_integer_stage_request(tmp_path,invalid):
    path=tmp_path/'original-ledger.json';proof=validation(path);first,second=proof['observations']
    if invalid=='shared_vision':second.update(vision_attempt=4,vision_attempts=[4])
    elif invalid=='shared_case':second['case_id']=first['case_id']
    elif invalid=='shared_run':second['run_id']=first['run_id']
    elif invalid=='duplicate_workflow':second['workflow']='claims'
    elif invalid=='mismatched_first':first['vision_attempt']=8
    elif invalid=='boolean_attempt':first['agent_attempts']=[True]
    else:del first['vision_attempts']
    with pytest.raises(ValueError):batch.validation_gate(proof,ledger(),path,'fixture-recovery')


def test_enqueue_is_idempotent_retrospective_and_preserves_case_human_analysis(isolated):
    conn,content_hash=isolated
    plan=batch.make_plan([audit_row('fixture-0',content_hash)],'fixture-batch',case_ids=['fixture-0'],ledger=ledger(),recovery_id='fixture-recovery')
    entry=plan['cases'][0]
    job=batch.enqueue_one(conn,plan,entry);again=batch.enqueue_one(conn,plan,entry)
    assert job['job_id']==again['job_id']==batch.run_id('fixture-batch','fixture-0')
    assert job['retrospective'] and job['preserve_human_basis'] and job['prior_human_basis']['reviewer_action']=='reject'
    assert db.get_case(conn,'fixture-0').status=='closed_rejected'
    assert conn.execute('SELECT COUNT(*) FROM admin_actions').fetchone()[0]==2
    assert conn.execute('SELECT COUNT(*) FROM api_jobs').fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM agent_decisions').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==0
    assert len([event for event in db.get_audit_events_for_case(conn,'fixture-0') if event.event_type=='historical_reprocessing_requested'])==1


def test_apply_budget_gate_checkpoint_and_resume_without_duplicate_jobs(isolated,tmp_path,monkeypatch):
    conn,content_hash=isolated;path=tmp_path/'original-ledger.json';batch.write_json(path,ledger());before=path.read_bytes()
    plan=batch.make_plan([audit_row('fixture-0',content_hash)],'fixture-batch',case_ids=['fixture-0'],ledger=ledger(),recovery_id='fixture-recovery')
    checkpoint=tmp_path/'checkpoint.json'
    def complete_worker(_delay):
        job=runtime_store.get_job(conn,plan['cases'][0]['run_id']);job.update(status='completed',perception_sources={'fresh_provider':1},adjudication_sources=[{'source':'fresh_provider'}]);runtime_store.save_job(conn,job);conn.commit()
    monkeypatch.setattr(batch.time,'sleep',complete_worker)
    result=batch.supervise(conn,plan,checkpoint,path,validation(path),'fixture-recovery',max_seconds=5,poll_seconds=.01)
    assert result['state']=='completed' and result['source_counts']=={'vision_fresh_provider':1,'agent_fresh_provider':1}
    assert batch.read_json(checkpoint)['state']=='completed'
    assert path.read_bytes()==before
    resumed=batch.supervise(conn,batch.read_json(checkpoint),checkpoint,path,validation(path),'fixture-recovery',max_seconds=5)
    assert resumed['state']=='completed' and conn.execute('SELECT COUNT(*) FROM api_jobs').fetchone()[0]==1


def test_pause_rate_limit_backoff_and_repeated_systemic_stop(isolated,tmp_path):
    conn,content_hash=isolated;path=tmp_path/'original-ledger.json';batch.write_json(path,ledger())
    plan=batch.make_plan([audit_row('fixture-0',content_hash),audit_row('fixture-1',content_hash)],'failure-fixture',scope='all',ledger=ledger(),recovery_id='fixture-recovery')
    pause=tmp_path/'PAUSE';pause.write_text('fixture')
    result=batch.supervise(conn,plan,tmp_path/'checkpoint.json',path,validation(path),'fixture-recovery',pause_path=pause)
    assert result['state']=='paused' and conn.execute('SELECT COUNT(*) FROM api_jobs').fetchone()[0]==0
    pause.unlink()
    for entry in plan['cases']:
        job=batch.enqueue_one(conn,plan,entry);job.update(status='failed',root_failure_detail={'error_category':'provider_http_error'});runtime_store.save_job(conn,job);conn.commit()
    result=batch.supervise(conn,plan,tmp_path/'checkpoint.json',path,validation(path),'fixture-recovery')
    assert result['state']=='stopped_systemic_failure' and result['systemic_failures']==2
    job=runtime_store.get_job(conn,plan['cases'][0]['run_id']);job['root_failure_detail']['error_category']='provider_quota_or_rate_limit';runtime_store.save_job(conn,job);conn.commit()
    result=batch.supervise(conn,plan,tmp_path/'checkpoint.json',path,validation(path),'fixture-recovery')
    assert result['state']=='paused_rate_limit' and result['resume_after']>time.time()
