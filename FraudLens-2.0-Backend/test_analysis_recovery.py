"""Controlled provider transport/control tests; no external requests."""
import json
from types import SimpleNamespace
import pytest
from src import session_budget, llm
from src.analysis_diagnostics import failure_detail, safe_message
from src.quota_budget import QuotaBudgetExhausted


@pytest.fixture
def stopped(tmp_path,monkeypatch):
    path=tmp_path/'ledger.json'
    original={'attempts':2,'consecutive_failures':2,'stopped':'configuration failure or repeated provider failures',
        'events':[{'attempt':i,'model':'fixture','time':i,'outcome':'failure:503'} for i in (1,2)]}
    path.write_text(json.dumps(original))
    monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER',str(path))
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','15')
    monkeypatch.setenv('GEMINI_QUOTA_BUDGET',str(tmp_path/'quota.json'))
    monkeypatch.delenv('FRAUDLENS_RECOVERY_ID',raising=False)
    return path,original


def test_circuit_and_http_failure_are_distinct(stopped):
    with pytest.raises(session_budget.ProviderCircuitOpen) as error:session_budget.check()
    record=failure_detail(error.value,'perception')
    assert record['error_category']=='provider_circuit_open'
    assert record['provider_status']=='not_attempted' and not record['attempted_network']
    http=failure_detail(SimpleNamespace(code=503),'perception',attempt_count=1,attempted_network=True)
    assert http['http_status']==503 and http['retryable'] and http['attempt_count']==1


def test_one_failed_probe_retains_original_stop_and_blocks_repeats(stopped,monkeypatch):
    path,original=stopped
    recovery=session_budget.authorize_recovery('Explicit user-requested transient recovery')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    attempt=session_budget.reserve('fixture')
    session_budget.outcome(SimpleNamespace(code=503),attempt=attempt)
    after=json.loads(path.read_text())
    assert after['events'][:2]==original['events'] and after['stopped']==original['stopped']
    assert after['attempts']==3 and after['recoveries'][0]['status']=='failed'
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('fixture')
    with pytest.raises(ValueError):session_budget.authorize_recovery('No repeated probes')


def test_probe_success_requires_separate_bounded_validation(stopped,monkeypatch):
    path,original=stopped;recovery=session_budget.authorize_recovery('Authorized probe')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    attempt=session_budget.reserve('fixture');session_budget.outcome(attempt=attempt)
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('fixture')
    session_budget.authorize_validation(recovery,2,'One claim and one underwriting validation')
    for _ in range(2):session_budget.outcome(attempt=session_budget.reserve('fixture'))
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('fixture')
    after=json.loads(path.read_text())
    assert after['attempts']==5 and after['stopped']==original['stopped']
    assert after['events'][:2]==original['events']


@pytest.mark.parametrize('outcome',['failure:429','failure:403','failure:404'])
def test_quota_access_or_configuration_cannot_receive_transient_probe(stopped,outcome):
    path,_=stopped;data=json.loads(path.read_text());data['events'][-1]['outcome']=outcome;path.write_text(json.dumps(data))
    with pytest.raises(ValueError):session_budget.authorize_recovery('Must not bypass access/quota')


def test_recovery_does_not_rotate_keys_or_retry_real_transport(stopped,monkeypatch):
    from google.genai import errors
    path,_=stopped;recovery=session_budget.authorize_recovery('Single request fixture')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    calls=[]
    monkeypatch.setattr(provider,'_client_for',lambda *args:object())
    def fail(client):
        calls.append(1)
        raise errors.ServerError(503,{'error':{'code':503,'message':'Controlled offline fixture','status':'UNAVAILABLE'}})
    try:
        with pytest.raises(errors.ServerError) as error:provider._call_rotating(fail,attempts=5)
        assert calls==[1] and error.value.analysis_failure['attempted_network']
        assert json.loads(path.read_text())['attempts']==3
    finally:provider.close()


def test_function_call_content_and_signature_survive_cache_and_next_turn():
    from google.genai import types
    content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(name='lookup',args={'case':'fixture'}),thought_signature=b'opaque-signature')])
    response=types.GenerateContentResponse(candidates=[types.Candidate(content=content)])
    saved=llm._extract_model_content(response)
    result=llm.LLMResponse('',llm.ToolCall('lookup',{'case':'fixture'}),{},'fixture',False,1,saved)
    cached=llm._response_from_cache(llm._response_to_cache_entry(result),'fixture',0)
    contents=llm._to_gemini_contents([{'role':'user','content':'Review'},
        {'role':'assistant','content':'','provider_content':cached.model_content},
        {'role':'tool','name':'lookup','content':json.dumps({'found':True})}])
    assert types.Content.model_validate(contents[1]).parts[0].thought_signature==b'opaque-signature'
    assert contents[2]['parts'][0]['function_response']=={'name':'lookup','response':{'found':True}}
    assert llm._response_to_dict(response)['candidates'][0]['content']['role']=='model'


def test_sanitizer_removes_credentials_and_urls():
    result=safe_message('API_KEY=fixture-private bearer fixture-secret https://provider.invalid/?key=secret postgresql://person:secret@host/db')
    assert 'fixture-private' not in result and 'fixture-secret' not in result and 'person:secret' not in result and '?key=' not in result


def test_explicit_quota_stop_cannot_recover_based_on_older_transient_errors(stopped):
    path,_=stopped;state=json.loads(path.read_text());state['stopped']='provider quota exhausted';path.write_text(json.dumps(state))
    with pytest.raises(ValueError):session_budget.authorize_recovery('Must not override a quota control')


def test_quota_day_rollover_retains_every_prior_event_and_corruption_fails_closed(tmp_path):
    from src import quota_budget
    path=tmp_path/'quota.json';prior=quota_budget._base_state(20,'2026-10-14')
    prior.update(events=[{'outcome':'prior reservation'}],consumers={'pilot':{'budget':20,'reserved':11,'calls':11}})
    path.write_text(json.dumps(prior))
    current=quota_budget._load_state(path,20,'2026-10-20')
    assert current['history']==[prior] and current['quota_day']=='2026-10-20'
    path.write_text('invalid json')
    with pytest.raises(QuotaBudgetExhausted):quota_budget._load_state(path,20,'2026-10-20')


@pytest.mark.parametrize('state',[
    {}, [], {'quota_day':'2026-10-20'},
    {'quota_day':'2026-10-14','consumers':{},'keys':{}},
])
def test_structurally_invalid_quota_ledger_never_resets_allowance(tmp_path,state):
    from src import quota_budget
    path=tmp_path/'quota.json';original=json.dumps(state);path.write_text(original)
    with pytest.raises(QuotaBudgetExhausted):quota_budget._load_state(path,20,'2026-10-20')
    assert path.read_text()==original


@pytest.mark.parametrize('field,value',[
    ('attempts',-1),('attempts',True),('attempts',0),('events',[]),
    ('consecutive_failures',-1),('recoveries',[{'recovery_id':'broken'}]),
])
def test_invalid_session_ledger_blocks_before_reserving_and_retains_bytes(stopped,field,value):
    path,original=stopped;original[field]=value;saved=json.dumps(original);path.write_text(saved)
    with pytest.raises(QuotaBudgetExhausted):session_budget.reserve('offline-fixture')
    assert path.read_text()==saved


def test_unreadable_session_ledger_is_a_local_budget_failure(stopped):
    path,_=stopped;path.write_text('invalid json')
    with pytest.raises(QuotaBudgetExhausted):session_budget.check()
    assert path.read_text()=='invalid json'


@pytest.mark.parametrize('legacy_cache',[False,True])
def test_parallel_function_calls_preserve_ids_cache_and_one_response_turn(legacy_cache):
    from google.genai import types
    calls=[types.FunctionCall(name='get_claimant_history',args={},id='first'),
           types.FunctionCall(name='get_garage_history',args={},id='second')]
    response=types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',
        parts=[types.Part(function_call=call,thought_signature=b'opaque-signature') for call in calls]))])
    extracted=llm._extract_tool_calls(response)
    result=llm.LLMResponse('',extracted[0],{},'fixture',False,1,llm._extract_model_content(response),extracted)
    entry=llm._response_to_cache_entry(result)
    if legacy_cache:entry.pop('tool_calls')
    cached=llm._response_from_cache(entry,'fixture',0)
    assert [(call.name,call.id) for call in cached.tool_calls]==[(call.name,call.id) for call in calls]
    messages=[{'role':'assistant','content':'','provider_content':cached.model_content}]+[
        {'role':'tool','name':call.name,'tool_call_id':call.id,'content':json.dumps({'found':True})}
        for call in cached.tool_calls]
    contents=llm._to_gemini_contents(messages)
    assert len(contents)==2
    model=types.Content.model_validate(contents[0]);reply=types.Content.model_validate(contents[1])
    assert len(model.parts)==len(reply.parts)==2
    assert [part.function_response.id for part in reply.parts]==['first','second']
    assert [part.function_response.name for part in reply.parts]==[call.name for call in calls]
    assert model.parts[0].thought_signature==b'opaque-signature'


@pytest.mark.parametrize('opt_in',[None,'0'])
def test_live_integration_functions_refuse_transport_when_called_directly(monkeypatch,tmp_path,opt_in):
    import unittest
    monkeypatch.setenv('GEMINI_QUOTA_BUDGET',str(tmp_path/'unused-quota.json'))
    import test_llm as integration
    if opt_in is None:monkeypatch.delenv('FRAUDLENS_TEST_LIVE',raising=False)
    else:monkeypatch.setenv('FRAUDLENS_TEST_LIVE',opt_in)
    def forbidden():raise AssertionError('A disabled integration test reached transport setup.')
    monkeypatch.setattr(integration,'get_provider',forbidden)
    monkeypatch.setattr(integration,'get_ollama_provider',forbidden)
    for name in integration._LIVE_TESTS:
        with pytest.raises(unittest.SkipTest):getattr(integration,name)()
    assert not (tmp_path/'unused-quota.json').exists()
