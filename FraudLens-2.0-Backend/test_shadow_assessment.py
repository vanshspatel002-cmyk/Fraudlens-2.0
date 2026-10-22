from copy import deepcopy
import pytest
from src.shadow_assessment import calculate
from test_pilot_workflow import client

def test_experimental_loader_failure_retains_only_safe_error_type(monkeypatch):
 import builtins
 from src.checks import ai_detection
 original=builtins.__import__
 def controlled(name,*args,**kwargs):
  if name=='transformers':raise RuntimeError('private cache path and credential-like payload')
  return original(name,*args,**kwargs)
 monkeypatch.setattr(ai_detection,'_load_attempted',False)
 monkeypatch.setattr(ai_detection,'_pipeline',None)
 monkeypatch.setattr(ai_detection,'_load_error',None)
 monkeypatch.setattr(builtins,'__import__',controlled)
 assert ai_detection.get_pipeline() is None
 assert ai_detection._load_error=='RuntimeError'

@pytest.mark.parametrize('latitude,longitude', [('91','20'),('nan','20'),('20','181'),('20',None)])
def test_invalid_coordinates_are_rejected_before_processing(client,latitude,longitude):
 data={'vehicle_registration':'MH12EX1203','agent_type':'claims','latitude':latitude}
 if longitude is not None:data['longitude']=longitude
 response=client.post('/v1/cases',data=data)
 assert response.status_code==422 and response.json()['code']=='INVALID_COORDINATES'

def base(kind='claims'):
 return dict(run_id='fixture-run',case_type=kind,findings=[],routing={'model_recommendation':'approve','effective_recommendation':'request_evidence'},coverage={'requirements':{'plate_ocr':dict(required=True,applicable=True,evidence_sufficient=True)}})

def row(key='internal_duplicate',attribution='image'):
 return dict(check_id=key,finding_id=key,execution_state='completed',verdict='concern',registered_weight=1,eligibility={'eligible':True},attributed_to=attribution)

@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_duplicate_and_correlated_findings_do_not_inflate(kind):
 a=base(kind);a['findings']=[row()];one=calculate(a)
 a['findings']*=9;a['findings'].append(row('external_corpus'))
 assert calculate(a)['concern_index']==one['concern_index']==.8
 assert one['effective_routing']=='request_evidence' and one['status']=='shadow_only'

def test_missing_mandatory_never_clears_and_no_denominator_abstains():
 a=base();a['findings']=[{**row(), 'verdict':'pass'}]
 assert calculate(a)['candidate_recommendation']=='candidate_clear'
 a['coverage']['requirements']['plate_ocr']['evidence_sufficient']=False
 assert calculate(a)['candidate_recommendation']=='request_evidence'
 a['coverage']['requirements']={}
 assert calculate(a)['coverage'] is None and calculate(a)['candidate_recommendation']=='not_assessable'

def test_experiments_garage_and_incomplete_do_not_become_claimant_concerns():
 a=base();a['findings']=[row('threshold_gaming','garage'),{**row('ai_generation'),'registered_weight':0},{**row(),'execution_state':'inconclusive'}]
 out=calculate(a);assert out['concern_index']==0 and out['garage_alert_ids']==['threshold_gaming']
 assert out['candidate_recommendation']=='desk_review'

def test_pure_inputs_and_comparison_to_simple_group_maximum():
 a=base();a['findings']=[row(),row('plate_ocr')];before=deepcopy(a);out=calculate(a)
 assert a==before and out['concern_index']==pytest.approx(.92)
 assert max(out['groups'].values())==.8

@pytest.mark.parametrize('weight,category',[(.199999,'Low'),(.2,'Medium'),(.45,'High'),(.75,'Very high')])
def test_exact_candidate_boundaries(monkeypatch,weight,category):
 from src import shadow_assessment
 monkeypatch.setitem(shadow_assessment.GROUPS,'internal_duplicate',('image_reuse',weight))
 a=base();a['findings']=[row()]
 assert calculate(a)['candidate_category']==category

@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_saved_explanation_and_pdf_share_candidate(kind):
 from scripts.build_visual_report_samples import fixture
 from src.report_pdf import render_pdf
 from pypdf import PdfReader
 from io import BytesIO
 report=fixture(kind,'Medium',category_only=True)
 shadow=report['assessment_explanation']['shadow_assessment']
 assert shadow['status']=='shadow_only'
 text=' '.join(page.extract_text() for page in PdfReader(BytesIO(render_pdf(report,'fixture',1792650000))).pages)
 assert 'SHADOW ONLY' in text and str(shadow['concern_index']) in text
