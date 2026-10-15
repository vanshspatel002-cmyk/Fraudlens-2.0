"""Read-only evidence reconciliation; never deletes or rewrites any artifact."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from src import db


def main():
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=db.configured_target())
    parser.add_argument('--uploads',type=Path,default=Path(os.environ.get('FRAUDLENS_UPLOAD_DIR',str(ROOT/'outputs/pilot_validation/uploads'))))
    parser.add_argument('--hash',action='store_true',help='Compare actual bytes with recorded SHA-256 values')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Use a new output file; preserve earlier reconciliation results.')
    if args.db=='postgresql':
        conn=db.connect('postgresql')
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    else:
        source=Path(args.db).resolve()
        if not source.is_file():raise SystemExit('Existing database required; no empty database is created.')
        conn=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    missing=[];mismatches=[];referenced=set();rows=[]
    try:
        for image_id,path,expected in conn.execute('SELECT image_id,path,content_hash FROM images'):
            resolved=Path(path).resolve();referenced.add(resolved);rows.append(image_id)
            if not resolved.is_file():missing.append({'image_id':image_id,'path':path})
            elif args.hash and hashlib.sha256(resolved.read_bytes()).hexdigest()!=expected:
                mismatches.append({'image_id':image_id,'path':path})
        unreferenced=[str(p.resolve()) for p in args.uploads.rglob('*') if p.is_file() and p.resolve() not in referenced]
        result={'images':len(rows),'missing_paths':missing,'hash_checked':args.hash,
                'hash_mismatches':mismatches,'unreferenced_upload_files':unreferenced,
                'action':'None. Do not delete files until commit outcomes and all database/backup references are reconciled.'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'images':len(rows),'missing':len(missing),'hash_mismatches':len(mismatches),
                          'unreferenced_upload_files':len(unreferenced),'files_changed':0}))
        return int(bool(missing or mismatches))
    finally:
        conn.rollback();conn.close()


if __name__=='__main__':raise SystemExit(main())
