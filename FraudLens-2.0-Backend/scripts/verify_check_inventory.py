"""Run every registered check on real representative records in isolated copies.

Answer keys select evaluation samples only; checks receive stored case data.
Uncached external HTTP lookups are disabled and recorded as inconclusive.
No verdict is synthesized from labels and no historical outputs are replaced.
"""
from collections import Counter, defaultdict
import csv
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch
import requests

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.setdefault('HF_HUB_OFFLINE','1');os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
from src import db
from src.checks import REGISTRY, run_checks
from src.agent.production_policy import production_policy


def main():
    out=ROOT/'outputs/pilot_validation';out.mkdir(parents=True,exist_ok=True)
    labels={r['case_id']:r['archetype'] for r in csv.DictReader(open(ROOT/'data/generated/ground_truth.csv',encoding='utf-8'))}
    inventory=[];execution=[]
    for check in REGISTRY.values():
        inventory.append({'id':check.check_id,'path':str(Path(inspect.getfile(type(check))).relative_to(ROOT)),
            'weight':check.weight,'scope':check.scope,'requires_perception':check.requires_perception,
            'production_workflows':[k for k in ('claims','underwriting') if check.check_id in production_policy(k).check_ids],
            'research_targets':list(check.target_archetypes),'limitation':getattr(check,'limitation',None)})
    # Label keys in the scenario artifacts supplement evaluation metadata.
    for filename in ('collusion_ring_labels.json','repeat_claim_labels.json','baseline_linkage_labels.json'):
        data=json.loads((ROOT/'outputs'/filename).read_text(encoding='utf-8'))
        print(filename,'keys',list(data)[:8],flush=True)
    for filename in ('fraudlens.db','fraudlens_scenarios.db','fraudlens_ring.db','fraudlens_repeat.db'):
        path=out/('checks-'+filename)
        if path.exists(): raise RuntimeError('Evaluation copy already exists: inspect it rather than overwrite '+str(path))
        source=sqlite3.connect((ROOT/filename).as_uri()+'?mode=ro',uri=True);target=sqlite3.connect(path);source.backup(target);source.close();target.close()
        conn=db.connect(path);db.init_db(conn)
        try:
            cases=db.get_all_cases(conn);buckets=defaultdict(list)
            for case in cases:buckets[(case.agent_type,labels.get(case.case_id,'SCENARIO_UNLABELLED'))].append(case)
            selected=[]
            for key,rows in sorted(buckets.items()):
                # One per original archetype/workflow plus each actual injected
                # scenario record. Case IDs select membership only, never verdicts.
                selected.extend(rows if key[1]=='SCENARIO_UNLABELLED' else rows[:1])
            # Scenario scripts often modify existing IDs. Include every labeled
            # case referenced by scenario measurement artifacts recursively.
            if filename!='fraudlens.db':
                scenario_ids=set()
                for artifact in ('collusion_ring_labels.json','repeat_claim_labels.json','baseline_linkage_labels.json'):
                    def collect(value):
                        if isinstance(value,str) and value in {c.case_id for c in cases}:scenario_ids.add(value)
                        elif isinstance(value,dict):
                            for k,v in value.items():collect(k);collect(v)
                        elif isinstance(value,list):
                            for v in value:collect(v)
                    collect(json.loads((ROOT/'outputs'/artifact).read_text(encoding='utf-8')))
                selected.extend(c for c in cases if c.case_id in scenario_ids)
            unique={c.case_id:c for c in selected}
            print(filename,'selected',len(unique),flush=True)
            for index,case in enumerate(unique.values()):
                started=time.monotonic()
                with patch('requests.get',side_effect=requests.ConnectionError('Offline verification: external lookup disabled')):
                    findings=run_checks(conn,case)
                counts=defaultdict(Counter);errors=[]
                for f in findings:
                    counts[f.check_id][f.verdict.value]+=1
                    if f.evidence.get('error_type'):errors.append({'check':f.check_id,'type':f.evidence['error_type'],'message':f.evidence.get('error','')[:300]})
                item={'database':filename,'case_id':case.case_id,'workflow':case.agent_type,
                      'archetype':labels.get(case.case_id,'SCENARIO_UNLABELLED'),'counts':dict(counts),
                      'errors':errors,'seconds':round(time.monotonic()-started,2)}
                execution.append(item);conn.commit()
                (out/'check_verification.json').write_text(json.dumps({'inventory':inventory,'executions':execution},indent=2),encoding='utf-8')
                print(filename,index+1,'/',len(unique),'check_errors',len(errors),flush=True)
        finally:conn.close()
    print('Completed',len(execution),'representative case executions; not an accuracy benchmark.')


if __name__=='__main__':main()
