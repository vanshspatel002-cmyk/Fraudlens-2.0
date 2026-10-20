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
    for expected in ['Partial analysis','Applicant statements','Not run','no completed analysis inventory','calibrated fraud probabilit','structured calculation explanation was not recorded']:
        assert expected.lower() in text.lower(),expected
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_artifacts').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==1
        payload=json.loads(conn.execute('SELECT payload FROM report_snapshots').fetchone()[0])
        assert payload['evidence_inventory'][0]['thumbnail_base64']
        assert payload['evidence_inventory'][0]['considered_in_run'] is False
        assert payload['report_template_version']==report_pdf.RENDERER_VERSION
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


def test_new_report_template_creates_new_version_and_keeps_legacy_bytes(client,tmp_path):
    case_id=seed_case(tmp_path);headers=auth(client);path=f'/v1/cases/{case_id}/reports'
    with runtime_store.connection(api.DB_PATH) as conn:
        payload=api._build_report(conn,case_id).model_dump(mode='json')
        payload.pop('report_template_version',None)
        saved=json.dumps(payload);legacy_id=runtime_store.digest(saved)
        conn.execute('INSERT INTO report_snapshots(snapshot_id,case_id,run_id,payload,created_at) VALUES (?,?,?,?,?)',
            (legacy_id,case_id,payload['run_id'],saved,1000))
    legacy=client.post(path+'/prepare?snapshot_id='+legacy_id,headers=headers)
    assert legacy.status_code==200 and legacy.json()['renderer_version']==report_pdf.LEGACY_RENDERER_VERSION
    original=client.get(path+'/'+legacy_id+'/pdf',headers=headers).content
    latest=client.post(path+'/prepare',headers=headers)
    assert latest.status_code==200 and latest.json()['snapshot_id']!=legacy_id
    assert latest.json()['renderer_version']==report_pdf.RENDERER_VERSION
    assert client.get(path+'/'+legacy_id+'/pdf',headers=headers).content==original
    listed=client.get(path,headers=headers).json()['reports'];assert len(listed)==2


@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_reader_report_grouping_calculation_and_all_pages_render(kind,tmp_path):
    """Representative controlled report: six photos, repeated checks, real PDF."""
    import base64
    from dataclasses import asdict
    from src.assessment_explanation import explain_assessment
    from src.agent.production_policy import production_policy
    from src.models import AgentDecision,CheckCategory,Finding,Recommendation,RiskBand,Verdict
    image_bytes=photo('blue')
    findings=[Finding(check_id='plate_ocr',case_id='reader-fixture',category=CheckCategory.IDENTITY,
        verdict=Verdict.INCONCLUSIVE,confidence=0,explanation='OCR ran but detected no readable plate. Plate legibility is unverified; this is not itself suspicious.',
        evidence={'image_id':str(index),'ocr_status':'no_text_detected','execution_state':'inconclusive'}) for index in range(6)]
    findings.append(Finding(check_id='external_corpus',case_id='reader-fixture',category=CheckCategory.HISTORY,
        verdict=Verdict.CONCERN,confidence=.8,explanation='A submitted photograph matches an external reference; verify the source and context.',
        evidence={'image_id':'0','cosine_similarity':.97,'hamming_distance':2,'execution_state':'completed'}))
    case=Case(case_id='reader-fixture',claimant_id='fictional',garage_id='UNASSIGNED',claim_type='inspection',agent_type=kind)
    decision=AgentDecision(case_id=case.case_id,recommendation=Recommendation.ESCALATE,risk_band=RiskBand.DESK_REVIEW,
        confidence=.75,summary='Review the matching photograph and obtain a legible plate view.',supporting_finding_ids=[findings[-1].finding_id],requested_artifacts=[],policy_version=production_policy(kind).policy_version)
    explanation=explain_assessment(case,findings,decision,production_policy(kind),converged=True,run_id='hidden-run-reference')
    serialized=[{**asdict(f),'verdict':f.verdict.value} for f in findings]
    report={'case_id':case.case_id,'report_template_version':report_pdf.RENDERER_VERSION,'submitted_at':'2026-10-20T06:00:00+00:00',
        'run_id':'hidden-run-reference','declaration':{'agent_type':kind,'person_name':'Fictional Example','vehicle_registration':'MH12EX1234',
        'vehicle_make':'Honda','vehicle_model':'City','vehicle_year':2023,'claim_amount':42500 if kind=='claims' else None,'idv':450000,
        'policy_number':'EXAMPLE-POLICY','declaration_notes':'Applicant states that the vehicle photographs show the current condition.'},
        'processing':{'status':'completed','perception_sources':{'request_cache':6},'error_type':'DevelopmentOnlyMarker'},
        'agent_recommendation':{'risk_band':'desk_review'},'assessment_explanation':explanation,
        'evidence_inventory':[{'image_id':str(index),'label':f'Photograph {index+1}','considered_in_run':True,'sha256':'b'*64,'thumbnail_base64':base64.b64encode(image_bytes).decode()} for index in range(6)],
        'findings_by_category':{'identity':serialized},'check_inventory':[{'check_id':'plate_ocr','state':'inconclusive','finding_ids':[f.finding_id for f in findings[:6]]},{'check_id':'external_corpus','state':'completed','finding_ids':[findings[-1].finding_id]}]}
    content=report_pdf.render_pdf(report,'a'*64,1792476000)
    reader=PdfReader(BytesIO(content));text=' '.join(' '.join(page.extract_text().split()) for page in reader.pages)
    assert 'How the assessment was calculated' in text and 'Numeric score: not computed' in text
    assert text.count('OCR ran but detected no readable plate.')==1
    assert '6 inconclusive' in text and '0.97' in text
    for private in ['hidden-run-reference','DevelopmentOnlyMarker','request_cache','a'*64,'b'*64]:assert private not in text
    headings=['Submitted facts','Labeled photographs','Main findings','How the assessment','Material limitations','Next reviewer action']
    assert [text.index(value) for value in headings]==sorted(text.index(value) for value in headings)
    assert 'Human decision · this saved version' not in text
    # Real raster rendering of EVERY page catches malformed images/fonts/tables.
    import fitz
    document=fitz.open(stream=content,filetype='pdf')
    for index,page in enumerate(document):
        assert page.get_text().strip()
        assert not any(b[0]<0 or b[1]<0 or b[2]>page.rect.width+1 or b[3]>page.rect.height+1 for b in page.get_text('blocks'))
        page.get_pixmap(matrix=fitz.Matrix(.85,.85)).save(tmp_path/f'{kind}-page-{index+1}.png')
    (tmp_path/f'{kind}-reader.pdf').write_bytes(content)
    assert len(document)<=5


@pytest.mark.parametrize('reviewed_run',['older-run-reference',None])
def test_retrospective_report_does_not_inherit_earlier_or_unknown_human_decision(reviewed_run):
    report={'case_id':'retrospective-fixture','run_id':'new-run-reference','report_template_version':report_pdf.RENDERER_VERSION,
        'declaration':{'agent_type':'claims','person_name':'Fictional Example'},'processing':{'status':'completed'},
        'admin_action':{'action':'approve','admin_id':'reviewer-fixture','reviewed_run_id':reviewed_run,
                        'reason':'Older review remains preserved.','timestamp':'2026-10-18T06:00:00+00:00'}}
    content=report_pdf.render_pdf(report,'a'*64,1792476000)
    text=' '.join(' '.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
    assert 'Historical human decision' in text and 'human review required' in text
    assert 'Human decision for this analysis' not in text
    assert 'current assessment requires a separate review' in text
    if reviewed_run:
        assert 'new assessment has not received that decision' in text
        assert reviewed_run not in text
    else:assert 'cannot be treated as approval or rejection of this assessment' in text


def test_reader_report_preserves_failed_not_run_and_not_applicable_states():
    states=['failed','not_run','not_applicable']
    findings=[{'check_id':check_id,'verdict':'inconclusive','explanation':'A controlled missing-input observation.',
               'evidence':{'execution_state':state}} for check_id,state in zip(['plate_ocr','c2pa_credentials','baseline_linkage'],states)]
    report={'case_id':'state-fixture','report_template_version':report_pdf.RENDERER_VERSION,
        'declaration':{'agent_type':'claims'},'processing':{'status':'failed'},'findings_by_category':{'identity':findings}}
    content=report_pdf.render_pdf(report,'a'*64,1792476000)
    text=' '.join(' '.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
    for state in states:assert '1 '+state.replace('_',' ') in text


@pytest.mark.parametrize('confidence,rounded',[(.299999999,.3),(.999999999,1.0)])
def test_reader_report_explains_rounded_baseline_score_at_threshold(confidence,rounded):
    from src import baseline
    from src.assessment_explanation import explain_assessment
    from src.agent.production_policy import production_policy
    from src.models import CheckCategory,Finding,Verdict
    case=Case(case_id='rounding-fixture',claimant_id='fictional',garage_id='UNASSIGNED',claim_type='claims')
    findings=[Finding(check_id='external_corpus',case_id=case.case_id,category=CheckCategory.HISTORY,
        verdict=Verdict.CONCERN,confidence=confidence,explanation='Controlled threshold observation.')]
    decision=baseline.decide(findings,case)
    explanation=explain_assessment(case,findings,decision,production_policy('claims'),converged=True,use_agent=False)
    report={'case_id':case.case_id,'report_template_version':report_pdf.RENDERER_VERSION,
        'declaration':{'agent_type':'claims'},'processing':{'status':'completed'},'assessment_explanation':explanation}
    content=report_pdf.render_pdf(report,'a'*64,1792476000)
    text=' '.join(' '.join(page.extract_text().split()) for page in PdfReader(BytesIO(content)).pages)
    assert 'Recorded heuristic score: '+str(rounded) in text
    assert 'saved score is rounded to 4 decimal places' in text
    assert 'unrounded concern sum ('+repr(confidence)+')' in text


def test_report_basis_idempotence_ignores_other_cases_and_versions_real_changes(client,tmp_path,monkeypatch):
    from src.models import AgentDecision,CheckCategory,Finding,Recommendation,RiskBand,Verdict
    case_id=seed_case(tmp_path,status='completed');headers=auth(client);path=f'/v1/cases/{case_id}/reports'
    with runtime_store.connection(api.DB_PATH) as conn:
        job=runtime_store.latest_job(conn,case_id)
        recorded=Finding(check_id='entity_graph',case_id=case_id,category=CheckCategory.HISTORY,
            verdict=Verdict.PASS,confidence=.6,explanation='No shared identifiers in this controlled fixture.')
        db.insert_finding(conn,recorded)
        decision=AgentDecision(case_id=case_id,recommendation=Recommendation.ESCALATE,risk_band=RiskBand.DESK_REVIEW,
            confidence=.3,summary='Controlled stored routing; no live model call.',supporting_finding_ids=[],requested_artifacts=[],policy_version='controlled-test')
        db.insert_agent_decision(conn,decision)
        evidence_ids=[image.image_id for image in db.get_images_for_case(conn,case_id)]
        conn.execute('INSERT INTO processing_results(run_id,case_id,decision_id,finding_ids,image_ids,policy_version,converged,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (job['job_id'],case_id,decision.decision_id,json.dumps([recorded.finding_id]),json.dumps(evidence_ids),'controlled-test',1,1000))
    initial_live=client.get(f'/v1/cases/{case_id}/report',headers=headers).json()
    assert initial_live['findings_by_category']['history'][0]['check_status']=='corpus_untestable'
    first=client.post(path+'/prepare',headers=headers);assert first.status_code==200,first.text
    first=first.json();original=client.get(path+'/'+first['snapshot_id']+'/pdf',headers=headers).content
    with runtime_store.connection(api.DB_PATH) as conn:
        db.insert_case(conn,Case(case_id='unrelated-fixture',claimant_id='other-fictional',garage_id='UNASSIGNED',claim_type='claims'))
        db.insert_finding(conn,Finding(check_id='entity_graph',case_id='unrelated-fixture',category=CheckCategory.HISTORY,
            verdict=Verdict.CONCERN,confidence=.8,explanation='An unrelated controlled corpus concern.'))
    changed_live=client.get(f'/v1/cases/{case_id}/report',headers=headers).json()
    assert changed_live['findings_by_category']['history'][0]['check_status']=='active'
    repeated=client.post(path+'/prepare',headers=headers).json()
    assert repeated['snapshot_id']==first['snapshot_id'] and repeated['sha256']==first['sha256']
    assert client.get(path+'/'+first['snapshot_id']+'/pdf',headers=headers).content==original
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots WHERE case_id=?',(case_id,)).fetchone()[0]==1
    action=client.post(f'/v1/cases/{case_id}/action',headers=headers,json={'action':'approve','reason':'Controlled review of the recorded evidence.',
        'public_message':'Your application is approved.','expected_revision':0,'expected_run_id':job['job_id'],'expected_evidence_ids':evidence_ids})
    assert action.status_code==200,action.text
    human=client.post(path+'/prepare',headers=headers).json();assert human['snapshot_id']!=first['snapshot_id']
    with runtime_store.connection(api.DB_PATH) as conn:
        next_job=runtime_store.enqueue(conn,case_id);next_job.update(status='completed',stage='complete');runtime_store.save_job(conn,next_job)
    new_run=client.post(path+'/prepare',headers=headers).json();assert new_run['snapshot_id'] not in {first['snapshot_id'],human['snapshot_id']}
    monkeypatch.setattr(report_pdf,'RENDERER_VERSION',report_pdf.RENDERER_VERSION+'-controlled-next-template')
    template=client.post(path+'/prepare',headers=headers).json();assert template['snapshot_id'] not in {first['snapshot_id'],human['snapshot_id'],new_run['snapshot_id']}
    assert client.get(path+'/'+first['snapshot_id']+'/pdf',headers=headers).content==original
