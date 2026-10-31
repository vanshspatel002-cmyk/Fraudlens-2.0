"""Read-only local UI regression with injected network failures and real recovery.

Creates and revokes its own reviewer session. Does not submit cases, change
decisions, or call a model. Credentials and tokens are never printed.
"""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright, expect


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui', default='http://127.0.0.1:5173')
    parser.add_argument('--credentials', type=Path, default=root / 'outputs/pilot_validation/demo_credentials.json')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    observations = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page_errors = []
        page.on('pageerror', lambda error: page_errors.append(str(error)))
        attempts = 0
        successful_reads = 0

        def intermittent_queue(route):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                route.abort('connectionfailed')
            else:
                route.continue_()

        def response_seen(response):
            nonlocal successful_reads
            if '/v1/cases?' in response.url and response.status == 200:
                successful_reads += 1

        page.on('response', response_seen)
        page.route('**/v1/cases?*', intermittent_queue)
        # Unavailable photographs must not block readable queue data.
        page.route('**/v1/images/**', lambda route: route.abort('connectionfailed'))
        page.goto(args.ui.rstrip('/') + '/admin', wait_until='domcontentloaded', timeout=60000)
        page.locator('input[name=email]').fill(credentials['email'])
        page.locator('input[name=password]').fill(credentials['password'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        try:
            expect(page.get_by_role('alert')).to_contain_text('could not be reached', timeout=30000)
            started = time.monotonic()
            # Let the existing polling recover, without a reload or another login.
            expect(page.get_by_role('alert')).to_have_count(0, timeout=90000)
            expect(page.get_by_role('button', name='Open case queue', exact=False)).to_be_visible()
            assert successful_reads > 0 and attempts >= 2
            observations.append({'check': 'automatic recovery clears the connection error',
                                 'seconds': round(time.monotonic() - started, 2)})
            observations.append({'check': 'case queue remains available with failed thumbnails'})

            page.get_by_role('button', name='Case queue', exact=True).click()
            expect(page.locator('tbody tr').first).to_be_visible(timeout=60000)
            expect(page.get_by_role('alert')).to_have_count(0)
            with page.expect_response(lambda response: response.url.endswith('/reports'), timeout=90000) as reports:
                page.locator('button.case-open').first.click()
            assert reports.value.status == 200
            expect(page.get_by_role('heading', name='Desk Review', exact=True)).to_be_visible(timeout=90000)
            expect(page.get_by_role('alert')).to_have_count(0)
            assert not page_errors, page_errors
            observations.append({'check': 'real authenticated case queue loaded', 'javascript_errors': len(page_errors)})
            observations.append({'check': 'submitted case and saved report details loaded'})
            print(json.dumps(observations, indent=2), flush=True)
        finally:
            page.get_by_role('button', name='Sign out', exact=True).click()
            expect(page.locator('input[name=email]')).to_be_visible(timeout=30000)
            browser.close()


if __name__ == '__main__':
    main()
