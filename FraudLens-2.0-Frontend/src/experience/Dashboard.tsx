import { useState, type FormEvent } from "react";
import { Logo, Icon, Mark, Empty, post } from "./shared";
import "./user-dashboard.css";
type UserCase = {
  id: string;
  kind: "claims" | "underwriting";
  status: string;
  outcome: string | null;
  publicNarrative: string;
  updatedAt: string;
};
const date = (s: string) =>
  new Date(s).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
export default function Dashboard() {
  const [tab, setTab] = useState("Overview"),
    [cases, setCases] = useState<UserCase[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [connect, setConnect] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [query, setQuery] = useState("");
  const current = cases.find((c) => c.id === selected);
  const attention = cases.filter((c) => c.status === "Additional evidence requested");
  const visible = cases.filter(
    (c) =>
      (tab !== "My claims" || c.kind === "claims") &&
      (tab !== "My underwriting" || c.kind === "underwriting") &&
      c.id.toLowerCase().includes(query.toLowerCase()),
  );
  async function link(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(e.currentTarget);
    try {
      const result = (await post("track", {
        id: String(form.get("id")).trim(),
        identifier: String(form.get("identifier")).trim(),
      })) as UserCase;
      setCases((prev) => [result, ...prev.filter((c) => c.id !== result.id)]);
      setSelected(result.id);
      setConnect(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function go(next: string) {
    setTab(next);
    setSelected(null);
    setConnect(false);
    setError("");
    setQuery("");
  }
  function openLink() {
    setConnect(true);
    setError("");
  }
  const caseList = (
    <section className="ud-panel ud-case-list">
      <div className="ud-panel-head">
        <div>
          <span className="ud-kicker">YOUR APPLICATIONS</span>
          <h2>{tab === "Overview" ? "Recent cases" : tab}</h2>
        </div>
        <span className="ud-chip">{visible.length} linked</span>
      </div>
      <label className="ud-search">
        <Icon name="search" size={18} />
        <input
          aria-label="Search linked cases"
          placeholder="Search by case ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {visible.length ? (
        <div className="ud-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Application</th>
                <th>Status</th>
                <th>Last updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.id}>
                  <td>
                    <button className="ud-case-id" onClick={() => setSelected(c.id)}>
                      {c.id}
                    </button>
                  </td>
                  <td>
                    <span className={"ud-tag " + c.kind}>
                      {c.kind === "claims" ? "Claims" : "Underwriting"}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        "ud-status " +
                        (c.outcome
                          ? "complete"
                          : c.status === "Additional evidence requested"
                            ? "attention"
                            : "")
                      }
                    >
                      {c.status}
                    </span>
                  </td>
                  <td>{date(c.updatedAt)}</td>
                  <td>
                    <button
                      className="ud-text-button"
                      onClick={() => setSelected(c.id)}
                      aria-label={"View " + c.id}
                    >
                      View ↗
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          icon="file"
          title={query ? "No matching cases" : "Your cases will appear here"}
          text={
            query
              ? "Try another case ID."
              : "Already applied? Link your case using the ID from your submission and your registration or policy number."
          }
        />
      )}
      <button className="ud-outline" onClick={openLink}>
        + Link a case
      </button>
    </section>
  );
  return (
    <div className="user-dashboard">
      <a className="skip" href="#user-main">
        Skip to dashboard
      </a>
      <header className="ud-header">
        <Logo />
        <span>YOUR WORKSPACE</span>
        <div>
          <a href="/">View website ↗</a>
          <button
            className="ud-avatar"
            aria-label="About case access"
            onClick={() => go("Help & guidance")}
          >
            <Icon name="user" size={19} />
          </button>
        </div>
      </header>
      <div className="ud-layout">
        <aside className="ud-sidebar">
          <span className="ud-kicker">MY DASHBOARD</span>
          {[
            ["Overview", "layers"],
            ["My claims", "scan"],
            ["My underwriting", "shield"],
            ["Updates", "clock"],
            ["Help & guidance", "file"],
          ].map(([name, icon]) => (
            <button
              key={name}
              className={tab === name && !current && !connect ? "active" : ""}
              onClick={() => go(name)}
            >
              <Icon name={icon} size={18} />
              {name}
              {name === "Updates" && attention.length > 0 && <b>{attention.length}</b>}
            </button>
          ))}
          <div className="ud-sidebar-bottom">
            <Icon name="lock" size={22} />
            <h3>Your case. Your privacy.</h3>
            <p>Only public case updates appear here. Investigation records stay private.</p>
            <small>Research prototype</small>
          </div>
        </aside>
        <main id="user-main" className="ud-main">
          <div className="ud-title">
            <div>
              <span>FraudLens 2.0 / Your dashboard</span>
              <h1>
                {connect
                  ? "Link your case"
                  : current
                    ? "Case overview"
                    : tab === "Overview"
                      ? "Your insurance, in view."
                      : tab}
              </h1>
            </div>
            <button className="ud-outline" onClick={openLink}>
              <Icon name="search" size={16} /> {current ? "Refresh case" : "Link a case"}
            </button>
          </div>
          {connect ? (
            <section className="ud-panel ud-connect">
              <div>
                <span className="ud-kicker">CASE-BASED ACCESS</span>
                <h2>A clear view of what’s next.</h2>
                <p>
                  Enter both details exactly as submitted. We’ll check them before showing your case
                  status.
                </p>
                <div className="ud-assurance">
                  <Icon name="lock" size={21} />
                  <p>
                    Linked cases are available during this visit only. Reloading or closing this
                    page clears them from the dashboard.
                  </p>
                </div>
              </div>
              <form onSubmit={link}>
                <label className="field">
                  <span>Case ID</span>
                  <input
                    name="id"
                    defaultValue={selected || ""}
                    required
                    maxLength={64}
                    autoComplete="off"
                    placeholder="Your submission case ID"
                  />
                </label>
                <label className="field">
                  <span>Registration or policy number</span>
                  <input
                    name="identifier"
                    required
                    maxLength={160}
                    autoComplete="off"
                    placeholder="The number on your application"
                  />
                </label>
                {error && (
                  <p className="ud-error" role="alert">
                    {error}
                  </p>
                )}
                <button className="ud-primary" disabled={busy}>
                  {busy ? "Checking your details…" : "View my case"}
                  <Icon name="arrow" size={18} />
                </button>
                <button type="button" className="ud-text-button" onClick={() => setConnect(false)}>
                  Cancel
                </button>
              </form>
            </section>
          ) : current ? (
            <>
              <button className="ud-text-button" onClick={() => setSelected(null)}>
                ← Back to dashboard
              </button>
              <section className={"ud-panel ud-case-heading " + current.kind}>
                <div>
                  <span className={"ud-tag " + current.kind}>
                    {current.kind === "claims"
                      ? "Agent Recon · Claims"
                      : "Agent Sentinel · Underwriting"}
                  </span>
                  <h2>{current.id}</h2>
                  <p>Last updated {date(current.updatedAt)}</p>
                </div>
                <span className={"ud-status " + (current.outcome ? "complete" : "")}>
                  {current.status}
                </span>
              </section>
              <div className="ud-detail-grid">
                <section className="ud-panel">
                  <div className="ud-panel-head">
                    <div>
                      <span className="ud-kicker">YOUR CASE JOURNEY</span>
                      <h2>Where things stand</h2>
                    </div>
                    <Icon name="clock" />
                  </div>
                  <ol className="ud-progress">
                    <li className="done">
                      <i>
                        <Icon name="check" size={15} />
                      </i>
                      <div>
                        <h3>Application received</h3>
                        <p>Your case has been registered.</p>
                      </div>
                    </li>
                    <li className={!current.outcome ? "now" : "done"}>
                      <i>{current.outcome ? <Icon name="check" size={15} /> : "2"}</i>
                      <div>
                        <h3>
                          {current.status === "Additional evidence requested"
                            ? "More evidence requested"
                            : "Human review"}
                        </h3>
                        <p>
                          {current.status === "Additional evidence requested"
                            ? "Read the reviewer’s update below for the next step."
                            : current.outcome
                              ? "A human reviewer has recorded a decision."
                              : "Your case is awaiting a human decision."}
                        </p>
                      </div>
                    </li>
                    <li className={current.outcome ? "done" : ""}>
                      <i>{current.outcome ? <Icon name="check" size={15} /> : "3"}</i>
                      <div>
                        <h3>
                          {current.outcome ? "Final outcome: " + current.outcome : "Final decision"}
                        </h3>
                        <p>
                          {current.outcome
                            ? "The outcome is shown as recorded by your reviewer."
                            : "A final outcome will appear once a human reviewer decides."}
                        </p>
                      </div>
                    </li>
                  </ol>
                </section>
                <section className="ud-panel">
                  <span className="ud-kicker">LATEST PUBLIC UPDATE</span>
                  <h2>
                    {current.status === "Additional evidence requested"
                      ? "Your next step"
                      : "A note on your case"}
                  </h2>
                  <p className="ud-narrative">
                    {current.publicNarrative ||
                      "No public explanation has been recorded yet. Your case status is shown above."}
                  </p>
                  {current.status === "Additional evidence requested" && (
                    <p className="ud-hint">
                      Use your insurer’s established submission channel to provide the requested
                      evidence, quoting this case ID. This dashboard does not accept additional
                      uploads.
                    </p>
                  )}
                  <button className="ud-outline ud-print" onClick={() => window.print()}>
                    <Icon name="file" size={17} />
                    Print status summary
                  </button>
                </section>
              </div>
              <div className="ud-assurance">
                <Icon name="shield" />
                <p>
                  Agents can recommend a next step. Only a human can approve or reject your case,
                  and rejection requires a stated reason.
                </p>
              </div>
              <button
                className="ud-text-button"
                onClick={() => {
                  setCases((prev) => prev.filter((c) => c.id !== current.id));
                  setSelected(null);
                }}
              >
                Remove from this dashboard
              </button>
              <p className="ud-hint">
                Removing a case here does not withdraw or delete your application.
              </p>
            </>
          ) : tab === "Help & guidance" ? (
            <>
              <section className="ud-panel">
                <span className="ud-kicker">A LITTLE CLARITY</span>
                <h2>Answers for your next step.</h2>
                {[
                  [
                    "Where do I find my case ID?",
                    "Your case ID appears after a successful application. Keep it with your registration or policy number to check progress.",
                  ],
                  [
                    "Can the AI reject my application?",
                    "No. Recon and Sentinel only recommend next steps. Only a human reviewer can reject a claim or application, with a written reason.",
                  ],
                  [
                    "How do I send additional evidence?",
                    "Read the public update on your case and use your insurer’s established submission channel. Quote your case ID. Additional uploads are not supported in this dashboard.",
                  ],
                  [
                    "Are my cases saved to an account?",
                    "This is a case-based workspace. Linked cases remain available during this visit only; re-enter your case details after a page reload. No account password is needed.",
                  ],
                  [
                    "What can I see here?",
                    "Your current status, final outcome when available, and public explanation. Internal findings, photos, risk assessments and agent reasoning are not exposed.",
                  ],
                ].map(([q, a]) => (
                  <details className="ud-faq" key={q}>
                    <summary>{q}</summary>
                    <p>{a}</p>
                  </details>
                ))}
              </section>
              <div className="ud-assurance">
                <Icon name="file" />
                <p>
                  For policy documents, settlement timing, or changes to your application, contact
                  your insurer through its official channel and quote your case ID.
                </p>
              </div>
            </>
          ) : tab === "Updates" ? (
            <section className="ud-panel">
              <div className="ud-panel-head">
                <div>
                  <span className="ud-kicker">LATEST KNOWN STATUS</span>
                  <h2>Updates from your cases</h2>
                </div>
                <span className="ud-chip">This visit</span>
              </div>
              {cases.length ? (
                [...cases]
                  .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
                  .map((c) => (
                    <article className="ud-update" key={c.id}>
                      <Icon
                        name={c.status === "Additional evidence requested" ? "file" : "clock"}
                        size={20}
                      />
                      <div>
                        <span className={"ud-tag " + c.kind}>
                          {c.kind === "claims" ? "Claims" : "Underwriting"}
                        </span>
                        <h3>{c.status}</h3>
                        <p>{c.publicNarrative || "No public explanation has been recorded yet."}</p>
                        <small>
                          {c.id} · {date(c.updatedAt)}
                        </small>
                        <button className="ud-text-button" onClick={() => setSelected(c.id)}>
                          View case ↗
                        </button>
                      </div>
                    </article>
                  ))
              ) : (
                <Empty
                  icon="clock"
                  title="Updates will appear here"
                  text="Link a case to see its latest public update. Refresh a case with your verification details to check for changes."
                />
              )}
            </section>
          ) : (
            <>
              {tab === "Overview" && (
                <>
                  <section className="ud-welcome">
                    <div>
                      <span className="ud-kicker">WELCOME TO YOUR DASHBOARD</span>
                      <h2>
                        Less uncertainty.
                        <br />
                        More clarity.
                      </h2>
                      <p>
                        Start an application, follow its progress, and know your next step—all in
                        one place.
                      </p>
                      <button className="ud-primary" onClick={openLink}>
                        Track an existing case <Icon name="arrow" size={18} />
                      </button>
                    </div>
                    <div className="ud-welcome-art" aria-hidden="true">
                      <div>
                        <Icon name="shield" size={58} />
                        <span>
                          HUMAN REVIEW.
                          <br />
                          AT EVERY DECISION.
                        </span>
                      </div>
                    </div>
                  </section>
                  <div className="ud-metrics">
                    {[
                      ["file", "Linked cases", cases.length, "In this visit"],
                      [
                        "clock",
                        "In review",
                        cases.filter(
                          (c) => !c.outcome && c.status !== "Additional evidence requested",
                        ).length,
                        "Awaiting a decision",
                      ],
                      ["eye", "Action needed", attention.length, "Additional evidence requested"],
                      [
                        "check",
                        "Decided",
                        cases.filter((c) => c.outcome).length,
                        "Human-reviewed outcomes",
                      ],
                    ].map(([icon, title, count, caption]) => (
                      <article key={String(title)}>
                        <div>
                          <span>{title}</span>
                          <Icon name={String(icon)} size={18} />
                        </div>
                        <strong>{count}</strong>
                        <small>{caption}</small>
                      </article>
                    ))}
                  </div>
                  <div className="ud-agent-grid">
                    {["claims", "underwriting"].map((kind) => (
                      <a key={kind} className={"ud-agent " + kind} href={"/apply/" + kind}>
                        <div>
                          <span className="ud-kicker">
                            {kind === "claims" ? "REPORT A LOSS" : "ISSUE OR RENEW A POLICY"}
                          </span>
                          <h2>{kind === "claims" ? "Start a claim" : "Verify your vehicle"}</h2>
                          <p>
                            {kind === "claims"
                              ? "Let Agent Recon help review the evidence."
                              : "Build a reliable baseline with Agent Sentinel."}
                          </p>
                          <span className="ud-agent-cta">
                            {kind === "claims" ? "Apply for Claims" : "Apply for Underwriting"}{" "}
                            <Icon name="arrow" size={17} />
                          </span>
                        </div>
                        <Mark kind={kind === "claims" ? "recon" : "sentinel"} />
                      </a>
                    ))}
                  </div>
                </>
              )}
              {attention.length > 0 && (
                <div className="ud-attention">
                  <Icon name="file" size={21} />
                  <div>
                    <h3>
                      {attention.length} {attention.length === 1 ? "case needs" : "cases need"} your
                      attention
                    </h3>
                    <p>A reviewer has requested additional evidence.</p>
                  </div>
                  <button className="ud-text-button" onClick={() => setSelected(attention[0].id)}>
                    View request ↗
                  </button>
                </div>
              )}
              {caseList}
              <div className="ud-bottom-grid">
                <section className="ud-panel">
                  <span className="ud-kicker">BEFORE YOU APPLY</span>
                  <h2>A little preparation goes a long way.</h2>
                  <ul className="ud-checklist">
                    <li>
                      <Icon name="check" size={16} />
                      Keep your policy and vehicle details ready.
                    </li>
                    <li>
                      <Icon name="check" size={16} />
                      Use clear, original photographs of the vehicle.
                    </li>
                    <li>
                      <Icon name="check" size={16} />
                      For underwriting: four corners, odometer and plate.
                    </li>
                    <li>
                      <Icon name="check" size={16} />
                      Save the case ID after you submit.
                    </li>
                  </ul>
                </section>
                <section className="ud-panel ud-trust">
                  <Icon name="shield" size={28} />
                  <h2>A person makes the decision.</h2>
                  <p>
                    Recon investigates. Sentinel verifies. Neither agent can reject your claim or
                    application.
                  </p>
                  <button className="ud-text-button" onClick={() => go("Help & guidance")}>
                    How your case is handled ↗
                  </button>
                </section>
              </div>
              <p className="ud-hint">
                Cases shown here are linked for this visit only. Reloading the page clears this
                view. Use “Link a case” to check the latest status again.
              </p>
            </>
          )}
          <div className="ud-footer">
            <span>FraudLens 2.0 · Your evidence, handled with care.</span>
            <small>Research prototype built for academic evaluation.</small>
          </div>
        </main>
      </div>
    </div>
  );
}
