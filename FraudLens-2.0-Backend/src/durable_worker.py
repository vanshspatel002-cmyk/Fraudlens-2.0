"""Durable single-host SQLite worker with Windows/POSIX process exclusion."""
import os
from pathlib import Path
import threading
import logging
from . import runtime_store

log = logging.getLogger('fraudlens.worker')


class DurableWorker:
    def __init__(self, path, execute):
        self.path, self.execute = path, execute
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = None

    def start(self):
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
                        self.execute(job['job_id'], job['case_id'])
                    else:
                        self.stop_event.wait(0.5)
                except Exception:
                    log.exception('Worker error; queue retained')
                    self.stop_event.wait(2)
        finally:
            if self.lock:
                self.lock.close(); self.lock = None

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        # A running model call keeps its lock until it exits or process death.
