"""Read-only Gemini configuration/control audit. Never creates clients or calls APIs.

--process-id reads a local same-user pilot environment in memory (64-bit Windows
or Linux). Otherwise the shell must already contain COMPLETE pilot settings.
Only safe configuration is printed. No SQLite/alternate-ledger fallback exists.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def process_environment(pid):
    if os.name != 'nt':
        data = Path(f'/proc/{int(pid)}/environ').read_bytes().decode()
        return dict(item.split('=',1) for item in data.split('\0') if '=' in item)
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('Use the existing 64-bit Python environment.')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.ReadProcessMemory.argtypes = [wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    class Basic(ctypes.Structure):
        _fields_ = [('reserved',ctypes.c_void_p),('peb',ctypes.c_void_p),('reserved2',ctypes.c_void_p*2),('pid',ctypes.c_void_p),('reserved3',ctypes.c_void_p)]
    handle = kernel.OpenProcess(0x410,False,int(pid))
    if not handle:raise PermissionError('Cannot inspect the selected local process.')
    def read(address, length):
        buffer = ctypes.create_string_buffer(length);count = ctypes.c_size_t()
        ok = kernel.ReadProcessMemory(handle,address,buffer,length,ctypes.byref(count))
        if not ok and not count.value:raise OSError('Cannot read the selected process environment.')
        return buffer.raw[:count.value]
    def pointer(address):return int.from_bytes(read(address,8),'little')
    try:
        info = Basic();ntdll = ctypes.WinDLL('ntdll')
        query = ntdll.NtQueryInformationProcess
        query.argtypes = [wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.ULONG,ctypes.c_void_p]
        if query(handle,0,ctypes.byref(info),ctypes.sizeof(info),None):raise OSError('Process query failed.')
        parameters = pointer(info.peb+0x20)
        address = pointer(parameters+0x80)
        data = b''
        for _ in range(256):
            chunk = read(address+len(data), min(4096,4096-(address+len(data))%4096))
            data += chunk
            text = data.decode('utf-16-le',errors='ignore')
            if '\0\0' in text:
                return dict(item.split('=',1) for item in text.split('\0\0',1)[0].split('\0') if '=' in item and not item.startswith('='))
        raise ValueError('Environment exceeds bounded inspection size.')
    finally:kernel.CloseHandle(handle)


def safe_path(value):
    if not value:return None
    path = Path(value).resolve()
    try:return '<backend>/' + path.relative_to(ROOT).as_posix()
    except ValueError:return '<private>/' + path.name


def iso(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat() if isinstance(value,(int,float)) else None


def summarize(env):
    from src import session_budget, quota_budget
    model = env.get('GEMINI_MODEL','gemini-3.5-flash')
    # Model strings are configuration identifiers, not arbitrary text.
    if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',model):model='<invalid model identifier>'
    result = {'provider':env.get('LLM_PROVIDER','gemini') if env.get('LLM_PROVIDER','gemini') in {'gemini','ollama'} else 'unsupported',
        'agent_model':model,'perception_model':model,'same_provider_instance_for_both_stages':True,
        'key_present':any(bool(env.get('GEMINI_API_KEY'+suffix,'').strip()) for suffix in ['',*[f'_{i}' for i in range(2,11)]]),
        'sdk_version':importlib.metadata.version('google-genai'),
        'request_profile':env.get('FRAUDLENS_GEMINI_REQUEST_PROFILE','legacy') if env.get('FRAUDLENS_GEMINI_REQUEST_PROFILE','legacy') in {'legacy','gemini3_defaults_v2'} else 'unsupported',
        'session_ledger':safe_path(env.get('FRAUDLENS_LIVE_LEDGER')),
        'quota_ledger':safe_path(env.get('GEMINI_QUOTA_BUDGET','outputs/quota_budget.json')),
        'worker_enabled':env.get('FRAUDLENS_WORKER_ENABLED','1')=='1',
        'recovery_id_present':bool(env.get('FRAUDLENS_RECOVERY_ID')),
        'database_kind':'postgresql' if env.get('FRAUDLENS_DB')=='postgresql' else 'sqlite/default',
        'postgresql_schema':env.get('FRAUDLENS_PG_SCHEMA') if re.fullmatch(r'fraudlens_[a-z0-9_]+',env.get('FRAUDLENS_PG_SCHEMA','')) else None,
        'sdk_endpoint_override_present':any(bool(env.get(n)) for n in ['GOOGLE_GEMINI_BASE_URL','GOOGLE_VERTEX_BASE_URL','GOOGLE_GENAI_USE_VERTEXAI']),
        'shell_key_matches_dotenv':None}
    from dotenv import dotenv_values
    declared = dotenv_values(ROOT/'.env')
    names = ['GEMINI_API_KEY',*[f'GEMINI_API_KEY_{i}' for i in range(2,11)]]
    result['shell_key_matches_dotenv'] = all(env.get(n,'')==declared.get(n,'') for n in names)
    filename = env.get('FRAUDLENS_LIVE_LEDGER')
    if filename and Path(filename).is_file():
        state = json.loads(Path(filename).read_text(encoding='utf8'));session_budget._validate_state(state)
        cap = min(15,max(0,int(env.get('FRAUDLENS_LIVE_LIMIT','15'))));recovery = (state.get('recoveries') or [{}])[-1]
        failed = [e for e in state['events'] if e['outcome'].startswith('failure:')]
        result['session'] = {'attempts':state['attempts'],'cap':cap,'headroom':max(0,cap-state['attempts']),
            'stop':state['stopped'],'initial_stop_at':iso(failed[1].get('time')) if len(failed)>1 else None,
            'last_event_at':iso(state['events'][-1].get('time')) if state['events'] else None,
            'last_outcome':state['events'][-1]['outcome'] if state['events'] else None,
            'recovery_status':recovery.get('status'),'recovery_finished_at':iso(recovery.get('finished_at')),
            'new_recovery_permitted':session_budget.recovery_eligibility(state,cap,operator=True)['eligible'],
            'recovery_block_reason':session_budget.recovery_eligibility(state,cap,operator=True)['reason'],
            'authorized_now':0 if state['stopped'] and recovery.get('status') not in {'authorized','validation_authorized'} else max(0,min(cap-state['attempts'],recovery.get('allowance',cap)-recovery.get('reserved',0)))}
    else:result['session']={'status':'unconfigured_or_missing; do not infer pilot allowance'}
    if filename and Path(filename).is_file() and state.get('validation_grants'):
        grant=state['validation_grants'][-1]
        result['session'].update(normal_process_cap=cap,cap=grant['ceiling'],headroom=max(0,grant['ceiling']-state['attempts']))
        result['validation_grant']={key:grant.get(key) for key in ('policy','schema','status','allowance','reserved','jobs')}
        result['validation_grant'].update(expires_at=iso(grant['expires_at']),
            currently_authorized=max(0,grant['allowance']-grant['reserved']) if grant['status']=='active' and time.time()<grant['expires_at'] else 0)
    filename = env.get('GEMINI_QUOTA_BUDGET','outputs/quota_budget.json')
    if Path(filename).is_file():
        state=json.loads(Path(filename).read_text(encoding='utf8'));quota_budget._validate_state(state)
        result['daily']={'recorded_day':state['quota_day'],'current_pacific_day':quota_budget.pacific_quota_day(),
            'recorded_cap':state['total_daily_quota'],'recorded_reservations':sum(v['reserved'] for v in state['consumers'].values()),
            'historical_days':len(state.get('history',[])),'note':'Recorded reservations are not proof of outbound HTTP; no rollover is written by this audit.'}
    return result


def request_plan(claims_images=1,underwriting_images=6):
    """Counts for the existing rehearsal shape, not a promise of convergence."""
    from src.agent.production_policy import production_policy
    images=claims_images+underwriting_images
    turns=sum(production_policy(kind).max_iterations for kind in ['claims','underwriting'])
    return {'claims_photographs':claims_images,'underwriting_photographs':underwriting_images,
        'fresh_image_calls_minimum':images,'agent_final_turns_minimum':2,
        'case_calls_minimum_without_tool_followups':images+2,
        'case_calls_with_one_tool_followup_per_case':images+4,
        'initial_structured_image_probe':1,
        'total_including_probe_minimum':images+3,
        'total_with_probe_and_one_tool_followup_per_case':images+5,
        'worst_case_including_one_schema_retry_per_image_and_agent_iteration_caps':2*images+turns+1,
        'note':'No cache counts as fresh. Local tool execution costs no generation; its follow-up turn does. Recovery transport retries are disabled.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    group.add_argument('--process-id',type=int);group.add_argument('--pilot',action='store_true')
    parser.add_argument('--plan-validation',action='store_true',help='Count calls for the existing one-photo claims/six-photo underwriting rehearsal without submitting anything.')
    args=parser.parse_args()
    try:
        from src.pilot_config import load_pilot_environment,PilotConfigurationError
        env=load_pilot_environment(process_environment(args.process_id) if args.process_id else os.environ.copy())
        result=summarize(env)
        result['configuration_source']='running_pilot_process' if args.process_id else 'complete_pilot_environment'
        if args.plan_validation:result['validation_request_plan']=request_plan()
        print(json.dumps(result,indent=2))
    except Exception as exc:
        print(json.dumps({'audit_failed':type(exc).__name__,'detail':str(exc) if isinstance(exc,PilotConfigurationError) else 'Configuration/controls could not be read safely; no request attempted.'}));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
