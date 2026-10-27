"""Truthful review summaries, independent of risk and human decisions.

Historical status is never changed. A derived partial summary requires durable
results AND a saved snapshot, a provider cause, and no recorded local failure.
"""
VERSION = 'local-review-outcome-2026-10-23-v1'
LOCAL_COMPLETE = 'Local checks complete — AI analysis unavailable; human review required.'
ADMIN_PARTIAL = 'Ready for manual review — AI unavailable.'
CUSTOMER_PARTIAL = 'Your application is saved and awaiting review.'
TIMELINE_PARTIAL = 'Available checks finished; AI analysis could not complete.'
PROVIDER_ERRORS = {'provider_http_error','provider_network_failure','provider_circuit_open',
    'authorized_budget_exhausted','provider_quota_or_rate_limit','provider_access_denied',
    'provider_configuration','provider_control_busy','provider_control_invalid',
    'response_schema_invalid','timeout'}


def summary(job, *, durable_result=False, saved_snapshot=False):
    job=job or {};status=job.get('status','not_recorded')
    if (job.get('assessment_mode')=='local_rules' and status in {'completed','done'}
        and job.get('results_persisted') and job.get('local_checks_complete')
        and (job.get('assessment_presentation') or {}).get('run_id')==job.get('job_id')):
        assessment=job['assessment_presentation']
        return dict(version=VERSION,kind='local_rules',stored_execution_status=status,display_status=status,
            local_checks_complete=True,results_persisted=True,historical_derived=False,
            assessment_complete=True,provider_available=None,
            admin_label=assessment['status_label'],message=assessment['explanation'],
            customer_label=assessment['status_label'],timeline_label='Assessment complete — local rules')
    errors=[x for x in [*(job.get('failures') or []),job.get('root_failure_detail')] if isinstance(x,dict)]
    provider=any(x.get('error_category') in PROVIDER_ERRORS and (x.get('stage') in
        {'perception','perception_inputs','adjudication','provider'} or str(x.get('stage','')).startswith('agent')) for x in errors)
    local_failure=any(x.get('error_category') not in PROVIDER_ERRORS|{'required_perception_unavailable'}
        and not str(x.get('stage','')).startswith('agent') for x in errors)
    historical=(status=='failed' and job.get('stage')=='needs_review' and not job.get('error_type')
        and durable_result and saved_snapshot and provider and not local_failure)
    recorded=(status=='completed_partial' and job.get('local_checks_complete') is True
        and job.get('results_persisted') is True and not local_failure)
    partial=bool(historical or recorded)
    ai_unavailable=partial and (provider or job.get('partial_reason')=='ai_unavailable')
    return dict(version=VERSION,kind='provider_partial' if ai_unavailable else 'assessment_partial' if partial else status,
        stored_execution_status=status,display_status='completed_partial' if partial else status,
        local_checks_complete=partial or bool(job.get('local_checks_complete')),
        results_persisted=bool(durable_result or job.get('results_persisted')),
        historical_derived=bool(historical),provider_available=False if ai_unavailable else None,
        assessment_complete=False if partial else None,
        admin_label=ADMIN_PARTIAL if ai_unavailable else 'Ready for manual review — assessment incomplete.' if partial else None,
        message=LOCAL_COMPLETE if ai_unavailable else 'Available checks complete; assessment incomplete; human review required.' if partial else None,
        customer_label=CUSTOMER_PARTIAL if partial else None,
        timeline_label=TIMELINE_PARTIAL if ai_unavailable else None)
