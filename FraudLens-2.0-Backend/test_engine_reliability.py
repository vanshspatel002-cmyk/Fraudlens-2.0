"""Engine contracts on disposable SQLite; all model responses are explicit fixtures."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from src import db, perception, runtime_store
from src.agent import engine, tools
from src.agent.policy import CLAIMS_POLICY
from src.agent.production_policy import production_policy
from src.checks import REGISTRY, run_checks
from src.checks import provenance
from src.checks.base import CheckContext
from src.llm import LLMResponse, ToolCall
from src.models import Case, Image, PerceptionRecord, Verdict


OBSERVATIONS = {'damage_description': 'A small visible bumper dent.', 'damage_severity': 'minor',
    'weather_observed': 'unknown', 'road_condition': 'Not visible', 'shadow_direction': 'none_visible',
    'shadow_length': 'none', 'lighting': 'daylight', 'plate_text': '',
    'scene_context': 'A vehicle is parked beside a building.', 'anomaly_notes': ''}


@pytest.fixture
def store(tmp_path):
    conn = db.connect(':memory:'); db.init_db(conn); runtime_store.init(conn)
    case = Case(case_id='fixture-case', claimant_id='fictional', garage_id='UNASSIGNED',
                claim_type='collision', claim_amount=20000, vehicle_registration='EXAMPLE-1',
                declared_time=datetime(2026, 10, 20, tzinfo=timezone.utc))
    db.insert_case(conn, case)
    path = tmp_path/'evidence.png'
    from PIL import Image as Picture
    Picture.new('RGB', (32,32), 'blue').save(path)
    image = Image(image_id='fixture-image', case_id=case.case_id, path=str(path),
        content_hash=hashlib.sha256(path.read_bytes()).hexdigest(), phash='0'*16, dhash='0'*16)
    db.save_image(conn, image); conn.commit()
    try: yield conn, case, image
    finally: conn.close()


class VisionFixture:
    model = 'fixture-vision'
    def __init__(self, replies): self.replies=replies; self.calls=0; self.open_transactions=[]
    def describe_image(self, path, prompt, conn=None, **kwargs):
        self.open_transactions.append(conn.in_transaction)
        reply=self.replies[min(self.calls,len(self.replies)-1)]; self.calls+=1
        # Simulate the real provider's optional successful-request cache write.
        db.cache_set(conn,'fixture-response',str(self.calls),{'fixture':True})
        return LLMResponse(text=json.dumps(reply),tool_call=None,raw={},model=self.model,cached=False,latency_ms=1)


def test_failed_cache_can_recover_and_valid_cache_avoids_a_new_call(store):
    conn, case, image=store
    db.save_perception(conn,PerceptionRecord(content_hash=image.content_hash,source='old-fixture',
        raw_response={'error':'Prior schema failure'}));conn.commit()
    provider=VisionFixture([OBSERVATIONS]); provenance_info={}
    record=perception.perceive_image(conn,image,provider,provenance=provenance_info,release_transactions=True)
    conn.commit()
    assert provider.calls==1 and perception.perception_record_usable(record)
    assert record.source=='fixture-vision' and provenance_info['source']=='fresh_provider'
    again=perception.perceive_image(conn,image,provider,provenance=provenance_info)
    assert provider.calls==1 and again.damage_severity=='minor'
    assert provenance_info['source']=='perception_cache' and provenance_info['source_model']=='fixture-vision'


def test_schema_retry_releases_optional_cache_write_before_next_generation(store):
    conn,case,image=store
    provider=VisionFixture([{**OBSERVATIONS,'damage_severity':['invented']},OBSERVATIONS])
    record=perception.perceive_image(conn,image,provider,release_transactions=True)
    assert provider.calls==2 and provider.open_transactions==[False,False]
    assert record.damage_severity=='minor' and record.raw_response['schema_version']==perception.PERCEPTION_SCHEMA_VERSION


def test_invalid_json_schema_is_persisted_as_failure_and_never_used_by_checks(store):
    conn,case,image=store
    provider=VisionFixture([{**OBSERVATIONS,'damage_severity':'catastrophic'}])
    record=perception.perceive_image(conn,image,provider,release_transactions=True)
    assert record.raw_response['error'] and record.damage_severity is None
    assert record.raw_response['diagnostic']['error_category']=='response_schema_invalid'
    assert record.raw_response['diagnostic']['stage']=='perception_schema'
    finding=run_checks(conn,case,['damage_plausibility'])[0]
    assert finding.verdict is Verdict.INCONCLUSIVE and finding.confidence==0
    result=tools.requery_perception(conn,case,image.image_id)
    assert result['perception_available'] is False


@pytest.mark.parametrize('cached',[True,False])
def test_schema_failure_separates_cached_responses_from_network_attempts(store,cached):
    conn,case,image=store
    class InvalidFixture(VisionFixture):
        def describe_image(self,*args,**kwargs):
            response=super().describe_image(*args,**kwargs)
            response.cached=cached
            response.raw={'request_provenance':{'session_attempt':42,'requested_model':'fixture-requested',
                'serving_model':self.model,'timestamp':'2026-10-20T00:00:00Z','extra':'opaque-fixture'}}
            return response
    provider=InvalidFixture([{**OBSERVATIONS,'damage_severity':'invented'}])
    record=perception.perceive_image(conn,image,provider,release_transactions=True)
    diagnostic=record.raw_response['diagnostic']
    assert diagnostic['attempt_count']==(0 if cached else 2)
    assert diagnostic['response_count']==2 and diagnostic['attempted_network'] is (not cached)
    assert diagnostic['http_status'] is None and diagnostic['provider_status']=='response_received'
    assert set(record.raw_response['request_provenance'])=={'session_attempt','requested_model','serving_model','timestamp'}
    assert record.source==provider.model and 'opaque-fixture' not in json.dumps(record.raw_response)


def test_missing_exif_and_baseline_are_not_passed_authenticity(store):
    conn,case,image=store
    findings=run_checks(conn,case,['exif_metadata','baseline_linkage'])
    assert all(f.verdict is Verdict.INCONCLUSIVE and f.confidence==0 for f in findings)
    assert findings[0].evidence['exif_present'] is False
    assert findings[1].evidence['execution_state']=='not_applicable'


def test_wrong_case_type_precedes_perception_dependency_and_duplicate_check_ids_run_once(store):
    conn,case,image=store
    case=replace(case,agent_type='underwriting')
    findings=run_checks(conn,case,['severity_progression','damage_plausibility','damage_plausibility','scene_consistency'],config={'execution_states':True})
    assert len(findings)==3
    assert all(f.evidence['execution_state']=='not_applicable' for f in findings)


@pytest.mark.parametrize('prior_exists',[False,True])
def test_history_applicability_precedes_missing_perception(store,prior_exists):
    conn,case,image=store
    if prior_exists:
        db.insert_case(conn,replace(case,case_id='prior-unassessed',declared_time=case.declared_time-timedelta(days=1)))
        conn.commit()
    finding=run_checks(conn,case,['severity_progression'],config={'execution_states':True})[0]
    assert finding.verdict is Verdict.INCONCLUSIVE
    if prior_exists:
        assert finding.evidence['execution_state']=='inconclusive'
        assert 'fewer than two' in finding.explanation
    else:
        assert finding.evidence['execution_state']=='not_applicable'
        assert finding.evidence['reason']=='no_prior_claim_sequence'


def test_missing_perception_is_not_reported_as_an_invoked_measurement(store):
    conn,case,image=store
    findings=run_checks(conn,case,['scene_consistency','damage_plausibility'],config={'execution_states':True})
    assert findings and all(f.evidence['execution_state']=='not_run' for f in findings)
    assert all(f.evidence['missing_requirements']==['perception'] and f.confidence==0 for f in findings)


def test_baseline_requires_actual_complete_undamaged_observations(store):
    conn,case,image=store
    prior=replace(case,case_id='prior-inspection',agent_type='underwriting',declared_time=case.declared_time-timedelta(days=5))
    db.insert_case(conn,prior)
    previous_image=replace(image,image_id='prior-image',case_id=prior.case_id,content_hash='f'*64)
    db.save_image(conn,previous_image)
    db.save_perception(conn,PerceptionRecord(content_hash=image.content_hash,source='fixture',damage_severity='severe'))
    conn.commit()
    result=run_checks(conn,case,['baseline_linkage'])[0]
    assert result.verdict is Verdict.INCONCLUSIVE and result.evidence['reason']=='undamaged_baseline_unestablished'
    db.save_perception(conn,PerceptionRecord(content_hash=previous_image.content_hash,source='fixture',damage_severity='none'))
    result=run_checks(conn,case,['baseline_linkage'])[0]
    assert result.verdict is Verdict.CONCERN
    assert result.evidence['closest_inspection']['baseline_severity']=='none'
    assert 'passed a break-in inspection' not in result.explanation


def test_future_underwriting_and_conflicting_registration_do_not_create_a_baseline(store):
    conn,case,image=store
    db.insert_case(conn,replace(case,case_id='future',agent_type='underwriting',declared_time=case.declared_time+timedelta(days=1)))
    db.insert_case(conn,replace(case,case_id='different-car',agent_type='underwriting',vehicle_registration='OTHER',policy_number='POL',declared_time=case.declared_time-timedelta(days=1)))
    case=replace(case,policy_number='POL')
    result=run_checks(conn,case,['baseline_linkage'])[0]
    assert result.evidence['prior_inspections_found']==0 and result.verdict is Verdict.INCONCLUSIVE


class ContextFixture:
    settings=[]
    @classmethod
    def from_dict(cls, settings): cls.settings.append(settings); return cls()
    def __enter__(self): return self
    def __exit__(self,*args): return False


def c2pa_fixture(monkeypatch,payload=None,error=None):
    class Reader:
        def __init__(self,*args,**kwargs):
            if error: raise error
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def json(self):return json.dumps(payload)
    module=SimpleNamespace(Context=ContextFixture,Reader=Reader)
    monkeypatch.setattr(provenance,'_get_c2pa',lambda:module)


@pytest.mark.parametrize('state,codes,expected',[('Trusted',[],Verdict.PASS),('Valid',[],Verdict.PASS),
    ('Invalid',['assertion.dataHash.mismatch'],Verdict.CONCERN),('Invalid',['signingCredential.untrusted'],Verdict.INCONCLUSIVE),
    (None,[],Verdict.INCONCLUSIVE)])
def test_c2pa_uses_validation_results_instead_of_nonempty_json(store,monkeypatch,state,codes,expected):
    conn,case,image=store
    c2pa_fixture(monkeypatch,{'active_manifest':'fixture-manifest','validation_state':state,
        'validation_results':{'activeManifest':{'failure':[{'code':code} for code in codes]}}})
    finding=provenance.C2PA_CHECK.run(CheckContext(conn,case,[image],{}))[0]
    assert finding.verdict is expected
    assert ContextFixture.settings[-1]['verify']=={'remote_manifest_fetch':False,'ocsp_fetch':False}


def test_c2pa_manifest_runtime_error_is_failed_not_absent_or_tampered(store,monkeypatch):
    conn,case,image=store
    c2pa_fixture(monkeypatch,error=RuntimeError('manifest SDK failure at a private path'))
    finding=provenance.C2PA_CHECK.run(CheckContext(conn,case,[image],{}))[0]
    assert finding.verdict is Verdict.INCONCLUSIVE and finding.evidence['execution_state']=='failed'
    assert finding.evidence['credentials_present'] is None
    assert 'private path' not in json.dumps(finding.evidence)


def test_c2pa_unsigned_image_is_inconclusive(store,monkeypatch):
    conn,case,image=store
    class ManifestNotFound(Exception):pass
    c2pa_fixture(monkeypatch,error=ManifestNotFound('No embedded credentials'))
    finding=provenance.C2PA_CHECK.run(CheckContext(conn,case,[image],{}))[0]
    assert finding.verdict is Verdict.INCONCLUSIVE and finding.confidence==0
    assert finding.evidence['credentials_present'] is False


def test_check_exception_keeps_diagnostic_and_allows_independent_checks(store,monkeypatch):
    conn,case,image=store
    def fail(ctx):raise ImportError('Missing fixture dependency')
    monkeypatch.setattr(REGISTRY['c2pa_credentials'],'run',fail)
    findings=run_checks(conn,case,['c2pa_credentials','exif_metadata'])
    assert len(findings)==2
    assert findings[0].evidence['execution_state']=='failed'
    assert findings[0].evidence['diagnostic']['error_category']=='missing_dependency'
    assert findings[1].evidence['execution_state']=='inconclusive'


class AgentFixture:
    def __init__(self):self.calls=[]
    def chat(self,messages,**kwargs):
        self.calls.append(list(messages))
        if len(self.calls)==1:
            return LLMResponse(text='',tool_call=ToolCall(name='get_claimant_history',args={}),raw={},model='fixture-agent',cached=False,latency_ms=1,
                model_content={'role':'model','parts':[{'function_call':{'name':'get_claimant_history','args':{}},'thought_signature':b'opaque-fixture-signature'}]})
        return LLMResponse(text=json.dumps({'risk_band':'desk_review','recommendation':'escalate','narrative':'A human must inspect the original evidence.',
            'findings_cited':[],'requested_artifacts':[]}),tool_call=None,raw={},model='fixture-agent',cached=False,latency_ms=1)


def test_agent_preserves_function_content_but_never_logs_opaque_signature(store):
    conn,case,image=store
    provider=AgentFixture()
    result=engine.adjudicate(conn,case,[],CLAIMS_POLICY,provider)
    history=provider.calls[1]
    assert history[-2]['provider_content']['parts'][0]['thought_signature']==b'opaque-fixture-signature'
    assert history[-1]['role']=='tool' and history[-1]['name']=='get_claimant_history'
    trace=result.trace_dicts()
    assert 'opaque-fixture-signature' not in json.dumps(trace)
    step=next(step for step in trace if step['kind']=='tool_call')
    assert step['payload']['observation']['other_case_count']==0
    assert result.converged


@pytest.mark.parametrize('maximum_calls',[1,2])
def test_parallel_tool_calls_all_receive_results_under_the_existing_cap(store,monkeypatch,maximum_calls):
    from src import llm
    conn,case,image=store
    executed=[]
    def call_tool(name,*args,**kwargs):
        executed.append(name)
        return {'tool':name,'other_case_count':0}
    monkeypatch.setattr(tools,'call_tool',call_tool)
    class ParallelFixture(AgentFixture):
        def chat(self,messages,**kwargs):
            if not self.calls:
                self.calls.append(list(messages))
                calls=[ToolCall('get_claimant_history',{},'first'),ToolCall('get_garage_history',{},'second')]
                content={'role':'model','parts':[{'function_call':{'name':call.name,'args':call.args,'id':call.id},
                         'thought_signature':'opaque-fixture'} for call in calls]}
                return LLMResponse('',calls[0],{},'fixture',False,1,content,calls)
            self.calls.append(list(messages))
            contents=llm._to_gemini_contents(messages)
            responses=contents[-1]['parts']
            assert [part['function_response']['id'] for part in responses]==['first','second']
            assert len(responses)==2
            if maximum_calls==1:
                assert 'limit' in responses[1]['function_response']['response']['error'].lower()
            return LLMResponse(json.dumps({'risk_band':'desk_review','recommendation':'escalate',
                'narrative':'Review the available evidence.','findings_cited':[],'requested_artifacts':[]}),None,{},'fixture',False,1)
    result=engine.adjudicate(conn,case,[],replace(CLAIMS_POLICY,max_tool_calls=maximum_calls),ParallelFixture())
    assert result.converged and result.decision.tool_calls_count==maximum_calls
    assert executed==['get_claimant_history','get_garage_history'][:maximum_calls]
    assert 'opaque-fixture' not in json.dumps(result.trace_dicts())


def test_run_specific_explanation_is_persisted_with_findings_and_decision(store):
    from src.orchestrator import process_case
    conn,case,image=store
    job=runtime_store.enqueue(conn,case.case_id);conn.commit()
    policy=replace(production_policy('claims'),check_ids=('exif_metadata',))
    decision=process_case(conn,case.case_id,policy,AgentFixture(),run_id=job['job_id'])
    result=conn.execute('SELECT finding_ids,decision_id FROM processing_results WHERE run_id=?',(job['job_id'],)).fetchone()
    event=next(event for event in db.get_audit_events_for_case(conn,case.case_id) if event.event_type=='case_adjudicated')
    saved=event.details['assessment_explanation']
    assert saved==decision._assessment_explanation and saved['run_id']==job['job_id']
    assert saved['aggregation']['computed_value'] is None and result['decision_id']==decision.decision_id
    assert json.loads(result['finding_ids'])==[row['finding_id'] for row in saved['findings']]
    assert saved['coverage']['check_states']['exif_metadata']=='inconclusive'


@pytest.mark.parametrize('release_transactions',[False,True])
def test_agent_releases_owned_tool_writes_but_preserves_standalone_transaction_ownership(store,monkeypatch,release_transactions):
    conn,case,image=store
    transactions=[]
    class TransactionFixture(AgentFixture):
        def chat(self,*args,**kwargs):
            transactions.append(conn.in_transaction)
            return super().chat(*args,**kwargs)
    def cached_history(tool_conn,case,**kwargs):
        db.cache_set(tool_conn,'fixture-agent-tool','history',{'fixture':True})
        assert tool_conn.in_transaction
        return {'tool':'get_claimant_history','other_case_count':0,'cases':[]}
    monkeypatch.setitem(tools.TOOLS,'get_claimant_history',cached_history)
    db.cache_set(conn,'fixture-agent-tool','before',{'fixture':True})
    assert conn.in_transaction
    result=engine.adjudicate(conn,case,[],CLAIMS_POLICY,TransactionFixture(),release_transactions=release_transactions)
    assert result.converged and transactions==[not release_transactions,not release_transactions]
    assert conn.in_transaction is (not release_transactions)


def comparison_fixture(conn,case,image,identifier,created,embedding=(1.0,0.0),image_created=None):
    other=replace(case,case_id=identifier,created_at=created)
    db.insert_case(conn,other)
    photo=replace(image,image_id=identifier+'-image',case_id=identifier,content_hash=hashlib.sha256(identifier.encode()).hexdigest(),
                  embedding=list(embedding),created_at=image_created or created)
    db.save_image(conn,photo)
    return other,photo


def test_duplicate_excludes_self_same_case_future_cases_and_future_evidence(store):
    from src.ingest import SimilarityIndex
    conn,case,image=store
    image=replace(image,embedding=[1.,0.]);conn.execute('UPDATE images SET embedding=? WHERE image_id=?',(json.dumps(image.embedding),image.image_id))
    db.save_image(conn,replace(image,image_id='same-case-image',content_hash='a'*64))
    past,prior=comparison_fixture(conn,case,image,'prior-case',case.created_at-timedelta(days=2))
    comparison_fixture(conn,case,image,'future-case',case.created_at+timedelta(days=1))
    comparison_fixture(conn,case,image,'late-evidence',case.created_at-timedelta(days=1),image_created=case.created_at+timedelta(days=1))
    cutoff=case.created_at.isoformat()
    index=SimilarityIndex.from_database(conn,case.case_id,cutoff)
    assert [candidate.image_id for candidate in index.candidates]==[prior.image_id]
    results=run_checks(conn,case,['internal_duplicate'],config={'evaluation_cutoff':cutoff})
    assert len(results)==2 and all(result.verdict is Verdict.CONCERN for result in results)
    assert all(result.evidence['matched_case_id']==past.case_id and result.evidence['images_compared']==1 for result in results)
    # The agent cannot widen its way around the trusted evaluation date.
    widened=tools.call_tool('widen_similarity_search',conn,case,{'threshold':.8,'evaluation_cutoff':(case.created_at+timedelta(days=10)).isoformat()},evaluation_cutoff=cutoff)
    assert widened['matches'] and all(match['matched_case_id']==past.case_id for match in widened['matches'])
    assert tools.get_claimant_history(conn,case,evaluation_cutoff=cutoff)['other_case_count']==2


def test_duplicate_known_negative_has_no_candidate_or_low_similarity_concern(store):
    conn,case,image=store
    image=replace(image,embedding=[1.,0.]);conn.execute('UPDATE images SET embedding=? WHERE image_id=?',(json.dumps(image.embedding),image.image_id))
    comparison_fixture(conn,case,image,'future-identical',case.created_at+timedelta(days=1))
    cutoff=case.created_at.isoformat()
    result=run_checks(conn,case,['internal_duplicate'],config={'evaluation_cutoff':cutoff})[0]
    assert result.verdict is Verdict.INCONCLUSIVE and result.evidence['images_compared']==0
    comparison_fixture(conn,case,image,'prior-unrelated',case.created_at-timedelta(days=1),embedding=(0.,1.))
    result=run_checks(conn,case,['internal_duplicate'],config={'evaluation_cutoff':cutoff})[0]
    assert result.verdict is Verdict.PASS and result.evidence['cosine_similarity']==0


def test_installed_c2pa_reads_a_real_unsigned_png_offline(store):
    pytest.importorskip('c2pa')
    conn,case,image=store
    result=provenance.C2PA_CHECK.run(CheckContext(conn,case,[image],{}))[0]
    assert result.verdict is Verdict.INCONCLUSIVE and result.evidence['credentials_present'] is False
    assert result.evidence['execution_state']=='inconclusive'


@pytest.mark.parametrize('value',['not-an-array',{'invented':'id'},[4]])
def test_agent_decision_schema_rejects_non_string_citation_arrays(value):
    payload={'risk_band':'clear','recommendation':'approve','narrative':'Fixture output.',
             'findings_cited':value,'requested_artifacts':[]}
    assert engine.parse_decision(json.dumps(payload)) is None


@pytest.mark.parametrize('cache_states',[(True,True),(False,False),(True,False),(False,True),(None,None)])
def test_agent_invalid_schema_fallback_records_actual_response_sources_without_http_invention(store,cache_states):
    conn,case,image=store
    class InvalidFixture:
        calls=0
        def chat(self,*args,**kwargs):
            cached=cache_states[self.calls]
            self.calls+=1
            return LLMResponse(text='This is not a routing JSON object.',tool_call=None,
                raw={'request_provenance':{'session_attempt':42,'requested_model':'fixture-requested',
                     'serving_model':'fixture-serving','timestamp':'2026-10-20T00:00:00Z','extra':'opaque-fixture'}},
                model='fixture-serving',cached=cached,latency_ms=1)
    result=engine.adjudicate(conn,case,[],CLAIMS_POLICY,InvalidFixture())
    assert not result.converged and result.decision.risk_band.value=='desk_review'
    failures=[step for step in result.trace if step.kind=='parse_failure']
    assert len(failures)==2 and all('reply_preview' in step.payload for step in failures)
    diagnostic=result.trace[-1].payload['diagnostic']
    assert result.trace[-1].kind=='fallback' and diagnostic['stage']=='agent_response_schema'
    assert diagnostic['error_category']=='response_schema_invalid'
    assert diagnostic['provider_status']=='response_received' and diagnostic['http_status'] is None
    attempts=sum(state is False for state in cache_states)
    assert diagnostic['attempt_count']==attempts and diagnostic['attempted_network'] is bool(attempts)
    assert diagnostic['response_count']==2
    expected=['request_cache' if state is True else 'fresh_provider' if state is False else 'unrecorded' for state in cache_states]
    assert [source['source'] for source in diagnostic['response_sources']]==expected
    assert all(source['request_provenance']['serving_model']=='fixture-serving' for source in diagnostic['response_sources'])
    assert 'opaque-fixture' not in json.dumps(result.trace_dicts())


def test_agent_tool_iteration_limit_is_not_mislabeled_a_response_schema_failure(store):
    conn,case,image=store
    result=engine.adjudicate(conn,case,[],replace(CLAIMS_POLICY,max_iterations=1),AgentFixture())
    assert not result.converged and result.trace[-1].kind=='fallback'
    assert result.trace[-1].payload.get('diagnostic') is None
    assert not any(step.kind=='parse_failure' for step in result.trace)
