"""Versioned sufficiency policy; never changes a finding or the model output."""
VERSION = 'material-evidence-2026-10-22-v3'
OPTIONAL = {
    'exif_metadata': 'EXIF is optional provenance; absence is not manipulation.',
    'c2pa_credentials': 'Signed credentials are optional provenance; absence is not manipulation.',
    'threshold_gaming': 'Research repairer-pattern benchmark is advisory, not a clearance requirement.',
}


def assess(expected, states, rows, registry, input_requirements=None):
    requirements = {}; gaps = []
    for key in expected:
        state = states[key]; check = registry.get(key)
        weight = float(check.weight) if check else 0
        experimental = bool(check and weight == 0)
        optional = experimental or key in OPTIONAL
        applicable = state != 'not_applicable'
        # A genuinely absent historical comparison is N/A, never a clean match.
        reason = ('Zero-weight experimental observation; not a material requirement.' if experimental
                  else OPTIONAL.get(key) or 'Applicable identity, comparison, context or damage evidence is required for actionable routing.')
        sufficient = state == 'completed' or not applicable
        saved = [r for r in rows if r['check_id'] == key]
        if key == 'internal_duplicate' and saved and all(r.get('observed_values', {}).get('images_compared') == 0 for r in saved):
            applicable = False; sufficient = True
            reason = 'No eligible other image exists in this comparison corpus. History comparison is not applicable; clean real-world history is not established.'
        if key == 'plate_ocr' and any(r['execution_state'] == 'completed' for r in saved):
            sufficient = True
            reason = 'At least one plate comparison completed. Other close-ups need not contain a readable plate; same-vehicle identity across all images is not established by labels alone.'
        requirements[key] = dict(required=not optional, applicable=applicable,
            executed=state in {'completed','inconclusive'}, evidence_sufficient=sufficient,
            execution_state=state, reason=reason)
        if not optional and not sufficient:
            gaps.append(key)
    for key,requirement in (input_requirements or {}).items():
        requirements[key]=requirement
        if requirement['required'] and requirement['applicable'] and not requirement['evidence_sufficient']:gaps.append(key)
    return dict(version=VERSION, requirements=requirements, material_gap_ids=gaps,
                material_complete=not gaps)
