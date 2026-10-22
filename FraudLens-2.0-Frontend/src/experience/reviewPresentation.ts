export type ReviewFinding = { verdict: string; check_status?: string };
export type ReviewProcessing = { job_id?: string; status?: string; stage?: string; detail?: string };
export type AssessmentExplanation = {routing?:{source?:string;converged?:boolean;model_recommendation?:string;recommendation?:string;effective_recommendation?:string;guard_applied?:boolean;guard_policy?:string};coverage?:{material_complete?:boolean;complete?:boolean;material_gap_ids?:string[]}};
export type ReviewSummaryInput = {
  kind: string;
  registration?: string;
  amount?: number;
  declaration: Record<string, unknown>;
  processing?: ReviewProcessing | null;
  findings?: ReviewFinding[];
  analysisFallback?: boolean;
  assessmentExplanation?: AssessmentExplanation;
  status?: string;
  runId?: string;
  humanReviewedRun?: string;
};

export const readable = (value: string) => value.replaceAll('_', ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
const text = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value).trim().replace(/\s+/g, ' ') : '';
export const reviewMoney = (value: unknown) => new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',maximumFractionDigits:2}).format(Number(value));
export function reviewDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en-IN', {dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Kolkata'}).format(date) + ' IST';
}

export function processingLabel(processing?: ReviewProcessing | null) {
  if (!processing?.status || ['not_recorded','not_started','legacy','unknown'].includes(processing.status)) return 'Not recorded';
  return ({queued:'Queued',running:'Processing',completed:'Completed',done:'Completed',failed:'Failed',interrupted:'Interrupted'} as Record<string,string>)[processing.status] || readable(processing.status);
}

function firstStatement(value: unknown, limit = 180) {
  const normalized = text(value).split(/[.!?](?:\s|$)/)[0].replace(/[.!?]+$/,'');
  if (normalized.length <= limit) return normalized;
  const clipped = normalized.slice(0,limit);
  return clipped.slice(0,clipped.lastIndexOf(' ') > limit/2 ? clipped.lastIndexOf(' ') : limit) + '…';
}

/** Deterministic facts from the actual declaration and recorded processing.
 * Applicant statements stay attributed; no model call or inferred verdict. */
export function deskReviewSentences(input: ReviewSummaryInput): string[] {
  const declaration = input.declaration;
  const registration = text(declaration.vehicle_registration) || text(input.registration) || 'the declared vehicle';
  const amount = declaration.claim_amount ?? input.amount;
  const claims = input.kind === 'claims';
  const identity = claims
    ? `This is a motor claim for ${registration}${Number(amount) > 0 ? ` with a declared claim of ${reviewMoney(amount)}` : ''}.`
    : `This is an underwriting application for ${registration}.`;
  const notes = String(declaration.declaration_notes || '');
  const condition = notes.match(/Declared vehicle condition:\s*([^\n]+)/i)?.[1] || text(declaration.condition);
  const narrative = notes.split('\n').filter(line => !/^(Application type|Declared vehicle condition):/i.test(line.trim())).join(' ');
  const statement = firstStatement(narrative);
  const location = firstStatement(declaration.declared_location,90);
  const date = text(declaration.incident_date);
  const event = claims
    ? statement ? `The applicant reports “${statement}”${location ? ` in ${location}` : ''}${date ? ` (${reviewDate(date)})` : ''}.`
      : `The declared incident${date ? ` is recorded at ${reviewDate(date)}` : ' has no recorded date'}${location ? ` in ${location}` : ''}; no incident description was recorded.`
    : condition ? `The applicant declares “${firstStatement(condition)}”${statement ? ` and states “${statement}”` : ''}.`
      : statement ? `The applicant states “${statement}”.` : 'No vehicle condition declaration was recorded.';
  const status = input.processing?.status;
  const findings = input.findings || [];
  const concerns = findings.filter(finding => finding.verdict.toUpperCase() === 'CONCERN').length;
  const inconclusive = findings.filter(finding => finding.verdict.toUpperCase() === 'INCONCLUSIVE').length;
  const routing = input.assessmentExplanation?.routing;
  const coverage = input.assessmentExplanation?.coverage;
  const earlierReview = !!input.humanReviewedRun && !!input.runId && input.humanReviewedRun !== input.runId;
  const decided = ['closed_approved','closed_rejected'].includes(input.status || '');
  const human = earlierReview ? 'the recorded human decision reviewed an earlier analysis run'
    : decided && !input.humanReviewedRun ? 'the historical human decision has no recorded analysis basis'
      : decided ? 'the human decision is recorded below' : 'a human review is required';
  let conclusion: string;
  if (status === 'queued' || status === 'running') conclusion = `Analysis is ${status === 'queued' ? 'queued' : 'in progress'}; no completed conclusion is available.`;
  else if (['failed','interrupted'].includes(status || '') && routing?.converged === true) conclusion = `Processing did not fully complete, although automated routing is recorded${coverage?.material_complete === false ? ' with incomplete check coverage' : ''}; ${human}.`;
  else if (status === 'failed' || status === 'interrupted' || input.analysisFallback || routing?.converged === false) conclusion = `Automated interpretation is incomplete; ${human}.`;
  else if (coverage?.material_complete === false) conclusion = `Automated routing is recorded, but check coverage is incomplete; ${human}.`;
  else if (status === 'completed' || status === 'done') {
    conclusion = concerns ? `The recorded checks flag ${concerns} concern${concerns === 1 ? '' : 's'}; ${human}.`
      : inconclusive ? `The recorded checks include ${inconclusive} inconclusive result${inconclusive === 1 ? '' : 's'}; ${human}.`
        : findings.some(finding => ['failed','not_run'].includes(finding.check_status || '')) ? `Recorded check coverage is incomplete; ${human}.`
          : findings.length ? `The recorded checks did not flag a concern; ${human}.`
            : `Processing completed without recorded check results; ${human}.`;
  } else conclusion = findings.length ? 'Historical findings are available, but their processing status was not recorded.' : `Processing status was not recorded; ${human}.`;
  return [identity,event,conclusion];
}

const labels: Record<string,string> = {
  person_name:'Applicant',person_contact:'Contact',person_address:'Address',person_dob:'Date of birth',driving_license_number:'Driving licence',
  vehicle_registration:'Registration',vehicle_make:'Make',vehicle_model:'Model',vehicle_variant:'Variant',vehicle_year:'Manufacturing year',
  engine_number:'Engine number',chassis_number:'Chassis number',fuel_type:'Fuel type',rto:'Registration office',idv:'Insured declared value',
  policy_number:'Policy number',policy_type:'Policy type',previous_policy_number:'Previous policy',policy_ncb_percent:'No-claim bonus (%)',
  policy_start_date:'Policy start',policy_end_date:'Policy end',claim_amount:'Claimed amount',incident_date:'Declared incident date and time',
  declared_location:'Declared incident location',declaration_notes:'Applicant declaration',fir_number:'FIR reference',settlement_preference:'Settlement preference',bank_account_last4:'Bank account last four digits',
  garage_id:'Garage reference',
};
export function applicationDetails(declaration: Record<string,unknown>) {
  return Object.entries(declaration).filter(([key,value]) => key in labels && value !== null && value !== undefined && value !== '')
    .map(([key,value]) => ({key,label:labels[key],value:['idv','claim_amount'].includes(key) && Number.isFinite(Number(value)) ? reviewMoney(value) : key === 'incident_date' ? reviewDate(String(value)) : String(value)}));
}

type Audit = {created_at:string;actor?:string;event:string;detail?:unknown};
export function readableTimeline(audit: Audit[], submittedAt: string) {
  const titles: Record<string,string> = {
    case_submitted:'Application submitted',vehicle_image_gate:'Vehicle photographs received',processing_started:'Analysis started',
    processing_completed:'Analysis completed',processing_finished:'Analysis finished',processing_failed:'Analysis incomplete',processing_interrupted:'Analysis interrupted',
    additional_evidence_received:'Additional photographs received',reprocess_requested:'New analysis requested',analysis_requested:'New analysis requested',
    processing_restart_recovery:'Analysis recovered after restart',
  };
  const events = audit.flatMap((event,index) => {
    let detail: Record<string,unknown> = {};
    try {detail = typeof event.detail === 'string' ? JSON.parse(event.detail) : (event.detail || {}) as Record<string,unknown>;} catch { /* Older free text stays in the archived report. */ }
    if (event.event === 'admin_action') {
      const title = ({approve:'Approved by a reviewer',reject:'Rejected by a reviewer',request_more_evidence:'Additional photographs requested'} as Record<string,string>)[String(detail.action)] || 'Reviewer update';
      return [{id:String(index),at:event.created_at,actor:event.actor || 'Reviewer',title,message:text(detail.public_message),note:text(detail.reason)}];
    }
    if (!(event.event in titles)) return [];
    return [{id:String(index),at:event.created_at,actor:event.actor || 'System',title:titles[event.event],message:event.event === 'processing_failed' ? 'The recorded analysis could not complete. A human review is required.' : '',note:''}];
  });
  if (submittedAt && !audit.some(event => event.event === 'case_submitted')) events.unshift({id:'submitted',at:submittedAt,actor:'Applicant',title:'Application submitted',message:'',note:''});
  return events.sort((left,right) => new Date(left.at).getTime() - new Date(right.at).getTime());
}
