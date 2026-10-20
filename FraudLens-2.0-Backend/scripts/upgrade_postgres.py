"""Explicit additive upgrades; no case import, merge, deletion or model call.

Stop API/worker writers and make a fresh private logical/filesystem backup
before --apply. Default mode inspects installed migration checksums read-only.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src import db, pg_migrations


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', default=os.environ.get('FRAUDLENS_PG_SCHEMA', 'fraudlens_pilot'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.environ['FRAUDLENS_PG_SCHEMA'] = args.schema
    conn = None
    try:
        conn = db.connect('postgresql')
        conn.execute('BEGIN' if args.apply else 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if args.apply:
            db.lock_key(conn, 'migration:' + conn.schema)
        installed = pg_migrations.installed_versions(conn)
        expected = pg_migrations.versions()
        if not installed or installed != expected[:len(installed)]:
            raise RuntimeError('Migration checksums differ; preserve data and investigate. No migration was rewritten.')
        pending = [version for version, _ in expected[len(installed):]]
        if args.apply:
            applied = pg_migrations.upgrade(conn)
            security = pg_migrations.security_status(conn)
            if security['browser_privilege_violations'] or security['rls_enabled'] != security['tables']:
                raise RuntimeError('Private schema permission validation failed; upgrade rolled back.')
            conn.commit()
            print('Additive upgrade committed. Versions applied:', ','.join(applied) or 'none')
            print('Private tables checked:', security['tables'])
        else:
            conn.rollback()
            print('Read-only inspection. Pending versions:', ','.join(pending) or 'none')
        return 0
    except Exception as exc:
        if conn:
            conn.rollback()
        print('Upgrade failed:', type(exc).__name__)
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc))
        return 1
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
