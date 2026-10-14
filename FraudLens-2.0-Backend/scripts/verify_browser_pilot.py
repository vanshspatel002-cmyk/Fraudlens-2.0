"""Real two-tab Chrome rehearsal against the isolated local pilot.

Uses actual uploads/checks/provider failure behavior; no network/model mocking.
The photographs are existing corpus evidence, not validated six views of one
vehicle. This verifies UI/data flow, not detector accuracy or Gemini success.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import argparse
import hashlib
import sqlite3
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/pilot_validation'
UI=os.environ.get('PILOT_UI','http://127.0.0.1:5173')
API=os.environ.get('PILOT_API','http://127.0.0.1:8001')
observations=[]


def record(name, **detail):
    observations.append({'check':name,**detail})
    (OUT/'browser_verification.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')
    print(name,json.dumps(detail),flush=True)


def poll_job(admin,job_id):
    token=admin.evaluate("sessionStorage.getItem('fraudlens_admin_token')")
    started=time.monotonic()
    with httpx.Client(timeout=30) as client:
        while time.monotonic()-started<600:
            response=client.get(API+'/v1/jobs/'+job_id,headers={'Authorization':'Bearer '+token})
            response.raise_for_status();job=response.json()
            if job['status'] in {'completed','done','failed','interrupted'}:return job
            time.sleep(1)
    raise AssertionError('Processing did not finish within ten minutes; last state '+job['status'])


def admin_action(page,action,reason,public,requested=None):
    page.locator('select[name=action]').select_option(label=action)
    page.locator('textarea[name=reason]').fill(reason)
    page.locator('textarea[name=publicNarrative]').fill(public)
    if requested:page.locator('textarea[name=requestedArtifacts]').fill(requested)
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/action'),timeout=60000) as response:
        page.get_by_role('button',name='Record human decision',exact=True).click()
    assert response.value.status==200,response.value.text()


def fill_intake(page,kind,photos):
    page.bring_to_front()
    page.goto(UI+'/apply/'+kind,wait_until='domcontentloaded',timeout=120000)
    submit_button=page.get_by_role('button',name='Submit claim' if kind=='claims' else 'Submit application',exact=True)
    expect(submit_button).to_be_enabled(timeout=60000)
    submit_button.click()
    assert not page.locator('form').first.evaluate('(form)=>form.checkValidity()')
    record(kind+' required-field browser validation')
    fields={'name':'Local demonstration applicant','email':'applicant@example.test','phone':'9876543210',
        'license':'DEMO-DL-001','address':'Local demonstration only','make':'Maruti','model':'Swift','variant':'ZXI',
        'year':'2022','registration':'MH12DE1001' if kind=='claims' else 'MH12DE1002',
        'engine':'DEMO-ENGINE','chassis':'DEMO-CHASSIS','idv':'500000','policy':'PILOT-'+kind,
        'description':'Local demonstration with existing research photographs. Damage, identity and intent have not been independently validated.'}
    if kind=='claims':fields.update({'incidentDate':'2026-10-13','incidentTime':'12:00','location':'Mumbai','amount':'25000'})
    for name,value in fields.items():
        control=page.locator('form [name="'+name+'"]')
        if control.count():control.fill(value)
    page.locator('select[name=policyType]').select_option(label='Comprehensive')
    if kind=='claims':page.locator('select[name=settlement]').select_option(label='Reimbursement')
    else:
        page.locator('select[name=applicationType]').select_option(label='Break-in Inspection')
        page.locator('select[name=condition]').select_option(label='Unsure; inspection needed')
    page.locator('input[name=consent]').check()
    if kind=='claims':page.get_by_label('Upload Damage overview',exact=True).set_input_files(str(photos[0]))
    else:
        for role,path in zip(['Front left','Front right','Rear left','Rear right','Odometer','Registration plate'],photos):
            page.get_by_label('Upload '+role,exact=True).set_input_files(str(path))
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v1/cases'),timeout=120000) as response:
        page.get_by_role('button',name='Submit claim' if kind=='claims' else 'Submit application',exact=True).click()
    assert response.value.status==201,response.value.text()
    submitted=response.value.json()
    expect(page.get_by_role('heading',name='Your case has been received.')).to_be_visible(timeout=30000)
    assert page.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
    record(kind+' immediate confirmation',case_id=submitted['case_id'],image_count=submitted['images_received'])
    return submitted


def open_case(page,case_id):
    page.bring_to_front()
    page.get_by_role('button',name='Case queue',exact=True).click()
    page.get_by_placeholder('Search case ID, registration, policy or claimant').fill(case_id)
    expect(page.get_by_role('button',name=case_id,exact=True)).to_be_visible(timeout=45000)
    page.get_by_role('button',name=case_id,exact=True).click()
    expect(page.get_by_role('heading',name='Vehicle photographs',exact=True)).to_be_visible(timeout=45000)


def track(page,case_id,registration):
    page.bring_to_front()
    page.goto(UI+'/track?case='+case_id,wait_until='domcontentloaded',timeout=60000)
    expect(page.get_by_role('heading',name='Track your case.')).to_be_visible(timeout=60000)
    expect(page.get_by_role('button',name='Check status')).to_be_enabled(timeout=60000)
    page.locator('input[name=identifier]').fill(registration)
    page.get_by_role('button',name='Check status').click()
    expect(page.locator('.tracker-result')).to_be_visible(timeout=45000)


def main():
    global observations
    parser=argparse.ArgumentParser()
    parser.add_argument('--post-review-only',action='store_true',help='Finish expiry/mobile verification after a preserved completed two-tab flow')
    args=parser.parse_args()
    if args.post_review_only:
        observations=json.loads((OUT/'browser_verification.json').read_text())
    credentials=json.loads((OUT/'demo_credentials.json').read_text())
    photos=sorted((ROOT/'data/curated/whole').glob('*.jpg'))
    if len(photos)<9:raise RuntimeError('Need existing genuine corpus photographs; no replacements are generated.')
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport={'width':1365,'height':900})
        admin=context.new_page();applicant=context.new_page()
        errors=[]
        for page in (admin,applicant):page.on('pageerror',lambda e:errors.append(str(e)))
        for page in (admin,applicant):
            page.on('requestfailed',lambda r:print('Browser network failure',r.method,r.url.split('?')[0],r.failure,flush=True))
            page.on('console',lambda m:print('Browser policy error',m.text[:500],flush=True) if m.type=='error' and ('Content Security Policy' in m.text or 'CORS' in m.text) else None)
        try:
            admin.goto(UI+'/admin',wait_until='domcontentloaded',timeout=120000)
            expect(admin.get_by_role('button',name='Sign in',exact=True)).to_be_enabled(timeout=120000)
            admin.locator('input[name=email]').fill(credentials['email'])
            admin.locator('input[name=password]').fill(credentials['password'])
            with admin.expect_response(lambda r:r.url.endswith('/v1/auth/login'),timeout=60000) as login:
                admin.get_by_role('button',name='Sign in',exact=True).click()
            assert login.value.status==200,login.value.text()
            expect(admin.get_by_role('button',name='Sign out',exact=True)).to_be_visible(timeout=45000)
            record('admin authenticated in separate tab',browser=browser.version,ui=UI,api=API)
            for kind in (() if args.post_review_only else ('claims','underwriting')):
                submitted=fill_intake(applicant,kind,photos[:1] if kind=='claims' else photos[1:7])
                case_id=submitted['case_id'];open_case(admin,case_id)
                record(kind+' queue refresh and case detail')
                job=poll_job(admin,submitted['job_id'])
                admin.get_by_role('button',name='Refresh case',exact=True).click()
                expect(admin.locator('.recommendation-panel')).to_contain_text('Analysis: '+job['status'],timeout=45000)
                record(kind+' processing terminal state',status=job['status'],provider_unavailable=job['provider_unavailable'])
                assert admin.locator('.finding-group article').count()>0, 'Recorded findings are missing from the interface'
                record(kind+' recorded findings visible',count=admin.locator('.finding-group article').count())
                admin.locator('.image-gallery button').first.click()
                expect(admin.get_by_role('dialog')).to_be_visible(timeout=45000)
                width=admin.locator('.evidence-viewer-stage img').evaluate('(image)=>image.naturalWidth')
                admin.keyboard.press('Escape');expect(admin.get_by_role('dialog')).not_to_be_visible()
                record(kind+' original evidence viewer and Escape',image_width=width)
                admin.get_by_role('button',name='Agent Trace',exact=True).click()
                record(kind+' agent trace opened',text_present=bool(admin.locator('main').inner_text()) if admin.locator('main').count() else True)
                admin.get_by_role('button',name='Report',exact=True).click()
                expect(admin.get_by_role('button',name='Print report',exact=True)).to_be_visible()
                admin.emulate_media(media='print')
                pdf=OUT/(kind+'-report.pdf');admin.pdf(path=str(pdf),format='A4',print_background=True)
                admin.screenshot(path=str(OUT/(kind+'-print.png')),full_page=True)
                admin.emulate_media(media='screen')
                from pypdf import PdfReader
                extracted='\n'.join(page.extract_text() or '' for page in PdfReader(pdf).pages)
                assert case_id in extracted and 'Declaration' in extracted and 'exif_metadata' in extracted and 'Processing run' in extracted
                record(kind+' readable PDF',pages=len(PdfReader(pdf).pages),text_characters=len(extracted))
                admin_action(admin,'Request More Evidence','Local demonstration request; no inference of claimant guilt.',
                             'Please upload the original additional vehicle photograph.','Original rear view including the registration plate')
                track(applicant,case_id,'MH12DE1001' if kind=='claims' else 'MH12DE1002')
                expect(applicant.get_by_role('heading',name='Requested photographs',exact=True)).to_be_visible()
                receipt=applicant.get_by_label('Private evidence access receipt').input_value()
                assert receipt
                applicant.locator('input[type=file]').set_input_files(str(photos[7] if kind=='claims' else photos[8]))
                with applicant.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/evidence'),timeout=120000) as response:
                    applicant.get_by_role('button',name='Submit requested evidence',exact=True).click()
                assert response.value.status==200,response.value.text()
                expect(applicant.get_by_role('heading',name='evidence received',exact=True)).to_be_visible(timeout=45000)
                record(kind+' requested evidence securely resubmitted')
                job=poll_job(admin,response.value.json()['job_id'])
                admin.bring_to_front();admin.get_by_role('button',name='Refresh case',exact=True).click()
                expect(admin.locator('.image-gallery button')).to_have_count(2 if kind=='claims' else 7,timeout=45000)
                admin.get_by_role('button',name='Report',exact=True).click()
                history=admin.get_by_label('Report history')
                saved_id=history.locator('option').filter(has_text=submitted['job_id']).first.get_attribute('value')
                assert saved_id
                history.select_option(saved_id)
                saved=admin.get_by_role('dialog',name='Historical report')
                expect(saved).to_be_visible(timeout=45000)
                expect(saved).to_contain_text(submitted['job_id'])
                expect(saved).to_contain_text('Declaration at this report version')
                admin.keyboard.press('Escape');expect(saved).not_to_be_visible()
                record(kind+' originals preserved and saved report opened with keyboard dismissal',analysis_status=job['status'])
                admin_action(admin,'Approve','Local demonstration completed; independent accuracy validation remains outstanding.',
                             'The local demonstration review is complete.')
                track(applicant,case_id,'MH12DE1001' if kind=='claims' else 'MH12DE1002')
                expect(applicant.get_by_role('heading',name='closed approved',exact=True)).to_be_visible(timeout=45000)
                expect(applicant.locator('.tracker-result')).to_contain_text('The local demonstration review is complete.')
                assert 'Independent accuracy' not in applicant.locator('.tracker-result').inner_text()
                record(kind+' human decision and public tracking verified')
                applicant.screenshot(path=str(OUT/(kind+'-tracking.png')),full_page=True)
            admin.get_by_role('button',name='Sign out',exact=True).click()
            expect(admin.get_by_role('button',name='Sign in',exact=True)).to_be_visible(timeout=30000)
            record('logout verified')
            # Only expire this automation session in its known isolated DB.
            if API=='http://127.0.0.1:8001':
                admin.locator('input[name=email]').fill(credentials['email'])
                admin.locator('input[name=password]').fill(credentials['password'])
                admin.get_by_role('button',name='Sign in',exact=True).click()
                expect(admin.get_by_role('button',name='Sign out',exact=True)).to_be_visible(timeout=45000)
                token=admin.evaluate("sessionStorage.getItem('fraudlens_admin_token')")
                conn=sqlite3.connect(OUT/'demo.db')
                try:
                    updated=conn.execute('UPDATE admin_sessions SET expires_at=0 WHERE token_hash=?',
                        (hashlib.sha256(token.encode()).hexdigest(),)).rowcount
                    assert updated==1,'No matching isolated demo session to expire'
                    conn.commit()
                finally:conn.close()
                admin.get_by_role('button',name='Case queue',exact=True).click()
                expect(admin.get_by_role('button',name='Sign in',exact=True)).to_be_visible(timeout=45000)
                assert admin.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
                record('expired reviewer session returns to login')
            mobile=context.new_page()
            mobile.set_viewport_size({'width':390,'height':844})
            mobile.goto(UI+'/track',wait_until='domcontentloaded',timeout=60000)
            assert mobile.evaluate('document.documentElement.scrollWidth')<=391
            mobile.screenshot(path=str(OUT/'mobile-tracker.png'),full_page=True)
            record('mobile tracker no horizontal overflow',width=390)
            record('browser post-review completed' if args.post_review_only else 'browser script completed',javascript_errors=errors)
            if errors:raise AssertionError('Browser JavaScript errors: '+str(errors))
        except Exception as exc:
            record('browser blocker',error_type=type(exc).__name__,message=str(exc)[:800])
            for name,page in [('admin',admin),('applicant',applicant)]:
                try:page.screenshot(path=str(OUT/(name+'-failure.png')),full_page=True)
                except Exception:pass
            raise
        finally:browser.close()


if __name__=='__main__':main()
