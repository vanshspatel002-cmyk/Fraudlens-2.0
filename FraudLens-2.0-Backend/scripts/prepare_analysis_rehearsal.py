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


def validate_recovery(result,ledger,photo_count,limit=15):
    """An old generic-text success cannot unlock a new live rehearsal."""
    if not result.get('success') or result.get('cached') is not False or result.get('structured_observation_valid') is not True:
        raise ValueError('A fresh, schema-valid image probe is required; generic text or cached replies do not qualify.')
    recovery=next((r for r in ledger.get('recoveries',[]) if r.get('recovery_id')==result.get('recovery_id')),None)
    if not recovery or recovery.get('status')!='validation_authorized':
        raise ValueError('The original recovery must currently authorize bounded validation; failed recovery cannot be reused.')
    attempt=result.get('attempts_after')
    event=next((e for e in ledger.get('events',[]) if e.get('attempt')==attempt),None)
    if not event or event.get('outcome')!='success' or event.get('recovery_id')!=result.get('recovery_id'):
        raise ValueError('The image probe has no successful matching original-ledger attempt.')
    remaining=min(min(15,int(limit))-ledger['attempts'],recovery['allowance']-recovery['reserved'])
    if remaining < photo_count+2:
        raise ValueError('Remaining original allowance cannot fit fresh image calls and two minimum agent turns.')
    return remaining


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--schema',required=True)
    parser.add_argument('--recovery-result',type=Path,required=True)
    parser.add_argument('--claims-photo',type=Path,action='append',required=True,help='Explicit authorized non-sensitive claims photograph; may repeat.')
    parser.add_argument('--underwriting-photo',type=Path,action='append',required=True,help='Explicit authorized six-view sample set; repeat exactly six times. Labels alone do not establish vehicle identity.')
    args=parser.parse_args()
    if not args.schema.startswith('fraudlens_repair_'):raise SystemExit('Use a new fraudlens_repair_ namespace.')
    directory=args.directory.resolve()
    if directory.exists():raise SystemExit('Use a new private output directory.')
    result=json.loads(args.recovery_result.read_text())
    ledger=json.loads((ROOT/'outputs/pilot_validation/live_calls.json').read_text(encoding='utf8'))
    from src.session_budget import _validate_state
    _validate_state(ledger)
    try:remaining=validate_recovery(result,ledger,len(args.claims_photo)+len(args.underwriting_photo),os.getenv('FRAUDLENS_LIVE_LIMIT','15'))
    except ValueError as exc:raise SystemExit(str(exc)) from None
    if len(args.underwriting_photo)!=6 or not all(p.is_file() for p in args.claims_photo+args.underwriting_photo):
        raise SystemExit('Select existing authorized claims photographs and exactly six underwriting views before creating a schema.')
    load_dotenv(ROOT/'.env');os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    reviewer={'email':'repair-reviewer@example.test','password':secrets.token_urlsafe(24)}
    customer={'name':'Fictional Pipeline Validation','email':'repair-'+secrets.token_hex(4)+'@example.test','password':secrets.token_urlsafe(24)}
    conn=db.connect('postgresql')
    try:
        conn.execute('BEGIN')
        if conn.execute('SELECT 1 FROM pg_namespace WHERE nspname=?',(args.schema,)).fetchone():
            raise SystemExit('Use a new isolated schema; the existing namespace was not modified.')
        pg_migrations.install(conn)
        conn.execute("INSERT INTO organizations(organization_id,name) VALUES ('local','Isolated pipeline validation')")
        conn.execute('INSERT INTO reviewer_accounts(email,password_hash,role) VALUES (?,?,?)',
            (reviewer['email'],runtime_store.password_hash(reviewer['password']),'reviewer'))
        conn.commit()
    finally:conn.close()
    directory.mkdir(parents=True)
    config={'schema':args.schema,'reviewer':reviewer,'customer':customer,'customer_register':True,
        'photos':{'claims':[str(p.resolve()) for p in args.claims_photo],'underwriting':[str(p.resolve()) for p in args.underwriting_photo]},
        'evidence_limitation':'Explicit authorized photographs; view labels alone do not establish same-vehicle identity.',
        'remaining_generation_allowance':remaining,
        'output_dir':str(directory/'browser'),'runtime_dir':str(directory),
        'api':'http://127.0.0.1:8001','ui':'http://127.0.0.1:5173',
        'recovery_id':result['recovery_id'],'created_at':datetime.now(timezone.utc).isoformat()}
    (directory/'private-rehearsal.json').write_text(json.dumps(config,indent=2),encoding='utf8')
    print(json.dumps({'prepared_schema':args.schema,'private_configuration':str(directory/'private-rehearsal.json'),'model_requests':0}))

if __name__=='__main__':main()
