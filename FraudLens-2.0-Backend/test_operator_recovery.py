"""Cooldown recovery and full-schema probe via controlled SDK transports only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from PIL import Image

from src import session_budget,quota_budget,llm,perception
from src.pilot_config import load_pilot_environment,apply_pilot_environment,PilotConfigurationError
from test_analysis_recovery import stopped
from test_engine_reliability import OBSERVATIONS


@pytest.fixture
def failed(stopped,monkeypatch):
    path,_=stopped
    monkeypatch.setattr(session_budget.time,'time',lambda:10000.0)
    old=session_budget.authorize_recovery('Initial controlled probe')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',old)
    session_budget.outcome(SimpleNamespace(code=503),attempt=session_budget.reserve('fixture'))
    return path,json.loads(path.read_text())


def authorize_after_cooldown(failed,monkeypatch):
    path,old=failed
    monkeypatch.setattr(session_budget.time,'time',lambda:10000.0+session_budget.RECOVERY_COOLDOWN_SECONDS)
    recovery=session_budget.authorize_recovery('Explicit controlled retry',operator='fixture-operator',expected_attempts=old['attempts'])
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    return recovery


@pytest.mark.parametrize('elapsed',[0,1,1799,1799.99])
def test_operator_cannot_skip_cooldown_or_modify_history(failed,monkeypatch,elapsed):
    path,old=failed;before=path.read_bytes()
    monkeypatch.setattr(session_budget.time,'time',lambda:10000.0+elapsed)
    with pytest.raises(ValueError,match='recovery_cooldown'):
        session_budget.authorize_recovery('Must wait',operator='fixture-operator')
    assert path.read_bytes()==before
    result=session_budget.recovery_eligibility(old,15,operator=True)
    assert not result['eligible'] and result['retry_after_seconds']>0


def test_operator_appends_after_cooldown_and_retains_stop_cap_events_and_old_recovery(failed,monkeypatch):
    path,old=failed;recovery=authorize_after_cooldown(failed,monkeypatch);state=json.loads(path.read_text())
    assert state['attempts']==old['attempts']==3 and state['stopped']==old['stopped']
    assert state['events']==old['events'] and state['recoveries'][:-1]==old['recoveries']
    assert state['recoveries'][-1]['recovery_id']==recovery and state['recoveries'][-1]['allowance']==1
    assert state['recoveries'][-1]['operator']=='fixture-operator'
    assert state['recoveries'][-1]['cooldown_seconds']==1800
    with pytest.raises(ValueError):session_budget.authorize_recovery('No second concurrent grant',operator='another')


def test_success_consumes_the_only_grant_without_reopening_general_processing(failed,monkeypatch):
    path,old=failed;authorize_after_cooldown(failed,monkeypatch)
    session_budget.outcome(attempt=session_budget.reserve('fixture'))
    with pytest.raises(quota_budget.QuotaBudgetExhausted):session_budget.reserve('fixture')
    monkeypatch.delenv('FRAUDLENS_RECOVERY_ID')
    with pytest.raises(session_budget.ProviderCircuitOpen):session_budget.check()
    assert json.loads(path.read_text())['stopped']==old['stopped']


def test_failure_recloses_and_cooldown_starts_again(failed,monkeypatch):
    path,old=failed;authorize_after_cooldown(failed,monkeypatch)
    session_budget.outcome(SimpleNamespace(code=503),attempt=session_budget.reserve('fixture'))
    after=json.loads(path.read_text());assert after['recoveries'][-1]['status']=='failed'
    assert after['events'][:3]==old['events'] and after['recoveries'][:1]==old['recoveries']
    with pytest.raises(ValueError,match='recovery_cooldown'):session_budget.authorize_recovery('No immediate retry',operator='fixture')
    with pytest.raises(quota_budget.QuotaBudgetExhausted):session_budget.reserve('fixture')


@pytest.mark.parametrize('code',[400,401,403,404,429])
def test_operator_does_not_override_non_transient_provider_stops(failed,code):
    _,state=failed;state['events'][-1]['outcome']='failure:'+str(code)
    assert not session_budget.recovery_eligibility(state,15,operator=True,now=999999)['eligible']


@pytest.mark.parametrize('reason',['cap','in_flight','unknown_time','wrong_attempts'])
def test_budget_inflight_and_unknown_state_fail_closed(failed,monkeypatch,reason):
    path,state=failed
    if reason=='cap':monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','3')
    if reason=='in_flight':
        state['attempts']+=1;state['events'].append({'attempt':4,'outcome':'reserved','time':10001,'model':'fixture'})
    if reason=='unknown_time':state['recoveries'][0].pop('finished_at')
    path.write_text(json.dumps(state));before=path.read_bytes()
    monkeypatch.setattr(session_budget.time,'time',lambda:999999)
    with pytest.raises((ValueError,quota_budget.QuotaBudgetExhausted)):
        session_budget.authorize_recovery('Refuse unsafe grant',operator='fixture',expected_attempts=2 if reason=='wrong_attempts' else state['attempts'])
    assert path.read_bytes()==before


def test_concurrent_operators_and_workers_share_one_half_open_slot(failed,monkeypatch):
    path,old=failed
    command=[sys.executable,'-c','from src import session_budget;session_budget.authorize_recovery("fixture",operator="fixture-operator",expected_attempts=3)']
    def run(cmd):return subprocess.run(cmd,capture_output=True,env=os.environ.copy()).returncode
    with ThreadPoolExecutor(max_workers=3) as pool:codes=list(pool.map(run,[command]*3))
    assert codes.count(0)==1
    state=json.loads(path.read_text());assert len(state['recoveries'])==2 and state['attempts']==3
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',state['recoveries'][-1]['recovery_id'])
    probe=[sys.executable,'-c','from src import session_budget;from types import SimpleNamespace;a=session_budget.reserve("fixture");session_budget.outcome(SimpleNamespace(code=503),attempt=a)']
    with ThreadPoolExecutor(max_workers=3) as pool:codes=list(pool.map(run,[probe]*3))
    assert codes.count(0)==1
    state=json.loads(path.read_text());assert state['attempts']==4 and state['recoveries'][-1]['status']=='failed'
    assert state['recoveries'][:1]==old['recoveries'] and state['events'][:3]==old['events']


@pytest.mark.parametrize('outcome',['success','http503','invalid_schema'])
def test_actual_sdk_full_schema_probe_has_one_http_attempt_no_rotation_or_retry(failed,monkeypatch,tmp_path,outcome):
    path,old=failed;authorize_after_cooldown(failed,monkeypatch);requests=[]
    original=genai.Client
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        assert 'responseSchema' not in body['generationConfig']
        assert body['generationConfig']['responseJsonSchema']['additionalProperties'] is False
        assert 'additional_properties' not in body['generationConfig']['responseJsonSchema']
        if outcome=='http503':return httpx.Response(503,json={'error':{'code':503,'status':'UNAVAILABLE','message':'controlled'}})
        observations=OBSERVATIONS if outcome=='success' else {**OBSERVATIONS,'damage_severity':'invented'}
        return httpx.Response(200,json={'responseId':'controlled-probe','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(observations)}]}}]})
    def factory(**kwargs):
        options=kwargs['http_options'];assert options.retry_options.attempts==1 and options.timeout==60000
        options.client_args['transport']=httpx.MockTransport(handle)
        return original(**kwargs)
    monkeypatch.setattr(genai,'Client',factory)
    provider=llm.GeminiProvider(api_key='offline-placeholder',request_profile='gemini3_defaults_v2')
    image=tmp_path/'fixture.png';Image.new('RGB',(12,8)).save(image)
    try:
        if outcome=='success':
            result=provider.describe_image(str(image),perception.PERCEPTION_PROMPT,retry_attempts=5,response_schema=perception.PerceptionObservation)
            assert perception.PerceptionObservation.model_validate_json(result.text).damage_severity=='minor'
            assert not result.cached
        else:
            with pytest.raises(Exception):provider.describe_image(str(image),perception.PERCEPTION_PROMPT,retry_attempts=5,response_schema=perception.PerceptionObservation)
        assert provider.http_attempts==1 and len(requests)==1
        assert provider.http_statuses==[503 if outcome=='http503' else 200]
        schema=requests[0]['generationConfig']['responseJsonSchema']
        assert set(schema['required'])==set(perception._EXPECTED_FIELDS)
        assert 'temperature' not in requests[0]['generationConfig']
        state=json.loads(path.read_text());assert state['attempts']==4
        assert state['events'][:3]==old['events'] and state['recoveries'][:1]==old['recoveries']
        assert state['recoveries'][-1]['status']==('probe_succeeded' if outcome=='success' else 'failed')
    finally:provider.close()


def test_schema_is_exactly_the_existing_perception_contract():
    schema=perception.PerceptionObservation.model_json_schema()
    assert set(schema['required'])==set(perception._EXPECTED_FIELDS)
    for field,values in perception._ENUM_FIELDS.items():assert set(schema['properties'][field]['enum'])==values
    assert not perception._schema_issues(perception.PerceptionObservation.model_validate(OBSERVATIONS).model_dump())


@pytest.fixture
def pilot(tmp_path):
    folder=tmp_path/'outputs/pilot_validation';folder.mkdir(parents=True)
    session={'attempts':0,'events':[],'consecutive_failures':0,'stopped':None}
    (folder/'live_calls.json').write_text(json.dumps(session))
    (folder/'quota_budget.json').write_text(json.dumps(quota_budget._base_state(20,'2026-10-21')))
    env={'FRAUDLENS_DB':'postgresql','FRAUDLENS_PG_SCHEMA':'fraudlens_pilot','DATABASE_URL':'postgresql://localhost/fixture',
        'LLM_PROVIDER':'gemini','GEMINI_MODEL':'gemini-3.5-flash','FRAUDLENS_GEMINI_REQUEST_PROFILE':'gemini3_defaults_v2',
        'FRAUDLENS_LIVE_LEDGER':str(folder/'live_calls.json'),'GEMINI_QUOTA_BUDGET':str(folder/'quota_budget.json'),
        'FRAUDLENS_LIVE_LIMIT':'15','GEMINI_QUOTA_CONSUMER':'pilot','GEMINI_API_KEY':'offline-placeholder'}
    return tmp_path,env


@pytest.mark.parametrize('missing',['FRAUDLENS_PG_SCHEMA','DATABASE_URL','GEMINI_MODEL','FRAUDLENS_LIVE_LEDGER','GEMINI_QUOTA_BUDGET','GEMINI_API_KEY'])
def test_missing_pilot_configuration_fails_without_values_or_defaults(pilot,missing):
    root,env=pilot;env.pop(missing)
    with pytest.raises(PilotConfigurationError) as caught:load_pilot_environment(env,root)
    assert 'offline-placeholder' not in str(caught.value) and 'postgresql://' not in str(caught.value)


@pytest.mark.parametrize('field,value',[('FRAUDLENS_DB','sqlite'),('FRAUDLENS_GEMINI_REQUEST_PROFILE','legacy'),
    ('GEMINI_QUOTA_BUDGET','outputs/alternative.json'),('FRAUDLENS_LIVE_LIMIT','16'),('LLM_PROVIDER','ollama')])
def test_alternate_controls_or_configuration_are_refused(pilot,field,value):
    root,env=pilot;env[field]=value
    with pytest.raises(PilotConfigurationError):load_pilot_environment(env,root)


def test_reference_config_is_readonly_and_clears_unrelated_shell_keys(pilot,monkeypatch):
    root,env=pilot;paths=[Path(env[n]) for n in ['FRAUDLENS_LIVE_LEDGER','GEMINI_QUOTA_BUDGET']];before=[p.read_bytes() for p in paths]
    aligned=load_pilot_environment(env,root)
    monkeypatch.setenv('GEMINI_API_KEY_2','unrelated-offline-placeholder')
    # Save every changed environment name, so this test cannot leak its fixture.
    from src.pilot_config import CONFIG_NAMES,KEY_NAMES
    saved=os.environ.copy()
    try:
        apply_pilot_environment(aligned)
        assert os.environ['FRAUDLENS_DB']=='postgresql' and os.environ['FRAUDLENS_PG_SCHEMA']=='fraudlens_pilot'
        assert 'GEMINI_API_KEY_2' not in os.environ
        assert os.environ['GEMINI_MODEL']==env['GEMINI_MODEL']
    finally:os.environ.clear();os.environ.update(saved)
    assert [p.read_bytes() for p in paths]==before


@pytest.mark.parametrize('failure',['ReadTimeout','ConnectError'])
def test_transient_network_failures_also_have_cooldown_governed_operator_recovery(failed,failure):
    _,state=failed;state['events'][-1]['outcome']='failure:'+failure
    state['recoveries'][-1]['failure_outcome']='failure:'+failure
    assert session_budget.recovery_eligibility(state,15,operator=True,now=999999)['eligible']


@pytest.mark.parametrize('status',[200,400])
def test_metadata_is_one_get_separately_counted_and_never_changes_generation_stop(failed,monkeypatch,status):
    path,old=failed;requests=[];original=genai.Client
    monkeypatch.setenv('GEMINI_MODEL',llm.GEMINI_MODEL)
    def handle(request):
        requests.append(request.method)
        if status==400:return httpx.Response(400,json={'error':{'code':400,'status':'INVALID_ARGUMENT',
            'message':'PRIVATE omitted request context','details':[{'reason':'API_KEY_INVALID','metadata':{'private':'MUST_NOT_APPEAR'}}]}})
        return httpx.Response(200,json={'name':'models/'+llm.GEMINI_MODEL,'supportedGenerationMethods':['generateContent']})
    def factory(**kwargs):
        kwargs['http_options'].client_args['transport']=httpx.MockTransport(handle)
        return original(**kwargs)
    monkeypatch.setattr(genai,'Client',factory)
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    try:
        if status==200:
            metadata=provider.model_metadata(operator='fixture-operator',reason='Explicit read-only inspection')
            assert metadata['supported_actions']==['generateContent']
        else:
            with pytest.raises(Exception) as caught:provider.model_metadata(operator='fixture-operator',reason='Explicit read-only inspection')
            from src.analysis_diagnostics import failure_detail
            record=failure_detail(caught.value,'model_metadata')
            assert record['provider_error_reason']=='API_KEY_INVALID' and record['error_category']=='provider_access_denied'
            assert 'PRIVATE' not in json.dumps(record) and 'MUST_NOT_APPEAR' not in json.dumps(record)
        assert requests==['GET'] and provider.http_attempts==1
        state=json.loads(path.read_text());assert state['attempts']==4
        assert state['events'][:3]==old['events'] and state['events'][-1]['kind']=='model_metadata'
        assert state['stopped']==old['stopped'] and state['consecutive_failures']==old['consecutive_failures']
        assert state['recoveries']==old['recoveries']
    finally:provider.close()


def test_metadata_cannot_escape_original_cap_or_target_a_different_model(failed,monkeypatch):
    path,old=failed;monkeypatch.setenv('GEMINI_MODEL','fixture-model')
    before=path.read_bytes()
    with pytest.raises(ValueError):session_budget.reserve_model_metadata('different','fixture','fixture')
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','3')
    with pytest.raises(quota_budget.QuotaBudgetExhausted):session_budget.reserve_model_metadata('fixture-model','fixture','fixture')
    assert path.read_bytes()==before
