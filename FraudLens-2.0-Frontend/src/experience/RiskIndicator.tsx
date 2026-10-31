import './risk-indicator.css';

export type RiskPresentation = {
  version: string; run_id?: string | null; policy_version?: string | null;
  complete: boolean; category?: 'Low' | 'Medium' | 'High' | null; label: string;
  display_label?: string; processing_state?: string; state?: string; score?: number | null; score_scale?: string | null;
  risk_index?: number | null; risk_index_formatted?: string | null; risk_policy_note?: string;
  thresholds?: Record<string, number> | null; position_basis?: 'category_only';
  basis: string; explanation: string; historical?: boolean; scope?: string;
  display_band?: 'LOW'|'MEDIUM'|'HIGH'|'UNASSESSED'; provisional?: boolean;
  display_policy_version?:string; next_action?:string;
  method?:string;method_note?:string;status_label?:string;review_recommendation?:string;
  coverage?:{sufficient:number;required_applicable:number;material_gap_ids:string[]};
  supporting_findings?:{finding_id?:string;check_id?:string;attributed_to?:string;explanation?:string}[];
};

export default function RiskIndicator({ assessment }: { assessment?: RiskPresentation | null }) {
  const completed = assessment?.complete === true && ['Low', 'Medium', 'High'].includes(assessment.category || '')
    && ['completed', 'historical'].includes(assessment.state || '') && ['completed', 'done'].includes(assessment.processing_state || '');
  const provisional = assessment?.provisional === true && !!assessment.display_policy_version && assessment.state==='partial'
    && ['Medium','High'].includes(assessment.category || '');
  const valid = completed || provisional;
  const category = valid ? assessment!.category : null;
  const bandName = category ? category.toUpperCase() : (assessment?.display_band || '');
  const heading = valid && bandName
    ? (assessment?.risk_index != null
        ? `${bandName} — Risk index: ${assessment.risk_index}%`
        : assessment?.historical
          ? `${bandName} — Risk index: Not calculated for this historical assessment`
          : assessment!.label)
    : 'UNASSESSED — insufficient evidence';

  return <section className={'risk-indicator' + (valid ? ' is-assessed' : ' is-neutral')} aria-label={heading}>
    <div className="risk-indicator-heading">
      <strong>{heading}</strong>
      {completed && typeof assessment?.score === 'number' && Number.isFinite(assessment.score)
        && <span title={assessment.score_scale || 'Recorded heuristic score'}>Heuristic score {assessment.score}</span>}
    </div>
    <div className="risk-segments" role="img" aria-label={`${heading}. Category scale: Low, Medium, High. Category markers do not imply numerical ranges.`}>
      {(['Low', 'Medium', 'High'] as const).map(level => <span key={level}
        className={'risk-segment risk-segment-' + level.toLowerCase() + (category === level ? ' is-selected' : '')}>
        {category === level && <span className="risk-marker" aria-hidden="true">▼</span>}{level}
      </span>)}
    </div>
    <small title={[assessment?.explanation, assessment?.scope, assessment?.run_id, assessment?.policy_version].filter(Boolean).join(' · ')}>
      {valid ? `${assessment!.basis} · ${assessment!.method === 'Local rules assessment' ? 'review priority under the local rules policy' : assessment!.score == null ? 'category only' : 'heuristic score'}`
        : assessment?.state === 'stale' ? 'Earlier assessment does not cover this run.'
        : `Current state: ${(assessment?.processing_state || 'unavailable').replaceAll('_', ' ')}.`}
      {assessment?.run_id && ` · Run ${assessment.run_id.slice(0, 10)}`}
      {assessment?.policy_version && <span className="risk-policy"> · Policy {assessment.policy_version.match(/v\d+$/)?.[0] || assessment.policy_version.slice(0, 14)}</span>}
    </small>
    <p className="risk-disclaimer" style={{fontSize: '10px', color: 'var(--muted, #66727a)', margin: '6px 0 0', fontStyle: 'italic'}}>
      Risk index expresses the strength of findings under this assessment policy; it is not a statistical probability of fraud.
    </p>
    {assessment?.method_note && <p>{assessment.method_note}</p>}
    {assessment?.coverage && <p className="risk-coverage">Material evidence: {assessment.coverage.sufficient} / {assessment.coverage.required_applicable} applicable requirements sufficient.</p>}
    <p className="risk-explanation">{assessment?.explanation || 'A run-bound assessment was not saved. Review the evidence and processing status.'}</p>
    {!!assessment?.supporting_findings?.length && <p className="risk-support">Band supported by: {[...new Set(assessment.supporting_findings.map(finding=>`${(finding.check_id || 'recorded finding').replaceAll('_',' ')} (${finding.attributed_to || 'attribution unrecorded'})`))].join('; ')}. See the recorded findings below.</p>}
    {assessment?.next_action && <p className="risk-next-action">{assessment.next_action}</p>}
  </section>;
}
