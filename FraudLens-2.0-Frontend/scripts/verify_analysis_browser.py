"""Two real Chrome tabs, real API/worker and exactly one claim + one underwriting.

Requires --config pointing to private generated test credentials and photo paths.
There are no route intercepts or model mocks. Run only after the operator has
confirmed the isolated API/worker and bounded provider allowance are ready.
The manifest intentionally excludes credentials and bearer tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import traceback

import httpx
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='Resume saved accepted cases; never create replacements.')
    parser.add_argument('--allow-incomplete',action='store_true',
        help='Verify the explicit manual-review workflow after incomplete analysis; never count it as live AI validation.')
    parser.add_argument('--reports-only',action='store_true',
        help='Recheck current PDFs for both retained, decided cases without submitting applications or decisions.')
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    output=Path(config['output_dir']).resolve()
    output.mkdir(parents=True,exist_ok=True)
    state_path=output/'accepted-cases.json'
    account_state_path=output/'account-state.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    if state and not args.resume:
        raise SystemExit('Accepted case state already exists; use --resume to preserve it.')
    if args.reports_only and any(not state.get(kind,{}).get('decision') for kind in ('claims','underwriting')):
        raise SystemExit('Reports-only verification requires both retained cases and their existing human decisions.')
    api=config.get('api','http://127.0.0.1:8001').rstrip('/')
    ui=config.get('ui','http://127.0.0.1:5173').rstrip('/')
    os.environ.update(PRESENTATION_UI=ui,PRESENTATION_API=api,PRESENTATION_OUTPUT_DIR=str(output),
        PRESENTATION_DB=str(output/'unused-no-sqlite-access.db'))
    donor=ROOT.parent/'FraudLens-2.0-Backend/scripts/verify_presentation_browser.py'
    spec=importlib.util.spec_from_file_location('intake_helpers',donor)
    helpers=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    observations=[]
    javascript_errors=[]
    checkpoint='startup'
    def record(check,**details):
        if 'confirmation_and_replay_seconds' in details:
            details['confirmation_and_navigation_seconds']=details.pop('confirmation_and_replay_seconds')
        observations.append(dict(check=check,**details))
        (output/'browser-observations.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')
        print(json.dumps(dict(check=check,**details)),flush=True)
    helpers.record=record

    def save_state():
        state_path.write_text(json.dumps(state,indent=2),encoding='utf-8')

    def open_case(admin,case_id):
        back=admin.get_by_role('button',name='Back to case queue',exact=False)
        if back.count():
            back.click()
        helpers.open_case(admin,case_id)
        expect(admin.get_by_role('heading',name='Desk Review',exact=True)).to_be_visible(timeout=45000)

    def layout(admin,kind):
        sections=admin.locator('[data-review-section]')
        assert sections.evaluate_all('nodes=>nodes.map(node=>node.dataset.reviewSection)')==['application','photos','desk','actions','timeline']
        expect(admin.locator('.desk-review-summary')).to_have_attribute('data-sentence-count','3')
        expect(admin.get_by_text('Evidence Battery',exact=False)).to_have_count(0)
        expect(admin.locator('pre')).to_have_count(0)
        for width in [1365,390]:
            admin.set_viewport_size({'width':width,'height':900})
            boxes=sections.evaluate_all('nodes=>nodes.map(node=>{const b=node.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,end:b.bottom}})')
            assert all(abs(box['x']-boxes[0]['x'])<2 and abs(box['w']-boxes[0]['w'])<2 for box in boxes)
            assert all(boxes[index]['end']<=boxes[index+1]['y'] for index in range(len(boxes)-1))
            assert admin.evaluate('document.documentElement.scrollWidth<=innerWidth')
            admin.screenshot(path=str(output/f'real-{kind}-{width}.png'),full_page=True,animations='disabled')
        admin.set_viewport_size({'width':1365,'height':900})

    def wait_terminal(admin,job_id):
        started=time.monotonic()
        last=None
        with httpx.Client(timeout=60) as client:
            while time.monotonic()-started<1500:
                response=client.get(api+'/v1/jobs/'+job_id,headers=helpers.headers(admin))
                response.raise_for_status()
                job=response.json()
                if (job.get('status'),job.get('stage'))!=last:
                    last=(job.get('status'),job.get('stage'))
                    record('Real durable processing stage',job_id=job_id,status=job.get('status'),stage=job.get('stage'))
                if job['status'] in {'failed','completed','done','interrupted'}:
                    record('Real durable worker reached terminal',job_id=job_id,status=job['status'],
                        observed_terminal_wait_seconds=round(time.monotonic()-started,3),
                        timing_note='Observed API polling wait; persisted worker duration is reported separately by the isolated database audit.')
                    return job
                # Playwright wait keeps this ordinary tab responsive to polling.
                admin.wait_for_timeout(2000)
        raise TimeoutError('Durable job did not reach terminal within the verification window')

    def pdf(admin,case_id,label):
        panel=admin.get_by_role('region',name='Saved PDF report')
        panel.get_by_label('PDF report version',exact=True).select_option('')
        panel.get_by_role('button',name='Preview report',exact=True).click()
        dialog=admin.get_by_role('dialog',name='PDF report preview',exact=True)
        expect(dialog).to_be_visible(timeout=90000)
        snapshot=panel.get_by_label('PDF report version',exact=True).input_value()
        blob_sha=dialog.locator('iframe').evaluate("async frame=>{const hash=window.__fraudlensPdfHashes?.[frame.src];if(!hash)throw Error('Preview PDF blob was not observed');return await hash}")
        dialog.get_by_role('button',name='Close preview',exact=True).click()
        with admin.expect_download(timeout=90000) as download:
            panel.get_by_role('button',name='Download PDF',exact=True).click()
        destination=output/f'{label}.pdf'
        download.value.save_as(str(destination))
        response=httpx.get(api+'/v1/cases/'+case_id+'/reports/'+snapshot+'/pdf',headers=helpers.headers(admin),timeout=90)
        response.raise_for_status()
        sha=hashlib.sha256(destination.read_bytes()).hexdigest()
        assert sha==hashlib.sha256(response.content).hexdigest()==blob_sha
        reader=PdfReader(str(destination))
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
        assert case_id in text
        record('Real preview/download/private API return identical saved PDF bytes',case_id=case_id,snapshot_id=snapshot,
            sha256=sha,pages=len(reader.pages),pdf_path=str(destination))
        return snapshot

    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='chrome',headless=True,args=['--disable-gpu'])
            context=browser.new_context(viewport={'width':1365,'height':900},accept_downloads=True)
            customer=context.new_page()
            admin=context.new_page()
            # Observe the actual preview blob at creation. Fetching its blob:
            # URL would violate the app's connect-src policy on current Chrome.
            # Keep the real responses, object URL and browser policy unchanged.
            admin.add_init_script("""(() => {
                const original = URL.createObjectURL;
                window.__fraudlensPdfHashes = {};
                URL.createObjectURL = function(blob) {
                    const url = original.call(this, blob);
                    if (blob.type === 'application/pdf') {
                        window.__fraudlensPdfHashes[url] = blob.arrayBuffer()
                            .then(bytes => crypto.subtle.digest('SHA-256', bytes))
                            .then(hash => [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, '0')).join(''));
                    }
                    return url;
                };
            })();""")
            customer.on('pageerror',lambda error:javascript_errors.append(type(error).__name__))
            admin.on('pageerror',lambda error:javascript_errors.append(type(error).__name__))
            current_kind=None
            def preserve_acceptance(response):
                if 200<=response.status<300 and response.request.method=='POST' and response.url==api+'/v1/customer/auth/register':
                    account_state_path.write_text(json.dumps({'registered':True}),encoding='utf-8')
                if current_kind and response.status==201 and response.request.method=='POST' and response.url==api+'/v1/cases':
                    state.setdefault(current_kind,{})['submitted']=response.json()
                    save_state()
                    accepted=state[current_kind]['submitted']
                    record('Genuine case accepted and preserved',kind=current_kind,case_id=accepted['case_id'],job_id=accepted.get('job_id'))
            customer.on('response',preserve_acceptance)
            checkpoint='sign-in'
            register=config.get('customer_register',not config.get('customer_precreated',True))
            helpers.customer_signin(customer,config['customer'],register=bool(register) and not bool(state) and not account_state_path.exists())
            helpers.admin_signin(admin,config['reviewer'])
            assert customer.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
            assert admin.evaluate("sessionStorage.getItem('fraudlens_customer_token')") is None
            record('Two ordinary tabs in one Chrome context retain independent customer and reviewer sessions')
            for index,(kind,action) in enumerate([('claims','Approve'),('underwriting','Reject')],11):
                current_kind=kind
                checkpoint=kind+'-intake'
                if kind not in state:
                    # Persist as soon as the genuine accepted request returns.
                    # The donor never invokes SQLite or its old terminal helper.
                    submitted=helpers.intake(customer,kind,index,[Path(path) for path in config['photos'][kind]])
                    state[kind]=dict(submitted=submitted)
                    save_state()
                submitted=state[kind]['submitted']
                case_id=submitted['case_id']
                if args.reports_only:
                    checkpoint=kind+'-current-pdf'
                    admin.bring_to_front()
                    open_case(admin,case_id)
                    state[kind]['final_snapshot']=pdf(admin,case_id,kind+'-current')
                    save_state()
                    continue
                checkpoint=kind+'-processing'
                state[kind]['job']=wait_terminal(admin,submitted['job_id'])
                save_state()
                checkpoint=kind+'-review'
                customer.goto(ui+'/dashboard?case='+case_id,wait_until='domcontentloaded',timeout=120000)
                expect(customer.get_by_role('heading',name=case_id,exact=True)).to_be_visible(timeout=45000)
                admin.bring_to_front()
                open_case(admin,case_id)
                layout(admin,kind)
                response=httpx.get(api+'/v1/cases/'+case_id+'/report',headers=helpers.headers(admin),timeout=90)
                response.raise_for_status()
                report=response.json()
                explanation=report.get('assessment_explanation')
                assert explanation is not None,'No frozen assessment explanation in real report'
                assert report.get('run_id')==submitted['job_id']
                (output/f'{kind}-predecision-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                record('Real saved report contains exact-run assessment explanation',case_id=case_id,run_id=report['run_id'],
                    processing_status=(report.get('processing') or {}).get('status'),routing=explanation.get('routing',{}).get('source'),
                    converged=explanation.get('routing',{}).get('converged'),
                    material_complete=explanation.get('coverage',{}).get('material_complete'))
                if state[kind]['job']['status'] in {'failed','interrupted'} or explanation.get('routing',{}).get('converged') is False:
                    state[kind]['live_ai_complete']=False
                    save_state()
                    if not args.allow_incomplete:
                        record('Paused after incomplete real processing; accepted evidence retained without replacement or probe',case_id=case_id,job_id=submitted['job_id'])
                        raise RuntimeError('Real processing incomplete; preserve this case and await operator diagnosis')
                    record('Explicit manual-review verification after incomplete analysis; live AI remains unverified',
                        case_id=case_id,job_id=submitted['job_id'],processing_status=state[kind]['job']['status'])
                else:
                    state[kind]['live_ai_complete']=True
                    save_state()
                if 'decision' not in state[kind]:
                    state[kind]['initial_snapshot']=pdf(admin,case_id,kind+'-before-decision')
                    save_state()
                    checkpoint=kind+'-decision'
                    public='This fictional verification application is '+('approved after human review of the submitted evidence.' if action=='Approve'
                        else 'declined after human review because these sample photographs do not establish all required views of one vehicle.')
                    admin.locator('select[name="action"]').select_option(action)
                    admin.locator('textarea[name="reason"]').fill('Controlled verification only. Reviewed the saved application, original photograph(s) and recorded analysis limitations. Automated processing is incomplete where disclosed; this explicit manual decision checks accountable human routing, not fraud accuracy.')
                    admin.locator('textarea[name="publicNarrative"]').fill(public)
                    override=admin.locator('input[name="manualReviewOverride"]')
                    if override.count():
                        override.check()
                    with admin.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/action'),timeout=90000) as action_response:
                        admin.get_by_role('button',name=action+' case',exact=True).click()
                    assert action_response.value.status==200
                    state[kind]['decision']=dict(action=action,public=public,status=action_response.value.status)
                    save_state()
                    expect(admin.locator('.record-action')).to_be_disabled(timeout=45000)
                checkpoint=kind+'-dashboard-polling'
                customer.bring_to_front()
                expect(customer.locator('.ud-narrative')).to_have_text(state[kind]['decision']['public'],timeout=90000)
                assert customer.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
                record('Customer dashboard receives the recorded human outcome',case_id=case_id,action=action)
                checkpoint=kind+'-decision-pdf'
                admin.bring_to_front()
                open_case(admin,case_id)
                final_snapshot=pdf(admin,case_id,kind+'-after-decision')
                if state[kind].get('initial_snapshot'):
                    assert final_snapshot!=state[kind]['initial_snapshot'],'Human action did not produce a distinct saved report version'
                state[kind]['final_snapshot']=final_snapshot
                save_state()
                layout(admin,kind+'-decided')
            checkpoint='refresh-independent-tabs'
            customer.reload(wait_until='domcontentloaded',timeout=120000)
            admin.reload(wait_until='domcontentloaded',timeout=120000)
            expect(customer.get_by_role('button',name='Sign out customer',exact=True)).to_be_visible(timeout=45000)
            expect(admin.get_by_role('button',name='Sign out',exact=True)).to_be_visible(timeout=45000)
            assert customer.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
            assert admin.evaluate("sessionStorage.getItem('fraudlens_customer_token')") is None
            record('Refresh preserves both separate role sessions and recorded case outcomes')
            assert not javascript_errors,javascript_errors
            manifest=dict(ok=True,mode='real-production-ui-real-api-'+('reports-only' if args.reports_only else 'real-durable-worker-no-mocks'),api=api,ui=ui,
                reports_only=args.reports_only,
                incomplete_analysis_permitted=args.allow_incomplete,
                live_ai_complete=all(row.get('live_ai_complete') is True for row in state.values()),
                browser=browser.version,case_count=len(state),cases=state,observations=observations,
                screenshots=[path.name for path in output.glob('*.png')],javascript_error_types=javascript_errors)
            (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            browser.close()
        print(json.dumps(dict(ok=True,manifest=str(output/'manifest.json')),indent=2))
    except Exception as error:
        (output/'private-error.txt').write_text(str(error),encoding='utf-8')
        try:
            customer.screenshot(path=str(output/'failure-customer.png'),full_page=True,animations='disabled')
            admin.screenshot(path=str(output/'failure-reviewer.png'),full_page=True,animations='disabled')
        except Exception:
            pass
        (output/'failure.json').write_text(json.dumps(dict(ok=False,checkpoint=checkpoint,error_type=type(error).__name__,
            line=next((frame.lineno for frame in reversed(traceback.extract_tb(error.__traceback__)) if frame.filename==__file__),None),
            accepted_cases={kind:data['submitted']['case_id'] for kind,data in state.items()},javascript_error_types=javascript_errors),indent=2),encoding='utf-8')
        print(json.dumps(dict(ok=False,checkpoint=checkpoint,error_type=type(error).__name__,artifact=str(output/'failure.json'))),flush=True)
        raise SystemExit(1)


if __name__=='__main__':
    run()
