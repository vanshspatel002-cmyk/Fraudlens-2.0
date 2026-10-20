"""Optional hard session cap, counted immediately before every network attempt.

The ledger contains no credentials. Set one absolute ledger path in every local
process. A stopped session stays stopped across restarts and quota-day resets.
"""
import json
import os
from pathlib import Path
import time
import threading
import secrets
from .quota_budget import QuotaBudgetExhausted

_request = threading.local()


class ProviderCircuitOpen(QuotaBudgetExhausted):
    error_category = 'provider_circuit_open'


def _recovery(state):
    recovery_id = os.environ.get('FRAUDLENS_RECOVERY_ID')
    return next((r for r in state.get('recoveries',[]) if r['recovery_id']==recovery_id),None)


def _validate_state(state):
    integer = lambda value: type(value) is int and value >= 0
    valid = (isinstance(state, dict) and integer(state.get('attempts'))
        and integer(state.get('consecutive_failures'))
        and state['consecutive_failures'] <= state['attempts']
        and (state.get('stopped') is None or isinstance(state.get('stopped'), str))
        and 'stopped' in state and isinstance(state.get('events'), list))
    if valid:
        events = state['events']
        valid = len(events) == state['attempts'] and all(
            isinstance(event, dict) and type(event.get('attempt')) is int and event['attempt'] == index
            and isinstance(event.get('outcome'), str)
            and (event['outcome'] in {'reserved', 'success'} or event['outcome'].startswith('failure:'))
            for index, event in enumerate(events, 1))
    recoveries = state.get('recoveries', []) if isinstance(state, dict) else []
    valid = valid and isinstance(recoveries, list)
    if valid:
        seen = set()
        for recovery in recoveries:
            if not (isinstance(recovery, dict) and isinstance(recovery.get('recovery_id'), str)
                    and recovery['recovery_id'] and recovery['recovery_id'] not in seen
                    and isinstance(recovery.get('status'), str)
                    and recovery.get('status') in {'authorized','probing','probe_succeeded','validation_authorized','failed'}
                    and integer(recovery.get('allowance')) and integer(recovery.get('reserved'))
                    and recovery['reserved'] <= recovery['allowance']
                    and integer(recovery.get('base_attempts')) and recovery['base_attempts'] <= state['attempts']
                    and recovery['reserved'] == sum(event.get('recovery_id') == recovery['recovery_id'] for event in state['events'])):
                valid = False
                break
            seen.add(recovery['recovery_id'])
        valid = valid and all(not event.get('recovery_id') or isinstance(event['recovery_id'], str) and event['recovery_id'] in seen for event in state['events'])
    if not valid:
        raise QuotaBudgetExhausted('The existing session ledger is invalid; restore its audit history before any provider request.')


def _change(callback):
    filename = os.environ.get('FRAUDLENS_LIVE_LEDGER')
    if not filename:
        return
    path = Path(filename).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a+b') as lock:
        lock.seek(0,2)
        if lock.tell() == 0:lock.write(b'0');lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(path.read_text()) if path.exists() else {'attempts': 0, 'consecutive_failures': 0, 'stopped': None, 'events': []}
            except (OSError, json.JSONDecodeError) as exc:
                raise QuotaBudgetExhausted('The existing session ledger is unreadable; restore its audit history before any provider request.') from exc
            _validate_state(state)
            result = callback(state)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            tmp.replace(path)
            return result
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _allow(state):
    limit = min(15, max(0, int(os.environ.get('FRAUDLENS_LIVE_LIMIT', '15'))))
    if state['attempts'] >= limit:
        raise QuotaBudgetExhausted('Authorized live request cap reached; no network request attempted.')
    if state['stopped']:
        recovery=_recovery(state)
        if not recovery or recovery['status'] not in {'authorized','probing','validation_authorized'}:
            raise ProviderCircuitOpen('Application provider circuit is stopped; no network request attempted.')
        if recovery['reserved'] >= recovery['allowance']:
            raise QuotaBudgetExhausted('Audited recovery allowance reached; no network request attempted.')


def authorize_recovery(reason):
    """One explicit probe of a transient circuit, preserving the original stop.

    Quota/access/configuration stops and already attempted probes are ineligible.
    Merely authorizing does not reserve either budget or contact the provider.
    """
    if not os.environ.get('FRAUDLENS_LIVE_LEDGER'):
        raise ValueError('The original live ledger is required for recovery.')
    def update(state):
        _limit=min(15,max(0,int(os.environ.get('FRAUDLENS_LIVE_LIMIT','15'))))
        failures=[e for e in state.get('events',[]) if e.get('outcome','').startswith('failure:')]
        restricted=any(word in str(state.get('stopped','')).lower() for word in ('quota','billing','access denied','manual stop','request cap','capacity exhausted'))
        if restricted or not state.get('stopped') or not failures or any(e['outcome'] not in {'failure:500','failure:502','failure:503','failure:504'} for e in failures[-2:]):
            raise ValueError('Only a recorded transient HTTP-error circuit can receive a recovery probe.')
        if state.get('recoveries'):
            raise ValueError('A recovery has already been authorized; inspect its retained outcome instead of probing again.')
        if state['attempts'] >= _limit:
            raise QuotaBudgetExhausted('No authorized request budget remains for a recovery probe.')
        if not str(reason).strip():raise ValueError('An audited recovery reason is required.')
        recovery={'recovery_id':secrets.token_hex(12),'requested_at':time.time(),
            'reason':str(reason)[:300],'original_stop':state['stopped'],
            'base_attempts':state['attempts'],'allowance':1,'reserved':0,'status':'authorized'}
        state.setdefault('recoveries',[]).append(recovery)
        return recovery['recovery_id']
    return _change(update)


def authorize_validation(recovery_id, maximum_additional_calls, reason):
    """Explicit bounded follow-up after a successful probe, under the same cap."""
    def update(state):
        recovery=next((r for r in state.get('recoveries',[]) if r['recovery_id']==recovery_id),None)
        if not recovery or recovery['status']!='probe_succeeded':
            raise ValueError('Bounded validation requires the successful initial recovery probe.')
        remaining=min(15,int(os.environ.get('FRAUDLENS_LIVE_LIMIT','15')))-state['attempts']
        count=int(maximum_additional_calls)
        if not 1<=count<=remaining:raise ValueError('Validation allowance must fit the remaining original request cap.')
        recovery.update(status='validation_authorized',allowance=recovery['reserved']+count,
            validation_authorized_at=time.time(),validation_reason=str(reason)[:300])
    _change(update)


def check():
    """Avoid consuming research quota reservations when this session is stopped."""
    _change(_allow)


def reserve(model):
    def update(state):
        _allow(state)
        state['attempts'] += 1
        event={'attempt': state['attempts'], 'model': model, 'time': time.time(), 'outcome': 'reserved'}
        recovery=_recovery(state)
        if recovery:
            recovery['reserved']+=1
            if recovery['status']=='authorized':recovery['status']='probing'
            event['recovery_id']=recovery['recovery_id']
        state['events'].append(event)
        return state['attempts']
    attempt = _change(update)
    _request.attempt = attempt
    return attempt


def outcome(error=None, *, attempt=None):
    attempt = attempt if attempt is not None else getattr(_request, 'attempt', None)
    def update(state):
        event = next((e for e in state['events'] if e['attempt'] == attempt), None)
        if event is None:
            raise RuntimeError('Provider outcome has no matching reserved request')
        if event['outcome'] != 'reserved':
            raise RuntimeError('Provider request outcome already recorded')
        code = getattr(error, 'code', None)
        event['outcome'] = 'success' if error is None else f'failure:{code or type(error).__name__}'
        event['completed_at']=time.time()
        recovery=next((r for r in state.get('recoveries',[]) if r['recovery_id']==event.get('recovery_id')),None)
        if recovery:
            if error:
                recovery.update(status='failed',failure_outcome=event['outcome'],finished_at=time.time())
            elif recovery['status']=='probing':
                recovery.update(status='probe_succeeded',probe_succeeded_at=time.time())
        state['consecutive_failures'] = state['consecutive_failures'] + 1 if error else 0
        if code == 429:
            state['stopped'] = 'provider quota exhausted'
        elif error and (code in (400, 401, 403, 404) or state['consecutive_failures'] >= 2):
            state['stopped'] = 'configuration failure or repeated provider failures'
    _change(update)
