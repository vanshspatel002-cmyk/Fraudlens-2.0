"""Pure, persisted candidate calculation. Never replaces production routing.

Strength is binary supported concern, not model confidence or probability.
Unvalidated operating points exist only for offline comparison.
"""
from decimal import Decimal

VERSION = 'grouped-two-axis-2026-10-22-v1'
GROUPS = {
 'internal_duplicate':('image_reuse',.8), 'external_corpus':('image_reuse',.8),
 'plate_ocr':('identity',.6), 'entity_graph':('identity',.4),
 'scene_consistency':('incident',.6), 'damage_plausibility':('incident',.4),
 'baseline_linkage':('vehicle_history',.4), 'severity_progression':('vehicle_history',.4),
 'exif_metadata':('provenance',.3), 'c2pa_credentials':('provenance',.3),
}
OPERATING_POINTS = (.20,.45,.75)


def calculate(explanation, evidence_ids=()):
    rows=explanation.get('findings') or []
    requirements=(explanation.get('coverage') or {}).get('requirements') or {}
    per_check=[]; groups={}; garage=[]
    for key in sorted(set(requirements)|{r['check_id'] for r in rows}):
        findings=[r for r in rows if r['check_id']==key]
        group,weight=GROUPS.get(key,(None,0.0))
        eligible=[r for r in findings if r.get('execution_state')=='completed'
                  and r.get('verdict')=='concern' and (r.get('eligibility') or {}).get('eligible')
                  and r.get('registered_weight',0)>0]
        # Garage concerns are separately attributed, never claimant-index inputs.
        garage += [r['finding_id'] for r in eligible if r.get('attributed_to')=='garage' or key=='threshold_gaming']
        eligible=[r for r in eligible if r.get('attributed_to')!='garage' and key!='threshold_gaming']
        strength=float(bool(eligible)) if weight else 0.0
        value=weight*strength
        if group:groups[group]=max(groups.get(group,0.0),value)
        per_check.append(dict(check_id=key,group=group,a=weight,e=strength,value=value,
          finding_ids=[r['finding_id'] for r in findings],supported_ids=[r['finding_id'] for r in eligible],
          exclusion=None if eligible and weight else 'No supported eligible concern; zero-weight, incomplete, non-concern or separately attributed',
          attribution=[r.get('attributed_to') for r in findings],
          thresholds=[r.get('rule_parameters',{}) for r in findings]))
    material=[(k,r) for k,r in requirements.items() if r.get('required') and r.get('applicable')]
    denominator=len(material);numerator=sum(bool(r.get('evidence_sufficient')) for _,r in material)
    gaps=[k for k,r in material if not r.get('evidence_sufficient')]
    residual=Decimal(1)
    for value in groups.values():residual *= Decimal(1)-Decimal(str(value))
    concern=float(Decimal(1)-residual) if rows else None
    coverage=numerator/denominator if denominator else None
    band=(None if concern is None or coverage is None else 'Low' if concern<.20 else 'Medium' if concern<.45 else 'High' if concern<.75 else 'Very high')
    recommendation=('not_assessable' if coverage is None or concern is None else
       'request_evidence' if gaps or coverage<.60 else 'investigate' if concern>=.75 else
       'desk_review' if concern>=.20 or garage else 'candidate_clear')
    return dict(version=VERSION,status='shadow_only',case_id=explanation.get('case_id'),run_id=explanation.get('run_id'),
      case_type=explanation.get('case_type'),evidence_ids=list(evidence_ids),
      formula='R = 1 - product(1 - max(a_j * e_j)); C = sum(b_j * s_j) / sum(b_j)',
      strength_basis='Binary completed eligible concern; heuristic confidence is not multiplied',
      checks=per_check,groups=groups,concern_index=concern,coverage=coverage,
      coverage_numerator=numerator,coverage_denominator=denominator,coverage_weight=1,
      mandatory_gaps=gaps,material_requirements=requirements,garage_alert_ids=garage,
      candidate_category=band,candidate_recommendation=recommendation,
      model_recommendation=(explanation.get('routing') or {}).get('model_recommendation'),
      effective_routing=(explanation.get('routing') or {}).get('effective_recommendation'),
      operating_points={'concern':[.20,.45,.75],'coverage':.60,'validated':False},
      limitation='Unvalidated bounded heuristic, not a fraud probability. Production model routing and human decisions are unchanged.')
