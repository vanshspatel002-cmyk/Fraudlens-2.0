"""Consistent backup and non-overwriting restore of a stopped/local pilot.

SQLite backup API includes committed WAL content. Stop evidence writers while
copying files. Backup directories include private .env files; keep them local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def snapshot_database(source,target_path):
    target_path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);target=sqlite3.connect(target_path)
    try:
        conn.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Database integrity failed: '+str(source))
    finally:conn.close();target.close()


def backup(root,destination):
    root=root.resolve();destination=destination.resolve()
    if destination.exists():raise SystemExit('Use a new backup directory; existing backups are never overwritten.')
    if destination.is_relative_to(root):raise SystemExit('Place the backup outside the backend directory.')
    destination.mkdir(parents=True)
    for source in root.glob('*.db'):
        snapshot_database(source,destination/source.name)
    for source in root.iterdir():
        if source.is_file() and (source.name.endswith('.bak') or source.name.endswith('.db.old')):
            shutil.copy2(source,destination/source.name)
    for name in ('data','outputs','models','.env'):
        source=root/name
        if source.is_dir():
            shutil.copytree(source,destination/name,ignore=shutil.ignore_patterns('*.db','*.db-wal','*.db-shm','*.worker.lock','*.lock'))
            for database in source.rglob('*.db'):
                snapshot_database(database,destination/database.relative_to(root))
        elif source.is_file():shutil.copy2(source,destination/name)
    files={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
    (destination/'backup_manifest.json').write_text(json.dumps({'files':files},indent=2),encoding='utf-8')
    print('Backup complete:',destination,'files:',len(files))


def restore(source,destination):
    source=source.resolve();destination=destination.resolve()
    if destination.exists():raise SystemExit('Restore only into a new directory. Stop services and review the restored copy before promotion.')
    if destination.is_relative_to(source):raise SystemExit('Restore outside the backup directory.')
    manifest=json.loads((source/'backup_manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        path=(source/name).resolve()
        if not path.is_relative_to(source) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise SystemExit('Backup verification failed: '+name)
    shutil.copytree(source,destination)
    for path in destination.rglob('*.db'):
        conn=sqlite3.connect(path)
        try:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Restored database integrity failure')
        finally:conn.close()
    print('Restore verified:',destination,'files:',len(manifest['files']))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['backup','restore']);parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();globals()[args.operation](args.source,args.destination)
