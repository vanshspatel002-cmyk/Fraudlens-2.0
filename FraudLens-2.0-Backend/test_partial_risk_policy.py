"""Controlled policy scenarios, deliberately separate from classifier accuracy."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from src.risk_presentation import assessment_presentation, PARTIAL_POLICY
from src import api, runtime_store
from test_risk_presentation import saved
from test_partial_review import pipeline
from test_pilot_workflow import client, auth
from test_customer_workflow import customer, owned_submit


def finding(check, state='completed', verdict='concern', weight=1, subject='image'):
    return {'finding_id':'fixture-'+check,'check_id':check,'execution_state':state,'verdict':verdict,
            'registered_weight':weight,'eligibility':{'eligible':weight>0 and state=='completed' and verdict=='concern'},
            'attributed_to':subject,'explanation':'Controlled '+check+' finding; no live qualification.'}


def partial(rows):
    report=saved();report['processing']['status']='completed_partial'
    explanation=report['assessment_explanation'];explanation['coverage'].update(material_complete=False,material_gap_ids=['scene_consistency'])
    explanation['routing'].update(source='fallback',converged=False)
    explanation['findings']=rows
    return report


@pytest.mark.parametrize('band,display',[('clear','LOW'),('request_evidence','MEDIUM'),('desk_review','MEDIUM'),('escalate_siu','HIGH')])
def test_completed_model_policy(band,display):
    result=assessment_presentation(saved(band=band))
    assert result['display_band']==display and result['complete'] and not result['provisional']
    assert result['score'] is None and result['basis']=='Completed AI-assisted assessment'


@pytest.mark.parametrize('rows,expected',[
    ([], 'UNASSESSED'),
    ([finding('plate_ocr',verdict='pass')], 'UNASSESSED'),
    ([finding('plate_ocr',state='inconclusive')], 'UNASSESSED'),
    ([finding('internal_duplicate',state='failed')], 'UNASSESSED'),
    ([finding('view_completeness',weight=0)], 'UNASSESSED'),
    ([finding('threshold_gaming',subject='garage')], 'UNASSESSED'),
    ([finding('internal_duplicate')], 'MEDIUM'),
    ([finding('internal_duplicate'),finding('external_corpus'),finding('baseline_linkage')], 'MEDIUM'),
    ([finding('plate_ocr',subject='vehicle'),finding('internal_duplicate')], 'HIGH'),
])
def test_outage_policy_with_actual_saved_execution_states(rows,expected):
    report=partial(rows);original=deepcopy(report);result=assessment_presentation(report)
    assert report==original and result['display_band']==expected
    assert not result['complete'] and result['score'] is None and result['manual_review_required']
    assert result['display_policy_version']==PARTIAL_POLICY
    assert result['provisional']==(expected!='UNASSESSED')
    assert result['missing_check_ids']==['scene_consistency']
    assert len(result['check_results'])==len(rows)


@pytest.mark.parametrize('change',['stale','running','failed','no_run'])
def test_partial_concerns_require_terminal_run_bound_results(change):
    report=partial([finding('internal_duplicate')])
    if change=='stale':report['assessment_explanation']['run_id']='old'
    elif change=='no_run':report['run_id']=None
    else:report['processing']['status']=change
    assert assessment_presentation(report)['display_band']=='UNASSESSED'


def test_material_gap_never_turns_completed_clearance_or_provider_outage_into_low():
    report=saved(band='clear');report['assessment_explanation']['coverage']['material_complete']=False
    assert assessment_presentation(report)['display_band']=='UNASSESSED'
    report['processing']['status']='completed_partial'
    report['agent_recommendation']={'provider_unavailable':True}
    assert assessment_presentation(report)['display_band']=='UNASSESSED'


@pytest.mark.parametrize('rows,band',[([finding('internal_duplicate')],'MEDIUM'),
    ([finding('internal_duplicate'),finding('plate_ocr',subject='vehicle')],'HIGH')])
def test_pdf_uses_saved_provisional_values_without_reclassifying(rows,band):
    from scripts.build_visual_report_samples import fixture
    from src.report_pdf import render_pdf
    report=fixture('claims','Low');contract=assessment_presentation(partial(rows))
    report['assessment_presentation']=contract
    front=PdfReader(BytesIO(render_pdf(report,'controlled-partial',1792569600))).pages[0].extract_text()
    assert contract['label'] in front and band in front
    assert 'Findings supporting the display band' in front
    assert '[vehicle]' in front if band=='HIGH' else '[image]' in front
    assert 'Assessed risk: Low' not in front and 'Heuristic score' not in front


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_job_list_detail_snapshot_pdf_reuse_the_persisted_contract(client,pipeline,kind,monkeypatch):
    receipt=owned_submit(client,customer(client),kind).json();run,_=pipeline
    run(receipt['job_id'],receipt['case_id']);reviewer=auth(client)
    path='/v1/cases/'+receipt['case_id']
    report=client.get(path+'/report',headers=reviewer).json();contract=report['assessment_presentation']
    assert contract['run_id']==receipt['job_id'] and contract['display_band']=='UNASSESSED'
    from src import risk_presentation
    monkeypatch.setattr(risk_presentation,'assessment_presentation',lambda *a,**k:pytest.fail('Saved assessment was recomputed on read'))
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.get_job(conn,receipt['job_id'])
        assert job['assessment_presentation']==contract
        snapshot=json.loads(conn.execute('SELECT payload FROM report_snapshots WHERE run_id=?',(receipt['job_id'],)).fetchone()[0])
        assert snapshot['assessment_presentation']==contract
    row=next(row for row in client.get('/v1/cases',headers=reviewer).json()['items'] if row['case_id']==receipt['case_id'])
    assert row['assessment_presentation']==contract
    filtered=client.get('/v1/cases?display_band=UNASSESSED',headers=reviewer).json()
    assert any(row['case_id']==receipt['case_id'] for row in filtered['items'])
    prepared=client.post(path+'/reports/prepare',headers=reviewer).json()
    content=client.get(path+'/reports/'+prepared['snapshot_id']+'/pdf',headers=reviewer).content
    front=PdfReader(BytesIO(content)).pages[0].extract_text()
    assert 'UNASSESSED' in front and 'insufficient evidence' in front
    # New connections simulate reader restart; no rebuilding from live registry.
    with runtime_store.connection(api.DB_PATH) as conn:
        assert api._build_report(conn,receipt['case_id']).assessment_presentation==contract
