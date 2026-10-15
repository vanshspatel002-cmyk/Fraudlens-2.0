"""Compare storage-sensitive checks on identical preserved SQLite/PG records.

Labels select representative coverage only, never detector inputs. No provider,
uncached HTTP, new OCR or fabricated perception is used. Execution equivalence
does not demonstrate detection accuracy. Output contains summaries, not photos.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import db
from src.checks.base import run_checks

CHECKS=['internal_duplicate','entity_graph','baseline_linkage','severity_progression','threshold_gaming']


def canonical(findings):
    return sorted([{'check_id':f.check_id,'verdict':f.verdict.value,'confidence':f.confidence,
                    'explanation':f.explanation,'evidence':f.evidence} for f in findings],
                  key=lambda f:json.dumps(f,sort_keys=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'outputs/pilot_validation/demo.db')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Use a new verification output file.')
    # The full restored data copy is isolated from the pilot's working tables.
    if not args.schema.startswith('fraudlens_restore_'):
        raise SystemExit('Run checks on a new restored schema, not the active pilot.')
    os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    selected={}
    with (ROOT/'data/generated/ground_truth.csv').open(encoding='utf-8') as f:
        for row in csv.DictReader(f):
            selected.setdefault((row['agent_type'],row['archetype']),row['case_id'])
    source=sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    target=db.connect('postgresql')
    observations=[]
    try:
        target.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for (workflow,archetype),case_id in selected.items():
            left=canonical(run_checks(source,db.get_case(source,case_id),check_ids=CHECKS))
            right=canonical(run_checks(target,db.get_case(target,case_id),check_ids=CHECKS))
            observations.append({'workflow':workflow,'archetype':archetype,'case_id':case_id,
                'identical':left==right,'sqlite':left,'postgresql':right})
        result={'checks':CHECKS,'representatives':len(observations),
                'identical':sum(r['identical'] for r in observations),'provider_requests':0,
                'limitations':'Stored evidence and deterministic execution comparison; not independent accuracy.',
                'observations':observations}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='observations'}))
        return int(result['identical']!=result['representatives'])
    finally:
        target.rollback();target.close();source.close()


if __name__=='__main__':raise SystemExit(main())
