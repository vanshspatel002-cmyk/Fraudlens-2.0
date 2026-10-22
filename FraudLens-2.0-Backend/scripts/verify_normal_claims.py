"""One fictional ordinary-UI claim; no provider probes or historical workload.

Run submit once, then inspect after starting the normal durable worker. Private
credentials/tokens are kept only under ignored outputs. Errors print class names,
never Playwright logs that can echo password input values.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.diagnose_gemini import process_environment
from src.pilot_config import load_pilot_environment,apply_pilot_environment
ROOT=Path(__file__).resolve().parents[1]


def write(path,value):path.write_text(json.dumps(value,indent=2),encoding='utf8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['submit','retry-transient','inspect'])
    p.add_argument('--process-id',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();env=load_pilot_environment(process_environment(a.process_id));apply_pilot_environment(env)
    if env['FRAUDLENS_PG_SCHEMA']!='fraudlens_pilot':raise ValueError('Actual pilot schema required.')
    from src import session_budget
    state=session_budget._change(lambda s:s)
    if not state.get('operation') or state['operation']['task']['status']!='active':raise ValueError('Active bounded task required.')
    directory=a.output.resolve();directory.mkdir(parents=True,exist_ok=True);config_path=directory/'private-browser.json'
    if not config_path.exists():
        if a.phase!='submit':raise ValueError('No accepted presentation case.')
        config=dict(api='http://127.0.0.1:8001',ui='http://127.0.0.1:5173',
            customer=dict(name='Fictional Normal Operation',email='normal-claims-20261022@example.test',password=secrets.token_urlsafe(22)),
            reviewer=dict(email='normal-reviewer-20261022@example.test',password=secrets.token_urlsafe(22)),
            photos={'claims':[str(ROOT/'data/curated/damaged/damaged_0002.jpg')]})
        write(config_path,config)
        # Actual management implementation, secret via getpass callback only.
        from scripts import manage_reviewer
        manage_reviewer.getpass=lambda _:config['reviewer']['password']
        saved=sys.argv
        try:
            sys.argv=['manage_reviewer','--db','postgresql','--email',config['reviewer']['email'],'--role','reviewer']
            with contextlib.redirect_stdout(io.StringIO()):manage_reviewer.main()
        finally:sys.argv=saved
    config=json.loads(config_path.read_text())
    os.environ.update(PRESENTATION_UI=config['ui'],PRESENTATION_API=config['api'],PRESENTATION_OUTPUT_DIR=str(directory),PRESENTATION_DB=str(directory/'unused.db'))
    from scripts import verify_presentation_browser as h
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport={'width':1365,'height':900},accept_downloads=True)
        customer=context.new_page();admin=context.new_page()
        if a.phase=='retry-transient':
            accepted=json.loads((directory/'claims-accepted.json').read_text())
            new=state['events'][state['operation']['task']['base_attempts']:]
            if (accepted.get('previous_run_id') or len(new)!=1 or new[0]['outcome']!='failure:503'
                    or new[0].get('operation_case')!=accepted['case_id'] or state['operation'].get('circuit')):
                raise ValueError('Only one bounded retry of this first transient failure is permitted.')
            h.admin_signin(admin,config['reviewer']);h.open_case(admin,accepted['case_id'])
            admin.get_by_text('Technical diagnostics',exact=True).click()
            with admin.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/reprocess'),timeout=60000) as captured:
                admin.get_by_role('button',name='Retry analysis',exact=True).click()
            if captured.value.status not in {200,201,202}:raise ValueError('Retry was not durably accepted.')
            reply=captured.value.json()
            write(directory/'claims-first-accepted.json',accepted)
            accepted.update(previous_run_id=accepted['job_id'],job_id=reply['job_id'])
            write(directory/'claims-accepted.json',accepted)
            print(json.dumps({'retry_accepted_via_admin_ui':True,'case_id':accepted['case_id'],'new_run_id':accepted['job_id']}))
            browser.close();return
        if a.phase=='submit':
            if (directory/'claims-accepted.json').exists():raise ValueError('Presentation case already accepted; inspect it instead.')
            h.customer_signin(customer,config['customer'],register=not config.get('registered'))
            config['registered']=True;write(config_path,config)
            customer.goto(config['ui']+'/apply/claims',wait_until='domcontentloaded')
            fields=['name','email','phone','license','address','make','model','variant','year','registration','engine','chassis','idv','policy','ncb','incidentDate','incidentTime','location','amount','garage','description']
            for name in fields:h.sample(customer,name)
            values=dict(name='Fictional Normal Claims Presentation',email=config['customer']['email'],phone='9000000041',
                registration='MH12EX9241',make='Fictional sample vehicle',model='Unverified model',
                amount='20000',garage='UNASSIGNED',policy='FICTIONAL-NORMAL-2026',
                description='FICTIONAL PRESENTATION CASE. Authorized existing sample photograph shows rear body-panel scuffs and a dent. Applicant identity, vehicle identity, policy, incident date, place and INR 20000 amount are fictional software test declarations. The image does not authenticate them. Request missing evidence where needed; do not infer verified repair costs.')
            for name,value in values.items():customer.locator('form [name="'+name+'"]').fill(value)
            customer.keyboard.press('Escape');customer.locator('select[name="policyType"]').select_option(label='Comprehensive')
            customer.locator('select[name="settlement"]').select_option(label='Reimbursement')
            customer.get_by_label('Upload Damage overview',exact=True).set_input_files(config['photos']['claims'][0])
            customer.locator('input[name="consent"]').check()
            started=time.monotonic()
            with customer.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v1/cases'),timeout=180000) as captured:
                customer.get_by_role('button',name='Submit claim',exact=True).click()
            response=captured.value
            if response.status!=201:raise ValueError('Ordinary UI submission rejected with HTTP '+str(response.status))
            accepted={k:response.json()[k] for k in ['case_id','job_id','status','images_received']}
            accepted['ui_acceptance_seconds']=round(time.monotonic()-started,3)
            write(directory/'claims-accepted.json',accepted)
            customer.screenshot(path=str(directory/'customer-accepted.png'),full_page=True)
            print(json.dumps(accepted));browser.close();return
        # Reuse last task's browser/download/ownership verification against this
        # actual normal case. This path contains no submission or model call.
        browser.close()
    from scripts.verify_scoped_case import browser as verify_browser
    import httpx
    accepted=json.loads((directory/'claims-accepted.json').read_text());case=accepted['case_id'];run=accepted['job_id']
    with httpx.Client(timeout=60) as client:
        def login(path,account):
            r=client.post(config['api']+path,json={k:account[k] for k in ['email','password']});r.raise_for_status();return {'Authorization':'Bearer '+r.json()['token']}
        admin_headers=login('/v1/auth/login',config['reviewer']);customer_headers=login('/v1/customer/auth/login',config['customer'])
        job=client.get(config['api']+'/v1/jobs/'+run,headers=admin_headers);job.raise_for_status()
        if job.json()['status'] in {'queued','running'}:print(json.dumps({'terminal':False,'stage':job.json()['stage']}));return
        report=client.get(config['api']+f'/v1/cases/{case}/report',headers=admin_headers);report.raise_for_status()
        own=client.get(config['api']+'/v1/customer/cases/'+case,headers=customer_headers);own.raise_for_status()
        assert own.json()['id']==case and own.json()['processingStatus']==job.json()['status']
        assert client.get(config['api']+f'/v1/cases/{case}/reports',headers=customer_headers).status_code in {401,403}
        assert client.get(config['api']+f'/v1/cases/{case}/report').status_code==401
        outsider=config.get('outsider') or dict(name='Fictional ownership check',email='normal-outsider-20261022@example.test',password=secrets.token_urlsafe(22))
        if not config.get('outsider'):
            registered=client.post(config['api']+'/v1/customer/auth/register',json=outsider)
            registered.raise_for_status();config['outsider']=outsider;write(config_path,config)
        other=login('/v1/customer/auth/login',outsider)
        assert client.get(config['api']+'/v1/customer/cases/'+case,headers=other).status_code in {403,404}
        for image in own.json().get('images') or []:
            assert client.get(config['api']+image['url'],headers=customer_headers).status_code==200
            assert client.get(config['api']+image['url'],headers=other).status_code in {403,404}
        version=client.post(config['api']+f'/v1/cases/{case}/reports/prepare',headers=admin_headers);version.raise_for_status();snapshot=version.json()['snapshot_id']
        path=config['api']+f'/v1/cases/{case}/reports/{snapshot}/pdf'
        pdf=client.get(path,headers=admin_headers);pdf.raise_for_status()
        assert pdf.content==client.get(path+'?download=true',headers=admin_headers).content
        pdf_path=directory/'claims-live.pdf';pdf_path.write_bytes(pdf.content)
        write(directory/'claims-job.json',job.json());write(directory/'claims-report.json',report.json())
        result=verify_browser(config,accepted,directory,report.json(),snapshot,pdf_path,'claims')
        # Explicit fictional reviewer action only on this newly created case.
        with sync_playwright() as pw:
            b=pw.chromium.launch(channel='chrome',headless=True);ctx=b.new_context(viewport={'width':1365,'height':900})
            adm=ctx.new_page();cust=ctx.new_page();h.admin_signin(adm,config['reviewer']);h.customer_signin(cust,config['customer'])
            h.open_case(adm,case)
            if own.json()['status']!='awaiting_evidence':
                h.decision(adm,'Request More Evidence','Fictional presentation review: please provide an original registration view and incident context. This request demonstrates the workflow only.')
            adm.screenshot(path=str(directory/'admin-human-review.png'),full_page=True)
            cust.goto(config['ui']+'/dashboard?case='+case,wait_until='domcontentloaded')
            expect(cust.get_by_text('Fictional presentation review:',exact=False).first).to_be_visible(timeout=45000)
            cust.screenshot(path=str(directory/'customer-outcome.png'),full_page=True);b.close()
        after=client.get(config['api']+'/v1/customer/cases/'+case,headers=customer_headers);after.raise_for_status();write(directory/'claims-customer-after.json',after.json())
        assert after.json()['status']=='awaiting_evidence'
        result.update(case_id=case,run_id=run,snapshot_id=snapshot,human_action='request_more_evidence',
                      customer_outcome_verified=True,ownership_verified=True,pdf_sha256=hashlib.sha256(pdf.content).hexdigest())
        write(directory/'verification.json',result);print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Never emit Playwright's input-value or raw SDK/DB exception logs.
        import traceback
        print(json.dumps({'verification_failed':type(exc).__name__,
            'frames':[dict(file=Path(frame.filename).name,line=frame.lineno,function=frame.name)
                      for frame in traceback.extract_tb(exc.__traceback__) if 'playwright' not in frame.filename][-6:]}),flush=True)
        raise SystemExit(1)
