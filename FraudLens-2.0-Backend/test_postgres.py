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
from src import api, db, ingest, pg_migrations, runtime_store, vehicle_gate
from test_pilot_workflow import auth, submit, photo
import test_pilot_workflow as workflows
import test_durable_pilot as durable

pytestmark = pytest.mark.skipif(os.environ.get('FRAUDLENS_TEST_POSTGRES') != '1',
                                reason='Real PostgreSQL tests require explicit opt-in.')

# Run the same contracts on both engines. The OS-lock-specific assertion has
# a cluster-leadership counterpart below. Test names/parametrization remain
# visible in pytest output rather than hiding checks in one aggregate test.
for module in (workflows, durable):
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
        yield name
    finally:
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
            sql.Identifier(pg_schema, t) for t in pg_migrations.TABLES)))
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
            data={'agent_type':'claims','policy_number':'POL-123'},
            files={'images':('photo.png',photo(),'image/png')})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(send,range(2)))
    assert [r.status_code for r in results]==[201,201]
    assert results[0].json()==results[1].json()
    with runtime_store.connection('postgresql') as conn:
        assert conn.execute('SELECT count(*) FROM cases').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM api_jobs').fetchone()[0]==1


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
        assert status=={'tables':22,'rls_enabled':22,'browser_privilege_violations':0}
        for table in (*pg_migrations.TABLES,'schema_migrations','migration_imports'):
            for operation in ('SELECT * FROM {} LIMIT 0','DELETE FROM {} WHERE false'):
                with pytest.raises(db.DatabaseError):
                    with conn.raw.transaction():
                        conn.raw.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                        conn.raw.execute(sql.SQL(operation).format(sql.Identifier(conn.schema,table)))


def test_postgres_report_history_is_immutable(client):
    receipt=submit(client).json();headers=auth(client)
    assert client.post('/v1/cases/'+receipt['case_id']+'/action',headers=headers,json={'action':'approve'}).status_code==200
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


def test_postgres_parameters_preserve_literals_and_percent(client):
    with runtime_store.connection('postgresql') as conn:
        row=conn.execute("SELECT ? AS value, 'why? 50%' AS literal, ? AS other -- ? remains comment\n", ('private? % value',42)).fetchone()
        assert tuple(row)==('private? % value','why? 50%',42)
        assert dict(row)=={'value':'private? % value','literal':'why? 50%','other':42}


def test_postgres_pool_return_rolls_back_uncommitted_changes(client):
    receipt=submit(client).json()
    conn=db.connect('postgresql')
    conn.execute("UPDATE cases SET status='uncommitted' WHERE case_id=?",(receipt['case_id'],))
    conn.close();conn.close()  # idempotent close, no double return
    with runtime_store.connection('postgresql') as other:
        assert db.get_case(other,receipt['case_id']).status=='open'
        assert not other.in_transaction


def test_postgres_import_refuses_changed_existing_target(client):
    import sqlite3
    from scripts.migrate_postgres import inventory,apply
    receipt=submit(client).json()
    source=sqlite3.connect(':memory:')
    try:
        db.init_db(source);runtime_store.init(source);source.commit()
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
