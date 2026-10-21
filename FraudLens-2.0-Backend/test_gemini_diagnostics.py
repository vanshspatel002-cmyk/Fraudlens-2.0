"""Real SDK + controlled transports only. No model quota or application database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from google.genai import errors, types
from PIL import Image

from src import llm, quota_budget, session_budget
from src.analysis_diagnostics import failure_detail
from test_analysis_recovery import stopped
from test_pilot_workflow import client, auth


@pytest.fixture
def controlled(tmp_path,monkeypatch):
    monkeypatch.setenv('FRAUDLENS_LIVE_LEDGER',str(tmp_path/'session.json'))
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','15')
    monkeypatch.setenv('GEMINI_QUOTA_BUDGET',str(tmp_path/'quota.json'))
    monkeypatch.setenv('GEMINI_QUOTA_CONSUMER','diagnostic-fixture')
    monkeypatch.delenv('FRAUDLENS_RECOVERY_ID',raising=False)
    monkeypatch.setattr(llm.time,'sleep',lambda _:None)
    return tmp_path


def sdk_provider(monkeypatch,handler):
    transport=httpx.Client(transport=httpx.MockTransport(handler))
    client=genai.Client(api_key='offline-placeholder',http_options=types.HttpOptions(
        httpx_client=transport,timeout=60000,retry_options=types.HttpRetryOptions(attempts=1)))
    provider=llm.GeminiProvider(api_key='offline-placeholder',request_profile='gemini3_defaults_v2')
    monkeypatch.setattr(provider,'_client_for',lambda *args:client)
    return provider,client,transport


@pytest.mark.parametrize('code,category',[(400,'provider_configuration'),(401,'provider_access_denied'),
    (403,'provider_access_denied'),(404,'provider_configuration'),(429,'provider_quota_or_rate_limit'),
    (500,'provider_http_error'),(503,'provider_http_error'),(504,'provider_http_error')])
def test_http_error_metadata_never_echoes_request_data(controlled,monkeypatch,code,category):
    sent=[]
    def handle(request):
        sent.append(1)
        return httpx.Response(code,headers={'x-request-id':'fixture-request-17'},json={'error':{
            'code':code,'status':'RESOURCE_EXHAUSTED' if code==429 else 'UNAVAILABLE',
            'message':'PRIVATE APPLICANT PROMPT AND PHOTO password=private-secret'}})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        with pytest.raises(errors.APIError) as caught:
            provider._call_rotating(lambda c:c.models.generate_content(model=provider.model,contents='fixture'),attempts=1)
        diagnostic=failure_detail(caught.value,'perception')
        assert diagnostic['error_category']==category and diagnostic['http_status']==code
        assert diagnostic['provider_error_code'] in {'RESOURCE_EXHAUSTED','UNAVAILABLE'}
        assert diagnostic['provider_request_id']=='fixture-request-17' and diagnostic['model']==provider.model
        assert diagnostic['attempt_count']==1 and diagnostic['attempted_network'] and sent==[1]
        assert 'PRIVATE' not in json.dumps(diagnostic) and 'private-secret' not in json.dumps(diagnostic)
        assert json.loads((controlled/'session.json').read_text())['attempts']==1
        assert json.loads((controlled/'quota.json').read_text())['consumers']['diagnostic-fixture']['reserved']==1
    finally:client.close();provider.close();transport.close()


@pytest.mark.parametrize('error,category',[(httpx.ConnectError('private'),'provider_network_failure'),
    (httpx.ReadTimeout('private'),'timeout'),(httpx.ConnectTimeout('private'),'timeout')])
def test_network_and_timeout_are_attempted_without_fabricated_http_status(controlled,monkeypatch,error,category):
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    monkeypatch.setattr(provider,'_client_for',lambda *args:object())
    def fail(_):raise error
    with pytest.raises(type(error)) as caught:provider._call_rotating(fail)
    diagnostic=failure_detail(caught.value,'agent_adjudication')
    assert diagnostic['error_category']==category and diagnostic['attempted_network']
    assert diagnostic['http_status'] is None and diagnostic['attempt_count']==1 and diagnostic['retryable']


@pytest.mark.parametrize('finish',['MAX_TOKENS','SAFETY','RECITATION','MALFORMED_FUNCTION_CALL','OTHER',None])
def test_truncated_or_blocked_text_is_not_cached_or_accepted(controlled,monkeypatch,finish):
    def handle(_):return httpx.Response(200,json={'responseId':'fixture-response-1','candidates':[{
        'finishReason':finish,'content':{'role':'model','parts':[{'text':'{"looks_valid":true}'}]}}]})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        with pytest.raises(llm.GenerationResponseError) as caught:provider.chat([{'role':'user','content':'fixture'}])
        diagnostic=failure_detail(caught.value,'agent_adjudication')
        assert diagnostic.get('finish_reason')==finish and diagnostic['provider_request_id']=='fixture-response-1'
        assert diagnostic['provider_status']=='response_received' and diagnostic['attempt_count']==1
        assert json.loads((controlled/'session.json').read_text())['events'][0]['outcome'].startswith('failure:')
    finally:client.close();provider.close();transport.close()


@pytest.mark.parametrize('payload',[{}, {'candidates':[]}, {'candidates':[{'finishReason':'STOP','content':{'parts':[]}}]},
    {'promptFeedback':{'blockReason':'SAFETY','blockReasonMessage':'private prompt'}}])
def test_empty_candidates_and_prompt_blocks_are_response_validation_failures(payload):
    response=types.GenerateContentResponse.model_validate(payload)
    with pytest.raises(llm.GenerationResponseError) as caught:llm._validate_generation_response(response)
    diagnostic=failure_detail(caught.value,'perception',attempt_count=1,attempted_network=True,model='fixture')
    assert diagnostic['error_category']=='response_schema_invalid'
    assert diagnostic['provider_status']=='response_received' and 'private prompt' not in json.dumps(diagnostic)


@pytest.mark.parametrize('format,mime',[('PNG','image/png'),('JPEG','image/jpeg'),('WEBP','image/webp')])
def test_image_bytes_and_mime_follow_decoded_format_not_extension(controlled,monkeypatch,format,mime):
    path=controlled/'sample.wrong-extension';Image.new('RGB',(12,8),'blue').save(path,format=format)
    sent=[]
    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'fixture observation'}]}}]})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        result=provider.describe_image(str(path),'fixture',retry_attempts=1)
        import base64
        image=sent[0]['contents'][0]['parts'][1]['inlineData']
        assert image['mimeType']==mime and base64.urlsafe_b64decode(image['data'])==path.read_bytes()
        assert result.cached is False and result.raw['request_provenance']['finish_reason']=='STOP'
    finally:client.close();provider.close();transport.close()


@pytest.mark.parametrize('valid',[True,False])
def test_probe_schema_is_enforced_by_installed_sdk(controlled,monkeypatch,valid):
    from scripts.recover_provider import ProbeObservation
    path=controlled/'sample.png';Image.new('RGB',(8,8)).save(path);sent=[]
    def handle(request):
        sent.append(json.loads(request.content))
        text=json.dumps({'vehicle_visible':True,'observations':['A parked vehicle.']}) if valid else '{"wrong":true}'
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        if valid:
            result=provider.describe_image(str(path),'fixture',retry_attempts=1,response_schema=ProbeObservation)
            assert ProbeObservation.model_validate_json(result.text).vehicle_visible
        else:
            with pytest.raises(llm.GenerationResponseError):provider.describe_image(str(path),'fixture',retry_attempts=1,response_schema=ProbeObservation)
        config=sent[0]['generationConfig']
        assert config['responseMimeType']=='application/json' and ('responseSchema' in config or 'responseJsonSchema' in config)
    finally:client.close();provider.close();transport.close()


def test_retry_then_local_stop_retains_every_attempt_in_diagnostic(controlled,monkeypatch):
    sent=[]
    def handle(_):
        sent.append(1);return httpx.Response(503,json={'error':{'code':503,'status':'UNAVAILABLE','message':'fixture'}})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        with pytest.raises(session_budget.ProviderCircuitOpen) as caught:provider.chat([{'role':'user','content':'fixture'}])
        detail=failure_detail(caught.value,'agent_adjudication')
        assert sent==[1,1] and detail['attempt_count']==2 and detail['attempted_network']
        assert detail['provider_status']=='locally_blocked_after_attempts'
        assert [item['http_status'] for item in detail['attempt_history']]==[503,503]
    finally:client.close();provider.close();transport.close()


def test_test_firewall_stops_real_http_before_dns_even_with_key(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','offline-developer-placeholder')
    with pytest.raises(AssertionError,match='External HTTP disabled'):
        with httpx.Client() as client:client.get('https://generativelanguage.googleapis.com/never-send')
    async def attempt():
        async with httpx.AsyncClient() as client:await client.get('https://generativelanguage.googleapis.com/never-send')
    with pytest.raises(AssertionError,match='External HTTP disabled'):asyncio.run(attempt())
    import requests
    with pytest.raises(AssertionError,match='External HTTP disabled'):requests.get('https://generativelanguage.googleapis.com/never-send')
    import importlib.util
    if importlib.util.find_spec('aiohttp'):
        import aiohttp
        async def aio_attempt():
            async with aiohttp.ClientSession() as client:await client.get('https://generativelanguage.googleapis.com/never-send')
        with pytest.raises(AssertionError,match='External HTTP disabled'):asyncio.run(aio_attempt())


def test_exhausted_session_makes_no_transport_call(controlled,monkeypatch):
    monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT','0');calls=[]
    provider=llm.GeminiProvider(api_key='offline-placeholder');monkeypatch.setattr(provider,'_client_for',lambda *a:object())
    with pytest.raises(quota_budget.QuotaBudgetExhausted) as caught:provider._call_rotating(lambda _:calls.append(1))
    assert not calls and not caught.value.analysis_failure['attempted_network']
    assert not (controlled/'quota.json').exists()


def test_named_and_unnamed_consumers_share_global_and_key_caps(controlled,monkeypatch):
    monkeypatch.setenv('GEMINI_DAILY_QUOTA_PER_KEY','2')
    for consumer in ['first-diagnostic','second-diagnostic']:
        quota_budget.reserve_call(consumer,'explicit',keys_configured=1,model='fixture',kind='fixture')
    with pytest.raises(quota_budget.QuotaBudgetExhausted):
        quota_budget.reserve_call('third-diagnostic','explicit',keys_configured=1,model='fixture',kind='fixture')
    assert sum(v['reserved'] for v in json.loads((controlled/'quota.json').read_text())['consumers'].values())==2


def test_slow_quota_writer_is_not_deleted(controlled,monkeypatch):
    path=controlled/'quota.json';lock=path.with_suffix('.json.lock');lock.write_text('fixture-owner')
    monkeypatch.setattr(quota_budget,'LOCK_TIMEOUT_SECONDS',0)
    with pytest.raises(quota_budget.QuotaBudgetExhausted):
        quota_budget.reserve_call('fixture','explicit',keys_configured=1,model='fixture',kind='fixture')
    assert lock.read_text()=='fixture-owner' and not path.exists()


def test_half_open_probe_is_serialized_across_processes_and_restart_retains_failure(stopped,monkeypatch):
    path,original=stopped;recovery=session_budget.authorize_recovery('Controlled concurrency fixture')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    command=[sys.executable,'-c',
        'from src import session_budget; from types import SimpleNamespace; '
        'a=session_budget.reserve("fixture"); session_budget.outcome(SimpleNamespace(code=503),attempt=a)']
    def run(_):return subprocess.run(command,capture_output=True,env=os.environ.copy()).returncode
    with ThreadPoolExecutor(max_workers=3) as pool:codes=list(pool.map(run,range(3)))
    assert codes.count(0)==1
    after=json.loads(path.read_text());assert after['attempts']==3 and after['recoveries'][0]['status']=='failed'
    assert after['events'][:2]==original['events']
    restarted=subprocess.run([sys.executable,'-c','from src import session_budget;session_budget.check()'],capture_output=True)
    assert restarted.returncode!=0 and json.loads(path.read_text())==after


def test_readonly_audit_reports_failed_recovery_and_never_rolls_ledgers(stopped,monkeypatch):
    from scripts.diagnose_gemini import summarize
    path,_=stopped;recovery=session_budget.authorize_recovery('Fixture');monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
    session_budget.outcome(SimpleNamespace(code=503),attempt=session_budget.reserve('fixture'))
    before=path.read_bytes();result=summarize(os.environ.copy())
    assert result['session']['headroom']==12 and result['session']['authorized_now']==0
    assert not result['session']['new_recovery_permitted'] and path.read_bytes()==before


def test_transient_sdk_failures_allow_only_one_explicit_successful_probe(controlled,monkeypatch):
    sent=[]
    def handle(_):
        sent.append(1)
        if len(sent)<=2:return httpx.Response(503,json={'error':{'code':503,'status':'UNAVAILABLE','message':'fixture'}})
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'fixture response'}]}}]})
    provider,client,transport=sdk_provider(monkeypatch,handle)
    try:
        with pytest.raises(session_budget.ProviderCircuitOpen):provider.chat([{'role':'user','content':'fixture'}])
        original=json.loads((controlled/'session.json').read_text())
        recovery=session_budget.authorize_recovery('Controlled permitted transient probe')
        monkeypatch.setenv('FRAUDLENS_RECOVERY_ID',recovery)
        assert not provider.chat([{'role':'user','content':'fixture'}]).cached
        with pytest.raises(quota_budget.QuotaBudgetExhausted):provider.chat([{'role':'user','content':'fixture'}])
        state=json.loads((controlled/'session.json').read_text())
        assert len(sent)==3 and state['events'][:2]==original['events']
        assert state['recoveries'][0]['status']=='probe_succeeded' and state['attempts']==3
    finally:client.close();provider.close();transport.close()


def test_concurrent_processes_do_not_overspend_shared_daily_quota(controlled,monkeypatch):
    monkeypatch.setenv('GEMINI_DAILY_QUOTA_PER_KEY','2')
    command=[sys.executable,'-c','from src import quota_budget;quota_budget.reserve_call("fixture","explicit",keys_configured=1,model="fixture",kind="fixture")']
    def run(_):return subprocess.run(command,capture_output=True,env=os.environ.copy()).returncode
    with ThreadPoolExecutor(max_workers=4) as pool:codes=list(pool.map(run,range(4)))
    assert codes.count(0)==2
    state=json.loads((controlled/'quota.json').read_text())
    assert state['consumers']['fixture']['reserved']==state['keys']['explicit']['reserved']==2


def test_one_key_cannot_spend_other_keys_remaining_daily_allowance(controlled,monkeypatch):
    monkeypatch.setenv('GEMINI_DAILY_QUOTA_PER_KEY','1')
    quota_budget.reserve_call('fixture','first',keys_configured=2,model='fixture',kind='fixture')
    with pytest.raises(quota_budget.QuotaBudgetExhausted):quota_budget.reserve_call('fixture','first',keys_configured=2,model='fixture',kind='fixture')
    quota_budget.reserve_call('fixture','second',keys_configured=2,model='fixture',kind='fixture')


def test_batch_error_log_omits_private_exception_body(controlled,monkeypatch):
    from src import perception
    path=controlled/'sanitized.log';monkeypatch.setattr(perception,'ERROR_LOG',path)
    image=SimpleNamespace(case_id='fictional-case',image_id='fictional-image')
    error=errors.ServerError(503,{'error':{'code':503,'status':'UNAVAILABLE','message':'PRIVATE applicant text password=secret'}})
    perception.log_failure(image,'fixture',error)
    text=path.read_text();saved=json.loads(text)
    assert 'PRIVATE' not in text and 'password' not in text and saved['http_status']==503


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_failed_stage_diagnostics_persist_run_identity_in_reviewer_report(client,tmp_path,kind):
    from src import api,runtime_store
    from test_report_pdf import seed_case
    case_id=seed_case(tmp_path,kind)
    with runtime_store.connection(api.DB_PATH) as conn:job=runtime_store.latest_job(conn,case_id)
    diagnostic=failure_detail(SimpleNamespace(code=503),'perception',attempt_count=1,attempted_network=True,model='fixture-model')
    api._set_job(job['job_id'],failures=[diagnostic],root_failure_detail=diagnostic)
    report=client.get(f'/v1/cases/{case_id}/report',headers=auth(client)).json()
    saved=report['processing']['root_failure_detail']
    assert saved['run_id']==job['job_id'] and saved['case_id']==case_id and saved['model']=='fixture-model'
    assert report['assessment_presentation']['category'] is None


def test_request_plan_counts_images_followups_and_actual_iteration_caps():
    from scripts.diagnose_gemini import request_plan
    result=request_plan()
    assert result['total_including_probe_minimum']==10
    assert result['total_with_probe_and_one_tool_followup_per_case']==12
    assert result['worst_case_including_one_schema_retry_per_image_and_agent_iteration_caps']==31


@pytest.mark.parametrize('opt_in',[None,'0'])
def test_perception_legacy_functions_cannot_bypass_live_opt_in(monkeypatch,opt_in):
    import unittest
    import test_perception as integration
    if opt_in is None:monkeypatch.delenv('FRAUDLENS_TEST_LIVE',raising=False)
    else:monkeypatch.setenv('FRAUDLENS_TEST_LIVE',opt_in)
    def forbidden():raise AssertionError('Disabled perception test reached provider construction.')
    monkeypatch.setattr(integration,'get_provider',forbidden)
    for name in integration._LIVE_TESTS:
        with pytest.raises(unittest.SkipTest):getattr(integration,name)()


@pytest.mark.parametrize('kind',['chat','vision'])
def test_known_truncated_cache_is_ignored_and_normal_controls_apply(controlled,monkeypatch,kind):
    entry={'text':'{"looks_valid":true}','raw':{'candidates':[{'finish_reason':'MAX_TOKENS'}]}}
    monkeypatch.setattr(llm.db,'cache_get',lambda *args:entry)
    calls=[]
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    def blocked(*args,**kwargs):calls.append(1);raise session_budget.ProviderCircuitOpen('fixture circuit')
    monkeypatch.setattr(provider,'_call_rotating',blocked)
    path=controlled/'sample.png';Image.new('RGB',(8,8)).save(path)
    with pytest.raises(session_budget.ProviderCircuitOpen):
        if kind=='chat':provider.chat([{'role':'user','content':'fixture'}],conn=object())
        else:provider.describe_image(str(path),'fixture',conn=object())
    assert calls==[1]


@pytest.mark.parametrize('reason',['generic_text','cached','failed_recovery','budget','unmatched_attempt'])
def test_rehearsal_does_not_trust_old_probe_success_or_overrun_allowance(reason):
    from scripts.prepare_analysis_rehearsal import validate_recovery
    result={'success':True,'cached':False,'structured_observation_valid':True,'recovery_id':'fixture','attempts_after':3}
    ledger={'attempts':3,'recoveries':[{'recovery_id':'fixture','status':'validation_authorized','allowance':13,'reserved':1}],
            'events':[{'attempt':3,'outcome':'success','recovery_id':'fixture'}]}
    if reason=='generic_text':result.pop('structured_observation_valid')
    if reason=='cached':result['cached']=True
    if reason=='failed_recovery':ledger['recoveries'][0]['status']='failed'
    if reason=='budget':ledger['recoveries'][0]['allowance']=2
    if reason=='unmatched_attempt':result['attempts_after']=2
    with pytest.raises(ValueError):validate_recovery(result,ledger,7)
