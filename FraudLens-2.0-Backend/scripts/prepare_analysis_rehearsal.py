"""Prepare a NEW private PostgreSQL namespace for real two-role verification.

Never resets an existing schema. Credentials are generated locally and written
only to ignored private files. This command does not call a model or enqueue work.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from src import db,pg_migrations,runtime_store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--schema',required=True)
    parser.add_argument('--recovery-result',type=Path,required=True)
    args=parser.parse_args()
    if not args.schema.startswith('fraudlens_repair_'):raise SystemExit('Use a new fraudlens_repair_ namespace.')
    directory=args.directory.resolve()
    if directory.exists():raise SystemExit('Use a new private output directory.')
    result=json.loads(args.recovery_result.read_text())
    if not result.get('success'):raise SystemExit('Real validation requires a successful audited provider recovery.')
    load_dotenv(ROOT/'.env');os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    reviewer={'email':'repair-reviewer@example.test','password':secrets.token_urlsafe(24)}
    customer={'name':'Fictional Pipeline Validation','email':'repair-'+secrets.token_hex(4)+'@example.test','password':secrets.token_urlsafe(24)}
    conn=db.connect('postgresql')
    try:
        conn.execute('BEGIN');pg_migrations.install(conn)
        conn.execute("INSERT INTO organizations(organization_id,name) VALUES ('local','Isolated pipeline validation')")
        conn.execute('INSERT INTO reviewer_accounts(email,password_hash,role) VALUES (?,?,?)',
            (reviewer['email'],runtime_store.password_hash(reviewer['password']),'reviewer'))
        conn.commit()
    finally:conn.close()
    directory.mkdir(parents=True)
    photos=sorted((ROOT/'data/curated/whole').glob('*.jpg'))
    if len(photos)<7:raise SystemExit('Seven explicit real vehicle photographs are required.')
    config={'schema':args.schema,'reviewer':reviewer,'customer':customer,'customer_register':True,
        'photos':{'claims':[str(photos[0])],'underwriting':[str(p) for p in photos[1:7]]},
        'evidence_limitation':'Real corpus photographs test processing; independent same-vehicle six-view identity is not established.',
        'output_dir':str(directory/'browser'),'runtime_dir':str(directory),
        'api':'http://127.0.0.1:8001','ui':'http://127.0.0.1:5173',
        'recovery_id':result['recovery_id'],'created_at':datetime.now(timezone.utc).isoformat()}
    (directory/'private-rehearsal.json').write_text(json.dumps(config,indent=2),encoding='utf8')
    print(json.dumps({'prepared_schema':args.schema,'private_configuration':str(directory/'private-rehearsal.json'),'model_requests':0}))

if __name__=='__main__':main()
