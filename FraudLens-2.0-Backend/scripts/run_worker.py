"""Dedicated local processing process, using the existing durable queue/pipeline.

Native model imports/inference must not stall FastAPI's interpreter or cloud
evidence requests. OCR warmup precedes leadership, so cold imports cannot
expire a claimed job. No provider probe, policy change or synthetic reply.
"""
import argparse
import logging
import os
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import api, db, runtime_store
from src.durable_worker import DurableWorker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-warm-ocr',action='store_true')
    args=parser.parse_args()
    ledger=os.environ.get('FRAUDLENS_LIVE_LEDGER')
    if not ledger or not Path(ledger).is_file():
        raise SystemExit('The preserved FRAUDLENS_LIVE_LEDGER is required; do not create a fresh allowance.')
    with runtime_store.connection(api.DB_PATH) as conn:
        db.init_db(conn)
    from src.runtime_readiness import write_worker_status
    heartbeat_stop=threading.Event();health={'ocr':None,'worker':None}
    def heartbeat():
        while not heartbeat_stop.is_set():
            current=health['worker'];leader=bool(current and current.lock)
            state='warming' if health['ocr'] is None else 'degraded' if not health['ocr'] else 'ready' if leader else 'waiting_for_leadership'
            try:write_worker_status(state=state,ocr_ready=health['ocr'],leader=leader)
            except OSError:logging.getLogger('fraudlens.worker').warning('Worker readiness write unavailable.')
            heartbeat_stop.wait(2)
    threading.Thread(target=heartbeat,name='fraudlens-worker-readiness',daemon=True).start()
    if not args.no_warm_ocr:
        from src.checks.plate_ocr import get_reader
        health['ocr']=get_reader() is not None
        print('Worker OCR warmup: '+('ready' if health['ocr'] else 'unavailable; checks will report inconclusive'),flush=True)
    else:health['ocr']=False
    worker=DurableWorker(api.DB_PATH,api._run_pipeline)
    health['worker']=worker
    worker.start()
    print('Durable worker started; waiting for database leadership/jobs.',flush=True)
    try:
        while worker.thread and worker.thread.is_alive():
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logging.getLogger('fraudlens.worker').info('Worker shutdown requested; accepted jobs remain durable.')
    finally:
        heartbeat_stop.set()
        worker.stop()
    return 0


if __name__=='__main__':raise SystemExit(main())
