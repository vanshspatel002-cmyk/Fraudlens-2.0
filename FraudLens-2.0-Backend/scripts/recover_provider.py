"""One audited transient-circuit probe via the normal provider adapter.

Does not clear the original stop, rotate credentials, change quotas or retry.
The original ledgers must exist. Named operator recovery after a failed transient
probe requires a 30-minute cooldown, preserved headroom and no in-flight request.
"""
import argparse
import hashlib
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import session_budget
from src.analysis_diagnostics import failure_detail
from src.pilot_config import load_pilot_environment,apply_pilot_environment,PilotConfigurationError
from scripts.diagnose_gemini import process_environment,summarize
# Compatibility name now refers to the ACTUAL ten-field observation contract.
from src.perception import PerceptionObservation as ProbeObservation


def inspect_metadata(env,output,operator,reason):
    """One separately budgeted GET; never authorizes or executes generation."""
    if not operator:raise SystemExit('Metadata inspection requires an explicit operator audit label.')
    if output.exists():raise SystemExit('Use a new private metadata output directory.')
    output.mkdir(parents=True)
    paths=[Path(env[name]) for name in ['FRAUDLENS_LIVE_LEDGER','GEMINI_QUOTA_BUDGET']]
    before=[p.read_bytes() for p in paths]
    if before!=[p.read_bytes() for p in paths]:raise SystemExit('Controls changed; metadata was not requested.')
    for name,data in zip(['session-before.json','quota-before.json'],before):(output/name).write_bytes(data)
    from src.llm import GeminiProvider
    provider=GeminiProvider(model=env['GEMINI_MODEL'],request_profile=env['FRAUDLENS_GEMINI_REQUEST_PROFILE'])
    result={'operation':'configured_model_metadata','generation_requests':0,'metadata_requests':0,
        'started_at':datetime.now(timezone.utc).isoformat(),'success':False}
    try:
        result['metadata']=provider.model_metadata(operator=operator,reason=reason)
        result['success']=True
    except Exception as exc:result['failure']=failure_detail(exc,'model_metadata')
    finally:
        result.update(http_attempts=provider.http_attempts,metadata_requests=provider.http_attempts,
            http_status=provider.http_statuses[-1] if provider.http_statuses else None,
            finished_at=datetime.now(timezone.utc).isoformat())
        provider.close()
        state=json.loads(paths[0].read_text(encoding='utf8'))
        result.update(attempts_after=state['attempts'],remaining_session_cap=max(0,int(env['FRAUDLENS_LIVE_LIMIT'])-state['attempts']))
        (output/'metadata-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2))
    return 0 if result['success'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Spend at most one original-budget request; explicit authorization required.')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reason',required=True)
    parser.add_argument('--image',type=Path,help='Explicitly authorized, non-sensitive sample vehicle photograph; required with --execute.')
    parser.add_argument('--process-id',type=int,help='Read the running pilot API environment; no shell defaults are accepted.')
    parser.add_argument('--operator',help='Explicit operator audit label for cooldown-governed recovery after an earlier failure.')
    parser.add_argument('--metadata-only',action='store_true',help='One separately budgeted configured-model GET; no generation or circuit reopening.')
    parser.add_argument('--schema-correction-commit',help='Explicit registered correction commit; separate one-use HTTP 400 gate.')
    parser.add_argument('--previous-failed-attempt',type=int,help='Original failed generation attempt corrected by this probe.')
    args=parser.parse_args()
    try:env=load_pilot_environment(process_environment(args.process_id) if args.process_id else os.environ.copy())
    except PilotConfigurationError as exc:raise SystemExit(str(exc)) from None
    apply_pilot_environment(env)
    import logging
    logging.getLogger().setLevel(logging.WARNING)
    ledger=Path(env['FRAUDLENS_LIVE_LEDGER']);quota=Path(env['GEMINI_QUOTA_BUDGET'])
    before=json.loads(ledger.read_text(encoding='utf8'))
    cap=min(15,max(0,int(os.environ['FRAUDLENS_LIVE_LIMIT'])))
    print(json.dumps({'operation':'configured-model metadata inspection' if args.metadata_only else 'single audited recovery probe','execute':args.execute,
        'historical_attempts':before['attempts'],'remaining_session_cap':max(0,cap-before['attempts']),
        'original_stop':before.get('stopped'),'prior_recoveries':len(before.get('recoveries',[]))}))
    if args.metadata_only:
        if args.schema_correction_commit or args.previous_failed_attempt is not None:raise SystemExit('Schema correction cannot authorize metadata.')
        if args.execute:raise SystemExit('Choose metadata-only or generation execution, not both.')
        return inspect_metadata(env,args.output.resolve(),args.operator,args.reason)
    if not args.execute:return 0
    if bool(args.schema_correction_commit) != (args.previous_failed_attempt is not None):raise SystemExit('Schema correction requires commit and previous failed attempt together.')
    if env.get('FRAUDLENS_WORKER_ENABLED')!='0':raise SystemExit('Use the API-only pilot environment; pause dedicated provider consumers before executing.')
    if not args.image or not args.image.is_file():raise SystemExit('Select an authorized sample vehicle photograph with --image. No request attempted.')
    from PIL import Image
    with Image.open(args.image) as image:image.verify()
    image_hash=hashlib.sha256(args.image.read_bytes()).hexdigest()
    output=args.output.resolve()
    if output.exists():raise SystemExit('Use a new private output directory.')
    output.mkdir(parents=True)
    # Stable controls are copied before any authorization mutation. Never reset
    # them or treat the backup as a new allowance. No credentials are copied.
    controls=[ledger.read_bytes(),quota.read_bytes()]
    if controls != [ledger.read_bytes(),quota.read_bytes()]:raise SystemExit('Controls changed concurrently; no recovery was authorized.')
    for name,content in zip(['session-before.json','quota-before.json'],controls):
        (output/name).write_bytes(content)
    provider=None
    stage='recovery_authorization'
    result={'started_at':datetime.now(timezone.utc).isoformat(),'success':False,'request_attempted':False,
        'http_attempted':False,'http_attempts':0,'metadata_requests':0,'schema_validation':'not_run',
        'requested_model':env['GEMINI_MODEL'],'request_profile':env['FRAUDLENS_GEMINI_REQUEST_PROFILE'],
        'perception_schema_version':None,'configuration':summarize(env)}
    try:
        from src.provider_contract import SCHEMA_WIRE_VERSION,perception_correction_contract
        request_contract=perception_correction_contract(image_hash,env['GEMINI_MODEL'],env['FRAUDLENS_GEMINI_REQUEST_PROFILE'])
        if args.schema_correction_commit:
            recovery_id=session_budget.authorize_schema_correction(args.reason,operator=args.operator,
                previous_attempt=args.previous_failed_attempt,correction_commit=args.schema_correction_commit,
                wire_version=SCHEMA_WIRE_VERSION,request_contract=request_contract,expected_attempts=before['attempts'])
            result.update(correction_commit=args.schema_correction_commit,previous_failed_attempt=args.previous_failed_attempt,
                wire_version=SCHEMA_WIRE_VERSION,request_contract=request_contract)
        else:
            recovery_id=session_budget.authorize_recovery(args.reason,operator=args.operator,expected_attempts=before['attempts'])
        os.environ['FRAUDLENS_RECOVERY_ID']=recovery_id
        result['recovery_id']=recovery_id
        from src.llm import GeminiProvider
        # Explicit values avoid module-import-time defaults captured from a shell.
        provider=GeminiProvider(model=env['GEMINI_MODEL'],request_profile=env['FRAUDLENS_GEMINI_REQUEST_PROFILE'])
        from src.perception import PERCEPTION_PROMPT,PERCEPTION_SCHEMA_VERSION,_record_from_parsed,perception_record_usable
        result['perception_schema_version']=PERCEPTION_SCHEMA_VERSION
        result['requested_model']=getattr(provider,'model','unrecorded')
        stage='recovery_probe'
        response=provider.describe_image(str(args.image),PERCEPTION_PROMPT,
            conn=None,retry_attempts=1,response_schema=ProbeObservation)
        stage='probe_observation_validation'
        observation=ProbeObservation.model_validate_json(response.text)
        result.update(cached=response.cached,latency_ms=response.latency_ms,structured_observation_valid=True,
            schema_validation='valid',observation_field_count=len(observation.model_dump()),
            request_provenance=response.raw.get('request_provenance',{}),
            finish_reason=response.raw.get('request_provenance',{}).get('finish_reason'))
        stage='probe_artifact_persistence'
        # Save a safe receipt before constructing the dataclass artifact, so a
        # local write/serialization error cannot erase provider provenance.
        (output/'response-receipt.json').write_text(json.dumps({key:result[key] for key in
            ('cached','latency_ms','schema_validation','observation_field_count','request_provenance','finish_reason')}),encoding='utf8')
        (output/'observations.json').write_text(observation.model_dump_json(indent=2),encoding='utf8')
        if hashlib.sha256(args.image.read_bytes()).hexdigest()!=image_hash:
            raise ValueError('Sample image changed during the request; observations cannot be attributed safely.')
        record=_record_from_parsed(image_hash,provider.model,observation.model_dump(),response.text)
        provenance=response.raw.get('request_provenance',{})
        record.raw_response['request_provenance']=provenance
        from dataclasses import asdict
        record_data=asdict(record)
        record_data['created_at']=record.created_at.isoformat()
        artifact={'record':record_data,'schema':ProbeObservation.model_json_schema(),
            'schema_version':PERCEPTION_SCHEMA_VERSION,'wire_version':SCHEMA_WIRE_VERSION,
            'request_profile':provider.request_profile,'request_contract':request_contract,
            'cached':response.cached,'latency_ms':response.latency_ms,
            'started_at':result['started_at'],'received_at':datetime.now(timezone.utc).isoformat()}
        (output/'observation-record.json').write_text(json.dumps(artifact,indent=2),encoding='utf8')
        usable=perception_record_usable(record)
        result.update(success=usable,cached=response.cached,latency_ms=response.latency_ms,
            structured_observation_valid=True,schema_validation='valid',usable_observations=usable,
            observation_field_count=len(observation.model_dump()),
            finish_reason=response.raw.get('request_provenance',{}).get('finish_reason'))
        result.update(image_sha256=image_hash,request_provenance=provenance,
            observation_artifact='observation-record.json')
        result['provider_model_version']=response.raw.get('model_version') or response.raw.get('modelVersion')
        result['response_present']=bool(response.text.strip())
        if not result['success']:
            session_budget.reject_recovery_result(recovery_id,'response_schema_invalid')
            raise ValueError('Schema-valid observations were unusable; no further generation is authorized.')
    except Exception as exc:
        result['failure']=failure_detail(exc,stage,attempted_network=bool(provider and provider.http_attempts))
        if stage=='probe_artifact_persistence':
            result['failure'].update(error_category='diagnostic_artifact_persistence',
                provider_status='response_received',message='The provider response was received; local diagnostic artifact persistence failed.')
        if result['failure']['error_category']=='response_schema_invalid':result['schema_validation']='invalid_or_incomplete'
        result['finish_reason']=result['failure'].get('finish_reason',result.get('finish_reason'))
    finally:
        if provider:
            result.update(http_attempts=provider.http_attempts,http_attempted=provider.http_attempts>0,
                http_status=provider.http_statuses[-1] if provider.http_statuses else None)
            provider.close()
        after=json.loads(ledger.read_text(encoding='utf8'))
        result['request_attempted']=after['attempts']>before['attempts']
        result['attempts_after']=after['attempts']
        result['remaining_session_cap']=max(0,cap-after['attempts'])
        result['generation_allowance_remaining']=0
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        (output/'probe-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2))
    return 0 if result['success'] else 1

if __name__=='__main__':raise SystemExit(main())
