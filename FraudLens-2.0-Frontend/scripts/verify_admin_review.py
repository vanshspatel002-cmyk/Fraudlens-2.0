"""Controlled Chrome verification of the real admin UI; no backend/model calls.

Run with the backend venv Python against a production UI on 5173. Every /v1
request is intercepted with explicitly fictional fixtures. --before captures the
preceding production build for visual comparison. Artifacts stay git-ignored.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import traceback
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
UI = os.environ.get('ADMIN_REVIEW_UI', 'http://127.0.0.1:5173')
LONG_NARRATIVE = 'PRIVATE_LONG_AGENT_NARRATIVE_MUST_NOT_RENDER ' * 40
AT = '2026-10-20T08:30:00+00:00'


def case_fixture(case_id, kind, state='failed'):
    declaration = dict(agent_type=kind, person_name='Mira Fictional', person_contact='mira@example.test',
        person_address='17 Sample Road, Pune', person_dob='1990-05-08', driving_license_number='SAMPLE-LICENCE',
        vehicle_registration='MH00ZZ0000', vehicle_make='Maruti Suzuki', vehicle_model='Swift',
        vehicle_variant='VXI', vehicle_year=2021, engine_number='SAMPLE-ENGINE', chassis_number='SAMPLE-CHASSIS',
        fuel_type='Petrol', idv=450000, policy_number='FICTIONAL-POLICY', policy_type='Comprehensive',
        policy_ncb_percent=0, claim_amount=12500 if kind == 'claims' else None,
        incident_date='2026-10-19T09:15:00+05:30' if kind == 'claims' else None,
        declared_location='Pune' if kind == 'claims' else None,
        declaration_notes='A parked vehicle was struck at low speed. The left bumper was scratched.' if kind == 'claims'
        else 'Application type: Renewal\nDeclared vehicle condition: Good condition\nThe vehicle is used for family travel.')
    findings = {'identity':[dict(finding_id='fixture-finding',check_id='plate_ocr',category='identity',verdict='pass',
        confidence=.8,explanation='CONTROLLED_FINDING_EXPLANATION_MUST_NOT_RENDER',evidence={'raw':'RAW_JSON_SENTINEL'})]}
    processing = None if state == 'legacy' else dict(job_id=case_id+'-run',status=state,stage='finished' if state=='completed' else state,
        detail='Controlled fixture diagnostic; no provider was called.')
    decision = dict(recommendation='escalate',risk_band='desk_review',summary=LONG_NARRATIVE,
        provider_unavailable=state=='failed', supporting_finding_ids=['fixture-finding'])
    audit = [dict(created_at=AT,actor='applicant',event='case_submitted',detail={}),
        dict(created_at='2026-10-20T08:30:10+00:00',actor='worker',event='processing_'+state,detail={'raw':'RAW_JSON_SENTINEL'})]
    return dict(case_id=case_id,agent_type=kind,person_name='Mira Fictional',vehicle_registration='MH00ZZ0000',
        policy_number='FICTIONAL-POLICY',claim_amount=12500 if kind=='claims' else 0,status='open',created_at=AT,
        processing_status=None if state=='legacy' else state,processing=processing,risk_band='desk_review',
        recommendation='escalate',review_revision=0,images=[dict(image_id='fixture-photo',damage_description='Submitted vehicle photograph')],
        findings_by_category=findings,decision=decision,audit=audit,declaration=declaration,admin_action=None,
        run_id=None if state=='legacy' else case_id+'-run',policy_version='fixture-policy-v1',limitations=['Controlled diagnostic limitation.'],
        report_history=[dict(snapshot_id='historical-'+case_id,run_id=case_id+'-old-run',created_at=1792485000)],
        assessment_explanation=dict(routing=dict(source='fallback' if state=='failed' else 'model',converged=state!='failed'),
            coverage=dict(material_complete=True)))


class Fixtures:
    def __init__(self):
        self.cases = {key:case_fixture(key,kind,state) for key,kind,state in [
            ('claim-approve','claims','failed'),('claim-reject','claims','failed'),
            ('uw-approve','underwriting','failed'),('uw-reject','underwriting','failed'),
            ('legacy-claim','claims','legacy'),('legacy-uw','underwriting','legacy'),
            ('completed-claim','claims','completed'),('queued-uw','underwriting','queued'),
            ('partial-uw','underwriting','completed'),('retrospective-claim','claims','completed'),
            ('unknown-basis-uw','underwriting','completed'),('failed-routing-claim','claims','failed')]}
        self.cases['partial-uw']['assessment_explanation']['coverage']['material_complete'] = False
        retrospective=self.cases['retrospective-claim']
        retrospective['status']='closed_approved'
        retrospective['admin_action']=dict(action='approve',reason='Recorded earlier review.',admin_id='reviewer@example.test',timestamp=AT,
            reviewed_run_id='retrospective-earlier-run')
        unknown=self.cases['unknown-basis-uw']
        unknown['status']='closed_rejected'
        unknown['admin_action']=dict(action='reject',reason='Historical review with no run basis.',admin_id='reviewer@example.test',timestamp=AT)
        failed_routing=self.cases['failed-routing-claim']
        failed_routing['decision']['provider_unavailable']=False
        failed_routing['assessment_explanation']=dict(routing=dict(source='model',converged=True),coverage=dict(material_complete=False))
        self.actions = []
        self.requests = []
        self.unexpected = []
        self.role = 'reviewer'
        photo = ROOT.parent/'FraudLens-2.0-Backend/data/curated/damaged/damaged_0002.jpg'
        self.photo = photo.read_bytes()
        pdf = BytesIO()
        document = canvas.Canvas(pdf)
        document.drawString(50,750,'Controlled fictional FraudLens UI PDF fixture; no analysis executed.')
        document.save()
        self.pdf = pdf.getvalue()

    def report(self, item, historical=False):
        report = deepcopy(item)
        report['agent_recommendation'] = report['decision']
        report['agent_narrative'] = LONG_NARRATIVE
        if historical:
            report['snapshot_id'] = 'historical-'+item['case_id']
        return report

    def version(self, case_id, historical=False):
        return dict(snapshot_id=('historical-' if historical else 'current-')+case_id,
            run_id=case_id+'-run',snapshot_created_at=1792485000,pdf_status='ready',generated_at=1792485001,
            renderer_version='controlled-fixture')

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        query = parse_qs(url.query)
        self.requests.append(dict(method=request.method,path=path))
        headers = {'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*',
            'Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Expose-Headers':'Content-Disposition'}
        def respond(value=None, status=200, content_type='application/json', body=None, extra=None):
            route.fulfill(status=status,content_type=content_type,headers={**headers,**(extra or {})},
                body=body if body is not None else json.dumps(value))
        if request.method == 'OPTIONS':
            respond({})
        elif path=='/v1/auth/session':
            respond(dict(user='reviewer@example.test',role=self.role))
        elif path=='/v1/auth/logout':
            respond({'ok':True})
        elif path=='/v1/finding-counts':
            respond({'counts':[]})
        elif path=='/v1/cases':
            search=query.get('search',[''])[0]
            kind=query.get('agent_type',[''])[0]
            items=[dict(item,thumbnail_url='/v1/images/fixture-photo?thumb=1') for item in self.cases.values()
                if search in item['case_id'] and (not kind or item['agent_type']==kind)]
            respond(dict(items=items,total=len(items),has_more=False,page=1,page_size=10))
        elif path.startswith('/v1/images/'):
            respond(content_type='image/jpeg',body=self.photo)
        else:
            match=re.fullmatch(r'/v1/cases/([^/]+)(.*)',path)
            if not match or match[1] not in self.cases:
                self.unexpected.append(dict(method=request.method,path=path))
                respond({'message':'Unexpected controlled fixture request'},status=404)
                return
            case_id,suffix=match.groups()
            item=self.cases[case_id]
            if not suffix:
                respond(item)
            elif suffix=='/trace':
                respond({'steps':[dict(type='fallback',content=LONG_NARRATIVE,tool_output={'raw':'RAW_JSON_SENTINEL'})]})
            elif suffix=='/report':
                respond(self.report(item,'snapshot_id' in query))
            elif suffix=='/reports':
                respond({'reports':[self.version(case_id,True)]})
            elif suffix=='/reports/prepare':
                respond(self.version(case_id,query.get('snapshot_id',[''])[0].startswith('historical-')))
            elif suffix.endswith('/pdf'):
                respond(content_type='application/pdf',body=self.pdf,extra={'Content-Disposition':'attachment; filename="controlled-review.pdf"'})
            elif suffix=='/action' and request.method=='POST':
                action=request.post_data_json
                self.actions.append(dict(case_id=case_id,**action))
                item['review_revision']+=1
                item['status']={'approve':'closed_approved','reject':'closed_rejected','request_more_evidence':'awaiting_evidence'}[action['action']]
                item['admin_action']=dict(action=action['action'],reason=action['reason'],admin_id='reviewer@example.test',timestamp=AT,
                    reviewed_run_id=action['expected_run_id'],public_message=action['public_message'])
                item['audit'].append(dict(created_at='2026-10-20T09:00:00+00:00',actor='reviewer@example.test',event='admin_action',detail=action))
                respond({'ok':True})
            else:
                self.unexpected.append(dict(method=request.method,path=path))
                respond({'message':'Unexpected controlled fixture request'},status=404)


def open_case(page, case_id):
    back=page.get_by_role('button',name='Back to case queue',exact=False)
    if back.count():
        back.click()
    page.get_by_role('button',name='Case queue',exact=True).click()
    page.get_by_label('Search cases',exact=True).fill(case_id)
    page.get_by_role('button',name=case_id,exact=True).click()
    expect(page.locator('.review-case-status strong')).to_have_text(case_id,timeout=30000)
    expect(page.get_by_role('heading',name='Application details',exact=True)).to_be_visible(timeout=30000)


def verify_layout(page):
    sections=page.locator('[data-review-section]')
    assert sections.evaluate_all("nodes=>nodes.map(node=>node.dataset.reviewSection)")==['application','photos','desk','actions','timeline']
    boxes=sections.evaluate_all("nodes=>nodes.map(node=>{const box=node.getBoundingClientRect();return {x:box.x,y:box.y,width:box.width,bottom:box.bottom}})")
    assert all(abs(box['x']-boxes[0]['x'])<2 and abs(box['width']-boxes[0]['width'])<2 for box in boxes)
    assert all(boxes[index]['bottom']<=boxes[index+1]['y'] for index in range(len(boxes)-1))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'page-wide overflow'
    expect(page.locator('.desk-review-summary')).to_have_attribute('data-sentence-count','3')
    assert page.locator('.desk-review-summary').evaluate("node=>node.nextElementSibling.getAttribute('aria-label')")== 'Saved PDF report'
    expect(page.get_by_text('Evidence Battery',exact=False)).to_have_count(0)
    expect(page.locator('pre')).to_have_count(0)
    assert LONG_NARRATIVE[:44] not in page.locator('body').inner_text()
    assert 'CONTROLLED_FINDING_EXPLANATION_MUST_NOT_RENDER' not in page.locator('body').inner_text()
    assert 'RAW_JSON_SENTINEL' not in page.locator('body').inner_text()
    expect(page.locator('.review-diagnostics')).not_to_have_attribute('open','')


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--before',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or ROOT/'.browser-check'/('admin-review-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True,exist_ok=True)
    fixtures=Fixtures()
    checks=[]
    errors=[]
    checkpoint='startup'
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport={'width':1365,'height':900},accept_downloads=True)
            context.add_init_script("sessionStorage.setItem('fraudlens_admin_token','controlled-fictional-token');sessionStorage.setItem('fraudlens_admin_email','reviewer@example.test');")
            context.route('**/v1/**',fixtures.route)
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(type(error).__name__))
            page.goto(UI+'/admin',wait_until='domcontentloaded')
            expect(page.get_by_role('button',name='Case queue',exact=True)).to_be_visible(timeout=60000)
            checkpoint='before' if args.before else 'linear-layout'
            for case_id in ['claim-approve','uw-approve']:
                # The old production build has different application heading;
                # capture it without applying the replacement assertions.
                if args.before:
                    page.get_by_role('button',name='Case queue',exact=True).click()
                    page.get_by_label('Search cases',exact=True).fill(case_id)
                    page.get_by_role('button',name=case_id,exact=True).click()
                    expect(page.get_by_role('button',name='Evidence',exact=True)).to_be_visible(timeout=30000)
                else:
                    open_case(page,case_id)
                for width in [1365,768,390]:
                    page.set_viewport_size({'width':width,'height':900})
                    if not args.before:
                        verify_layout(page)
                    page.screenshot(path=str(output/f'{"before" if args.before else "after"}-{case_id}-{width}.png'),full_page=True,animations='disabled')
                page.set_viewport_size({'width':1365,'height':900})
                if args.before:
                    page.get_by_role('button',name='Back to case queue',exact=False).click()
            if args.before:
                checks.append('preceding production claims/underwriting screenshots at desktop/tablet/mobile')
            else:
                checks.append('claims and underwriting use the same single column at1365/768/390 with no overflow or raw JSON/narrative/finding cards')
                checkpoint='pdf-and-history'
                panel=page.get_by_role('region',name='Saved PDF report')
                panel.get_by_role('button',name='Preview report',exact=True).click()
                preview=page.get_by_role('dialog',name='PDF report preview')
                expect(preview).to_be_visible()
                expect(preview.locator('iframe')).to_have_attribute('src',re.compile('^blob:'))
                preview.get_by_role('button',name='Close preview',exact=True).click()
                with page.expect_download() as download:
                    panel.get_by_role('button',name='Download PDF',exact=True).click()
                download.value.save_as(str(output/'controlled-review.pdf'))
                page.get_by_text('Earlier reports and reviews',exact=True).click()
                page.get_by_label('Report history',exact=True).select_option('historical-uw-approve')
                historical=page.get_by_role('dialog',name='Historical report',exact=True)
                expect(historical).to_be_visible()
                expect(historical.get_by_role('heading',name='Desk Review',exact=True)).to_be_visible()
                assert LONG_NARRATIVE[:44] not in historical.inner_text()
                historical.get_by_role('button',name='Preview report',exact=True).click()
                page.get_by_role('dialog',name='PDF report preview').get_by_role('button',name='Close preview',exact=True).click()
                historical.get_by_role('button',name='Close historical report').click()
                checks.append('current and historical PDF preview, blob iframe, download, compact saved review history')
                checkpoint='original-photo'
                page.locator('.review-photos button').first.click()
                expect(page.get_by_role('dialog',name='Submitted vehicle photograph',exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog',name='Submitted vehicle photograph',exact=True)).to_have_count(0)
                checks.append('original evidence viewer and Escape close retained')
                checkpoint='human-actions'
                for case_id,action in [('claim-approve','Approve'),('claim-reject','Reject'),('uw-approve','Approve'),('uw-reject','Reject')]:
                    open_case(page,case_id)
                    expect(page.locator('.review-processing')).to_have_text('Failed')
                    expect(page.locator('.desk-review-summary')).to_contain_text('incomplete')
                    page.locator('select[name="action"]').select_option(action)
                    page.locator('textarea[name="reason"]').fill('Controlled manual evidence review of submitted photograph; fictional decision for UI contract.')
                    page.locator('textarea[name="publicNarrative"]').fill('Your application has been '+('approved.' if action=='Approve' else 'rejected with the recorded explanation.'))
                    page.locator('input[name="manualReviewOverride"]').check()
                    with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/action')) as recorded_action:
                        page.get_by_role('button',name=action+' case',exact=True).click()
                    assert recorded_action.value.status==200
                    expect(page.locator('.record-action')).to_be_disabled()
                    expect(page.locator('.review-timeline')).to_contain_text('Approved by a reviewer' if action=='Approve' else 'Rejected by a reviewer')
                    payload=fixtures.actions[-1]
                    assert payload['case_id']==case_id and payload['action']==action.lower()
                    assert payload['expected_revision']==0 and payload['expected_run_id']==case_id+'-run'
                    assert payload['expected_evidence_ids']==['fixture-photo'] and payload['manual_review_override'] is True
                    assert payload['public_message'] and payload['reason']
                checks.append('claims and underwriting approve/reject preserve revision/run/evidence basis, manual override, public/private notes and readable history')
                checkpoint='legacy-and-incomplete'
                for case_id in ['legacy-claim','legacy-uw']:
                    open_case(page,case_id)
                    expect(page.locator('.review-processing')).to_have_text('Not recorded')
                    expect(page.locator('.desk-review-summary')).to_contain_text('processing status was not recorded')
                    expect(page.locator('input[name="manualReviewOverride"]')).to_have_count(0)
                open_case(page,'completed-claim')
                expect(page.locator('.review-processing')).to_have_text('Completed')
                expect(page.locator('.desk-review-summary')).to_contain_text('did not flag a concern')
                open_case(page,'partial-uw')
                expect(page.locator('.desk-review-summary')).to_contain_text('routing is recorded, but check coverage is incomplete')
                open_case(page,'retrospective-claim')
                expect(page.locator('.review-case-status')).to_contain_text('Approved (earlier analysis)')
                expect(page.locator('.review-recorded-outcome')).to_contain_text('does not review the current analysis')
                expect(page.get_by_role('button',name='Approve case',exact=True)).to_be_disabled()
                open_case(page,'unknown-basis-uw')
                expect(page.locator('.review-case-status')).to_contain_text('Rejected (historical; basis not recorded)')
                expect(page.locator('.desk-review-summary')).to_contain_text('historical human decision has no recorded analysis basis')
                expect(page.get_by_role('button',name='Approve case',exact=True)).to_be_disabled()
                open_case(page,'failed-routing-claim')
                expect(page.locator('.review-processing')).to_have_text('Failed')
                expect(page.locator('.desk-review-summary')).to_contain_text('Processing did not fully complete, although automated routing is recorded with incomplete check coverage')
                open_case(page,'queued-uw')
                expect(page.get_by_role('button',name='Approve case',exact=True)).to_be_disabled()
                expect(page.get_by_role('button',name='Preview report',exact=True)).to_be_disabled()
                page.get_by_label('PDF report version',exact=True).select_option('historical-queued-uw')
                expect(page.get_by_role('button',name='Preview report',exact=True)).to_be_enabled()
                checks.append('legacy no-run distinct from failed; completed/partial/queued semantics; earlier human decision basis labeled without changing closed status; historical PDF while current run active')
                checkpoint='evidence-request'
                open_case(page,'legacy-claim')
                page.locator('select[name="action"]').select_option('Request More Evidence')
                page.locator('textarea[name="reason"]').fill('Need a clear original front photograph.')
                page.locator('textarea[name="publicNarrative"]').fill('Please upload the requested front photograph.')
                page.locator('textarea[name="requestedArtifacts"]').fill('Front view with registration visible\nClose view of left bumper')
                page.get_by_role('button',name='Request more evidence',exact=True).click()
                expect(page.locator('.review-timeline')).to_contain_text('Additional photographs requested')
                assert fixtures.actions[-1]['requested_artifacts']==['Front view with registration visible','Close view of left bumper']
                checks.append('specific additional evidence action contract and readable timeline retained')
                checkpoint='restricted-diagnostics'
                expect(page.locator('.review-diagnostics')).not_to_have_attribute('open','')
                page.get_by_text('Technical diagnostics',exact=True).click()
                expect(page.get_by_role('button',name='Retry analysis',exact=True)).to_be_visible()
                fixtures.role='viewer'
                page.reload(wait_until='domcontentloaded')
                open_case(page,'legacy-uw')
                expect(page.locator('.review-diagnostics')).to_have_count(0)
                expect(page.get_by_role('button',name='Approve case',exact=True)).to_be_disabled()
                checks.append('technical diagnostics collapsed for reviewers and unavailable to viewer role; viewer decision disabled')
            assert not fixtures.unexpected,fixtures.unexpected
            assert not errors,errors
            manifest=dict(ok=True,mode='controlled-http-fixtures-no-backend-or-model-calls',before=args.before,
                ui=UI,browser=browser.version,checks=checks,actions=fixtures.actions,requests=fixtures.requests,
                screenshots=[path.name for path in output.glob('*.png')],javascript_error_types=errors)
            (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            browser.close()
        print(json.dumps(dict(ok=True,checks=checks,manifest=str(output/'manifest.json')),indent=2))
    except Exception as error:
        (output/'private-error.txt').write_text(str(error),encoding='utf-8')
        try:
            page.screenshot(path=str(output/'failure.png'),full_page=True,animations='disabled')
        except Exception:
            pass
        (output/'failure.json').write_text(json.dumps(dict(ok=False,checkpoint=checkpoint,error_type=type(error).__name__,
            line=next((frame.lineno for frame in reversed(traceback.extract_tb(error.__traceback__)) if frame.filename==__file__),None),actions=fixtures.actions,
            requests=fixtures.requests,unexpected=fixtures.unexpected),indent=2),encoding='utf-8')
        print(json.dumps(dict(ok=False,checkpoint=checkpoint,error_type=type(error).__name__,artifact=str(output/'failure.json'))))
        raise SystemExit(1)


if __name__=='__main__':
    run()
