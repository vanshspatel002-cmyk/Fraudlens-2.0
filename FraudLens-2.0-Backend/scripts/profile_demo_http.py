"""Two real local submissions to measure first/warm admission on an isolated API.

Preserves accepted cases, performs no provider requests itself, and refuses ports
other than the explicitly isolated local 8001. Start with NoWorker/NoWarmup for a
cold-first measurement; warm startup should be measured separately in its log.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--database-name',required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise SystemExit('Use a new measurement output.')
    api='http://127.0.0.1:8001'
    image=sorted((ROOT/'data/curated/whole').glob('*.jpg'))[0]
    ledger=ROOT/'outputs/pilot_validation/live_calls.json'
    digest=hashlib.sha256(ledger.read_bytes()).hexdigest()
    result={'provider_requests':0,'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'submissions':[]}
    with httpx.Client(timeout=600) as client:
        assert client.get(api+'/health').json()['database']==args.database_name
        for label in ('cold_first','warm_second'):
            started=time.monotonic()
            response=client.post(api+'/v1/cases',headers={'Idempotency-Key':uuid.uuid4().hex},
                data={'agent_type':'claims','vehicle_registration':'MH12DE2001','policy_number':'PROFILE-FICTIONAL',
                      'declaration_notes':'Fictional latency rehearsal; stock image; no verified identity or fraud inference.'},
                files={'images':('vehicle.jpg',image.read_bytes(),'image/jpeg')})
            row={'label':label,'seconds':round(time.monotonic()-started,3),'http_status':response.status_code}
            if response.status_code==201:
                row.update(case_id=response.json()['case_id'],job_id=response.json()['job_id'])
            result['submissions'].append(row)
            args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)
            response.raise_for_status()
    assert hashlib.sha256(ledger.read_bytes()).hexdigest()==digest,'Provider ledger changed; investigate immediately.'


if __name__=='__main__':main()
