"""Scoped development-budget and SDK receipt regressions: no external HTTP."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

from google import genai
import httpx
import pytest

from src import session_budget, validation_budget, llm
from src.agent import tools
from src.agent.engine import parse_decision


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    state = {'attempts': 7, 'consecutive_failures': 0,
        'stopped': 'configuration failure or repeated provider failures',
        'events': [{'attempt': i, 'model': 'gemini-3.5-flash', 'time': i, 'outcome': 'success'} for i in range(1,8)],
        'recoveries': [{'recovery_id': 'prior', 'status': 'probe_succeeded', 'kind': 'request_schema_correction',
            'allowance': 1, 'reserved': 1, 'base_attempts': 6}]}
    state['events'][-1]['recovery_id'] = 'prior'
    path = tmp_path/'session.json'; path.write_text(json.dumps(state))
    monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER', str(path))
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT', '15')
    monkeypatch.setenv('FRAUDLENS_PG_SCHEMA', 'fraudlens_validation_fixture')
    monkeypatch.setenv('GEMINI_QUOTA_BUDGET', str(tmp_path/'quota.json'))
    monkeypatch.setenv('FRAUDLENS_RESPONSE_DIR', str(tmp_path/'responses'))
    grant = validation_budget.authorize('fraudlens_validation_fixture', operator='fixture',
        reason='Explicit controlled authorization', expires_at=time.time()+3600)
    monkeypatch.setenv('FRAUDLENS_VALIDATION_ID', grant)
    job = {'job_id': 'run-claims', 'case_id': 'case-fictional', 'status': 'queued'}
    validation_budget.bind_job(grant, 'fraudlens_validation_fixture', job, 'claims')
    return path, state, grant, job


def test_exact_thirty_new_reservations_preserve_seven_historical_events(scoped):
    path, old, grant, job = scoped
    with validation_budget.execution('fraudlens_validation_fixture', job):
        for _ in range(30): session_budget.outcome(attempt=session_budget.reserve('gemini-3.5-flash'))
        with pytest.raises(session_budget.QuotaBudgetExhausted): session_budget.reserve('gemini-3.5-flash')
    state = json.loads(path.read_text())
    assert state['attempts'] == 37 and state['events'][:7] == old['events']
    assert state['recoveries'] == old['recoveries'] and state['stopped'] == old['stopped']
    assert state['validation_grants'][0]['reserved'] == 30
    assert state['budget_revisions'][0]['old_ceiling'] == 15
    validation_budget.close(grant, 'Controlled task finished')
    with validation_budget.execution('fraudlens_validation_fixture', job):
        with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()


@pytest.mark.parametrize('violation', ['no_context', 'schema', 'run', 'case', 'expired', 'closed', 'normal_worker'])
def test_scope_expiry_and_close_fail_closed(scoped, monkeypatch, violation):
    path, _, grant, job = scoped
    target = dict(job); schema = 'fraudlens_validation_fixture'
    if violation == 'schema': schema = 'fraudlens_pilot'
    if violation == 'run': target['job_id'] = 'unbound'
    if violation == 'case': target['case_id'] = 'other-case'
    if violation == 'expired':
        future = time.time()+90000
        monkeypatch.setattr(validation_budget.time, 'time', lambda: future)
    if violation == 'closed': validation_budget.close(grant, 'Finished early')
    if violation == 'normal_worker': monkeypatch.delenv('FRAUDLENS_VALIDATION_ID')
    before = path.read_bytes()
    if violation == 'no_context':
        with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()
    else:
        with validation_budget.execution(schema, target):
            with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()
    assert path.read_bytes() == before


@pytest.mark.parametrize('codes', [[400], [401], [403], [404], [429], [503,503]])
def test_provider_stop_rules_and_no_extra_calls(scoped, codes):
    path, _, _, job = scoped
    with validation_budget.execution('fraudlens_validation_fixture', job):
        for code in codes: session_budget.outcome(SimpleNamespace(code=code), attempt=session_budget.reserve('gemini-3.5-flash'))
        with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()
    assert json.loads(path.read_text())['validation_grants'][0]['status'] == 'stopped'


def test_lower_operator_kill_limit_is_not_overridden_by_scoped_revision(scoped, monkeypatch):
    path, _, _, job = scoped
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT', '0')
    before = path.read_bytes()
    with validation_budget.execution('fraudlens_validation_fixture', job):
        with pytest.raises(session_budget.QuotaBudgetExhausted): session_budget.check()
    assert path.read_bytes() == before


def test_concurrent_consumers_only_one_inflight_reservation(scoped):
    path, _, _, job = scoped
    with validation_budget.execution('fraudlens_validation_fixture', job):
        active = session_budget.reserve('gemini-3.5-flash')
    def run(_):
        with validation_budget.execution('fraudlens_validation_fixture', job):
            try:
                session_budget.reserve('gemini-3.5-flash')
                return True
            except session_budget.ProviderCircuitOpen: return False
    with ThreadPoolExecutor(max_workers=3) as pool: result = list(pool.map(run,range(3)))
    assert result == [False]*3 and json.loads(path.read_text())['attempts'] == 8
    session_budget.outcome(attempt=active)


def test_agent_real_sdk_tools_followup_and_receipts_before_artifact_work(scoped, monkeypatch):
    path, _, _, job = scoped; requests = []; client_class = genai.Client
    final = {'recommendation':'request_evidence','risk_band':'request_evidence',
        'narrative':'Request original photographs to resolve missing evidence.', 'findings_cited':[], 'requested_artifacts':['Original photographs']}
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        assert body['tools'][0]['functionDeclarations']
        assert body['generationConfig']['automaticFunctionCalling'] if 'automaticFunctionCalling' in body['generationConfig'] else True
        if len(requests) == 1:
            parts = [{'functionCall':{'id':'controlled-call','name':'get_claimant_history','args':{}},'thoughtSignature':'c2ln'}]
        else:
            assert body['contents'][-2]['parts'][0]['thoughtSignature'] == 'c2ln'
            assert body['contents'][-1]['parts'][0]['functionResponse']['name'] == 'get_claimant_history'
            parts = [{'text':json.dumps(final)}]
        return httpx.Response(200, json={'modelVersion':'fixture-serving','responseId':'fixture-'+str(len(requests)),
            'usageMetadata':{'promptTokenCount':12,'candidatesTokenCount':8,'totalTokenCount':20},
            'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':parts}}]})
    def factory(**kwargs):
        assert kwargs['http_options'].retry_options.attempts == 1
        kwargs['http_options'].client_args['transport'] = httpx.MockTransport(handler)
        return client_class(**kwargs)
    monkeypatch.setattr(genai,'Client',factory)
    provider=llm.GeminiProvider(model='gemini-3.5-flash',api_key='offline-placeholder',request_profile='gemini3_defaults_v2')
    try:
        with validation_budget.execution('fraudlens_validation_fixture', job):
            messages=[{'role':'user','content':'Controlled recorded findings'}]
            schemas=tools.schemas_for(('get_claimant_history',))
            response=provider.chat(messages,tools=schemas)
            assert response.tool_calls[0].name == 'get_claimant_history'
            messages += [{'role':'assistant','content':'','provider_content':response.model_content},
                {'role':'tool','name':'get_claimant_history','tool_call_id':'controlled-call','content':'{"cases":[]}'}]
            response=provider.chat(messages,tools=schemas)
            assert parse_decision(response.text)['risk_band'] == final['risk_band']
        state=json.loads(path.read_text())
        assert provider.http_attempts == 2 and len(list(Path(os.environ['FRAUDLENS_RESPONSE_DIR']).glob('*.json'))) == 2
        assert all(e['receipt']['token_usage']['total_token_count'] == 20 for e in state['events'][7:])
        assert all(e['receipt']['http_status'] == 200 for e in state['events'][7:])
        assert all(e['receipt']['finish_reason'] == 'STOP' for e in state['events'][7:])
    finally: provider.close()


def test_receipt_write_failure_never_repeats_generation(scoped, monkeypatch):
    _, _, _, job=scoped; count=[]; original=genai.Client
    def handler(request):
        count.append(1)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]})
    def factory(**kwargs):
        kwargs['http_options'].client_args['transport']=httpx.MockTransport(handler)
        return original(**kwargs)
    monkeypatch.setattr(genai,'Client',factory)
    write=Path.write_text
    def fail(self,*args,**kwargs):
        if self.parent.name=='responses': raise OSError('Controlled failure')
        return write(self,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',fail)
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    try:
        with validation_budget.execution('fraudlens_validation_fixture',job):
            with pytest.raises(Exception):provider.chat([{'role':'user','content':'Controlled fixture'}])
        assert count==[1]
        state=json.loads(scoped[0].read_text());assert state['events'][-1]['receipt']['http_status']==200
    finally:provider.close()
