"""Sanitized operational failures; no provider body, secret, or hidden reasoning."""
from datetime import datetime, timezone
import re


def safe_message(value, limit=400):
    text=str(value)
    text=re.sub(r'https?://\S+', '[provider URL redacted]', text)
    text=re.sub(r'(?i)(bearer\s+|api[_ -]?key[=: ]+|password[=: ]+|token[=: ]+)\S+', r'\1[redacted]',text)
    text=re.sub(r'AIza[\w-]+|\bsk-[\w-]+', '[redacted]', text)
    text=re.sub(r'postgres(?:ql)?://\S+', '[database URL redacted]', text)
    return text[:limit]


def failure_detail(error, stage, attempt_count=None, attempted_network=None):
    saved=getattr(error,'analysis_failure',None)
    if saved:
        return {**saved,'stage':stage}
    code=getattr(error,'code',None)
    try: code=int(code) if code is not None else None
    except (ValueError,TypeError): code=None
    name=type(error).__name__;lower=str(error).lower()
    category=getattr(error,'error_category',None)
    if not category:
        if code==429: category='provider_quota_or_rate_limit'
        elif code in {401,403}:category='provider_access_denied'
        elif code in {400,404}:category='provider_configuration'
        elif code and code>=500:category='provider_http_error'
        elif name in {'QuotaBudgetExhausted','ProviderCircuitOpen'}:
            category='provider_circuit_open' if 'stopped' in lower or 'circuit' in lower else 'authorized_budget_exhausted'
        elif isinstance(error,(ModuleNotFoundError,ImportError)):category='missing_dependency'
        elif isinstance(error,FileNotFoundError):category='missing_evidence_or_weights'
        elif 'timeout' in name.lower():category='timeout'
        elif name in {'ValidationError','JSONDecodeError'}:category='response_schema_invalid'
        elif 'operationalerror' in name.lower() or 'database' in name.lower():category='database_error'
        elif 'vision is incomplete' in lower:category='required_perception_unavailable'
        else:category='worker_exception'
    attempted_network=bool(code) if attempted_network is None else bool(attempted_network)
    return {'stage':stage,'error_category':category,'timestamp':datetime.now(timezone.utc).isoformat(),
        'attempt_count':int(attempt_count or 0),'retryable':category in {'provider_http_error','timeout','database_error'},
        'provider_status':('http_'+str(code)) if code else ('response_received' if category=='response_schema_invalid' else 'not_attempted' if not attempted_network else 'no_response'),
        'http_status':code,'attempted_network':attempted_network,'exception_type':name,'message':safe_message(error)}
