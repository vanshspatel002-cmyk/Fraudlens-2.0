"""Use each suite's own runner, archive combined output and true exit codes.

Live integration is disabled. Some tests use explicitly mocked model responses;
none of these results establishes provider reliability or detection accuracy.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('FRAUDLENS_OFFLINE_OUTPUT_DIR',str(ROOT/'outputs/pilot_validation/offline_release')))
COMMANDS=[
    ['test_models.py'],['test_baseline.py'],['test_agent.py'],['test_llm.py'],
    ['test_perception.py'],['test_ingest.py'],['test_checks.py'],['test_api.py'],
    ['scripts/verify_integration.py'],
    ['-m','pytest','-q','test_pilot_workflow.py','test_durable_pilot.py'],
]


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.update(FRAUDLENS_TEST_LIVE='0',FRAUDLENS_WARM_MODELS='0',
        FRAUDLENS_WORKER_ENABLED='0',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        GEMINI_QUOTA_BUDGET=str(OUT/'quota_budget.json'),GEMINI_QUOTA_CONSUMER='offline-test')
    results=[]
    for index,command in enumerate(COMMANDS):
        name=command[0] if command[0]!='-m' else 'focused-pytest'
        logfile=OUT/(Path(name).stem+'.log')
        if logfile.exists():raise SystemExit('Existing release log; inspect rather than overwrite: '+str(logfile))
        print('Running',name,flush=True);started=time.monotonic()
        with logfile.open('w',encoding='utf-8') as log:
            run=subprocess.run([sys.executable,'-u','-X','utf8',*command],cwd=ROOT,env=env,
                stdout=log,stderr=subprocess.STDOUT,timeout=1800)
        content=logfile.read_text(encoding='utf-8')
        matches=re.findall(r'(\d+) passed, (\d+) failed(?:, (\d+) skipped)?',content)
        if matches:
            passed,failed,skipped=matches[-1];counts={'passed':int(passed),'failed':int(failed),'skipped':int(skipped or 0)}
        elif name=='focused-pytest':
            counts={key:int((re.findall(r'(\d+) '+key,content) or ['0'])[-1]) for key in ('passed','failed','skipped')}
        else:
            # The integration runner uses a final success sentence, not test counts.
            counts={'passed':int(run.returncode==0),'failed':int(run.returncode!=0),'skipped':0}
        result={'runner':name,'command':[sys.executable,*command],'exit_code':run.returncode,
                'seconds':round(time.monotonic()-started,2),'counts':counts,'log':str(logfile.relative_to(ROOT))}
        results.append(result)
        (OUT/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    return 1 if any(r['exit_code'] or r['counts']['failed'] for r in results) else 0


if __name__=='__main__':raise SystemExit(main())
