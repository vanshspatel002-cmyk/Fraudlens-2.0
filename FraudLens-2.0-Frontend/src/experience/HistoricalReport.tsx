import { useEffect, useRef } from 'react';
import ReportPanel from './ReportPanel';
import {applicationDetails,deskReviewSentences,processingLabel,reviewDate,type ReviewProcessing,type AssessmentExplanation} from './reviewPresentation';

export default function HistoricalReport({ text, close, allowDiagnostics = false }: {text: string; close: () => void; allowDiagnostics?: boolean}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const report = JSON.parse(text) as Record<string, unknown>;
  const agent = (report.agent_recommendation || {}) as Record<string, unknown>;
  const action = (report.admin_action || {}) as Record<string, unknown>;
  const declaration = (report.declaration || {}) as Record<string, unknown>;
  const findings = Object.values((report.findings_by_category || {}) as Record<string, Record<string, unknown>[]>).flat();
  const processing = report.processing as ReviewProcessing | undefined;
  const earlierReview = !!action.reviewed_run_id && !!report.run_id && action.reviewed_run_id !== report.run_id;
  const sentences = deskReviewSentences({kind:String(declaration.agent_type || ''),declaration,processing,status:String(report.status || declaration.status || ''),runId:String(report.run_id || ''),humanReviewedRun:String(action.reviewed_run_id || ''),assessmentExplanation:report.assessment_explanation as AssessmentExplanation | undefined,
    analysisFallback:!!agent.provider_unavailable,findings:findings.map(finding=>({verdict:String(finding.verdict || '')}))});
  return <dialog ref={dialog} aria-label="Historical report" className="report-history-dialog" onCancel={close}>
    <div className="report-history-controls"><button onClick={close}>Close historical report</button></div>
    <h2>Saved review</h2>
    <p>{String(report.case_id)} · Analysis: {processingLabel(processing)}</p>
    <h3>Desk Review</h3><p className="desk-review-summary" data-sentence-count={sentences.length}>{sentences.join(' ')}</p>
    {!!report.snapshot_id && <ReportPanel caseId={String(report.case_id)} runId={String(report.run_id || '')} initialSnapshotId={String(report.snapshot_id)} compact />}
    <details><summary>Application at this report version</summary><dl className="review-application">{applicationDetails(declaration).map(field=><div key={field.key}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></details>
    <h3>Recorded human decision</h3><p>{String(action.action || 'No human decision was recorded')}{!!action.admin_id && <> · {String(action.admin_id)}</>}{!!action.timestamp && <> · {reviewDate(String(action.timestamp))}</>}</p>
    {!!action.action && <p>{earlierReview ? 'This decision reviewed an earlier analysis run; it does not review this report’s analysis.' : !action.reviewed_run_id ? 'The analysis basis for this historical human decision was not recorded.' : 'This decision reviewed the analysis saved in this report.'}</p>}
    {!!action.reason && <details><summary>Internal reviewer note</summary><p>{String(action.reason)}</p></details>}
    {allowDiagnostics && <details><summary>Technical diagnostics for this version</summary><p>Analysis run: {String(report.run_id || 'Not recorded')}<br/>Policy: {String(report.policy_version || 'Not recorded')}<br/>Recorded findings: {findings.length}</p>{!!action.reviewed_run_id && <p>Run reviewed by a human: {String(action.reviewed_run_id)}</p>}<ul>{((report.limitations || []) as string[]).map(item=><li key={item}>{item}</li>)}</ul></details>}
  </dialog>;
}
