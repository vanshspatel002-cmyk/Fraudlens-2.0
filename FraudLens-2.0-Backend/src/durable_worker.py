"""SQLite process exclusion; PostgreSQL cluster leadership and fenced runs."""
import os
from pathlib import Path
import threading
import logging
from . import db, runtime_store

log = logging.getLogger('fraudlens.worker')


class DurableWorker:
    def __init__(self, path, execute):
        self.path, self.execute = path, execute
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = None

    def start(self):
        if self.path == 'postgresql':
            self.thread = threading.Thread(target=self._postgres_loop, name='fraudlens-pg-worker', daemon=True)
            self.thread.start()
            return True
        self.lock = open(str(Path(self.path).resolve()) + '.worker.lock', 'a+b')
        self.lock.seek(0,2)
        if self.lock.tell() == 0:self.lock.write(b'0');self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close(); self.lock = None
            log.info('Another process owns the worker; this API process only enqueues.')
            return False
        with runtime_store.connection(self.path) as conn:
            runtime_store.interrupt_jobs(conn)
        self.thread = threading.Thread(target=self._loop, name='fraudlens-worker', daemon=True)
        self.thread.start()
        return True

    def _loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    with runtime_store.connection(self.path) as conn:
                        job = runtime_store.claim_next(conn)
                    if job:
                        with runtime_store.execution(job):
                            self.execute(job['job_id'], job['case_id'])
                    else:
                        self.stop_event.wait(0.5)
                except Exception as exc:
                    log.error('Worker error (%s); queue retained', type(exc).__name__)
                    self.stop_event.wait(2)
        finally:
            if self.lock:
                self.lock.close(); self.lock = None

    def _postgres_loop(self):
        # A transaction advisory lock is held on a dedicated connection, so
        # transaction poolers pin its backend and process death releases it.
        # This intentionally runs one leader per schema, not parallel workers.
        # Each claimed run also has a fencing token checked in its result tx.
        while not self.stop_event.is_set():
            guard = None
            heartbeat = None
            heartbeat_stop = threading.Event()
            ownership_lost = threading.Event()
            try:
                guard = db.connect(self.path)
                guard.execute('BEGIN')
                timeout=int(os.environ.get('FRAUDLENS_PG_LEADER_TIMEOUT_SECONDS','120'))
                if not 10 <= timeout <= 300:
                    raise ValueError('PostgreSQL leader timeout must be 10-300 seconds.')
                guard.execute("SELECT set_config('idle_in_transaction_session_timeout',?,true)",(str(timeout)+'s',))
                acquired = guard.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))',
                                         ('fraudlens-worker:' + guard.schema,)).fetchone()[0]
                if not acquired:
                    guard.rollback()
                    self.stop_event.wait(2)
                    continue
                self.lock = guard
                epoch=guard.execute('SELECT txid_current()').fetchone()[0]
                def keep_leadership(connection=guard,stopping=heartbeat_stop,lost=ownership_lost,interval=min(5,timeout/3)):
                    while not stopping.wait(interval):
                        try:
                            connection.execute('SELECT 1')
                        except Exception:
                            lost.set()
                            return
                heartbeat = threading.Thread(target=keep_leadership,name='fraudlens-pg-heartbeat',daemon=True)
                heartbeat.start()
                with runtime_store.connection(self.path) as conn:
                    runtime_store.interrupt_jobs(conn,before_epoch=epoch)
                while not self.stop_event.is_set():
                    if ownership_lost.is_set():
                        raise runtime_store.ExecutionLost('PostgreSQL leadership connection was lost.')
                    guard.execute('SELECT 1')  # detect a lost database session
                    with runtime_store.connection(self.path) as conn:
                        job = runtime_store.claim_next(conn,leader_epoch=epoch)
                    if job:
                        with runtime_store.execution(job,ownership_lost):
                            self.execute(job['job_id'], job['case_id'])
                        try:
                            guard.execute('SELECT 1')
                        except Exception:
                            ownership_lost.set()
                        if ownership_lost.is_set():
                            with runtime_store.connection(self.path) as conn:
                                runtime_store.release_lost_claim(conn,job)
                    else:
                        self.stop_event.wait(1)
            except Exception as exc:
                log.error('PostgreSQL worker error (%s); queue retained', type(exc).__name__)
                self.stop_event.wait(2)
            finally:
                heartbeat_stop.set()
                if heartbeat:
                    heartbeat.join(timeout=2)
                self.lock = None
                if guard:
                    guard.close()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        # A running model call keeps its lock until it exits or process death.
