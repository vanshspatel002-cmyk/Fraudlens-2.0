import type { FormEvent } from 'react';
import ReportPanel from './ReportPanel';
import {applicationDetails,deskReviewSentences,formatShadowMetric,processingLabel,readableTimeline,recordedModelRecommendation,reviewDate,type ReviewSummaryInput} from './reviewPresentation';
import './case-review.css';

type ReviewCase = ReviewSummaryInput & {
  id:string; status:string; created_at:string; name:string; images:{id:string;src:string;label:string}[];
  audit:{created_at:string;actor:string;event:string;detail:string}[];
  outcome?:string; admin?:string; updated_at?:string; reason?:string; runId?:string; policyVersion?:string; version?:number;
  limitations:string[]; humanReviewedRun?:string;
  reportHistory:{snapshot_id:string;run_id?:string;created_at:number}[];
  evidenceRequest?:{artifacts:string[]};
};

export default function CaseReview({detail,userRole,busy,humanAction,onHumanAction,onAction,onPhoto,onHistory,onRefresh,onRetry}: {
  detail:ReviewCase;userRole:string;busy:boolean;humanAction:string;
  onHumanAction:(value:string)=>void;onAction:(event:FormEvent<HTMLFormElement>)=>void;
  onPhoto:(image:ReviewCase['images'][number])=>void;onHistory:(snapshot:string)=>void;onRefresh:()=>void;onRetry:()=>void;
}) {
  const active = ['queued','running'].includes(detail.processing?.status || '');
  const final = ['closed_approved','closed_rejected'].includes(detail.status);
  const manual = !!detail.analysisFallback || ['failed','interrupted','completed_partial'].includes(detail.processing?.status || '');
  const outcome = detail.status === 'closed_approved' ? 'Approved' : detail.status === 'closed_rejected' ? 'Rejected' : detail.status === 'awaiting_evidence' ? 'Additional photographs requested' : 'Awaiting reviewer';
  const recordedOutcome = ({approve:'Approved',reject:'Rejected',request_more_evidence:'Additional photographs requested'} as Record<string,string>)[detail.outcome || ''] || outcome;
  const earlierReview = !!detail.outcome && !!detail.humanReviewedRun && !!detail.runId && detail.humanReviewedRun !== detail.runId;
  const unknownReviewBasis = !!detail.outcome && !detail.humanReviewedRun;
  const sentences = deskReviewSentences(detail);
  const timeline = readableTimeline(detail.audit,detail.created_at,detail.processing);
  return <div className={'case-review '+(detail.kind === 'claims' ? 'recon' : 'sentinel')}>
    <header className="review-case-status">
      <div><span className={'agent-tag '+(detail.kind === 'claims' ? 'recon' : 'sentinel')}>{detail.kind === 'claims' ? 'Claims' : 'Underwriting'}</span><strong>{detail.id}</strong></div>
      <dl><div><dt>Analysis</dt><dd className={'review-processing '+(detail.processing?.status || 'not-recorded')}>{processingLabel(detail.processing)}</dd></div><div><dt>Human decision</dt><dd>{earlierReview ? recordedOutcome+' (earlier analysis)' : unknownReviewBasis ? recordedOutcome+' (historical; basis not recorded)' : outcome}</dd></div><div><dt>Submitted</dt><dd>{reviewDate(detail.created_at)}</dd></div></dl>
    </header>

    <section className="case-panel review-section" aria-labelledby="review-application-title" data-review-section="application">
      <h2 id="review-application-title">Application details</h2>
      <dl className="review-application">{applicationDetails(detail.declaration).map(field=><div key={field.key}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
      {!applicationDetails(detail.declaration).length && <p>No application details were recorded for this case.</p>}
    </section>

    <section className="case-panel review-section" aria-labelledby="review-photos-title" data-review-section="photos">
      <h2 id="review-photos-title">Vehicle photographs</h2>
      {detail.images.length ? <div className="image-gallery review-photos">{detail.images.map(image=><button key={image.id} type="button" onClick={()=>onPhoto(image)}><img src={image.src} alt={image.label}/><span>{image.label}</span></button>)}</div> : <p>No vehicle photographs were recorded.</p>}
    </section>

    <section className="case-panel review-section review-desk" aria-labelledby="review-desk-title" data-review-section="desk">
      <h2 id="review-desk-title">Desk Review</h2>
      <p className="desk-review-summary" data-sentence-count={sentences.length}>{sentences.join(' ')}</p>
      {detail.assessmentExplanation?.routing?.effective_recommendation && <dl className="review-application" aria-label="Automated routing basis">
        <div><dt>Model recommendation (recorded)</dt><dd>{recordedModelRecommendation(detail)}</dd></div>
        <div><dt>Effective system routing</dt><dd>{detail.assessmentExplanation.routing.effective_recommendation.replaceAll('_',' ')}{detail.assessmentExplanation.routing.guard_applied ? ' · material evidence guard applied' : ''}</dd></div>
        {!!detail.assessmentExplanation.coverage?.material_gap_ids?.length && <div><dt>Material missing evidence</dt><dd>{detail.assessmentExplanation.coverage.material_gap_ids.map(key=>key.replaceAll('_',' ')).join(', ')}</dd></div>}
      </dl>}
      {detail.assessmentExplanation?.shadow_assessment && <aside aria-label="Shadow candidate assessment">
        <h3>Candidate assessment — shadow only</h3>
        <p>Saved concern index: {formatShadowMetric(detail.assessmentExplanation.shadow_assessment.concern_index)}. Material evidence coverage: {formatShadowMetric(detail.assessmentExplanation.shadow_assessment.coverage,true)}.</p>
        <p>{detail.assessmentExplanation.shadow_assessment.candidate_recommendation.replaceAll('_',' ')} · {detail.assessmentExplanation.shadow_assessment.version}. Unvalidated heuristic; neither axis is a fraud probability. Production routing and human review remain separate.</p>
      </aside>}
      <ReportPanel key={detail.id+'-'+detail.version} caseId={detail.id} runId={detail.runId} processingStatus={detail.processing?.status} compact />
      {!!detail.reportHistory.length && <details className="review-history"><summary>Earlier reports and reviews</summary><label className="field"><span>Report history</span><select aria-label="Report history" defaultValue="" onChange={event=>{const snapshot=event.target.value;event.target.value='';if(snapshot)onHistory(snapshot);}}><option value="">Choose an earlier report</option>{detail.reportHistory.map(item=><option key={item.snapshot_id} value={item.snapshot_id}>{reviewDate(new Date(item.created_at*1000).toISOString())} · {item.snapshot_id.slice(0,12)}</option>)}</select></label></details>}
    </section>

    <section className="case-panel review-section action-panel" aria-labelledby="review-actions-title" data-review-section="actions">
      <h2 id="review-actions-title">Human actions</h2>
      {detail.outcome && <p className="review-recorded-outcome"><strong>{earlierReview ? 'Earlier decision: '+recordedOutcome : outcome}</strong>{detail.admin && <> · {detail.admin}</>}{detail.updated_at && <> · {reviewDate(detail.updated_at)}</>}<br/>{earlierReview ? 'This decision reviewed an earlier analysis run; it does not review the current analysis.' : !detail.humanReviewedRun ? 'The analysis basis for this historical human decision was not recorded.' : 'The recorded explanation and review history appear in the timeline below.'}</p>}
      {detail.evidenceRequest && <div className="review-evidence-request"><h3>Requested photographs</h3><ul>{detail.evidenceRequest.artifacts.map(item=><li key={item}>{item}</li>)}</ul></div>}
      <form onSubmit={onAction}>
        {active && <p role="status">Wait for processing to finish before recording a decision.</p>}
        {final && <p role="status">A final decision has been recorded. Its history is preserved.</p>}
        <label className="field"><span>Action</span><select name="action" required value={humanAction} onChange={event=>onHumanAction(event.target.value)}><option>Approve</option><option>Reject</option><option>Request More Evidence</option></select></label>
        <label className="field"><span>Internal reviewer note / decision reason</span><textarea name="reason" required={humanAction !== 'Approve' || manual} maxLength={3000} rows={3}/><small>Private to reviewers. Required for rejection, evidence requests and manual review overrides.</small></label>
        {manual && humanAction !== 'Request More Evidence' && <label className="manual-review-consent"><input type="checkbox" name="manualReviewOverride" required/><span>Proceed with manual review because automated analysis is unavailable. Explain the evidence reviewed and the reason for this override in the internal note.</span></label>}
        {humanAction === 'Request More Evidence' && <label className="field"><span>Specific photographs required (one per line)</span><textarea name="requestedArtifacts" required maxLength={3000} rows={3}/></label>}
        <label className="field"><span>Customer-visible explanation *</span><textarea name="publicNarrative" required maxLength={1500} rows={3}/><small>Share the outcome clearly without private investigation details.</small></label>
        <button className="record-action" disabled={busy || userRole === 'viewer' || active || final}>{busy ? 'Recording…' : humanAction === 'Approve' ? 'Approve case' : humanAction === 'Reject' ? 'Reject case' : 'Request more evidence'}</button>
      </form>
    </section>

    <section className="case-panel review-section" aria-labelledby="review-timeline-title" data-review-section="timeline">
      <h2 id="review-timeline-title">Case timeline</h2>
      {timeline.length ? <ol className="review-timeline">{timeline.map(event=><li key={event.id}><time dateTime={event.at}>{reviewDate(event.at)}</time><h3>{event.title}</h3><span>{event.actor}</span>{event.message && <p>{event.message}</p>}{event.note && <details><summary>Internal reviewer note</summary><p>{event.note}</p></details>}</li>)}</ol> : <p>No timeline events were recorded.</p>}
    </section>

    {userRole !== 'viewer' && <details className="review-diagnostics"><summary>Technical diagnostics</summary><dl className="review-application"><div><dt>Recorded processing status</dt><dd>{detail.processing?.status || 'Not recorded'}{detail.processing?.review_summary?.historical_derived ? ' (original status; review summary derived from saved results)' : ''}</dd></div><div><dt>Processing stage</dt><dd>{detail.processing?.stage || 'Not recorded'}</dd></div><div><dt>Analysis run</dt><dd>{detail.runId || 'Not recorded for this historical case'}</dd></div><div><dt>Policy version</dt><dd>{detail.policyVersion || 'Not recorded'}</dd></div><div><dt>Recorded findings</dt><dd>{detail.findings?.length || 0}</dd></div>{detail.humanReviewedRun && <div><dt>Run reviewed by a human</dt><dd>{detail.humanReviewedRun}</dd></div>}</dl>{!!detail.processing?.failures?.length && <dl className="review-application">{detail.processing.failures.map((failure,index)=><div key={index}><dt>{failure.stage || 'AI stage'}</dt><dd>{failure.error_category || 'Unavailable'} · {failure.timestamp || 'Time not recorded'} · attempts {failure.attempt_count ?? 'not recorded'} · retryable {failure.retryable ? 'yes' : 'no'}{failure.http_status ? ' · HTTP '+failure.http_status : ''}</dd></div>)}</dl>}{detail.processing?.detail && <p className="review-diagnostic-message">{detail.processing.detail}</p>}{!!detail.limitations.length && <><h3>Recorded limitations</h3><ul>{detail.limitations.map(item=><li key={item}>{item}</li>)}</ul></>}<div className="review-diagnostic-actions"><button type="button" disabled={busy} onClick={onRefresh}>Refresh case</button><button type="button" disabled={busy || active} onClick={onRetry}>Retry analysis</button></div></details>}
  </div>;
}
