"""Real PostgreSQL regression suite in a newly created, disposable schema.

Opt-in: FRAUDLENS_TEST_POSTGRES=1. DATABASE_URL stays in backend .env.
Uploads/models in API contract tests are explicit mocks. The database, locks,
transactions, roles, recovery and immutable history use actual PostgreSQL.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from src import api, db, ingest, pg_migrations, runtime_store, vehicle_gate,photo_admission
from test_pilot_workflow import auth, submit, photo,initial_files
import test_pilot_workflow as workflows
import test_durable_pilot as durable
import test_customer_workflow as customers
import test_report_pdf as reports

pytestmark = pytest.mark.skipif(os.environ.get('FRAUDLENS_TEST_POSTGRES') != '1',
                                reason='Real PostgreSQL tests require explicit opt-in.')

# Run the same contracts on both engines. The OS-lock-specific assertion has
# a cluster-leadership counterpart below. Test names/parametrization remain
# visible in pytest output rather than hiding checks in one aggregate test.
for module in (workflows, durable, customers, reports):
    for name in dir(module):
        if name.startswith('test_') and name != 'test_exclusive_worker_execution_and_shutdown':
            globals()[name] = getattr(module, name)


@pytest.fixture(scope='module')
def pg_schema():
    previous = os.environ.get('FRAUDLENS_PG_SCHEMA')
    name = 'fraudlens_test_' + uuid.uuid4().hex
    os.environ['FRAUDLENS_PG_SCHEMA'] = name
    conn = db.connect('postgresql')
    try:
        conn.execute('BEGIN')
        pg_migrations.install(conn)
        conn.commit()
        conn.close()
        yield name
    finally:
        # Do not hold a borrowed connection idle for the entire long suite.
        conn=db.connect('postgresql')
        conn.rollback()
        # Only this fixture's newly allocated namespace may be removed.
        assert conn.schema == name and name.startswith('fraudlens_test_') and len(name) == 47
        conn.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
        conn.close()
        if previous is None:
            os.environ.pop('FRAUDLENS_PG_SCHEMA', None)
        else:
            os.environ['FRAUDLENS_PG_SCHEMA'] = previous


@pytest.fixture
def client(pg_schema, tmp_path, monkeypatch):
    assert pg_schema.startswith('fraudlens_test_')
    with runtime_store.connection('postgresql') as conn:
        assert conn.schema == pg_schema
        conn.raw.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(sql.SQL(',').join(
            sql.Identifier(pg_schema, t) for t in (*pg_migrations.TABLES,*pg_migrations.EXTENSION_TABLES))))
        conn.execute("INSERT INTO organizations(organization_id,name) VALUES ('local','Isolated test organization')")
    monkeypatch.setenv('FRAUDLENS_WORKER_ENABLED','0')
    monkeypatch.setenv('FRAUDLENS_WARM_MODELS','0')
    monkeypatch.setattr(api,'DB_PATH','postgresql')
    monkeypatch.setattr(api,'UPLOAD_DIR',tmp_path/'uploads')
    monkeypatch.setenv('ADMIN_EMAIL','reviewer@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD_SHA256',hashlib.sha256(b'correct-password').hexdigest())
    monkeypatch.delenv('EVIDENCE_SERVICE_TOKEN',raising=False)
    monkeypatch.setattr(api,'RATE_LIMIT_SUBMIT_MAX',100)
    api._RATE_LIMITS.clear();api._JOBS.clear()
    monkeypatch.setattr(api,'_run_pipeline',lambda *args:None)
    score=SimpleNamespace(accepted=True,to_dict=lambda:{'accepted':True})
    monkeypatch.setattr(vehicle_gate,'classify_uploads',lambda paths,names:[score for _ in paths])
    monkeypatch.setattr(ingest,'_default_embedder',SimpleNamespace(embed=lambda path:[1.,0.]))
    from src import photo_admission
    monkeypatch.setattr(photo_admission,'infer',lambda path,slot:('accepted','Controlled semantic fixture',[1.,0.],{}))
    photo_admission._cache.clear()
    with TestClient(api.app) as value:
        yield value


def test_postgres_concurrent_claims_and_skip_locked(client):
    receipts=[submit(client).json() for _ in range(3)]
    held=db.connect('postgresql')
    try:
        held.execute('BEGIN')
        held.execute('SELECT job_id FROM api_jobs WHERE job_id=? FOR UPDATE',(receipts[0]['job_id'],))
        barrier=threading.Barrier(2)
        def claim(_):
            with runtime_store.connection('postgresql') as conn:
                barrier.wait(timeout=20)
                return runtime_store.claim_next(conn)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=list(pool.map(claim,range(2)))
        assert {j['job_id'] for j in jobs}=={r['job_id'] for r in receipts[1:]}
        assert all(j['attempts']==1 for j in jobs)
    finally:
        held.rollback();held.close()
    with runtime_store.connection('postgresql') as conn:
        assert runtime_store.claim_next(conn)['job_id']==receipts[0]['job_id']
        assert runtime_store.claim_next(conn) is None


def test_postgres_concurrent_submission_replays_one_acceptance(client):
    key=str(uuid.uuid4())
    def send(_):
        return client.post('/v1/cases',headers={'Idempotency-Key':key},
            data={'agent_type':'claims','policy_number':'POL-123','photo_slots':list(photo_admission.SLOTS['claims'])},
            files=initial_files())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(send,range(2)))
    assert [r.status_code for r in results]==[201,201]
    assert results[0].json()==results[1].json()
    with runtime_store.connection('postgresql') as conn:
        assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM api_jobs').fetchone()[0]==1


def test_postgres_camera_exif_padding_intake_roundtrip(client):
    import io,piexif
    from PIL import Image
    from pathlib import Path
    buffer=io.BytesIO()
    Image.open(io.BytesIO(photo('red'))).save(buffer,format='JPEG',exif=piexif.dump({'Exif':{piexif.ExifIFD.UserComment:b'ASCII\x00\x00\x00camera comment\x00'}}))
    original=buffer.getvalue();files=initial_files();files[0]=('images',('camera.jpg',original,'image/jpeg'))
    response=client.post('/v1/cases',data={'agent_type':'claims','vehicle_registration':'MH12EX1203','policy_number':'FICTIONAL-EXIF','photo_slots':list(photo_admission.SLOTS['claims'])},files=files)
    assert response.status_code==201,response.text
    with runtime_store.connection('postgresql') as conn:
        images=db.get_images_for_case(conn,response.json()['case_id'])
        image=next(i for i in images if i.content_hash==hashlib.sha256(original).hexdigest())
        assert Path(image.path).read_bytes()==original
        assert image.exif['Exif']['UserComment']=='ASCIIcamera comment'


def test_postgres_advisory_leader_and_worker_failover(client):
    from src.durable_worker import DurableWorker
    one=submit(client).json();seen=[];done=threading.Event()
    guard=db.connect('postgresql')
    guard.execute('BEGIN')
    key='fraudlens-worker:'+guard.schema
    assert guard.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))',(key,)).fetchone()[0]
    def execute(job_id,case_id):
        seen.append(job_id)
        api._set_job(job_id,status='completed',stage='complete')
        done.set()
    first=DurableWorker('postgresql',execute);second=DurableWorker('postgresql',execute)
    first.start();second.start()
    try:
        time.sleep(1)
        assert seen==[]
        guard.close()  # simulates loss/death of the previous leader connection
        assert done.wait(40)
        assert seen==[one['job_id']]
    finally:
        first.stop();second.stop();guard.close()
        # Ensure neither worker outlives schema cleanup/fixture truncation.
        first.thread.join(25);second.thread.join(25)
        assert not first.thread.is_alive() and not second.thread.is_alive()


def test_postgres_stale_attempt_cannot_commit_findings_or_progress(client,monkeypatch):
    from src import orchestrator
    from src.agent.production_policy import production_policy
    receipt=submit(client).json()
    with runtime_store.connection('postgresql') as conn:
        old=runtime_store.claim_next(conn)
        runtime_store.interrupt_jobs(conn);conn.commit()
        current=runtime_store.claim_next(conn)
    assert old['execution_token']!=current['execution_token']
    monkeypatch.setattr(orchestrator,'run_checks',lambda *a,**kw:[])
    with runtime_store.execution(old):
        with pytest.raises(runtime_store.ExecutionLost):
            api._set_job(receipt['job_id'],status='failed')
        with runtime_store.connection('postgresql') as conn:
            with pytest.raises(runtime_store.ExecutionLost):
                orchestrator.process_case(conn,receipt['case_id'],policy=production_policy('claims'),use_agent=False,run_id=receipt['job_id'])
            conn.rollback()
    with runtime_store.connection('postgresql') as conn:
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='running'
        assert conn.execute('SELECT count(*) FROM findings').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM agent_decisions').fetchone()[0]==0


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_postgres_browser_roles_cannot_read_or_write_any_table(client,role):
    with runtime_store.connection('postgresql') as conn:
        status=pg_migrations.security_status(conn)
        table_count=len(pg_migrations.TABLES)+len(pg_migrations.EXTENSION_TABLES)+2
        assert status=={'tables':table_count,'rls_enabled':table_count,'browser_privilege_violations':0}
        for table in (*pg_migrations.TABLES,*pg_migrations.EXTENSION_TABLES,'schema_migrations','migration_imports'):
            column='version' if table=='schema_migrations' else 'source_digest' if table=='migration_imports' else 'rowid'
            operations=('SELECT * FROM {} LIMIT 0','DELETE FROM {} WHERE false',
                        'INSERT INTO {} DEFAULT VALUES','UPDATE {} SET '+column+'='+column+' WHERE false')
            for operation in operations:
                with conn.raw.transaction():
                    conn.raw.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                    assert conn.raw.execute('SELECT current_user').fetchone()[0]==role
                    with pytest.raises(db.DatabaseError):
                        conn.raw.execute(sql.SQL(operation).format(sql.Identifier(conn.schema,table)))


def test_postgres_report_history_is_immutable(client):
    receipt=submit(client).json();headers=auth(client)
    basis=workflows.complete_for_review(client,receipt['case_id'],headers)
    assert client.post('/v1/cases/'+receipt['case_id']+'/action',headers=headers,json={**basis,'action':'approve'}).status_code==200
    with runtime_store.connection('postgresql') as conn:
        original=[tuple(r) for r in conn.execute('SELECT snapshot_id,payload FROM report_snapshots ORDER BY rowid')]
        assert original
        with pytest.raises(db.DatabaseError):
            conn.execute("UPDATE report_snapshots SET payload='{}'")
        conn.rollback()
        with pytest.raises(db.DatabaseError):
            conn.execute('DELETE FROM report_snapshots')
        conn.rollback()
        assert original==[tuple(r) for r in conn.execute('SELECT snapshot_id,payload FROM report_snapshots ORDER BY rowid')]


def test_additive_customer_upgrade_preserves_rows_and_is_idempotent(monkeypatch):
    """Actual PostgreSQL DDL in this test's own namespace, never the pilot."""
    name='fraudlens_test_'+uuid.uuid4().hex
    monkeypatch.setenv('FRAUDLENS_PG_SCHEMA',name)
    conn=db.connect('postgresql')
    migrations=pg_migrations.MIGRATIONS
    try:
        conn.execute('BEGIN')
        monkeypatch.setattr(pg_migrations,'MIGRATIONS',migrations[:1])
        pg_migrations.install(conn)
        conn.execute("INSERT INTO claimants(claimant_id,name,phone,bank_account,address,created_at) VALUES (?,?,?,?,?,?)",
                     ('preserved','Fictional Applicant','0000000000','fictional','Example address','2026-01-01T00:00:00+00:00'))
        original=[tuple(row) for row in conn.execute('SELECT * FROM claimants ORDER BY rowid')]
        monkeypatch.setattr(pg_migrations,'MIGRATIONS',migrations)
        assert pg_migrations.upgrade(conn)==['002']
        assert pg_migrations.upgrade(conn)==[]
        assert [tuple(row) for row in conn.execute('SELECT * FROM claimants ORDER BY rowid')]==original
        assert pg_migrations.installed_versions(conn)==pg_migrations.versions()
        for table in pg_migrations.EXTENSION_TABLES:
            assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        assert pg_migrations.security_status(conn)['browser_privilege_violations']==0
        conn.commit()
    finally:
        monkeypatch.setattr(pg_migrations,'MIGRATIONS',migrations)
        conn.rollback()
        assert conn.schema==name and name.startswith('fraudlens_test_') and len(name)==47
        conn.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
        conn.close()


def test_postgres_parameters_preserve_literals_and_percent(client):
    with runtime_store.connection('postgresql') as conn:
        row=conn.execute("SELECT ? AS value, 'why? 50%' AS literal, ? AS other -- ? remains comment\n", ('private? % value',42)).fetchone()
        assert tuple(row)==('private? % value','why? 50%',42)
        assert dict(row)=={'value':'private? % value','literal':'why? 50%','other':42}


def test_postgres_backup_restores_customer_ownership_sessions_and_pdf(client,tmp_path,monkeypatch):
    """Full format-2 restore, isolated schemas and explicit binary PDF fixture."""
    from scripts.postgres_backup import backup,restore
    receipt=submit(client).json()
    source=db.connect('postgresql')
    archive=tmp_path/'private-logical-backup'
    try:
        source.execute('BEGIN')
        source.execute('''INSERT INTO customer_accounts(customer_id,email,password_hash,name,created_at)
            VALUES (?,?,?,?,?)''',('customer-test','restore@example.com','fixture-hash','Fictional Restore',time.time()))
        source.execute('INSERT INTO customer_sessions(token_hash,customer_id,credential_hash,expires_at) VALUES (?,?,?,?)',
                       ('fixture-session','customer-test','fixture-hash',time.time()+3600))
        source.execute('INSERT INTO case_owners(case_id,customer_id,created_at) VALUES (?,?,?)',
                       (receipt['case_id'],'customer-test',time.time()))
        source.execute('INSERT INTO report_snapshots(snapshot_id,case_id,payload,created_at) VALUES (?,?,?,?)',
                       ('fixture-report',receipt['case_id'],'{}',time.time()))
        source.execute('''INSERT INTO report_artifacts(snapshot_id,renderer_version,pdf_base64,sha256,created_at)
            VALUES (?,?,?,?,?)''',('fixture-report','fixture-renderer','JVBERi1maXh0dXJl','fixture-digest',time.time()))
        source.commit()
        backup(source,archive)
    finally:
        source.close()
    name='fraudlens_test_'+uuid.uuid4().hex
    monkeypatch.setenv('FRAUDLENS_PG_SCHEMA',name)
    target=db.connect('postgresql')
    try:
        restore(target,archive)
        assert target.execute('SELECT customer_id FROM case_owners WHERE case_id=?',(receipt['case_id'],)).fetchone()[0]=='customer-test'
        assert target.execute('SELECT COUNT(*) FROM customer_sessions').fetchone()[0]==1
        assert tuple(target.execute('SELECT renderer_version,pdf_base64,sha256 FROM report_artifacts WHERE snapshot_id=?',
                                    ('fixture-report',)).fetchone())==('fixture-renderer','JVBERi1maXh0dXJl','fixture-digest')
        with pytest.raises(ValueError,match='new schema'):
            restore(target,archive)
    finally:
        target.rollback()
        assert target.schema==name and name.startswith('fraudlens_test_') and len(name)==47
        target.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
        target.close()


def test_postgres_pool_return_rolls_back_uncommitted_changes(client):
    receipt=submit(client).json()
    conn=db.connect('postgresql')
    conn.execute("UPDATE cases SET status='uncommitted' WHERE case_id=?",(receipt['case_id'],))
    conn.close();conn.close()  # idempotent close, no double return
    with runtime_store.connection('postgresql') as other:
        assert db.get_case(other,receipt['case_id']).status=='open'
        assert not other.in_transaction


def test_postgres_rollback_after_idle_timeout_discards_connection(client):
    conn=db.connect('postgresql')
    try:
        conn.execute('BEGIN')
        conn.execute("SET LOCAL idle_in_transaction_session_timeout='1s'")
        threading.Event().wait(1.5)
        conn.rollback()
        assert conn.raw.closed
    finally:
        conn.close()
    with runtime_store.connection('postgresql') as replacement:
        assert replacement.execute('SELECT COUNT(*) FROM cases').fetchone()[0]==0


def test_postgres_import_refuses_changed_existing_target(client):
    import sqlite3
    from scripts.migrate_postgres import inventory,apply
    receipt=submit(client).json()
    source=sqlite3.connect(':memory:')
    source.row_factory=sqlite3.Row
    try:
        db.init_db(source);runtime_store.init(source)
        # This importer deliberately targets the frozen pre-customer boundary.
        # New extension data belongs in format-2 backups, not a historical merge.
        for table in reversed(pg_migrations.EXTENSION_TABLES):
            source.execute('DROP TABLE IF EXISTS '+table)
        source.commit()
        incoming=inventory(source)
        with runtime_store.connection('postgresql') as conn:
            before={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in pg_migrations.TABLES}
            with pytest.raises(ValueError,match='Target differs'):
                apply(conn,incoming)
            after={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in pg_migrations.TABLES}
            assert before==after
            assert db.get_case(conn,receipt['case_id']) is not None
    finally:
        source.close()


def test_migration_checksum_is_stable_across_windows_newlines(tmp_path,monkeypatch):
    folder=tmp_path/'migrations';folder.mkdir()
    migration=folder/'001_initial.sql'
    migration.write_bytes(b'SELECT 1;\nSELECT 2;\n')
    monkeypatch.setattr(pg_migrations,'ROOT',folder)
    unix=pg_migrations.checksum()
    migration.write_bytes(b'SELECT 1;\r\nSELECT 2;\r\n')
    assert pg_migrations.checksum()==unix


def test_postgres_worker_requires_preserved_live_ledger(monkeypatch):
    monkeypatch.setattr(api,'DB_PATH','postgresql')
    monkeypatch.setenv('FRAUDLENS_WORKER_ENABLED','1')
    monkeypatch.delenv('FRAUDLENS_LIVE_LEDGER',raising=False)
    with pytest.raises(RuntimeError,match='preserved FRAUDLENS_LIVE_LEDGER'):
        with TestClient(api.app):
            pass


def lose_commit_confirmation(monkeypatch, timing):
    import psycopg
    from psycopg.pq import TransactionStatus
    original=psycopg.Connection.commit
    injected=[]
    def fail_once(raw):
        if not injected and raw.info.transaction_status!=TransactionStatus.IDLE:
            injected.append(True)
            if timing=='after':original(raw)
            raw.close()  # real database connection loss; model calls remain mocked
            raise psycopg.OperationalError('Explicit isolated commit acknowledgement loss')
        return original(raw)
    monkeypatch.setattr(psycopg.Connection,'commit',fail_once)
    return injected


@pytest.mark.parametrize('timing',['before','after'])
def test_postgres_uncertain_submission_preserves_files_and_replays_safely(client,monkeypatch,timing):
    injected=lose_commit_confirmation(monkeypatch,timing)
    key=str(uuid.uuid4())
    def send():
        return client.post('/v1/cases',headers={'Idempotency-Key':key},
            data={'agent_type':'claims','policy_number':'POL-123','photo_slots':list(photo_admission.SLOTS['claims'])},
            files=initial_files())
    first=send()
    assert injected and first.status_code==503
    assert first.json()['code']=='SUBMISSION_SAVE_UNCONFIRMED'
    assert len(list(api.UPLOAD_DIR.rglob('*.png')))==4
    with runtime_store.connection('postgresql') as conn:
        assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==int(timing=='after')
    retry=send()
    assert retry.status_code==201,retry.text
    with runtime_store.connection('postgresql') as conn:
        assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM api_jobs').fetchone()[0]==1
        assert __import__('pathlib').Path(db.get_images_for_case(conn,retry.json()['case_id'])[0].path).is_file()


def test_postgres_uncertain_supplement_preserves_committed_evidence(client,monkeypatch):
    receipt=submit(client).json();durable.finish(receipt['case_id'])
    request_id=durable.request_evidence(client,receipt['case_id'],auth(client))
    injected=lose_commit_confirmation(monkeypatch,'after')
    response=client.post('/v1/cases/'+receipt['case_id']+'/evidence',
        headers={'X-Applicant-Token':receipt['applicant_token']},data={'request_id':request_id},
        files={'images':('requested.png',photo('blue'),'image/png')})
    assert injected and response.status_code==503
    assert response.json()['code']=='EVIDENCE_SAVE_UNCONFIRMED'
    tracked=client.get('/v1/track',headers={'X-Applicant-Token':receipt['applicant_token']},
        params={'case_id':receipt['case_id'],'policy_number':'POL-123'}).json()
    assert tracked['status']=='evidence_received' and tracked['evidence_request'] is None
    with runtime_store.connection('postgresql') as conn:
        paths=[__import__('pathlib').Path(i.path) for i in db.get_images_for_case(conn,receipt['case_id'])]
        assert len(paths)==5 and all(p.is_file() for p in paths)
        assert runtime_store.latest_job(conn,receipt['case_id'])['status']=='queued'


def test_postgres_recovery_epoch_and_release_cannot_reset_newer_work(client):
    receipt=submit(client).json()
    with runtime_store.connection('postgresql') as conn:
        first=runtime_store.claim_next(conn,leader_epoch=200)
        runtime_store.interrupt_jobs(conn,before_epoch=100);conn.commit()
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='running'
        runtime_store.interrupt_jobs(conn,before_epoch=201);conn.commit()
        latest=runtime_store.claim_next(conn,leader_epoch=201)
        assert latest['execution_token']!=first['execution_token']
        runtime_store.release_lost_claim(conn,first);conn.commit()
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='running'
        runtime_store.release_lost_claim(conn,latest);conn.commit()
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='queued'


def test_postgres_lost_heartbeat_fences_progress(client):
    receipt=submit(client).json()
    with runtime_store.connection('postgresql') as conn:job=runtime_store.claim_next(conn)
    lost=threading.Event();lost.set()
    with runtime_store.execution(job,lost):
        with pytest.raises(runtime_store.ExecutionLost,match='leadership'):
            api._set_job(receipt['job_id'],status='completed')
    with runtime_store.connection('postgresql') as conn:
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='running'


def test_postgres_heartbeat_keeps_one_leader_during_long_work(client,monkeypatch):
    from src.durable_worker import DurableWorker
    receipt=submit(client).json();started=threading.Event();release=threading.Event();seen=[]
    monkeypatch.setenv('FRAUDLENS_PG_LEADER_TIMEOUT_SECONDS','10')
    def execute(job_id,case_id):
        seen.append(job_id);started.set()
        assert release.wait(50)
        api._set_job(job_id,status='completed',stage='complete')
    one=DurableWorker('postgresql',execute);two=DurableWorker('postgresql',execute)
    one.start();two.start()
    try:
        assert started.wait(20)
        time.sleep(13)  # exceeds the explicitly shortened test guard timeout
        assert seen==[receipt['job_id']]
        with runtime_store.connection('postgresql') as conn:
            job=runtime_store.get_job(conn,receipt['job_id'])
            assert job['status']=='running' and job['attempts']==1 and job['leader_epoch']>0
        release.set()
    finally:
        release.set();one.stop();two.stop()
        one.thread.join(25);two.thread.join(25)
        assert not one.thread.is_alive() and not two.thread.is_alive()


def test_database_initialization_failure_always_closes_connection(monkeypatch):
    from starlette.requests import Request
    calls=[]
    fake=SimpleNamespace(rollback=lambda:calls.append('rollback'),close=lambda:calls.append('close'))
    monkeypatch.setattr(db,'connect',lambda _:fake)
    def fail(_):raise RuntimeError('Explicit isolated initialization failure')
    monkeypatch.setattr(db,'init_db',fail)
    with pytest.raises(RuntimeError,match='initialization failure'):
        next(api.get_conn(Request({'type':'http','method':'GET'})))
    assert calls==['rollback','close']


def test_postgres_operations_observes_external_database_leader(client):
    headers=auth(client)
    guard=db.connect('postgresql')
    try:
        guard.execute('BEGIN')
        acquired=guard.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))',
            ('fraudlens-worker:'+guard.schema,)).fetchone()[0]
        assert acquired
        info=client.get('/v1/operations',headers=headers).json()
        assert info['worker_leader_in_this_process'] is False
        assert info['database_worker_leader_present'] is True
        guard.rollback()
        assert client.get('/v1/operations',headers=headers).json()['database_worker_leader_present'] is False
    finally:
        guard.close()


def test_postgres_duplicate_snapshot_reads_fresh_evidence_once(client,monkeypatch):
    from src.checks.base import CheckContext
    from src.checks.duplicate import InternalDuplicateCheck
    from src.models import Verdict
    first=submit(client).json()
    second=submit(client).json()
    original=db.get_all_images;loads=[]
    def load(conn):
        loads.append(1)
        return original(conn)
    monkeypatch.setattr(db,'get_all_images',load)
    with runtime_store.connection('postgresql') as conn:
        case=db.get_case(conn,second['case_id'])
        images=db.get_images_for_case(conn,case.case_id)
        check=InternalDuplicateCheck()
        initial=check.run(CheckContext(conn,case,images+images,{}))
        assert len(loads)==1 and len(initial)==2
        assert all(f.verdict is Verdict.CONCERN and f.evidence['images_compared']==1 for f in initial)
    third=submit(client).json()
    with runtime_store.connection('postgresql') as conn:
        case=db.get_case(conn,third['case_id'])
        current=check.run(CheckContext(conn,case,db.get_images_for_case(conn,case.case_id),{}))
        assert len(loads)==2 and current[0].evidence['images_compared']==2
        assert current[0].verdict is Verdict.CONCERN


def test_postgres_retrospective_duplicate_cutoff_excludes_same_case_and_future_evidence(client,tmp_path):
    """Real timestamp SQL and similarity checks, with explicit stored vectors."""
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    import json
    from src.agent import tools
    from src.checks import run_checks
    from src.models import Case, Image, Verdict

    cutoff=datetime(2026,10,20,tzinfo=timezone.utc)
    case=Case(case_id='retrospective-current',claimant_id='fictional',garage_id='UNASSIGNED',
        claim_type='collision',claim_amount=20000,created_at=cutoff)
    image=Image(image_id='current-image',case_id=case.case_id,path=str(tmp_path/'fixture.png'),
        content_hash='1'*64,phash='0'*16,dhash='0'*16,embedding=[1.,0.],created_at=cutoff)
    with runtime_store.connection('postgresql') as conn:
        assert conn.schema.startswith('fraudlens_test_')
        db.insert_case(conn,case);db.save_image(conn,image)
        db.save_image(conn,replace(image,image_id='same-case-image',content_hash='2'*64))
        candidates=(('earlier-case',cutoff-timedelta(days=2),cutoff-timedelta(days=2)),
                    ('future-case',cutoff+timedelta(days=1),cutoff+timedelta(days=1)),
                    ('later-evidence',cutoff-timedelta(days=1),cutoff+timedelta(days=1)))
        for identifier,created,image_created in candidates:
            db.insert_case(conn,replace(case,case_id=identifier,created_at=created))
            db.save_image(conn,replace(image,image_id=identifier+'-image',case_id=identifier,
                content_hash=hashlib.sha256(identifier.encode()).hexdigest(),created_at=image_created))
        conn.commit()
        bound=cutoff.isoformat()
        index=ingest.SimilarityIndex.from_database(conn,case.case_id,bound)
        assert [candidate.image_id for candidate in index.candidates]==['earlier-case-image']
        findings=run_checks(conn,case,['internal_duplicate'],config={'evaluation_cutoff':bound})
        assert len(findings)==2 and all(f.verdict is Verdict.CONCERN for f in findings)
        assert all(f.evidence['matched_case_id']=='earlier-case' and f.evidence['images_compared']==1 for f in findings)
        # A model-supplied wider date cannot override the server's bound.
        widened=tools.call_tool('widen_similarity_search',conn,case,
            {'threshold':.8,'evaluation_cutoff':(cutoff+timedelta(days=10)).isoformat()},evaluation_cutoff=bound)
        assert widened['matches'] and all(m['matched_case_id']=='earlier-case' for m in widened['matches'])
        # Identical hashes alone must not flag an unrelated stored vector.
        conn.execute('UPDATE images SET embedding=? WHERE image_id=?',(json.dumps([0.,1.]),'earlier-case-image'))
        negative=run_checks(conn,case,['internal_duplicate'],config={'evaluation_cutoff':bound})
        assert all(f.verdict is Verdict.PASS and f.evidence['cosine_similarity']==0 for f in negative)


def test_postgres_run_persists_check_diagnostics_explanation_and_provider_provenance(client,monkeypatch):
    """A fenced run uses real PG writes; provider and failing dependency are fixtures."""
    from dataclasses import replace
    import json
    from src import orchestrator
    from src.agent import tools
    from src.agent.production_policy import production_policy
    from src.checks import REGISTRY
    from src.llm import LLMResponse, ToolCall
    from src.models import Verdict

    receipt=submit(client).json()
    def missing_dependency(ctx):raise ImportError('Explicit isolated fixture dependency unavailable')
    monkeypatch.setattr(REGISTRY['c2pa_credentials'],'run',missing_dependency)
    provenance={'session_attempt':42,'requested_model':'offline-fixture','serving_model':'offline-fixture',
                'timestamp':'2026-10-20T00:00:00+00:00'}
    class OfflineProvider:
        calls=0
        def chat(self,*args,**kwargs):
            assert not conn.in_transaction, 'A durable provider turn held tool/cache writes open'
            self.calls+=1
            if self.calls==1:
                return LLMResponse(text='',tool_call=ToolCall('get_claimant_history',{}),
                    raw={'request_provenance':provenance},model='offline-fixture',cached=True,latency_ms=1)
            return LLMResponse(text=json.dumps({'recommendation':'escalate','risk_band':'desk_review',
                'narrative':'Explicit offline fixture: a human must review the original evidence.',
                'findings_cited':[],'requested_artifacts':[]}),tool_call=None,
                raw={'request_provenance':{**provenance,'untrusted_extra':'fixture-opaque-value'}},
                model='offline-fixture',cached=True,latency_ms=1)
    provider=OfflineProvider()
    policy=replace(production_policy('claims'),check_ids=('c2pa_credentials','exif_metadata'))
    with runtime_store.connection('postgresql') as conn:
        assert conn.schema.startswith('fraudlens_test_')
        def cached_history(tool_conn,case,**kwargs):
            db.cache_set(tool_conn,'fixture-agent-tool','history',{'fixture':True})
            assert tool_conn.in_transaction  # The next provider turn must release this write.
            return {'tool':'get_claimant_history','other_case_count':0,'cases':[]}
        monkeypatch.setitem(tools.TOOLS,'get_claimant_history',cached_history)
        job=runtime_store.claim_next(conn)
        assert job['job_id']==receipt['job_id']
        with runtime_store.execution(job):
            decision=orchestrator.process_case(conn,receipt['case_id'],policy,provider,run_id=job['job_id'])
        result=runtime_store.current_result(conn,receipt['case_id'])
        assert result['run_id']==job['job_id'] and result['decision_id']==decision.decision_id
        findings=db.get_findings_for_case(conn,receipt['case_id'])
        failed=next(f for f in findings if f.check_id=='c2pa_credentials')
        assert failed.verdict is Verdict.INCONCLUSIVE and failed.confidence==0
        assert failed.evidence['execution_state']=='failed'
        assert failed.evidence['diagnostic']['stage']=='check:c2pa_credentials'
        assert failed.evidence['diagnostic']['error_category']=='missing_dependency'
        assert failed.evidence['diagnostic']['attempted_network'] is False
        assert next(f for f in findings if f.check_id=='exif_metadata').evidence['execution_state']=='inconclusive'
        event=next(e for e in db.get_audit_events_for_case(conn,receipt['case_id']) if e.event_type=='case_adjudicated')
        explanation=event.details['assessment_explanation']
        assert explanation==decision._assessment_explanation and explanation['run_id']==job['job_id']
        assert explanation['aggregation']['computed_value'] is None
        assert explanation['coverage']['check_states']['c2pa_credentials']=='failed'
        assert set(json.loads(result['finding_ids']))=={f.finding_id for f in findings}
        expected=[{'source':'request_cache','model':'offline-fixture','request_provenance':provenance}]*2
        assert provider.calls==2 and event.details['model_response_sources']==expected
        assert decision._model_response_sources==expected
        assert 'fixture-opaque-value' not in json.dumps(event.details)
        assert db.cache_get(conn,'fixture-agent-tool','history')=={'fixture':True}
