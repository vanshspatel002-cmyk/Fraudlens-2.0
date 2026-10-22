"""Normal worker controls stored atomically in the ORIGINAL session ledger.

Diagnostic grants remain historical. This policy has no inference entrypoint.
All checks/reservations run inside session_budget's cross-process file lock.
"""
import os
import time
from datetime import datetime, timezone
from .quota_budget import QuotaBudgetExhausted, QuotaControlInvalid, pacific_quota_day

VERSION = 'local-operation-2026-10-22-v1'
DEFAULTS = dict(daily_attempts=30, case_attempts=16, agent_turns=8,
                concurrent_cases=1, retry_attempts=2, pacing_seconds=2,
                cooldown_seconds=1800)


def enabled(state=None):
    if state is not None:
        return bool(state.get('operation'))
    from .session_budget import _change
    return bool(_change(lambda s: bool(s.get('operation')))) if os.getenv('FRAUDLENS_LIVE_LEDGER') else False


def validate(state):
    op = state.get('operation')
    if op is None:
        return
    if (not isinstance(op, dict) or op.get('version') != VERSION
            or op.get('mode') not in {'normal', 'paused'} or not isinstance(op.get('schema'), str)
            or not isinstance(op.get('audit'), list)
            or set(op.get('limits', {})) != set(DEFAULTS)
            or any(type(v) is not int or v < 1 for v in op['limits'].values())
            or op['limits']['concurrent_cases'] != 1):
        raise QuotaControlInvalid('Operating controls invalid; restore and inspect their history.')
    task = op.get('task')
    if task and (type(task.get('base_attempts')) is not int or type(task.get('ceiling')) is not int
                 or task['ceiling'] != task['base_attempts'] + 30
                 or task.get('status') not in {'active', 'closed'}):
        raise QuotaControlInvalid('Task request accounting invalid.')


def migrate(*, schema, expected_attempts, operator, reason):
    """One explicit audited migration; does not erase stops/events/recoveries."""
    from .session_budget import _change
    def change(state):
        if state.get('operation') or state['attempts'] != expected_attempts:
            raise ValueError('Inspect existing operating policy / changed attempt count first.')
        if not operator or not reason or schema != 'fraudlens_pilot':
            raise ValueError('Explicit operator, reason and pilot schema required.')
        if any(e['outcome'] == 'reserved' for e in state['events']):
            raise ValueError('An existing provider request is still in flight.')
        if any(g['status'] == 'active' for g in state.get('validation_grants', [])):
            raise ValueError('Close the earlier validation grant first.')
        # Require the recorded corrected full workflow, not an arbitrary reset.
        verified = [e for e in state['events'] if e.get('validation_id') and e['outcome'] == 'success']
        if len(verified) < 2 or not any((e.get('receipt') or {}).get('operation') == 'agent' for e in verified):
            raise ValueError('A successful recorded corrected workflow is required for migration.')
        now = time.time()
        state['operation'] = dict(version=VERSION, schema=schema, mode='normal',
            limits=dict(DEFAULTS), circuit=None, migrated_at=now,
            historical_stop=state['stopped'],
            task=dict(base_attempts=expected_attempts, ceiling=expected_attempts+30, status='active'),
            audit=[dict(action='migrate', time=now, operator=operator, reason=reason,
                        original_attempts=expected_attempts, previous_lifetime_cap=15,
                        previous_stop=state['stopped'])])
        # state.stopped is retained verbatim as the historical diagnostic stop.
    _change(change)


def scope():
    from .validation_budget import scope as current
    return current()


def allow(state):
    from .session_budget import ProviderCircuitOpen
    op = state['operation']; context = scope(); now = time.time()
    if os.getenv('FRAUDLENS_VALIDATION_ID') or os.getenv('FRAUDLENS_RECOVERY_ID'):
        raise ProviderCircuitOpen('Normal operation cannot use a diagnostic grant.')
    if op['mode'] != 'normal':
        raise ProviderCircuitOpen('Normal generation manually paused; no request attempted.')
    if os.getenv('FRAUDLENS_LIVE_LIMIT') == '0':
        raise ProviderCircuitOpen('Legacy zero kill-switch is set; no request attempted.')
    if (not context or context.get('schema') != op['schema']
            or context.get('schema') != os.getenv('FRAUDLENS_PG_SCHEMA')
            or not context.get('case_id') or not context.get('run_id')):
        raise ProviderCircuitOpen('Normal generation requires the actual pilot worker job context.')
    if context.get('retrospective') and context['run_id'] not in op.get('batch_runs', []):
        raise ProviderCircuitOpen('Historical batch run has not been explicitly activated.')
    task = op.get('task') or {}
    if task.get('status') == 'active' and state['attempts'] >= task['ceiling']:
        raise QuotaBudgetExhausted('Task-wide request ceiling reached; no request attempted.')
    # All consumers, including pre-migration calls today, count toward the day.
    day = pacific_quota_day()
    today = sum(pacific_quota_day(datetime.fromtimestamp(e['time'], timezone.utc)) == day
                for e in state['events'])
    case_calls = sum(e.get('operation_case') == context['case_id'] for e in state['events'])
    if today >= op['limits']['daily_attempts'] or case_calls >= op['limits']['case_attempts']:
        raise QuotaBudgetExhausted('Normal daily or per-case attempt limit reached; no request attempted.')
    if any(e['outcome'] == 'reserved' for e in state['events']):
        raise ProviderCircuitOpen('Another provider request is in flight; no concurrent probe allowed.')
    circuit = op.get('circuit')
    if circuit:
        if circuit['category'] != 'transient' or now < circuit['retry_at']:
            raise ProviderCircuitOpen('Provider stopped: '+circuit['category']+'; no request attempted.')
    return op


def reserve(state, event):
    op = state['operation']; context = scope()
    event.update(operation_version=VERSION, operation_case=context['case_id'],
                 case_id=context['case_id'], run_id=context['run_id'], schema=context['schema'])
    if op.get('circuit'):
        event['half_open'] = True
        op['audit'].append(dict(action='half_open', time=event['time'], attempt=event['attempt']))


def outcome(state, event, error):
    if not event.get('operation_version'):
        return
    from .session_budget import TRANSIENT_OUTCOMES
    from .analysis_diagnostics import failure_detail
    op = state['operation']; now = time.time()
    if error is None:
        if event.get('half_open'):
            op['audit'].append(dict(action='circuit_recovered', time=now, attempt=event['attempt']))
            op['circuit'] = None
        return
    event['diagnostic'] = failure_detail(error, 'provider_request', attempt_count=1,
                                         attempted_network=True, model=event['model'])
    code = getattr(error, 'code', None)
    transient = event['outcome'] in TRANSIENT_OUTCOMES
    previous = [e for e in state['events'][:-1] if e.get('operation_version')]
    consecutive = bool(previous and previous[-1]['outcome'] in TRANSIENT_OUTCOMES)
    category = ('authentication_access' if event['diagnostic']['error_category']=='provider_access_denied'
                else 'quota' if code == 429 else 'authentication_access' if code in (401,403)
                else 'invalid_request_model' if code in (400,404) else 'transient' if transient
                else 'response_validation' if getattr(error, 'error_category', '') == 'response_schema_invalid'
                else 'local_or_validation_failure')
    if not transient and code is None:
        # Parsing/storage failures do not establish a provider outage. The job
        # records the local failure and exact received reply; no automatic retry.
        # A replayable saved valid response may reconcile the same run later.
        return
    # One retry of a first transient is allowed; a failed half-open stops again.
    if not transient or consecutive or event.get('half_open'):
        op['circuit'] = dict(category=category, stopped_at=now,
                             retry_at=now+op['limits']['cooldown_seconds'], attempt=event['attempt'])
        op['audit'].append(dict(action='circuit_stopped', time=now, category=category, attempt=event['attempt']))


def control(action, *, operator, reason):
    from .session_budget import _change
    if action not in {'pause','resume','finish-task'} or not operator or not reason:
        raise ValueError('Explicit action/operator/reason required.')
    def change(state):
        op = state.get('operation')
        if not op:
            raise ValueError('Normal operation has not been migrated.')
        if action == 'finish-task':
            op['task'].update(status='closed', finished_at=time.time(), final_attempts=state['attempts'])
        else:
            op['mode'] = 'paused' if action == 'pause' else 'normal'
        op['audit'].append(dict(action=action, time=time.time(), operator=operator, reason=reason))
    _change(change)


def configure(changes, *, operator, reason):
    """Intentional, append-audited setting revision; never edits old events."""
    from .session_budget import _change
    if not operator or not reason or not changes or set(changes)-set(DEFAULTS):
        raise ValueError('Explicit supported setting change, operator and reason required.')
    if any(type(v) is not int or v < 1 for v in changes.values()) or changes.get('concurrent_cases',1)!=1:
        raise ValueError('Positive limits and one processing case required.')
    def change(state):
        op=state['operation']
        if (op.get('task') or {}).get('status')=='active' and any(changes[k]>DEFAULTS[k] for k in changes if k in {'daily_attempts','case_attempts','agent_turns'}):
            raise ValueError('Current task conservative ceilings cannot be increased.')
        previous=dict(op['limits']);op['limits'].update(changes)
        op['audit'].append(dict(action='configure',time=time.time(),operator=operator,reason=reason,
                                previous_limits=previous,limits=dict(op['limits'])))
    _change(change)


def limits():
    from .session_budget import _change
    if not os.getenv('FRAUDLENS_LIVE_LEDGER'):
        return dict(DEFAULTS)
    return _change(lambda s: dict((s.get('operation') or {}).get('limits', DEFAULTS)))


def pace():
    from .session_budget import _change
    delay = _change(lambda s: max(0, (s['events'][-1].get('completed_at', s['events'][-1]['time'])
        if s['events'] else 0) + (s.get('operation') or {}).get('limits', DEFAULTS)['pacing_seconds']-time.time()))
    if delay:
        time.sleep(min(delay, 60))
