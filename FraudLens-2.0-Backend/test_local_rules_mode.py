"""Controlled local policy and real persistence paths; no provider HTTP."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from src import api,db,runtime_store,local_rules,llm
from src.risk_presentation import assessment_presentation
from test_partial_review import pipeline
from test_pilot_workflow import client,auth
from test_customer_workflow import customer,owned_submit,basis


def finding(check='plate_ocr',verdict='pass',state='completed',subject='vehicle',weight=.3):
    return dict(finding_id='controlled-'+check,check_id=check,execution_state=state,verdict=verdict,
        attributed_to=subject,registered_weight=weight,eligibility={'eligible':verdict=='concern' and state=='completed' and weight>0},
        explanation='Controlled policy scenario, not live AI.')


def scenario(rows,gaps=()):
    return dict(findings=rows,coverage=dict(material_gap_ids=list(gaps),state_counts={},requirements={
        'plate_ocr':dict(required=True,applicable=True,evidence_sufficient=not gaps)}))


@pytest.mark.parametrize('rows,gaps,band',[
    ([finding()],[],'LOW'),
    ([finding()],['incident_context'],'MEDIUM'),
    ([],[],'MEDIUM'),
    ([finding(state='not_run')],[],'MEDIUM'),
    ([finding(verdict='concern')],[],'MEDIUM'),
    ([finding(),finding('internal_duplicate','concern',weight=1)],[],'MEDIUM'),
    ([finding('plate_ocr','concern'),finding('internal_duplicate','concern',weight=1)],[],'HIGH'),
    ([finding(),finding('internal_duplicate','concern',weight=1),finding('external_corpus','concern',weight=1)],[],'MEDIUM'),
    ([finding(),finding('digital_edit','concern',weight=0)],[],'LOW'),
    ([finding(),finding('threshold_gaming','concern',subject='garage',weight=.1)],[],'LOW'),
    ([finding('plate_ocr','concern',state='failed'),finding('internal_duplicate','concern',weight=1)],['plate_ocr'],'MEDIUM'),
])
def test_local_policy(rows,gaps,band):
    explanation=scenario(rows,gaps);before=deepcopy(explanation)
    result=local_rules.classify(explanation)
    assert result['display_band']==band and result['method']=='Local rules assessment'
    assert explanation==before
    if result['coverage']['material_gap_ids']:assert local_rules.GAP_EXPLANATION in result['explanation']
    if band=='HIGH':assert result['review_recommendation']=='investigate'
    if band=='LOW':assert result['supporting_findings'] and all(row['verdict']=='pass' for row in result['supporting_findings'])


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_local_pipeline_never_initializes_provider_and_freezes_one_contract(client,pipeline,monkeypatch,kind):
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    monkeypatch.setattr(llm,'get_provider',lambda:pytest.fail('Local processing initialized Gemini'))
    owner=customer(client);receipt=owned_submit(client,owner,kind).json();run,provider=pipeline
    # pipeline fixture selected a paused provider before this assertion; forbid its use too.
    monkeypatch.setattr(llm,'get_provider',lambda:pytest.fail('Local processing initialized Gemini'))
    run(receipt['job_id'],receipt['case_id']);reviewer=auth(client);path='/v1/cases/'+receipt['case_id']
    job=client.get('/v1/jobs/'+receipt['job_id'],headers=reviewer).json()
    assert job['status']=='completed' and job['review_summary']['kind']=='local_rules'
    assert job['failures']==[] and provider.calls==0 and not job['provider_unavailable']
    contract=client.get(path+'/report',headers=reviewer).json()['assessment_presentation']
    assert contract['method']==local_rules.METHOD and contract['display_band'] in {'LOW','MEDIUM','HIGH'}
    assert contract['score'] is None and contract['complete'] and not contract['provisional']
    assert contract['processing_complete'] and contract['run_id']==receipt['job_id']
    public_job=client.get('/v1/jobs/'+receipt['job_id'],headers=owner).json()
    assert public_job['detail']==contract['status_label']
    assert 'message' not in public_job['review_summary'] and 'admin_label' not in public_job['review_summary']
    assert contract['explanation'] not in json.dumps(public_job)
    monkeypatch.setattr(local_rules,'classify',lambda *a:pytest.fail('Persisted assessment was recalculated'))
    row=next(row for row in client.get('/v1/cases',headers=reviewer).json()['items'] if row['case_id']==receipt['case_id'])
    assert row['assessment_presentation']==contract and row['processing_label']==contract['status_label']
    with runtime_store.connection(api.DB_PATH) as conn:
        assert runtime_store.get_job(conn,receipt['job_id'])['assessment_presentation']==contract
        saved=json.loads(conn.execute('SELECT payload FROM report_snapshots WHERE run_id=?',(receipt['job_id'],)).fetchone()[0])
        assert saved['assessment_presentation']==contract
    prepared=client.post(path+'/reports/prepare',headers=reviewer).json();url=path+'/reports/'+prepared['snapshot_id']+'/pdf'
    content=client.get(url,headers=reviewer).content
    assert content==client.get(url+'?download=true',headers=reviewer).content
    front=PdfReader(BytesIO(content)).pages[0].extract_text()
    for text in [contract['label'],local_rules.METHOD,contract['status_label']]:assert text in front
    assert 'AI failed' not in front and 'Partial analysis' not in front
    assert client.get(url,headers=owner).status_code==401
    assert client.get('/v1/customer/cases/'+receipt['case_id'],headers=owner).json()['processingDetail']==contract['status_label']
    payload={**basis(client,receipt['case_id'],reviewer),'action':'request_more_evidence','reason':'Controlled local review',
        'public_message':'Controlled local reviewer outcome.','requested_artifacts':['Current readable registration photograph']}
    assert client.post(path+'/action',headers=reviewer,json=payload).status_code==200
    assert client.get('/v1/customer/cases/'+receipt['case_id'],headers=owner).json()['publicNarrative']==payload['public_message']
    assert client.get(url,headers=reviewer).content==content


def test_ai_dependent_check_is_not_executed_or_passed():
    from src.checks.base import _run_one,CheckContext,REGISTRY
    from types import SimpleNamespace
    ctx=CheckContext(conn=None,case=SimpleNamespace(case_id='controlled',agent_type='claims'),images=[SimpleNamespace(image_id='fixture')],perception={},config={'assessment_mode':'local_rules','execution_states':True})
    results=_run_one(REGISTRY['damage_plausibility'],ctx)
    assert results and all(row.verdict.value=='inconclusive' and row.evidence['reason']=='ai_dependency_not_performed' for row in results)


@pytest.mark.parametrize('failure',['missing_file','database','check','snapshot'])
def test_local_infrastructure_failures_are_not_success(client,pipeline,monkeypatch,failure):
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    receipt=owned_submit(client,customer(client)).json();run,provider=pipeline
    if failure=='missing_file':
        from pathlib import Path
        with runtime_store.connection(api.DB_PATH) as conn:Path(db.get_images_for_case(conn,receipt['case_id'])[0].path).unlink()
    elif failure=='database':monkeypatch.setattr(db,'insert_finding',lambda *a:(_ for _ in ()).throw(RuntimeError('Controlled database failure')))
    elif failure=='snapshot':monkeypatch.setattr(api,'_snapshot_report',lambda *a:(_ for _ in ()).throw(OSError('Controlled snapshot failure')))
    else:
        from src.checks import REGISTRY
        monkeypatch.setattr(REGISTRY['internal_duplicate'],'run',lambda *a:(_ for _ in ()).throw(RuntimeError('Controlled check failure')))
    run(receipt['job_id'],receipt['case_id'])
    job=client.get('/v1/jobs/'+receipt['job_id'],headers=auth(client)).json()
    assert job['status']=='failed' and job['review_summary']['kind']=='failed' and job['failures']
    assert provider.calls==0


def test_no_local_publication_is_not_reconciled_as_complete(client,monkeypatch):
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    receipt=owned_submit(client,customer(client)).json()
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id'])
        assert runtime_store.reconciled_result_status(conn,job,True)=='interrupted'


def test_paused_provider_does_not_degrade_ready_local_mode(client,monkeypatch):
    from src import runtime_readiness
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    monkeypatch.setitem(api.app.state.capabilities,'validator','ready')
    monkeypatch.setattr(runtime_readiness,'provider_status',lambda *args:{'ready':False,'state':'paused'})
    assert client.get('/ready').status_code==200
    health=client.get('/health').json()
    assert health['status']=='ok' and health['capabilities']['provider']['state']=='paused'


@pytest.mark.parametrize('band',['LOW','MEDIUM','HIGH'])
def test_local_pdf_uses_saved_band_and_explanation(band,monkeypatch):
    from scripts.build_visual_report_samples import fixture
    from src.report_pdf import render_pdf
    rows=[finding()]
    if band=='MEDIUM':rows.append(finding('internal_duplicate','concern',weight=1))
    if band=='HIGH':rows=[finding('plate_ocr','concern'),finding('internal_duplicate','concern',weight=1)]
    explanation=scenario(rows)
    explanation.update(local_rules=local_rules.classify(explanation),policy_version=local_rules.VERSION,run_id='controlled-local',routing={'recorded_band':'desk_review'})
    report=fixture('claims','High' if band=='LOW' else 'Low')
    report.update(run_id='controlled-local',assessment_explanation=explanation,
        processing={'status':'completed','job_id':'controlled-local'})
    contract=local_rules.presentation(report);report['assessment_presentation']=contract
    monkeypatch.setattr(local_rules,'classify',lambda *args:pytest.fail('PDF recalculated the local assessment'))
    front=PdfReader(BytesIO(render_pdf(report,'controlled-local',1793070000))).pages[0].extract_text()
    assert contract['label'] in front and contract['explanation'] in front.replace('\n',' ')
    assert local_rules.METHOD in front and 'Partial analysis' not in front


@pytest.mark.parametrize('action',['approve','reject'])
def test_local_decisions_retain_explicit_human_review(client,pipeline,monkeypatch,action):
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    owner=customer(client);receipt=owned_submit(client,owner).json();run,_=pipeline
    run(receipt['job_id'],receipt['case_id']);reviewer=auth(client)
    path='/v1/cases/'+receipt['case_id']
    payload={**basis(client,receipt['case_id'],reviewer),'action':action,'reason':'Controlled independent local review.',
        'public_message':'Controlled local decision: '+action}
    assert client.post(path+'/action',headers=reviewer,json=payload).status_code==422
    payload['manual_review_override']=True
    assert client.post(path+'/action',headers=reviewer,json=payload).status_code==200
    assert client.get('/v1/customer/cases/'+receipt['case_id'],headers=owner).json()['outcome']==action


def test_local_preflight_refuses_live_probe(monkeypatch):
    from scripts import pilot_preflight
    import sys
    monkeypatch.setenv('FRAUDLENS_ASSESSMENT_MODE','local_rules')
    monkeypatch.setattr(sys,'argv',['pilot_preflight.py','--live'])
    monkeypatch.setattr(llm,'get_provider',lambda:pytest.fail('Local preflight attempted a provider probe'))
    with pytest.raises(SystemExit) as error:pilot_preflight.main()
    assert error.value.code==2


def test_local_engine_flag_cannot_enter_agent_branch(client,pipeline,monkeypatch):
    from src import orchestrator
    from src.agent.production_policy import production_policy
    receipt=owned_submit(client,customer(client)).json()
    monkeypatch.setattr(llm,'get_provider',lambda:pytest.fail('Local engine initialized Gemini'))
    monkeypatch.setattr(orchestrator,'get_provider',lambda:pytest.fail('Local engine entered its agent branch'))
    with runtime_store.connection(api.DB_PATH) as conn:
        decision=orchestrator.process_case(conn,receipt['case_id'],policy=production_policy('claims'),local_rules=True,persist=False)
    assert decision.llm_calls_count==0
    assert decision._assessment_explanation['assessment_type']=='local_rules'
