import { useState, useEffect, type FormEvent } from "react";
import { Shell, Icon, post, applicantToken, submitAdditionalEvidence } from "./shared";
type TrackResult = {
  status: string;
  processingStatus?: string;
  evidenceRequest?: {request_id: string; artifacts: string[]; status: string};
  publicNarrative?: string;
  outcome?: string;
  latestAction?: string;
  updatedAt: string;
};
export default function Tracker() {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const [id, setId] = useState(""),
    [result, setResult] = useState<TrackResult | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [identifier, setIdentifier] = useState(''),
    [receipt, setReceipt] = useState(''),
    [evidenceFiles, setEvidenceFiles] = useState<File[]>([]),
    [success, setSuccess] = useState('');
  useEffect(() => {
    const caseId = new URLSearchParams(window.location.search).get('case') || '';
    setId(caseId); setReceipt(applicantToken(caseId));
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
    setIdentifier(identifier); setSuccess('');
    if (!identifier) {
      setError("Enter the registration or policy number used in the application.");
      setBusy(false);
      return;
    }
    try {
      setResult((await post("track", { id, identifier, receipt })) as TrackResult);
      setReceipt(old => old || applicantToken(id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function addEvidence(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setError(''); setSuccess('');
    if (!result?.evidenceRequest || !receipt.trim() || !evidenceFiles.length) {
      setError('Enter the private access receipt and select the requested photographs.'); return;
    }
    setBusy(true);
    try {
      await submitAdditionalEvidence(id, result.evidenceRequest.request_id, evidenceFiles, receipt.trim());
      setEvidenceFiles([]); setSuccess('Additional evidence accepted. Original evidence and previous decisions are preserved. Analysis is queued.');
      setResult((await post('track', {id, identifier, receipt})) as TrackResult);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <Shell>
      <section className="tracker wrap">
        <Icon name="search" size={34} />
        <h1>Track your case.</h1>
        <p>Your status, clearly explained.</p>
        <form method="post" onSubmit={submit}>
          <label className="field">
            <span>Case ID</span>
            <input
              value={id}
              onChange={(e) => {setId(e.target.value); setReceipt(applicantToken(e.target.value));}}
              required
              maxLength={64}
              placeholder="Enter your case ID"
            />
          </label>
          <label className="field"><span>Private access receipt (or sign in to your account)</span>
            <input aria-label="Tracking access receipt" value={receipt} onChange={e=>setReceipt(e.target.value)} autoComplete="off" maxLength={256} />
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
          <button className="track-submit" disabled={!hydrated || busy}>
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
            <h2>{result.status.replaceAll('_', ' ')}</h2>
            {result.processingStatus && <p>Analysis: {result.processingStatus}</p>}
            <p>
              {result.publicNarrative ||
                "Your case is awaiting review. No final decision has been recorded."}
            </p>
            {result.latestAction && (
              <p>
                <strong>Latest reviewer action:</strong> {result.latestAction}
              </p>
            )}
            {result.evidenceRequest && <form onSubmit={addEvidence}>
              <h3>Requested photographs</h3>
              <ul>{result.evidenceRequest.artifacts.map(item => <li key={item}>{item}</li>)}</ul>
              <label className="field"><span>Private evidence access receipt</span>
                <input aria-label="Private evidence access receipt" value={receipt} onChange={e => setReceipt(e.target.value)} required autoComplete="off" />
              </label>
              <label className="field"><span>Additional photographs (JPEG, PNG or WebP; up to 5 MB each)</span>
                <input type="file" accept="image/jpeg,image/png,image/webp" multiple required
                  onChange={e => setEvidenceFiles(Array.from(e.target.files || []))} />
              </label>
              <button disabled={busy} type="submit">{busy ? 'Uploading...' : 'Submit requested evidence'}</button>
            </form>}
            {success && <p role="status">{success}</p>}
            <small>Status checked: {new Date(result.updatedAt).toLocaleString()}</small>
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
