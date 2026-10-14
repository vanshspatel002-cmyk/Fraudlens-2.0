import { useEffect, useRef } from 'react';

export default function HistoricalReport({ text, close }: {text: string; close: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const report = JSON.parse(text) as Record<string, unknown>;
  const agent = (report.agent_recommendation || {}) as Record<string, unknown>;
  const action = (report.admin_action || {}) as Record<string, unknown>;
  const declaration = (report.declaration || {}) as Record<string, unknown>;
  const findings = Object.values((report.findings_by_category || {}) as Record<string, Record<string, unknown>[]>).flat();
  return <dialog ref={dialog} aria-label="Historical report" className="report-history-dialog" onCancel={close}>
    <div className="report-history-controls"><button onClick={close}>Close historical report</button><button onClick={() => window.print()}>Print saved report</button></div>
    <h2>FraudLens saved report</h2>
    <p>Case: {String(report.case_id)} · Processing run: {String(report.run_id || 'legacy')}<br />Policy: {String(report.policy_version || 'unrecorded')}</p>
    <h3>Declaration at this report version</h3>
    <dl>{Object.entries(declaration).filter(([, value]) => value != null && value !== '').map(([key,value]) => <div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
    <h3>Agent recommendation</h3><p>{String(agent.recommendation || 'No recorded recommendation')}</p><p>{String(report.agent_narrative || '')}</p>
    {!!agent.provider_unavailable && <p>Fallback: automated adjudication did not converge.</p>}
    <h3>Human decision</h3><p>{String(action.action || 'No recorded human action')} · {String(action.admin_id || '')} · {String(action.timestamp || '')}</p><p>{String(action.reason || '')}</p>
    {!!action.reviewed_run_id && <p>Human reviewed processing run: {String(action.reviewed_run_id)} · {((action.reviewed_evidence_ids || []) as string[]).length} photographs</p>}
    <h3>Recorded findings</h3>{findings.map(f => <article key={String(f.finding_id)}><h4>{String(f.check_id)} — {String(f.verdict)}</h4><p>{String(f.explanation)}</p><small>{String(f.finding_id)} · attributed to {String(f.attributed_to)}</small>{!!f.check_limitation && <p>{String(f.check_limitation)}</p>}</article>)}
    <h3>Limitations</h3><ul>{((report.limitations || []) as string[]).map(item => <li key={item}>{item}</li>)}</ul>
    <p>Heuristic confidence is not a calibrated fraud probability. The agent recommends; a human decides.</p>
  </dialog>;
}
