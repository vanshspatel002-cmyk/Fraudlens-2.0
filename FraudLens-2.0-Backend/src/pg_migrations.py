"""Explicit, transactional PostgreSQL schema installation and private grants."""
import hashlib
from pathlib import Path
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1] / 'migrations' / 'postgresql'
TABLES = ('claimants', 'cases', 'findings', 'perception_records', 'image_artifacts',
          'agent_decisions', 'images', 'audit_log', 'cache_entries', 'admin_actions',
          'admin_sessions', 'api_jobs', 'organizations', 'reviewer_accounts',
          'applicant_grants', 'evidence_requests', 'evidence_batches',
          'submission_receipts', 'processing_results', 'report_snapshots')
EXTENSION_TABLES = ('customer_accounts', 'customer_sessions', 'case_owners', 'report_artifacts')
MIGRATIONS = (('001', '001_initial.sql'), ('002', '002_customer_workflow.sql'), ('003','003_partial_review.sql'))


def checksum(version='001'):
    # Git may check out CRLF on Windows. Hash canonical migration text so
    # an unchanged migration verifies identically on Windows and Linux.
    names = dict(MIGRATIONS)
    return hashlib.sha256((ROOT / names[version]).read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def versions():
    return [(version, checksum(version)) for version, _ in MIGRATIONS]


def installed_versions(conn):
    return [tuple(row) for row in conn.execute('SELECT version,checksum FROM schema_migrations ORDER BY version')]


def upgrade(conn):
    """Apply only checked additive versions within the caller's transaction."""
    installed = installed_versions(conn)
    expected = versions()
    if not installed or installed != expected[:len(installed)]:
        raise RuntimeError('PostgreSQL migration version/checksum mismatch; applied migrations are never rewritten.')
    applied = []
    for version, filename in MIGRATIONS[len(installed):]:
        conn.raw.execute((ROOT / filename).read_text(encoding='utf-8'), prepare=False)
        conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES (?,?)', (version, checksum(version)))
        applied.append(version)
    secure(conn)
    return applied


def schema_exists(conn):
    return bool(conn.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (conn.schema,)).fetchone())


def install(conn):
    """Must be inside the import's transaction; never amend an existing schema."""
    if schema_exists(conn):
        raise ValueError('Target schema already exists; validate it or choose a new schema. No data changed.')
    conn.raw.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(conn.schema)))
    conn.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(conn.schema)))
    conn.raw.execute('''CREATE TABLE schema_migrations (
        version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    conn.raw.execute('''CREATE TABLE migration_imports (
        source_digest TEXT PRIMARY KEY, counts TEXT NOT NULL,
        imported_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    conn.raw.execute((ROOT / '001_initial.sql').read_text(encoding='utf-8'), prepare=False)
    conn.raw.execute('INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)', ('001', checksum()))
    upgrade(conn)


def secure(conn):
    """No policies grant browser roles access. Backend owner bypass is explicit.

    Do not change public schema grants, project API settings or other schemas.
    Even accidental API exposure of this schema must not reveal its objects.
    """
    schema = sql.Identifier(conn.schema)
    roles = ['PUBLIC'] + [r[0] for r in conn.raw.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')")]
    for role in roles:
        target = sql.SQL('PUBLIC') if role == 'PUBLIC' else sql.Identifier(role)
        conn.raw.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM {}').format(schema, target))
        for kind in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            conn.raw.execute(sql.SQL('REVOKE ALL ON ALL {} IN SCHEMA {} FROM {}').format(sql.SQL(kind), schema, target))
            conn.raw.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON {} FROM {}').format(schema, sql.SQL(kind), target))
    available = {r[0] for r in conn.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=?', (conn.schema,))}
    for table in (*TABLES, *EXTENSION_TABLES, 'schema_migrations', 'migration_imports'):
        if table not in available:
            continue
        conn.raw.execute(sql.SQL('ALTER TABLE {}.{} ENABLE ROW LEVEL SECURITY').format(schema, sql.Identifier(table)))


def security_status(conn):
    rows = conn.execute('''SELECT c.relname,c.relrowsecurity,
        has_schema_privilege('anon', n.oid, 'USAGE') AS anon_schema,
        has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS anon_table,
        has_schema_privilege('authenticated', n.oid, 'USAGE') AS auth_schema,
        has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS auth_table
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=? AND c.relkind='r' ''', (conn.schema,)).fetchall()
    return {'tables': len(rows), 'rls_enabled': sum(bool(r[1]) for r in rows),
            'browser_privilege_violations': sum(any(r[i] for i in range(2,6)) for r in rows)}
