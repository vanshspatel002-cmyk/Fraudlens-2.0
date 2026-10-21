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


def response_metadata(response):
    """Only provider identifiers/enums; never response text or feedback messages."""
    result = {}
    def enum(value):
        value = getattr(value, 'value', value)
        return value if isinstance(value, str) and re.fullmatch(r'[A-Z_]{2,64}', value) else None
    candidates = getattr(response, 'candidates', None) or []
    if candidates:
        result['finish_reason'] = enum(getattr(candidates[0], 'finish_reason', None))
    feedback = getattr(response, 'prompt_feedback', None)
    result['block_reason'] = enum(getattr(feedback, 'block_reason', None))
    request_id = getattr(response, 'response_id', None)
    if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id) and not request_id.startswith(('AIza', 'sk-')):
        result['provider_request_id'] = request_id
    return {key: value for key, value in result.items() if value is not None}


def failure_detail(error, stage, attempt_count=None, attempted_network=None, model=None):
    saved=getattr(error,'analysis_failure',None)
    if saved:
        return {**saved,'stage':stage, **({'model':model} if model else {})}
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
        elif name in {'ConnectError','ReadError','WriteError','RemoteProtocolError','NetworkError'}:category='provider_network_failure'
        elif name in {'ValidationError','JSONDecodeError'}:category='response_schema_invalid'
        elif 'operationalerror' in name.lower() or 'database' in name.lower():category='database_error'
        elif 'vision is incomplete' in lower:category='required_perception_unavailable'
        else:category='worker_exception'
    attempted_network=bool(code) if attempted_network is None else bool(attempted_network)
    # Fixed messages prevent SDK errors from echoing private prompts, images,
    # URLs, account details or arbitrary provider response bodies into logs.
    messages = {
        'provider_quota_or_rate_limit':'Provider quota/rate limit rejected the request; inspect limits before retrying.',
        'provider_access_denied':'Provider authentication/access was denied; verify access without rotating credentials.',
        'provider_configuration':'Provider rejected the request or model configuration.',
        'provider_http_error':'A transient provider HTTP error was returned.',
        'provider_network_failure':'The provider connection failed without an HTTP response.',
        'provider_circuit_open':'The application provider circuit blocked this request locally.',
        'authorized_budget_exhausted':'The application attempt budget blocked this request locally.',
        'provider_control_busy':'Another writer holds the provider control; no request was admitted.',
        'provider_control_invalid':'Provider control history is unreadable or invalid; preserve and repair its audit history.',
        'timeout':'The bounded provider operation timed out.',
        'response_schema_invalid':'The returned response failed validation; its contents are omitted.',
        'required_perception_unavailable':'Required visible observations are unavailable; human review is required.',
    }
    result = {'stage':stage,'error_category':category,'timestamp':datetime.now(timezone.utc).isoformat(),
        'attempt_count':int(attempt_count or 0),'retryable':category in {'provider_http_error','provider_network_failure','timeout','database_error'},
        'provider_status':('http_'+str(code)) if code else ('response_received' if category=='response_schema_invalid' else 'not_attempted' if not attempted_network else 'no_response'),
        'http_status':code,'attempted_network':attempted_network,'exception_type':name,
        'message':messages.get(category, 'The stage failed (' + name + '); inspect its sanitized category and required inputs.')}
    status = getattr(error, 'status', None)
    if isinstance(status,str) and re.fullmatch(r'[A-Z_]{2,64}',status):result['provider_error_code']=status
    response = getattr(error,'response',None)
    headers = getattr(response,'headers',{}) or {}
    request_id = headers.get('x-request-id') or headers.get('x-goog-request-id')
    if isinstance(request_id,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',request_id) and not request_id.startswith(('AIza','sk-')):
        result['provider_request_id']=request_id
    result.update(getattr(error,'response_metadata',{}) or {})
    if model:result['model']=model
    return result
