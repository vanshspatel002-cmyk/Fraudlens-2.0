"""Save received responses before parsing/cache/database work, without prompts."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


class ReceiptPersistenceError(RuntimeError):
    error_category = 'diagnostic_artifact_persistence'


def received(provider, response, operation, schema_version=None, request_contract=None):
    if not os.environ.get('FRAUDLENS_VALIDATION_ID'):
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
        session_budget.save_receipt(attempt, receipt)
        directory = Path(os.environ['FRAUDLENS_RESPONSE_DIR']).resolve()
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
        raise ReceiptPersistenceError('Received response could not be checkpointed; do not generate again.') from None
