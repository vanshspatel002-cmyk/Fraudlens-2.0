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
import math
from .quota_budget import QuotaBudgetExhausted, QuotaControlInvalid

_request = threading.local()
RECOVERY_POLICY_VERSION = 'operator-transient-recovery-2026-10-21-v2'
RECOVERY_COOLDOWN_SECONDS = 30 * 60
TRANSIENT_OUTCOMES = {'failure:'+value for value in (
    '500','502','503','504','TimeoutError','ReadTimeout','WriteTimeout','ConnectTimeout',
    'PoolTimeout','ConnectError','ReadError','WriteError','RemoteProtocolError','NetworkError')}


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
        raise QuotaControlInvalid('The existing session ledger is invalid; restore its audit history before any provider request.')


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
                raise QuotaControlInvalid('The existing session ledger is unreadable; restore its audit history before any provider request.') from exc
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
        if recovery is not state['recoveries'][-1]:
            raise ProviderCircuitOpen('An earlier recovery cannot spend the latest operator allowance.')
        if recovery['reserved'] >= recovery['allowance']:
            raise QuotaBudgetExhausted('Audited recovery allowance reached; no network request attempted.')


def recovery_eligibility(state, limit, *, operator=False, now=None):
    """Pure audit of existing policy; inspecting it never reopens a circuit."""
    failures=[e for e in state.get('events',[]) if e.get('outcome','').startswith('failure:') and e.get('kind')!='model_metadata']
    restricted=any(word in str(state.get('stopped','')).lower() for word in ('quota','billing','access denied','manual stop','request cap','capacity exhausted'))
    if restricted or not state.get('stopped') or not failures or any(e['outcome'] not in TRANSIENT_OUTCOMES for e in failures[-2:]):
        return {'eligible':False,'reason':'not_a_transient_http_circuit'}
    if state['attempts'] >= min(15,max(0,int(limit))):
        return {'eligible':False,'reason':'attempt_budget_exhausted'}
    if any(event['outcome']=='reserved' for event in state['events']):
        return {'eligible':False,'reason':'request_still_in_flight'}
    if state.get('recoveries'):
        if not operator:return {'eligible':False,'reason':'prior_recovery_already_recorded'}
        prior=state['recoveries'][-1]
        if prior['status']!='failed':return {'eligible':False,'reason':'recovery_already_active_or_awaiting_validation'}
        if prior.get('failure_outcome') not in TRANSIENT_OUTCOMES:
            return {'eligible':False,'reason':'previous_recovery_not_transient'}
        finished=prior.get('finished_at')
        if not isinstance(finished,(float,int)) or isinstance(finished,bool) or not math.isfinite(finished):
            return {'eligible':False,'reason':'recovery_completion_time_unverified'}
        remaining=math.ceil(finished+RECOVERY_COOLDOWN_SECONDS-(time.time() if now is None else now))
        if remaining>0:return {'eligible':False,'reason':'recovery_cooldown','retry_after_seconds':remaining}
        return {'eligible':True,'reason':'operator_half_open_probe_permitted','cooldown_seconds':RECOVERY_COOLDOWN_SECONDS}
    return {'eligible':True,'reason':'one_initial_half_open_probe_permitted'}


def authorize_recovery(reason, *, operator=None, expected_attempts=None):
    """One explicit probe of a transient circuit, preserving the original stop.

    A named operator may retry a FAILED TRANSIENT recovery after cooldown.
    Quota/access/configuration stops and in-flight requests remain ineligible.
    Merely authorizing does not reserve either budget or contact the provider.
    """
    if not os.environ.get('FRAUDLENS_LIVE_LEDGER'):
        raise ValueError('The original live ledger is required for recovery.')
    def update(state):
        _limit=min(15,max(0,int(os.environ.get('FRAUDLENS_LIVE_LIMIT','15'))))
        if expected_attempts is not None and state['attempts']!=expected_attempts:
            raise ValueError('The backed-up attempt count changed; inspect controls before authorizing.')
        eligibility=recovery_eligibility(state,_limit,operator=bool(operator))
        if eligibility['reason']=='not_a_transient_http_circuit':
            raise ValueError('Only a recorded transient HTTP-error circuit can receive a recovery probe.')
        if eligibility['reason']=='prior_recovery_already_recorded':
            raise ValueError('A recovery has already been authorized; inspect its retained outcome instead of probing again.')
        if eligibility['reason']=='attempt_budget_exhausted':
            raise QuotaBudgetExhausted('No authorized request budget remains for a recovery probe.')
        if not eligibility['eligible']:raise ValueError('Operator recovery blocked: '+eligibility['reason'])
        if operator is not None and (not isinstance(operator,str) or not operator.strip()):raise ValueError('An operator audit label is required.')
        if not str(reason).strip():raise ValueError('An audited recovery reason is required.')
        recovery={'recovery_id':secrets.token_hex(12),'requested_at':time.time(),
            'reason':str(reason)[:300],'original_stop':state['stopped'],
            'base_attempts':state['attempts'],'allowance':1,'reserved':0,'status':'authorized'}
        if operator:
            recovery.update(policy_version=RECOVERY_POLICY_VERSION,operator=operator[:100],
                previous_recovery_id=state['recoveries'][-1]['recovery_id'] if state.get('recoveries') else None,
                cooldown_seconds=RECOVERY_COOLDOWN_SECONDS)
        state.setdefault('recoveries',[]).append(recovery)
        return recovery['recovery_id']
    return _change(update)


def authorize_validation(recovery_id, maximum_additional_calls, reason):
    """Explicit bounded follow-up after a successful probe, under the same cap."""
    def update(state):
        recovery=next((r for r in state.get('recoveries',[]) if r['recovery_id']==recovery_id),None)
        if not recovery or recovery is not state['recoveries'][-1] or recovery['status']!='probe_succeeded':
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


def reject_recovery_result(recovery_id, category):
    """Retain HTTP success but close a probe whose saved observations are unusable."""
    if category!='response_schema_invalid':raise ValueError('Unsupported probe validation category.')
    def update(state):
        recovery=state['recoveries'][-1] if state.get('recoveries') else None
        if not recovery or recovery['recovery_id']!=recovery_id or recovery['status']!='probe_succeeded':
            raise ValueError('Only the just-completed current probe can fail observation validation.')
        recovery.update(status='failed',failure_outcome='failure:'+category,finished_at=time.time())
    _change(update)


def reserve_model_metadata(model,operator,reason):
    """Explicit one-shot READ scope under the same lifetime cap, never generation.

    Used only by GeminiProvider.model_metadata's fixed models.get call. It cannot
    reopen the generation circuit or extend a recovery's one-request allowance.
    """
    if not os.environ.get('FRAUDLENS_LIVE_LEDGER') or not isinstance(operator,str) or not operator.strip() or not isinstance(reason,str) or not reason.strip():
        raise ValueError('Original ledger and explicit operator/reason are required for metadata inspection.')
    if model!=os.environ.get('GEMINI_MODEL'):raise ValueError('Only configured-model metadata may be read.')
    def update(state):
        cap=min(15,max(0,int(os.environ.get('FRAUDLENS_LIVE_LIMIT','15'))))
        if state['attempts']>=cap:raise QuotaBudgetExhausted('Original attempt cap prevents metadata inspection.')
        if any(e['outcome']=='reserved' for e in state['events']):raise ProviderCircuitOpen('A provider operation is still in flight.')
        state['attempts']+=1
        state['events'].append({'attempt':state['attempts'],'model':model,'time':time.time(),'outcome':'reserved',
            'kind':'model_metadata','operator':str(operator)[:100],'reason':str(reason)[:300]})
        return state['attempts']
    return _change(update)


def model_metadata_outcome(attempt,error=None):
    """A metadata reply must not alter generation failure counters or stops."""
    def update(state):
        event=next((e for e in state['events'] if e['attempt']==attempt),None)
        if not event or event.get('kind')!='model_metadata' or event['outcome']!='reserved':
            raise ValueError('No matching in-flight metadata inspection.')
        event.update(outcome='success' if error is None else 'failure:'+str(getattr(error,'code',None) or type(error).__name__),completed_at=time.time())
    _change(update)


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
        previous_stop=state['stopped']
        if code == 429:
            state['stopped'] = 'provider quota exhausted'
        elif error and (code in (400, 401, 403, 404) or state['consecutive_failures'] >= 2):
            state['stopped'] = 'configuration failure or repeated provider failures'
        if state['stopped']!=previous_stop:
            state.setdefault('stop_history',[]).append({'time':time.time(),'previous_stop':previous_stop,
                'stop':state['stopped'],'cause_attempt':attempt})
    _change(update)
