"""Correction-specific recovery: real SDK serialization, zero external HTTP."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import base64
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

from google import genai
import httpx
from PIL import Image
import pytest

from src import llm, perception, session_budget
from src.provider_contract import (SCHEMA_CORRECTION_COMMIT, SCHEMA_WIRE_VERSION,
    perception_correction_contract)
from test_analysis_recovery import stopped
from test_engine_reliability import OBSERVATIONS


@pytest.fixture
def correction(stopped, monkeypatch, tmp_path):
    path, _ = stopped
    monkeypatch.setenv('GEMINI_MODEL', llm.GEMINI_MODEL)
    monkeypatch.setenv('FRAUDLENS_GEMINI_REQUEST_PROFILE', 'gemini3_defaults_v2')
    prior = session_budget.authorize_recovery('Controlled legacy-schema probe')
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID', prior)
    session_budget.outcome(SimpleNamespace(code=400), attempt=session_budget.reserve(llm.GEMINI_MODEL))
    # Match the real history shape: a later metadata success is not generation.
    metadata = session_budget.reserve_model_metadata(llm.GEMINI_MODEL, 'fixture', 'Controlled GET')
    session_budget.model_metadata_outcome(metadata)
    image = tmp_path/'sample.jpg'
    Image.new('RGB', (16, 10), 'gray').save(image)
    contract = perception_correction_contract(hashlib.sha256(image.read_bytes()).hexdigest(),
        llm.GEMINI_MODEL, 'gemini3_defaults_v2')
    kwargs = dict(operator='fixture-operator', previous_attempt=3,
        correction_commit=SCHEMA_CORRECTION_COMMIT, wire_version=SCHEMA_WIRE_VERSION,
        request_contract=contract, expected_attempts=4)
    return path, json.loads(path.read_text()), image, kwargs


def grant(correction, monkeypatch):
    recovery = session_budget.authorize_schema_correction('Explicit corrected-schema test', **correction[3])
    monkeypatch.setenv('FRAUDLENS_RECOVERY_ID', recovery)
    return recovery


@pytest.mark.parametrize('mutation', ['operator', 'commit', 'wire', 'attempt', 'race',
    'schema', 'prompt', 'profile', 'model', 'image_hash', 'quota_stop', 'cap', 'inflight'])
def test_correction_gate_refuses_unbound_or_unsafe_grants(correction, monkeypatch, mutation):
    path, state, _, original = correction
    args = deepcopy(original)
    if mutation == 'operator': args['operator'] = ''
    if mutation == 'commit': args['correction_commit'] = '0'*40
    if mutation == 'wire': args['wire_version'] = 'legacy'
    if mutation == 'attempt': args['previous_attempt'] = 2
    if mutation == 'race': args['expected_attempts'] = 3
    for target in ['schema', 'prompt']:
        if mutation == target: args['request_contract'][target+'_sha256'] = '0'*64
    if mutation == 'profile': args['request_contract']['request_profile'] = 'legacy'
    if mutation == 'model': args['request_contract']['model'] = 'different-model'
    if mutation == 'image_hash': args['request_contract']['image_sha256'] = 'invalid'
    if mutation == 'quota_stop': state['stopped'] = 'provider quota exhausted'
    if mutation == 'cap': monkeypatch.setenv('FRAUDLENS_LIVE_LIMIT', '4')
    if mutation == 'inflight': state['events'][-1]['outcome'] = 'reserved'
    path.write_text(json.dumps(state)); before = path.read_bytes()
    with pytest.raises((ValueError, session_budget.QuotaBudgetExhausted)):
        session_budget.authorize_schema_correction('Controlled refusal', **args)
    assert path.read_bytes() == before


@pytest.mark.parametrize('outcome', ['success', 'http400', 'invalid_json', 'invalid_enum'])
def test_corrected_full_schema_one_dispatch_and_traceable_result(correction, monkeypatch, outcome):
    path, before, image, args = correction
    grant(correction, monkeypatch)
    requests = []; original = genai.Client
    def handle(request):
        body = json.loads(request.content); requests.append(body)
        config = body['generationConfig']
        assert request.method == 'POST' and 'generateContent' in request.url.path
        assert 'responseSchema' not in config and config['responseMimeType'] == 'application/json'
        assert config['responseJsonSchema'] == perception.PerceptionObservation.model_json_schema()
        assert config['responseJsonSchema']['additionalProperties'] is False
        assert 'additional_properties' not in json.dumps(config)
        assert 'temperature' not in config
        parts = [p for content in body['contents'] for p in content['parts']]
        inline = next(p['inlineData'] for p in parts if 'inlineData' in p)
        assert inline['mimeType'] == 'image/jpeg'
        assert base64.urlsafe_b64decode(inline['data']) == image.read_bytes()
        assert next(p['text'] for p in parts if 'text' in p) == perception.PERCEPTION_PROMPT
        if outcome == 'http400':
            return httpx.Response(400, json={'error': {'code': 400, 'status': 'INVALID_ARGUMENT',
                'message': 'PRIVATE text omitted', 'details': [{'fieldViolations': [
                    {'field': 'generation_config.response_json_schema', 'description': 'PRIVATE details'}]}]}})
        text = json.dumps(OBSERVATIONS)
        if outcome == 'invalid_json': text = '{invalid'
        if outcome == 'invalid_enum': text = json.dumps({**OBSERVATIONS, 'lighting': 'invented'})
        return httpx.Response(200, json={'modelVersion': 'controlled-serving', 'responseId': 'controlled-request',
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]})
    def factory(**kwargs):
        options = kwargs['http_options']
        assert options.retry_options.attempts == 1 and options.client_args['follow_redirects'] is False
        options.client_args['transport'] = httpx.MockTransport(handle)
        return original(**kwargs)
    monkeypatch.setattr(genai, 'Client', factory)
    provider = llm.GeminiProvider(api_key='offline-placeholder', request_profile='gemini3_defaults_v2')
    try:
        if outcome == 'success':
            response = provider.describe_image(str(image), perception.PERCEPTION_PROMPT,
                retry_attempts=1, response_schema=perception.PerceptionObservation)
            assert not response.cached
            assert response.raw['request_provenance']['session_attempt'] == 5
            assert response.raw['request_provenance']['finish_reason'] == 'STOP'
            assert perception.PerceptionObservation.model_validate_json(response.text).lighting == 'daylight'
        else:
            with pytest.raises(Exception) as caught:
                provider.describe_image(str(image), perception.PERCEPTION_PROMPT,
                    retry_attempts=5, response_schema=perception.PerceptionObservation)
            from src.analysis_diagnostics import failure_detail
            detail = failure_detail(caught.value, 'controlled-probe')
            if outcome == 'http400':
                assert detail['invalid_request_fields'] == ['generation_config.response_json_schema']
            else: assert detail['validation_issues']
            assert 'PRIVATE' not in json.dumps(detail) and 'invented' not in json.dumps(detail)
        assert provider.http_attempts == len(requests) == 1
        state = json.loads(path.read_text())
        assert state['events'][:4] == before['events'] and state['recoveries'][:-1] == before['recoveries']
        assert state['stopped'] == before['stopped'] and state['attempts'] == 5
        assert state['events'][-1]['request_contract'] == args['request_contract']
        assert state['recoveries'][-1]['status'] == ('probe_succeeded' if outcome == 'success' else 'failed')
        with pytest.raises(session_budget.QuotaBudgetExhausted):
            provider.describe_image(str(image), perception.PERCEPTION_PROMPT,
                retry_attempts=1, response_schema=perception.PerceptionObservation)
        assert provider.http_attempts == 1
        monkeypatch.delenv('FRAUDLENS_RECOVERY_ID')
        with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()
        # Restart/re-read cannot grant this correction again.
        args = {**args, 'expected_attempts': 5}
        with pytest.raises(ValueError, match='already received'):
            session_budget.authorize_schema_correction('No unchanged repetition', **args)
    finally: provider.close()


@pytest.mark.parametrize('mutation', ['generic', 'legacy_schema', 'other_image', 'other_prompt'])
def test_only_bound_request_can_spend_grant(correction, monkeypatch, mutation):
    path, _, _, args = correction; grant(correction, monkeypatch)
    before = path.read_bytes(); contract = deepcopy(args['request_contract'])
    if mutation == 'generic': contract = None
    if mutation == 'legacy_schema': contract['wire_version'] = 'legacy'
    if mutation == 'other_image': contract['image_sha256'] = '0'*64
    if mutation == 'other_prompt': contract['prompt_sha256'] = '0'*64
    with pytest.raises(session_budget.ProviderCircuitOpen):
        session_budget.reserve(llm.GEMINI_MODEL, request_contract=contract)
    assert path.read_bytes() == before


def test_concurrent_correction_authorization_is_single_use(correction):
    path, before, _, args = correction
    code = ('import json;from src import session_budget;'
        'session_budget.authorize_schema_correction("Explicit controlled grant",**json.loads('+repr(json.dumps(args))+'))')
    def run(_):
        return subprocess.run([sys.executable, '-c', code], capture_output=True, env=os.environ.copy()).returncode
    with ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(run, range(3)))
    assert results.count(0) == 1
    after = json.loads(path.read_text())
    assert after['attempts'] == 4 and len(after['recoveries']) == len(before['recoveries'])+1
    assert after['events'] == before['events'] and after['recoveries'][:-1] == before['recoveries']


def test_future_workflow_needs_separate_explicit_bounded_validation_grant(correction, monkeypatch):
    path, before, _, args = correction
    recovery = grant(correction, monkeypatch)
    session_budget.outcome(attempt=session_budget.reserve(llm.GEMINI_MODEL, request_contract=args['request_contract']))
    with pytest.raises(session_budget.QuotaBudgetExhausted): session_budget.reserve(llm.GEMINI_MODEL)
    # Controlled ledger fixture only: no real allowance and no HTTP here.
    session_budget.authorize_validation(recovery, 2, 'Separately authorized controlled workflow')
    for _ in range(2): session_budget.outcome(attempt=session_budget.reserve(llm.GEMINI_MODEL))
    with pytest.raises(session_budget.QuotaBudgetExhausted): session_budget.reserve(llm.GEMINI_MODEL)
    monkeypatch.delenv('FRAUDLENS_RECOVERY_ID')
    with pytest.raises(session_budget.ProviderCircuitOpen): session_budget.check()
    assert json.loads(path.read_text())['stopped'] == before['stopped']


@pytest.mark.parametrize('disk_failure', [False, True])
def test_diagnostic_persists_datetime_and_receipt_without_second_call(correction, monkeypatch, tmp_path, disk_failure):
    from scripts import recover_provider
    from src import quota_budget
    path, _, image, _ = correction
    quota = Path(os.environ['GEMINI_QUOTA_BUDGET'])
    quota.write_text(json.dumps(quota_budget._base_state(20, '2026-10-22')))
    monkeypatch.setenv('FRAUDLENS_WORKER_ENABLED', '0')
    monkeypatch.setattr(recover_provider, 'load_pilot_environment', lambda source: dict(os.environ))
    monkeypatch.setattr(recover_provider, 'apply_pilot_environment', lambda env: None)
    monkeypatch.setattr(recover_provider, 'summarize', lambda env: {'fixture': True})
    client_class = genai.Client; provider_class = llm.GeminiProvider; sent = []
    def handle(request):
        sent.append(request.method)
        return httpx.Response(200, json={'modelVersion': 'controlled-serving', 'responseId': 'controlled-request',
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(OBSERVATIONS)}]}}]})
    def factory(**kwargs):
        kwargs['http_options'].client_args['transport'] = httpx.MockTransport(handle)
        return client_class(**kwargs)
    monkeypatch.setattr(genai, 'Client', factory)
    monkeypatch.setattr(llm, 'GeminiProvider', lambda **kwargs: provider_class(api_key='offline-placeholder', **kwargs))
    output = tmp_path/'output'
    monkeypatch.setattr(sys, 'argv', ['recover_provider.py', '--execute', '--operator', 'fixture',
        '--reason', 'Controlled artifact test', '--output', str(output), '--image', str(image),
        '--schema-correction-commit', SCHEMA_CORRECTION_COMMIT, '--previous-failed-attempt', '3'])
    write_text = Path.write_text
    def guarded_write(self, *args, **kwargs):
        if disk_failure and self.name == 'observation-record.json': raise OSError('Controlled write failure')
        return write_text(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', guarded_write)
    assert recover_provider.main() == (1 if disk_failure else 0)
    assert sent == ['POST']
    receipt = json.loads((output/'response-receipt.json').read_text())
    assert receipt['finish_reason'] == 'STOP' and receipt['request_provenance']['provider_request_id'] == 'controlled-request'
    result = json.loads((output/'probe-result.json').read_text())
    assert result['http_attempts'] == 1 and result['schema_validation'] == 'valid'
    if disk_failure:
        assert result['failure']['stage'] == 'probe_artifact_persistence'
        assert result['failure']['error_category'] == 'diagnostic_artifact_persistence'
        assert result['failure']['attempted_network'] and result['finish_reason'] == 'STOP'
    else:
        artifact = json.loads((output/'observation-record.json').read_text())
        assert isinstance(artifact['record']['created_at'], str)
        assert artifact['record']['content_hash'] == hashlib.sha256(image.read_bytes()).hexdigest()
        assert artifact['schema_version'] == perception.PERCEPTION_SCHEMA_VERSION
        assert artifact['record']['raw_response']['request_provenance']['serving_model'] == 'controlled-serving'
    assert json.loads(path.read_text())['stopped']
