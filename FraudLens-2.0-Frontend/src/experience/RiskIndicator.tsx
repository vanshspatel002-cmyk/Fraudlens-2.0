import './risk-indicator.css';

export type RiskPresentation = {
  version: string; run_id?: string | null; policy_version?: string | null;
  complete: boolean; category?: 'Low' | 'Medium' | 'High' | null; label: string;
  processing_state?: string; state?: string; score?: number | null; score_scale?: string | null;
  thresholds?: Record<string, number> | null; position_basis?: 'category_only';
  basis: string; explanation: string; historical?: boolean; scope?: string;
};

export default function RiskIndicator({ assessment }: { assessment?: RiskPresentation | null }) {
  const valid = assessment?.complete === true && ['Low', 'Medium', 'High'].includes(assessment.category || '')
    && ['completed', 'historical'].includes(assessment.state || '') && ['completed', 'done'].includes(assessment.processing_state || '');
  const category = valid ? assessment!.category : null;
  const label = valid ? `${assessment!.historical ? 'Historical assessed risk' : 'Assessed risk'}: ${category}` : 'Assessment incomplete';
  return <section className={'risk-indicator' + (valid ? ' is-assessed' : ' is-neutral')} aria-label={label}>
    <div className="risk-indicator-heading"><strong>{label}</strong>
      {valid && typeof assessment?.score === 'number' && Number.isFinite(assessment.score)
        && <span title={assessment.score_scale || 'Recorded heuristic score'}>Score {assessment.score}</span>}
    </div>
    <div className="risk-segments" role="img" aria-label={`${label}. Category scale: Low, Medium, High. Category markers do not imply numerical ranges.`}>
      {(['Low', 'Medium', 'High'] as const).map(level => <span key={level}
        className={'risk-segment risk-segment-' + level.toLowerCase() + (category === level ? ' is-selected' : '')}>
        {category === level && <span className="risk-marker" aria-hidden="true">▼</span>}{level}
      </span>)}
    </div>
    <small title={[assessment?.explanation, assessment?.scope, assessment?.run_id, assessment?.policy_version].filter(Boolean).join(' · ')}>
      {valid ? `${assessment!.basis} · ${assessment!.score == null ? 'category only' : 'heuristic score'}`
        : assessment?.state === 'stale' ? 'Earlier assessment does not cover this run.'
        : `Current state: ${(assessment?.processing_state || 'unavailable').replaceAll('_', ' ')}.`}
      {assessment?.run_id && ` · Run ${assessment.run_id.slice(0, 10)}`}
      {assessment?.policy_version && <span className="risk-policy"> · Policy {assessment.policy_version.match(/v\d+$/)?.[0] || assessment.policy_version.slice(0, 14)}</span>}
    </small>
  </section>;
}
