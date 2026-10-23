"""Small DB-API bridge for the application's parameterized SQL.

Domain code retains qmark parameters and sqlite3.Row's name/position access.
Only parameter markers are translated here; dialect SQL lives at its call site.
PostgreSQL schemas are installed explicitly, never from an HTTP request.
"""
from collections.abc import Sequence
import atexit
import hashlib
import logging
import os
import re
import threading

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

_pools = {}
_pool_lock = threading.Lock()


class _PoolLogFilter(logging.Filter):
    def filter(self, record):
        # Pool worker threads can otherwise log raw libpq connection errors.
        record.msg = 'PostgreSQL pool connection warning; check backend database readiness/configuration.'
        record.args = ()
        record.exc_info = None
        return True


logging.getLogger('psycopg.pool').addFilter(_PoolLogFilter())


class Row(Sequence):
    def __init__(self, names, values):
        self.names, self.values = names, values

    def __getitem__(self, key):
        return self.values[self.names.index(key)] if isinstance(key, str) else self.values[key]

    def __len__(self):
        return len(self.values)

    def keys(self):
        return self.names


def row_factory(cursor):
    names = tuple(c.name for c in cursor.description) if cursor.description else ()
    return lambda values: Row(names, values)


def parameters(query):
    """Translate qmarks outside SQL literals/comments; escape psycopg percent.

No values are interpolated. Dollar quoted blocks belong in migration scripts,
which execute without parameters and do not pass through this function.
"""
    tokens = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/)", query)
    return ''.join(part.replace('%', '%%').replace('?', '%s') if i % 2 == 0
                   else part.replace('%', '%%') for i, part in enumerate(tokens))


def schema_name():
    value = os.environ.get('FRAUDLENS_PG_SCHEMA', 'fraudlens_pilot')
    if not re.fullmatch(r'fraudlens_[a-z0-9_]{1,48}', value):
        raise ValueError('Use a fraudlens_ prefixed PostgreSQL schema (lowercase letters, numbers, underscores).')
    return value


class Connection:
    dialect = 'postgresql'

    def __init__(self, raw, schema, pool=None):
        self.raw, self.schema, self.pool = raw, schema, pool
        self.closed = False
        self.commit_uncertain = False

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def execute(self, query, params=None):
        try:
            from .timing import span
            with span('database.'+query.lstrip().split(None,1)[0].lower()):
                return self._execute(query, params)
        except psycopg.Error as exc:
            # PostgreSQL DETAIL may include rejected rows, grants or hashes.
            # Preserve the driver exception class/SQLSTATE for callers, while
            # keeping application/server logs free of private values.
            raise type(exc)('PostgreSQL operation failed (' + type(exc).__name__ + ').') from None

    def _execute(self, query, params=None):
        command = query.lstrip().split(None, 1)[0].upper()
        if query.strip().upper() == 'BEGIN IMMEDIATE':
            query = 'BEGIN'
        if command == 'BEGIN':
            with self.raw.pipeline():
                cursor = self.raw.execute(query)
                self._configure_transaction()
            return cursor
        query = parameters(query) if params is not None else query
        if not self.in_transaction:
            writing = command in {'INSERT','UPDATE','DELETE'}
            try:
                # Send setup/read/commit together. Separate network waits per
                # SET/BEGIN made cloud-backed evidence/queue requests unusable.
                # Writes retain their transaction until the caller commits.
                with self.raw.pipeline():
                    self.raw.execute('BEGIN')
                    self._configure_transaction()
                    cursor = self.raw.execute(query, params)
                    if not writing:
                        self.raw.execute('COMMIT')
                return cursor
            except BaseException:
                if not writing:
                    self.rollback()
                raise
        return self.raw.execute(query, params)

    def _configure_transaction(self):
        # Supabase may default to shorter textual floats. Round-trip every
        # SQLite binary64 value exactly, including historical confidences.
        self.raw.execute("""SELECT set_config('search_path',%s,true),
            set_config('statement_timeout','60s',true),set_config('lock_timeout','15s',true),
            set_config('idle_in_transaction_session_timeout','90s',true),
            set_config('extra_float_digits','3',true)""",
            (sql.Identifier(self.schema).as_string(self.raw)+',pg_catalog',))

    def executemany(self, query, rows):
        if not self.in_transaction:
            self.execute('BEGIN')
        with self.raw.cursor() as cursor:
            cursor.executemany(parameters(query), rows)

    def commit(self):
        try:
            self.raw.commit()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            # The server may have committed before the connection disappeared.
            # Never remove evidence on the assumption that rollback succeeded.
            self.commit_uncertain = True
            raise type(exc)('PostgreSQL commit confirmation unavailable; preserve evidence and retry the same submission key.') from None

    def rollback(self):
        if self.raw.closed:
            return
        try:
            self.raw.rollback()
        except psycopg.Error:
            self.raw.close()  # do not mask the original authentication/HTTP error

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.raw.rollback()
        except psycopg.Error:
            self.raw.close()
        if self.pool:
            self.pool.putconn(self.raw)
        else:
            self.raw.close()


def connect():
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        raise ValueError('DATABASE_URL is required for PostgreSQL; keep credentials server-side.')
    schema = schema_name()
    from psycopg_pool import ConnectionPool, PoolTimeout
    key = hashlib.sha256(dsn.encode()).hexdigest()
    with _pool_lock:
        pool = _pools.get(key)
        if pool is None or pool.closed:
            settings = psycopg.conninfo.conninfo_to_dict(dsn)
            # TLS is required for a remote server; retain stronger verification
            # when explicitly configured. Never print the connection settings.
            local = settings.get('host') in {'localhost','127.0.0.1','::1'}
            if not local and settings.get('sslmode') in {'disable','allow','prefer'}:
                raise ValueError('Remote PostgreSQL requires sslmode=require or certificate verification.')
            size = int(os.environ.get('FRAUDLENS_PG_POOL_SIZE','8'))
            if not 3 <= size <= 16:
                raise ValueError('FRAUDLENS_PG_POOL_SIZE must be 3-16 (leader, API and job connections).')
            pool = ConnectionPool(dsn, min_size=0, max_size=size, timeout=15,
                max_waiting=32, max_idle=120, reconnect_timeout=15,
                check=ConnectionPool.check_connection,
                name='fraudlens-backend', open=True,
                kwargs={'autocommit':True,'row_factory':row_factory,'prepare_threshold':None,
                        'connect_timeout':15,'application_name':'fraudlens_backend',
                        'keepalives_idle':30,'keepalives_interval':10,'keepalives_count':3,
                        'sslmode':settings.get('sslmode') or ('disable' if local else 'require')})
            _pools[key] = pool
    try:
        raw = pool.getconn()
    except (psycopg.Error, PoolTimeout):
        raise psycopg.OperationalError('PostgreSQL connection unavailable; check server-side configuration.') from None
    return Connection(raw, schema, pool)


def close_pools():
    with _pool_lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()


atexit.register(close_pools)


def verify_schema(conn):
    """Fail closed on an uninstalled schema; no surprise DDL or empty pilot."""
    if getattr(conn, '_schema_verified', False):
        return
    try:
        rows = [tuple(r) for r in conn.execute('SELECT version,checksum FROM schema_migrations ORDER BY version')]
    except psycopg.errors.UndefinedTable:
        raise RuntimeError('PostgreSQL schema is not installed. Run scripts/migrate_postgres.py first.') from None
    from .pg_migrations import versions
    if rows != versions():
        raise RuntimeError('PostgreSQL migration version/checksum mismatch; run scripts/upgrade_postgres.py after a private backup. Do not rewrite applied migrations.')
    conn._schema_verified = True
