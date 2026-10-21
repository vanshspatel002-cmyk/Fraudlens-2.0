"""Controlled visual fixtures only. No API, provider, application DB or worker."""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import baseline, report_pdf
from src.agent.production_policy import production_policy
from src.assessment_explanation import explain_assessment
from src.checks import REGISTRY
from src.models import AgentDecision, Case, Finding, RiskBand, Recommendation, Verdict
from src.risk_presentation import assessment_presentation


def photograph(index=0):
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(720,420),'#e5eded'); draw=ImageDraw.Draw(image)
    draw.rectangle((0,310,720,420),fill='#bdc9ca')
    draw.rounded_rectangle((130,185,585,315),35,fill=['#287a80','#4e647f','#a26751'][index%3])
    draw.polygon([(220,185),(285,100),(450,100),(520,185)],fill='#34666f')
    draw.polygon([(240,174),(294,113),(365,113),(365,174)],fill='#b8d8dd')
    draw.polygon([(380,113),(442,113),(495,174),(380,174)],fill='#b8d8dd')
    for x in (235,505):
        draw.ellipse((x-43,273,x+43,359),fill='#24363e');draw.ellipse((x-22,294,x+22,338),fill='#c2cfd3')
    draw.rectangle((165,248,285,275),fill='white');draw.text((171,254),'MH12EX1203',fill='#203941')
    draw.text((20,20),'FICTIONAL VISUAL FIXTURE / NOT LIVE ANALYSIS',fill='#203941')
    draw.text((20,393),f'Saved photograph {index+1} - authored illustration, not detector validation',fill='#203941')
    buffer=BytesIO();image.save(buffer,'JPEG',quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def fixture(kind='claims', category='High', incomplete=False, category_only=False):
    policy=production_policy(kind); case_id='visual-'+kind; run_id=case_id+'-run-1'
    case=Case(case_id=case_id,claimant_id='fictional',garage_id='EXAMPLE-GARAGE',claim_type='collision' if kind=='claims' else 'inspection',
              agent_type=kind,vehicle_registration='MH12EX1203',claim_amount=48000 if kind=='claims' else None)
    duplicate_concern=category=='High' or category_only and category=='Medium'
    editing_observation=category=='Medium' and not category_only
    rows={
        'internal_duplicate': ('concern' if duplicate_concern else 'pass','The saved image comparison exceeded the recorded similarity rule. A reviewer should verify the matched photograph.' if duplicate_concern else 'The saved internal comparison remains below the recorded concern thresholds.',
            {'image_id':'photo-1','matched_image_id':'reference-1','matched_case_id':'visual-reference','cosine_similarity':.97 if duplicate_concern else .83,'hamming_distance':2 if duplicate_concern else 18,'images_compared':12,'submission_role':'later'}),
        'external_corpus': ('pass','The saved reference-corpus comparison did not reach its concern thresholds.',{'image_id':'photo-2','cosine_similarity':.83,'hamming_distance':18,'corpus_size':24}),
        'plate_ocr': ('concern' if category=='Medium' and not category_only else 'pass','The saved registration text is shown alongside the declaration for review.',
            {'image_id':'photo-3','plate_candidate':'MH12EX1208' if category=='Medium' and not category_only else 'MH12EX1203','ocr_confidence':1.0,'comparison_status':'mismatch' if category=='Medium' and not category_only else 'match','ocr_status':'candidate_read'}),
        'exif_metadata': ('concern' if editing_observation else 'pass','The saved Software field names an editing tool; this has benign explanations and does not prove manipulation.' if editing_observation else 'The saved capture fields are available. Their authenticity has not been independently established.',{'image_id':'photo-1','exif_present':True,'exif_gps':{'lat':19.0,'lon':72.0},'gps_distance_km':.4,'exif_capture_time':'2026-10-19T08:00:00+00:00',**({'software':'Adobe Photoshop'} if editing_observation else {})}),
        'c2pa_credentials': ('pass','Embedded credentials validated under the saved local policy; the incident itself is not verified.',{'image_id':'photo-1','credentials_present':True,'validation_state':'Valid'}),
        'entity_graph': ('pass','A single shared contact has innocent explanations; this relationship does not establish fraud.',{'identifiers_examined':['contact'],'linked_cases':{'visual-linked':['contact']}}),
        'scene_consistency': ('pass','Recorded scene observations are compatible with the declared account in this controlled fixture.',{'image_id':'photo-1','declared_time_basis':'aware_instant','observed_shadow_direction':'NW','expected_shadow_direction':'NW','shadow_bearing_difference_deg':12,'weather_status':'consistent'}),
        'damage_plausibility': ('pass','The saved severity label and claim amount are compared without converting damage area into a physical percentage.',{'claim_amount_inr':48000,'severity_used':'moderate','observed_severities':['moderate'],'ratio_to_ceiling':.96,'ceiling_tolerance':1.5}),
        'threshold_gaming': ('pass','The recorded garage share does not exceed the implemented research benchmark.',{'amount':48000,'band_low':45000,'band_high':50000,'garage_claim_count':12,'garage_in_band_pct':25,'garage_concern_pct':40,'minimum_garage_claims':5}),
        'baseline_linkage': ('pass','A dated earlier inspection is recorded; it is not a certificate of an undamaged vehicle.',{'prior_inspections_found':1,'inspections':[{'inspection_time':'2026-10-01T08:00:00+00:00','days_before_claim':18,'damage_severity':'minor'}]}),
        'severity_progression': ('pass','Saved observations use ordered severity labels, not a physical damage percentage.',{'sequence':[{'declared_time':'2026-10-01T08:00:00+00:00','severity':'minor'},{'declared_time':'2026-10-19T08:00:00+00:00','severity':'moderate'}]}),
        'ai_generation': ('inconclusive','An experimental classifier output was saved but excluded from routing.',{'image_id':'photo-1','artificial_probability':.87,'demoted':True,'weight':0}),
        'digital_edit': ('inconclusive','Experimental image-edit observations were excluded from routing.',{'image_id':'photo-1','calibrated':False,'concern_threshold':.6,'combined_score':.24}),
        'view_completeness': ('inconclusive','Photo-slot labels and visual variety do not establish that all views show one vehicle.',{'distinct_views':4,'required_views':4,'plate_seen':True}),
        'baseline_corruption': ('inconclusive','No absence-of-damage declaration was inferred from the underwriting application.',{'declared_condition':'Disclosed damage','contradicting_severity':'minor'}),
    }
    findings=[]
    for check_id,(verdict,narrative,evidence) in rows.items():
        evidence={**evidence,'execution_state':'inconclusive' if verdict=='inconclusive' else 'completed'}
        if kind=='underwriting' and check_id in {'baseline_linkage','severity_progression','threshold_gaming','damage_plausibility'}:
            verdict='inconclusive';evidence={'execution_state':'not_applicable','reason':'Claims-only comparison'};narrative='This claims-only comparison is not applicable to an underwriting inspection.'
        if incomplete and check_id in {'plate_ocr','scene_consistency'}:
            verdict='inconclusive';evidence={'image_id':'photo-3','execution_state':'failed' if check_id=='scene_consistency' else 'not_run','reason':'Compatible observation not available'};narrative='A compatible saved observation was unavailable; no replacement measurement is invented.'
        confidence=1.0 if verdict=='concern' else .8 if verdict=='pass' else 0.0
        if check_id=='internal_duplicate':
            # Exercise the real saved comparison thresholds/confidence rule,
            # without embedding images or running a model.
            check=REGISTRY[check_id]
            _,confidence,_=check._verdict_for([(None,evidence['cosine_similarity'],evidence['hamming_distance'])],check.HAMMING_CONCERN,check.COSINE_CONCERN,check.COSINE_FLOOR,check.COSINE_INCONCLUSIVE)
        elif verdict=='concern' and check_id in {'plate_ocr','exif_metadata'}:
            confidence=.85
        findings.append(Finding(check_id=check_id,case_id=case_id,category=REGISTRY[check_id].category,verdict=Verdict(verdict),confidence=confidence,explanation=narrative,evidence=evidence))
    if category=='High' and not category_only:
        first=findings[0]
        findings.append(Finding(check_id=first.check_id,case_id=case_id,category=first.category,verdict=first.verdict,confidence=first.confidence,
            explanation='A second submitted photograph also meets the recorded internal comparison rule; verify the reference and submission chronology.',evidence={**first.evidence,'image_id':'photo-4'}))
    if category_only:
        decision=AgentDecision(case_id=case_id,risk_band=RiskBand({'Low':'clear','Medium':'desk_review','High':'escalate_siu'}[category]),recommendation=Recommendation.ESCALATE if category!='Low' else Recommendation.APPROVE,
            confidence=.7,summary='Controlled fixture of saved category routing; no model request was made.',supporting_finding_ids=[findings[0].finding_id],policy_version=policy.policy_version)
    else:
        decision=baseline.decide(findings,case)
    explanation=explain_assessment(case,findings,decision,policy,converged=not incomplete,run_id=run_id,use_agent=category_only)
    serialized=[]
    for index,finding in enumerate(findings):
        row=asdict(finding);row['category']=finding.category.value;row['verdict']=finding.verdict.value
        serialized.append(row)
    grouped={}
    for row in serialized:grouped.setdefault(row['category'],[]).append(row)
    report={'case_id':case_id,'illustrative_fixture':True,'run_id':run_id,'report_template_version':report_pdf.RENDERER_VERSION,'submitted_at':'2026-10-20T08:00:00+00:00','policy_version':decision.policy_version,
        'declaration':{'agent_type':kind,'person_name':'Fictional Example','vehicle_registration':'MH12EX1203','vehicle_make':'Example','vehicle_model':'Demonstrator','vehicle_year':2023,'claim_amount':case.claim_amount,'policy_number':'FICTIONAL-POLICY',
                       'declared_location':'Fictional Junction','declaration_notes':'CONTROLLED SOFTWARE / LAYOUT FIXTURE. No live model assessment or detection accuracy is established.'},
        'processing':{'job_id':run_id,'status':'failed' if incomplete else 'completed','stage':'needs_review' if incomplete else 'complete'},
        'agent_recommendation':{**asdict(decision),'risk_band':decision.risk_band.value,'recommendation':decision.recommendation.value,'provider_unavailable':incomplete},
        'assessment_explanation':explanation,'findings_by_category':grouped,'evidence_ids':[f'photo-{index+1}' for index in range(6)],
        'evidence_inventory':[{'image_id':f'photo-{index+1}','label':f'Photograph {index+1}','thumbnail_base64':photograph(index),'considered_in_run':True,
                               'extracted_metadata':{'DateTimeOriginal':'2026:10:19 13:30:00','Make':'Fixture camera','Software':'Not recorded'}} for index in range(6)],
        'comparison_evidence':[{'image_id':'reference-1','label':'Internal reference','access_basis':'reviewer_only','thumbnail_base64':photograph(0)}],
        'check_inventory':[{'check_id':key,'state':(explanation['coverage']['check_states'].get(key) or 'inconclusive'),'applicable':key in policy.check_ids,'purpose':report_pdf.CHECK_PURPOSES[key]} for key in REGISTRY],
        'limitations':['Controlled authored fixture only. The graphics do not demonstrate improved analysis accuracy.']}
    report['assessment_presentation']=assessment_presentation(report)
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT.parent/'docs/visual_review');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    fixtures={
        'claims-high':fixture(), 'underwriting-medium':fixture('underwriting','Medium',category_only=True),
        'claims-incomplete':fixture(incomplete=True), 'underwriting-incomplete':fixture('underwriting','Medium',incomplete=True,category_only=True),
        'claims-low':fixture(category='Low'), 'claims-medium':fixture(category='Medium'),
    }
    for name,report in fixtures.items():
        (args.output/(name+'.pdf')).write_bytes(report_pdf.render_pdf(report,'controlled-'+name,1792569600))
    (args.output/'fixtures.json').write_text(json.dumps(fixtures,default=str),encoding='utf-8')
    print('Generated controlled report fixtures; no application database or model was called.')


if __name__=='__main__':main()
