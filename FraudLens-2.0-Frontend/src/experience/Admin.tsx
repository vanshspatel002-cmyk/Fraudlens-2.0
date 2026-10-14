import EvidenceViewer from "./EvidenceViewer";
import AdminOverview from "./AdminOverview";
import "./admin-workspace.css";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Logo,
  Icon,
  Empty,
  api,
  post,
  checks,
  recommendations,
  categories,
  useConfig,
} from "./shared";
const adminChecks = checks
  .map((c) => {
    const a = [...c];
    if (a[0] === "Case Memory similarity" || a[0] === "EXIF metadata") a[2] = "Both";
    if (a[0] === "External corpus search") a[1] = "History";
    if (a[0] === "View completeness") a[1] = "Identity";
    return a;
  })
  .concat([
    [
      "AI-Generation Detection",
      "Provenance",
      "Both",
      "Screens for synthetic images.",
      "Zero weight: unreliable on the project corpus; recorded, never acted on.",
    ],
    [
      "Digital Edit Detection",
      "Provenance",
      "Both",
      "Screens for splicing or retouching.",
      "Zero weight: could not reliably distinguish edited and untouched images on the project corpus.",
    ],
  ]);
type Row = {
  id: string;
  kind: string;
  name: string;
  registration: string;
  policy: string;
  garage: string;
  amount: number;
  status: string;
  recommendation: string;
  risk: string;
  created_at: string;
  thumbnail: string;
};
type CaseImage = { id: string; src: string; label: string };
type TraceEntry = {
  type: string;
  title?: string;
  summary?: string;
  explanation?: string;
  tool?: string;
  input?: unknown;
  result?: unknown;
};
type AuditEntry = {
  created_at: string;
  actor: string;
  event: string;
  detail: string;
};
type Finding = {
  id: string;
  check: string;
  category: string;
  verdict: string;
  confidence: number;
  explanation: string;
  attributed_to?: string;
  evidence?: unknown;
};
type CaseDetail = Row & {
  trace: TraceEntry[];
  audit: AuditEntry[];
  images: CaseImage[];
  findings: Finding[];
  declaration: Record<string, unknown>;
  requestedEvidence: string[];
  citedFindings: string[];
  processing?: { status?: string; stage?: string; detail?: string };
  analysisFallback?: boolean;
  narrative?: string;
  outcome?: string;
  reason?: string;
  admin?: string;
  updated_at?: string;
  version?: string;
};
const money = (n: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n);
export default function Admin() {
  const config = useConfig();
  const [user, setUser] = useState<string | null>(null),
    [tab, setTab] = useState("Overview"),
    [rows, setRows] = useState<Row[]>([]),
    [detail, setDetail] = useState<CaseDetail | null>(null),
    [detailTab, setDetailTab] = useState("Evidence"),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [sort, setSort] = useState("Newest first"),
    [filters, setFilters] = useState<Record<string, string>>({}),
    [lightbox, setLightbox] = useState<CaseImage | null>(null),
    [humanAction, setHumanAction] = useState("Approve"),
    [total, setTotal] = useState(0),
    [hasMore, setHasMore] = useState(false);
  useEffect(() => {
    api("session")
      .then((j) => setUser((j as { user: string }).user))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!user) return;
    load();
    const timer = window.setInterval(() => { if (!document.hidden) load(false); }, 10000);
    return () => window.clearInterval(timer);
  }, [user, page, search, filters, sort]);
  useEffect(() => {
    setPage(1);
  }, [search, filters, sort]);
  async function load(showLoading = true) {
    if (showLoading) setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (search) params.set("search", search);
      if (filters.kind) params.set("agent_type", filters.kind);
      if (filters.status) params.set("status", filters.status);
      if (filters.garage) params.set("garage_id", filters.garage);
      if (filters.from) params.set("date_from", new Date(filters.from).toISOString());
      if (filters.to) params.set("date_to", new Date(filters.to).toISOString());
      if (filters.min) params.set("amount_min", filters.min);
      if (filters.max) params.set("amount_max", filters.max);
      if (filters.risk)
        params.set(
          "risk_band",
          filters.risk === "Low"
            ? "clear"
            : filters.risk === "Medium"
              ? "desk_review"
              : filters.risk === "High"
                ? "escalate_siu"
                : "",
        );
      if (filters.recommendation)
        params.set(
          "recommendation",
          filters.recommendation === "Clear"
            ? "approve"
            : filters.recommendation === "Request Additional Evidence"
              ? "request_evidence"
              : "escalate",
        );
      params.set("sort_by", sort === "Amount high to low" ? "claim_amount" : "created_at");
      params.set("sort_dir", sort === "Oldest first" ? "asc" : "desc");
      const j = (await api("queue?" + params.toString())) as {
        cases: Row[];
        total?: number;
        has_more?: boolean;
      };
      setRows(j.cases);
      setTotal(j.total || j.cases.length);
      setHasMore(!!j.has_more);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    const f = new FormData(e.currentTarget);
    setLoading(true);
    try {
      const j = (await post("login", {
        email: f.get("email"),
        password: f.get("password"),
      })) as { user: string };
      setUser(j.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function open(id: string) {
    setError("");
    setLoading(true);
    try {
      setDetail((await api("case?id=" + encodeURIComponent(id))) as CaseDetail);
      setDetailTab(tab === "Reports" ? "Report" : "Evidence");
      setHumanAction("Approve");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function retryAnalysis() {
    if (!detail) return;
    setLoading(true);
    setError("");
    try {
      await api("reprocess?id=" + detail.id);
      await open(detail.id);
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  const filtered = rows;
  const metrics = [
    ["Matching cases", total],
    ["Awaiting review", rows.filter((r) => r.status === "open").length],
    [
      "Clear recommendations on this page",
      rows.length
        ? ((100 * rows.filter((r) => r.recommendation === "Clear").length) / rows.length).toFixed(
            1,
          ) + "%"
        : "Not measured",
    ],
    ["High risk", rows.filter((r) => r.risk === "High").length],
  ];
  async function action(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!detail) return;
    setError("");
    const f = new FormData(e.currentTarget);
    if (f.get("action") !== "Approve" && !String(f.get("reason") || "").trim()) {
      setError("A written reason is required for this decision.");
      return;
    }
    setLoading(true);
    try {
      await post("action", {
        id: detail.id,
        version: detail.version,
        action: f.get("action"),
        reason: f.get("reason"),
        publicNarrative: f.get("publicNarrative"),
      });
      await open(detail.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="admin">
      <header className="admin-header">
        <Logo />
        <span className="workspace-label">REVIEW WORKSPACE</span>
        <div>
          <a href="/">View website ↗</a>
          {user && (
            <button
              onClick={async () => {
                try {
                  await post("logout", {});
                  setUser(null);
                  setRows([]);
                  setDetail(null);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <div className="admin-layout">
        <aside className="admin-sidebar">
          <span>WORKSPACE</span>
          {[
            "Overview",
            "Case queue",
            "Claims",
            "Underwriting",
            "Reports",
            "Checks reference",
            "Garage analysis",
          ].map((t, i) => (
            <button
              key={t}
              className={tab === t && !detail ? "selected" : ""}
              onClick={() => {
                setTab(t);
                setDetail(null);
                setSearch("");
                setFilters(
                  t === "Claims"
                    ? { kind: "claims" }
                    : t === "Underwriting"
                      ? { kind: "underwriting" }
                      : {},
                );
              }}
            >
              <Icon
                name={["layers", "file", "scan", "shield", "file", "eye", "car"][i]}
                size={19}
              />
              {t}
            </button>
          ))}
          <div className="sidebar-note">
            <Icon name="shield" size={22} />
            <p>
              Agents recommend.
              <br />
              Humans decide.
            </p>
            <small>Research prototype</small>
            <div className="ops-user">
              <Icon name="user" size={17} />
              <span>{user || "Protected workspace"}</span>
            </div>
          </div>
        </aside>
        <main className="admin-main">
          <div className="admin-title">
            <div>
              <span>FraudLens 2.0 / {detail ? "Case detail" : tab}</span>
              <h1>
                {detail
                  ? detail.registration
                  : !user
                    ? "Review workspace"
                    : tab === "Overview"
                      ? "Operations overview"
                      : tab}
              </h1>
            </div>
            {user && (
              <button onClick={() => (detail ? open(detail.id) : load())}>
                <Icon name="clock" size={17} /> Refresh
              </button>
            )}
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {!user ? (
            <>
              <div className="admin-login">
                <div>
                  <Icon name="lock" size={31} />
                  <span className="ops-kicker">AUTHORIZED REVIEWERS ONLY</span>
                  <h2>
                    Evidence first.
                    <br />
                    Your judgment, next.
                  </h2>
                  <p>
                    A dedicated workspace for claims investigation, underwriting verification, and
                    accountable human decisions.
                  </p>
                  <div className="ops-login-agents">
                    <span className="agent-tag recon">Agent Recon · Claims</span>
                    <span className="agent-tag sentinel">Agent Sentinel · Underwriting</span>
                  </div>
                  {config && !config.admin && (
                    <div className="notice">
                      Admin access is awaiting owner configuration. No default credentials are
                      enabled.
                    </div>
                  )}
                </div>
                <form onSubmit={login}>
                  <label className="field">
                    <span>Admin email</span>
                    <input name="email" type="email" autoComplete="username" required />
                  </label>
                  <label className="field">
                    <span>Password</span>
                    <input
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      required
                    />
                  </label>
                  <button className="admin-signin" disabled={loading}>
                    {loading ? "Signing in…" : "Sign in"}
                    <Icon name="arrow" size={17} />
                  </button>
                </form>
              </div>
              <div className="admin-preview">
                <div className="table-toolbar">
                  <h2>Case workspace</h2>
                  <span>Private access</span>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {["Case", "Agent", "Registration", "Recommendation", "Risk", "Status"].map(
                          (t) => (
                            <th key={t}>{t}</th>
                          ),
                        )}
                      </tr>
                    </thead>
                  </table>
                </div>
                <Empty
                  icon="lock"
                  title="Your case queue is protected"
                  text="Sign in to view assigned cases and record an accountable human decision."
                />
              </div>
            </>
          ) : detail ? (
            <>
              <button className="back-link" onClick={() => setDetail(null)}>
                ← Back to case queue
              </button>
              <div className="case-meta">
                <span className={"agent-tag " + (detail.kind === "claims" ? "recon" : "sentinel")}>
                  Agent {detail.kind === "claims" ? "Recon" : "Sentinel"}
                </span>
                <span>{detail.id}</span>
                <span>{detail.status}</span>
              </div>
              <div className="detail-tabs">
                {["Evidence", "Agent Trace", "Report", "Audit log"].map((t) => (
                  <button
                    key={t}
                    className={t === detailTab ? "selected" : ""}
                    onClick={() => setDetailTab(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
              {detailTab === "Agent Trace" ? (
                <section className="trace">
                  {detail.trace.length ? (
                    detail.trace.map((t, i) => (
                      <article key={i}>
                        <span>{i + 1}</span>
                        <div>
                          <small>{t.type.toUpperCase()}</small>
                          <h2>{t.title || t.tool || "Evidence assessment"}</h2>
                          <p>{t.summary || t.explanation}</p>
                          {t.input ? <pre>{JSON.stringify(t.input, null, 2)}</pre> : null}
                          {t.result ? <pre>{JSON.stringify(t.result, null, 2)}</pre> : null}
                        </div>
                      </article>
                    ))
                  ) : (
                    <Empty
                      title="No completed reasoning steps"
                      text="Only completed, recorded steps appear here. Service failures are recorded separately in the audit log."
                    />
                  )}
                </section>
              ) : detailTab === "Audit log" ? (
                <div className="audit-list">
                  {detail.audit.map((a, i) => (
                    <article key={i}>
                      <small>
                        {new Date(a.created_at).toLocaleString()} · {a.actor}
                      </small>
                      <h3>{a.event}</h3>
                      <p>{a.detail}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <div
                  className={
                    "case-layout " +
                    (detail.kind === "claims" ? "recon " : "sentinel ") +
                    (detailTab === "Report" ? "print-report" : "")
                  }
                >
                  <div>
                    <section className="case-panel">
                      <div className="panel-title">
                        <h2>Declaration</h2>
                        {detailTab === "Report" && (
                          <button onClick={() => window.print()}>Print report</button>
                        )}
                      </div>
                      <dl className="declaration">
                        {Object.entries(detail.declaration)
                          .filter(([k, v]) => v && k !== "consent")
                          .map(([k, v]) => (
                            <div key={k}>
                              <dt>{k.replace(/([A-Z])/g, " $1")}</dt>
                              <dd>{String(v)}</dd>
                            </div>
                          ))}
                      </dl>
                    </section>
                    <section className="case-panel">
                      <h2>Vehicle photographs</h2>
                      <div className="image-gallery">
                        {detail.images.map((im) => (
                          <button key={im.id} onClick={() => setLightbox(im)}>
                            <img src={im.src} alt={im.label} />
                            <span>{im.label}</span>
                          </button>
                        ))}
                      </div>
                    </section>
                    <section className="case-panel">
                      <h2>Evidence Battery</h2>
                      {categories.map((cat) => (
                        <details open key={cat} className="finding-group">
                          <summary>
                            {cat}
                            <span>{detail.findings.filter((f) => f.category === cat).length}</span>
                          </summary>
                          {detail.findings
                            .filter((f) => f.category === cat)
                            .map((f) => (
                              <article key={f.id}>
                                <div className="finding-title">
                                  <h3>{f.check}</h3>
                                  <span>{f.verdict}</span>
                                </div>
                                <p>{f.explanation}</p>
                                <small>
                                  {Math.round(f.confidence * 100)}% confidence · attributed_to:{" "}
                                  {f.attributed_to} · {f.id}
                                </small>
                                {f.evidence ? (
                                  <pre>{JSON.stringify(f.evidence, null, 2)}</pre>
                                ) : null}
                              </article>
                            ))}
                        </details>
                      ))}
                      {!detail.findings.length && (
                        <p>No findings have been recorded. This is not a clean result.</p>
                      )}
                    </section>
                  </div>
                  <aside>
                    <section className="recommendation-panel">
                      <span>THE AGENT'S ASSESSMENT</span>
                      <h2>{detail.recommendation || "Awaiting analysis"}</h2>
                      <p>
                        {detail.narrative ||
                          "A human review is required. No analysis narrative has been recorded."}
                      </p>
                      {detail.requestedEvidence?.length > 0 && (
                        <>
                          <h3>Requested evidence</h3>
                          <ul>
                            {detail.requestedEvidence.map((s: string) => (
                              <li key={s}>{s}</li>
                            ))}
                          </ul>
                        </>
                      )}
                      {detail.citedFindings?.length > 0 && (
                        <p>Cited findings: {detail.citedFindings.join(", ")}</p>
                      )}
                      {detail.analysisFallback && <p role="status">Automated adjudication did not complete. This is a fallback for human review, not a model assessment.</p>}
                      {detail.processing && <p role="status">Analysis: {detail.processing.status} · {detail.processing.stage}<br />{detail.processing.detail}</p>}
                      <button type="button" disabled={loading || ["queued", "running"].includes(detail.processing?.status || "")} onClick={retryAnalysis}>Retry analysis</button>
                      <button type="button" disabled={loading} onClick={() => open(detail.id)}>Refresh case</button>
                      <small>This is a recommendation, not a final decision. Confidence values are heuristic scores, not calibrated probabilities of fraud.</small>
                    </section>
                    <section className="action-panel">
                      <span>YOUR DECISION</span>
                      <h2>Human admin action</h2>
                      <p>
                        Record the accountable outcome separately from the agent's assessment above.
                      </p>
                      {detail.outcome && (
                        <p>
                          Recorded: <strong>{detail.outcome}</strong>
                          <br />
                          {detail.reason}
                          <br />
                          <small>
                            {detail.admin} · {detail.updated_at}
                          </small>
                        </p>
                      )}
                      <form onSubmit={action}>
                        <label className="field">
                          <span>Action</span>
                          <select
                            name="action"
                            required
                            value={humanAction}
                            onChange={(e) => setHumanAction(e.target.value)}
                          >
                            <option>Approve</option>
                            <option>Reject</option>
                            <option>Request More Evidence</option>
                          </select>
                        </label>
                        <label className="field">
                          <span>Written reason / requested evidence</span>
                          <textarea
                            name="reason"
                            required={humanAction !== "Approve"}
                            maxLength={3000}
                            rows={4}
                          />
                          <small>Required for Reject and Request More Evidence.</small>
                        </label>
                        <label className="field">
                          <span>Public explanation *</span>
                          <textarea name="publicNarrative" required maxLength={1500} rows={3} />
                          <small>
                            Visible in the tracker. Do not include private findings, evidence or
                            investigation details.
                          </small>
                        </label>
                        <button className="record-action" disabled={loading}>
                          {loading ? "Recording…" : "Record human decision"}
                        </button>
                      </form>
                    </section>
                  </aside>
                </div>
              )}
            </>
          ) : ["Case queue", "Claims", "Underwriting", "Reports"].includes(tab) ? (
            <>
              {tab === "Reports" && (
                <div className="ops-assurance">
                  <Icon name="file" />
                  <div>
                    <h3>Case reports</h3>
                    <p>Open a case to print or save its full report as a PDF.</p>
                  </div>
                </div>
              )}
              <div className="queue-tools">
                <label className="search-input">
                  <Icon name="search" size={19} />
                  <input
                    aria-label="Search cases"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search case ID, registration, policy or claimant"
                  />
                </label>
                <select
                  aria-label="Sort cases"
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                >
                  {["Newest first", "Oldest first", "Amount high to low"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </div>
              <details className="filter-box">
                <summary>
                  Filter cases <span>{Object.values(filters).filter(Boolean).length} active</span>
                </summary>
                <div className="filters">
                  {[
                    ["kind", "Agent", ["claims", "underwriting"]],
                    ["risk", "Risk band", ["Low", "Medium", "High", "Unrated"]],
                    [
                      "status",
                      "Status",
                      ["Awaiting review", "Additional evidence requested", "Decided"],
                    ],
                    ["recommendation", "Recommendation", recommendations],
                    ["garage", "Garage", [...new Set(rows.map((r) => r.garage).filter(Boolean))]],
                  ].map(([key, label, opts]) => (
                    <label key={String(key)} className="field">
                      <span>{String(label)}</span>
                      <select
                        disabled={
                          String(key) === "kind" && ["Claims", "Underwriting"].includes(tab)
                        }
                        value={filters[String(key)] || ""}
                        onChange={(e) => setFilters({ ...filters, [String(key)]: e.target.value })}
                      >
                        <option value="">All</option>
                        {(opts as string[]).map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </label>
                  ))}
                  {[
                    ["from", "From date", "date"],
                    ["to", "To date", "date"],
                    ["min", "Minimum amount", "number"],
                    ["max", "Maximum amount", "number"],
                  ].map(([key, label, type]) => (
                    <label className="field" key={key}>
                      <span>{label}</span>
                      <input
                        type={type}
                        value={filters[key] || ""}
                        onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
                      />
                    </label>
                  ))}
                  <button
                    onClick={() => {
                      setFilters(
                        tab === "Claims"
                          ? { kind: "claims" }
                          : tab === "Underwriting"
                            ? { kind: "underwriting" }
                            : {},
                      );
                      setSearch("");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              </details>
              <div className="case-table">
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {[
                          "Evidence",
                          "Case / claimant",
                          "Agent",
                          "Vehicle",
                          "Claim amount",
                          "Recommendation",
                          "Risk",
                          "Status",
                        ].map((t) => (
                          <th key={t}>{t}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((r) => (
                        <tr key={r.id}>
                          <td>
                            {r.thumbnail ? (
                              <img className="thumb" src={r.thumbnail} alt="Vehicle evidence" />
                            ) : (
                              <Icon name="car" />
                            )}
                          </td>
                          <td>
                            <button className="case-open" onClick={() => open(r.id)}>
                              {r.id.slice(0, 15)}…
                            </button>
                            <small>{r.name}</small>
                          </td>
                          <td>
                            <span
                              className={
                                "agent-tag " + (r.kind === "claims" ? "recon" : "sentinel")
                              }
                            >
                              {r.kind === "claims" ? "Recon" : "Sentinel"}
                            </span>
                          </td>
                          <td>
                            {r.registration}
                            <small>{r.policy}</small>
                          </td>
                          <td>{r.kind === "claims" ? money(r.amount) : "Not applicable"}</td>
                          <td>{r.recommendation || "Pending"}</td>
                          <td>
                            <span className={"risk risk-" + r.risk.toLowerCase()}>{r.risk}</span>
                          </td>
                          <td>
                            {r.status}
                            <small>{new Date(r.created_at).toLocaleDateString()}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!filtered.length && (
                  <Empty
                    title={
                      loading
                        ? "Loading cases…"
                        : rows.length
                          ? "No matching cases"
                          : "No cases received yet"
                    }
                    text={
                      rows.length
                        ? "Adjust your search or filters."
                        : "Accepted submissions will appear here. No sample cases or fabricated findings are shown."
                    }
                  />
                )}
                <div className="pagination">
                  <span>{total} cases</span>
                  <button disabled={page === 1} onClick={() => setPage(page - 1)}>
                    Previous
                  </button>
                  <span>Page {page}</span>
                  <button disabled={!hasMore} onClick={() => setPage(page + 1)}>
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : tab === "Overview" ? (
            <AdminOverview
              rows={rows}
              open={open}
              queue={(kind) => {
                setTab(
                  kind === "claims"
                    ? "Claims"
                    : kind === "underwriting"
                      ? "Underwriting"
                      : "Case queue",
                );
                setFilters(kind ? { kind } : {});
                setSearch("");
              }}
            />
          ) : tab === "Checks reference" ? (
            <section className="case-panel">
              <h2>Deterministic Evidence Battery</h2>
              <p>
                AI-Generation Detection and Digital Edit Detection are held at zero weight. Other
                weights and measured reliability are unpublished. A Concern is a review signal, not
                a fraud verdict.
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Category</th>
                      <th>Agent</th>
                      <th>Weight / reliability</th>
                      <th>Known limitation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminChecks.map(([title, cat, agent, , limit]) => (
                      <tr key={title}>
                        <td>{title}</td>
                        <td>{cat}</td>
                        <td>{agent}</td>
                        <td>
                          {["AI-Generation Detection", "Digital Edit Detection"].includes(title)
                            ? "0 · excluded from decisions"
                            : "Not published"}
                        </td>
                        <td>{limit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : (
            <Garage rows={rows} />
          )}
        </main>
      </div>
      {lightbox && <EvidenceViewer image={lightbox} onClose={() => setLightbox(null)} />}
    </div>
  );
}
function Garage({ rows }: { rows: Row[] }) {
  const [garage, setGarage] = useState("");
  const all = rows.filter((r) => r.kind === "claims"),
    selected = all.filter((r) => r.garage === garage),
    band = (r: Row) => r.amount >= 40000 && r.amount < 50000,
    percent = (rs: Row[]) =>
      rs.length ? ((100 * rs.filter(band).length) / rs.length).toFixed(1) + "%" : "No data";
  return (
    <section className="case-panel">
      <h2>Garage-level claim patterns</h2>
      <p>
        Threshold Gaming describes a garage's distribution, never an accusation against an
        individual claimant. This view uses a transparent ₹40,000 to ₹49,999 exploratory band; it
        does not establish misconduct.
      </p>
      <label className="field">
        <span>Garage</span>
        <select value={garage} onChange={(e) => setGarage(e.target.value)}>
          <option value="">Select a garage</option>
          {[...new Set(all.map((r) => r.garage).filter(Boolean))].map((g) => (
            <option key={g}>{g}</option>
          ))}
        </select>
      </label>
      {!garage ? (
        <Empty
          icon="car"
          title="Choose a garage"
          text="Distributions become available as real claims are received."
        />
      ) : (
        <>
          <div className="metric-grid">
            <article>
              <span>Garage claims</span>
              <strong>{selected.length}</strong>
            </article>
            <article>
              <span>Garage sub-threshold band</span>
              <strong>{percent(selected)}</strong>
            </article>
            <article>
              <span>Population band baseline</span>
              <strong>{percent(all)}</strong>
            </article>
          </div>
          <h3>Claim-value distribution</h3>
          {[
            [0, 20000],
            [20000, 40000],
            [40000, 50000],
            [50000, 100000],
            [100000, Infinity],
          ].map(([min, max]) => (
            <div className="bar-row" key={min}>
              <span>
                {money(min)} {max === Infinity ? "+" : "to " + money(max - 1)}
              </span>
              <div>
                <i
                  style={{
                    width:
                      (100 * selected.filter((r) => r.amount >= min && r.amount < max).length) /
                        Math.max(selected.length, 1) +
                      "%",
                  }}
                />
              </div>
              <b>{selected.filter((r) => r.amount >= min && r.amount < max).length}</b>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
