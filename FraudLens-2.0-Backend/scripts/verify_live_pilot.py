"""Bounded real Gemini vision/adjudication probe on an isolated corpus copy.

Never rewrites research DBs or policies. Shares one persistent 15-request
session ledger with the demonstration server; failures stop network attempts.
"""
import json
import os
from pathlib import Path
import sys
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
OUT=ROOT/'outputs/pilot_validation'
OUT.mkdir(parents=True,exist_ok=True)
os.environ.setdefault('FRAUDLENS_LIVE_LEDGER',str(OUT/'live_calls.json'))
os.environ.setdefault('FRAUDLENS_LIVE_LIMIT','15')
os.environ.setdefault('GEMINI_QUOTA_BUDGET',str(OUT/'quota_budget.json'))
os.environ.setdefault('GEMINI_QUOTA_CONSUMER','pilot')
os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
from src import api, db, llm
from src.perception import perceive_image
from src.agent.engine import adjudicate
from src.agent.production_policy import production_policy
from src.checks import run_checks


def main():
    path=OUT/'demo.db'
    if not path.exists(): raise SystemExit('Prepare the isolated demo.db first; source database is never used for writes.')
    output=OUT/'live_verification.json'
    if output.exists(): raise SystemExit('This probe already ran. Inspect its output; do not repeat unattended requests.')
    conn=db.connect(path); provider=llm.get_provider(); observations=[]
    try:
        for kind in ('claims','underwriting'):
            # Evidence selection uses workflow and cache coverage only. No
            # filename, ground-truth label or desired result reaches inference.
            candidates=[c for c in db.get_all_cases(conn) if c.agent_type==kind]
            selected=None
            for case in candidates:
                images=db.get_images_for_case(conn,case.case_id)
                missing=[i for i in images if not db.get_perception_record(conn,i.content_hash) and Path(i.path).is_file()]
                if len(images)==1 and missing: selected=(case,missing[0]);break
            if not selected:
                observations.append({'workflow':kind,'status':'skipped','reason':'No single-image unperceived representative case'});continue
            case,image=selected; item={'workflow':kind,'case_id':case.case_id,'content_hash':image.content_hash,'model':provider.model}
            try:
                record=perceive_image(conn,image,provider,retry_attempts=1);conn.commit()
                item['vision_status']='parse_failure' if record.raw_response.get('error') else 'parsed'
                if item['vision_status']!='parsed':
                    item['status']='failed';observations.append(item);break
                findings=run_checks(conn,case,check_ids=list(production_policy(kind).check_ids));conn.commit()
                policy=replace(production_policy(kind),max_iterations=3,max_tool_calls=2,
                               policy_version=production_policy(kind).policy_version+'-probe-cap3')
                result=adjudicate(conn,case,findings,policy,provider);conn.commit()
                item.update(status='completed' if result.converged else 'fallback',converged=result.converged,
                    decision=result.decision.model_dump(mode='json') if hasattr(result.decision,'model_dump') else
                    {'recommendation':result.decision.recommendation.value,'risk_band':result.decision.risk_band.value,
                     'summary':result.decision.summary,'llm_calls':result.decision.llm_calls_count,'policy_version':policy.policy_version},
                    trace=result.trace_dicts(),finding_ids=[f.finding_id for f in findings])
                observations.append(item)
                ledger=json.loads(Path(os.environ['FRAUDLENS_LIVE_LEDGER']).read_text())
                if ledger.get('stopped'):break
            except Exception as exc:
                conn.rollback();item.update(status='failed',error_type=type(exc).__name__,provider_code=getattr(exc,'code',None));observations.append(item)
                # Quota/configuration/failure: stop this probe and continue offline.
                break
    finally:
        provider.close();conn.close()
        output.write_text(json.dumps({'observations':observations,'ledger':os.environ['FRAUDLENS_LIVE_LEDGER']},indent=2),encoding='utf-8')
    print(json.dumps(observations,default=str))


if __name__=='__main__':main()
