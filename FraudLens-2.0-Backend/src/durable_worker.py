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
            try:
                guard = db.connect(self.path)
                guard.execute('BEGIN')
                guard.execute("SET LOCAL idle_in_transaction_session_timeout='0'")
                acquired = guard.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))',
                                         ('fraudlens-worker:' + guard.schema,)).fetchone()[0]
                if not acquired:
                    guard.rollback()
                    self.stop_event.wait(2)
                    continue
                with runtime_store.connection(self.path) as conn:
                    runtime_store.interrupt_jobs(conn)
                self.lock = guard
                while not self.stop_event.is_set():
                    guard.execute('SELECT 1')  # detect a lost database session
                    with runtime_store.connection(self.path) as conn:
                        job = runtime_store.claim_next(conn)
                    if job:
                        with runtime_store.execution(job):
                            self.execute(job['job_id'], job['case_id'])
                    else:
                        self.stop_event.wait(1)
            except Exception as exc:
                log.error('PostgreSQL worker error (%s); queue retained', type(exc).__name__)
                self.stop_event.wait(2)
            finally:
                self.lock = None
                if guard:
                    guard.close()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        # A running model call keeps its lock until it exits or process death.
