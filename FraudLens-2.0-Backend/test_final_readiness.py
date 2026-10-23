"""Release regressions: fixtures never contact a provider or pilot database."""
import json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_normal_operation import normal,run_call
from test_pilot_workflow import client,initial_files
from src import operating_policy as op,session_budget,photo_admission as gate


@pytest.mark.parametrize('mode,circuit,expected',[('normal',None,'locally_enabled_unverified'),('paused',None,'paused'),
    ('normal',{'category':'transient','retry_at':time.time()+3600},'circuit_open'),
    ('normal',{'category':'transient','retry_at':0},'recovery_pending')])
def test_provider_readiness_reads_controls_without_mutating_or_calling(normal,mode,circuit,expected):
    from src.runtime_readiness import provider_status
    state=json.loads(normal.read_text());state['operation'].update(mode=mode,circuit=circuit);normal.write_text(json.dumps(state))
    before=normal.read_bytes();result=provider_status(configured=True)
    assert result['state']==expected and result['ready']==(expected=='locally_enabled_unverified')
    assert normal.read_bytes()==before


def test_camera_exif_nul_padding_preserves_original_bytes(tmp_path):
    import io,piexif,hashlib
    from PIL import Image
    from src import ingest
    content=io.BytesIO()
    Image.new('RGB',(96,96),'red').save(content,format='JPEG',exif=piexif.dump({'Exif':{piexif.ExifIFD.UserComment:b'ASCII\x00\x00\x00original comment\x00'}}))
    path=tmp_path/'camera.jpg';path.write_bytes(content.getvalue());before=hashlib.sha256(path.read_bytes()).hexdigest()
    prepared=ingest.prepare_image(path)
    assert prepared['exif']['Exif']['UserComment']=='ASCIIoriginal comment'
    assert prepared['content_hash']==before==hashlib.sha256(path.read_bytes()).hexdigest()
    assert '\\u0000' not in json.dumps(prepared['exif'])


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_fallback_is_never_labelled_as_a_model_decision(kind):
    from src import report_pdf
    from src.risk_presentation import assessment_presentation
    from scripts.build_visual_report_samples import fixture
    from pypdf import PdfReader
    from io import BytesIO
    from src.assessment_explanation import explain_assessment
    from src.agent.production_policy import production_policy
    from src.models import Case,AgentDecision,RiskBand,Recommendation
    decision=AgentDecision(case_id='fallback-fixture',risk_band=RiskBand.DESK_REVIEW,recommendation=Recommendation.ESCALATE,confidence=0.0,summary='Controlled system fallback; no model result.')
    saved=explain_assessment(Case(case_id='fallback-fixture',claimant_id='fictional',garage_id='UNASSIGNED',claim_type='fixture',agent_type=kind),[],decision,production_policy(kind),converged=False,run_id='fixture-run')
    assert saved['routing']['source']=='fallback' and saved['routing']['model_recommendation'] is None
    assert decision.recommendation is Recommendation.ESCALATE
    report=fixture(kind,'Low',category_only=True)
    report['processing']['status']='failed'
    routing=report['assessment_explanation']['routing']
    routing.update(source='fallback',converged=False,model_recommendation='approve',effective_recommendation='desk_review')
    # A legacy erroneous label remains in the immutable source; display must
    # honor its actual fallback source rather than inventing a model decision.
    report['assessment_presentation']=assessment_presentation(report)
    assert report['assessment_presentation']['model_recommendation'] is None
    assert report['assessment_presentation']['category'] is None
    report['report_template_version']=report_pdf.RENDERER_VERSION
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(report_pdf.render_pdf(report,'fixture-fallback',1792690000))).pages)
    assert 'No converged model decision' in text
    assert 'Model output (unchanged)' not in text


def test_loopback_browser_preflight(monkeypatch):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient
    from src import api
    monkeypatch.delenv('CORS_ORIGINS',raising=False)
    app=FastAPI();app.add_middleware(CORSMiddleware,allow_origins=api._cors_origins(),allow_methods=['*'],allow_headers=['*'])
    response=TestClient(app).options('/v1/customer/auth/register',headers={
        'Origin':'http://127.0.0.1:5173','Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'content-type'})
    assert response.status_code==200
    assert response.headers['access-control-allow-origin']=='http://127.0.0.1:5173'
    monkeypatch.setenv('CORS_ORIGINS','https://explicit.example.test')
    assert api._cors_origins()==['https://explicit.example.test']


def test_new_task_preserves_previous_allowance_and_limits(normal):
    op.control('finish-task',operator='fixture',reason='close earlier task')
    before=json.loads(normal.read_text())
    op.begin_task(expected_attempts=2,operator='fixture',reason='explicit new 30-attempt release validation')
    after=json.loads(normal.read_text())
    assert after['events']==before['events'] and after['stopped']==before['stopped']
    assert after['operation']['task_history'][-1]==before['operation']['task']
    assert after['operation']['limits']==before['operation']['limits']
    assert after['operation']['task']['ceiling']==32
    with pytest.raises(ValueError):op.begin_task(expected_attempts=2,operator='fixture',reason='cannot overlap')
    op.control('finish-task',operator='fixture',reason='release complete')
    assert json.loads(normal.read_text())['operation']['mode']=='normal'


def test_expired_task_cannot_spend_or_reset_history(normal):
    session_budget._change(lambda s:s['operation']['task'].update(expires_at=time.time()-1))
    with pytest.raises(session_budget.ProviderCircuitOpen):run_call()
    assert json.loads(normal.read_text())['attempts']==2


def test_isolated_schema_scope_closes_with_task(normal,monkeypatch):
    from src import validation_budget
    op.control('finish-task',operator='fixture',reason='previous task done')
    op.begin_task(expected_attempts=2,operator='fixture',reason='isolated real validation',validation_schema='fraudlens_validation_fixture')
    monkeypatch.setenv('FRAUDLENS_PG_SCHEMA','fraudlens_validation_fixture')
    with validation_budget.execution('fraudlens_validation_fixture',dict(case_id='fictional',job_id='isolated-run')):
        number=session_budget.reserve('fixture');session_budget.outcome(None,attempt=number)
    op.control('finish-task',operator='fixture',reason='no residual isolated grant')
    with validation_budget.execution('fraudlens_validation_fixture',dict(case_id='fictional',job_id='isolated-run')):
        with pytest.raises(session_budget.ProviderCircuitOpen):session_budget.reserve('fixture')


def test_blurred_file_requests_retake(tmp_path):
    import io
    from PIL import Image,ImageDraw,ImageFilter
    image=Image.new('RGB',(256,256),'white');ImageDraw.Draw(image).rectangle((50,50,200,200),fill='gray')
    buffer=io.BytesIO();image.filter(ImageFilter.GaussianBlur(24)).save(buffer,format='PNG')
    with pytest.raises(gate.InvalidPhoto,match='blurred'):
        gate.decode(buffer.getvalue(),'image/png',tmp_path/'unused.png')


def test_vehicle_detail_relevance_does_not_claim_ocr_success(monkeypatch,tmp_path):
    import numpy as np
    from src import vehicle_gate
    from src.checks import plate_ocr
    class Embedder:
        def embed(self,p):return [1.,0.]
        def embed_texts(self,prompts):return [[1.,0.] if i<2 else [0.,1.] for i in range(len(prompts))]
    monkeypatch.setattr(vehicle_gate,'_default_embedder',Embedder());monkeypatch.setattr(gate,'_texts',{})
    monkeypatch.setattr(plate_ocr,'get_reader',lambda:(_ for _ in ()).throw(AssertionError('OCR belongs to assessment, not admission')))
    for slot in ['front_registration','odometer']:
        state,reason,embedding,scores=gate.infer(tmp_path/'fixture',slot)
        assert state=='accepted' and scores['quality_readable'] is None
        assert scores['quality_check']=='extraction_deferred_to_assessment' and not scores['identity_verified']


def test_utc_offset_required_for_new_initial_application(client):
    response=client.post('/v1/cases',data={'agent_type':'claims','vehicle_registration':'MH12EX1203',
        'declared_time':'2026-10-20T12:00:00','photo_slots':list(gate.SLOTS['claims'])},files=initial_files())
    assert response.status_code==422 and response.json()['code']=='INCIDENT_TIMEZONE_REQUIRED'


def test_warming_validator_is_explicit_retryable_without_case(client):
    from test_customer_workflow import customer
    from src import api
    owner=customer(client);api.app.state.capabilities['validator']='warming'
    try:
        response=client.post('/v1/photos/validate',headers=owner,data={'agent_type':'claims','slot':'vehicle_overview'},
            files={'image':initial_files()[0][1]})
        assert response.status_code==503 and response.json()['code']=='VALIDATOR_UNAVAILABLE'
        ready=client.get('/ready');assert ready.status_code==503
        assert ready.json()['capabilities']['validator']=='warming'
    finally:api.app.state.capabilities['validator']='lazy'


def test_excluded_model_not_loaded_in_normal_run(monkeypatch):
    from src.checks.base import _run_one,CheckContext
    from src.checks.ai_detection import AI_GENERATION_CHECK
    from src.models import Case
    monkeypatch.setattr(AI_GENERATION_CHECK,'run',lambda ctx:(_ for _ in ()).throw(AssertionError('Research model must not load')))
    ctx=CheckContext(conn=None,case=SimpleNamespace(case_id='fictional',agent_type='claims'),
        images=[SimpleNamespace(image_id='fixture')],perception={},config={'skip_experimental_models':True})
    results=_run_one(AI_GENERATION_CHECK,ctx)
    assert len(results)==1 and results[0].evidence['execution_state']=='not_run' and results[0].confidence==0


def test_required_odometer_gap_is_not_risk_and_unrelated_ocr_cannot_clear_it():
    from src.input_coverage import assess_inputs
    config={'odometer_photo_required':True,'required_odometer_image_ids':['odo-photo']}
    row={'finding_id':'ocr-fixture','check_id':'plate_ocr','observed_values':{'image_id':'unrelated-photo','raw_ocr_strings':[{'text':'ODO 123456','confidence':.9}]}}
    assert not assess_inputs('underwriting',[row],config)['odometer_readability']['evidence_sufficient']
    row['observed_values']['image_id']='odo-photo'
    assert assess_inputs('underwriting',[row],config)['odometer_readability']['evidence_sufficient']
    row['observed_values']['raw_ocr_strings']=[]
    result=assess_inputs('underwriting',[row],config)['odometer_readability']
    assert not result['evidence_sufficient'] and 'not evidence of fraud' in result['reason']


def test_underwriting_actual_intake_slots_reach_material_guard(client,monkeypatch):
    from src import api,db,orchestrator
    from src.agent.production_policy import production_policy
    from src.models import AgentDecision,Recommendation,RiskBand
    receipt=client.post('/v1/cases',data={'agent_type':'underwriting','vehicle_registration':'MH12EX1203',
        'photo_slots':list(gate.SLOTS['underwriting'])},files=initial_files('underwriting')).json()
    case_id=receipt['case_id'];model=AgentDecision(case_id=case_id,risk_band=RiskBand.CLEAR,recommendation=Recommendation.APPROVE,confidence=0.0,
        summary='Controlled original model clearance; not a live assessment.')
    monkeypatch.setattr(orchestrator,'run_checks',lambda *a,**k:[])
    monkeypatch.setattr(orchestrator,'adjudicate',lambda *a,**k:SimpleNamespace(decision=model,trace_dicts=lambda:[],converged=True))
    conn=db.connect(api.DB_PATH)
    try:
        decision=orchestrator.process_case(conn,case_id,policy=production_policy('underwriting'),provider=object(),
            run_id=receipt['job_id'],persist=False)
        explanation=decision._assessment_explanation
        assert explanation['coverage']['requirements']['odometer_readability']['evidence_ids']
        assert not explanation['coverage']['material_complete']
        assert explanation['routing']['model_recommendation']=='approve'
        assert explanation['routing']['effective_recommendation']=='request_evidence'
    finally:conn.close()
