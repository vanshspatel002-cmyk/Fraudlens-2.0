"""Prepare a new schema/task grant or bind/close its real API-created jobs.

No inference or case outcome insertion. Private account configuration stays in
ignored outputs; only sanitized counts and schema names are printed.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.diagnose_gemini import process_environment
from src.pilot_config import load_pilot_environment, apply_pilot_environment
from src import db, pg_migrations, runtime_store, validation_budget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare','bind','close'])
    parser.add_argument('--process-id', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--schema')
    parser.add_argument('--expires-at', type=float)
    parser.add_argument('--claims-photo', type=Path)
    parser.add_argument('--underwriting-photo', type=Path, action='append', default=[])
    parser.add_argument('--case-id')
    parser.add_argument('--run-id')
    parser.add_argument('--kind', choices=['claims','underwriting'])
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    env = load_pilot_environment(process_environment(args.process_id))
    apply_pilot_environment(env)
    directory = args.directory.resolve(); config_path = directory/'private-validation.json'
    if args.operation == 'prepare':
        if directory.exists() or not args.claims_photo or not args.claims_photo.is_file():
            raise SystemExit('Use a new private directory and an inspected claims sample.')
        import re
        if not re.fullmatch(r'fraudlens_validation_[a-z0-9_]+', args.schema or ''):
            raise SystemExit('Use a new isolated validation schema.')
        if args.underwriting_photo and (len(args.underwriting_photo) != 6 or not all(p.is_file() for p in args.underwriting_photo)):
            raise SystemExit('Underwriting requires six inspected same-vehicle photographs; omit it if unavailable.')
        os.environ['FRAUDLENS_PG_SCHEMA'] = args.schema
        reviewer = {'email':'validation-reviewer@example.test','password':secrets.token_urlsafe(24)}
        customer = {'name':'Fictional Live Validation','email':'validation-customer@example.test','password':secrets.token_urlsafe(24)}
        conn = db.connect('postgresql')
        try:
            conn.execute('BEGIN')
            if conn.execute('SELECT 1 FROM pg_namespace WHERE nspname=?',(args.schema,)).fetchone():
                raise SystemExit('Schema already exists; no existing data was changed.')
            pg_migrations.install(conn)
            conn.execute("INSERT INTO organizations(organization_id,name) VALUES ('local','Isolated live validation')")
            conn.execute('INSERT INTO reviewer_accounts(email,password_hash,role) VALUES (?,?,?)',
                (reviewer['email'],runtime_store.password_hash(reviewer['password']),'reviewer'))
            conn.commit()
        finally: conn.close()
        directory.mkdir(parents=True)
        grant = validation_budget.authorize(args.schema,operator='user-authorized-20261022',
            reason=args.reason,expires_at=args.expires_at)
        config = {'schema':args.schema,'validation_id':grant,'reviewer':reviewer,'customer':customer,
            'photos':{'claims':[str(args.claims_photo.resolve())],
                'underwriting':[str(p.resolve()) for p in args.underwriting_photo]},
            'runtime_dir':str(directory),'response_dir':str(directory/'responses'),
            'api':'http://127.0.0.1:8001','ui':'http://127.0.0.1:5173',
            'expires_at':args.expires_at,'created_at':datetime.now(timezone.utc).isoformat()}
        config_path.write_text(json.dumps(config,indent=2),encoding='utf8')
        print(json.dumps({'schema':args.schema,'application_ceiling':37,'task_allowance':30,
            'underwriting_evidence_available':bool(args.underwriting_photo),'generation_requests':0}))
        return
    config = json.loads(config_path.read_text(encoding='utf8'))
    if args.operation == 'close':
        validation_budget.close(config['validation_id'],args.reason)
        print(json.dumps({'grant_closed':True,'generation_requests':0})); return
    os.environ['FRAUDLENS_PG_SCHEMA'] = config['schema']
    conn = db.connect('postgresql')
    try:
        conn.execute('BEGIN TRANSACTION READ ONLY')
        job = runtime_store.get_job(conn,args.run_id)
        case = db.get_case(conn,args.case_id)
        if not job or job['case_id'] != args.case_id or not case or case.agent_type != args.kind:
            raise SystemExit('The exact API-created case/run/type was not found.')
    finally: conn.rollback(); conn.close()
    validation_budget.bind_job(config['validation_id'],config['schema'],job,args.kind)
    print(json.dumps({'bound_run':args.run_id,'case_id':args.case_id,'kind':args.kind,'generation_requests':0}))


if __name__ == '__main__': main()
