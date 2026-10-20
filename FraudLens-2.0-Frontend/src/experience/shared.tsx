import { useState, useEffect, type ReactNode } from "react";
import { customerToken, clearCustomerSession } from './customer-api';
export const categories = ["Identity", "History", "Provenance", "Context", "Economic"];
export const recommendations = [
  "Clear",
  "Request Additional Evidence",
  "Desk Review",
  "Escalate to SIU",
];
export const checks = [
  [
    "Plate verification",
    "Identity",
    "Both",
    "Matches visible registration with the declaration.",
    "OCR can be inconclusive on obscured plates.",
  ],
  [
    "Case Memory similarity",
    "History",
    "Recon",
    "Searches earlier submissions across both agents.",
    "Reuse is a lead, not proof of dishonest intent.",
  ],
  [
    "External corpus search",
    "Provenance",
    "Recon",
    "Looks for images from outside sources.",
    "Coverage depends on the available corpus.",
  ],
  [
    "EXIF metadata",
    "Provenance",
    "Recon",
    "Reads available capture information.",
    "Missing EXIF is neutral; messaging services routinely strip it.",
  ],
  [
    "Content credentials",
    "Provenance",
    "Recon",
    "Examines available provenance credentials.",
    "Absent credentials do not imply manipulation.",
  ],
  [
    "Sun and shadow consistency",
    "Context",
    "Recon",
    "Compares declared time and location with visible shadows.",
    "Requires reliable time, location and observable geometry.",
  ],
  [
    "Historical weather",
    "Context",
    "Recon",
    "Compares the scene with recorded conditions.",
    "Records may not resolve local conditions.",
  ],
  [
    "Threshold Gaming",
    "Economic",
    "Recon",
    "Examines garage-level clustering below ₹50,000.",
    "Attributed to the garage, never an accusation against one claimant.",
  ],
  [
    "Damage and amount plausibility",
    "Economic",
    "Recon",
    "Compares visible damage with the amount claimed.",
    "A photograph cannot reveal all internal damage.",
  ],
  [
    "Entity Graph",
    "History",
    "Recon",
    "Finds relationships across separate cases.",
    "Shared identifiers are leads, not proof of collusion.",
  ],
  [
    "Severity Progression",
    "History",
    "Recon",
    "Compares damage across repeat claims.",
    "Different views and lighting limit comparison.",
  ],
  [
    "View completeness",
    "Context",
    "Sentinel",
    "Checks four corners, odometer and plate.",
    "A missing view triggers a targeted evidence request.",
  ],
  [
    "Baseline Corruption Check",
    "Context",
    "Sentinel",
    "Compares declared condition with visible damage.",
    "Uncertainty remains Inconclusive, never automatically Concern.",
  ],
  [
    "Baseline Linkage",
    "History",
    "Sentinel",
    "Connects an inspection with subsequent claims.",
    "Timing alone cannot establish pre-existing damage.",
  ],
];
export function Icon({ name = "scan", size = 24 }: { name?: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5" />,
    shield: (
      <>
        <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    scan: (
      <>
        <path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5M2 12h20" />
        <circle cx="12" cy="12" r="5" />
      </>
    ),
    file: <path d="M5 3h10l4 4v14H5Zm10 0v5h4M8 12h8m-8 4h6" />,
    eye: (
      <>
        <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2" />
      </>
    ),
    layers: <path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 17l10 5 10-5" />,
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" />
      </>
    ),
    check: <path d="m4 12 5 5L20 6" />,
    car: <path d="m4 10 2-6h12l2 6M3 10h18v9H3Zm3 9v2m12-2v2M6 14h2m8 0h2" />,
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 6 6" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.scan}
    </svg>
  );
}
export function Mark({ kind = "recon" }: { kind?: string }) {
  const recon = kind === "recon";
  return (
    <div className={"agent-mark agent-portrait " + kind}>
      <img
        src={recon ? "/media/agent-recon.png" : "/media/agent-sentinel.png"}
        alt={
          recon
            ? "Agent Recon — Claims investigation"
            : "Agent Sentinel — Underwriting verification"
        }
        width="600"
        height="600"
        decoding="async"
      />
    </div>
  );
}
export function Logo() {
  return (
    <a className="brand" href="/" aria-label="FraudLens 2.0 home">
      <span className="brand-symbol">
        <Icon name="scan" size={25} />
      </span>
      FraudLens<span className="brand-version">2.0</span>
    </a>
  );
}
export function Header({ active = "" }: { active?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <header
      className="header"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <div className="nav-wrap">
        <Logo />
        <nav className={open ? "open" : ""} id="main-navigation" aria-label="Main navigation">
          {[
            ["/", "Home"],
            ["/claims", "Claims"],
            ["/underwriting", "Underwriting"],
            ["/about", "About"],
            ["/dashboard", "Dashboard"],
          ].map(([url, label]) => (
            <a
              key={url}
              className={active === label ? "active" : ""}
              aria-current={active === label ? "page" : undefined}
              href={url}
            >
              {label}
            </a>
          ))}
          <a className="track-nav admin-nav" href="/admin">
            Admin <Icon name="lock" size={16} />
          </a>
          <a className="track-nav" href="/track">
            Track a case <Icon name="arrow" size={16} />
          </a>
        </nav>
        <button
          className="menu-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="main-navigation"
          aria-label="Toggle navigation"
        >
          <Icon name="menu" />
        </button>
      </div>
    </header>
  );
}
export function Footer() {
  return (
    <footer>
      <div className="footer-grid">
        <div>
          <Logo />
          <p>
            Evidence before decisions.
            <br />
            Human judgment, always.
          </p>
        </div>
        <div>
          <span>Platform</span>
          <a href="/claims">Agent Recon</a>
          <a href="/underwriting">Agent Sentinel</a>
          <a href="/about">How it works</a>
        </div>
        <div>
          <span>Your case</span>
          <a href="/dashboard">Your dashboard</a>
          <a href="/apply/claims">Apply for Claims</a>
          <a href="/apply/underwriting">Apply for Underwriting</a>
          <a href="/track">Track a case</a>
        </div>
        <div>
          <span>Workspace</span>
          <a href="/admin">
            Admin login <Icon name="arrow" size={14} />
          </a>
          <p>
            Built for Indian
            <br />
            motor insurance.
          </p>
        </div>
      </div>
      <div className="footer-bottom">
        <span>© 2026 FraudLens 2.0</span>
        <span>Evidence-led review. Human accountability.</span>
      </div>
    </footer>
  );
}
export function Shell({ children, active }: { children: ReactNode; active?: string }) {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <Header active={active} />
      <main id="main">{children}</main>
      <Footer />
    </>
  );
}
export function DualCTA() {
  return (
    <div className="dual-cta">
      <a className="claims-link" href="/apply/claims">
        Apply for Claims <Icon name="arrow" size={18} />
      </a>
      <a className="underwriting-link" href="/apply/underwriting">
        Apply for Underwriting <Icon name="arrow" size={18} />
      </a>
    </div>
  );
}
export function Closing() {
  return (
    <section className="closing wrap">
      <h2>Start with the evidence.</h2>
      <p>
        A claim to investigate. A vehicle to verify.
        <br />
        Choose the right starting point.
      </p>
      <DualCTA />
    </section>
  );
}
export function Safety() {
  return (
    <div className="safety">
      <Icon name="shield" size={21} />
      <p>
        <strong>The agent recommends. A human decides.</strong> Neither agent can reject a claim or
        application.
      </p>
    </div>
  );
}
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const adminEmail = () => sessionStorage.getItem("fraudlens_admin_email") || "";
const adminToken = () => sessionStorage.getItem("fraudlens_admin_token") || "";
const authHeaders = (): Record<string, string> =>
  adminToken() ? { Authorization: "Bearer " + adminToken() } : {};
type ApiRecord = Record<string, unknown>;
const stringValue = (value: unknown) => String(value || "");
async function request(path: string, options: RequestInit = {}, scope: 'reviewer'|'customer'|'public' = 'reviewer'): Promise<ApiRecord> {
  const headers = new Headers(options.headers);
  if (scope === 'reviewer') for (const [k, v] of Object.entries(authHeaders())) headers.set(k, v);
  if (scope === 'customer' && customerToken()) headers.set('Authorization', 'Bearer ' + customerToken());
  const sentAuthorization = headers.get('Authorization') || '';
  let r: Response;
  try {
    r = await fetch(API_BASE + path, { ...options, headers,
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(45000)]) : AbortSignal.timeout(45000) });
  } catch {
    throw new Error("The FraudLens API is unreachable. Check the backend service and try again.");
  }
  const text = await r.text();
  let j: unknown = null;
  try {
    j = text ? JSON.parse(text) : null;
  } catch {
    j = text;
  }
  const message = j && typeof j === "object" ? (j as ApiRecord).message : null;
  const error = j && typeof j === "object" ? (j as ApiRecord).error : null;
  const details = j && typeof j === "object" ? (j as ApiRecord).details : null;
  const detailText = Array.isArray(details)
    ? details
        .map((d) =>
          d && typeof d === "object"
            ? [stringValue((d as ApiRecord).field), stringValue((d as ApiRecord).reason)]
                .filter(Boolean)
                .join(": ")
            : "",
        )
        .filter(Boolean)
        .join("; ")
    : "";
  if (path !== '/v1/auth/login' && scope !== 'public' && sentAuthorization &&
      sentAuthorization !== 'Bearer ' + (scope === 'customer' ? customerToken() : adminToken())) {
    throw new Error('Your session changed. Reload this view to continue.');
  }
  if (r.status === 401 && scope === 'customer') {
    clearCustomerSession(); window.dispatchEvent(new Event('fraudlens-customer-session-expired'));
  }
  if (r.status === 401 && scope === 'reviewer' && path !== '/v1/auth/login' && headers.has('Authorization')) {
    sessionStorage.removeItem('fraudlens_admin_token');
    sessionStorage.removeItem('fraudlens_admin_email');
    imageUrls.forEach(url => URL.revokeObjectURL(url)); imageUrls.clear();
    window.dispatchEvent(new Event('fraudlens-session-expired'));
  }
  if (!r.ok)
    throw new Error(
      [stringValue(message || error), detailText].filter(Boolean).join(" ") ||
        "The request could not be completed. Please try again.",
    );
  return j as ApiRecord;
}
const band = (b?: string) =>
  b === "clear"
    ? "Low"
    : b === "request_evidence" || b === "desk_review"
      ? "Medium"
      : b === "escalate_siu"
        ? "High"
        : "Unrated";
const recommendation = (r?: string, riskBand?: string) =>
  riskBand === "desk_review" ? "Desk Review" : r === "approve"
    ? "Clear"
    : r === "request_evidence"
      ? "Request Additional Evidence"
      : r === "escalate"
        ? "Escalate to SIU"
        : "Pending";
const publicCase = (j: ApiRecord) => ({
  id: stringValue(j.case_id),
  kind: stringValue(j.agent_type) || "claims",
  status: stringValue(j.status),
  outcome: ['approve','reject'].includes(String(j.final_admin_action)) ? j.final_admin_action : null,
  latestAction: j.final_admin_action || null,
  publicNarrative: stringValue(j.narrative),
  updatedAt: new Date().toISOString(),
  processingStatus: stringValue(j.processing_status),
  evidenceRequest: j.evidence_request,
});
function mapFormData(input: FormData) {
  const out = new FormData();
  const claims = input.get("kind") !== "underwriting";
  out.set("agent_type", claims ? "claims" : "underwriting");
  out.set("claim_type", claims ? "motor_claim" : "underwriting_inspection");
  out.set('declaration_notes', [input.get('applicationType') ? 'Application type: '+String(input.get('applicationType')) : '', input.get('condition') ? 'Declared vehicle condition: '+String(input.get('condition')) : '', String(input.get('description') || '')].filter(Boolean).join('\n'));
  out.set("person_name", String(input.get("name") || ""));
  out.set("person_contact", [input.get("email"), input.get("phone")].filter(Boolean).join(" / "));
  out.set("person_address", String(input.get("address") || ""));
  out.set("driving_license_number", String(input.get("license") || ""));
  out.set("vehicle_make", String(input.get("make") || ""));
  out.set("vehicle_model", String(input.get("model") || ""));
  out.set("vehicle_variant", String(input.get("variant") || ""));
  out.set("vehicle_year", String(input.get("year") || ""));
  out.set("vehicle_registration", String(input.get("registration") || ""));
  out.set("engine_number", String(input.get("engine") || ""));
  out.set("chassis_number", String(input.get("chassis") || ""));
  out.set("idv", String(input.get("idv") || ""));
  out.set("policy_number", String(input.get("policy") || input.get("previousPolicy") || ""));
  out.set("policy_type", String(input.get("policyType") || input.get("applicationType") || ""));
  out.set("previous_policy_number", String(input.get("previousPolicy") || ""));
  out.set("policy_ncb_percent", String(input.get("ncb") || ""));
  out.set("declared_location", String(input.get("location") || ""));
  out.set("claim_amount", String(input.get("amount") || ""));
  out.set("garage_id", String(input.get("garage") || ""));
  out.set("settlement_preference", String(input.get("settlement") || ""));
  out.set("bank_account_last4", String(input.get("bankLast4") || ""));
  const d = String(input.get("incidentDate") || ""),
    t = String(input.get("incidentTime") || "00:00");
  if (d) out.set("declared_time", new Date(d + "T" + t + ":00+05:30").toISOString());
  for (const [k, v] of input.entries())
    if (k.startsWith("photo:") && v instanceof File) out.append("images", v, v.name);
  return out;
}
async function caseDetail(id: string) {
  const d = await request("/v1/cases/" + encodeURIComponent(id));
  let trace: { steps?: ApiRecord[] } = { steps: [] };
  try {
    trace = (await request("/v1/cases/" + encodeURIComponent(id) + "/trace")) as {
      steps?: ApiRecord[];
    };
  } catch {
    trace = { steps: [] };
  }
  let report: ApiRecord = {};
  try {
    report = await request("/v1/cases/" + encodeURIComponent(id) + "/report");
  } catch {
    report = {};
  }
  const findings = Object.values(
    (d.findings_by_category as Record<string, ApiRecord[]> | undefined) || {},
  ).flat();
  const images = await Promise.all(
    ((d.images as ApiRecord[] | undefined) || []).map(async (im) => ({
      ...im,
      id: stringValue(im.image_id),
      label: stringValue(im.damage_description) || "Vehicle evidence",
      src: await apiImageUrl(stringValue(im.image_id)),
    })),
  );
  const decision = (d.decision as ApiRecord | undefined) || {};
  const adminAction = (report.admin_action as ApiRecord | undefined) || {};
  return {
    ...d,
    images,
    id: stringValue(d.case_id),
    kind: stringValue(d.agent_type),
    name: stringValue(d.person_name || d.claimant_id),
    registration: stringValue(d.vehicle_registration),
    policy: stringValue(d.policy_number),
    garage: stringValue(d.garage_id),
    amount: Number(d.claim_amount || 0),
    risk: band(stringValue(d.risk_band)),
    recommendation: recommendation(stringValue(decision.recommendation), stringValue(decision.risk_band)),
    narrative: stringValue(decision.summary),
    outcome: stringValue(adminAction.action),
    reason: stringValue(adminAction.reason),
    admin: stringValue(adminAction.admin_id),
    updated_at: stringValue(adminAction.timestamp),
    requestedEvidence: (decision.requested_artifacts as string[] | undefined) || [],
    citedFindings: (decision.supporting_finding_ids as string[] | undefined) || [],
    declaration: {...((report.declaration as ApiRecord) || {}), ...(d.garage_id ? {garage_id:d.garage_id} : {})},
    runId: stringValue(report.run_id),
    policyVersion: stringValue(report.policy_version),
    limitations: (report.limitations as string[]) || [],
    reportHistory: d.report_history || [],
    version: d.review_revision,
    evidenceRequest: d.evidence_request,
    findings: findings.map((f) => ({
      id: stringValue(f.finding_id),
      check: stringValue(f.check_id),
      category: stringValue(f.category).replace(/^./,letter => letter.toUpperCase()),
      verdict: stringValue(f.verdict),
      confidence: Number(f.confidence || 0),
      explanation: stringValue(f.explanation),
      evidence: f.evidence,
      attributed_to: stringValue(f.attributed_to),
      subject_id: f.subject_id,
      subject_url: f.subject_url,
      check_status: f.check_status,
      check_weight: f.check_weight,
      check_limitation: f.check_limitation,
    })),
    trace: (trace.steps || []).map((s) => ({
      type: stringValue(s.type),
      title: stringValue(s.kind),
      summary: stringValue(s.content),
      tool: stringValue(s.tool_name),
      input: s.tool_input,
      result: s.tool_output,
    })),
    processing: d.processing,
    assessmentExplanation: report.assessment_explanation,
    analysisFallback: !!decision.provider_unavailable,
    humanReviewedRun: (report.admin_action as ApiRecord | undefined)?.reviewed_run_id
      ? String((report.admin_action as ApiRecord).reviewed_run_id) : undefined,
    audit: ((d.audit as ApiRecord[]) || []).map((entry) => ({
      ...entry, detail: JSON.stringify(entry.detail),
    })),
  };
}
export async function api(path: string, options?: RequestInit): Promise<unknown> {
  if (path === "config") return { intake: true, admin: true };
  if (path === "session") {
    // Remove credentials retained by older releases.
    localStorage.removeItem("fraudlens_admin_password");
    localStorage.removeItem("fraudlens_admin_email");
    if (!adminToken()) throw new Error("No active admin session.");
    return request("/v1/auth/session");
  }
  if (path === "logout") {
    const logoutToken = adminToken();
    try {
      await request("/v1/auth/logout", { method: "POST" });
    } finally {
      if (logoutToken === adminToken()) {
        sessionStorage.removeItem("fraudlens_admin_email");
        sessionStorage.removeItem("fraudlens_admin_token");
        imageUrls.forEach((url) => URL.revokeObjectURL(url));
        imageUrls.clear();
      }
    }
    return { ok: true };
  }
  if (path === "login" && options?.body) {
    const j = await request("/v1/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: options.body,
    });
    sessionStorage.setItem("fraudlens_admin_email", stringValue(j.user));
    sessionStorage.setItem("fraudlens_admin_token", stringValue(j.token));
    return { user: j.user, role:j.role };
  }
  if (path.startsWith("queue")) {
    const params = new URLSearchParams(path.split("?")[1] || "");
    if (!params.has("sort_by")) params.set("sort_by", "created_at");
    if (!params.has("sort_dir")) params.set("sort_dir", "desc");
    const j = await request("/v1/cases?" + params);
    const cases = await Promise.all(
      ((j.items as ApiRecord[] | undefined) || []).map(async (r) => {
        const thumbId = String(r.thumbnail_url || "").match(/\/v1\/images\/([^?]+)/)?.[1];
        return {
          id: stringValue(r.case_id),
          kind: stringValue(r.agent_type),
          name: stringValue(r.person_name || r.claimant_id),
          registration: stringValue(r.vehicle_registration),
          policy: stringValue(r.policy_number),
          garage: stringValue(r.garage_id),
          amount: Number(r.claim_amount || 0),
          status: stringValue(r.status) || "open",
          processingStatus: stringValue(r.processing_status) || 'not_recorded',
          outcome: stringValue(r.final_admin_action),
          recommendation: recommendation(stringValue(r.recommendation), stringValue(r.risk_band)),
          risk: band(stringValue(r.risk_band)),
          created_at: stringValue(r.created_at) || new Date().toISOString(),
          thumbnail: thumbId ? await apiImageUrl(thumbId) : "",
        };
      }),
    );
    return { cases, total: j.total, has_more: j.has_more, page: j.page, page_size: j.page_size };
  }
  if (path.startsWith("case?id="))
    return caseDetail(new URLSearchParams(path.slice(path.indexOf("?"))).get("id") || "");
  if (path === "submit" && options?.body instanceof FormData) {
    const j = await request('/v1/cases', { method: 'POST', body: mapFormData(options.body),
      headers: {'Idempotency-Key': String(options.body.get('submissionKey') || crypto.randomUUID())} }, 'customer');
    if (j.applicant_token) sessionStorage.setItem('fraudlens_applicant_' + j.case_id, String(j.applicant_token));
    if (j.job_id) sessionStorage.setItem('fraudlens_job_' + j.job_id, String(j.case_id));
    return { id: j.case_id, case_id: j.case_id, job_id: j.job_id, status: j.status, applicant_token: j.applicant_token };
  }
  if (path.startsWith("job?id=")) {
    const jobId = path.slice('job?id='.length);
    const caseId = sessionStorage.getItem('fraudlens_job_' + jobId) || '';
    return request('/v1/jobs/' + encodeURIComponent(jobId), {headers: {'X-Applicant-Token': applicantToken(caseId)}}, customerToken() ? 'customer' : 'public');
  }
  if (path.startsWith("track") && options?.body) {
    const b = JSON.parse(String(options.body));
    const qs = new URLSearchParams({
      case_id: b.id,
      registration_number: b.identifier,
      policy_number: b.identifier,
    });
    return publicCase(await request("/v1/track?" + qs,
      {headers:{'X-Applicant-Token': String(b.receipt || applicantToken(b.id))}}, customerToken() ? 'customer' : 'public'));
  }
  if (path === "action" && options?.body) {
    const b = JSON.parse(String(options.body));
    const action =
      b.action === "Reject"
        ? "reject"
        : b.action === "Request More Evidence"
          ? "request_more_evidence"
          : "approve";
    return request("/v1/cases/" + encodeURIComponent(b.id) + "/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        reason: b.reason,
        admin_id: adminEmail() || "admin",
        public_message: b.publicNarrative || null,
        requested_artifacts: b.requestedArtifacts || [],
        expected_revision: b.version,
        expected_run_id: b.reviewedRunId || null,
        expected_evidence_ids: b.reviewedEvidenceIds || null,
        manual_review_override: !!b.manualReviewOverride,
      }),
    });
  }
  if (path.startsWith("reprocess?id=")) {
    return request("/v1/cases/" + encodeURIComponent(path.slice("reprocess?id=".length)) + "/reprocess", { method: "POST" });
  }
  return request("/v1/" + path, options);
}
const imageUrls = new Map<string, string>();
export const applicantToken = (id: string) => sessionStorage.getItem('fraudlens_applicant_' + id) || '';
export async function submitAdditionalEvidence(id: string, requestId: string, files: File[], token: string) {
  const body = new FormData(); body.set('request_id', requestId);
  files.forEach(file => body.append('images', file));
  const result = await request('/v1/cases/' + encodeURIComponent(id) + '/evidence', {
    method: 'POST', body, headers: {'X-Applicant-Token': token},
  }, customerToken() ? 'customer' : 'public');
  sessionStorage.setItem('fraudlens_applicant_' + id, token);
  return result;
}
export async function historicalReport(id: string, snapshot: string) {
  return request('/v1/cases/' + encodeURIComponent(id) + '/report?snapshot_id=' + encodeURIComponent(snapshot));
}
const imageRequests = new Map<string,Promise<string>>();
export async function apiImageUrl(id: string, full = false) {
  const key = id + (full ? ':full' : ':thumb');
  const cached = imageUrls.get(key);
  if (cached) return cached;
  if (imageRequests.has(key)) return imageRequests.get(key)!;
  const token = adminToken();
  if (!token) return '';
  const pending = (async () => {
    const r = await fetch(API_BASE + '/v1/images/' + encodeURIComponent(id) + (full ? '' : '?thumb=1'), {headers: authHeaders()});
    if (!r.ok) return '';
    const blob = await r.blob();
    if (adminToken() !== token) return '';
    const url = URL.createObjectURL(blob); imageUrls.set(key,url); return url;
  })();
  imageRequests.set(key,pending);
  try { return await pending; }
  finally { if (imageRequests.get(key) === pending) imageRequests.delete(key); }
}
export const post = (path: string, body: unknown) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export function useConfig() {
  const [c, setC] = useState<{ intake: boolean; admin: boolean } | null>(null);
  useEffect(() => {
    api("config")
      .then((value) => setC(value as { intake: boolean; admin: boolean }))
      .catch(() => setC({ intake: false, admin: false }));
  }, []);
  return c;
}
export function Empty({
  title,
  text,
  icon = "file",
}: {
  title: string;
  text: string;
  icon?: string;
}) {
  return (
    <div className="empty">
      <Icon name={icon} size={36} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
