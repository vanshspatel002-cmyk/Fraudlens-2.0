"""Freeze how an assessment was reached, without inventing a production score.

The production agent chooses a routing band; it does not add up check weights.
Only the existing research baseline computes a weighted sum. This module records
that distinction at assessment time and never reruns a check or calls a model.
"""
from __future__ import annotations

from collections import Counter
from importlib import import_module
import json
import math

VERSION = 'assessment-explanation-2026-10-23-v5'
STATES = {'completed', 'inconclusive', 'failed', 'not_applicable', 'not_run'}

# Config key and the exact default attribute consumed by the corresponding rule.
_CLASS_PARAMETERS = {
    'internal_duplicate': [('duplicate_hamming_concern','HAMMING_CONCERN'),('duplicate_cosine_concern','COSINE_CONCERN'),('duplicate_cosine_floor','COSINE_FLOOR'),('duplicate_cosine_inconclusive','COSINE_INCONCLUSIVE')],
    'external_corpus': [('external_hamming_concern','HAMMING_CONCERN'),('external_cosine_concern','COSINE_CONCERN'),('external_cosine_floor','COSINE_FLOOR'),('external_cosine_inconclusive','COSINE_INCONCLUSIVE')],
    'exif_metadata': [('metadata_gps_concern_km','GPS_CONCERN_KM'),('metadata_timestamp_inconclusive_hours','TIMESTAMP_INCONCLUSIVE_HOURS')],
    'plate_ocr': [('plate_ocr_confidence_concern','OCR_CONFIDENCE_CONCERN')],
    'threshold_gaming': [('threshold_band_low','BAND_LOW'),('threshold_band_high','BAND_HIGH'),('threshold_garage_concern_pct','GARAGE_CONCERN_PCT'),('threshold_min_garage_claims','MIN_GARAGE_CLAIMS')],
}
_MODULE_PARAMETERS = {
    'damage_plausibility': ('damage_plausibility',('SEVERITY_RANGES','CEILING_TOLERANCE')),
    'baseline_linkage': ('baseline_linkage',('WINDOW_DAYS','SERIOUS_SEVERITIES')),
    'entity_graph': ('entity_graph',('MIN_SHARED_IDENTIFIERS','MIN_VEHICLES_PER_CLAIMANT')),
    'severity_progression': ('severity_progression',('SAME_PANEL_WINDOW_DAYS','SEVERITY_ORDER')),
    'scene_consistency': ('scene_consistency',('SHADOW_BEARING_CONCERN_DEG','ELEVATION_SHORT_ABOVE','ELEVATION_MEDIUM_ABOVE','CIVIL_TWILIGHT_DEG','LIGHTING_NIGHT_CONFLICT_DEG','RAIN_MM','RAINY_HOUR_MM','DRY_MM','OVERCAST_CLOUD_PCT','CLEAR_CLOUD_PCT')),
}


def _value(value):
    return value.value if hasattr(value,'value') else value


def _copy(value):
    # Detach from mutable Finding.evidence before audit persistence.
    return json.loads(json.dumps(value,ensure_ascii=False,default=str))


def execution_state(finding):
    evidence = finding.evidence or {}
    explicit = evidence.get('execution_state')
    if explicit in STATES:
        return explicit
    if evidence.get('error_type') or evidence.get('error'):
        return 'failed'
    return 'inconclusive' if _value(finding.verdict)=='inconclusive' else 'completed'


def rule_parameters(check_id, check, config):
    recorded = {}
    for key, attribute in _CLASS_PARAMETERS.get(check_id,[]):
        if check is not None and hasattr(check,attribute):
            recorded[key] = config.get(key,getattr(check,attribute))
    if check_id in _MODULE_PARAMETERS:
        module_name,names = _MODULE_PARAMETERS[check_id]
        module = import_module('.checks.'+module_name,package=__package__)
        recorded.update({name.lower():getattr(module,name) for name in names})
    return _copy(recorded)


def explain_assessment(case, findings, decision, policy, *, converged, trace=(), run_id=None, use_agent=True, check_config=None):
    """Return a JSON-safe explanation to persist with this exact decision/run."""
    from .checks import REGISTRY
    from . import baseline
    config = check_config or {}
    findings = list(findings)
    expected = list(policy.check_ids)
    cited = set(decision.supporting_finding_ids or [])
    rows = []
    for finding in findings:
        check = REGISTRY.get(finding.check_id)
        weight = float(check.weight) if check is not None else 0.0
        state = execution_state(finding)
        verdict = _value(finding.verdict)
        eligible = check is not None and weight>0 and verdict=='concern' and ((not use_agent and config.get('assessment_mode')!='local_rules') or state=='completed')
        reason = ('Unknown or retired check' if check is None else 'Zero-weight experimental check' if weight==0 else
                  'The existing baseline includes this concern despite its non-completed execution label; inspect the recorded inconsistency' if eligible and state!='completed' else
                  'Check did not complete with an applicable result' if state!='completed' else
                  'Only concern findings contribute to the baseline' if verdict!='concern' else 'Recorded concern from an eligible check')
        # Preserve the existing baseline operation exactly, including each
        # repeated finding. Model routing has no numeric contribution at all.
        contribution = None if use_agent else weight*float(finding.confidence) if verdict=='concern' else 0.0
        observed = {key:value for key,value in (finding.evidence or {}).items() if key not in {'error','traceback','stack_trace'}}
        thresholds = observed.get('rule_parameters') or rule_parameters(finding.check_id,check,config)
        rows.append({'finding_id':finding.finding_id,'check_id':finding.check_id,
            'execution_state':state,'verdict':verdict,'attributed_to':getattr(check,'attributed_to',None),
            'observed_values':_copy(observed),'rule_parameters':_copy(thresholds),
            'eligibility':{'eligible':eligible,'reason':reason},'registered_weight':weight,
            'finding_confidence':float(finding.confidence),'contribution':contribution,
            'cited_by_agent':finding.finding_id in cited,'explanation':finding.explanation,
            'limitation':getattr(check,'limitation','') or None})
    missing = [check_id for check_id in expected if not any(row['check_id']==check_id for row in rows)]
    by_check = {}
    for check_id in expected:
        states = [row['execution_state'] for row in rows if row['check_id']==check_id]
        by_check[check_id] = ('not_run' if not states or all(state=='not_run' for state in states) else 'failed' if 'failed' in states else
                              'inconclusive' if 'inconclusive' in states or 'not_run' in states else
                              'completed' if 'completed' in states else 'not_applicable')
    material = [check_id for check_id in expected if check_id in REGISTRY and float(REGISTRY[check_id].weight)>0]
    if use_agent:
        aggregation = {'method':'model_routing','computed_value':None,'unrounded_value':None,'valid_numeric_score':False,
            'rule':'The agent selects a routing band from the recorded evidence. Check weights are context, not an additive production score.',
            'thresholds':None,'status':'not_computed'}
    else:
        # Match baseline.decide's sequential additions exactly. Python's sum()
        # may use compensated summation, which can change a boundary comparison.
        unrounded = 0.0
        for row in rows:
            if row['verdict']=='concern':
                unrounded += row['contribution']
        computed = round(unrounded,4)
        reproduced_band = baseline.band_for(unrounded).value
        recorded = decision.score
        matches = recorded is not None and math.isclose(computed,float(recorded),abs_tol=0.00005)
        aggregation = {'method':'weighted_concern_sum','computed_value':float(recorded) if matches else None,
            'unrounded_value':unrounded,'rounding_places':4,'band_comparison_basis':'unrounded_concern_sum',
            'reproduced_band':reproduced_band,'matches_recorded_band':reproduced_band==_value(decision.risk_band),
            'valid_numeric_score':matches,'status':'recorded' if matches else 'recorded_score_mismatch',
            'rule':'Sum registered weight × finding confidence for every concern finding. Pass and inconclusive findings add zero; repeated findings are added individually.',
            'thresholds':{'clear_below':baseline.CLEAR_BELOW,'request_evidence_below':baseline.REQUEST_EVIDENCE_BELOW,'desk_review_below':baseline.DESK_REVIEW_BELOW},
            'score_label':'Unbounded heuristic routing score; not a fraud probability'}
    overrides = []
    for step in trace:
        kind = step.get('kind') or step.get('type')
        summary = step.get('detail') or step.get('summary') or step.get('content') or ''
        if kind in {'fallback','guard'}:
            # Keep the rule, never a provider's raw exception or reply preview.
            label = 'Automated adjudication unavailable or incomplete; desk review required' if kind=='fallback' else (
                'Rejection language routed to a human investigation decision' if 'rejection' in summary.lower() else 'Agent execution policy guard applied')
            if label not in overrides:
                overrides.append(label)
    if use_agent and not converged and not overrides:
        overrides.append('Automated adjudication unavailable or incomplete; desk review required')
    from .coverage_policy import assess
    from .input_coverage import assess_inputs
    sufficiency = assess(expected, by_check, rows, REGISTRY,assess_inputs(case.agent_type,rows,config))
    guarded = use_agent and (not converged or not sufficiency['material_complete'])
    clearance_guard = guarded and _value(decision.recommendation) == 'approve'
    effective = ('request_evidence' if converged else 'desk_review') if clearance_guard or not converged else _value(decision.risk_band)
    if guarded:
        overrides.append('Material-evidence guard: '+('model output retained; ' if converged else 'no converged model decision; ')+'incomplete assessment cannot route as actionable clearance.')
    result = {'version':VERSION,'case_id':case.case_id,'run_id':run_id,'policy_version':decision.policy_version or policy.policy_version,
        'check_policy_version':policy.policy_version,
        'case_type':case.agent_type,'assessment_type':'agent_routing' if use_agent else 'rules_baseline',
        'aggregation':aggregation,'findings':rows,
        'coverage':{'expected_check_ids':expected,'missing_check_ids':missing,'check_states':by_check,
                    'eligible_check_ids':material, **sufficiency,
                    'state_counts':dict(Counter(by_check.values())),
                    'complete':all(state in {'completed','not_applicable'} for state in by_check.values())},
        'routing':{'source':'model' if use_agent and converged else 'fallback' if use_agent else 'rules_baseline',
                   'converged':bool(converged),'recorded_band':_value(decision.risk_band),
                   'recommendation':_value(decision.recommendation),'cited_finding_ids':list(decision.supporting_finding_ids or []),
                   'model_recommendation':_value(decision.recommendation) if use_agent and converged else None,
                   'effective_band':effective, 'effective_recommendation':'desk_review' if not converged else 'request_evidence' if clearance_guard else _value(decision.recommendation),
                   'guard_policy':sufficiency['version'], 'guard_applied':guarded,
                   'overrides':overrides,'recorded_narrative':decision.summary},
        'limitations':['Check weights and finding confidence are heuristic inputs, not calibrated fraud probabilities.',
                       'Missing, failed and not-applicable checks do not count as passed checks.']}
    from .shadow_assessment import calculate
    result['shadow_assessment'] = calculate(result, sorted({str(r['observed_values']['image_id']) for r in rows if r['observed_values'].get('image_id')}))
    return result
