"""Read-only Claims navigation regression against the running frontend/API.

Uses its own reviewer session and existing cases. Holds photo/detail responses
to verify that navigation remains usable; never creates cases or calls models.
"""
import json
from pathlib import Path
import re
import time

from playwright.sync_api import sync_playwright, expect, Error


def main():
    root = Path(__file__).resolve().parents[1]
    credentials = json.loads((root / 'outputs/pilot_validation/demo_credentials.json').read_text())
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        errors = []
        held_images = []
        hold_images = True
        def image_route(route):
            if hold_images:
                held_images.append(route)
            else:
                route.continue_()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/v1/images/**', image_route)
        page.goto('http://127.0.0.1:5173/admin', wait_until='domcontentloaded')
        page.locator('input[name=email]').fill(credentials['email'])
        page.locator('input[name=password]').fill(credentials['password'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('button', name='Sign out', exact=True)).to_be_visible(timeout=30000)
        try:
            started = time.monotonic()
            with page.expect_response(lambda r: '/v1/cases?' in r.url and 'agent_type=claims' in r.url, timeout=60000) as response:
                page.get_by_role('button', name='Claims', exact=True).click()
            assert response.value.status == 200
            expect(page.locator('tbody tr').first).to_be_visible(timeout=2000)
            assert set(page.locator('tbody .agent-tag').all_text_contents()) == {'Recon'}
            assert held_images, 'Photos should still be pending when rows become usable'
            checks.append({'check': 'Claims rows are usable while photos are pending',
                           'seconds': round(time.monotonic() - started, 2)})
            hold_images = False
            for route in held_images:
                try:
                    route.continue_()
                except Error:
                    pass
            page.unroute_all(behavior='wait')
            expect(page.locator('tbody .evidence-image img').first).to_be_visible(timeout=45000)
            checks.append({'check': 'authenticated photographs load independently'})

            events = []
            page.on('request', lambda request: events.append(('request', request.url, time.monotonic())))
            page.on('response', lambda response: events.append(('response', response.url, time.monotonic())))
            started = time.monotonic()
            case_id = page.locator('button.case-open').first.get_attribute('aria-label')
            case_url = 'http://127.0.0.1:8001/v1/cases/' + case_id
            page.locator('button.case-open').first.click()
            expect(page.get_by_role('status').filter(has_text='Opening claim or application')).to_be_visible(timeout=2000)
            expect(page.get_by_role('heading', name='Desk Review', exact=True)).to_be_visible(timeout=90000)
            report_start = next(t for kind, url, t in events if kind == 'request' and url == case_url + '/report')
            detail_end = next(t for kind, url, t in events if kind == 'response' and url == case_url)
            assert report_start < detail_end, 'Case/report requests must overlap'
            assert not any('/trace' in url for _, url, _ in events)
            checks.append({'check': 'Claims opens with visible progress and concurrent reads',
                           'seconds': round(time.monotonic() - started, 2)})

            page.get_by_role('button', name='Claims', exact=True).click()
            expect(page.locator('button.case-open').first).to_be_visible(timeout=60000)
            held_details = []
            hold_details = True
            def detail_route(route):
                if hold_details:
                    held_details.append(route)
                else:
                    route.abort()
            detail_pattern = re.compile(r'/v1/cases/[^/?]+$')
            page.route(detail_pattern, detail_route)
            page.locator('button.case-open').first.click()
            expect(page.get_by_role('status').filter(has_text='Opening claim or application')).to_be_visible(timeout=2000)
            page.get_by_role('button', name='Underwriting', exact=True).click()
            expect(page.get_by_role('heading', name='Underwriting', exact=True)).to_be_visible(timeout=2000)
            expect(page.locator('tbody tr').first).to_be_visible(timeout=60000)
            assert set(page.locator('tbody .agent-tag').all_text_contents()) == {'Sentinel'}
            hold_details = False
            for route in held_details:
                try:
                    route.abort()
                except Error:
                    pass
            page.unroute_all(behavior='wait')
            expect(page.get_by_role('heading', name='Desk Review', exact=True)).to_have_count(0)
            expect(page.get_by_role('alert')).to_have_count(0)
            checks.append({'check': 'switching tabs cancels an unfinished claim and keeps the selected tab'})

            page.get_by_role('button', name='Claims', exact=True).click()
            expect(page.locator('tbody tr').first).to_be_visible(timeout=60000)
            page.get_by_role('button', name='Refresh', exact=True).click(click_count=3, delay=100)
            expect(page.get_by_role('status').filter(has_text='Loading cases')).to_have_count(0, timeout=60000)
            expect(page.locator('tbody tr').first).to_be_visible()
            expect(page.get_by_role('alert')).to_have_count(0)
            assert not errors, errors
            checks.append({'check': 'repeated refresh settles without stale loading or JavaScript errors'})
            print(json.dumps(checks, indent=2), flush=True)
        finally:
            page.get_by_role('button', name='Sign out', exact=True).click()
            expect(page.locator('input[name=email]')).to_be_visible(timeout=30000)
            browser.close()


if __name__ == '__main__':
    main()
