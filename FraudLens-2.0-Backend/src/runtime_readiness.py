"""Content-free local capability status; never an inference or quota probe."""
import json
import os
from pathlib import Path
import time


def worker_path():
    return Path(os.environ.get('FRAUDLENS_UPLOAD_DIR','outputs/pilot_validation/uploads')).parent/'worker-status.json'


def worker_status():
    try:
        value=json.loads(worker_path().read_text())
        if time.time()-value['heartbeat_at']>15:
            return {'state':'unavailable','reason':'worker_heartbeat_stale'}
        return {key:value[key] for key in ('state','ocr_ready','leader','heartbeat_at') if key in value}
    except (OSError,ValueError,KeyError,TypeError):
        return {'state':'unavailable','reason':'worker_heartbeat_missing'}


def provider_status(configured=None):
    """Read recorded controls only. Never reserve, rewrite, probe or import SDKs."""
    if configured is None:
        configured=any(os.getenv(name) for name in ('GEMINI_API_KEY','GEMINI_API_KEY_1','GOOGLE_API_KEY'))
    if not configured:return {'state':'not_configured','ready':False}
    try:
        from .session_budget import _validate_state
        path=os.environ.get('FRAUDLENS_LIVE_LEDGER')
        if not path:raise ValueError()
        state=json.loads(Path(path).read_text());_validate_state(state)
        operation=state.get('operation') or {}
        circuit=operation.get('circuit') or {}
        if operation.get('mode')=='paused':status='paused'
        elif circuit:status='circuit_open' if time.time()<circuit.get('retry_at',float('inf')) else 'recovery_pending'
        elif operation.get('mode')!='normal':status='diagnostic_only'
        else:status='locally_enabled_unverified'
        return dict(state=status,ready=status=='locally_enabled_unverified',
            circuit_category=circuit.get('category'),recorded_stop_at=circuit.get('stopped_at'),
            retry_at=circuit.get('retry_at'),basis='Persisted local controls only; no Google inference or account-quota check.')
    except Exception:
        return {'state':'controls_unavailable','ready':False,'basis':'Provider controls could not be read safely; no request attempted.'}


def write_worker_status(*,state,ocr_ready,leader):
    path=worker_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.'+str(os.getpid())+'.tmp')
    temporary.write_text(json.dumps(dict(state=state,ocr_ready=ocr_ready,leader=leader,
        heartbeat_at=time.time(),pid=os.getpid())))
    temporary.replace(path)
