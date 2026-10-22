"""Save received responses before parsing/cache/database work, without prompts."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


class ReceiptPersistenceError(RuntimeError):
    error_category = 'diagnostic_artifact_persistence'


def reconcile(provider, operation, contract):
    """Reuse the exact received reply on a restarted run; never repeat inference.

    No cross-run reuse is represented as fresh inference. A receipt without its
    full response is an explicit local blocker, not permission to regenerate.
    """
    from .operating_policy import enabled, scope
    if not enabled():return None
    if getattr(provider,'_receipt_failure',False):
        raise ReceiptPersistenceError('Resolve the local receipt failure before any further generation.')
    context=scope()
    if not context:return None
    from .session_budget import _change
    state=_change(lambda s:s)
    for event in reversed(state['events']):
        receipt=event.get('receipt') or {}
        saved_contract=event.get('request_contract') or {}
        if (operation=='agent' and event.get('run_id')==context['run_id']
                and receipt.get('operation')=='agent' and event['outcome'] in {'success','failure:ReceiptPersistenceError'}
                and saved_contract.get('agent_turn') in {None,contract.get('agent_turn')}
                and saved_contract!=contract):
            raise ReceiptPersistenceError('An earlier received agent turn uses different inputs; reconcile saved findings and reply before generating.')
        if (event.get('run_id')!=context['run_id'] or receipt.get('operation',operation)!=operation
                or event.get('request_contract')!=contract):continue
        if event['outcome'] not in {'success','failure:ReceiptPersistenceError'}:continue
        directory=Path(os.environ.get('FRAUDLENS_RESPONSE_DIR') or
                       str(Path(os.environ['FRAUDLENS_LIVE_LEDGER']).parent/'responses'))
        path=directory/f"attempt-{event['attempt']:06d}.json"
        try:
            payload=json.loads(path.read_text(encoding='utf8'))
            if payload['request_contract']!=contract:raise ValueError()
            from google.genai import types
            response=types.GenerateContentResponse.model_validate(payload['response'])
        except Exception:
            raise ReceiptPersistenceError('A received reply needs local reconciliation; no replacement generation permitted.') from None
        provider._last_attempt=event['attempt']
        provider._reconciled=True
        return response
    return None


def received(provider, response, operation, schema_version=None, request_contract=None):
    from .operating_policy import enabled
    if not os.environ.get('FRAUDLENS_VALIDATION_ID') and not enabled():
        return
    from . import session_budget, validation_budget
    from .analysis_diagnostics import response_metadata
    attempt = provider._last_attempt
    usage = getattr(response, 'usage_metadata', None)
    counts = {name: getattr(usage, name) for name in ('prompt_token_count', 'candidates_token_count',
        'total_token_count', 'thoughts_token_count', 'cached_content_token_count')
        if type(getattr(usage, name, None)) is int}
    receipt = {'session_attempt': attempt, 'source': 'fresh_provider', 'operation': operation,
        'requested_model': provider.model, 'serving_model': getattr(response, 'model_version', None),
        'timestamp': datetime.now(timezone.utc).isoformat(), 'started_at': provider._request_started_at,
        'latency_ms': int((time.monotonic()-provider._request_started_mono)*1000),
        'http_status': provider.http_statuses[-1] if provider.http_statuses else None,
        'http_attempts': 1, 'schema_version': schema_version, 'token_usage': counts,
        **response_metadata(response), **validation_budget.scope()}
    try:
        session_budget.save_receipt(attempt, receipt, request_contract=request_contract)
        directory = Path(os.environ.get('FRAUDLENS_RESPONSE_DIR') or
                         str(Path(os.environ['FRAUDLENS_LIVE_LEDGER']).parent/'responses')).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        payload = response.model_dump(mode='json', exclude_none=True)
        for candidate in payload.get('candidates', []):
            content = candidate.get('content') or {}
            content['parts'] = [part for part in content.get('parts', []) if not part.get('thought')]
        destination = directory/f'attempt-{attempt:06d}.json'
        if destination.exists():
            raise ReceiptPersistenceError('A received-response checkpoint already exists; reconcile it.')
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps({'receipt': receipt, 'request_contract': request_contract,
            'response': payload}, indent=2), encoding='utf8')
        temporary.replace(destination)
    except Exception as exc:
        provider._receipt_failure=True
        raise ReceiptPersistenceError('Received response could not be checkpointed; do not generate again.') from None
