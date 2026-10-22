"""Expiring, run-scoped development allowance; ordinary generation stays stopped."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import secrets
import time

from .quota_budget import QuotaBudgetExhausted, QuotaControlInvalid

POLICY = 'isolated-two-case-validation-budget-2026-10-22-v1'
MAX_NEW = 30
CUMULATIVE_CAP = 37
_scope = ContextVar('provider_validation_scope', default=None)


@contextmanager
def execution(schema, job):
    token = _scope.set({'schema': schema, 'run_id': job['job_id'], 'case_id': job['case_id'],
                       **({'retrospective':True, 'batch_id':job.get('batch_id')} if job.get('retrospective') else {})})
    try:
        yield
    finally:
        _scope.reset(token)


def validate_state(state):
    grants = state.get('validation_grants', [])
    if not isinstance(grants, list):
        raise QuotaControlInvalid('Validation audit is invalid.')
    seen = set()
    for grant in grants:
        valid = (isinstance(grant, dict) and isinstance(grant.get('grant_id'), str)
            and grant['grant_id'] not in seen and grant.get('policy') == POLICY
            and grant.get('status') in {'active', 'stopped', 'closed'}
            and grant.get('base_attempts') == 7 and grant.get('ceiling') == CUMULATIVE_CAP
            and type(grant.get('allowance')) is int and 0 < grant['allowance'] <= MAX_NEW
            and type(grant.get('reserved')) is int and 0 <= grant['reserved'] <= grant['allowance']
            and isinstance(grant.get('jobs'), dict)
            and isinstance(grant.get('expires_at'), (float, int))
            and grant['created_at'] < grant['expires_at'] <= grant['created_at'] + 86400
            and grant['reserved'] == sum(e.get('validation_id') == grant['grant_id'] for e in state['events']))
        if not valid:
            raise QuotaControlInvalid('Validation audit is invalid; retain and inspect controls.')
        seen.add(grant['grant_id'])
    if any(e.get('validation_id') and e['validation_id'] not in seen for e in state['events']):
        raise QuotaControlInvalid('A request references an unknown validation grant.')


def authorize(schema, *, operator, reason, expires_at, expected_attempts=7):
    """Explicit task authorization; no provider request or job insertion."""
    from . import session_budget
    if not re.fullmatch(r'fraudlens_validation_[a-z0-9_]+', schema):
        raise ValueError('Use a new isolated validation schema.')
    now = time.time()
    if not isinstance(expires_at, (int, float)) or not now < expires_at <= now + 86400:
        raise ValueError('Validation expiry must fit the authorized 24-hour window.')
    if not operator or not reason:
        raise ValueError('Explicit operator and authorization reason are required.')
    def update(state):
        if state['attempts'] != expected_attempts or expected_attempts != 7:
            raise ValueError('The original seven attempts must precede this task grant.')
        if state.get('validation_grants') or any(e['outcome'] == 'reserved' for e in state['events']):
            raise ValueError('A validation grant already exists or a request is in flight.')
        prior = state.get('recoveries', [])[-1] if state.get('recoveries') else {}
        if (state['events'][-1]['outcome'] != 'success' or prior.get('status') != 'probe_succeeded'
                or prior.get('kind') != 'request_schema_correction' or not state.get('stopped')):
            raise ValueError('Retained successful corrected perception qualification is required.')
        grant = {'grant_id': secrets.token_hex(16), 'policy': POLICY, 'schema': schema,
            'operator': str(operator)[:100], 'reason': str(reason)[:400], 'created_at': now,
            'expires_at': expires_at, 'base_attempts': 7, 'ceiling': CUMULATIVE_CAP,
            'allowance': MAX_NEW, 'reserved': 0, 'status': 'active', 'jobs': {},
            'qualifying_attempt': 7, 'transient_failures': 0, 'original_stop': state['stopped']}
        state.setdefault('validation_grants', []).append(grant)
        state.setdefault('budget_revisions', []).append({'policy': POLICY, 'grant_id': grant['grant_id'],
            'time': now, 'operator': str(operator)[:100], 'reason': str(reason)[:400],
            'old_ceiling': 15, 'new_ceiling': CUMULATIVE_CAP, 'historical_attempts': 7,
            'expires_at': expires_at, 'schema': schema})
        return grant['grant_id']
    return session_budget._change(update)


def bind_job(grant_id, schema, job, kind):
    """Operator binds the actual API-accepted durable job before worker execution."""
    from . import session_budget
    if kind not in {'claims', 'underwriting'} or job.get('status') != 'queued':
        raise ValueError('Bind only an actual queued claims/underwriting job.')
    def update(state):
        grant = next((g for g in state.get('validation_grants', []) if g['grant_id'] == grant_id), None)
        if not grant or grant['schema'] != schema or grant['status'] != 'active' or time.time() >= grant['expires_at']:
            raise ValueError('The matching validation grant is unavailable or expired.')
        if any(v['kind'] == kind for v in grant['jobs'].values()):
            raise ValueError('Only one case/run of each type is authorized.')
        grant['jobs'][job['job_id']] = {'case_id': job['case_id'], 'kind': kind, 'bound_at': time.time()}
    session_budget._change(update)


def allow(state):
    """Called under the ORIGINAL session file lock, before daily reservation."""
    grant_id = os.environ.get('FRAUDLENS_VALIDATION_ID')
    if not grant_id:
        return None
    from .session_budget import ProviderCircuitOpen
    grant = next((g for g in state.get('validation_grants', []) if g['grant_id'] == grant_id), None)
    scope = _scope.get()
    if (not grant or grant['status'] != 'active' or time.time() >= grant['expires_at']
            or os.environ.get('FRAUDLENS_RECOVERY_ID')
            or not scope or scope['schema'] != grant['schema']
            or os.environ.get('FRAUDLENS_PG_SCHEMA') != grant['schema']
            or grant['jobs'].get(scope['run_id'], {}).get('case_id') != scope['case_id']):
        raise ProviderCircuitOpen('Validation grant is closed, expired or outside this actual worker run.')
    if state['attempts'] >= grant['ceiling'] or grant['reserved'] >= grant['allowance']:
        raise QuotaBudgetExhausted('Task validation generation limit reached; no request attempted.')
    configured = int(os.environ.get('FRAUDLENS_LIVE_LIMIT', '15'))
    if configured < 15 and state['attempts'] >= max(0, configured):
        raise QuotaBudgetExhausted('An explicit lower process limit prevents this request.')
    if any(e['outcome'] == 'reserved' for e in state['events']):
        raise ProviderCircuitOpen('Another controlled provider request is in flight.')
    return grant


def reserve(grant, event):
    grant['reserved'] += 1
    event.update(validation_id=grant['grant_id'], **_scope.get())


def outcome(state, event, error):
    grant = next((g for g in state.get('validation_grants', []) if g['grant_id'] == event.get('validation_id')), None)
    if not grant:
        return
    from .session_budget import TRANSIENT_OUTCOMES
    transient = event['outcome'] in TRANSIENT_OUTCOMES
    grant['transient_failures'] = grant['transient_failures'] + 1 if transient else 0
    if error and (getattr(error, 'code', None) in {400, 401, 403, 404, 429}
            or grant['transient_failures'] >= 2):
        grant.update(status='stopped', stopped_at=time.time(), stop_outcome=event['outcome'])


def close(grant_id, reason):
    from . import session_budget
    def update(state):
        grant = next((g for g in state.get('validation_grants', []) if g['grant_id'] == grant_id), None)
        if not grant:
            raise ValueError('Validation grant was not found.')
        if any(e['outcome'] == 'reserved' for e in state['events']):
            raise ValueError('Reconcile the in-flight request before closing.')
        if grant['status'] != 'closed':
            grant.update(status='closed', closed_at=time.time(), close_reason=str(reason)[:300],
                unused_allowance=grant['allowance']-grant['reserved'])
    session_budget._change(update)


def scope():
    return _scope.get()
