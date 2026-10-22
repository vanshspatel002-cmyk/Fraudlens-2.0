"""Strict diagnostic alignment with the pilot's effective process environment.

No database/client creation, default SQLite selection or alternative ledgers.
Credentials only pass through memory; exceptions name settings, never values.
"""
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAMES = ('FRAUDLENS_DB','FRAUDLENS_PG_SCHEMA','DATABASE_URL',
    'LLM_PROVIDER','GEMINI_MODEL','FRAUDLENS_GEMINI_REQUEST_PROFILE',
    'FRAUDLENS_LIVE_LEDGER','FRAUDLENS_LIVE_LIMIT','GEMINI_QUOTA_BUDGET','GEMINI_QUOTA_CONSUMER')
KEY_NAMES = ('GEMINI_API_KEY',*[f'GEMINI_API_KEY_{i}' for i in range(2,11)])


class PilotConfigurationError(ValueError):
    pass


def load_pilot_environment(source, root=ROOT):
    """Validate the supplied API/worker environment; never supply defaults."""
    env=dict(source)
    missing=[name for name in CONFIG_NAMES if not str(env.get(name,'')).strip()]
    if missing:
        raise PilotConfigurationError('Missing pilot configuration: '+', '.join(missing)+'. Use --process-id for the running pilot API; shell defaults are refused.')
    if env['FRAUDLENS_DB']!='postgresql':raise PilotConfigurationError('FRAUDLENS_DB must select the pilot PostgreSQL database.')
    if not re.fullmatch(r'fraudlens_[a-z0-9_]+',env['FRAUDLENS_PG_SCHEMA']):raise PilotConfigurationError('FRAUDLENS_PG_SCHEMA is invalid.')
    if env['LLM_PROVIDER']!='gemini':raise PilotConfigurationError('LLM_PROVIDER must select the configured Gemini adapter.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',env['GEMINI_MODEL']):raise PilotConfigurationError('GEMINI_MODEL is invalid.')
    if env['FRAUDLENS_GEMINI_REQUEST_PROFILE']!='gemini3_defaults_v2':raise PilotConfigurationError('The pilot request profile must be gemini3_defaults_v2.')
    if env['GEMINI_QUOTA_CONSUMER']!='pilot':raise PilotConfigurationError('GEMINI_QUOTA_CONSUMER must select pilot controls.')
    try:cap=int(env['FRAUDLENS_LIVE_LIMIT'])
    except ValueError:raise PilotConfigurationError('FRAUDLENS_LIVE_LIMIT must be an integer.') from None
    if not 0<=cap<=15:raise PilotConfigurationError('FRAUDLENS_LIVE_LIMIT must retain the original cap or a lower limit.')
    if not any(env.get(name,'').strip() for name in KEY_NAMES):raise PilotConfigurationError('The pilot Gemini key configuration is missing.')
    if not env['DATABASE_URL'].startswith(('postgresql://','postgres://')):raise PilotConfigurationError('DATABASE_URL must select PostgreSQL.')
    for name,filename in [('FRAUDLENS_LIVE_LEDGER','live_calls.json'),('GEMINI_QUOTA_BUDGET','quota_budget.json')]:
        actual=Path(env[name]);actual=actual if actual.is_absolute() else root/actual
        expected=(root/'outputs/pilot_validation'/filename).resolve()
        if actual.resolve()!=expected or not expected.is_file():raise PilotConfigurationError(name+' must reference the preserved existing pilot ledger.')
        env[name]=str(expected)
    from . import session_budget,quota_budget
    import json
    session_budget._validate_state(json.loads(Path(env['FRAUDLENS_LIVE_LEDGER']).read_text(encoding='utf8')))
    quota_budget._validate_state(json.loads(Path(env['GEMINI_QUOTA_BUDGET']).read_text(encoding='utf8')))
    return env


def apply_pilot_environment(env):
    """Use exactly the reference's provider settings, including absent numbered keys."""
    names=set(CONFIG_NAMES+KEY_NAMES+('GEMINI_DAILY_QUOTA_PER_KEY','GOOGLE_API_KEY',
        'FRAUDLENS_VALIDATION_ID','FRAUDLENS_RESPONSE_DIR',
        'GOOGLE_GENAI_USE_VERTEXAI','GOOGLE_GENAI_USE_ENTERPRISE','GOOGLE_GEMINI_BASE_URL','GOOGLE_VERTEX_BASE_URL',
        'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR'))
    for name in names:
        if name in env:os.environ[name]=env[name]
        else:os.environ.pop(name,None)
    # Never inherit an unrelated process's recovery grant.
    os.environ.pop('FRAUDLENS_RECOVERY_ID',None)
