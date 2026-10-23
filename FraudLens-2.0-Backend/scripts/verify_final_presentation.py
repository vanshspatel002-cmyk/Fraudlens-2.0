"""Real Chrome/API rehearsal against an explicitly isolated PostgreSQL session.

No mocked routes, outcome insertion, provider probe or automatic reprocessing.
Credentials and receipts stay in the ignored output directory. Errors expose
only stage/type/line numbers, never input values or credential-bearing messages.
"""
import argparse,hashlib,json,os,sys,time,traceback,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['submit','inspect','pdf','admission-smoke','sessions'])
 p.add_argument('--kind',choices=['claims','underwriting'],default='claims');p.add_argument('--directory',type=Path,required=True)
 a=p.parse_args();D=a.directory.resolve();cfgpath=D/'private-browser.json';cfg=json.loads(cfgpath.read_text())
 if not cfg['schema'].startswith('fraudlens_validation_'):raise ValueError('Isolated presentation data required.')
 os.environ.update(PRESENTATION_UI=cfg['ui'],PRESENTATION_API=cfg['api'],PRESENTATION_OUTPUT_DIR=str(D),PRESENTATION_DB=str(D/'unused.db'))
 from scripts import verify_presentation_browser as h
 from playwright.sync_api import sync_playwright,expect
 from src.photo_admission import SLOTS
 assets=ROOT/'outputs/final_presentation/assets'
 files={'claims':['chevrolet-classic-front-right.jpg','chevrolet-classic-left.jpg','chevrolet-classic-interior.jpg','chevrolet-classic-door.jpg'],
        'underwriting':['chevrolet-classic-left.jpg','chevrolet-classic-front-right.jpg','chevrolet-classic-rear-left.jpg','chevrolet-classic-rear-right.jpg','chevrolet-classic-gauges.jpg','chevrolet-classic-rear.jpg']}
 def write(name,value): (D/name).write_text(json.dumps(value,indent=2),encoding='utf8')
 stage='browser_start'
 os.environ.setdefault('PW_TEST_SCREENSHOT_NO_FONTS_READY','1')
 with sync_playwright() as pw:
  # An ordinary persistent Chrome profile, with both roles in the same context.
  # It is private rehearsal state, never the user's personal Chrome profile.
  context=pw.chromium.launch_persistent_context(str(D/'chrome-profile'),channel='chrome',headless=False,
      viewport={'width':1365,'height':900},accept_downloads=True)
  browser=context
  customer=context.new_page();admin=context.new_page()
  for page in list(context.pages):
   if page not in (customer,admin):page.close()
  try:
   stage='customer_login';h.customer_signin(customer,cfg['customer'],register=not cfg.get('registered'))
   cfg['registered']=True;cfgpath.write_text(json.dumps(cfg,indent=2),encoding='utf8')
   if a.phase=='admission-smoke':
    import httpx,skimage.data
    headers=h.headers(customer,'customer');rows=[];pack=Path(skimage.data.__file__).parent
    negatives=[('animal',pack/'chelsea.png','damage_closeup'),('document',pack/'page.png','front_registration'),('person',pack/'astronaut.png','vehicle_overview'),('food',pack/'coffee.png','odometer'),
      ('document-damage',pack/'page.png','damage_overview'),('person-plate',pack/'astronaut.png','front_registration'),
      ('animal-plate',pack/'chelsea.png','registration_plate'),('food-damage',pack/'coffee.png','damage_closeup'),
      ('motorcycle',pack/'motorcycle_left.png','front_left'),('scenery',pack/'grass.png','rear_left'),('object-damage',pack/'coins.png','damage_closeup')]
    positives=[(slot,assets/name,slot) for kind in files for slot,name in zip(SLOTS[kind],files[kind])]
    with httpx.Client(timeout=45) as client:
     for name,path,slot in negatives+positives:
      kind='underwriting' if slot in {'front_left','front_right','rear_left','rear_right','odometer','registration_plate'} else 'claims'
      response=client.post(cfg['api']+'/v1/photos/validate',headers=headers,data={'agent_type':kind,'slot':slot},files={'image':(path.name,path.read_bytes(),'image/png' if path.suffix=='.png' else 'image/jpeg')})
      data=response.json();rows.append(dict(name=name,slot=slot,http_status=response.status_code,state=data.get('state'),reason=data.get('reason') or data.get('message'),scores=data.get('scores'),source='real_local_model'))
      write('real-admission.json',rows);time.sleep(2)
    print(json.dumps({'real_admission':rows}),flush=True);return
   stage='reviewer_login';h.admin_signin(admin,cfg['reviewer'])
   if a.phase=='sessions':
    customer.bring_to_front();customer.reload(wait_until='domcontentloaded');expect(customer.get_by_role('button',name='Sign out customer',exact=True)).to_be_visible(timeout=45000)
    with customer.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/customer/auth/logout'),timeout=45000) as logout:customer.get_by_role('button',name='Sign out customer',exact=True).click()
    assert logout.value.status==200
    admin.bring_to_front();admin.reload(wait_until='domcontentloaded');expect(admin.get_by_role('button',name='Sign out',exact=True)).to_be_visible(timeout=45000)
    h.customer_signin(customer,cfg['customer']);admin.bring_to_front()
    with admin.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v1/auth/logout'),timeout=45000) as logout:admin.get_by_role('button',name='Sign out',exact=True).click()
    assert logout.value.status==200
    customer.bring_to_front();customer.reload(wait_until='domcontentloaded');expect(customer.get_by_role('button',name='Sign out customer',exact=True)).to_be_visible(timeout=45000)
    result={'schema':cfg['schema'],'verified_at':time.time(),'persistent_regular_chrome':True,'same_context':True,'customer_logout_keeps_admin':True,'admin_logout_keeps_customer':True,'refresh_verified':True}
    write('sessions-verification.json',result);print(json.dumps(result),flush=True);return
   if a.phase=='submit':
    customer.bring_to_front()
    accepted=D/(a.kind+'-accepted.private.json')
    if accepted.exists():raise ValueError('A case was already accepted; inspect rather than resubmit.')
    stage='application_fields';customer.goto(cfg['ui']+'/apply/'+a.kind,wait_until='domcontentloaded')
    fields=['name','email','phone','license','address','make','model','variant','year','registration','engine','chassis','idv','policy','ncb','description']
    fields+=['incidentDate','incidentTime','location','amount','garage'] if a.kind=='claims' else ['previousPolicy']
    for name in fields:h.sample(customer,name)
    values={'name':'Fictional Panel Applicant','email':cfg['customer']['email'],'phone':'9000000067','registration':'MH12PX4067',
     'make':'Chevrolet','model':'Classic','variant':'Archived public rental-car sample','year':'2005','policy':'FICTIONAL-PANEL-2026',
     'description':'FICTIONAL SOFTWARE REHEARSAL with licensed archived 2005 photographs by Milkmandan. No relationship to the real car owner or policy is asserted. '+(
       'Applicant reports an unconfirmed interior electrical/window concern; these photos do not establish damage or repair cost. Incident date, location, coordinates and INR 2000 amount are fictional declarations, not authenticated capture evidence.' if a.kind=='claims' else
       'Condition is uncertain. The dashboard display is off; mileage has not been established. These archives do not verify current condition, identity, ownership or policy.')}
    if a.kind=='claims':values.update(amount='2000',garage='UNASSIGNED',incidentDate='2026-10-22',incidentTime='15:30',location='Fictional incident point: Vadodara sample coordinates')
    for name,value in values.items():customer.locator('form [name="'+name+'"]').fill(value)
    customer.keyboard.press('Escape');customer.locator('select[name="policyType"]').select_option(label='Comprehensive')
    if a.kind=='claims':
     customer.locator('[name=latitude]').fill('22.3');customer.locator('[name=longitude]').fill('73.2');customer.locator('[name=incidentOffset]').select_option('+05:30')
     customer.locator('select[name=settlement]').select_option(label='Reimbursement')
    else:
     customer.locator('select[name=applicationType]').select_option(label='Break-in Inspection');customer.locator('select[name=condition]').select_option(label='Unsure; inspection needed')
    stage='real_photo_admission';inputs=customer.locator('.upload-slot input[type=file]')
    for i,name in enumerate(files[a.kind]):
     inputs.nth(i).set_input_files(str(assets/name))
     expect(customer.locator('.upload-item').nth(i)).to_contain_text('accepted:',timeout=45000)
    customer.locator('input[name=consent]').check();button=customer.locator('.submit-case');expect(button).to_be_enabled()
    write(a.kind+'-form-values.json',customer.locator('form').evaluate("form => Object.fromEntries([...new FormData(form)].filter(([key,value]) => typeof value === 'string'))"))
    customer.screenshot(path=str(D/(a.kind+'-application.png')),full_page=True)
    stage='durable_submission';started=time.monotonic()
    with customer.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v1/cases'),timeout=90000) as captured:button.click()
    response=captured.value
    if response.status!=201:
     write(a.kind+'-submission-failure.json',{'http_status':response.status,'error':response.json()})
     raise ValueError('Initial submission not accepted: HTTP '+str(response.status))
    data=response.json();write(a.kind+'-accepted.private.json',data)
    write(a.kind+'-submission.json',{'case_id':data['case_id'],'run_id':data['job_id'],'accepted_seconds':round(time.monotonic()-started,3),'required_photos':len(files[a.kind]),'real_gate':True,'schema':cfg['schema']})
    stage='visible_ownership';customer.goto(cfg['ui']+'/dashboard?case='+data['case_id'],wait_until='domcontentloaded');h.open_case(admin,data['case_id'])
    customer.screenshot(path=str(D/(a.kind+'-customer-queued.png')),full_page=True);admin.screenshot(path=str(D/(a.kind+'-admin-queued.png')),full_page=True)
    print(json.dumps({'case_type':a.kind,'durably_accepted':True,'case_id':data['case_id'],'run_id':data['job_id']}),flush=True);return
   import httpx
   accepted=json.loads((D/(a.kind+'-accepted.private.json')).read_text());case=accepted['case_id'];run=accepted['job_id']
   ch=h.headers(customer,'customer');ah=h.headers(admin)
   with httpx.Client(timeout=45) as client:
    stage='saved_run';job=client.get(cfg['api']+'/v1/jobs/'+run,headers=ch);job.raise_for_status();job=job.json()
    print(json.dumps({'stage':stage}),flush=True)
    if job['status'] in {'queued','running'}:
     print(json.dumps({'terminal':False,'stage':job.get('stage'),'case_type':a.kind}));return
    report=client.get(cfg['api']+'/v1/cases/'+case+'/report',headers=ah);report.raise_for_status();report=report.json()
    write(a.kind+'-job.json',job);write(a.kind+'-report.private.json',report)
    stage='ui_saved_report';h.open_case(admin,case);admin.screenshot(path=str(D/(a.kind+'-admin-assessment.png')),full_page=True)
    if report.get('assessment_explanation',{}).get('routing',{}).get('source')=='fallback':
     expect(admin.get_by_text('No converged model decision; saved system fallback',exact=True)).to_be_visible()
    for index in range(len(files[a.kind])):
     photo=admin.locator('.review-photos > button').nth(index);photo.scroll_into_view_if_needed()
     expect(photo.locator('img')).to_be_visible(timeout=45000)
    admin.wait_for_function("[...document.querySelectorAll('.review-photos img')].every(image => image.complete && image.naturalWidth > 0)",timeout=45000)
    admin.locator('.review-photos > button').first.click()
    expect(admin.locator('.evidence-viewer img')).to_be_visible(timeout=45000)
    admin.wait_for_function("document.querySelector('.evidence-viewer img')?.naturalWidth > 0",timeout=45000)
    admin.locator('.evidence-viewer').screenshot(path=str(D/(a.kind+'-original-evidence.png')));admin.keyboard.press('Escape')
    admin.screenshot(path=str(D/(a.kind+'-admin-assessment.png')),full_page=True)
    admin.set_viewport_size({'width':390,'height':844});admin.screenshot(path=str(D/(a.kind+'-admin-mobile.png')),full_page=True)
    mobile=admin.evaluate('({viewport:innerWidth,content:document.documentElement.scrollWidth})');assert mobile['content']<=mobile['viewport']+2
    admin.set_viewport_size({'width':1365,'height':900})
    if report.get('assessment_presentation',{}).get('complete') is False:expect(admin.get_by_text('Assessment incomplete',exact=False).first).to_be_visible()
    before=json.loads((ROOT/'outputs/pilot_validation/live_calls.json').read_text())['attempts']
    stage='pdf_preview';admin.get_by_role('button',name='Preview report',exact=True).click()
    expect(admin.get_by_role('dialog',name='PDF report preview')).to_be_visible(timeout=45000)
    admin.wait_for_timeout(5000);admin.screenshot(path=str(D/(a.kind+'-browser-pdf-preview.png')),full_page=True)
    admin.get_by_role('dialog',name='PDF report preview').screenshot(path=str(D/(a.kind+'-pdf-dialog.png')))
    admin.get_by_role('button',name='Close preview',exact=True).click()
    stage='pdf_download'
    with admin.expect_download(timeout=45000) as download:admin.get_by_role('button',name='Download PDF',exact=True).click()
    download.value.save_as(D/(a.kind+'-live.pdf'))
    versions=client.get(cfg['api']+'/v1/cases/'+case+'/reports',headers=ah);versions.raise_for_status();versions=versions.json()['reports']
    # Read the exact artifact selected by the UI, not a newly computed analysis.
    raw=versions[0];snapshot=raw['snapshot_id'];url=cfg['api']+f'/v1/cases/{case}/reports/{snapshot}/pdf'
    preview=client.get(url,headers=ah);downloaded=client.get(url+'?download=true',headers=ah)
    assert preview.content==downloaded.content==(D/(a.kind+'-live.pdf')).read_bytes()
    print(json.dumps({'stage':'saved_pdf_bytes_equal'}),flush=True)
    assert json.loads((ROOT/'outputs/pilot_validation/live_calls.json').read_text())['attempts']==before
    if a.phase=='pdf':
     previous_path=D/(a.kind+'-verification.json');previous=json.loads(previous_path.read_text())
     old_url=cfg['api']+f'/v1/cases/{case}/reports/'+previous['pdf_snapshot']+'/pdf'
     old_pdf=client.get(old_url,headers=ah);old_pdf.raise_for_status()
     assert hashlib.sha256(old_pdf.content).hexdigest()==previous['pdf_sha256']
     assert report['admin_action']['action']=='request_more_evidence'
     if not (D/(a.kind+'-v8-verification.json')).exists():shutil.copyfile(previous_path,D/(a.kind+'-v8-verification.json'))
     shutil.copyfile(D/(a.kind+'-live.pdf'),D/(a.kind+'-reviewed.pdf'))
     previous.update(pdf_snapshot=snapshot,reviewed_pdf_snapshot=snapshot,pdf_sha256=hashlib.sha256(preview.content).hexdigest(),
         renderer_version=raw['renderer_version'],assessment=report['assessment_presentation'],previous_pdf_version_preserved=True)
     write(previous_path.name,previous);print(json.dumps({'final_pdf':a.kind,'snapshot':snapshot,'renderer':raw['renderer_version'],'previous_bytes_preserved':True,'generation_requests':0}),flush=True);return
    stage='authorization';assert client.get(url,headers=ch).status_code in {401,403}
    outsider=cfg.get('outsider')
    if not outsider:
     import secrets
     outsider={'name':'Fictional access verifier','email':'panel-outsider-20261022@example.test','password':secrets.token_urlsafe(24)}
     registered=client.post(cfg['api']+'/v1/customer/auth/register',json=outsider);registered.raise_for_status();cfg['outsider']=outsider;cfgpath.write_text(json.dumps(cfg,indent=2),encoding='utf8')
    login=client.post(cfg['api']+'/v1/customer/auth/login',json={'email':outsider['email'],'password':outsider['password']});login.raise_for_status()
    other={'Authorization':'Bearer '+login.json()['token']}
    assert client.get(cfg['api']+'/v1/customer/cases/'+case,headers=other).status_code in {403,404}
    assert client.get(url,headers=other).status_code in {401,403,404}
    assert len(report.get('evidence_ids',[]))==len(files[a.kind])
    for image in report.get('evidence_ids',[]):
     assert client.get(cfg['api']+'/v1/images/'+image,headers=other).status_code in {401,403,404}
     assert client.get(cfg['api']+'/v1/customer/images/'+image,headers=other).status_code in {403,404}
     assert client.get(cfg['api']+'/v1/customer/images/'+image,headers=ch).status_code==200
    stage='reviewer_action'
    action_path=D/(a.kind+'-review-action.json');recorded=report.get('admin_action') or {}
    if recorded:
     assert recorded.get('action')=='request_more_evidence' and recorded.get('admin_id')==cfg['reviewer']['email']
     write(action_path.name,recorded)
    if not action_path.exists():
     admin.locator('select[name=action]').select_option(label='Request More Evidence')
     admin.locator('textarea[name=reason]').fill('Fictional panel review: the archived licensed photographs establish neither a current insured loss nor verified vehicle identity. Required evidence remains incomplete. No accuracy or entitlement is established.')
     admin.locator('textarea[name=publicNarrative]').fill('Fictional panel review: please provide current readable registration, '+('diagnostic evidence of the reported interior concern.' if a.kind=='claims' else 'a powered readable odometer display.'))
     admin.locator('textarea[name=requestedArtifacts]').fill('Current sharp mounted registration photograph\n'+('Diagnostic evidence of the reported interior concern' if a.kind=='claims' else 'Powered dashboard photograph showing readable ODO/mileage and units'))
     with admin.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/action'),timeout=45000) as action:admin.get_by_role('button',name='Request more evidence',exact=True).click()
     assert action.value.status==200
     write(action_path.name,action.value.json())
    admin.screenshot(path=str(D/(a.kind+'-reviewer-action.png')),full_page=True)
    customer.bring_to_front();customer.goto(cfg['ui']+'/dashboard?case='+case,wait_until='domcontentloaded')
    expect(customer.get_by_text('Fictional panel review:',exact=False).first).to_be_visible(timeout=45000)
    customer.screenshot(path=str(D/(a.kind+'-customer-outcome.png')),full_page=True)
    stage='reviewed_report';h.open_case(admin,case)
    with admin.expect_download(timeout=45000) as reviewed_download:admin.get_by_role('button',name='Download PDF',exact=True).click()
    reviewed_download.value.save_as(D/(a.kind+'-reviewed.pdf'))
    reviewed=client.get(cfg['api']+'/v1/cases/'+case+'/reports',headers=ah).json()['reports'][0]
    reviewed_url=cfg['api']+f'/v1/cases/{case}/reports/'+reviewed['snapshot_id']+'/pdf'
    assert client.get(reviewed_url,headers=ah).content==(D/(a.kind+'-reviewed.pdf')).read_bytes()
    assert client.get(url,headers=ah).content==preview.content
    assert json.loads((ROOT/'outputs/pilot_validation/live_calls.json').read_text())['attempts']==before
    stage='session_independence'
    sessions=json.loads((D/'sessions-verification.json').read_text())
    assert sessions['customer_logout_keeps_admin'] and sessions['admin_logout_keeps_customer'] and sessions['same_context']
    result=dict(case_type=a.kind,case_id=case,run_id=run,execution=job['status'],assessment=report.get('assessment_presentation'),
      pdf_snapshot=snapshot,pdf_sha256=hashlib.sha256(preview.content).hexdigest(),pdf_preview_download_bytes_equal=True,
      headed_chrome_preview_screenshot=True,reviewer_action='request_more_evidence',customer_update_verified=True,
      reviewed_pdf_snapshot=reviewed['snapshot_id'],earlier_pdf_preserved=True,
      mobile_no_horizontal_overflow=True,
      cross_customer_case_evidence_report_blocked=True,sessions_independent_after_logout=True,provider_calls_during_pdf=0)
    write(a.kind+'-verification.json',result);print(json.dumps(result),flush=True)
  except Exception as exc:
   print(json.dumps({'failed_stage':stage,'error_type':type(exc).__name__,'lines':[f.lineno for f in traceback.extract_tb(exc.__traceback__) if Path(f.filename).name==Path(__file__).name]}),flush=True)
   try:customer.screenshot(path=str(D/(a.kind+'-'+a.phase+'-failure.png')),full_page=False,timeout=5000)
   except Exception:pass
   raise SystemExit(1)
  finally:browser.close()


if __name__=='__main__':main()
