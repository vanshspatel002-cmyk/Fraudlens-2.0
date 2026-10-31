"""Local review-priority policy; no provider, score or approval decision.

HIGH: completed positive-weight plate mismatch AND image/history concern.
MEDIUM: another eligible concern, or insufficient required material evidence.
LOW: sufficient required evidence, at least one completed required local check,
and no eligible concern. Correlated matches never add up to HIGH. Garage-only
alerts and zero-weight experiments do not establish claimant risk.
"""
from copy import deepcopy

VERSION = 'local-rules-review-priority-2026-10-27-v1'
METHOD = 'Local rules assessment'
NOTE = 'This assessment uses available local checks. AI-dependent checks were not performed.'
GAP_EXPLANATION = 'Review required because evidence is insufficient; this is not a finding of fraud. Review priority increased because required evidence is incomplete; this does not establish fraud.'
RISK_INDEX_NOTE = 'Risk index expresses the strength of findings under this assessment policy; it is not a statistical probability of fraud.'
DOMAINS = {'plate_ocr':'vehicle_identity', 'internal_duplicate':'image_history',
           'external_corpus':'image_history', 'baseline_linkage':'image_history',
           'severity_progression':'image_history', 'entity_graph':'relationships',
           'exif_metadata':'provenance', 'c2pa_credentials':'provenance'}
DOMAIN_WEIGHTS = {'vehicle_identity': 35, 'image_history': 40, 'relationships': 15, 'provenance': 10, 'incident_context': 15}
LABELS = {'plate_ocr':'registration reading','internal_duplicate':'internal photograph reuse',
          'external_corpus':'external photograph match','baseline_linkage':'earlier inspection comparison',
          'severity_progression':'damage history','entity_graph':'shared identifiers',
          'exif_metadata':'capture metadata','c2pa_credentials':'content credentials',
          'scene_consistency':'incident context','damage_plausibility':'damage and claimed amount',
          'odometer_readability':'readable odometer','usable_required_local_evidence':'usable required local evidence'}


def classify(explanation):
    """Only consume actual saved execution rows and existing sufficiency rules."""
    rows = explanation.get('findings') or []
    coverage = deepcopy(explanation.get('coverage') or {})
    required = coverage.get('requirements') or {}
    applicable = {key:row for key,row in required.items() if row.get('required') and row.get('applicable')}
    gaps = list(coverage.get('material_gap_ids') or [])
    usable = any(row.get('execution_state')=='completed' and row.get('check_id') in applicable for row in rows)
    # An absent/empty coverage declaration cannot support clearance.
    if not applicable or not usable:
        gaps.append('usable_required_local_evidence')
    gaps = list(dict.fromkeys(gaps))
    concerns = [row for row in rows if row.get('check_id') in DOMAINS
                and row.get('execution_state')=='completed' and row.get('verdict')=='concern'
                and row.get('eligibility',{}).get('eligible') is True
                and isinstance(row.get('registered_weight'),(int,float)) and row['registered_weight']>0
                and row.get('attributed_to')!='garage']
    domains = sorted({DOMAINS[row['check_id']] for row in concerns})
    strong = {'vehicle_identity','image_history'} <= set(domains)
    band = 'HIGH' if strong else 'MEDIUM' if concerns or gaps else 'LOW'

    # Domain-grouped concern contribution
    concern_score = sum(DOMAIN_WEIGHTS.get(d, 10) for d in domains)
    
    # Evidence uncertainty adjustment
    if gaps:
        gap_ratio = min(len(gaps), len(applicable)) / max(1, len(applicable))
        uncertainty_adjustment = 32 + round(14 * gap_ratio)
    else:
        uncertainty_adjustment = 0

    if band == 'HIGH':
        # Bounded in [70, 95]
        risk_index = min(95, max(72, concern_score))
    elif band == 'MEDIUM':
        # Bounded in [30, 69]
        if concerns and gaps:
            raw_idx = concern_score + round(uncertainty_adjustment * 0.4)
            risk_index = min(68, max(36, raw_idx))
        elif gaps:
            risk_index = min(55, max(35, uncertainty_adjustment))
        else:
            risk_index = min(68, max(35, concern_score))
    else:  # LOW
        # Bounded in [0, 29]
        sufficient_count = sum(row.get('evidence_sufficient') is True for row in applicable.values())
        coverage_factor = 1.0 - (sufficient_count / max(1, len(applicable)))
        risk_index = min(20, max(5, round(10 + 10 * coverage_factor)))

    reason = ('Completed registration-mismatch and image/history concerns require investigation. '
              'Verify both sources independently; this review priority is not a finding of fraud.' if strong else
              'Completed local checks require independent review: '+', '.join(dict.fromkeys(LABELS[row['check_id']] for row in concerns))+'.' if concerns else
              'Applicable required evidence is sufficient and completed local checks contain no eligible review concern.')
    if gaps:
        reason = (reason+' ' if concerns else '') + GAP_EXPLANATION
    recommendation = 'investigate' if strong else 'request_evidence' if gaps else 'desk_review' if concerns else 'routine_review'
    selected = ([row for row in rows if row.get('check_id') in applicable
                 and row.get('execution_state')=='completed' and row.get('verdict')=='pass'] if band=='LOW' else concerns)
    supporting = [{key:row.get(key) for key in ('finding_id','check_id','execution_state','verdict','attributed_to','explanation')} for row in selected]
    return dict(display_band=band,method=METHOD,display_policy_version=VERSION,
        risk_index=risk_index,risk_index_formatted=f"{risk_index}%",
        label=f"Review priority: {band} — Risk index: {risk_index}%",
        display_label=f"{band} — Risk index: {risk_index}%",
        risk_policy_note=RISK_INDEX_NOTE,
        concern_score=concern_score,uncertainty_adjustment=uncertainty_adjustment,
        explanation=reason,review_recommendation=recommendation,supporting_findings=supporting,
        concern_domains=domains,coverage=dict(required_applicable=len(applicable),
            sufficient=sum(row.get('evidence_sufficient') is True for row in applicable.values()),
            material_complete=not gaps,material_gap_ids=gaps,state_counts=coverage.get('state_counts') or {}),
        next_action=('Investigate the cited registration and reuse findings; ' if strong else '')+
            ('request evidence for: '+', '.join(LABELS.get(key,key.replace('_',' ')) for key in gaps)+'.' if gaps else 'Review the saved findings and record an independent human decision.'),
        status_label='Assessment complete — additional evidence recommended' if gaps else 'Assessment complete — local rules',
        method_note=NOTE)


def apply(explanation, decision):
    result = classify(explanation)
    explanation.update(assessment_type='local_rules',local_rules=result)
    explanation['aggregation'] = dict(method='local_review_priority',computed_value=None,
        valid_numeric_score=False,thresholds={'low_max': 29, 'medium_max': 69, 'high_max': 100},
        risk_index=result['risk_index'],status='category_and_index',
        rule='Index bounded 0-100: LOW [0-29%], MEDIUM [30-69%], HIGH [70-100%]. Domain-grouped concern findings plus evidence uncertainty adjustment. Not a statistical probability of fraud.',
        policy_note=RISK_INDEX_NOTE)
    # Preserve human approval/rejection and the existing conservative desk queue.
    # The new risk priority never automatically approves or rejects a case.
    explanation['routing'].update(source='local_rules',converged=True,
        recorded_narrative=result['explanation'],model_recommendation=None,
        effective_band='desk_review',effective_recommendation='desk_review',
        guard_policy=VERSION,guard_applied=False,overrides=['Local mode retains desk review; human approval/rejection is separate.'])
    explanation.pop('shadow_assessment',None)
    decision.summary = result['explanation']
    decision.score = None
    decision.supporting_finding_ids = [row['finding_id'] for row in result['supporting_findings']]
    for row in explanation['findings']:
        row['cited_by_agent'] = False
        row['cited_by_local_policy'] = row['finding_id'] in decision.supporting_finding_ids
    return result


def presentation(report):
    """Adapt the frozen local result to the shared saved presentation contract."""
    explanation = report['assessment_explanation'];result = deepcopy(explanation['local_rules'])
    processing = report.get('processing') or {}
    band = result['display_band']
    risk_index = result.get('risk_index')
    label = f"Review priority: {band} — Risk index: {risk_index}%" if risk_index is not None else f"Review priority: {band}"
    result.update(
        version=VERSION,run_id=report['run_id'],policy_version=explanation['policy_version'],
        complete=True,processing_complete=True,processing_state=processing['status'],state='completed',
        category=band.title(),label=label,display_label=f"{band} — Risk index: {risk_index}%" if risk_index is not None else band,
        basis=METHOD,provisional=False,manual_review_required=True,score=None,score_scale=None,
        risk_index=risk_index,risk_index_formatted=f"{risk_index}%" if risk_index is not None else None,
        risk_policy_note=RISK_INDEX_NOTE,
        position_basis='category_only',thresholds=None,recorded_band=explanation['routing']['recorded_band'],
        missing_check_ids=result['coverage']['material_gap_ids'],historical=False,
        model_recommendation=None,effective_recommendation='desk_review',
        check_results=[{key:row.get(key) for key in ('finding_id','check_id','execution_state','verdict','attributed_to','explanation')} for row in explanation['findings']],
        scope='Review priority under the saved local rules policy; not a fraud probability or approval.'
    )
    return result
