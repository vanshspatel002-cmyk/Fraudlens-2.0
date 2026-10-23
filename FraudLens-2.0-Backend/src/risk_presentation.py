"""One saved-assessment display contract. No scoring, models, or database I/O."""
from __future__ import annotations

import math

VERSION = 'risk-presentation-2026-10-23-v3'
BANDS = {'clear': 'Low', 'request_evidence': 'Medium', 'desk_review': 'Medium', 'escalate_siu': 'High'}


def assessment_presentation(report):
    explanation = report.get('assessment_explanation') or {}
    routing = explanation.get('routing') or {}
    aggregation = explanation.get('aggregation') or {}
    coverage = explanation.get('coverage') or {}
    processing = report.get('processing') or {}
    decision = report.get('agent_recommendation') or {}
    run_id = report.get('run_id')
    state = processing.get('status') or 'unrecorded'
    band = routing.get('recorded_band')
    reasons = []
    if not run_id:
        reasons.append('The analysis run/version was not recorded.')
    stale = bool(run_id and explanation.get('run_id') != run_id)
    stale |= bool(run_id and processing.get('job_id') and processing['job_id'] != run_id)
    if stale:
        reasons.append('The saved explanation belongs to an earlier or unverified analysis run.')
    if (processing.get('review_summary') or {}).get('kind')=='provider_partial':
        reasons.append('Local checks complete — AI analysis unavailable; human review required.')
    elif state not in {'completed', 'done'}:
        reasons.append('Processing is ' + state.replace('_', ' ') + '; no completed current assessment is established.')
    if not explanation:
        reasons.append('A structured assessment explanation was not recorded.')
    if routing.get('source') not in {'model','rules_baseline'}:
        reasons.append('The saved assessment basis is unavailable or unsupported.')
    if not (explanation.get('policy_version') or report.get('policy_version')):
        reasons.append('The assessment policy version was not recorded.')
    if routing.get('source') == 'fallback' or decision.get('provider_unavailable') or routing.get('converged') is not True:
        reasons.append('Automated interpretation did not establish a converged assessment.')
    if coverage.get('material_complete') is not True:
        reasons.append('Required check coverage is incomplete or was not recorded.')
    if band not in BANDS:
        reasons.append('A supported risk category was not recorded.')
    if aggregation.get('matches_recorded_band') is False:
        reasons.append('The saved score and recorded routing band disagree; review is required.')
    valid = not reasons
    category = BANDS[band] if valid else None
    historical = report.get('assessment_context') == 'historical'
    score = aggregation.get('computed_value')
    numeric = (valid and aggregation.get('valid_numeric_score') is True
               and aggregation.get('method') == 'weighted_concern_sum'
               and isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score))
    if numeric and decision.get('score') is not None:
        numeric = isinstance(decision['score'], (int, float)) and not isinstance(decision['score'],bool) and math.isclose(score, decision['score'], abs_tol=.00005)
    source = routing.get('source') or 'unrecorded'
    basis = 'Saved model routing' if source == 'model' else 'Saved research baseline' if source == 'rules_baseline' else 'Saved assessment unavailable'
    states = coverage.get('check_states') or {}
    missing = coverage.get('material_gap_ids', [key for key, value in states.items() if value not in {'completed', 'not_applicable'}])
    return {
        'version': VERSION, 'run_id': run_id, 'policy_version': explanation.get('policy_version') or report.get('policy_version'),
        'processing_state': state, 'state': 'historical' if valid and historical else 'completed' if valid else 'stale' if stale else 'incomplete',
        'complete': valid, 'category': category, 'recorded_band': band,
        'label': ('Historical assessed risk: ' if historical else 'Assessed risk: ') + category if valid else 'Assessment incomplete',
        'score': score if numeric else None,
        'score_scale': 'Unbounded heuristic routing score; not a fraud probability' if numeric else None,
        'thresholds': aggregation.get('thresholds') if numeric else None,
        'position_basis': 'category_only', 'basis': basis, 'historical': historical,
        'scope': 'Saved run and evidence only; later evidence requires its own assessment.',
        'explanation': ' '.join(reasons) if reasons else (routing.get('recorded_narrative') or 'The recorded routing category is shown without implying a numeric position.'),
        'missing_check_ids': missing,
        'model_recommendation':routing.get('model_recommendation', routing.get('recommendation')) if source=='model' else None,
        'effective_recommendation':routing.get('effective_recommendation', routing.get('recommendation')),
        'coverage_policy':coverage.get('version'),
    }
