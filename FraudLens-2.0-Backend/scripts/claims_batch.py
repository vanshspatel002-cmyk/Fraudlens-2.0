"""Claims-only historical plan / one-at-a-time resumable enqueue. No model calls.

Default is read-only. --enqueue-next is a separate operator action; it preserves
case status, human decisions, findings and earlier snapshots. Never used during
normal-operation qualification. Underwriting is deliberately excluded.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
import time
import shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.diagnose_gemini import process_environment
from src.pilot_config import load_pilot_environment, apply_pilot_environment
from src import db, session_budget
from scripts.audit_analysis_history import audit
from scripts.reprocess_history import enqueue_one


def plan(records, batch_id):
    entries=[];unique_misses=set()
    for record in records:
        if record['case_type']!='claims':continue
        evidence=record.get('evidence') or []
        misses=sum(not e.get('cache_compatible') for e in evidence)
        if record['eligible_evidence']:
            unique_misses.update(e['content_hash'] for e in evidence if not e.get('cache_compatible'))
        entries.append(dict(case_id=record['case_id'],run_id=str(uuid.uuid4()),
            evidence_hashes=sorted({e['content_hash'] for e in evidence}),
            eligible=record['eligible_evidence'],blockers=record.get('blockers',[]),
            before=record['analysis_state'],human_action=record.get('latest_human_action'),
            compatible_images=len(evidence)-misses,minimum_calls=misses+1,
            # Full per-case ceiling includes image correction, retries and agent.
            maximum_calls=16, evidence_count=len(evidence),outcome='not_enqueued'))
    return dict(version='claims-retrospective-2026-10-22-v1',batch_id=batch_id,
        created_at=datetime.now(timezone.utc).isoformat(),state='dry_run',concurrency=1,
        cases=entries,minimum_calls=len(unique_misses)+sum(e['eligible'] for e in entries),
        unique_vision_misses=len(unique_misses),
        maximum_calls=16*sum(e['eligible'] for e in entries),
        note='Estimates require compatible caches at execution time; tool turns vary. Cases needing more than 16 calls will remain partial. No underwriting or historical execution is authorized by creating this manifest.')


def write(path,payload):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(payload,indent=2));temporary.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--process-id',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--enqueue-next',action='store_true');p.add_argument('--operator');p.add_argument('--reason')
    p.add_argument('--include-reviewed',action='store_true')
    args=p.parse_args();env=load_pilot_environment(process_environment(args.process_id));apply_pilot_environment(env)
    conn=db.connect('postgresql');directory=args.output.resolve();checkpoint=directory/'claims-plan.json'
    try:
        if not args.enqueue_next:
            summary=audit(conn,directory)  # immutable point-in-time, private hash inventory
            records=json.loads((directory/'cases.json').read_text())
            payload=plan(records,'claims-'+uuid.uuid4().hex[:12]);payload['schema']=env['FRAUDLENS_PG_SCHEMA']
            write(checkpoint,payload);print(json.dumps({'summary':summary,'plan_cases':len(payload['cases']),
                'estimated_minimum_calls':payload['minimum_calls'],'estimated_maximum_calls':payload['maximum_calls'],'historical_jobs_enqueued':0}));return
        if not args.operator or not args.reason:p.error('Enqueue requires explicit --operator and --reason')
        payload=json.loads(checkpoint.read_text());assert payload['schema']==env['FRAUDLENS_PG_SCHEMA']
        if conn.execute("SELECT 1 FROM api_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('Another job is active; wait before resuming this batch.')
        # Checkpoint from actual jobs. A failure stops further work for inspection.
        for entry in payload['cases']:
            row=conn.execute('SELECT payload FROM api_jobs WHERE job_id=?',(entry['run_id'],)).fetchone()
            if row:
                job=json.loads(row[0]);entry['outcome']=job['status']
                if job['status'] in {'failed','interrupted','completed_partial'}:
                    write(checkpoint,payload);raise ValueError('Prior batch job failed/interrupted; diagnose before resuming.')
                if job['status']=='completed':
                    events=conn.execute("SELECT details FROM audit_log WHERE case_id=? AND event_type='case_adjudicated' ORDER BY rowid DESC",(entry['case_id'],)).fetchall()
                    detail=next((json.loads(r[0]) for r in events if json.loads(r[0]).get('run_id')==entry['run_id']),{})
                    entry['assessment_sufficient']=(detail.get('assessment_explanation') or {}).get('coverage',{}).get('material_complete')
                    if entry['assessment_sufficient'] is not True:
                        write(checkpoint,payload);raise ValueError('Prior batch execution completed with incomplete/unrecorded assessment; inspect before continuing.')
        write(checkpoint,payload)
        next_entry=next((e for e in payload['cases'] if e['eligible'] and e['outcome']=='not_enqueued'
                         and (args.include_reviewed or not e['human_action'])),None)
        if not next_entry:print('No eligible pending claims; reviewed cases require explicit inclusion.');return
        state=session_budget._change(lambda s:s);op=state.get('operation') or {}
        if op.get('mode')!='normal' or op.get('circuit') or (op.get('task') or {}).get('status')=='active':
            raise ValueError('Batch cannot consume an active diagnostic/task allowance or bypass a circuit stop.')
        from src.quota_budget import pacific_quota_day
        today=sum(pacific_quota_day(datetime.fromtimestamp(e['time'],timezone.utc))==pacific_quota_day() for e in state['events'])
        if op['limits']['daily_attempts']-today<next_entry['minimum_calls']:
            raise ValueError('Insufficient daily application headroom for the minimum estimate; leave checkpoint paused.')
        backup=directory/'control-backups'/str(time.time_ns());backup.mkdir(parents=True)
        def snapshot(s):
            from src import quota_budget
            with quota_budget._lock(Path(env['GEMINI_QUOTA_BUDGET'])):
                (backup/'session.json').write_text(json.dumps(s,indent=2))
                shutil.copy2(env['GEMINI_QUOTA_BUDGET'],backup/'quota.json')
        session_budget._change(snapshot)
        # One explicitly chosen future run, using normal daily/case limits.
        def activate(s):
            s['operation'].setdefault('batch_runs',[]).append(next_entry['run_id'])
            s['operation']['audit'].append(dict(action='historical_run_activated',
                operator=args.operator,reason=args.reason,run_id=next_entry['run_id'],batch_id=payload['batch_id']))
        session_budget._change(activate)
        conn.rollback()
        job=enqueue_one(conn,payload,next_entry)
        next_entry['outcome']=job['status'];payload['state']='one_job_enqueued';write(checkpoint,payload)
        print(json.dumps({'case_id':next_entry['case_id'],'new_run_id':job['job_id'],'status':job['status'],
                          'message':'Wait for terminal state, inspect it, then explicitly repeat --enqueue-next.'}))
    finally:conn.close()


if __name__=='__main__':main()
