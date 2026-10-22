"""Offline only: original audit preservation and normal operating boundaries."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
import pytest
from src import session_budget as budget, operating_policy as op, validation_budget
from src.quota_budget import QuotaBudgetExhausted
from test_validation_budget import scoped


@pytest.fixture
def normal(tmp_path,monkeypatch):
    path=tmp_path/'session.json'
    old={'attempts':2,'consecutive_failures':0,'stopped':'old diagnostic stop',
         'events':[dict(attempt=i+1,model='fixture',time=time.time(),outcome='success') for i in range(2)]}
    # Migration requires real validated provenance; mock that prerequisite only.
    old['operation']=dict(version=op.VERSION,schema='fraudlens_pilot',mode='normal',limits=dict(op.DEFAULTS),
                          circuit=None,audit=[],task=dict(base_attempts=2,ceiling=32,status='active'))
    path.write_text(json.dumps(old));monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER',str(path))
    monkeypatch.setenv('FRAUDLENS_PG_SCHEMA','fraudlens_pilot')
    monkeypatch.delenv('FRAUDLENS_VALIDATION_ID',raising=False);monkeypatch.delenv('FRAUDLENS_RECOVERY_ID',raising=False)
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','15')
    return path


def run_call(case='case-fictional',error=None):
    with validation_budget.execution('fraudlens_pilot',dict(job_id='run-fixture',case_id=case)):
        attempt=budget.reserve('fixture-model');budget.outcome(error,attempt=attempt)
        return attempt


def test_old_cap_history_and_task_ceiling_survive_restart(normal):
    initial=json.loads(normal.read_text())
    # Across days/cases, task cap remains independent of daily cap.
    def change(s):s['operation']['limits']['daily_attempts']=100
    budget._change(change)
    for i in range(30):run_call('fictional-'+str(i))
    assert json.loads(normal.read_text())['events'][:2]==initial['events']
    assert json.loads(normal.read_text())['stopped']=='old diagnostic stop'
    with pytest.raises(QuotaBudgetExhausted):run_call('next')
    op.control('finish-task',operator='fixture',reason='no background task')
    assert run_call('normal-next')==33


def test_case_daily_manual_stop_and_unscoped(normal):
    with pytest.raises(budget.ProviderCircuitOpen):budget.reserve('fixture')
    for _ in range(16):run_call()
    with pytest.raises(QuotaBudgetExhausted):run_call()
    op.control('pause',operator='fixture',reason='pause')
    with pytest.raises(budget.ProviderCircuitOpen):run_call('other')
    op.control('resume',operator='fixture',reason='resume')
    budget._change(lambda s:s['operation']['limits'].update(daily_attempts=18))
    with pytest.raises(QuotaBudgetExhausted):run_call('other')


def test_task_ceiling_does_not_renew_when_prior_requests_are_on_previous_day(normal):
    for i in range(16):run_call('before-midnight-'+str(i))
    # Controlled persisted state representing yesterday; no production ledger.
    def previous_day(s):
        for event in s['events'][2:]:event['time']-=86400
    budget._change(previous_day)
    for i in range(14):run_call('after-midnight-'+str(i))
    with pytest.raises(QuotaBudgetExhausted):run_call('thirty-first-new-attempt')


def test_transient_cooldown_one_probe_and_reopen(normal,monkeypatch):
    class Transient(Exception):code=503
    run_call(error=Transient());run_call(error=Transient())
    with pytest.raises(budget.ProviderCircuitOpen):run_call()
    budget._change(lambda s:s['operation']['circuit'].update(retry_at=0))
    run_call(error=Transient())
    assert json.loads(normal.read_text())['events'][-1]['half_open'] is True
    with pytest.raises(budget.ProviderCircuitOpen):run_call()
    budget._change(lambda s:s['operation']['circuit'].update(retry_at=0))
    run_call()
    assert json.loads(normal.read_text())['operation']['circuit'] is None


@pytest.mark.parametrize('code',[400,401,403,404,429])
def test_nontransient_never_automatically_recovers(normal,code):
    class Rejected(Exception):pass
    e=Rejected();e.code=code;run_call(error=e)
    budget._change(lambda s:s['operation']['circuit'].update(retry_at=0))
    with pytest.raises(budget.ProviderCircuitOpen):run_call()


def test_concurrent_workers_reserve_only_one_probe(normal):
    budget._change(lambda s:s['operation'].update(circuit=dict(category='transient',retry_at=0)))
    charges=[]
    def reserve(_):
        try:
            with validation_budget.execution('fraudlens_pilot',dict(job_id='run',case_id='case')):
                return budget.reserve('fixture',charge=lambda:charges.append(1))
        except budget.ProviderCircuitOpen:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(reserve,range(4)))
    assert len([r for r in results if r])==1
    assert charges==[1]


def test_migration_append_only_with_dynamic_start_count(normal):
    state=json.loads(normal.read_text());state.pop('operation')
    # Valid existing successful isolated grant/event audit as stored by v1.
    # Use the policy prerequisite without manufacturing provider execution.
    for event in state['events']:
        event['receipt']={'operation':'agent'}
        event['validation_id']='fixture-only'
    # Direct migration callback can be isolated from ledger validation here.
    holder=deepcopy(state)
    import unittest.mock
    with unittest.mock.patch.object(budget,'_change',lambda fn:fn(holder)):
        op.migrate(schema='fraudlens_pilot',expected_attempts=2,operator='fixture',reason='authorized transition')
    assert holder['events']==state['events'] and holder['stopped']==state['stopped']
    assert holder['operation']['task']['ceiling']==32


def test_optional_experiments_do_not_clear_material_identity_gap():
    from src.coverage_policy import assess
    from src.checks import REGISTRY
    expected=['plate_ocr','exif_metadata','c2pa_credentials','ai_generation']
    states=dict.fromkeys(expected,'inconclusive')
    result=assess(expected,states,[],REGISTRY)
    assert result['material_gap_ids']==['plate_ocr']
    states['plate_ocr']='completed'
    assert assess(expected,states,[],REGISTRY)['material_complete']


def test_empty_history_is_not_a_clean_pass():
    from src.coverage_policy import assess
    from src.checks import REGISTRY
    r=assess(['internal_duplicate'],{'internal_duplicate':'inconclusive'},[
        dict(check_id='internal_duplicate',observed_values={'images_compared':0})],REGISTRY)
    assert r['material_complete'] and not r['requirements']['internal_duplicate']['applicable']
    assert not r['requirements']['internal_duplicate']['execution_state']=='completed'


def test_normal_receipt_restart_reuses_exact_response_without_http(normal,monkeypatch):
    from google import genai
    import httpx
    from src import llm
    original=genai.Client;requests=[]
    def handler(request):
        requests.append(1)
        return httpx.Response(200,json={'responseId':'fixture-receipt','modelVersion':'fixture-serving',
            'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':'{"saved":true}'}]}}]})
    def factory(**kwargs):
        assert kwargs['http_options'].retry_options.attempts==1
        kwargs['http_options'].client_args['transport']=httpx.MockTransport(handler)
        return original(**kwargs)
    monkeypatch.setattr(genai,'Client',factory);monkeypatch.setattr(op,'pace',lambda:None)
    provider=llm.GeminiProvider(model='gemini-3.5-flash',api_key='offline-placeholder',request_profile='gemini3_defaults_v2')
    messages=[{'role':'user','content':'Fictional offline fixture'}]
    try:
        with validation_budget.execution('fraudlens_pilot',dict(job_id='fixture-run',case_id='fixture-case')):
            first=provider.chat(messages)
            provider.close()
            provider=llm.GeminiProvider(model='gemini-3.5-flash',api_key='offline-placeholder',request_profile='gemini3_defaults_v2')
            second=provider.chat(messages)
        assert first.text==second.text and second.cached and len(requests)==1
        assert second.raw['request_provenance']['source']=='response_checkpoint'
        assert json.loads(normal.read_text())['events'][-1]['receipt']['provider_request_id']=='fixture-receipt'
    finally:provider.close()


def test_received_reply_with_changed_restart_inputs_blocks_new_inference(normal,monkeypatch):
    from google import genai
    from src import llm
    from src.provider_receipts import ReceiptPersistenceError
    import httpx
    original=genai.Client;requests=[]
    def handler(request):
        requests.append(1)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]})
    def factory(**kwargs):
        kwargs['http_options'].client_args['transport']=httpx.MockTransport(handler);return original(**kwargs)
    monkeypatch.setattr(genai,'Client',factory);monkeypatch.setattr(op,'pace',lambda:None)
    first=llm.GeminiProvider(api_key='offline-placeholder');second=llm.GeminiProvider(api_key='offline-placeholder')
    try:
        with validation_budget.execution('fraudlens_pilot',dict(job_id='run',case_id='case')):
            first.chat([{'role':'user','content':'Original saved finding IDs'}])
            with pytest.raises(ReceiptPersistenceError):second.chat([{'role':'user','content':'Different regenerated finding IDs'}])
        assert requests==[1]
    finally:first.close();second.close()


def test_local_receipt_failure_does_not_retry_or_open_provider_circuit(normal,monkeypatch):
    from google import genai
    from src import llm
    from src.provider_receipts import ReceiptPersistenceError
    from pathlib import Path
    import httpx
    original=genai.Client;requests=[];write=Path.write_text
    def handler(request):
        requests.append(1)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]})
    def factory(**kwargs):
        kwargs['http_options'].client_args['transport']=httpx.MockTransport(handler);return original(**kwargs)
    def failed(self,*args,**kwargs):
        if self.parent.name=='responses':raise OSError('Controlled local storage failure')
        return write(self,*args,**kwargs)
    monkeypatch.setattr(genai,'Client',factory);monkeypatch.setattr(op,'pace',lambda:None);monkeypatch.setattr(Path,'write_text',failed)
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    try:
        with validation_budget.execution('fraudlens_pilot',dict(job_id='run',case_id='case')):
            for _ in range(2):
                with pytest.raises(ReceiptPersistenceError):provider.chat([{'role':'user','content':'Fixture'}])
        s=json.loads(normal.read_text());assert s['operation']['circuit'] is None and requests==[1]
        assert s['events'][-1]['receipt'] and s['events'][-1]['request_contract']
    finally:provider.close()


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_saved_model_approval_guard_and_pdf_consistency(kind):
    from scripts.build_visual_report_samples import fixture
    from src import report_pdf
    from src.risk_presentation import assessment_presentation
    from pypdf import PdfReader
    from io import BytesIO
    report=fixture(kind,'Low',category_only=True)
    exp=report['assessment_explanation']
    assert exp['routing']['recorded_band']=='clear'
    assert exp['coverage']['material_complete']
    assert report['assessment_presentation']['category']=='Low'
    assert report['assessment_presentation']['score'] is None
    # Saved output is retained; the deterministic guard is a distinct field.
    exp['coverage']['material_complete']=False;exp['coverage']['material_gap_ids']=['plate_ocr']
    exp['routing'].update(model_recommendation='approve',effective_recommendation='request_evidence',guard_applied=True)
    report['assessment_presentation']=assessment_presentation(report)
    assert report['assessment_presentation']['category'] is None
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(report_pdf.render_pdf(report,'fixture-snapshot',1792640000))).pages)
    assert 'Assessment incomplete' in text and 'request evidence' in text
    assert 'Numeric score: not computed' in text


def test_underwriting_not_in_claims_batch_plan():
    from scripts.claims_batch import plan
    cases=[dict(case_id='fictional-'+kind,case_type=kind,evidence=[],eligible_evidence=False,
                blockers=['no_evidence'],analysis_state='legacy_no_durable_run') for kind in ['claims','underwriting']]
    result=plan(cases,'offline-batch')
    assert len(result['cases'])==1 and result['cases'][0]['case_id']=='fictional-claims'


def test_migration_preserves_real_ledger_shape_and_closed_grant(scoped,monkeypatch):
    path,_,grant,job=scoped
    with validation_budget.execution('fraudlens_validation_fixture',job):
        for _ in range(2):
            n=budget.reserve('fixture');budget.save_receipt(n,{'operation':'agent'});budget.outcome(attempt=n)
    validation_budget.close(grant,'Offline fixture complete')
    monkeypatch.delenv('FRAUDLENS_VALIDATION_ID');monkeypatch.setenv('FRAUDLENS_PG_SCHEMA','fraudlens_pilot')
    before=json.loads(path.read_text())
    op.migrate(schema='fraudlens_pilot',expected_attempts=9,operator='fixture',reason='Controlled migration')
    after=json.loads(path.read_text());budget._validate_state(after)
    for key in ('events','recoveries','validation_grants','stopped','budget_revisions'):
        assert after[key]==before[key]
    assert run_call()==10


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_material_guard_is_saved_without_rewriting_model_decision(kind):
    from scripts.build_visual_report_samples import fixture
    from src.models import Finding,Case,AgentDecision,Recommendation,RiskBand,CheckCategory,Verdict
    from src.assessment_explanation import explain_assessment
    from src.agent.production_policy import production_policy
    report=fixture(kind,'Low',category_only=True)
    rows=[Finding(**{**r,'category':CheckCategory(r['category']),'verdict':Verdict(r['verdict']),'evidence':dict(r['evidence'])}) for group in report['findings_by_category'].values() for r in group]
    for row in rows:
        if row.check_id=='plate_ocr':row.evidence['execution_state']='inconclusive';row.verdict='inconclusive'
    decision=AgentDecision(case_id='fictional',recommendation=Recommendation.APPROVE,risk_band=RiskBand.CLEAR,summary='Original model recommendation',confidence=.5)
    case=Case(case_id='fictional',claimant_id='fixture',garage_id='UNASSIGNED',claim_type='inspection',agent_type=kind)
    explanation=explain_assessment(case,rows,decision,production_policy(kind),converged=True,run_id='fixture',use_agent=True)
    assert decision.recommendation==Recommendation.APPROVE and decision.risk_band==RiskBand.CLEAR
    assert explanation['routing']['effective_recommendation']=='request_evidence'
    assert explanation['coverage']['material_gap_ids']==['plate_ocr']
