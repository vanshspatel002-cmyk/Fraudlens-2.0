import { useState, useEffect } from "react";
import { Icon, Empty, recommendations, api } from "./shared";
export type CaseRow = {
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
type FindingCountsResponse = {
  counts: Array<{ name: string; verdict: string; count: number }>;
};
export default function AdminOverview({
  rows,
  open,
  queue,
}: {
  rows: CaseRow[];
  open: (id: string) => void;
  queue: (kind?: string) => void;
}) {
  const [counts, setCounts] = useState<Array<{ name: string; verdict: string; count: number }>>([]),
    [countState, setCountState] = useState("loading");
  useEffect(() => {
    api("finding-counts")
      .then((j) => {
        setCounts((j as FindingCountsResponse).counts);
        setCountState("ready");
      })
      .catch(() => setCountState("error"));
  }, [rows]);
  const pending = rows.filter((r) => r.status === "open");
  const clear = rows.filter((r) => r.recommendation === "Clear").length;
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 13 + i);
    return d.toISOString().slice(0, 10);
  });
  const volume = days.map((day) => ({
    day,
    claims: rows.filter((r) => r.kind === "claims" && r.created_at.slice(0, 10) === day).length,
    underwriting: rows.filter((r) => r.kind === "underwriting" && r.created_at.slice(0, 10) === day)
      .length,
  }));
  const peak = Math.max(1, ...volume.map((d) => Math.max(d.claims, d.underwriting)));
  const recent = [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);
  const risk = ["Low", "Medium", "High", "Unrated"];
  const colors = ["#80ae96", "#d2b56f", "#bc91d3", "#666"];
  let offset = 0;
  const segments = risk.map((name, i) => {
    const n = rows.filter((r) => (r.risk || "Unrated") === name).length;
    const start = offset;
    offset += (n / Math.max(rows.length, 1)) * 100;
    return `${colors[i]} ${start}% ${offset}%`;
  });
  return (
    <>
      <section className="ops-banner">
        <div>
          <span className="ops-kicker">EVIDENCE OPERATIONS</span>
          <h2>Every case deserves clarity.</h2>
          <p>One shared memory. Two specialized agents. Human judgment at every decision.</p>
        </div>
        <button onClick={() => queue()}>
          Open case queue <Icon name="arrow" size={17} />
        </button>
      </section>
      <div className="ops-metrics">
        {[
          ["file", "Cases on this page", String(rows.length), "Use the queue to browse all cases"],
          ["clock", "Awaiting review", String(pending.length), "Open cases on this page"],
          [
            "check",
            "Clear recommendations",
            rows.length ? ((clear / rows.length) * 100).toFixed(1) + "%" : "—",
            "On this page; human decision required",
          ],
          [
            "shield",
            "Escalated to SIU",
            String(rows.filter((r) => r.recommendation === "Escalate to SIU").length),
            "On this page",
          ],
        ].map(([icon, label, value, caption]) => (
          <article key={label}>
            <div>
              <span>{label}</span>
              <Icon name={icon} size={18} />
            </div>
            <strong>{value}</strong>
            <small>{caption}</small>
          </article>
        ))}
      </div>
      <div className="ops-primary-grid">
        <section className="case-panel ops-volume">
          <div className="ops-panel-head">
            <div>
              <span className="ops-kicker">CASE INTAKE</span>
              <h2>Evidence coming in</h2>
            </div>
            <span className="ops-chip">Last 14 days · UTC</span>
          </div>
          <div className="ops-legend">
            <span>
              <i className="claims-dot" />
              Claims
            </span>
            <span>
              <i className="underwriting-dot" />
              Underwriting
            </span>
          </div>
          <div
            className="ops-chart"
            role="img"
            aria-label={
              "Daily case volume: " +
              volume
                .map((d) => `${d.day}: ${d.claims} claims, ${d.underwriting} underwriting`)
                .join("; ")
            }
          >
            {volume.map((d) => (
              <div
                className="ops-day"
                key={d.day}
                title={`${d.day} · ${d.claims} claims / ${d.underwriting} underwriting`}
              >
                <div>
                  <i style={{ height: `${(d.claims / peak) * 100}%` }} />
                  <i style={{ height: `${(d.underwriting / peak) * 100}%` }} />
                </div>
                <small>{d.day.slice(8)}</small>
              </div>
            ))}
          </div>
          {!volume.some((d) => d.claims + d.underwriting) && (
            <p className="ops-chart-note">No submissions in this period.</p>
          )}
        </section>
        <section className="case-panel ops-risk">
          <div className="ops-panel-head">
            <div>
              <span className="ops-kicker">REVIEW PRIORITY</span>
              <h2>Risk distribution</h2>
            </div>
            <Icon name="shield" size={20} />
          </div>
          <div
            className="ops-donut"
            style={{
              background: rows.length ? `conic-gradient(${segments.join(",")})` : "#292929",
            }}
            role="img"
            aria-label={risk
              .map((v) => `${v}: ${rows.filter((r) => (r.risk || "Unrated") === v).length}`)
              .join(", ")}
          >
            <div>
              <strong>{rows.length}</strong>
              <span>Total cases</span>
            </div>
          </div>
          <div className="ops-risk-list">
            {risk.map((v, i) => (
              <div key={v}>
                <span>
                  <i style={{ background: colors[i] }} />
                  {v}
                </span>
                <b>{rows.filter((r) => (r.risk || "Unrated") === v).length}</b>
              </div>
            ))}
          </div>
        </section>
      </div>
      <div className="ops-agent-grid">
        {["claims", "underwriting"].map((kind) => (
          <button key={kind} className={"ops-agent " + kind} onClick={() => queue(kind)}>
            <div className="ops-agent-icon">
              <Icon name={kind === "claims" ? "scan" : "shield"} size={27} />
            </div>
            <div>
              <span className="ops-kicker">
                {kind === "claims" ? "FIRST NOTICE OF LOSS" : "POLICY VERIFICATION"}
              </span>
              <h3>Agent {kind === "claims" ? "Recon" : "Sentinel"}</h3>
              <p>
                {rows.filter((r) => r.kind === kind && r.status === "open").length}{" "}
                awaiting review · {rows.filter((r) => r.kind === kind).length} total cases
              </p>
            </div>
            <Icon name="arrow" size={20} />
          </button>
        ))}
      </div>
      <div className="ops-secondary-grid">
        <section className="case-panel ops-recent">
          <div className="ops-panel-head">
            <div>
              <span className="ops-kicker">LATEST SUBMISSIONS</span>
              <h2>Recent cases</h2>
            </div>
            <button className="ops-text-button" onClick={() => queue()}>
              View all ↗
            </button>
          </div>
          {recent.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Vehicle / claimant</th>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <strong>{r.registration}</strong>
                        <small>{r.name}</small>
                      </td>
                      <td>
                        <span
                          className={"agent-tag " + (r.kind === "claims" ? "recon" : "sentinel")}
                        >
                          {r.kind === "claims" ? "Recon" : "Sentinel"}
                        </span>
                      </td>
                      <td>{r.status}</td>
                      <td>
                        <button
                          className="ops-text-button"
                          aria-label={"Review " + r.registration}
                          onClick={() => open(r.id)}
                        >
                          Open ↗
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="Your first case starts here"
              text="Accepted submissions will appear here with their evidence and review status."
            />
          )}
        </section>
        <section className="case-panel ops-recommendations">
          <div className="ops-panel-head">
            <div>
              <span className="ops-kicker">AGENT OUTPUTS</span>
              <h2>Recommendations</h2>
            </div>
          </div>
          {recommendations.map((v) => {
            const n = rows.filter((r) => r.recommendation === v).length;
            return (
              <div className="ops-rec" key={v}>
                <div>
                  <span>{v}</span>
                  <b>{n}</b>
                </div>
                <div>
                  <i style={{ width: `${(n / Math.max(rows.length, 1)) * 100}%` }} />
                </div>
              </div>
            );
          })}
          <p>Recommendations guide review. Neither agent can reject a case.</p>
        </section>
      </div>
      <section className="case-panel">
        <div className="ops-panel-head">
          <div>
            <span className="ops-kicker">ALL RECORDED FINDINGS</span>
            <h2>Evidence Battery results</h2>
          </div>
          <span className="ops-chip">Pass / Inconclusive / Concern</span>
        </div>
        {counts.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Pass</th>
                  <th>Inconclusive</th>
                  <th>Concern</th>
                </tr>
              </thead>
              <tbody>
                {[...new Set(counts.map((c) => c.name))].map((name) => (
                  <tr key={name}>
                    <td>{name}</td>
                    {["Pass", "Inconclusive", "Concern"].map((v) => (
                      <td key={v}>
                        {counts.find((c) => c.name === name && c.verdict === v)?.count || 0}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>
            {countState === "loading"
              ? "Loading recorded findings…"
              : countState === "error"
                ? "Findings counts could not be loaded. Refresh to try again."
                : "No findings recorded yet. Uncertainty is never counted as suspicion."}
          </p>
        )}
      </section>
      <section className="ops-assurance">
        <Icon name="lock" size={22} />
        <div>
          <h3>Accountability is part of the workflow.</h3>
          <p>
            *Straight-Through Processing is the share recommended Clear, not an autonomous approval
            rate. Final decisions remain human. Queue metrics cover the latest 2,000 cases at most.
          </p>
        </div>
      </section>
      <section className="case-panel ops-evaluation">
        <div>
          <span className="ops-kicker">EVALUATION</span>
          <h2>Baseline versus agentic performance</h2>
          <p>
            Measured false-positive rates and comparative results will appear when a verified
            evaluation dataset is connected.
          </p>
        </div>
        <span className="ops-chip">Not available</span>
      </section>
    </>
  );
}
