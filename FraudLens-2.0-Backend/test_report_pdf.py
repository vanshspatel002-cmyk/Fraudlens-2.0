"""Real local PDF rendering/storage/auth contracts; no AI or application DB writes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from src import api, db, report_pdf, runtime_store
from src.models import Case, Image
from test_pilot_workflow import client, auth, photo


def seed_case(tmp_path, kind='claims', status='failed', case_id='pdf-case'):
    path = tmp_path / (case_id + '.png'); path.write_bytes(photo())
    with runtime_store.connection(api.DB_PATH) as conn:
        db.insert_case(conn, Case(case_id=case_id,claimant_id='fictional',garage_id='UNASSIGNED',claim_type='collision' if kind=='claims' else 'inspection',agent_type=kind,
            person_name='Fictional Example',policy_number='EXAMPLE-POLICY',vehicle_registration='MH12EX1234',
            claim_amount=42500 if kind=='claims' else None,idv=450000,person_address='12 Fictional Lane',
            declaration_notes='Applicant states that the vehicle sustained damage at a fictional junction.'))
        db.save_image(conn,Image(image_id=case_id+'-image',case_id=case_id,path=str(path),content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),phash='a'*16,dhash='b'*16,exif={'Make':'Example camera'}))
        job = runtime_store.enqueue(conn,case_id); job.update(status=status,stage='needs_review' if status=='failed' else 'complete',detail='Automated analysis unavailable; submitted evidence is saved.',error_type='ProviderUnavailable')
        runtime_store.save_job(conn,job)
    return case_id


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_pdf_private_durable_idempotent(client,tmp_path,monkeypatch,kind):
    case_id=seed_case(tmp_path,kind); headers=auth(client); path=f'/v1/cases/{case_id}/reports'
    assert client.post(path+'/prepare').status_code==401
    ready=client.post(path+'/prepare',headers=headers)
    assert ready.status_code==200,ready.text
    version=ready.json(); assert version['pdf_status']=='ready'
    snapshot=version['snapshot_id']; url=path+'/'+snapshot+'/pdf'
    assert client.get(url).status_code==401
    assert client.get('/v1/cases/another-case/reports/'+snapshot+'/pdf',headers=headers).status_code==404
    first=client.get(url,headers=headers)
    assert first.status_code==200 and first.content.startswith(b'%PDF-')
    assert first.headers['content-type']=='application/pdf'
    assert first.headers['content-disposition'].startswith('inline; filename="FraudLens-')
    assert 'no-store' in first.headers['cache-control']
    assert client.get(url+'?download=true',headers=headers).headers['content-disposition'].startswith('attachment;')
    text=' '.join(' '.join(page.extract_text().split()) for page in PdfReader(BytesIO(first.content)).pages)
    for expected in ['Partial analysis','Applicant statements','Not run','no completed analysis inventory','calibrated fraud probability','ProviderUnavailable']:
        assert expected.lower() in text.lower(),expected
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_artifacts').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==1
        payload=json.loads(conn.execute('SELECT payload FROM report_snapshots').fetchone()[0])
        assert payload['evidence_inventory'][0]['thumbnail_base64']
        assert payload['evidence_inventory'][0]['considered_in_run'] is False
        assert all(c['state']=='not_run' for c in payload['check_inventory'])
    def forbidden(*args,**kwargs): raise AssertionError('Existing artifact must not render or analyze again')
    monkeypatch.setattr(report_pdf,'render_pdf',forbidden)
    assert client.post(path+'/prepare',headers=headers).json()['snapshot_id']==snapshot
    assert client.get(url,headers=headers).content==first.content


def test_pdf_failure_retry_keeps_snapshot(client,tmp_path,monkeypatch):
    case_id=seed_case(tmp_path); headers=auth(client); path=f'/v1/cases/{case_id}/reports'
    renderer=report_pdf.render_pdf
    def fail(*args): raise OSError('Private machine path must never be returned')
    monkeypatch.setattr(report_pdf,'render_pdf',fail)
    response=client.post(path+'/prepare',headers=headers)
    assert response.status_code==503 and response.json()['code']=='PDF_GENERATION_FAILED'
    assert 'Private machine' not in response.text
    listed=client.get(path,headers=headers).json()['reports']; assert len(listed)==1 and listed[0]['pdf_status']=='failed'
    monkeypatch.setattr(report_pdf,'render_pdf',renderer)
    retry=client.post(path+'/prepare?snapshot_id='+listed[0]['snapshot_id'],headers=headers)
    assert retry.status_code==200 and retry.json()['pdf_status']=='ready'
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==1
        assert runtime_store.latest_job(conn,case_id)['status']=='failed'


def test_pdf_pending_does_not_snapshot_active_analysis(client,tmp_path):
    case_id=seed_case(tmp_path,status='queued'); headers=auth(client)
    assert client.post(f'/v1/cases/{case_id}/reports/prepare',headers=headers).status_code==409
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==0


def test_saved_pdf_unchanged_after_decision_and_source_removal(client,tmp_path):
    case_id=seed_case(tmp_path); headers=auth(client); path=f'/v1/cases/{case_id}/reports'
    first=client.post(path+'/prepare',headers=headers).json(); snapshot=first['snapshot_id']
    before=client.get(path+'/'+snapshot+'/pdf',headers=headers).content
    detail=client.get(f'/v1/cases/{case_id}',headers=headers).json()
    action=client.post(f'/v1/cases/{case_id}/action',headers=headers,json={'action':'approve','reason':'Actual photograph manually reviewed; provider unavailable.','public_message':'Your claim has been approved.','manual_review_override':True,
        'expected_revision':detail['review_revision'],'expected_run_id':detail['processing']['job_id'],'expected_evidence_ids':[image['image_id'] for image in detail['images']]})
    assert action.status_code==200,action.text
    Path(tmp_path / (case_id+'.png')).unlink()
    assert client.get(path+'/'+snapshot+'/pdf',headers=headers).content==before
    # Generating the existing saved snapshot again retains its frozen thumbnail.
    assert client.post(path+'/prepare?snapshot_id='+snapshot,headers=headers).json()['sha256']==first['sha256']
    with runtime_store.connection(api.DB_PATH) as conn:
        payload=json.loads(conn.execute('SELECT payload FROM report_snapshots WHERE snapshot_id=?',(snapshot,)).fetchone()[0])
        assert payload['admin_action'] is None


def test_long_pdf_layout_and_all_execution_states(tmp_path):
    paragraph='Long fictional narrative with <markup> & escaped characters, ₹42,500, a measured observation and a stated limitation. '*90
    states=['completed','inconclusive','failed','not_run','not_applicable']
    report={'case_id':'layout-fixture','run_id':'offline-controlled-fixture','submitted_at':'2026-10-18T06:00:00+00:00',
        'declaration':{'agent_type':'claims','person_name':'Fictional Example','declaration_notes':paragraph},
        'processing':{'status':'failed','error_type':'ProviderUnavailable'},
        'evidence_ids':[],'findings_by_category':{'identity':[{'finding_id':'recorded-finding','check_id':'plate_ocr','verdict':'inconclusive','attributed_to':'vehicle','explanation':paragraph,'evidence':{'observed_text':paragraph,'image_id':'evidence-fixture'}}]},
        'check_inventory':[{'check_id':str(index),'purpose':'Fixture check','state':state,'finding_ids':[]} for index,state in enumerate(states)],'limitations':['Controlled offline rendering fixture; no model was called.']}
    content=report_pdf.render_pdf(report,'a'*64,1792303200)
    reader=PdfReader(BytesIO(content)); assert len(reader.pages)>3
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert '₹42,500' in text and '<markup>' in text
    for state in states: assert state.replace('_',' ') in text
    for page in reader.pages:
        assert page.extract_text().strip()
        assert 'Page ' in page.extract_text()
    # Persist a standalone artifact for a human/rendered inspection when requested.
    (tmp_path/'long-layout.pdf').write_bytes(content)
