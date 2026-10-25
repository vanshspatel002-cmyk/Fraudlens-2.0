"""Saved display assessment, separate from production routing and shadow scoring.

Partial policy: one completed eligible concern supports MEDIUM; corroborating
plate identity and image/history concerns support HIGH. Correlated image/history
checks count as one domain. No partial LOW clearance is supported. Garage-only,
experimental, missing and inconclusive results cannot establish claimant risk.
"""
from __future__ import annotations

import math

VERSION = 'risk-presentation-2026-10-25-v4'
PARTIAL_POLICY = 'partial-evidence-display-2026-10-25-v1'
BANDS = {'clear': 'Low', 'request_evidence': 'Medium', 'desk_review': 'Medium', 'escalate_siu': 'High'}
DOMAINS = {'plate_ocr': 'vehicle_identity', 'internal_duplicate': 'image_history',
           'external_corpus': 'image_history', 'baseline_linkage': 'image_history',
           'severity_progression': 'image_history', 'entity_graph': 'relationships',
           'damage_plausibility': 'damage_context', 'scene_consistency': 'incident_context'}


def saved_display_band(summary):
    """Read a saved category, including the previous schema; never use routing."""
    summary = summary or {}
    if summary.get('display_band') in {'LOW','MEDIUM','HIGH','UNASSESSED'}:
        return summary['display_band']
    category = summary.get('category')
    return category.upper() if summary.get('complete') is True and category in {'Low','Medium','High'} else 'UNASSESSED'


def assessment_presentation(report, *, allow_partial=True):
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
    rows = explanation.get('findings') or []
    # Require run-bound, terminal saved work, including proven legacy provider
    # partial runs. Never upgrade a queued/stale/failed local execution.
    terminal = state in {'completed', 'done', 'completed_partial'} or (
        state == 'failed' and (processing.get('review_summary') or {}).get('kind') == 'provider_partial')
    trusted = bool(run_id and not stale and explanation.get('run_id') == run_id
                   and explanation.get('policy_version') and terminal)
    supports = [row for row in rows if allow_partial and trusted and row.get('execution_state') == 'completed'
                and row.get('verdict') == 'concern' and row.get('check_id') in DOMAINS
                and row.get('eligibility', {}).get('eligible') is True
                and isinstance(row.get('registered_weight'), (int, float))
                and row['registered_weight'] > 0 and row.get('attributed_to') != 'garage']
    domains = sorted({DOMAINS[row['check_id']] for row in supports})
    provisional = bool(not valid and supports)
    if provisional:
        category = 'High' if {'vehicle_identity', 'image_history'} <= set(domains) else 'Medium'
    historical = report.get('assessment_context') == 'historical'
    score = aggregation.get('computed_value')
    numeric = (valid and aggregation.get('valid_numeric_score') is True
               and aggregation.get('method') == 'weighted_concern_sum'
               and isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score))
    if numeric and decision.get('score') is not None:
        numeric = isinstance(decision['score'], (int, float)) and not isinstance(decision['score'],bool) and math.isclose(score, decision['score'], abs_tol=.00005)
    source = routing.get('source') or 'unrecorded'
    basis = ('Partial rules-based assessment' if not valid else
             'Completed AI-assisted assessment' if source == 'model' else 'Completed rules-based assessment')
    states = coverage.get('check_states') or {}
    missing = coverage.get('material_gap_ids', [key for key, value in states.items() if value not in {'completed', 'not_applicable'}])
    required = coverage.get('requirements') or {}
    applicable = [row for row in required.values() if row.get('required') and row.get('applicable')]
    satisfied = sum(row.get('evidence_sufficient') is True for row in applicable)
    coverage_summary = {'required_applicable': len(applicable), 'sufficient': satisfied,
                        'material_complete': coverage.get('material_complete') is True,
                        'state_counts': coverage.get('state_counts') or {}, 'material_gap_ids': missing}
    selected = supports if provisional else [row for row in rows if row.get('cited_by_agent') and row.get('execution_state') == 'completed' and row.get('registered_weight', 0) > 0] if valid else []
    supporting = [{key: row.get(key) for key in ('finding_id', 'check_id', 'verdict', 'execution_state', 'attributed_to', 'explanation')} for row in selected]
    partial_reason = ('Completed eligible concern findings establish a provisional review band. '
                      + ('Vehicle identity and image/history concerns provide two corroborating domains.' if category == 'High' else 'At least one material concern needs independent review.')
                      + ' This is an evidence concern category, not a finding of fraud or a clearance.')
    unassessed_reason = 'No completed eligible material concern establishes a partial band; incomplete evidence cannot support LOW clearance.'
    return {
        'version': VERSION, 'run_id': run_id, 'policy_version': explanation.get('policy_version') or report.get('policy_version'),
        'display_policy_version': PARTIAL_POLICY,
        'display_band': category.upper() if category else 'UNASSESSED', 'provisional': provisional,
        'manual_review_required': True, 'coverage': coverage_summary, 'supporting_findings': supporting,
        'check_results': [{key: row.get(key) for key in ('finding_id','check_id','execution_state','verdict','attributed_to','explanation')} for row in rows],
        'concern_domains': domains if provisional else [],
        'processing_complete': state in {'completed','done'},
        'next_action': 'Review the cited findings and resolve material gaps: ' + ', '.join(missing) if missing else 'Review saved evidence and record an independent human decision.',
        'processing_state': state, 'state': 'historical' if valid and historical else 'completed' if valid else 'stale' if stale else 'partial' if provisional else 'incomplete',
        'complete': valid, 'category': category, 'recorded_band': band,
        'label': ('Historical assessed risk: ' if historical else 'Assessed risk: ') + category if valid else 'Provisional — partial assessment: ' + category.upper() if provisional else 'UNASSESSED — insufficient evidence',
        'score': score if numeric else None,
        'score_scale': 'Unbounded heuristic routing score; not a fraud probability' if numeric else None,
        'thresholds': aggregation.get('thresholds') if numeric else None,
        'position_basis': 'category_only', 'basis': basis, 'historical': historical,
        'scope': 'Saved run and evidence only; later evidence requires its own assessment.',
        'explanation': (partial_reason if provisional else unassessed_reason) + ' ' + ' '.join(reasons) if reasons else (routing.get('recorded_narrative') or 'The recorded routing category is shown without implying a numeric position.'),
        'missing_check_ids': missing,
        'model_recommendation':routing.get('model_recommendation', routing.get('recommendation')) if source=='model' else None,
        'effective_recommendation':routing.get('effective_recommendation', routing.get('recommendation')),
        'coverage_policy':coverage.get('version'),
    }
