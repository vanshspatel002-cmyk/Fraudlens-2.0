"""One audited transient-circuit probe via the normal provider adapter.

Does not clear the original stop, rotate credentials, change quotas or retry.
The original ledgers must already exist. Re-running after any probe is refused.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from src import session_budget
from src.analysis_diagnostics import failure_detail
from src.llm import get_provider
from pydantic import BaseModel, ConfigDict, Field


class ProbeObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vehicle_visible: bool
    observations: list[str] = Field(max_length=3)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Spend at most one original-budget request; explicit authorization required.')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reason',required=True)
    parser.add_argument('--image',type=Path,help='Explicitly authorized, non-sensitive sample vehicle photograph; required with --execute.')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env')
    ledger=ROOT/'outputs/pilot_validation/live_calls.json'
    quota=ROOT/'outputs/pilot_validation/quota_budget.json'
    if not ledger.is_file() or not quota.is_file():raise SystemExit('Restore original provider ledgers before recovery.')
    os.environ['FRAUDLENS_LIVE_LEDGER']=str(ledger)
    os.environ.setdefault('FRAUDLENS_LIVE_LIMIT','15')
    os.environ['GEMINI_QUOTA_BUDGET']=str(quota)
    os.environ['GEMINI_QUOTA_CONSUMER']='pilot'
    os.environ['FRAUDLENS_GEMINI_REQUEST_PROFILE']='gemini3_defaults_v2'
    before=json.loads(ledger.read_text(encoding='utf8'))
    cap=min(15,max(0,int(os.environ['FRAUDLENS_LIVE_LIMIT'])))
    print(json.dumps({'operation':'single audited recovery probe','execute':args.execute,
        'historical_attempts':before['attempts'],'remaining_session_cap':max(0,cap-before['attempts']),
        'original_stop':before.get('stopped'),'prior_recoveries':len(before.get('recoveries',[]))}))
    if not args.execute:return 0
    if not args.image or not args.image.is_file():raise SystemExit('Select an authorized sample vehicle photograph with --image. No request attempted.')
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
    result={'started_at':datetime.now(timezone.utc).isoformat(),'success':False,'request_attempted':False}
    try:
        recovery_id=session_budget.authorize_recovery(args.reason)
        os.environ['FRAUDLENS_RECOVERY_ID']=recovery_id
        result['recovery_id']=recovery_id
        provider=get_provider()
        from src.llm import GeminiProvider
        if not isinstance(provider,GeminiProvider):raise ValueError('This recovery operation requires the configured Gemini adapter.')
        result['requested_model']=getattr(provider,'model','unrecorded')
        response=provider.describe_image(str(args.image),
            'Describe only visible vehicle observations. Return vehicle_visible and up to three short observations. Do not infer identity, damage cost or fraud.',
            conn=None,retry_attempts=1,response_schema=ProbeObservation)
        observation=ProbeObservation.model_validate_json(response.text)
        result.update(success=True,cached=response.cached,latency_ms=response.latency_ms,
            structured_observation_valid=True,vehicle_visible=observation.vehicle_visible,
            observation_count=len(observation.observations))
        result['provider_model_version']=response.raw.get('model_version') or response.raw.get('modelVersion')
        result['response_present']=bool(response.text.strip())
        if not result['success']:
            raise ValueError('Provider returned an empty recovery response; stop and inspect response handling.')
    except Exception as exc:
        result['failure']=failure_detail(exc,'recovery_probe')
    finally:
        if provider:provider.close()
        after=json.loads(ledger.read_text(encoding='utf8'))
        result['request_attempted']=after['attempts']>before['attempts']
        result['attempts_after']=after['attempts']
        result['remaining_session_cap']=max(0,cap-after['attempts'])
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        (output/'probe-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2))
    return 0 if result['success'] else 1

if __name__=='__main__':raise SystemExit(main())
