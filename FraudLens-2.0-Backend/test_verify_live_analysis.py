"""Saved-state qualification boundaries; fictional records and no provider calls."""
from copy import deepcopy
import json
import sys

import pytest

from scripts import verify_live_analysis as verify
from src.perception import PERCEPTION_SCHEMA_VERSION


OBSERVATIONS = {
    'damage_description': 'A small visible bumper dent.', 'damage_severity': 'minor',
    'weather_observed': 'unknown', 'road_condition': 'Not visible',
    'shadow_direction': 'none_visible', 'shadow_length': 'none', 'lighting': 'daylight',
    'plate_text': '', 'scene_context': 'A parked vehicle.', 'anomaly_notes': '',
}
RECOVERY = 'fictional-existing-recovery'


@pytest.fixture
def qualification(tmp_path):
    """Both fictional workflows have distinct exact-run fresh stage evidence."""
    ledger_path = tmp_path / 'original-ledger.json'
    ledger = {'attempts': 6, 'stopped': 'original circuit retained',
              'recoveries': [{'recovery_id': RECOVERY, 'status': 'validation_authorized',
                              'allowance': 12, 'reserved': 4,
                              'validation_authorized_at': '2026-10-20T07:59:00+00:00'}], 'events': []}
    accepted = {}
    saved = {name: [] for name in ('cases', 'jobs', 'results', 'decisions',
                                  'findings', 'images', 'events', 'perceptions')}
    for index, workflow in enumerate(('claims', 'underwriting')):
        case_id, run_id = f'fictional-{workflow}', f'fictional-{workflow}-run'
        image_id, finding_id, decision_id = (f'{workflow}-{kind}' for kind in ('image', 'finding', 'decision'))
        content_hash = str(index + 1) * 64
        hour = 8 + index
        created = f'2026-10-20T{hour:02d}:00:00+00:00'
        updated = f'2026-10-20T{hour:02d}:10:00+00:00'
        provenances = []
        for offset in range(2):
            attempt = 3 + index * 2 + offset
            started = f'2026-10-20T{hour:02d}:0{offset + 1}:00+00:00'
            completed = f'2026-10-20T{hour:02d}:0{offset + 1}:10+00:00'
            ledger['events'].append({'attempt': attempt, 'outcome': 'success',
                'recovery_id': RECOVERY, 'model': 'fictional-model',
                'time': started, 'completed_at': completed})
            provenances.append({'session_attempt': attempt, 'requested_model': 'fictional-model',
                                'timestamp': completed})
        sources = [{'source': 'fresh_provider', 'request_provenance': provenances[1]}]
        job = {'case_id': case_id, 'job_id': run_id, 'status': 'completed', 'stage': 'completed',
               'created_at': created, 'updated_at': updated,
               'perception_sources': {'fresh_provider': 1}, 'adjudication_sources': sources}
        finding = {'finding_id': finding_id, 'check_id': 'scene_consistency',
                   'verdict': 'INCONCLUSIVE', 'contribution': None, 'execution_state': 'completed'}
        explanation = {'run_id': run_id, 'assessment_type': 'agent_routing', 'findings': [finding],
            'aggregation': {'method': 'model_routing', 'computed_value': None,
                            'unrounded_value': None, 'valid_numeric_score': False},
            'routing': {'converged': True, 'source': 'model', 'recorded_band': 'desk_review',
                        'recommendation': 'desk_review'}, 'coverage': {}}
        event = {'run_id': run_id, 'decision_id': decision_id, 'arm': 'agent',
                 'converged': True, 'risk_band': 'desk_review',
                 'assessment_explanation': explanation, 'model_response_sources': sources}
        accepted[workflow] = {'submitted': {'case_id': case_id, 'job_id': run_id}}
        saved['cases'].append({'case_id': case_id, 'agent_type': workflow})
        saved['jobs'].append({'case_id': case_id, 'job_id': run_id, 'payload': job})
        saved['results'].append({'case_id': case_id, 'run_id': run_id, 'converged': 1,
                                'decision_id': decision_id, 'finding_ids': [finding_id],
                                'image_ids': [image_id]})
        saved['decisions'].append({'case_id': case_id, 'decision_id': decision_id,
            'risk_band': 'desk_review', 'recommendation': 'desk_review', 'score': None,
            'policy_version': 'agent-production-fictional'})
        saved['findings'].append({**finding, 'case_id': case_id, 'created_at': updated})
        saved['images'].append({'case_id': case_id, 'image_id': image_id, 'content_hash': content_hash})
        saved['events'].append({'case_id': case_id, 'details': event})
        saved['perceptions'].append({'content_hash': content_hash, 'source': 'fictional-model',
            'embedding': None, 'caption': None, 'ocr_text': None, **OBSERVATIONS,
            'created_at': updated, 'raw_response': json.dumps({'parsed': OBSERVATIONS,
                'schema_version': PERCEPTION_SCHEMA_VERSION, 'request_provenance': provenances[0]})})
    return accepted, saved, ledger, ledger_path


def checked(documents):
    accepted, saved, ledger, ledger_path = documents
    return verify.verify_saved(accepted, saved, ledger, ledger_path, RECOVERY,
                               'fraudlens_repair_fictional')


def test_distinct_successful_workflows_produce_proof_without_mutating_saved_inputs(qualification):
    before = deepcopy(qualification)
    proof, audit = checked(qualification)
    assert audit['status'] == 'verified' and audit['errors'] == []
    assert [row['vision_attempts'] for row in proof['observations']] == [[3], [5]]
    assert [row['agent_attempts'] for row in proof['observations']] == [[4], [6]]
    assert qualification == before


def test_database_json_columns_are_decoded_without_losing_exact_run_proof(qualification):
    _, saved, _, _ = qualification
    for job in saved['jobs']:
        job['payload'] = json.dumps(job['payload'])
    for result in saved['results']:
        for field in ('finding_ids', 'image_ids'):
            result[field] = json.dumps(result[field])
    for event in saved['events']:
        event['details'] = json.dumps(event['details'])
    proof, audit = checked(qualification)
    assert proof is not None and audit['status'] == 'verified'


def test_retained_failed_claim_and_missing_underwriting_emit_audit_only(qualification, tmp_path):
    accepted, saved, ledger, _ = qualification
    del accepted['underwriting']
    job = saved['jobs'][0]['payload']
    job.update(status='failed', stage='needs_review',
               root_failure_detail={'stage': 'perception', 'error_category': 'provider_http_error',
                                    'attempt_count': 1, 'attempted_network': True})
    ledger['recoveries'][0]['status'] = 'failed'
    proof, audit = checked(qualification)
    assert proof is None and audit['status'] == 'blocked'
    assert any('not authorized for validation' in error for error in audit['errors'])
    assert any(error.startswith('claims:') for error in audit['errors'])
    assert any(error.startswith('underwriting:') for error in audit['errors'])
    assert audit['observations'][0]['root_failure']['attempted_network'] is True
    output = tmp_path / 'blocked'
    verify.emit(output, proof, audit)
    assert {path.name for path in output.iterdir()} == {'audit.json'}
    assert json.loads((output / 'audit.json').read_text())['status'] == 'blocked'


@pytest.mark.parametrize('replacement', ['request_cache', 'perception_cache'])
def test_cached_agent_response_cannot_prove_live_adjudication(qualification, replacement):
    _, saved, _, _ = qualification
    # The job and audit agree about reuse, but reuse is not fresh qualification.
    saved['jobs'][0]['payload']['adjudication_sources'][0]['source'] = replacement
    proof, audit = checked(qualification)
    assert proof is None
    assert any('fresh adjudication request' in error for error in audit['errors'])


def test_historical_vision_provenance_cannot_count_as_fresh(qualification):
    _, saved, ledger, _ = qualification
    ledger['events'][0]['time'] = '2026-10-19T08:01:00+00:00'
    ledger['events'][0]['completed_at'] = '2026-10-19T08:01:10+00:00'
    proof, audit = checked(qualification)
    assert proof is None
    assert any('parsed fresh vision request' in error for error in audit['errors'])


def test_one_successful_request_cannot_prove_both_vision_and_adjudication(qualification):
    _, saved, _, _ = qualification
    saved['jobs'][0]['payload']['adjudication_sources'][0]['request_provenance']['session_attempt'] = 3
    proof, audit = checked(qualification)
    assert proof is None
    assert any('reused as multiple live-stage proofs' in error for error in audit['errors'])


@pytest.mark.parametrize('invalid', ['failed', 'foreign_recovery', 'wrong_model', 'outside_run',
                                    'duplicate_attempt', 'invalid_parse', 'missing_perception'])
def test_request_and_observation_provenance_must_be_verified(qualification, invalid):
    _, saved, ledger, _ = qualification
    if invalid == 'failed':
        ledger['events'][0]['outcome'] = 'failure:503'
    elif invalid == 'foreign_recovery':
        ledger['events'][0]['recovery_id'] = 'unrelated-recovery'
    elif invalid == 'wrong_model':
        ledger['events'][0]['model'] = 'unrelated-model'
    elif invalid == 'outside_run':
        ledger['events'][0]['completed_at'] = '2026-10-20T08:11:00+00:00'
    elif invalid == 'duplicate_attempt':
        ledger['events'].append(deepcopy(ledger['events'][0]))
    elif invalid == 'invalid_parse':
        raw = json.loads(saved['perceptions'][0]['raw_response'])
        raw['parsed'] = {**raw['parsed'], 'damage_severity': ['invalid']}
        saved['perceptions'][0]['raw_response'] = json.dumps(raw)
    else:
        saved['perceptions'].pop(0)
    proof, audit = checked(qualification)
    assert proof is None and audit['status'] == 'blocked'
    assert any(error.startswith('claims:') for error in audit['errors'])


@pytest.mark.parametrize('invalid', ['newer_run', 'wrong_finding', 'numeric_routing', 'missing_score_key'])
def test_proof_requires_the_exact_current_run_and_production_null_score(qualification, invalid):
    _, saved, _, _ = qualification
    explanation = saved['events'][0]['details']['assessment_explanation']
    if invalid == 'newer_run':
        saved['jobs'].append({'case_id': saved['cases'][0]['case_id'], 'job_id': 'newer-run',
                              'payload': {}})
    elif invalid == 'wrong_finding':
        saved['results'][0]['finding_ids'] = ['not-this-run-finding']
    elif invalid == 'numeric_routing':
        explanation['aggregation']['computed_value'] = 0.5
    else:
        del explanation['aggregation']['computed_value']
    proof, audit = checked(qualification)
    assert proof is None and audit['status'] == 'blocked'
    assert any(error.startswith('claims:') for error in audit['errors'])


def test_successful_output_cannot_overwrite_retained_artifacts(qualification, tmp_path):
    proof, audit = checked(qualification)
    output = tmp_path / 'qualification'
    verify.emit(output, proof, audit)
    assert {path.name for path in output.iterdir()} == {'audit.json', 'live-validation.json'}
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(verify.VerificationError, match='previous verification artifacts are retained'):
        verify.emit(output, None, {'status': 'blocked'})
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_cli_connection_failure_records_only_sanitized_audit(tmp_path, monkeypatch, capsys):
    """A connection exception must never disclose connection secrets or mint proof."""
    from src import db
    ledger_path = tmp_path / 'ledger.json'
    ledger_path.write_text('{}')
    accepted_path = tmp_path / 'accepted.json'
    accepted_path.write_text('{}')
    output = tmp_path / 'sanitized'
    monkeypatch.setattr(verify, 'ORIGINAL_LEDGER', ledger_path)
    monkeypatch.setattr(sys, 'argv', ['verify_live_analysis.py', '--schema', 'fraudlens_repair_fictional',
                        '--accepted-cases', str(accepted_path), '--output', str(output)])
    # Never read real dotenv credentials or connect to a real database.
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **k: None)
    def refused_connection(*args, **kwargs):
        raise RuntimeError('postgresql://fictional:secret-sentinel@invalid/database')
    monkeypatch.setattr(db, 'connect', refused_connection)
    assert verify.main() == 2
    output_text = (output / 'audit.json').read_text() + capsys.readouterr().out
    assert 'secret-sentinel' not in output_text and 'postgresql://' not in output_text
    assert not (output / 'live-validation.json').exists()
    assert json.loads((output / 'audit.json').read_text())['error_type'] == 'RuntimeError'
