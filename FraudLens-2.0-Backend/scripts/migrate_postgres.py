"""Non-overwriting, single-demo SQLite import. No credentials or records printed.

Dry-run is the default. --apply installs/imports only into a nonexistent private
schema, atomically. Repeats validate exact data; they never merge/upsert history.
--validate compares all source columns/rowids; it never writes target data.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from psycopg import sql
from src import db, pg_migrations


def digest_rows(rows):
    value = hashlib.sha256()
    for row in rows:
        value.update(json.dumps(list(row), ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
        value.update(b'\n')
    return value.hexdigest()


@contextmanager
def source_snapshot(path):
    with tempfile.TemporaryDirectory(prefix='fraudlens_sqlite_import_') as temp:
        original = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        snapshot = sqlite3.connect(str(Path(temp) / 'source.db'))
        try:
            original.backup(snapshot)
            original.close()
            if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed; no target changes.')
            if snapshot.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('SQLite has foreign key violations; no target changes.')
            yield snapshot
        finally:
            original.close()
            snapshot.close()


def inventory(source):
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables != set(pg_migrations.TABLES):
        raise ValueError('Unexpected source table set; inspect the selected demo schema before importing.')
    data = {}
    for table in pg_migrations.TABLES:
        names = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
        rows = source.execute(f'SELECT rowid,* FROM "{table}" ORDER BY rowid').fetchall()
        data[table] = {'columns': ['rowid', *names], 'rows': rows, 'digest': digest_rows(rows)}
    return data


def source_digest(data):
    return hashlib.sha256(json.dumps({t: {'columns': d['columns'], 'digest': d['digest']}
                                     for t, d in data.items()}, sort_keys=True).encode()).hexdigest()


def validate(conn, data):
    db.init_db(conn)
    if conn.execute('SELECT checksum FROM schema_migrations WHERE version=?', ('001',)).fetchone()[0] != pg_migrations.checksum():
        raise ValueError('Installed schema checksum differs; no migration will be rewritten.')
    mismatched = []
    counts = {}
    for table, entry in data.items():
        cols = sql.SQL(',').join(map(sql.Identifier, entry['columns']))
        query = sql.SQL('SELECT {} FROM {}.{} ORDER BY rowid').format(cols, sql.Identifier(conn.schema), sql.Identifier(table))
        rows = conn.raw.execute(query).fetchall()
        counts[table] = len(rows)
        if digest_rows(rows) != entry['digest']:
            mismatched.append(table)
    if mismatched:
        raise ValueError('Target differs from the source in tables: ' + ', '.join(mismatched) + '. No existing target data changed.')
    # PG checks all inserted FKs. Also verify IDs inside run-specific JSON lists.
    issues = conn.execute('''SELECT COUNT(*) FROM processing_results r WHERE
        EXISTS (SELECT 1 FROM jsonb_array_elements_text(r.finding_ids::jsonb) f(id)
            LEFT JOIN findings x ON x.finding_id=f.id AND x.case_id=r.case_id WHERE x.finding_id IS NULL)
        OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(r.image_ids::jsonb) i(id)
            LEFT JOIN images x ON x.image_id=i.id AND x.case_id=r.case_id WHERE x.image_id IS NULL)''').fetchone()[0]
    if issues:
        raise ValueError('Run-specific finding/evidence references failed validation.')
    security = pg_migrations.security_status(conn)
    if security['browser_privilege_violations'] or security['rls_enabled'] != security['tables']:
        raise ValueError('Private schema grants/RLS validation failed.')
    return {'counts': counts, 'all_rows_and_rowids_match': True,
            'run_relationship_issues': issues, 'security': security}


def apply(conn, data, import_history=()):
    counts = {t: len(d['rows']) for t, d in data.items()}
    digest = source_digest(data)
    conn.execute('BEGIN')
    try:
        db.lock_key(conn, 'migration:' + conn.schema)
        if pg_migrations.schema_exists(conn):
            result = validate(conn, data)
            conn.rollback()
            return {**result, 'operation': 'existing target validated; no writes'}
        pg_migrations.install(conn)
        conn.execute("SET LOCAL statement_timeout='0'")
        # FK order, deliberately independent from SQLite creation order.
        order = ('claimants','cases','findings','perception_records','image_artifacts',
                 'agent_decisions','images','audit_log','cache_entries','admin_actions',
                 'admin_sessions','api_jobs','organizations','reviewer_accounts',
                 'applicant_grants','evidence_requests','evidence_batches',
                 'submission_receipts','processing_results','report_snapshots')
        order = (*order, *(table for table in pg_migrations.EXTENSION_TABLES if table in data))
        for table in order:
            entry = data[table]
            available = db.columns(conn, table)
            if not set(entry['columns']) <= available:
                raise ValueError('Unsupported source columns in ' + table + '; schema migration required.')
            query = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(table),
                sql.SQL(',').join(map(sql.Identifier, entry['columns'])))
            with conn.raw.cursor() as cursor:
                with cursor.copy(query) as copy:
                    for row in entry['rows']:
                        copy.write_row(row)
            maximum = max((r[0] for r in entry['rows']), default=0)
            sequence = conn.raw.execute('SELECT pg_get_serial_sequence(%s,%s)', (conn.schema + '.' + table, 'rowid')).fetchone()[0]
            conn.raw.execute('SELECT setval(%s,%s,%s)', (sequence, max(maximum, 1), maximum > 0))
        conn.execute('INSERT INTO migration_imports(source_digest,counts) VALUES (?,?)', (digest, json.dumps(counts)))
        for record in import_history:
            conn.execute('INSERT INTO migration_imports(source_digest,counts,imported_at) VALUES (?,?,?) ON CONFLICT(source_digest) DO NOTHING',record)
        result = validate(conn, data)
        conn.commit()
        return {**result, 'operation': 'imported and verified', 'source_digest': digest}
    except BaseException:
        conn.rollback()
        raise


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'outputs/pilot_validation/demo.db')
    parser.add_argument('--schema', default=os.environ.get('FRAUDLENS_PG_SCHEMA', 'fraudlens_pilot'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--validate', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    # Explicitly constrain this tool to the configured rollback/demo database.
    configured = os.environ.get('FRAUDLENS_SQLITE_ROLLBACK') or os.environ.get('FRAUDLENS_DB')
    if configured in (None, 'postgresql'):
        configured = str(ROOT / 'outputs/pilot_validation/demo.db')
    if args.source.resolve() != Path(configured).resolve() or not args.source.is_file():
        parser.error('Source must be the existing configured SQLite demo/rollback database. Research databases are not imported.')
    if args.output and args.output.exists():
        parser.error('Use a new output file; verification records are never overwritten.')
    os.environ['FRAUDLENS_PG_SCHEMA'] = args.schema
    conn = None
    try:
        with source_snapshot(args.source) as source:
            data = inventory(source)
        conn = db.connect('postgresql')
        if args.apply:
            result = apply(conn, data)
        elif args.validate:
            conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            result = {**validate(conn, data), 'operation': 'validated read only'}
            conn.rollback()
        else:
            result = {'operation': 'dry run; no writes', 'source_integrity': 'ok',
                      'counts': {t: len(d['rows']) for t,d in data.items()},
                      'source_digest': source_digest(data),
                      'target_schema_exists': pg_migrations.schema_exists(conn)}
        result['schema'] = args.schema
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # Driver DETAIL can contain private rows/URLs. Output only type and
        # safe application validation messages, never a provider/driver dump.
        print('Migration failed:', type(exc).__name__)
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc))
        print('No existing database was replaced or merged. Inspect configuration/schema and retry safely.')
        return 1
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
