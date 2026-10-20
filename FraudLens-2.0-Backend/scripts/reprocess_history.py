"""Plan/resume explicitly scoped retrospective jobs; never calls a provider.

Dry-run is the default. Apply requires successful real claims+underwriting
validation in the original live ledger and enough remaining authorized calls
for the selected work. It never authorizes recovery or edits either ledger.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import db,runtime_store
from src.models import AuditEvent

ORIGINAL_LEDGER=ROOT/'outputs/pilot_validation/live_calls.json'
TERMINAL={'completed','failed','interrupted'}
SYSTEMIC={'provider_http_error','provider_access_denied','provider_configuration','provider_circuit_open','missing_dependency','database_error','required_perception_unavailable','response_schema_invalid'}


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path,value):
    target=Path(path);temporary=target.with_suffix(target.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');temporary.replace(target)


def run_id(batch_id,case_id):
    return uuid.uuid5(uuid.NAMESPACE_URL,'fraudlens/retrospective/'+batch_id+'/'+case_id).hex


def records_from(path):
    value=read_json(path);records=value if isinstance(value,list) else value.get('cases')
    if not isinstance(records,list):raise ValueError('Use audit cases.json or run-manifest.json.')
    if len({row['case_id'] for row in records})!=len(records):raise ValueError('Audit contains duplicate case IDs.')
    return records


def budget_remaining(ledger,recovery_id=None):
    attempts=ledger.get('attempts')
    if not isinstance(attempts,int) or isinstance(attempts,bool) or attempts<0:raise ValueError('Original request ledger has an invalid attempt count; stop for inspection.')
    remaining=max(0,min(15,max(0,int(os.environ.get('FRAUDLENS_LIVE_LIMIT','15'))))-attempts)
    if ledger.get('stopped'):
        recovery=next((row for row in ledger.get('recoveries',[]) if row.get('recovery_id')==recovery_id),None)
        if not recovery or recovery.get('status')!='validation_authorized':return 0
        remaining=min(remaining,max(0,int(recovery['allowance'])-int(recovery['reserved'])))
    return remaining


def validation_gate(evidence,ledger,ledger_path,recovery_id):
    if not recovery_id:raise ValueError('Apply requires the existing audited recovery ID; no new recovery is authorized here.')
    if Path(evidence.get('ledger','')).resolve()!=Path(ledger_path).resolve():raise ValueError('Validation must reference the original ledger.')
    if evidence.get('recovery_id')!=recovery_id:raise ValueError('Use the same audited recovery ID for validation and retrospective work.')
    recoveries=[row for row in ledger.get('recoveries',[]) if row.get('recovery_id')==recovery_id]
    if len(recoveries)!=1 or recoveries[0].get('status')!='validation_authorized':
        raise ValueError('The existing audited recovery is not currently authorized for validation; retained proof cannot reopen it.')
    def recorded_time(value):
        try:
            if type(value) in (int,float):
                result=float(value)
            elif isinstance(value,str):
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None:raise ValueError()
                result=parsed.timestamp()
            else:raise ValueError()
            if not math.isfinite(result):raise ValueError()
            return result
        except (ValueError,OverflowError,OSError):
            raise ValueError('Validation authorization and request timestamps must be recorded and timezone-qualified.') from None
    authorized_at=recorded_time(recoveries[0].get('validation_authorized_at'))
    if type(ledger.get('attempts')) is not int or ledger['attempts']<0:
        raise ValueError('The original ledger attempt count is invalid.')
    observations=evidence.get('observations')
    if not isinstance(observations,list) or len(observations)!=2 or not all(isinstance(row,dict) for row in observations) or {row.get('workflow') for row in observations}!={'claims','underwriting'}:
        raise ValueError('Apply requires exactly one successful live proof for each workflow.')
    used=set();case_ids=set();run_ids=set()
    for workflow in ('claims','underwriting'):
        row=next(row for row in observations if row.get('workflow')==workflow)
        if not row or row.get('status')!='completed' or row.get('converged') is not True or row.get('vision_status')!='parsed' or row.get('vision_source')!='fresh_provider':
            raise ValueError('Apply requires successful uncached vision and converged live adjudication for both claims and underwriting.')
        case_id,accepted_run=row.get('case_id'),row.get('run_id')
        if not isinstance(case_id,str) or not case_id or not isinstance(accepted_run,str) or not accepted_run or case_id in case_ids or accepted_run in run_ids:
            raise ValueError('Claims and underwriting must identify distinct accepted cases and runs.')
        case_ids.add(case_id);run_ids.add(accepted_run)
        vision,agent=row.get('vision_attempts'),row.get('agent_attempts')
        if not isinstance(vision,list) or not vision or type(row.get('vision_attempt')) is not int or row['vision_attempt']!=vision[0] or not isinstance(agent,list) or not agent:
            raise ValueError('Validation must enumerate every fresh vision and adjudication request.')
        attempts=vision+agent
        if any(type(value) is not int or not 1<=value<=ledger['attempts'] for value in attempts):
            raise ValueError('Validation request attempts must be positive integer calls in the original ledger.')
        if len(set(attempts))!=len(attempts) or used.intersection(attempts):raise ValueError('Claims and underwriting must have distinct validated live requests.')
        for attempt in attempts:
            events=[event for event in ledger.get('events',[]) if type(event.get('attempt')) is int and event['attempt']==attempt]
            if len(events)!=1 or events[0].get('outcome')!='success' or events[0].get('recovery_id')!=recovery_id:
                raise ValueError('Every validation request must be one successful original-ledger call in the existing audited recovery.')
            started,completed=recorded_time(events[0].get('time')),recorded_time(events[0].get('completed_at'))
            if not authorized_at<=started<=completed:
                raise ValueError('A recovery probe or historical request cannot prove fresh authorized validation.')
        used.update(attempts)


def make_plan(records,batch_id,case_ids=(),scope=None,ledger=None,recovery_id=None,compatible=None):
    if not batch_id.strip() or len(batch_id)>100:raise ValueError('Supply a stable batch ID of at most 100 characters.')
    if bool(case_ids)==bool(scope):raise ValueError('Choose explicit case IDs or an explicit claims/underwriting/all scope.')
    wanted=set(case_ids)
    if wanted-set(row['case_id'] for row in records):raise ValueError('Selected case IDs must exist in the audit manifest.')
    chosen=[row for row in records if row['case_id'] in wanted] if wanted else [row for row in records if scope=='all' or row['case_type']==scope]
    if not chosen:raise ValueError('The selected scope contains no audited cases.')
    entries=[];missing_hashes=set();unverified_hashes=set()
    for row in chosen:
        evidence=row.get('evidence') or []
        unverified_hashes.update(item['content_hash'] for item in evidence if item['content_hash'] not in (compatible or {}) and not isinstance(item.get('cache_compatible'),bool))
        valid=bool(row.get('eligible_evidence')) and bool(evidence)
        misses={item['content_hash'] for item in evidence if not (compatible or {}).get(item['content_hash'],item.get('cache_compatible') is True)}
        missing_hashes.update(misses if valid else ())
        entries.append({'case_id':row['case_id'],'case_type':row['case_type'],'run_id':run_id(batch_id,row['case_id']),
            'outcome':'planned' if valid else 'blocked_by_inputs','blockers':row.get('blockers',[]) if not valid else [],
            'evidence_hashes':sorted({item['content_hash'] for item in evidence}),
            'vision_miss_hashes':sorted(misses),'minimum_agent_requests':1 if valid else 0,
            'minimum_requests':1+len(misses) if valid else 0,
            'evaluation_cutoff':row.get('submitted_at'),'prior_human_actions':row.get('human_actions_preserved',0)})
    minimum=sum(row['minimum_agent_requests'] for row in entries)+len(missing_hashes)
    remaining=budget_remaining(ledger,recovery_id) if ledger else 0
    if minimum>remaining:
        for entry in entries:
            if entry['outcome']=='planned':entry['outcome']='budget_deferred'
    return {'format':1,'batch_id':batch_id,'scope':scope or 'explicit_case_ids','created_at':time.time(),
        'cases':entries,'minimum_requests':minimum,'remaining_authorized_requests':remaining,
        'budget_sufficient':minimum<=remaining,'unverified_cache_hashes':len(unverified_hashes),
        'request_estimate_status':'conservative_unverified_cache' if unverified_hashes else 'validated_cache_lower_bound',
        'estimate_note':('Unverified caches are conservatively treated as missing; this is not a measured cache-miss count. ' if unverified_hashes else '')+'One agent request per case plus unique compatible-vision misses. Agent tool/parse turns may need more; the original hard cap remains enforced.',
        'state':'dry_run','concurrency':1,'source_counts':{},'systemic_failures':0}


def current_compatibility(conn,plan):
    from src.perception import perception_record_usable
    result={}
    for entry in plan['cases']:
        for image in db.get_images_for_case(conn,entry['case_id']):
            result[image.content_hash]=perception_record_usable(db.get_perception_record(conn,image.content_hash))
    return result


def enqueue_one(conn,batch,entry):
    """Only additive queue/audit writes. Human outcome and analysis rows stay intact."""
    conn.execute('BEGIN IMMEDIATE');db.lock_case(conn,entry['case_id'])
    existing=runtime_store.get_job(conn,entry['run_id'])
    if existing:
        conn.commit();return existing
    case=db.get_case(conn,entry['case_id'])
    if not case:raise ValueError('Selected case no longer exists.')
    images=db.get_images_for_case(conn,entry['case_id'])
    if sorted({image.content_hash for image in images})!=entry['evidence_hashes']:
        raise ValueError('Evidence changed since the audit; create a new scoped plan.')
    for image in images:
        path=Path(image.path)
        if not path.is_absolute():path=ROOT/path
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=image.content_hash:
            raise ValueError('Evidence is missing or changed; no retrospective job was enqueued.')
    if conn.execute("SELECT 1 FROM api_jobs WHERE case_id=? AND status IN ('queued','running')",(entry['case_id'],)).fetchone():raise ValueError('Another analysis is active for this case.')
    action=db.get_latest_admin_action(conn,entry['case_id'])
    basis={'case_status':case.status,'reviewer_action':action.action.value if action else None,
           'reviewer':action.admin_id if action else None,'reviewed_at':action.timestamp.isoformat() if action else None}
    job=runtime_store.enqueue(conn,entry['case_id'],entry['run_id'])
    job.update(retrospective=True,batch_id=batch['batch_id'],preserve_human_basis=True,prior_human_basis=basis,
               evaluation_cutoff=case.created_at.isoformat(),max_attempts=1)
    runtime_store.save_job(conn,job)
    db.log_audit_event(conn,AuditEvent(event_type='historical_reprocessing_requested',case_id=case.case_id,
        details={'batch_id':batch['batch_id'],'run_id':job['job_id'],'retrospective':True,'prior_human_basis':basis}))
    conn.commit();return job


def update_from_jobs(conn,plan):
    counts=Counter();systemic=0
    for entry in plan['cases']:
        job=runtime_store.get_job(conn,entry['run_id'])
        if not job:continue
        entry['outcome']=job['status']
        detail=job.get('root_failure_detail') or job.get('failure_detail') or {}
        if job['status'] in {'failed','interrupted'}:
            entry['failure_category']=detail.get('error_category') or 'analysis_incomplete'
            if entry['failure_category'] in SYSTEMIC:systemic+=1
            if entry['failure_category']=='provider_quota_or_rate_limit' and entry.get('rate_limit_seen')!=job.get('updated_at'):
                entry['rate_limit_seen']=job.get('updated_at');plan['resume_after']=max(plan.get('resume_after',0),time.time()+30)
        for source,count in (job.get('perception_sources') or {}).items():counts['vision_'+source]+=count
        for response in job.get('adjudication_sources') or []:counts['agent_'+response.get('source','unrecorded')]+=1
    plan['source_counts']=dict(counts);plan['systemic_failures']=systemic


def supervise(conn,plan,checkpoint,ledger_path,validation,recovery_id,*,max_seconds=120,poll_seconds=2,pause_path=None):
    started=time.monotonic();plan['state']='running'
    while True:
        if pause_path and Path(pause_path).exists():plan['state']='paused';break
        if time.monotonic()-started>=max_seconds:plan['state']='paused_time_limit';break
        update_from_jobs(conn,plan)
        if plan['systemic_failures']>=2:plan['state']='stopped_systemic_failure';break
        if plan.get('resume_after',0)>time.time():plan['state']='paused_rate_limit';break
        ledger=read_json(ledger_path);validation_gate(validation,ledger,ledger_path,recovery_id)
        pending=[entry for entry in plan['cases'] if entry['outcome'] in {'planned','budget_deferred','deferred_active_run'}]
        active=[entry for entry in plan['cases'] if entry['outcome'] in {'queued','running'}]
        if not pending and not active:
            plan['state']='completed' if all(entry['outcome']=='completed' for entry in plan['cases']) else 'completed_with_failures'
            break
        if not active and pending:
            plan['remaining_authorized_requests']=budget_remaining(ledger,recovery_id)
            if len(pending)>plan['remaining_authorized_requests']:
                for entry in pending:entry['outcome']='budget_deferred'
                plan['state']='blocked_budget';break
            compatible=current_compatibility(conn,plan)
            required=sum(1 for entry in pending)+len({key for entry in pending for key in entry['evidence_hashes'] if not compatible.get(key,False)})
            plan['remaining_authorized_requests']=budget_remaining(ledger,recovery_id)
            if required>plan['remaining_authorized_requests']:
                for entry in pending:entry['outcome']='budget_deferred'
                plan['state']='blocked_budget';break
            entry=pending[0]
            try:entry['outcome']=enqueue_one(conn,plan,entry)['status']
            except ValueError as error:
                conn.rollback();entry['outcome']='deferred_active_run' if 'active' in str(error) else 'blocked_by_inputs';entry['failure_category']='case_conflict' if 'active' in str(error) else 'evidence_changed';plan['state']='paused_case_conflict';break
            except Exception:
                conn.rollback();entry['outcome']='enqueue_failed';entry['failure_category']='database_error';plan['state']='paused_database_error';break
        write_json(checkpoint,plan)
        time.sleep(max(.01,min(poll_seconds,5)))
    write_json(checkpoint,plan);return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--batch-id')
    parser.add_argument('--case-id',action='append',default=[])
    parser.add_argument('--scope',choices=['claims','underwriting','all'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--pause',action='store_true')
    parser.add_argument('--validation',type=Path)
    parser.add_argument('--db',default='postgresql')
    parser.add_argument('--schema',default='fraudlens_pilot')
    parser.add_argument('--max-seconds',type=int,default=120)
    args=parser.parse_args();output=args.output.resolve();checkpoint=output/'checkpoint.json'
    if args.pause:
        if not checkpoint.is_file():raise ValueError('No checkpoint exists to pause.')
        (output/'PAUSE').write_text('Operator pause requested.',encoding='utf-8');return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    recovery_id=os.environ.get('FRAUDLENS_RECOVERY_ID');ledger=read_json(ORIGINAL_LEDGER)
    if args.resume:
        plan=read_json(checkpoint)
        if args.batch_id and args.batch_id!=plan['batch_id']:raise ValueError('Resume must use the original batch ID.')
        if (output/'PAUSE').exists():
            (output/'PAUSE').unlink()
    else:
        if not args.audit or not args.batch_id:raise ValueError('An audit manifest and batch ID are required.')
        if output.exists():raise ValueError('Use a new private output directory or --resume.')
        plan=make_plan(records_from(args.audit),args.batch_id,args.case_id,args.scope,ledger,recovery_id)
        plan['audit_sha256']=hashlib.sha256(args.audit.read_bytes()).hexdigest()
        output.mkdir(parents=True);write_json(output/'plan.json',plan);write_json(checkpoint,plan)
    if not args.apply:
        print(json.dumps({'state':'dry_run','selected':len(plan['cases']),'minimum_requests':plan['minimum_requests'],
            'remaining_authorized_requests':plan['remaining_authorized_requests'],'budget_sufficient':plan['budget_sufficient'],'output':str(output)},indent=2));return 0
    if not args.validation:raise ValueError('Apply requires a successful claims+underwriting live validation artifact.')
    validation=read_json(args.validation);validation_gate(validation,ledger,ORIGINAL_LEDGER,recovery_id)
    os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    conn=db.connect(args.db)
    try:
        # Explicit migrations must already be applied; do not migrate data here.
        from filelock import FileLock,Timeout
        try:
            with FileLock(str(output/'batch.lock'),timeout=0):
                result=supervise(conn,plan,checkpoint,ORIGINAL_LEDGER,validation,recovery_id,max_seconds=max(1,args.max_seconds),pause_path=output/'PAUSE')
        except Timeout as error:raise ValueError('Another process is supervising this checkpoint. Pause or wait for that process before resuming.') from error
    finally:conn.close()
    print(json.dumps({'state':result['state'],'outcomes':dict(Counter(row['outcome'] for row in result['cases'])),'source_counts':result['source_counts']},indent=2))
    return 0 if result['state']=='completed' else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except ValueError as error:raise SystemExit(str(error))
