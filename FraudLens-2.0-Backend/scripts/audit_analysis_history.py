"""Read-only, point-in-time analysis inventory and explicit reprocessing scope.

Writes private manifests to a NEW directory; never modifies application records.
Database reads finish before filesystem hashing. No applicant fields or secrets
are included in console output. Keep the detailed manifests outside source control.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src import db


def audit(conn, output: Path):
    if output.exists():
        raise ValueError('Use a new private output directory; previous audits are retained.')
    conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if db.is_postgres(conn) else 'BEGIN')
    try:
        cases = [dict(r) for r in conn.execute('SELECT case_id,agent_type,status,created_at FROM cases ORDER BY rowid')]
        images = [dict(r) for r in conn.execute('SELECT image_id,case_id,path,content_hash FROM images ORDER BY rowid')]
        jobs = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM api_jobs ORDER BY rowid')]
        results = {r['run_id']: dict(r) for r in conn.execute('SELECT * FROM processing_results')}
        snapshots = [dict(r) for r in conn.execute('SELECT snapshot_id,case_id,run_id,created_at FROM report_snapshots ORDER BY rowid')]
        actions = [dict(r) for r in conn.execute('SELECT case_id,action FROM admin_actions ORDER BY rowid')]
        decisions = Counter(r[0] for r in conn.execute('SELECT case_id FROM agent_decisions'))
        perceptions = {r['content_hash']: dict(r) for r in conn.execute('SELECT * FROM perception_records')}
        explanation_events = [dict(r) for r in conn.execute("SELECT case_id,details FROM audit_log WHERE event_type='case_adjudicated' ORDER BY rowid")]
        artifact_count = conn.execute('SELECT COUNT(*) FROM report_artifacts').fetchone()[0]
    finally:
        conn.rollback()
    by_case, by_job, by_report, by_action = (defaultdict(list) for _ in range(4))
    for row in images: by_case[row['case_id']].append(row)
    for row in jobs: by_job[row['case_id']].append(row)
    for row in snapshots: by_report[row['case_id']].append(row)
    for row in actions: by_action[row['case_id']].append(row)
    hashed = {}
    from src.perception import perception_record_usable
    compatible={key:perception_record_usable(db._perception_from_row(row)) for key,row in perceptions.items()}
    explanations={}
    for event in explanation_events:
        details=json.loads(event['details'])
        if details.get('run_id') and details.get('assessment_explanation'):
            explanations[details['run_id']]=details['assessment_explanation']
    file_counts = Counter()
    records = []
    for case in cases:
        evidence = []
        for image in by_case[case['case_id']]:
            path = Path(image['path'])
            if not path.is_absolute(): path = ROOT/path
            key = str(path.resolve())
            if key not in hashed:
                if not path.is_file(): hashed[key] = 'missing'
                else:
                    try: hashed[key] = 'available' if hashlib.sha256(path.read_bytes()).hexdigest() == image['content_hash'] else 'hash_mismatch'
                    except OSError: hashed[key] = 'unreadable'
            status = hashed[key]
            file_counts[status] += 1
            observation = perceptions.get(image['content_hash'])
            raw = json.loads(observation['raw_response']) if observation and isinstance(observation['raw_response'], str) else (observation or {}).get('raw_response', {})
            evidence.append({'image_id':image['image_id'], 'content_hash':image['content_hash'],
                'file_status':status, 'observation_present':bool(observation),
                'observation_has_error':bool((raw or {}).get('error')),
                'observation_source':(observation or {}).get('source'),
                'cache_compatible':bool(compatible.get(image['content_hash'])),
                'cache_compatibility':'validated_usable_observations' if compatible.get(image['content_hash']) else 'invalid_or_missing'})
        history = by_job[case['case_id']]
        job = history[-1] if history else None
        result = results.get(job['job_id']) if job else None
        if not job: state = 'legacy_no_durable_run'
        elif job['status'] == 'completed' and result and bool(result['converged']):
            explanation=explanations.get(job['job_id']) or {}
            state='completed_partial_evidence' if explanation.get('coverage',{}).get('material_complete') is False else 'completed_converged'
        elif job['status'] in {'failed', 'interrupted'}: state = 'failed_or_partial'
        else: state = job['status']
        blockers = []
        if not evidence: blockers.append('no_evidence')
        if any(e['file_status'] != 'available' for e in evidence): blockers.append('missing_unreadable_or_changed_evidence')
        active = bool(job and job['status'] in {'queued','running'})
        if active: blockers.append('active_processing_run')
        human = by_action[case['case_id']]
        records.append({'case_id':case['case_id'], 'case_type':case['agent_type'],
            'submitted_at':str(case['created_at']), 'case_status':case['status'],
            'analysis_state':state, 'latest_run_id':job['job_id'] if job else None,
            'latest_job_status':job['status'] if job else None, 'durable_runs':len(history),
            'has_latest_result':bool(result), 'latest_result_converged':bool(result and result['converged']),
            'legacy_decision_count':decisions[case['case_id']], 'report_count':len(by_report[case['case_id']]),
            'latest_human_action':human[-1]['action'] if human else None,
            'human_actions_preserved':len(human), 'evidence':evidence,
            'eligible_evidence':not blockers, 'blockers':blockers,
            'requires_explicit_retrospective_scope':bool(human),
            'reprocessing_outcome':'blocked_by_missing_evidence_or_configuration' if blockers else 'pending_provider_and_budget_validation'})
    summary = {'generated_at':datetime.now(timezone.utc).isoformat(), 'cases':len(cases),
        'by_case_type':dict(Counter(c['case_type'] for c in records)),
        'by_analysis_state':dict(Counter(c['analysis_state'] for c in records)),
        'by_recorded_job_state':dict(Counter(j['status'] for j in jobs)),
        'cases_with_results':sum(bool(by_job[c['case_id']] and any(j['job_id'] in results for j in by_job[c['case_id']])) for c in cases),
        'cases_with_reports':sum(bool(by_report[c['case_id']]) for c in cases),
        'cases_with_human_action':sum(bool(by_action[c['case_id']]) for c in cases),
        'evidence_files':dict(file_counts), 'eligible_evidence_cases':sum(c['eligible_evidence'] for c in records),
        'images':len(images), 'unique_image_hashes':len({i['content_hash'] for i in images}),
        'raw_perception_rows':len(perceptions), 'compatible_perception_rows':sum(compatible.values()),
        'durable_jobs':len(jobs), 'results':len(results),
        'report_snapshots':len(snapshots), 'pdf_artifacts':artifact_count,
        'live_request_estimate':{'minimum_agent_requests':sum(c['eligible_evidence'] for c in records),
            'vision_requests_upper_bound':len({e['content_hash'] for c in records if c['eligible_evidence'] for e in c['evidence']}),
            'compatible_vision_misses':len({e['content_hash'] for c in records if c['eligible_evidence'] for e in c['evidence'] if not e['cache_compatible']}),
            'note':'Compatibility validates recorded observation fields; failed rows are excluded. Agent tool/parse turns can require additional requests.'}}
    output.mkdir(parents=True)
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    (output/'cases.json').write_text(json.dumps(records,indent=2),encoding='utf8')
    (output/'run-manifest.json').write_text(json.dumps({'generated_at':summary['generated_at'],'cases':records},indent=2),encoding='utf8')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='postgresql')
    parser.add_argument('--schema',default='fraudlens_pilot')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    load_dotenv(ROOT/'.env');os.environ['FRAUDLENS_PG_SCHEMA']=args.schema
    conn=db.connect(args.db)
    try: print(json.dumps(audit(conn,args.output.resolve()),indent=2))
    finally: conn.close()

if __name__=='__main__':main()
