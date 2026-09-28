import { useState, useEffect, type FormEvent } from "react";
import { Shell, Icon, post } from "./shared";
type TrackResult = {
  status: string;
  publicNarrative?: string;
  outcome?: string;
  updatedAt: string;
};
export default function Tracker() {
  const [id, setId] = useState(""),
    [result, setResult] = useState<TrackResult | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setId(new URLSearchParams(window.location.search).get("case") || "");
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setResult(null);
    setError("");
    if (!id.trim()) {
      setError("Enter your case ID.");
      return;
    }
    setBusy(true);
    const f = new FormData(e.currentTarget);
    const identifier = String(f.get("identifier") || "").trim();
    if (!identifier) {
      setError("Enter the registration or policy number used in the application.");
      setBusy(false);
      return;
    }
    try {
      setResult((await post("track", { id, identifier })) as TrackResult);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Shell>
      <section className="tracker wrap">
        <Icon name="search" size={34} />
        <h1>Track your case.</h1>
        <p>Your status, clearly explained.</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>Case ID</span>
            <input
              value={id}
              onChange={(e) => setId(e.target.value)}
              required
              maxLength={64}
              placeholder="Enter your case ID"
            />
          </label>
          <label className="field">
            <span>Registration or policy number</span>
            <input
              name="identifier"
              required
              maxLength={160}
              placeholder="The number used in your application"
            />
          </label>
          <button className="track-submit" disabled={busy}>
            {busy ? "Checking…" : "Check status"}
            <Icon name="arrow" size={18} />
          </button>
        </form>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {busy && (
          <section className="tracker-result" aria-live="polite">
            <span>CHECKING</span>
            <h2>Looking up your case</h2>
            <p>We are verifying the case ID against the registration or policy number.</p>
          </section>
        )}
        {result && (
          <section className="tracker-result" aria-live="polite">
            <span>CASE STATUS</span>
            <h2>{result.status}</h2>
            <p>
              {result.publicNarrative ||
                "Your case is awaiting review. No final decision has been recorded."}
            </p>
            {result.outcome && (
              <p>
                <strong>Final outcome:</strong> {result.outcome}
              </p>
            )}
            <small>Last updated: {new Date(result.updatedAt).toLocaleString()}</small>
          </section>
        )}
        <p>
          <a href="/dashboard">Open your user dashboard ↗</a>
        </p>
        <div className="tracker-privacy">
          <Icon name="lock" size={18} />
          <p>
            Your evidence stays private. This tracker shows status and the final outcome, never
            investigation findings or the Agent Trace.
          </p>
        </div>
      </section>
    </Shell>
  );
}
