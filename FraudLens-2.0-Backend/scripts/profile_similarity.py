"""Read-only full-corpus similarity timing and exact-result equivalence.

Reads one existing case and the comparison corpus; never runs a provider,
changes a database or sweeps cases. Use a new output path for each observation.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import db, ingest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--case-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Use a new output file; prior observations are immutable.')
    load_dotenv(ROOT/'.env')
    conn=db.connect(args.db)
    try:
        if db.is_postgres(conn):
            conn.execute('BEGIN')
            conn.execute('SET TRANSACTION READ ONLY')
        else:conn.execute('PRAGMA query_only=ON')
        images=db.get_images_for_case(conn,args.case_id)
        if not images:raise SystemExit('Existing case has no images.')
        start=time.perf_counter()
        index=ingest.SimilarityIndex.from_database(conn,args.case_id)
        loaded=time.perf_counter()-start
        start=time.perf_counter();results=[]
        for image in images:
            if image.embedding is None:continue
            actual=index.search(image.embedding)
            # Independent copy of the original calculation; do not reuse the
            # cached matrix/norms in this reference comparison.
            matrix=np.asarray([c.embedding for c in index.candidates],dtype=np.float64)
            query=np.asarray(image.embedding,dtype=np.float64)
            if not index.candidates or not np.linalg.norm(query):expected=[]
            else:
                denom=np.linalg.norm(matrix,axis=1)*np.linalg.norm(query)
                sims=np.divide(matrix@query,denom,out=np.zeros_like(denom),where=denom!=0)
                expected=[(index.candidates[i],float(sims[i])) for i in np.argsort(-sims)[:10]]
            assert [(x.image_id,s) for x,s in actual]==[(x.image_id,s) for x,s in expected]
            results.append({'exact_order_and_scores_equal':True,'match_count':len(actual)})
        result={'database':'postgresql' if db.is_postgres(conn) else 'sqlite',
            'case_id':args.case_id,'image_count':len(images),'compared':len(index.candidates),
            'corpus_load_and_prepare_seconds':round(loaded,3),
            'queries_and_reference_comparison_seconds':round(time.perf_counter()-start,3),
            'corpus_reads':1,'provider_requests':0,'comparisons':results}
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally:conn.rollback();conn.close()


if __name__=='__main__':main()
