"""Render the actual risk component using controlled saved-policy scenarios."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,expect
from src.risk_presentation import assessment_presentation
from test_partial_risk_policy import saved,partial,finding


def main():
    output=ROOT/'outputs/workflow_repair';fixtures=[assessment_presentation(saved(band=band)) for band in ['clear','desk_review','escalate_siu']]
    fixtures += [assessment_presentation(partial([finding('internal_duplicate')])),assessment_presentation(partial([]))]
    html='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{margin:0;font:14px Arial}h1{font-size:18px}</style>
<script type="module">import RefreshRuntime from '/@react-refresh';RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>type=>type;window.__vite_plugin_react_preamble_installed__=true;</script></head>
<body><div id="root"></div><script>window.riskFixtures=FIXTURES</script><script type="module" src="/scripts/risk-summary-harness.tsx"></script></body></html>'''.replace('FIXTURES',json.dumps(fixtures))
    results=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        for width in [1365,390]:
            context=browser.new_context(viewport={'width':width,'height':900});page=context.new_page();errors=[]
            page.on('pageerror',lambda exc:errors.append(type(exc).__name__))
            def route_request(route):
                if '/__risk_summary' in route.request.url:route.fulfill(content_type='text/html',body=html)
                elif route.request.url.startswith('http://127.0.0.1:5174/'):route.continue_()
                else:errors.append('Unexpected external request');route.abort()
            page.route('**/*',route_request);page.goto('http://127.0.0.1:5174/__risk_summary',wait_until='domcontentloaded',timeout=120000)
            cards=page.locator('.risk-indicator');expect(cards).to_have_count(5,timeout=60000)
            colors=[]
            for i,contract in enumerate(fixtures):
                card=cards.nth(i);expect(card).to_contain_text(contract['label']);expect(card.locator('.risk-explanation')).to_contain_text(contract['explanation'])
                expect(card.locator('.risk-marker')).to_have_count(0 if i==4 else 1)
                if i<3:colors.append(card.locator('.is-selected').evaluate('e=>getComputedStyle(e).backgroundColor'))
                if i>=3:expect(card.locator('.risk-indicator-heading')).not_to_contain_text('Score')
            assert colors==['rgb(215, 234, 219)','rgb(248, 229, 165)','rgb(241, 204, 204)']
            assert cards.last.locator('.risk-segment').first.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(237, 240, 242)'
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            assert not errors,errors
            for index in range(5):
                cards.nth(index).screenshot(path=str(output/f'risk-fixture-{index}-{width}.png'))
            results.append({'width':width,'LOW_MEDIUM_HIGH_colors_and_labels':True,'provisional_coverage_explanation':True,'UNASSESSED_neutral':True,'numeric_gauge':False,'source':'controlled policy contracts / actual React component'})
            context.close()
        browser.close()
    (output/'risk-browser.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))


if __name__=='__main__':main()
