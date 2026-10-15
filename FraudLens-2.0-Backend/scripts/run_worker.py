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
    if not args.no_warm_ocr:
        from src.checks.plate_ocr import get_reader
        print('Worker OCR warmup: '+('ready' if get_reader() is not None else 'unavailable; checks will report inconclusive'),flush=True)
    worker=DurableWorker(api.DB_PATH,api._run_pipeline)
    worker.start()
    print('Durable worker started; waiting for database leadership/jobs.',flush=True)
    try:
        while worker.thread and worker.thread.is_alive():
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logging.getLogger('fraudlens.worker').info('Worker shutdown requested; accepted jobs remain durable.')
    finally:
        worker.stop()
    return 0


if __name__=='__main__':raise SystemExit(main())
