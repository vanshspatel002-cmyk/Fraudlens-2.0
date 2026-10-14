"""Optional hard session cap, counted immediately before every network attempt.

The ledger contains no credentials. Set one absolute ledger path in every local
process. A stopped session stays stopped across restarts and quota-day resets.
"""
import json
import os
from pathlib import Path
import time
import threading
from .quota_budget import QuotaBudgetExhausted

_request = threading.local()


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
            state = json.loads(path.read_text()) if path.exists() else {'attempts': 0, 'consecutive_failures': 0, 'stopped': None, 'events': []}
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
    if state['stopped'] or state['attempts'] >= limit:
        raise QuotaBudgetExhausted('Live session stopped or request cap reached; use cached evidence and offline verification.')


def check():
    """Avoid consuming research quota reservations when this session is stopped."""
    _change(_allow)


def reserve(model):
    def update(state):
        _allow(state)
        state['attempts'] += 1
        state['events'].append({'attempt': state['attempts'], 'model': model, 'time': time.time(), 'outcome': 'reserved'})
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
        state['consecutive_failures'] = state['consecutive_failures'] + 1 if error else 0
        if code == 429:
            state['stopped'] = 'provider quota exhausted'
        elif error and (code in (400, 401, 403, 404) or state['consecutive_failures'] >= 2):
            state['stopped'] = 'configuration failure or repeated provider failures'
    _change(update)
