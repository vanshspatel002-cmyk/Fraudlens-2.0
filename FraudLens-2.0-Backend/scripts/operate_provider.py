"""Explicit offline controls, aligned with a running pilot process; no AI calls."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.diagnose_gemini import process_environment
from src.pilot_config import load_pilot_environment, apply_pilot_environment
from src import operating_policy, session_budget


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['status','migrate','pause','resume','finish-task','configure'])
    p.add_argument('--process-id', type=int, required=True)
    p.add_argument('--operator');p.add_argument('--reason');p.add_argument('--expected-attempts', type=int)
    p.add_argument('--daily-attempts',type=int);p.add_argument('--case-attempts',type=int);p.add_argument('--agent-turns',type=int)
    a = p.parse_args()
    env = load_pilot_environment(process_environment(a.process_id));apply_pilot_environment(env)
    if a.action != 'status':
        if not a.operator or not a.reason:p.error('--operator and --reason are required')
        # Locked consistent copy of BOTH controls before any state mutation.
        from src import quota_budget
        backup = Path(env['FRAUDLENS_LIVE_LEDGER']).parent/'control_backups'/str(time.time_ns())
        backup.mkdir(parents=True)
        def save(state):
            (backup/'session.json').write_text(json.dumps(state,indent=2))
            # These commands require idle consumers, verified below. Quota lock
            # also protects against a reservation while the copy is taken.
            with quota_budget._lock(Path(env['GEMINI_QUOTA_BUDGET'])):
                shutil.copy2(env['GEMINI_QUOTA_BUDGET'], backup/'quota.json')
            if a.action!='pause' and any(e['outcome']=='reserved' for e in state['events']):raise ValueError('Provider operation in flight; pause consumers first.')
        session_budget._change(save)
        from src import db
        conn = db.connect('postgresql')
        try:
            busy = conn.execute("SELECT COUNT(*) FROM api_jobs WHERE status IN ('running','queued')").fetchone()[0]
            if busy and a.action not in {'pause','resume'}:raise ValueError('Queued/running jobs exist; finish or explicitly pause the worker before changing controls.')
        finally:conn.close()
        if a.action == 'migrate':
            operating_policy.migrate(schema=env['FRAUDLENS_PG_SCHEMA'],expected_attempts=a.expected_attempts,
                                     operator=a.operator,reason=a.reason)
        elif a.action=='configure':operating_policy.configure({key:getattr(a,key) for key in ['daily_attempts','case_attempts','agent_turns'] if getattr(a,key) is not None},operator=a.operator,reason=a.reason)
        else:operating_policy.control(a.action,operator=a.operator,reason=a.reason)
    state = session_budget._change(lambda s: s)
    print(json.dumps({'attempts':state['attempts'],'historical_stop':state['stopped'],
                      'operation':state.get('operation')},indent=2))


if __name__ == '__main__':main()
