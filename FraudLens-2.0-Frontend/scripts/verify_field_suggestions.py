r"""Chrome component rehearsal; no backend/model calls or case data are created.

Run against the Vite development server with the backend's Playwright Python:
  ..\FraudLens-2.0-Backend\venv\Scripts\python.exe scripts\verify_field_suggestions.py
Set SUGGESTIONS_UI if the isolated development server is not on port 5174.
"""
import json
import os
from datetime import date
from playwright.sync_api import expect, sync_playwright

UI = os.environ.get("SUGGESTIONS_UI", "http://127.0.0.1:5174")
HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{box-sizing:border-box}body{background:#111;color:#eee;font:16px Arial;margin:0}.field{display:flex;flex-direction:column;gap:8px;margin:24px 0}input,textarea,select{font:16px Arial;padding:12px;width:100%;min-width:0}input[type=checkbox]{width:auto}button{padding:14px}label{line-height:1.5}
</style><script type="module">import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body><div id="root"></div><script type="module" src="/scripts/field-suggestions-harness.tsx"></script></body></html>'''


def open_fixture(page, kind="claims"):
    page.route("**/__field-suggestions-check*", lambda route: route.fulfill(status=200, content_type="text/html", body=HTML))
    page.goto(UI + "/__field-suggestions-check?kind=" + kind, wait_until="domcontentloaded")
    expect(page.locator('[name="name"]')).to_be_visible(timeout=60000)


def run():
    checks = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1365, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        open_fixture(page)
        assert page.locator('form').evaluate("form => Array.from(new FormData(form).values()).every(value => typeof value !== 'string' || value === '')")
        name = page.locator('[name="name"]')
        if os.environ.get("SUGGESTIONS_EXPECT_DISABLED") == "1":
            name.hover()
            name.click()
            name.fill("Manual input with suggestions disabled")
            name.press("ArrowDown")
            expect(page.get_by_role("listbox")).to_have_count(0)
            expect(name).to_have_value("Manual input with suggestions disabled")
            assert name.get_attribute("role") is None
            assert not errors, errors
            print(json.dumps({"checks": ["VITE_SAMPLE_SUGGESTIONS=false disables dropdowns and preserves manual input"], "javascript_errors": errors, "browser": browser.version}, indent=2))
            browser.close()
            return
        name.hover()
        expect(page.get_by_role("listbox", name="Sample suggestions for name")).to_be_visible()
        option = page.get_by_role("option", name="Aarav Example", exact=True)
        box = option.bounding_box()
        page.mouse.move(box["x"] + 15, box["y"] + 12, steps=8)
        expect(option).to_be_visible()
        option.click()
        expect(name).to_have_value("Aarav Example")
        expect(page.get_by_role("listbox")).to_have_count(0)
        expect(page.locator('[name="email"]')).to_have_value("")
        checks.append("desktop hover, pointer transition, one-field selection, no prefill")

        name.fill("mira")
        expect(page.locator(".sample-popover").get_by_role("option")).to_have_count(1)
        name.press("ArrowDown")
        name.press("Enter")
        expect(name).to_have_value("Mira Sample")
        name.fill("My manual editable entry")
        expect(name).to_have_value("My manual editable entry")
        expect(page.get_by_text("No matching samples. Keep typing your own value.")).to_be_visible()
        name.press("Escape")
        expect(page.get_by_role("listbox")).to_have_count(0)
        name.click()
        expect(page.get_by_role("listbox")).to_be_visible()
        page.locator("h1").click()
        expect(page.get_by_role("listbox")).to_have_count(0)
        checks.append("type filtering, keyboard selection, editable manual entry, Escape and outside close")

        page.locator('[name="make"]').fill("Maruti Suzuki")
        page.locator('[name="make"]').press("Escape")
        page.locator('[name="model"]').click()
        expect(page.locator(".sample-popover").get_by_role("option")).to_have_count(2)
        page.get_by_role("option", name="Swift · Maruti Suzuki", exact=True).click()
        page.locator('[name="variant"]').click()
        expect(page.get_by_role("option", name="VXI", exact=True)).to_be_visible()
        page.get_by_role("option", name="VXI", exact=True).click()
        page.locator('[name="make"]').fill("Hyundai")
        expect(page.get_by_text("Swift is listed in the sample catalog under Maruti Suzuki.", exact=False)).to_be_visible()
        expect(page.locator('[name="model"]')).to_have_value("Swift")
        expect(page.locator('[name="variant"]')).to_have_value("VXI")
        page.locator('[name="make"]').press("Escape")
        checks.append("dependent make/model/variant suggestions and warnings preserve entries")

        for field in ["phone", "license", "address", "year", "registration", "engine", "chassis", "idv", "policy", "previousPolicy", "ncb", "incidentDate", "incidentTime", "location", "amount", "garage", "description"]:
            control = page.locator(f'[name="{field}"]')
            control.click()
            expect(page.get_by_role("listbox")).to_be_visible()
            page.locator(".sample-popover").get_by_role("option").first.click()
            assert control.input_value(), field
            assert control.evaluate("control => control.checkValidity()"), field
        assert date.fromisoformat(page.locator('[name="incidentDate"]').input_value()) < date.today()
        checks.append("actual catalog text, numeric, date/time, address and narrative selections satisfy field constraints")
        page.locator('[name="bankLast4"]').click()
        expect(page.get_by_role("listbox")).to_have_count(0)
        assert not page.locator('[name="consent"]').is_checked()
        assert page.locator('[name="evidence"]').evaluate("control => control.files.length") == 0
        checks.append("banking details, selects, consent and evidence remain explicit")

        mobile = browser.new_context(viewport={"width": 390, "height": 700}, is_mobile=True, has_touch=True)
        mobile_page = mobile.new_page()
        mobile_page.on("pageerror", lambda error: errors.append(str(error)))
        open_fixture(mobile_page, "underwriting")
        mobile_page.locator('[name="name"]').tap()
        mobile_page.get_by_role("option", name="Mira Sample", exact=True).tap()
        expect(mobile_page.locator('[name="name"]')).to_have_value("Mira Sample")
        narrative = mobile_page.locator('[name="description"]')
        narrative.tap()
        mobile_page.locator(".sample-popover").get_by_role("option").first.tap()
        assert "private commuting" in narrative.input_value()
        mobile_page.locator('[name="email"]').tap()
        rectangle = mobile_page.locator(".sample-popover").bounding_box()
        assert rectangle["x"] >= 0 and rectangle["x"] + rectangle["width"] <= 391
        assert rectangle["y"] >= 0 and rectangle["y"] + rectangle["height"] <= 701
        assert mobile_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        checks.append("mobile focus/tap selection, underwriting narratives, edge positioning, no horizontal overflow")
        assert not errors, errors
        print(json.dumps({"checks": checks, "javascript_errors": errors, "browser": browser.version}, indent=2))
        browser.close()


if __name__ == "__main__":
    run()
