"""Read saved isolated live runs and produce evidence for the historical batch gate.

No model, API, PDF, schema-init, queue or ledger writes occur here. A successful
proof requires both genuine workflows and their distinct successful requests in
the ORIGINAL session ledger. A blocked run produces audit.json only, never a
plausible-looking live-validation.json. Output must be a new private directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ORIGINAL_LEDGER = ROOT / 'outputs/pilot_validation/live_calls.json'
WORKFLOWS = ('claims', 'underwriting')


class VerificationError(ValueError):
    """A fixed, safe-to-record validation failure, without raw provider data."""


def require(condition, reason):
    if not condition:
        raise VerificationError(reason)


def decoded(value, default=None):
    return json.loads(value) if isinstance(value, str) else value if value is not None else default


def references(accepted):
    result = {}
    for workflow in WORKFLOWS:
        submitted = (accepted.get(workflow) or {}).get('submitted') or {}
        case_id, run_id = submitted.get('case_id'), submitted.get('job_id')
        if isinstance(case_id, str) and case_id and isinstance(run_id, str) and run_id:
            result[workflow] = {'case_id': case_id, 'run_id': run_id}
    return result


def read_saved(conn, refs):
    """One bounded snapshot of just the accepted cases; leave no transaction open."""
    from src import db
    if not refs:
        return {}
    case_ids = [row['case_id'] for row in refs.values()]
    markers = ','.join('?' for _ in case_ids)
    conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if db.is_postgres(conn) else 'BEGIN')
    try:
        # This utility never calls runtime_store.init or any model-loading code.
        tables = {
            'cases': f'SELECT case_id,agent_type,status FROM cases WHERE case_id IN ({markers})',
            'jobs': f'SELECT job_id,case_id,status,payload FROM api_jobs WHERE case_id IN ({markers}) ORDER BY rowid',
            'results': f'SELECT * FROM processing_results WHERE case_id IN ({markers})',
            'decisions': f'SELECT decision_id,case_id,risk_band,recommendation,score,supporting_finding_ids,policy_version FROM agent_decisions WHERE case_id IN ({markers})',
            'findings': f'SELECT finding_id,case_id,check_id,verdict,created_at FROM findings WHERE case_id IN ({markers})',
            'images': f'SELECT image_id,case_id,content_hash FROM images WHERE case_id IN ({markers})',
            'events': f"SELECT case_id,details FROM audit_log WHERE event_type='case_adjudicated' AND case_id IN ({markers})",
            'perceptions': f'SELECT * FROM perception_records WHERE content_hash IN (SELECT content_hash FROM images WHERE case_id IN ({markers}))',
        }
        saved = {name: [dict(row) for row in conn.execute(query, case_ids)] for name, query in tables.items()}
    finally:
        conn.rollback()
    return saved


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    require(isinstance(value, str), 'A request or run timestamp is missing.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'A request timestamp has no timezone.')
        return result.timestamp()
    except ValueError:
        raise VerificationError('A request or run timestamp is invalid.') from None


def current_recovery(ledger, configured=None):
    rows = ledger.get('recoveries') or []
    if configured:
        row = next((row for row in rows if row.get('recovery_id') == configured), None)
        require(row is not None, 'The configured recovery is absent from the original ledger.')
        return row
    require(len(rows) == 1, 'Use the existing unambiguous audited recovery ID.')
    return rows[0]


def request_attempt(provenance, ledger, recovery_id, job):
    """Prove the request happened successfully during this run and recovery."""
    require(isinstance(provenance, dict), 'Fresh response request provenance is missing.')
    attempt = provenance.get('session_attempt')
    require(isinstance(attempt, int) and not isinstance(attempt, bool), 'A response has no integer session attempt.')
    events = [event for event in ledger.get('events', []) if event.get('attempt') == attempt]
    require(len(events) == 1, 'The response attempt is absent or duplicated in the original ledger.')
    event = events[0]
    require(event.get('outcome') == 'success', 'The response attempt is not a successful original-ledger request.')
    require(event.get('recovery_id') == recovery_id, 'The response attempt belongs to a different recovery.')
    require(provenance.get('requested_model') == event.get('model') and bool(event.get('model')), 'The response requested model differs from the original ledger.')
    created, updated = timestamp(job.get('created_at')), timestamp(job.get('updated_at'))
    started, completed, response_at = timestamp(event.get('time')), timestamp(event.get('completed_at')), timestamp(provenance.get('timestamp'))
    require(created <= started <= completed <= updated + 5 and started <= response_at <= updated + 5,
            'The response attempt is outside the accepted run; cached or historical provenance cannot prove a live request.')
    return attempt


def _matching(saved, table, field, value):
    return [row for row in saved.get(table, []) if row.get(field) == value]


def case_documents(saved, ref):
    case_id, run_id = ref['case_id'], ref['run_id']
    jobs = _matching(saved, 'jobs', 'case_id', case_id)
    rows = [row for row in jobs if row['job_id'] == run_id]
    job = decoded(rows[0].get('payload'), {}) if len(rows) == 1 else {}
    result_rows = _matching(saved, 'results', 'run_id', run_id)
    result = result_rows[0] if len(result_rows) == 1 else {}
    decisions = _matching(saved, 'decisions', 'decision_id', result.get('decision_id'))
    decision = decisions[0] if len(decisions) == 1 else {}
    events = [decoded(row.get('details'), {}) for row in _matching(saved, 'events', 'case_id', case_id)]
    events = [event for event in events if event.get('run_id') == run_id and event.get('decision_id') == result.get('decision_id')]
    event = events[0] if len(events) == 1 else {}
    return jobs, job, result, decision, event


def audit_case(saved, ref):
    jobs, job, result, decision, event = case_documents(saved, ref)
    explanation = event.get('assessment_explanation') or {}
    rows = explanation.get('findings') or []
    coverage = explanation.get('coverage') or {}
    routing = explanation.get('routing') or {}
    trace = event.get('trace') or []
    return {**ref, 'status': job.get('status', 'not_recorded'), 'stage': job.get('stage', 'not_recorded'),
        'has_result': bool(result), 'has_current_run_explanation': bool(explanation),
        'converged': bool(result.get('converged')), 'computed_value': (explanation.get('aggregation') or {}).get('computed_value'),
        'routing': {key: routing.get(key) for key in ('source', 'converged', 'recorded_band', 'recommendation')},
        'coverage': {key: coverage.get(key) for key in ('expected_check_ids', 'eligible_check_ids', 'missing_check_ids', 'check_states', 'state_counts', 'complete', 'material_complete')},
        'stage_counts': {'vision_sources': job.get('perception_sources') or {},
            'agent_sources': dict(Counter(item.get('source', 'unrecorded') for item in job.get('adjudication_sources') or [])),
            'trace_kinds': dict(Counter(item.get('kind', 'unrecorded') for item in trace)),
            'finding_verdicts': dict(Counter(row.get('verdict', 'unrecorded') for row in rows)),
            'finding_states': dict(Counter(row.get('execution_state', 'unrecorded') for row in rows))},
        'finding_ids': [row.get('finding_id') for row in rows],
        'root_failure': {key: (job.get('root_failure_detail') or {}).get(key) for key in ('stage', 'error_category', 'attempt_count', 'attempted_network')},
        'verification_status': 'not_ready'}


def prove_case(workflow, saved, ref, ledger, recovery_id):
    from src import db
    from src.perception import PERCEPTION_SCHEMA_VERSION, _schema_issues, perception_record_usable
    case_id, run_id = ref['case_id'], ref['run_id']
    cases = _matching(saved, 'cases', 'case_id', case_id)
    require(len(cases) == 1 and cases[0]['agent_type'] == workflow, 'The accepted case type is missing or mismatched.')
    jobs, job, result, decision, event = case_documents(saved, ref)
    require(bool(job) and jobs[-1]['job_id'] == run_id and job.get('case_id') == case_id, 'The accepted run is missing or no longer current.')
    require(job.get('status') == 'completed', 'The accepted processing job did not complete.')
    require(not job.get('provider_unavailable') and not job.get('failed_images') and not job.get('root_failure_detail'), 'The accepted run has an unresolved processing failure.')
    require(result.get('case_id') == case_id and result.get('converged') in (True, 1), 'A converged result for this exact run is missing.')
    require(decision.get('case_id') == case_id and bool(event), 'The exact saved decision or current-run adjudication audit is missing.')
    explanation = event.get('assessment_explanation') or {}
    require(explanation.get('run_id') == run_id and explanation.get('assessment_type') == 'agent_routing' and event.get('arm') == 'agent', 'The current-run production explanation is missing.')
    require(str(decision.get('policy_version', '')).startswith('agent-production-'), 'The saved decision is not the production agent policy.')
    aggregation, routing = explanation.get('aggregation') or {}, explanation.get('routing') or {}
    require(aggregation.get('method') == 'model_routing' and 'computed_value' in aggregation and aggregation['computed_value'] is None
            and aggregation.get('unrounded_value') is None and aggregation.get('valid_numeric_score') is False and decision.get('score') is None,
            'Production routing incorrectly contains or omits the required null numeric score.')
    require(routing.get('converged') is True and routing.get('source') == 'model' and event.get('converged') is True,
            'Saved production routing did not converge on a model result.')
    require(decision.get('risk_band') and decision['risk_band'] == event.get('risk_band') == routing.get('recorded_band')
            and decision.get('recommendation') == routing.get('recommendation'), 'Saved routing disagrees with the exact result decision.')
    result_ids = decoded(result.get('finding_ids'), [])
    rows = explanation.get('findings') or []
    require(bool(result_ids) and len(set(result_ids)) == len(result_ids) and [row.get('finding_id') for row in rows] == result_ids,
            'Explanation finding IDs do not match this exact new-run result.')
    actual = {row['finding_id']: row for row in _matching(saved, 'findings', 'case_id', case_id)}
    for row in rows:
        recorded = actual.get(row['finding_id']) or {}
        require(recorded.get('check_id') == row.get('check_id') and recorded.get('verdict') == row.get('verdict'), 'An explanation finding is missing from the actual case/run evidence.')
        require(timestamp(job['created_at']) <= timestamp(recorded.get('created_at')) <= timestamp(job['updated_at']) + 5,
                'An explanation finding predates the accepted run.')
        require(row.get('contribution') is None, 'A production finding invents a numeric contribution.')
    image_ids = decoded(result.get('image_ids'), [])
    images = _matching(saved, 'images', 'case_id', case_id)
    require(bool(image_ids) and set(image_ids) == {row['image_id'] for row in images}, 'Result evidence does not match the accepted case photographs.')
    perceptions = {row['content_hash']: row for row in saved.get('perceptions', [])}
    vision_attempts = []
    for content_hash in dict.fromkeys(image['content_hash'] for image in images):
        row = perceptions.get(content_hash)
        require(row is not None, 'An accepted photograph has no saved perception record.')
        record = db._perception_from_row(row)
        require(perception_record_usable(record), 'An accepted photograph has unusable saved observations.')
        raw = record.raw_response
        provenance = raw.get('request_provenance') or {}
        # Cache provenance from an earlier run is honest reuse, not fresh proof.
        matching = [event for event in ledger.get('events', []) if event.get('attempt') == provenance.get('session_attempt')]
        if matching and timestamp(matching[0].get('time')) >= timestamp(job['created_at']):
            require(raw.get('schema_version') == PERCEPTION_SCHEMA_VERSION and isinstance(raw.get('parsed'), dict)
                    and not _schema_issues(raw['parsed']), 'A fresh vision response has no valid parsed observation document.')
            vision_attempts.append(request_attempt(provenance, ledger, recovery_id, job))
    sources = job.get('adjudication_sources') or []
    require(bool(sources) and sources == event.get('model_response_sources'), 'Saved job and adjudication request provenance disagree or are missing.')
    agent_attempts = [request_attempt(source.get('request_provenance'), ledger, recovery_id, job)
                      for source in sources if source.get('source') == 'fresh_provider']
    require(bool(vision_attempts) and (job.get('perception_sources') or {}).get('fresh_provider') == len(vision_attempts), 'At least one parsed fresh vision request is not proven for this workflow.')
    require(bool(agent_attempts), 'At least one fresh adjudication request is not proven for this workflow.')
    used = vision_attempts + agent_attempts
    require(len(set(used)) == len(used), 'A single request attempt is reused as multiple live-stage proofs.')
    return {'workflow': workflow, **ref, 'status': 'completed', 'converged': True,
        'vision_status': 'parsed', 'vision_source': 'fresh_provider', 'vision_attempt': vision_attempts[0],
        'vision_attempts': vision_attempts, 'agent_attempts': agent_attempts}


def verify_saved(accepted, saved, ledger, ledger_path=ORIGINAL_LEDGER, recovery_id=None, schema=None):
    """Pure verification over collected records; never turns absent data into proof."""
    refs = references(accepted)
    audit = {'format': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'schema': schema,
        'status': 'blocked', 'ledger_attempts': ledger.get('attempts'), 'ledger_stopped': bool(ledger.get('stopped')),
        'observations': [], 'errors': []}
    recovery = {}
    try:
        recovery = current_recovery(ledger, recovery_id)
        require(recovery.get('status') == 'validation_authorized', 'The original audited recovery is not authorized for validation; no successful validation proof can be issued.')
    except VerificationError as error:
        audit['errors'].append(str(error))
    audit['recovery_status'] = recovery.get('status', 'not_recorded')
    observations = []
    for workflow in WORKFLOWS:
        ref = refs.get(workflow)
        if not ref:
            audit['observations'].append({'workflow': workflow, 'verification_status': 'not_ready'})
            audit['errors'].append(workflow + ': An accepted case/run document is missing.')
            continue
        summary = {'workflow': workflow, **audit_case(saved, ref)}
        audit['observations'].append(summary)
        try:
            observation = prove_case(workflow, saved, ref, ledger, recovery.get('recovery_id'))
            observations.append(observation)
            summary['verification_status'] = 'verified'
            summary['verified_attempts'] = {'vision': observation['vision_attempts'], 'agent': observation['agent_attempts']}
        except VerificationError as error:
            audit['errors'].append(workflow + ': ' + str(error))
    proof = {'format': 1, 'generated_at': audit['generated_at'], 'schema': schema,
        'ledger': str(Path(ledger_path).resolve()), 'recovery_id': recovery.get('recovery_id'), 'observations': observations}
    if not audit['errors']:
        try:
            require(len({row['case_id'] for row in observations}) == 2 and len({row['run_id'] for row in observations}) == 2,
                    'The two workflows do not have distinct accepted cases and runs.')
            attempts = [attempt for row in observations for attempt in row['vision_attempts'] + row['agent_attempts']]
            require(len(attempts) == len(set(attempts)), 'The workflows share a live request attempt.')
            from scripts.reprocess_history import validation_gate
            validation_gate(proof, ledger, ledger_path, recovery['recovery_id'])
        except ValueError:
            audit['errors'].append('The distinct live-workflow proof does not satisfy the historical batch gate.')
    if audit['errors']:
        return None, audit
    audit['status'] = 'verified'
    return proof, audit


def emit(output, proof, audit):
    output = Path(output)
    require(not output.exists(), 'Use a new private output directory; previous verification artifacts are retained.')
    output.mkdir(parents=True)
    (output / 'audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    if proof is not None:
        (output / 'live-validation.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', required=True)
    parser.add_argument('--accepted-cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(bool(re.fullmatch(r'fraudlens_repair_[a-z0-9_]{1,41}', args.schema)), 'Use an explicitly named isolated fraudlens_repair_ schema.')
    require(not args.output.exists(), 'Use a new private output directory; previous verification artifacts are retained.')
    try:
        accepted = json.loads(args.accepted_cases.read_text(encoding='utf-8'))
        ledger = json.loads(ORIGINAL_LEDGER.read_text(encoding='utf-8'))
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
        os.environ['FRAUDLENS_PG_SCHEMA'] = args.schema
        from src import db
        conn = db.connect('postgresql')
        try:
            saved = read_saved(conn, references(accepted))
        finally:
            conn.close()
        proof, audit = verify_saved(accepted, saved, ledger, ORIGINAL_LEDGER, os.environ.get('FRAUDLENS_RECOVERY_ID'), args.schema)
    except VerificationError as error:
        proof, audit = None, {'status': 'blocked', 'errors': [str(error)]}
    except Exception as error:
        # Never print raw connection/provider exceptions, accepted receipt tokens,
        # applicant fields, model replies or the server-only connection string.
        proof, audit = None, {'status': 'blocked', 'errors': ['Saved validation documents could not be verified.'], 'error_type': type(error).__name__}
    emit(args.output, proof, audit)
    print(json.dumps({'status': audit['status'], 'audit': str(args.output / 'audit.json'),
        'successful_validation_proof': proof is not None, 'model_requests': 0, 'database_writes': 0}))
    return 0 if proof is not None else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}))
        raise SystemExit(2)
