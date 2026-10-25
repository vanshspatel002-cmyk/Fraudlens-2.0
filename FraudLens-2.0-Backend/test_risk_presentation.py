"""Controlled display states and actual baseline boundaries, without providers."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from src import baseline, report_pdf
from src.risk_presentation import assessment_presentation
from test_pilot_workflow import client, auth


def saved(score=None, band='desk_review', source='model'):
    return {'run_id':'fixture-run','policy_version':'fixture-policy-v1',
        'processing':{'status':'completed','job_id':'fixture-run'},
        'assessment_explanation':{'run_id':'fixture-run','policy_version':'fixture-policy-v1',
            'routing':{'source':source,'converged':True,'recorded_band':band},
            'coverage':{'material_complete':True,'check_states':{'plate_ocr':'completed'}},
            'aggregation':{'method':'weighted_concern_sum' if source=='rules_baseline' else 'model_routing',
                           'computed_value':score,'valid_numeric_score':source=='rules_baseline',
                           'thresholds':{'clear_below':baseline.CLEAR_BELOW,'request_evidence_below':baseline.REQUEST_EVIDENCE_BELOW,'desk_review_below':baseline.DESK_REVIEW_BELOW}}}}


@pytest.mark.parametrize('score,category',[(0,'Low'),(.299999999,'Low'),(.3,'Medium'),(.599999999,'Medium'),(.6,'Medium'),(.999999999,'Medium'),(1,'High'),(1.2,'High')])
def test_saved_baseline_boundaries_are_presented_without_a_second_score(score,category):
    report=saved(score,baseline.band_for(score).value,'rules_baseline')
    contract=assessment_presentation(report)
    assert contract['category']==category and contract['score']==score
    assert contract['position_basis']=='category_only'
    assert 'Unbounded' in contract['score_scale']


def test_model_category_never_uses_confidence_or_human_decision_as_score():
    report=saved();report['admin_action']={'action':'approve'}
    report['agent_recommendation']={'confidence':.99,'score':None}
    assert assessment_presentation(report)['category']=='Medium'
    assert assessment_presentation(report)['score'] is None
    report['admin_action']['action']='reject'
    assert assessment_presentation(report)['category']=='Medium'


@pytest.mark.parametrize('state',['queued','running','failed','interrupted','partial','needs_review','unrecorded'])
def test_unfinished_assessments_never_reassure_or_manufacture_a_score(state):
    report=saved(0,'clear','rules_baseline');report['processing']['status']=state
    result=assessment_presentation(report)
    assert not result['complete'] and result['category'] is None and result['score'] is None
    assert result['display_band']=='UNASSESSED'


@pytest.mark.parametrize('reason',['coverage','fallback','run','unknown_band','missing_run','band_mismatch','unknown_source'])
def test_incomplete_or_stale_saved_basis_stays_neutral(reason):
    report=saved()
    if reason=='coverage':report['assessment_explanation']['coverage']['material_complete']=False
    if reason=='fallback':report['assessment_explanation']['routing']['source']='fallback'
    if reason=='run':report['assessment_explanation']['run_id']='earlier-run'
    if reason=='unknown_band':report['assessment_explanation']['routing']['recorded_band']='unsupported'
    if reason=='missing_run':report['run_id']=None
    if reason=='band_mismatch':report['assessment_explanation']['aggregation']['matches_recorded_band']=False
    if reason=='unknown_source':report['assessment_explanation']['routing']['source']='unsupported'
    assert assessment_presentation(report)['category'] is None


@pytest.mark.parametrize('invalid',[float('nan'),float('inf'),True,'0.3'])
def test_invalid_numeric_values_are_never_printed_as_scores(invalid):
    assert assessment_presentation(saved(invalid,'desk_review','rules_baseline'))['score'] is None


def test_an_earlier_completed_assessment_is_explicitly_historical():
    report=saved();report['assessment_context']='historical'
    result=assessment_presentation(report)
    assert result['historical'] and result['state']=='historical'
    assert result['label']=='Historical assessed risk: Medium'


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_pdf_and_api_contract_agree_and_every_saved_check_is_represented(kind):
    from scripts.build_visual_report_samples import fixture
    report=fixture(kind,'High' if kind=='claims' else 'Medium',category_only=kind=='underwriting')
    report['declaration']['engine_number']='CONTROLLED-ENGINE-REFERENCE'
    contract=report['assessment_presentation']
    assert contract==assessment_presentation(report)
    content=report_pdf.render_pdf(report,'controlled-snapshot',1792569600)
    reader=PdfReader(BytesIO(content));text=' '.join(page.extract_text() for page in reader.pages)
    assert contract['label'] in text
    for item in report['check_inventory']:
        assert report_pdf.CHECK_LABELS[item['check_id']] in text
    assert 'Technical appendix' in text and 'Saved decision parameters' in text
    assert 'CONTROLLED-ENGINE-REFERENCE' in text
    assert 'ZERO WEIGHT' in text
    assert 'OCR confidence' in text and 'fraud probability' in text
    assert len(reader.pages)<13


def test_incomplete_pdf_is_neutral_and_excludes_sensitive_text():
    from scripts.build_visual_report_samples import fixture
    report=fixture(incomplete=True)
    report['declaration']['declaration_notes']='Fixture path C:\\private\\evidence.jpg and password=DO_NOT_PRINT'
    report['findings_by_category']['identity'][0]['evidence']['api_key']='DO_NOT_PRINT'
    content=report_pdf.render_pdf(report,'fixture-snapshot',1792569600)
    reader=PdfReader(BytesIO(content));front=reader.pages[0].extract_text();all_text=' '.join(page.extract_text() for page in reader.pages)
    assert 'UNASSESSED' in front and 'Assessed risk: Low' not in front and 'Assessed risk: High' not in front
    assert 'DO_NOT_PRINT' not in all_text and 'C:\\private' not in all_text


def test_v3_renderer_remains_available_without_changing_old_snapshots():
    report={'case_id':'historical-fixture','report_template_version':report_pdf.READER_V3_VERSION,
            'declaration':{'agent_type':'claims'},'processing':{'status':'failed'}}
    original=deepcopy(report)
    content=report_pdf.render_pdf(report,'old-snapshot',1792569600)
    assert content.startswith(b'%PDF') and report==original


def test_customer_cannot_read_or_prepare_reviewer_reports(client,tmp_path):
    from test_report_pdf import seed_case
    case_id=seed_case(tmp_path)
    registered=client.post('/v1/customer/auth/register',json={'email':'visual-fixture@example.test','password':'fictional-test-password','name':'Fictional Example'})
    assert registered.status_code==201
    customer={'Authorization':'Bearer '+registered.json()['token']}
    for path in [f'/v1/cases/{case_id}/report',f'/v1/cases/{case_id}/reports']:
        assert client.get(path,headers=customer).status_code==401
    assert client.post(f'/v1/cases/{case_id}/reports/prepare',headers=customer).status_code==401
    reviewer=auth(client)
    report=client.get(f'/v1/cases/{case_id}/report',headers=reviewer)
    assert report.status_code==200
    assert report.json()['assessment_presentation']['category'] is None


def test_only_database_owned_internal_comparisons_are_frozen(client,tmp_path,monkeypatch):
    from src import api, runtime_store
    from test_report_pdf import seed_case
    current=seed_case(tmp_path,case_id='visual-current')
    reference=seed_case(tmp_path,case_id='visual-reference')
    opened=[];resolve=api._resolve_data_path
    def safe_resolve(path):
        opened.append(str(path));return resolve(path)
    monkeypatch.setattr(api,'_resolve_data_path',safe_resolve)
    with runtime_store.connection(api.DB_PATH) as conn:
        payload=api._build_report(conn,current).model_dump(mode='json')
        payload['findings_by_category']={'history':[
            {'finding_id':'controlled-internal','check_id':'internal_duplicate','verdict':'concern','evidence':{'matched_image_id':reference+'-image'}},
            {'finding_id':'controlled-external','check_id':'external_corpus','verdict':'concern','evidence':{'matched_filename':'C:\\private\\do-not-open.jpg'}}]}
        frozen=report_pdf.enrich_snapshot(conn,payload)
    assert len(frozen['comparison_evidence'])==1
    assert frozen['comparison_evidence'][0]['access_basis']=='reviewer_only'
    assert frozen['comparison_evidence'][0]['thumbnail_base64']
    assert all('do-not-open' not in path for path in opened)
    assert not any('path' in item for item in frozen['comparison_evidence'])
