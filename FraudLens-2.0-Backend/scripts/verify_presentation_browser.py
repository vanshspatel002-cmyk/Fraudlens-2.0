"""Presentation acceptance through real Chrome, API, uploads and durable worker.

Uses a new explicitly supplied isolated SQLite database and private output folder.
Provider stop controls stay in place; genuine corpus photos test workflow only,
not six views of one vehicle or fraud accuracy. One deliberate network abort
checks preservation, and only this rehearsal's own sessions may be expired.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time
from datetime import date

import httpx
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
UI = os.environ.get("PRESENTATION_UI", "http://127.0.0.1:5173")
API = os.environ.get("PRESENTATION_API", "http://127.0.0.1:8001")
OUT = Path(os.environ["PRESENTATION_OUTPUT_DIR"]).resolve()
DB = Path(os.environ["PRESENTATION_DB"]).resolve()
LEDGER = ROOT / "outputs/pilot_validation/live_calls.json"
observations = []


def record(check, **details):
    observations.append({"check": check, **details})
    (OUT / "browser_verification.json").write_text(json.dumps(observations, indent=2), encoding="utf-8")
    print(check, json.dumps(details), flush=True)


def headers(page, role="admin"):
    token = page.evaluate("sessionStorage.getItem('fraudlens_" + role + "_token')")
    return {"Authorization": "Bearer " + token}


def customer_signin(page, account, register=False):
    page.bring_to_front()
    page.goto(UI + "/dashboard", wait_until="domcontentloaded", timeout=120000)
    if register:
        page.get_by_role("button", name="New here? Create an account", exact=True).click()
        page.locator('input[name="name"]').fill(account["name"])
    page.locator('input[name="email"]').fill(account["email"])
    page.locator('input[name="password"]').fill(account["password"])
    page.get_by_role("button", name="Create account" if register else "Sign in as customer", exact=True).click()
    expect(page.get_by_role("button", name="Sign out customer", exact=True)).to_be_visible(timeout=45000)


def admin_signin(page, account):
    page.bring_to_front()
    page.goto(UI + "/admin", wait_until="domcontentloaded", timeout=120000)
    page.locator('input[name="email"]').fill(account["email"])
    page.locator('input[name="password"]').fill(account["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible(timeout=45000)


def sample(page, name):
    page.keyboard.press("Escape")
    control = page.locator(f'form [name="{name}"]')
    control.click()
    option = page.locator(".sample-popover").get_by_role("option").first
    expect(option).to_be_visible(timeout=10000)
    option.click()
    assert control.input_value(), name


def intake(page, kind, index, photos):
    page.bring_to_front()
    page.goto(UI + "/apply/" + kind, wait_until="domcontentloaded", timeout=120000)
    button = page.get_by_role("button", name="Submit claim" if kind == "claims" else "Submit application", exact=True)
    expect(button).to_be_enabled(timeout=60000)
    button.click()
    assert not page.locator("form").evaluate("form => form.checkValidity()")
    fields = ["name", "email", "phone", "license", "address", "make", "model", "variant", "year", "registration", "engine", "chassis", "idv", "policy", "ncb"]
    if kind == "claims":
        fields += ["incidentDate", "incidentTime", "location", "amount", "garage"]
    else:
        fields += ["previousPolicy"]
    fields += ["description"]
    for name in fields:
        sample(page, name)
    page.locator('input[name="name"]').fill("Fictional presentation applicant " + str(index))
    page.locator('input[name="registration"]').fill("MH12EX" + str(1200 + index))
    page.keyboard.press("Escape")
    page.locator('select[name="policyType"]').select_option(label="Comprehensive")
    if kind == "claims":
        page.locator('select[name="settlement"]').select_option(label="Reimbursement")
        assert date.fromisoformat(page.locator('[name="incidentDate"]').input_value()) < date.today()
    else:
        page.locator('select[name="applicationType"]').select_option(label="Break-in Inspection")
        page.locator('select[name="condition"]').select_option(label="Unsure; inspection needed")
    if index == 1:
        page.get_by_label("Upload Damage overview", exact=True).set_input_files({"name": "invalid.txt", "mimeType": "text/plain", "buffer": b"invalid evidence"})
        expect(page.get_by_role("alert")).to_contain_text("JPG, PNG or WebP")
        expect(page.locator('[name="name"]')).to_have_value("Fictional presentation applicant 1")
    slots = ["Damage overview"] if kind == "claims" else ["Front left", "Front right", "Rear left", "Rear right", "Odometer", "Registration plate"]
    for slot, path in zip(slots, photos):
        page.get_by_label("Upload " + slot, exact=True).set_input_files(str(path))
    if index == 1:
        page.get_by_role("button", name="Remove damage overview photograph", exact=True).click()
        expect(page.get_by_role("button", name="Remove damage overview photograph", exact=True)).to_have_count(0)
        page.get_by_label("Upload Damage overview", exact=True).set_input_files(str(photos[0]))
    page.locator('input[name="consent"]').check()
    if index == 1:
        page.route("**/v1/cases", lambda route: route.abort("failed"))
        button.click()
        expect(page.get_by_role("alert")).to_be_visible(timeout=20000)
        expect(button).to_be_enabled()
        expect(page.locator('[name="name"]')).to_have_value("Fictional presentation applicant 1")
        expect(page.get_by_role("button", name="Remove damage overview photograph", exact=True)).to_be_visible()
        page.unroute("**/v1/cases")
        record("Required inputs, invalid upload, removal, and deliberately aborted network preserve the form")
    started = time.monotonic()
    if index == 1:
        # Retain the actual browser FormData, including its File objects. CDP's
        # textual multipart post-data representation can corrupt binary bytes.
        page.evaluate("""() => {
          const originalFetch = window.fetch.bind(window);
          window.__presentationFetch = originalFetch;
          window.fetch = (input, options) => {
            if (String(input).endsWith('/v1/cases') && options?.body instanceof FormData) {
              window.__presentationSubmission = {input, options: {...options}};
            }
            return originalFetch(input, options);
          };
        }""")
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/v1/cases"), timeout=180000) as response:
        button.dblclick(delay=25)
    assert response.value.status == 201, f"Unexpected HTTP status {response.value.status}"
    submitted = response.value.json()
    acceptance_observed = time.monotonic() - started
    request_timing = response.value.request.timing
    request_seconds = request_timing['responseEnd'] / 1000 if request_timing.get('responseEnd', -1) >= 0 else None
    expect(page.get_by_role("heading", name="Your case has been received.", exact=True)).to_be_visible(timeout=30000)
    assert page.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
    if index == 1:
        replay = page.evaluate("""async () => {
          const saved = window.__presentationSubmission;
          const response = await window.__presentationFetch(saved.input, {...saved.options, signal: AbortSignal.timeout(45000)});
          const data = await response.json();
          return {status: response.status, case_id: data.case_id, code: data.code};
        }""")
        assert replay["status"] == 201 and replay.get("case_id") == submitted["case_id"], f"Unexpected idempotency response status {replay['status']}"
        record("Exact authenticated idempotency replay returns the original durable case")
        # CDP can omit streamed multipart file bytes (post_data_buffer=None).
        # The real browser FormData replay above is the supported verification.
    page.get_by_role("link", name="View this case in your dashboard", exact=False).click()
    expect(page.get_by_role("heading", name=submitted["case_id"], exact=True)).to_be_visible(timeout=45000)
    record(kind + " accepted once with explicit field selections and uploads", case_id=submitted["case_id"], images=submitted["images_received"], browser_http_request_seconds=request_seconds, observed_submission_response_seconds=round(acceptance_observed, 3), confirmation_and_replay_seconds=round(time.monotonic()-started, 3))
    return submitted


def open_case(page, case_id):
    page.bring_to_front()
    page.get_by_role("button", name="Case queue", exact=True).click()
    page.get_by_placeholder("Search case ID, registration, policy or claimant").fill(case_id)
    expect(page.get_by_role("button", name=case_id, exact=True)).to_be_visible(timeout=45000)
    page.get_by_role("button", name=case_id, exact=True).click()
    expect(page.get_by_role("heading", name="Vehicle photographs", exact=True)).to_be_visible(timeout=45000)


def terminal(admin, job_id):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < 900:
        response = httpx.get(API + "/v1/jobs/" + job_id, headers=headers(admin), timeout=45)
        response.raise_for_status()
        job = response.json()
        if job["stage"] != last:
            print("Processing", job_id, job["stage"], round(time.monotonic()-started, 1), flush=True)
            last = job["stage"]
        if job["status"] in {"failed", "completed", "done", "interrupted"}:
            # JobOut deliberately exposes a smaller public view. Read timing
            # from this explicitly isolated database, never infer it from polls.
            with sqlite3.connect(DB) as conn:
                row = conn.execute('SELECT payload FROM api_jobs WHERE job_id=?',(job_id,)).fetchone()
            persisted = json.loads(row[0]) if row else {}
            elapsed = persisted.get('updated_at', 0) - persisted.get('started_at', 0) if persisted.get('started_at') and persisted.get('updated_at') else None
            record("Durable worker reached honest terminal state", job_id=job_id, status=job["status"], provider_unavailable=job.get("provider_unavailable"), observed_terminal_wait_seconds=round(time.monotonic()-started, 3), persisted_processing_seconds=round(elapsed,3) if elapsed is not None else None, job_started_at=persisted.get('started_at'), job_updated_at=persisted.get('updated_at'))
            return job
        time.sleep(2)
    raise AssertionError("Durable processing has not completed in 15 minutes")


def refresh_case(admin):
    admin.get_by_role("button", name="Refresh case", exact=True).click()
    expect(admin.get_by_role("button", name="Refresh case", exact=True)).to_be_enabled(timeout=60000)


def decision(admin, action, public):
    admin.locator('select[name="action"]').select_option(label=action)
    admin.locator('textarea[name="reason"]').fill("Fictional presentation manual review: inspected the submitted photographs and disclosed incomplete automated analysis. This demonstrates workflow and establishes no detection accuracy or real claim entitlement.")
    admin.locator('textarea[name="publicNarrative"]').fill(public)
    if action == "Request More Evidence":
        admin.locator('textarea[name="requestedArtifacts"]').fill("One original additional vehicle photograph showing the rear registration")
    elif admin.locator('input[name="manualReviewOverride"]').count():
        admin.locator('input[name="manualReviewOverride"]').check()
    name = {"Approve": "Approve case", "Reject": "Reject case", "Request More Evidence": "Request more evidence"}[action]
    with admin.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/action"), timeout=60000) as response:
        admin.get_by_role("button", name=name, exact=True).click()
    assert response.value.status == 200, f"Unexpected HTTP status {response.value.status}"


def pdf(admin, case_id, label):
    admin.get_by_role("button", name="Report", exact=True).click()
    panel = admin.get_by_role("region", name="Saved PDF report", exact=True)
    expect(panel.get_by_role("button", name="Preview report", exact=True)).to_be_enabled(timeout=60000)
    panel.get_by_role("button", name="Preview report", exact=True).click()
    dialog = admin.get_by_role("dialog", name="PDF report preview", exact=True)
    expect(dialog).to_be_visible(timeout=60000)
    frame = dialog.locator('iframe[title="Saved FraudLens PDF report"]')
    assert frame.get_attribute("src").startswith("blob:")
    expect(dialog.get_by_role("link", name="Open PDF in a new tab", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Close preview", exact=True).click()
    expect(dialog).to_have_count(0)
    with admin.expect_download(timeout=60000) as download:
        panel.get_by_role("button", name="Download PDF", exact=True).click()
    path = OUT / (label + ".pdf")
    download.value.save_as(path)
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert case_id in text and "FraudLens" in text and len(text) > 1000
    import fitz
    with fitz.open(path) as rendered:
        for number in sorted({0, len(rendered)-1}):
            rendered[number].get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(OUT / (label + "-page-" + str(number+1) + ".png"))
    record("Authenticated saved PDF preview/download", case_id=case_id, filename=download.value.suggested_filename, pages=len(reader.pages), text_characters=len(text))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "browser_verification.json").exists():
        raise SystemExit("Use a new output directory; earlier evidence is preserved.")
    assert DB.is_file() and (DB.parent == OUT or DB.parent in OUT.parents), "Only the explicit isolated rehearsal database may be touched"
    assert httpx.get(API + "/health", timeout=60).json()["database"] == DB.name
    initial_ledger = hashlib.sha256(LEDGER.read_bytes()).hexdigest()
    with sqlite3.connect(DB) as conn:
        baseline_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        baseline_owners = conn.execute("SELECT COUNT(*) FROM case_owners").fetchone()[0]
    admin_account = json.loads((ROOT / "outputs/pilot_validation/demo_credentials.json").read_text())
    account = {"name": "Fictional Presentation Customer", "email": "presentation-" + secrets.token_hex(4) + "@example.test", "password": secrets.token_urlsafe(24)}
    (OUT / "private_customer_credentials.json").write_text(json.dumps(account), encoding="utf-8")
    photos = sorted((ROOT / "data/curated/whole").glob("*.jpg"))
    assert len(photos) >= 9
    errors, console_errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width":1365, "height":900}, accept_downloads=True, has_touch=True)
        def observe(page):
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: console_errors.append(message.text[:500]) if message.type == "error" else None)
        context.on("page", observe)
        customer, admin = context.new_page(), context.new_page()
        cases = []
        try:
            customer_signin(customer, account, register=True)
            admin_signin(admin, admin_account)
            assert customer.evaluate("sessionStorage.getItem('fraudlens_admin_token')") is None
            assert admin.evaluate("sessionStorage.getItem('fraudlens_customer_token')") is None
            record("Customer registration and reviewer sign-in coexist in two ordinary tabs", browser=browser.version)
            for index, (kind, action) in enumerate((("claims", "Approve"), ("claims", "Reject"), ("underwriting", "Approve"), ("underwriting", "Reject")), start=1):
                submitted = intake(customer, kind, index, photos[:1] if kind == "claims" else photos[1:7])
                cases.append(submitted["case_id"])
                open_case(admin, submitted["case_id"])
                terminal(admin, submitted["job_id"])
                refresh_case(admin)
                digest = pdf(admin, submitted["case_id"], kind + "-" + action.lower() + "-analysis")
                versions = httpx.get(API + "/v1/cases/" + submitted["case_id"] + "/reports", headers=headers(admin), timeout=45).json()["reports"]
                saved_snapshot = next(version["snapshot_id"] for version in versions if version.get("sha256") == digest)
                if index == 1:
                    decision(admin, "Request More Evidence", "Please provide the requested original additional photograph for this fictional presentation review.")
                    customer.bring_to_front()
                    expect(customer.get_by_role("heading", name="Requested photographs", exact=True)).to_be_visible(timeout=45000)
                    customer.locator('input[type="file"]').set_input_files(str(photos[7]))
                    with customer.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/evidence"), timeout=180000) as supplemented:
                        customer.get_by_role("button", name="Submit requested evidence", exact=True).click()
                    assert supplemented.value.status == 200, f"Unexpected evidence response status {supplemented.value.status}"
                    terminal(admin, supplemented.value.json()["job_id"])
                    admin.bring_to_front()
                    refresh_case(admin)
                    record("Additional evidence requested and accepted through the authorized customer dashboard")
                public = "Fictional presentation application " + ("approved after manual evidence review." if action == "Approve" else "declined because the presentation evidence does not establish the required vehicle condition.")
                decision(admin, action, public)
                customer.bring_to_front()
                expect(customer.locator(".ud-narrative")).to_have_text(public, timeout=45000)
                expect(customer.get_by_role("heading", name="Approved" if action == "Approve" else "Declined", exact=True)).to_be_visible()
                assert "Fictional presentation manual review:" not in customer.locator("main").inner_text()
                saved_pdf = httpx.get(API + "/v1/cases/" + submitted["case_id"] + "/reports/" + saved_snapshot + "/pdf", headers=headers(admin), timeout=60)
                assert saved_pdf.status_code == 200 and hashlib.sha256(saved_pdf.content).hexdigest() == digest
                record("Original saved analysis PDF stays byte-identical after human decision", case_id=submitted["case_id"], snapshot_id=saved_snapshot)
                record(kind + " " + action.lower() + " automatically visible in customer tab", case_id=submitted["case_id"])
                customer.screenshot(path=str(OUT / (kind + "-" + action.lower() + "-customer.png")), full_page=True)
            # All data and sessions survive ordinary tab refreshes.
            customer.reload(wait_until="domcontentloaded")
            admin.reload(wait_until="domcontentloaded")
            expect(customer.get_by_role("button", name="Sign out customer", exact=True)).to_be_visible(timeout=45000)
            expect(admin.get_by_role("button", name="Sign out", exact=True)).to_be_visible(timeout=45000)
            record("Both ordinary tab sessions survive refresh")

            # A second genuine customer token cannot reach any first account data.
            stranger = {"name":"Fictional Other Customer", "email":"other-" + secrets.token_hex(4) + "@example.test", "password":secrets.token_urlsafe(24)}
            response = httpx.post(API + "/v1/customer/auth/register", json=stranger, timeout=45)
            assert response.status_code == 201
            other_headers = {"Authorization":"Bearer " + response.json()["token"]}
            first = httpx.get(API + "/v1/customer/cases/" + cases[0], headers=headers(customer, "customer"), timeout=45).json()
            private_version = httpx.get(API + "/v1/cases/" + cases[0] + "/reports", headers=headers(admin), timeout=45).json()["reports"][0]["snapshot_id"]
            checks = {}
            for path in ["/v1/customer/cases/" + cases[0], "/v1/customer/images/" + first["images"][0]["id"], "/v1/cases/" + cases[0] + "/reports/" + private_version + "/pdf"]:
                checks[path] = httpx.get(API + path, headers=other_headers, timeout=45).status_code
                assert checks[path] in {401,403,404}
            assert httpx.get(API + "/v1/customer/cases", headers=other_headers, timeout=45).json()["items"] == []
            assert httpx.get(API + "/v1/cases", headers=headers(customer, "customer"), timeout=45).status_code == 401
            assert httpx.get(API + "/v1/customer/cases", headers=headers(admin), timeout=45).status_code == 401
            with sqlite3.connect(DB) as conn:
                assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == baseline_cases + 4
                assert conn.execute("SELECT COUNT(*) FROM case_owners").fetchone()[0] == baseline_owners + 4
            record("Second customer cannot access another case, evidence, reports, or reviewer API", statuses=checks)

            # Receipt tracking works without an account; registration alone cannot.
            receipt = customer.evaluate("sessionStorage.getItem('fraudlens_applicant_' + " + json.dumps(cases[0]) + ")")
            params = {"case_id": cases[0], "registration_number": "MH12EX1201", "policy_number": "MH12EX1201"}
            assert httpx.get(API + "/v1/track", params=params, timeout=45).status_code in {401,403,404}
            tracked = httpx.get(API + "/v1/track", params=params, headers={"X-Applicant-Token":receipt}, timeout=45)
            assert tracked.status_code == 200 and tracked.json()["status"] == "closed_approved"
            record("Private receipt tracking succeeds; registration-only lookup is denied")

            customer.set_viewport_size({"width":390,"height":844})
            for kind in ("claims","underwriting"):
                customer.goto(UI + "/apply/" + kind, wait_until="domcontentloaded")
                name = customer.locator('form [name="name"]')
                expect(name).to_be_visible(timeout=45000)
                name.tap()
                customer.locator(".sample-popover").get_by_role("option", name="Mira Sample", exact=True).tap()
                expect(name).to_have_value("Mira Sample")
                name.fill("Fictional editable mobile entry")
                name.press("Escape")
                assert customer.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not customer.locator('[name="consent"]').is_checked()
                customer.screenshot(path=str(OUT / ("mobile-"+kind+"-form.png")),full_page=True)
                record("Real signed-in mobile " + kind + " form supports touch suggestion selection and manual editing", width=390)
            customer.goto(UI + "/dashboard?case=" + cases[-1], wait_until="domcontentloaded")
            expect(customer.locator(".ud-case-heading")).to_be_visible()
            assert customer.evaluate("document.documentElement.scrollWidth <= innerWidth")
            customer.screenshot(path=str(OUT / "mobile-customer-detail.png"), full_page=True)
            customer.set_viewport_size({"width":768,"height":1024})
            admin.set_viewport_size({"width":768,"height":1024})
            assert customer.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
            customer.screenshot(path=str(OUT / "tablet-customer.png"),full_page=True)
            admin.screenshot(path=str(OUT / "tablet-admin.png"),full_page=True)
            record("Tablet customer and reviewer dashboards fit 768px")
            open_case(admin, cases[-1])
            admin.set_viewport_size({"width":390,"height":844})
            admin.get_by_role("button", name="Report", exact=True).click()
            admin.get_by_role("region", name="Saved PDF report", exact=True).get_by_role("button", name="Preview report", exact=True).click()
            mobile_pdf = admin.get_by_role("dialog", name="PDF report preview", exact=True)
            expect(mobile_pdf).to_be_visible(timeout=60000)
            expect(mobile_pdf.get_by_role("link", name="Open PDF in a new tab", exact=True)).to_be_visible()
            mobile_pdf.get_by_role("button", name="Close preview", exact=True).click()
            assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
            admin.screenshot(path=str(OUT / "mobile-admin.png"), full_page=True)
            record("Mobile customer and reviewer layouts fit 390px")
            customer.set_viewport_size({"width":1365,"height":900})
            admin.set_viewport_size({"width":1365,"height":900})

            if os.environ.get("PRESENTATION_PAUSE_RESTART") == "1":
                (OUT / "restart_requested").write_text("Restart only this rehearsal API and worker, then create restart_ready.")
                print("RESTART CHECKPOINT", str(OUT), flush=True)
                deadline = time.monotonic() + 600
                while not (OUT / "restart_ready").exists() and time.monotonic() < deadline:
                    time.sleep(1)
                assert (OUT / "restart_ready").exists(), "Restart checkpoint was not acknowledged"
                customer.get_by_role("button", name="Refresh cases", exact=True).click()
                expect(customer.get_by_role("button", name="Sign out customer", exact=True)).to_be_visible(timeout=45000)
                assert len(httpx.get(API + "/v1/customer/cases", headers=headers(customer, "customer"), timeout=60).json()["items"]) == 4
                record("API/worker restart preserves four owned cases and both valid sessions")

            admin.get_by_role("button", name="Sign out", exact=True).click()
            expect(admin.get_by_role("button", name="Sign in", exact=True)).to_be_visible(timeout=45000)
            assert httpx.get(API + "/v1/customer/auth/session", headers=headers(customer,"customer"), timeout=45).status_code == 200
            admin_signin(admin, admin_account)
            customer.get_by_role("button", name="Sign out customer", exact=True).click()
            expect(customer.get_by_role("button", name="Sign in as customer", exact=True)).to_be_visible(timeout=45000)
            assert httpx.get(API + "/v1/auth/session", headers=headers(admin), timeout=45).status_code == 200
            customer_signin(customer, account)
            record("Independent reviewer and customer logout preserves the other role")

            # Change only the exact session hashes created by this isolated test.
            with sqlite3.connect(DB) as conn:
                for table, page, role in [("customer_sessions",customer,"customer"),("admin_sessions",admin,"admin")]:
                    token = page.evaluate("sessionStorage.getItem('fraudlens_"+role+"_token')")
                    assert conn.execute("UPDATE " + table + " SET expires_at=0 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).rowcount == 1
            customer.get_by_role("button", name="Refresh cases", exact=True).click()
            admin.get_by_role("button", name="Case queue", exact=True).click()
            expect(customer.get_by_role("button", name="Sign in as customer", exact=True)).to_be_visible(timeout=45000)
            expect(admin.get_by_role("button", name="Sign in", exact=True)).to_be_visible(timeout=45000)
            record("Expired customer/reviewer sessions return each tab to its correct sign-in")
            assert hashlib.sha256(LEDGER.read_bytes()).hexdigest() == initial_ledger, "Original model stop ledger changed"
            assert not errors, errors
            record("Presentation rehearsal complete", case_ids=cases, javascript_errors=errors, console_errors=console_errors, ledger_unchanged=True)
        except Exception as error:
            sanitized = str(error).replace(admin_account["password"], "[redacted]").replace(account["password"], "[redacted]")
            record("Rehearsal failed", error_type=type(error).__name__, message=sanitized[:1200], javascript_errors=errors, console_errors=console_errors)
            for name,page in [("customer",customer),("admin",admin)]:
                try: page.screenshot(path=str(OUT / (name+"-failure.png")), full_page=True)
                except Exception: pass
            raise RuntimeError("Browser rehearsal failed; see the sanitized private verification log.") from None
        finally:
            browser.close()


if __name__ == "__main__":
    main()
