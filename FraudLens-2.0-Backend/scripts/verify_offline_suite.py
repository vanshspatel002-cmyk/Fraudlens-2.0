"""Use each suite's own runner, archive combined output and true exit codes.

Live integration is disabled. Some tests use explicitly mocked model responses;
none of these results establishes provider reliability or detection accuracy.
"""
import json
import argparse
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
    ['-m','pytest','-q','test_pilot_workflow.py','test_durable_pilot.py','test_demo_readiness.py',
     'test_customer_workflow.py','test_report_pdf.py','test_deployment_storage.py'],
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',action='store_true',help='Keep verified completed runners; use new logs for interrupted/failed attempts.')
    parser.add_argument('--rerun',nargs='*',default=[],help='Runner names to repeat after relevant source changes; preserves earlier logs.')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.update(FRAUDLENS_TEST_LIVE='0',FRAUDLENS_WARM_MODELS='0',
        FRAUDLENS_SKIP_CORPUS_SWEEPS='1',
        FRAUDLENS_WORKER_ENABLED='0',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        GEMINI_QUOTA_BUDGET=str(OUT/'quota_budget.json'),GEMINI_QUOTA_CONSUMER='offline-test')
    saved=json.loads((OUT/'results.json').read_text(encoding='utf-8')) if args.resume and (OUT/'results.json').exists() else []
    results=[]
    for index,command in enumerate(COMMANDS):
        name=command[0] if command[0]!='-m' else 'focused-pytest'
        logfile=OUT/(Path(name).stem+'.log')
        previous=next((r for r in saved if r['runner']==name),None)
        if previous and previous['exit_code']==0 and previous['counts']['failed']==0 and name not in args.rerun:
            if previous['command'] != [sys.executable,*command] or not (ROOT/previous['log']).is_file():
                raise SystemExit('Saved runner does not match this command/log: '+name)
            results.append(previous)
            print('Preserved completed runner',name,flush=True)
            continue
        if logfile.exists():
            if not args.resume:raise SystemExit('Existing release log; inspect rather than overwrite: '+str(logfile))
            attempt=2
            while (OUT/(Path(name).stem+f'-attempt{attempt}.log')).exists():attempt+=1
            logfile=OUT/(Path(name).stem+f'-attempt{attempt}.log')
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
