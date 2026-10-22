"""Real API intake and UI/PDF inspection for explicitly authorized isolated cases.

No inference probes, mocked routes, direct outcome inserts or reviewer decisions.
Submit is idempotent; inspect/browser only read results and prepare saved PDFs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['submit','inspect','browser'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--kind',choices=['claims','underwriting'],default='claims')
    parser.add_argument('--process-id',type=int,required=True,help='Require the actual isolated API process environment.')
    args=parser.parse_args();directory=args.directory.resolve()
    config=json.loads((directory/'private-validation.json').read_text(encoding='utf8'))
    from scripts.diagnose_gemini import process_environment
    from src.pilot_config import load_pilot_environment
    reference=load_pilot_environment(process_environment(args.process_id))
    if reference['FRAUDLENS_PG_SCHEMA']!=config['schema'] or reference.get('FRAUDLENS_VALIDATION_ID')!=config['validation_id']:
        raise SystemExit('The API is not the matching isolated validation service; no request sent.')
    accepted_path=directory/(args.kind+'-accepted.json')
    accepted=json.loads(accepted_path.read_text()) if accepted_path.exists() else None
    api=config['api'];kind=args.kind
    with httpx.Client(timeout=120) as client:
        if args.operation=='submit' and accepted:
            print(json.dumps({'already_accepted':True,**accepted}));return
        customer=config['customer']
        login=client.post(api+'/v1/customer/auth/login',json={k:customer[k] for k in ['email','password']})
        if login.status_code==401 and args.operation=='submit':
            login=client.post(api+'/v1/customer/auth/register',json=customer)
        login.raise_for_status();customer_headers={'Authorization':'Bearer '+login.json()['token']}
        reviewer=client.post(api+'/v1/auth/login',json=config['reviewer']);reviewer.raise_for_status()
        reviewer_headers={'Authorization':'Bearer '+reviewer.json()['token']}
        if args.operation=='submit':
            photos=config['photos'][kind]
            if not photos or (kind=='underwriting' and len(photos)!=6):raise SystemExit('Suitable authorized evidence is unavailable.')
            key_path=directory/(kind+'-idempotency.json')
            key=json.loads(key_path.read_text()) if key_path.exists() else str(uuid.uuid4())
            if not key_path.exists():key_path.write_text(json.dumps(key))
            data={'agent_type':kind,'claim_type':'collision' if kind=='claims' else 'break_in',
                'claim_amount':'20000','declared_location':'Pune','declared_time':'2026-10-20T10:00:00+05:30',
                'vehicle_registration':'MH12EX9221','vehicle_make':'Volkswagen','vehicle_model':'Golf',
                'vehicle_variant':'Fictional validation example','vehicle_year':'2018','policy_number':'VALIDATION-CLAIMS-2026',
                'policy_type':'Comprehensive','idv':'400000','garage_id':'UNASSIGNED',
                'person_name':'Fictional Live Validation','person_contact':'9000000000',
                'declaration_notes':'Fictional software validation case. The sample photograph shows rear-panel damage; registration, policy, incident date/location and amount are synthetic test declarations, not facts established by this photograph. Assess only the available evidence.'}
            files=[('images',(f'authorized-sample-{i+1}.jpg',Path(path).read_bytes(),'image/jpeg')) for i,path in enumerate(photos)]
            submitted=client.post(api+'/v1/cases',data=data,files=files,
                headers={**customer_headers,'Idempotency-Key':key})
            if submitted.status_code!=201:
                body=submitted.json();print(json.dumps({'submission_status':submitted.status_code,'code':body.get('code'),'message':body.get('message')}))
                raise SystemExit('Case was not accepted; no worker was started.')
            accepted={key:submitted.json()[key] for key in ['case_id','job_id','status','images_received']}
            accepted_path.write_text(json.dumps(accepted,indent=2))
            own=client.get(api+'/v1/customer/cases/'+accepted['case_id'],headers=customer_headers)
            own.raise_for_status();assert own.json()['id']==accepted['case_id']
            print(json.dumps({'accepted_through_actual_api':True,'ownership_verified':True,**accepted}));return
        if not accepted:raise SystemExit('No accepted case to inspect; no replacement was created.')
        case=accepted['case_id'];run=accepted['job_id']
        job=client.get(api+'/v1/jobs/'+run,headers=reviewer_headers);job.raise_for_status()
        if job.json()['status'] in {'queued','running'}:
            print(json.dumps({'terminal':False,'job':job.json()}));return
        report=client.get(api+'/v1/cases/'+case+'/report',headers=reviewer_headers);report.raise_for_status()
        customer_view=client.get(api+'/v1/customer/cases/'+case,headers=customer_headers);customer_view.raise_for_status()
        assert customer_view.json()['processingStatus']==job.json()['status']
        # A distinct account must not inherit this case or its private images.
        outsider={**customer,'email':'validation-outsider@example.test'}
        other=client.post(api+'/v1/customer/auth/login',json={k:outsider[k] for k in ['email','password']})
        if other.status_code==401:other=client.post(api+'/v1/customer/auth/register',json=outsider)
        other.raise_for_status();other_headers={'Authorization':'Bearer '+other.json()['token']}
        denied=client.get(api+'/v1/customer/cases/'+case,headers=other_headers)
        assert denied.status_code in {403,404}
        for image in customer_view.json().get('images') or []:
            owner_image=client.get(api+image['url'],headers=customer_headers)
            other_image=client.get(api+image['url'],headers=other_headers)
            assert owner_image.status_code==200 and other_image.status_code in {403,404}
        anonymous=client.get(api+'/v1/cases/'+case+'/report');assert anonymous.status_code==401
        customer_pdf=client.get(api+'/v1/cases/'+case+'/reports',headers=customer_headers)
        assert customer_pdf.status_code in {401,403}
        version=client.post(api+'/v1/cases/'+case+'/reports/prepare',headers=reviewer_headers)
        version.raise_for_status();snapshot=version.json()['snapshot_id']
        path=api+f'/v1/cases/{case}/reports/{snapshot}/pdf'
        preview=client.get(path,headers=reviewer_headers);preview.raise_for_status()
        download=client.get(path,params={'download':'true'},headers=reviewer_headers);download.raise_for_status()
        assert preview.content==download.content
        pdf=directory/(kind+'-live.pdf');pdf.write_bytes(preview.content)
        for name,value in [('job',job.json()),('report',report.json()),('customer',customer_view.json())]:
            (directory/(kind+'-'+name+'.json')).write_text(json.dumps(value,indent=2))
        result={'case_id':case,'run_id':run,'status':job.json()['status'],'snapshot_id':snapshot,
            'same_saved_pdf_preview_download':True,'sha256':hashlib.sha256(preview.content).hexdigest(),
            'ownership_and_role_checks':True,'risk_presentation':report.json().get('assessment_presentation')}
        if args.operation=='browser':
            browser_result=browser(config,accepted,directory,report.json(),snapshot,pdf,kind)
            result['browser']=browser_result
        (directory/(kind+'-verification.json')).write_text(json.dumps(result,indent=2))
        print(json.dumps(result))


def browser(config,accepted,directory,report,snapshot,pdf,kind):
    from playwright.sync_api import sync_playwright,expect
    os.environ.update(PRESENTATION_UI=config['ui'],PRESENTATION_API=config['api'],
        PRESENTATION_OUTPUT_DIR=str(directory),PRESENTATION_DB=str(directory/'unused.db'))
    source=ROOT/'scripts/verify_presentation_browser.py'
    spec=importlib.util.spec_from_file_location('scoped_browser_helpers',source)
    helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
    with sync_playwright() as p:
        chrome=p.chromium.launch(channel='chrome',headless=True,args=['--disable-gpu'])
        context=chrome.new_context(viewport={'width':1365,'height':900},accept_downloads=True)
        customer=context.new_page();admin=context.new_page();errors=[]
        customer.on('pageerror',lambda e:errors.append(type(e).__name__))
        admin.on('pageerror',lambda e:errors.append(type(e).__name__))
        admin.add_init_script('''(() => {const original=URL.createObjectURL;window.__pdfHashes={};
            URL.createObjectURL=function(blob){const url=original.call(this,blob);
            if(blob.type==='application/pdf')window.__pdfHashes[url]=blob.arrayBuffer().then(b=>crypto.subtle.digest('SHA-256',b)).then(h=>[...new Uint8Array(h)].map(x=>x.toString(16).padStart(2,'0')).join(''));return url;};})();''')
        helpers.customer_signin(customer,config['customer']);helpers.admin_signin(admin,config['reviewer'])
        assert customer.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
        assert admin.evaluate("sessionStorage.getItem('fraudlens_customer_token')") is None
        customer.goto(config['ui']+'/dashboard?case='+accepted['case_id'],wait_until='domcontentloaded')
        expect(customer.get_by_role('heading',name=accepted['case_id'],exact=True)).to_be_visible(timeout=45000)
        customer.screenshot(path=str(directory/'customer-live.png'),full_page=True)
        helpers.open_case(admin,accepted['case_id'])
        # Evidence is intentionally lazy-loaded; scroll it into view before
        # capturing a full-page screenshot or asserting image availability.
        admin.locator('.review-photos').scroll_into_view_if_needed()
        expect(admin.locator('.review-photos img')).to_have_count(len(config['photos'][kind]))
        admin.wait_for_function("() => [...document.querySelectorAll('.review-photos img')].every(i=>i.complete&&i.naturalWidth>0)",timeout=45000)
        admin.evaluate('scrollTo(0,0)')
        risk=report['assessment_presentation']
        valid=risk.get('complete') and risk.get('category') in ['Low','Medium','High'] and risk.get('state') in ['completed','historical'] and risk.get('processing_state') in ['completed','done']
        expected='Assessed risk: '+risk['category'] if valid else 'Assessment incomplete'
        expect(admin.locator('.risk-indicator')).to_have_attribute('aria-label',expected)
        expect(admin.get_by_role('button',name='Preview report',exact=True)).to_be_enabled(timeout=60000)
        for width in [1365,390]:
            admin.set_viewport_size({'width':width,'height':900})
            assert admin.evaluate('document.documentElement.scrollWidth<=innerWidth')
            admin.screenshot(path=str(directory/f'admin-live-{width}.png'),full_page=True)
        admin.set_viewport_size({'width':1365,'height':900})
        panel=admin.get_by_role('region',name='Saved PDF report')
        panel.get_by_label('PDF report version',exact=True).select_option(snapshot)
        panel.get_by_role('button',name='Preview report',exact=True).click()
        dialog=admin.get_by_role('dialog',name='PDF report preview',exact=True)
        expect(dialog).to_be_visible(timeout=90000)
        blob=dialog.locator('iframe').evaluate('async f=>await window.__pdfHashes[f.src]')
        assert blob==hashlib.sha256(pdf.read_bytes()).hexdigest()
        # Let the native PDF viewer paint after receiving the verified blob.
        admin.wait_for_timeout(1500)
        dialog.screenshot(path=str(directory/'pdf-preview-live.png'))
        dialog.get_by_role('button',name='Close preview',exact=True).click()
        with admin.expect_download(timeout=90000) as download:
            panel.get_by_role('button',name='Download PDF',exact=True).click()
        destination=directory/(kind+'-browser-download.pdf');download.value.save_as(str(destination))
        assert destination.read_bytes()==pdf.read_bytes()
        assert not errors
        chrome.close()
    return {'two_normal_tabs':True,'risk_matches_saved_contract':True,'laptop_mobile_no_overflow':True,
        'preview_download_identical_saved_bytes':True,'javascript_errors':errors}


if __name__=='__main__':main()
