"""Real local rules viva rehearsal. No intercepted routes or provider grants.

Uses only the existing fictional presentation dataset and its private accounts.
New records are clearly labelled disposable software verification. Historical
cases are fingerprinted, never processed or acted on. Provider controls remain
unchanged. Archived photographs qualify admission, not current condition.
"""
import argparse, hashlib, json, os, sys, time, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'outputs/viva_local_20261027';OUT.mkdir(parents=True,exist_ok=True)
UI='http://127.0.0.1:5173';API='http://127.0.0.1:8001'


def write(name,value): (OUT/name).write_text(json.dumps(value,indent=2),encoding='utf8')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['submit','recover','inspect','persistence']);p.add_argument('--api-pid',required=True,type=int);a=p.parse_args()
    from scripts.diagnose_gemini import process_environment
    from src.pilot_config import load_pilot_environment
    env=load_pilot_environment(process_environment(a.api_pid));assert env['FRAUDLENS_PG_SCHEMA']=='fraudlens_validation_panel_20261022'
    os.environ.update(env)
    from src import db,runtime_store
    import httpx
    from playwright.sync_api import sync_playwright,expect
    cfg=json.loads((ROOT/'outputs/final_presentation/rehearsal/private-browser.json').read_text())
    def controls():return {name:digest(Path(env[name])) for name in ['FRAUDLENS_LIVE_LEDGER','GEMINI_QUOTA_BUDGET']}
    state_path=OUT/'real-state.private.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'schema':env['FRAUDLENS_PG_SCHEMA'],'controls_before':controls(),'cases':{}}
    if 'original_cases' not in state:
        with runtime_store.connection('postgresql') as conn:
            state['original_cases']={row['case_id']:hashlib.sha256(json.dumps(dict(row),sort_keys=True,default=str).encode()).hexdigest() for row in conn.execute('SELECT * FROM cases')}
            assert conn.execute("SELECT COUNT(*) FROM api_jobs WHERE status IN ('queued','running')").fetchone()[0]==0
        write(state_path.name,state)
    os.environ.update(PRESENTATION_UI=UI,PRESENTATION_API=API,PRESENTATION_OUTPUT_DIR=str(OUT),PRESENTATION_DB=str(OUT/'unused.db'))
    from scripts import verify_presentation_browser as h
    stage='browser'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport={'width':1365,'height':900},accept_downloads=True)
        customer=context.new_page();admin=context.new_page()
        customer.set_default_timeout(45000);admin.set_default_timeout(45000)
        errors=[];transport=[]
        for page in [customer,admin]:
            page.on('pageerror',lambda exc:errors.append(type(exc).__name__))
            page.on('response',lambda response:transport.append({'path':response.url.split(API)[-1].split('?')[0],'status':response.status}) if response.url.startswith(API) else None)
        try:
            stage='customer_login';h.customer_signin(customer,cfg['customer'])
            stage='reviewer_login';h.admin_signin(admin,cfg['reviewer'])
            ch=h.headers(customer,'customer');ah=h.headers(admin)
            with httpx.Client(timeout=120) as client:
                if a.phase=='submit':
                    from PIL import Image
                    source=ROOT.parent/'docs/presentation_assets'
                    plate=OUT/'mounted-plate.png'
                    with Image.open(source/'chevrolet-classic-rear.jpg') as image:
                        w,h_=image.size;image.crop((int(w*.34),int(h_*.62),int(w*.72),int(h_*.99))).save(plate)
                    files={'claims':[source/name for name in ['chevrolet-classic-front-right.jpg','chevrolet-classic-left.jpg','chevrolet-classic-door.jpg']]+[plate],
                           'underwriting':[source/name for name in ['chevrolet-classic-left.jpg','chevrolet-classic-front-right.jpg','chevrolet-classic-rear-left.jpg','chevrolet-classic-rear-right.jpg','chevrolet-classic-gauges.jpg']]+[plate]}
                    # Claims order pairs the mounted plate with its actual slot.
                    files['claims']=[files['claims'][0],plate,files['claims'][1],files['claims'][2]]
                    native_rows=[]
                    for kind in ['claims','underwriting']:
                        if kind in state['cases']:continue
                        stage=kind+'_form';customer.goto(UI+'/apply/'+kind,wait_until='domcontentloaded',timeout=120000)
                        expect(customer.locator('.upload-slot input')).to_have_count(len(files[kind]),timeout=90000)
                        values={'name':'Fictional Local Viva Verification','email':cfg['customer']['email'],'phone':'9000000082','license':'FICTIONAL-LICENCE',
                            'address':'Fictional local software verification address','make':'Chevrolet','model':'Classic','variant':'Archived licensed public photograph sample',
                            'year':'2005','registration':'MH12VR4083','engine':'FICTIONAL-ENGINE','chassis':'FICTIONAL-CHASSIS','idv':'500000','policy':'FICTIONAL-LOCAL-VIVA-20261027',
                            'incidentDate':'2026-10-26','incidentTime':'12:00','location':'Fictional declared incident location','amount':'2000',
                            'description':'FICTIONAL DISPOSABLE SOFTWARE VERIFICATION. Licensed archived photographs by Milkmandan, CC BY-SA 3.0; no current insured loss, ownership or readable mileage established. Gemini remains paused and is not used. This is a local rules workflow demonstration; no live AI completion is claimed.'}
                        for field in customer.locator('.intake-form [required]').all():
                            name=field.get_attribute('name');type_=field.get_attribute('type')
                            if type_=='checkbox':continue
                            if field.evaluate('e=>e.tagName')=='SELECT':field.select_option(index=1)
                            else:field.fill(values[name])
                        customer.keyboard.press('Escape')
                        inputs=customer.locator('.upload-slot input')
                        for i,path in enumerate(files[kind]):
                            stage=kind+'_native_'+str(i)
                            with customer.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/photos/validate'),timeout=180000) as validation:
                                inputs.nth(i).set_input_files(str(path))
                            result=validation.value.json()
                            native_rows.append({'kind':kind,'image_sha256':digest(path),'http_status':validation.value.status,**result})
                            write('real-positive-results.json',native_rows)
                            expect(customer.locator('.upload-item').nth(i)).to_contain_text('accepted:',timeout=180000)
                        customer.locator('[name=consent]').check();expect(customer.locator('.submit-case')).to_be_enabled()
                        customer.screenshot(path=str(OUT/(kind+'-real-form.png')),full_page=True)
                        stage=kind+'_submit'
                        with customer.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v1/cases'),timeout=180000) as response:customer.locator('.submit-case').click()
                        assert response.value.status==201, response.value.status
                        receipt=response.value.json();state['cases'][kind]=receipt;write(state_path.name,state)
                        with runtime_store.connection('postgresql') as conn:
                            assert sorted(row[0] for row in conn.execute('SELECT content_hash FROM images WHERE case_id=?',(receipt['case_id'],)))==sorted(digest(path) for path in files[kind])
                        expect(customer.get_by_text('Your case has been received.',exact=True)).to_be_visible()
                        print(json.dumps({'stage':'durable_submission','kind':kind,'case_id':receipt['case_id'],'job_id':receipt['job_id'],'real_photos':len(files[kind])}),flush=True)
                    # Native unrelated negatives are a separate qualification sample.
                    stage='native_negatives';import skimage.data
                    negative=Path(skimage.data.__file__).parent/'chelsea.png';negative_results=[]
                    from src.photo_admission import SLOTS
                    for kind,slots in SLOTS.items():
                        for slot in slots:
                            response=client.post(API+'/v1/photos/validate',headers=ch,data={'agent_type':kind,'slot':slot},files={'image':('animal.png',negative.read_bytes(),'image/png')})
                            result=response.json();assert response.status_code==200 and result['state'] in {'rejected','needs_replacement'}
                            negative_results.append({'kind':kind,'slot':slot,'state':result['state'],'basis':'native local CLIP / real animal photograph'})
                    write('real-negative-results.json',negative_results)
                    damage_results=[]
                    for photo in sorted((ROOT/'data/curated/damaged').glob('*.jpg'))[:4]:
                        response=client.post(API+'/v1/photos/validate',headers=ch,data={'agent_type':'claims','slot':'damage_closeup'},files={'image':(photo.name,photo.read_bytes(),'image/jpeg')})
                        result=response.json();assert response.status_code==200 and result['state']=='accepted'
                        damage_results.append({'source':photo.name,'basis':'existing real damaged-car corpus / native local CLIP','sha256':digest(photo),**result})
                    write('real-damaged-positive-results.json',damage_results)
                else:
                    if a.phase=='persistence' and (OUT/'claims-before-api-restart.json').exists():
                        earlier=json.loads((OUT/'claims-before-api-restart.json').read_text())
                        for id_key,hash_key in [('snapshot_id','pdf_sha256'),('reviewed_snapshot_id','reviewed_pdf_sha256')]:
                            response=client.get(API+f"/v1/cases/{earlier['case_id']}/reports/{earlier[id_key]}/pdf",headers=ah)
                            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==earlier[hash_key]
                        print('Earlier pre-restart PDFs remain byte-identical.',flush=True)
                    for kind,receipt in state['cases'].items():
                        case=receipt['case_id'];stage=kind+'_saved_report'
                        job=client.get(API+'/v1/jobs/'+receipt['job_id'],headers=ah);job.raise_for_status();job=job.json()
                        if a.phase=='recover':
                            if job['status']=='failed':
                                stage=kind+'_reviewer_retry';h.open_case(admin,case)
                                admin.get_by_text('Technical diagnostics',exact=True).click()
                                with admin.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/reprocess'),timeout=120000) as retry:
                                    admin.get_by_role('button',name='Retry analysis',exact=True).click()
                                assert retry.value.status in {200,202}
                                result=retry.value.json()
                                receipt.setdefault('accepted_job_id',receipt['job_id'])
                                receipt.setdefault('earlier_failed_runs',[]).append(receipt['job_id'])
                                receipt['job_id']=result['job_id'];write(state_path.name,state)
                                print(json.dumps({'kind':kind,'reviewer_retry':'queued','job_id':receipt['job_id']}),flush=True)
                            else:print(json.dumps({'kind':kind,'status':job['status']}),flush=True)
                            continue
                        assert job['status']=='completed',job['status']
                        report=client.get(API+'/v1/cases/'+case+'/report',headers=ah);report.raise_for_status();report=report.json()
                        contract=report['assessment_presentation'];assert contract['run_id']==receipt['job_id'] and contract['score'] is None
                        assert contract['method']=='Local rules assessment' and contract['complete'] and not contract['provisional']
                        row=next(row for row in client.get(API+'/v1/cases',headers=ah).json()['items'] if row['case_id']==case)
                        assert row['assessment_presentation']==contract
                        if a.phase=='persistence':
                            previous=json.loads((OUT/(kind+'-real-verification.json')).read_text())
                            assert previous['assessment']==contract
                            url=API+f'/v1/cases/{case}/reports/'+previous['snapshot_id']+'/pdf'
                            assert hashlib.sha256(client.get(url,headers=ah).content).hexdigest()==previous['pdf_sha256']
                            reviewed_url=API+f'/v1/cases/{case}/reports/'+previous['reviewed_snapshot_id']+'/pdf'
                            assert hashlib.sha256(client.get(reviewed_url,headers=ah).content).hexdigest()==previous['reviewed_pdf_sha256']
                            assert report['admin_action']['action']=='request_more_evidence'
                            print(json.dumps({'kind':kind,'restart_persistence':'passed'}),flush=True);continue
                        h.open_case(admin,case)
                        expect(admin.get_by_text(contract['label'],exact=True)).to_be_visible(timeout=120000)
                        expect(admin.get_by_text(contract['status_label'],exact=True).first).to_be_visible(timeout=120000)
                        admin.screenshot(path=str(OUT/(kind+'-real-admin.png')),full_page=True)
                        admin.set_viewport_size({'width':390,'height':844});admin.screenshot(path=str(OUT/(kind+'-real-mobile.png')),full_page=True)
                        assert not admin.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                        admin.set_viewport_size({'width':1365,'height':900})
                        stage=kind+'_pdf'
                        for preview_attempt in range(3):
                            preview_button=admin.get_by_role('button',name='Preview report',exact=True)
                            expect(preview_button).to_be_enabled(timeout=120000);preview_button.click()
                            try:
                                expect(admin.get_by_role('dialog',name='PDF report preview')).to_be_visible(timeout=210000)
                                break
                            except AssertionError:
                                if preview_attempt==2:raise
                                print(json.dumps({'kind':kind,'preview':'retry after bounded request timeout; saved analysis retained'}),flush=True)
                        admin.screenshot(path=str(OUT/(kind+'-real-preview.png')),full_page=True)
                        admin.get_by_role('button',name='Close preview',exact=True).click()
                        with admin.expect_download(timeout=120000) as download:admin.get_by_role('button',name='Download PDF',exact=True).click()
                        pdf_path=OUT/(kind+'-real.pdf');download.value.save_as(pdf_path)
                        versions=client.get(API+f'/v1/cases/{case}/reports',headers=ah).json()['reports'];version=versions[0]
                        url=API+f'/v1/cases/{case}/reports/'+version['snapshot_id']+'/pdf'
                        assert client.get(url,headers=ah).content==client.get(url+'?download=true',headers=ah).content==pdf_path.read_bytes()
                        from pypdf import PdfReader
                        reader=PdfReader(pdf_path);front=reader.pages[0].extract_text()
                        assert contract['label'] in front and contract['method'] in front and contract['status_label'] in front
                        assert client.get(url,headers=ch).status_code in {401,403}
                        stage=kind+'_review_action'
                        if not report.get('admin_action'):
                            admin.locator('select[name=action]').select_option(label='Request More Evidence')
                            admin.locator('textarea[name=reason]').fill('Fictional local viva verification: manual review of archived photographs, unresolved identity and current condition. No fraud finding or AI clearance.')
                            public='Fictional local viva verification: please provide current readable registration and '+('incident evidence.' if kind=='claims' else 'powered odometer evidence.')
                            admin.locator('textarea[name=publicNarrative]').fill(public)
                            admin.locator('textarea[name=requestedArtifacts]').fill('Current readable mounted registration photograph\n'+('Evidence supporting the declared incident' if kind=='claims' else 'Powered odometer with readable mileage and units'))
                            with admin.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/action'),timeout=120000) as action:admin.get_by_role('button',name='Request more evidence',exact=True).click()
                            assert action.value.status==200
                        customer.bring_to_front()
                        customer.goto(UI+'/dashboard?case='+case,wait_until='domcontentloaded',timeout=120000)
                        expect(customer.locator('.ud-case-heading')).to_contain_text(case,timeout=120000)
                        expect(customer.locator('.ud-narrative')).to_contain_text('Fictional local viva verification:',timeout=120000)
                        customer.screenshot(path=str(OUT/(kind+'-real-customer.png')),full_page=True)
                        assert client.get(url,headers=ah).content==pdf_path.read_bytes()
                        reviewed=client.post(API+f'/v1/cases/{case}/reports/prepare',headers=ah).json()
                        reviewed_url=API+f'/v1/cases/{case}/reports/'+reviewed['snapshot_id']+'/pdf'
                        reviewed_path=OUT/(kind+'-real-reviewed.pdf');reviewed_path.write_bytes(client.get(reviewed_url,headers=ah).content)
                        assert contract['label'] in PdfReader(reviewed_path).pages[0].extract_text()
                        write(kind+'-real-verification.json',{'kind':kind,'case_id':case,'run_id':receipt['job_id'],'processing':job['status'],
                            'assessment':contract,'snapshot_id':version['snapshot_id'],'pdf_sha256':digest(pdf_path),'pdf_pages':len(reader.pages),
                            'reviewed_snapshot_id':reviewed['snapshot_id'],'reviewed_pdf_sha256':digest(reviewed_path),
                            'source':'actual Chrome/API/PostgreSQL/worker; no route interception','preview_download_equal':True,
                            'reviewer_customer_update':True,'mobile_no_overflow':True,'live_ai_completion':False,'local_rules_complete':True})
                        print(json.dumps({'kind':kind,'workflow':'passed','processing':job['status'],'display_band':contract['display_band'],'pages':len(reader.pages)}),flush=True)
                assert not errors,errors
                assert controls()==state['controls_before'],'Provider controls changed'
                with runtime_store.connection('postgresql') as conn:
                    for case,checksum in state['original_cases'].items():
                        row=conn.execute('SELECT * FROM cases WHERE case_id=?',(case,)).fetchone()
                        assert hashlib.sha256(json.dumps(dict(row),sort_keys=True,default=str).encode()).hexdigest()==checksum
                write('real-preservation.json',{'original_cases_unchanged':len(state['original_cases']),'provider_ledgers_byte_identical':True,'new_fictional_cases':len(state['cases'])})
        except Exception as exc:
            write('real-transport.json',transport)
            print(json.dumps({'stage':stage,'error_type':type(exc).__name__,'page_error_types':errors,'lines':[line.lineno for line in traceback.extract_tb(exc.__traceback__) if Path(line.filename).name==Path(__file__).name]}),flush=True)
            try:customer.screenshot(path=str(OUT/'real-failure.png'),timeout=5000)
            except Exception:pass
            try:admin.screenshot(path=str(OUT/'real-admin-failure.png'),timeout=5000)
            except Exception:pass
            raise SystemExit(1)
        finally:browser.close()


if __name__=='__main__':main()
