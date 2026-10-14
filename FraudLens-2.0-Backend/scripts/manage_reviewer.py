"""Local administrator account provisioning; passwords never enter arguments/logs."""
import argparse
from getpass import getpass
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import api, db, runtime_store
from src.models import AuditEvent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default=api.DB_PATH)
    parser.add_argument('--email',required=True)
    parser.add_argument('--role',choices=['admin','reviewer','viewer'],default='reviewer')
    parser.add_argument('--disable',action='store_true')
    args=parser.parse_args();email=args.email.strip().lower()
    if '@' not in email:raise SystemExit('Provide an email address.')
    conn=db.connect(args.db);db.init_db(conn);runtime_store.init(conn)
    try:
        if args.disable:
            changed=conn.execute('UPDATE reviewer_accounts SET enabled=0 WHERE email=?',(email,)).rowcount
            if not changed:raise SystemExit('Account not found; no changes made.')
        else:
            password=getpass('New password (at least 12 characters): ')
            if len(password)<12 or password!=getpass('Confirm password: '):raise SystemExit('Password did not meet the requirement or confirmation did not match.')
            conn.execute('''INSERT INTO reviewer_accounts(email,password_hash,role) VALUES (?,?,?)
                ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role,enabled=1''',
                (email,runtime_store.password_hash(password),args.role))
        conn.execute('DELETE FROM admin_sessions WHERE actor=?',(email,))
        db.log_audit_event(conn,AuditEvent(event_type='reviewer_account_provisioned',details={
            'actor':'local_administrator','email':email,'role':args.role,'enabled':not args.disable}))
        conn.commit();print('Account updated; prior sessions revoked:',email)
    finally:conn.close()


if __name__=='__main__':main()
