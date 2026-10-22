"""Offline browser verification: every API request is fulfilled from fixtures.

Only the local frontend's static/SSR pages are read. No request can reach the
application API, a database, or a model. Fixture tokens have no real authority.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.risk_presentation import assessment_presentation


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['before','after'],required=True)
    parser.add_argument('--ui',default='http://127.0.0.1:5173');parser.add_argument('--output',type=Path,default=ROOT.parent/'docs/visual_review')
    args=parser.parse_args();reports=json.loads((args.output/'fixtures.json').read_text())
    variants=['claims-high','underwriting-medium'] if args.phase=='before' else list(reports)
    if args.phase=='after':
        stale=deepcopy(reports['claims-high']);stale['run_id']='later-evidence-run';stale['processing']['job_id']='later-evidence-run'
        stale['assessment_presentation']=assessment_presentation(stale);reports['stale-after-evidence']=stale
        historical=deepcopy(reports['underwriting-medium']);historical['assessment_context']='historical';historical['assessment_presentation']=assessment_presentation(historical)
        reports['historical-completed']=historical
        unknown=deepcopy(reports['claims-high']);unknown['assessment_explanation']['routing']['recorded_band']='unsupported'
        unknown['assessment_presentation']=assessment_presentation(unknown);reports['unknown-category']=unknown
        variants+=['stale-after-evidence','historical-completed','unknown-category']
    screenshot_dir=args.output/'screenshots';screenshot_dir.mkdir(exist_ok=True)
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        for name in variants:
            report=reports[name];case_id=report['case_id'];errors=[]
            for viewport in ([{'width':1440,'height':1000},{'width':390,'height':844}] if name in {'claims-high','underwriting-medium'} else [{'width':1440,'height':1000}]):
                context=browser.new_context(viewport=viewport,accept_downloads=True)
                context.add_init_script("sessionStorage.setItem('fraudlens_admin_token','controlled-no-authority');sessionStorage.setItem('fraudlens_admin_email','reviewer@example.test');")
                requests=[];pdf_deliveries=[]
                snapshot='controlled-'+name
                pdf_name=name if (args.output/(name+'.pdf')).exists() else 'claims-high'
                pdf=(args.output/(pdf_name+'.pdf')).read_bytes()
                version={'snapshot_id':snapshot,'run_id':report.get('run_id'),'snapshot_created_at':1792569600,'generated_at':1792569600,'pdf_status':'ready','renderer_version':report['report_template_version']}
                detail={**report['declaration'],'case_id':case_id,'created_at':'2026-10-20T08:00:00Z','status':'open','agent_type':report['declaration']['agent_type'],
                    'review_revision':0,'risk_band':report['agent_recommendation']['risk_band'],'decision':report['agent_recommendation'],'processing':report['processing'],
                    'images':[{'image_id':item['image_id'],'damage_description':item['label']} for item in report['evidence_inventory']],
                    'findings_by_category':report['findings_by_category'],'report_history':[],'audit':[]}
                def route_request(route):
                    request=route.request;url=urlparse(request.url);path=url.path
                    if request.url.startswith(args.ui.rstrip('/')+'/'):
                        route.continue_();return
                    if url.scheme=='blob':route.continue_();return
                    if url.hostname not in {'127.0.0.1','localhost'} or url.port!=8001:
                        route.abort();return
                    requests.append((request.method,path))
                    headers={'Access-Control-Allow-Origin':args.ui,'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Applicant-Token, Idempotency-Key','Access-Control-Allow-Methods':'GET,POST,OPTIONS'}
                    if request.method=='OPTIONS':route.fulfill(status=204,headers=headers);return
                    if path=='/v1/auth/session':data={'user':'reviewer@example.test','role':'admin'}
                    elif path=='/v1/cases':data={'items':[detail],'total':1,'has_more':False,'page':1,'page_size':10}
                    elif path.endswith('/trace'):data={'steps':[]}
                    elif path.endswith('/report'):data=report
                    elif path.endswith('/reports'):data={'reports':[version]}
                    elif path.endswith('/reports/prepare'):data=version
                    elif path.endswith('/pdf'):
                        pdf_deliveries.append(hashlib.sha256(pdf).hexdigest())
                        route.fulfill(status=200,body=pdf,headers={**headers,'Content-Type':'application/pdf','Content-Disposition':'inline; filename="controlled-report.pdf"'});return
                    elif path.startswith('/v1/images/'):
                        route.fulfill(status=200,body=base64.b64decode(report['evidence_inventory'][0]['thumbnail_base64']),headers={**headers,'Content-Type':'image/jpeg'});return
                    elif path=='/v1/finding-counts':data={'counts':[]}
                    elif path=='/v1/cases/'+case_id:data=detail
                    else:
                        route.fulfill(status=501,json={'message':'Unknown fixture route; no live fallback is permitted.'},headers=headers);errors.append('Unknown mocked route '+path);return
                    route.fulfill(status=200,json=data,headers=headers)
                context.route('**/*',route_request)
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(args.ui+'/admin',wait_until='domcontentloaded')
                expect(page.get_by_role('button',name='Sign out',exact=True)).to_be_visible(timeout=30000)
                page.get_by_role('button',name='Claims' if report['declaration']['agent_type']=='claims' else 'Underwriting',exact=True).click()
                page.get_by_role('button',name=case_id,exact=True).click()
                expect(page.get_by_role('heading',name='MH12EX1203',exact=True)).to_be_visible(timeout=30000)
                if args.phase=='after':
                    expected=report['assessment_presentation']['label']
                    expect(page.locator('.risk-indicator')).to_contain_text(expected)
                    shadow=(report.get('assessment_explanation') or {}).get('shadow_assessment')
                    if shadow:
                        panel=page.get_by_role('complementary',name='Shadow candidate assessment')
                        expect(panel).to_contain_text(str(shadow['concern_index']).removesuffix('.0'))
                        expect(panel).to_contain_text(str(shadow['coverage']).removesuffix('.0'))
                        expect(panel).to_contain_text('shadow only')
                    if not report['assessment_presentation']['complete']:
                        expect(page.locator('.risk-marker')).to_have_count(0)
                        expect(page.locator('.risk-indicator-heading')).not_to_contain_text('Score')
                    else:
                        expect(page.locator('.risk-marker')).to_have_count(1)
                        if report['assessment_presentation']['score'] is None:expect(page.locator('.risk-indicator-heading')).not_to_contain_text('Score')
                    overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth+1')
                    assert not overflow,(name,viewport)
                if name in {'claims-high','underwriting-medium'}:
                    page.locator('.admin-title').screenshot(path=str(screenshot_dir/f'{args.phase}-{name}-{viewport["width"]}.png'))
                if args.phase=='after' and viewport['width']==1440 and name in {'claims-high','underwriting-medium'}:
                    page.get_by_role('button',name='Preview report',exact=True).click()
                    expect(page.get_by_role('dialog',name='PDF report preview')).to_be_visible()
                    page.get_by_role('button',name='Close preview',exact=True).click()
                    with page.expect_download() as download:
                        page.get_by_role('button',name='Download PDF',exact=True).click()
                    actual=Path(download.value.path()).read_bytes()
                    assert hashlib.sha256(actual).hexdigest()==hashlib.sha256(pdf).hexdigest()
                    assert len(pdf_deliveries)==2 and len(set(pdf_deliveries))==1
                    assert not any('reprocess' in path or path.endswith('/action') for _,path in requests)
                    results.append({'case':name,'check':'preview/download use identical saved bytes; no analysis/decision request'})
                assert not errors,errors
                results.append({'case':name,'width':viewport['width'],'phase':args.phase,'javascript_errors':0})
                context.close()
        browser.close()
    (args.output/f'browser-{args.phase}.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
