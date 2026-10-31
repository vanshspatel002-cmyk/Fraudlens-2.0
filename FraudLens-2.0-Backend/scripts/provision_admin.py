"""Idempotent administrator account provisioning.

Supplies the initial password via private environment variable or prompt;
never prints or hardcodes credentials in code, logs or git.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import db, runtime_store
from src.models import AuditEvent


def provision_schema(conn, email: str, password_hash: str, role: str = 'admin', raw_password: str = ''):
    # Remove known typo accounts if present
    typo_email = '23bt04122@gafcuniversity.ac.in'
    try:
        conn.execute('DELETE FROM reviewer_accounts WHERE email=?', (typo_email,))
    except Exception:
        pass

    # Ensure organization exists
    try:
        if not conn.execute("SELECT 1 FROM organizations WHERE organization_id='local'").fetchone():
            conn.execute("INSERT INTO organizations (organization_id, name) VALUES ('local', 'Local FraudLens pilot')")
    except Exception:
        pass

    existing = conn.execute('SELECT email, password_hash, role, enabled FROM reviewer_accounts WHERE email=?', (email,)).fetchone()
    if existing:
        # Check if already has correct role, enabled, and password matches
        if existing['role'] == role and existing['enabled'] == 1 and raw_password and runtime_store.password_matches(raw_password, existing['password_hash']):
            return 'unchanged'
        conn.execute(
            'UPDATE reviewer_accounts SET password_hash=?, role=?, enabled=1 WHERE email=?',
            (password_hash, role, email)
        )
        action = 'updated'
    else:
        conn.execute(
            '''INSERT INTO reviewer_accounts(email, password_hash, role, organization_id, enabled)
               VALUES (?, ?, ?, 'local', 1)''',
            (email, password_hash, role)
        )
        action = 'created'

    try:
        db.log_audit_event(conn, AuditEvent(
            event_type='reviewer_account_provisioned',
            details={'actor': 'system_provision', 'email': email, 'role': role, 'action': action}
        ))
    except Exception:
        pass
    return action


def main():
    parser = argparse.ArgumentParser(description='Durable idempotent admin provisioning')
    parser.add_argument('--email', default=os.environ.get('ADMIN_PROVISION_EMAIL', '23bt04122@gsfcuniversity.ac.in'))
    parser.add_argument('--role', default='admin', choices=['admin', 'reviewer', 'viewer'])
    args = parser.parse_args()

    email = args.email.strip().lower()
    raw_password = os.environ.get('ADMIN_INITIAL_PASSWORD') or os.environ.get('FRAUDLENS_INITIAL_ADMIN_PASSWORD')
    if not raw_password:
        from getpass import getpass
        raw_password = getpass('Enter initial admin password: ')
        if not raw_password:
            raise SystemExit('Password is required.')

    p_hash = runtime_store.password_hash(raw_password)

    # 1. Provision into PostgreSQL schemas
    schemas = ['fraudlens_pilot', 'fraudlens_validation_panel_20261022']
    configured_schema = os.environ.get('FRAUDLENS_PG_SCHEMA')
    if configured_schema and configured_schema not in schemas:
        schemas.append(configured_schema)

    for schema in schemas:
        try:
            os.environ['FRAUDLENS_PG_SCHEMA'] = schema
            conn = db.connect('postgresql')
            try:
                db.init_db(conn)
                action = provision_schema(conn, email, p_hash, args.role, raw_password=raw_password)
                conn.commit()
                print(f"PostgreSQL [{schema}]: admin account {email} is {action}.")
            finally:
                conn.close()
        except Exception as e:
            print(f"PostgreSQL [{schema}] provision notice: {e}")

    # 2. Provision into SQLite rollback/demo databases if present
    for sqlite_file in ['outputs/pilot_validation/demo.db', 'fraudlens.db']:
        path = Path(sqlite_file)
        if path.is_file():
            try:
                conn = db.connect(str(path))
                try:
                    db.init_db(conn)
                    runtime_store.init(conn)
                    action = provision_schema(conn, email, p_hash, args.role, raw_password=raw_password)
                    conn.commit()
                    print(f"SQLite [{sqlite_file}]: admin account {email} is {action}.")
                finally:
                    conn.close()
            except Exception as e:
                print(f"SQLite [{sqlite_file}] provision notice: {e}")


if __name__ == '__main__':
    main()
