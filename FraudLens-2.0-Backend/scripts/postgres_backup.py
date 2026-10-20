"""Private, repeatable-read logical backup and non-overwriting restore drill.

Application data only; local evidence/config are backed up separately with
pilot_backup.py while writers are stopped. No credentials enter this archive.
Restore always installs a new schema, and verifies every row before commit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from psycopg import sql
from src import db, pg_migrations
from scripts.migrate_postgres import apply, digest_rows, source_digest


def backup(conn,destination):
    if destination.exists():
        raise ValueError('Use a new private backup directory; existing backups are preserved.')
    destination.mkdir(parents=True)
    conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    installed = pg_migrations.installed_versions(conn)
    expected = pg_migrations.versions()
    if not installed or installed != expected[:len(installed)]:
        raise ValueError('Installed schema checksum differs; retain its matching source before backup.')
    tables = (*pg_migrations.TABLES, *pg_migrations.EXTENSION_TABLES) if len(installed) > 1 else pg_migrations.TABLES
    data={}
    for table in tables:
        names=[r[0] for r in conn.execute('''SELECT column_name FROM information_schema.columns
            WHERE table_schema=? AND table_name=? ORDER BY ordinal_position''',(conn.schema,table))]
        names=['rowid',*[n for n in names if n!='rowid']]
        query=sql.SQL('SELECT {} FROM {} ORDER BY rowid').format(sql.SQL(',').join(map(sql.Identifier,names)),sql.Identifier(table))
        rows=[list(r) for r in conn.raw.execute(query)]
        data[table]={'columns':names,'rows':rows,'digest':digest_rows(rows)}
    history=[[r[0],r[1],r[2].isoformat()] for r in conn.execute('SELECT source_digest,counts,imported_at FROM migration_imports ORDER BY imported_at')]
    conn.rollback()
    payload={'format':2,'schema_versions':installed,
             'created_at':datetime.now(timezone.utc).isoformat(),'source_schema':conn.schema,
             'source_digest':source_digest(data),'data':data,'import_history':history}
    content=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    (destination/'application.json').write_bytes(content)
    (destination/'manifest.json').write_text(json.dumps({'sha256':hashlib.sha256(content).hexdigest(),
        'counts':{t:len(d['rows']) for t,d in data.items()}},indent=2),encoding='utf-8')
    print('Consistent PostgreSQL backup created; tables:',len(data))


def restore(conn,source):
    if pg_migrations.schema_exists(conn):
        raise ValueError('Restore requires a new schema. Existing PostgreSQL data is never overwritten.')
    content=(source/'application.json').read_bytes()
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(content).hexdigest()!=manifest['sha256']:
        raise ValueError('Backup checksum failed.')
    payload=json.loads(content)
    if payload['format'] == 1:
        compatible = payload['schema_version']=='001' and payload['schema_checksum']==pg_migrations.checksum()
        tables = pg_migrations.TABLES
    elif payload['format'] == 2:
        installed = [tuple(row) for row in payload['schema_versions']]
        compatible = bool(installed) and installed == pg_migrations.versions()[:len(installed)]
        tables = (*pg_migrations.TABLES, *pg_migrations.EXTENSION_TABLES) if len(installed) > 1 else pg_migrations.TABLES
    else:
        compatible = False
        tables = ()
    if not compatible:
        raise ValueError('Unsupported backup schema/version; retain its matching source migration.')
    data=payload['data']
    if set(data)!=set(tables) or source_digest(data)!=payload['source_digest']:
        raise ValueError('Backup inventory digest failed.')
    for entry in data.values():
        if digest_rows(entry['rows'])!=entry['digest']:
            raise ValueError('Backup row digest failed.')
    result=apply(conn,data,payload['import_history'])
    print(json.dumps({'operation':'restored into a new schema and verified',**result},indent=2))


def main():
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','restore'])
    parser.add_argument('directory',type=Path)
    parser.add_argument('--schema',required=True)
    args=parser.parse_args()
    os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    conn=None
    try:
        conn=db.connect('postgresql')
        globals()[args.operation](conn,args.directory.resolve())
        return 0
    except Exception as exc:
        print('Backup/restore failed:',type(exc).__name__)
        if isinstance(exc,(ValueError,RuntimeError)):print(str(exc))
        return 1
    finally:
        if conn:conn.close()


if __name__=='__main__':raise SystemExit(main())
