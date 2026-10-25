"""Actual React form, controlled API fixtures only; never qualifies recognition."""
import argparse, io, json, re
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--ui', default='http://127.0.0.1:5173')
    args = parser.parse_args()
    output = ROOT / 'outputs/workflow_repair'
    output.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (128, 128), 'blue')
    ImageDraw.Draw(image).rectangle((8, 8, 60, 60), fill='white')
    stream = io.BytesIO(); image.save(stream, format='PNG')
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        for kind, width in [('claims', 1365), ('underwriting', 390)]:
            context = browser.new_context(viewport={'width': width, 'height': 900})
            context.add_init_script("sessionStorage.setItem('fraudlens_customer_token','controlled-no-authority')")
            pending = []; submissions = []; errors = []
            headers = {'Access-Control-Allow-Origin': args.ui, 'Access-Control-Allow-Headers': 'Authorization, Content-Type, Idempotency-Key', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'}
            def route_request(route):
                req = route.request; url = urlparse(req.url)
                if url.port == urlparse(args.ui).port: route.continue_(); return
                if url.port != 8001: route.abort(); return
                if req.method == 'OPTIONS': route.fulfill(status=204, headers=headers); return
                if url.path.endswith('/customer/auth/session'): route.fulfill(json={'user': 'fixture@example.test'}, headers=headers); return
                if url.path.endswith('/customer/auth/login'): route.fulfill(json={'user':'fixture@example.test','token':'controlled-refreshed-session'},headers=headers); return
                if url.path.endswith('/photos/validate'):
                    body = req.post_data_buffer.decode('latin1')
                    name = re.search(r'filename="([^"]+)"', body).group(1)
                    if name=='expired.png':route.fulfill(status=401,json={'message':'Controlled expired session'},headers=headers);return
                    data = {'state': 'accepted', 'reason': 'Controlled acceptance fixture', 'normalized_hash': name}
                    if name == 'slow.png': pending.append((route, data)); return
                    route.fulfill(json=data, headers=headers); return
                if url.path == '/v1/cases':
                    submissions.append(req.post_data_buffer)
                    if len(submissions) == 1: pending.append((route, None)); return
                    route.fulfill(status=201, json={'case_id': 'controlled-case'}, headers=headers); return
                if url.path.startswith('/v1/jobs/'): route.fulfill(json={'status': 'completed_partial'}, headers=headers); return
                errors.append(url.path); route.abort()
            context.route('**/*', route_request)
            page = context.new_page(); page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.goto(args.ui+'/apply/' + kind, wait_until='domcontentloaded', timeout=180000)
            count = 4 if kind == 'claims' else 6
            inputs = page.locator('.upload-slot input'); submit = page.locator('.submit-case')
            expect(inputs).to_have_count(count, timeout=60000)
            for i in range(count):
                inputs.nth(i).set_input_files({'name': f'photo-{i}.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()})
            expect(page.get_by_text(f'{count} of {count} photographs accepted.', exact=True)).to_be_visible()
            values = {'name': 'Fictional Regression', 'email': 'fixture@example.test', 'phone': '9000000041', 'registration': 'MH12AB1234', 'year': '2023', 'idv': '500000', 'amount': '2000', 'incidentDate': '2026-10-20', 'incidentTime': '12:00'}
            for field in page.locator('.intake-form [required]').all():
                name = field.get_attribute('name'); type_ = field.get_attribute('type')
                if name == 'description': continue
                if type_ == 'checkbox': field.check()
                elif field.evaluate('e=>e.tagName') == 'SELECT': field.select_option(index=1)
                else: field.fill(values.get(name, 'Fictional example'))
            description = page.locator('form [name=description]')
            description.click(); page.locator('.sample-popover [role=option]').first.click()
            assert page.locator('form.intake-form').evaluate('f=>f.checkValidity()')
            if args.baseline:
                expect(submit).to_be_disabled()
                rows.append({'kind': kind, 'accepted': count, 'native_valid': True, 'consent': True, 'last_change': 'description suggestion', 'submit_disabled': True, 'source': 'controlled API / actual component'})
                page.screenshot(path=str(output / f'baseline-{kind}.png'), full_page=True)
            else:
                expect(submit).to_be_enabled()
                checked_fields=[]
                for control in page.locator('.intake-form [required]').all():
                    name=control.get_attribute('name')
                    if name=='consent':continue
                    value=control.input_value()
                    if control.evaluate('e=>e.tagName')=='SELECT':
                        control.evaluate("e=>{e.value='';e.dispatchEvent(new Event('change',{bubbles:true}))}")
                    else:control.fill('')
                    expect(submit).to_be_disabled()
                    expect(page.locator('#submission-blockers')).to_contain_text('Enter ')
                    if control.evaluate('e=>e.tagName')=='SELECT':control.select_option(value=value)
                    else:control.fill(value)
                    expect(submit).to_be_enabled();checked_fields.append(name)
                page.locator('[name=consent]').uncheck(); expect(submit).to_be_disabled()
                expect(page.locator('#submission-blockers')).to_contain_text('Accept consent')
                page.locator('[name=consent]').check(); expect(submit).to_be_enabled()
                # Autofill input event and a script-only value restoration both resynchronise.
                page.locator('[name=email]').evaluate("e=>{e.value='invalid';e.dispatchEvent(new Event('input',{bubbles:true}))}")
                expect(submit).to_be_disabled(); expect(page.locator('#submission-blockers')).to_contain_text('Email address')
                page.locator('[name=email]').fill('fixture@example.test'); expect(submit).to_be_enabled()
                page.locator('[name=email]').fill('')
                expect(submit).to_be_disabled()
                page.locator('[name=email]').evaluate("e=>{e.value='fixture@example.test'}")
                expect(submit).to_be_enabled()
                page.wait_for_timeout(1100)
                expect(page.locator('[name=email]')).to_have_value('fixture@example.test')
                expect(submit).to_be_enabled()
                page.locator('form.intake-form').evaluate("f=>f.insertAdjacentHTML('beforeend','<div hidden><input name=inactive required></div>')")
                expect(submit).to_be_enabled()
                inputs.first.set_input_files({'name': 'slow.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()})
                expect(submit).to_be_disabled(); expect(page.locator('#submission-blockers')).to_contain_text('still being checked')
                inputs.first.set_input_files({'name': 'replacement.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()})
                pending.pop()[0].fulfill(json={'state': 'rejected', 'reason': 'Stale rejection'}, headers=headers)
                expect(submit).to_be_enabled()
                page.locator('.upload-item').first.get_by_role('button', name=re.compile('Remove')).click()
                expect(submit).to_be_disabled(); expect(page.locator('#submission-blockers')).to_contain_text('Upload')
                inputs.first.set_input_files({'name': 'final.png', 'mimeType': 'image/png', 'buffer': stream.getvalue()})
                expect(submit).to_be_enabled()
                submit.click(); expect(submit).to_be_disabled()
                page.locator('form.intake-form').evaluate("f=>{f.requestSubmit();f.requestSubmit()}")
                assert len(submissions) == 1
                pending.pop()[0].fulfill(status=503, json={'message': 'Controlled submission failure; retry preserved'}, headers=headers)
                expect(submit).to_be_enabled(); expect(page.locator('.form-error')).to_contain_text('Controlled submission failure')
                submit.click(); expect(page.get_by_text('Your case has been received.', exact=True)).to_be_visible()
                assert len(submissions) == 2
                # Header is tested by backend replay regressions; multipart photos must remain identical.
                assert all(body.count(b'name="images"') == count for body in submissions)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
                page.goto(args.ui+'/apply/'+kind,wait_until='domcontentloaded')
                expect(inputs).to_have_count(count)
                inputs.first.set_input_files({'name':'expired.png','mimeType':'image/png','buffer':stream.getvalue()})
                expect(page.get_by_text('Your customer session ended. Sign in to continue.',exact=True)).to_be_visible()
                page.locator('[name=email]').fill('fixture@example.test');page.locator('[name=password]').fill('controlled-fictional-password')
                page.get_by_role('button',name='Sign in as customer',exact=True).click()
                expect(inputs).to_have_count(count)
                inputs.first.set_input_files({'name':'refreshed.png','mimeType':'image/png','buffer':stream.getvalue()})
                expect(page.locator('.upload-item').first).to_contain_text('accepted:')
                rows.append({'kind': kind, 'width': width, 'required_field_blockers':checked_fields,'suggestions_autofill_consent': 'passed', 'replacement_removal_stale_response': 'passed', 'pending_reason': 'passed', 'failed_request_recovery_duplicate_click': 'passed','expired_session_signin_recovery':'passed', 'source': 'controlled API / actual component'})
            assert not errors, errors
            context.close()
        browser.close()
    (output / ('baseline-readiness.json' if args.baseline else 'readiness-browser.json')).write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__': main()
