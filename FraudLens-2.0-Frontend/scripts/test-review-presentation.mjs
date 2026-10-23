import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/experience/reviewPresentation.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {recordedModelRecommendation,formatShadowMetric,processingLabel,deskReviewSentences,readableTimeline,terminalProcessing} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
for(const status of ['completed','completed_partial','done','failed','interrupted'])assert.equal(terminalProcessing(status),true);
for(const status of ['queued','running',undefined,'unknown'])assert.equal(terminalProcessing(status),false);
for (const kind of ['claims','underwriting']) {
  const detail = {kind,declaration:{},assessmentExplanation:{routing:{source:'fallback',converged:false,model_recommendation:'approve',recommendation:'escalate'}}};
  assert.match(recordedModelRecommendation(detail), /No converged model decision/);
  detail.assessmentExplanation.routing = {source:'model',converged:true,model_recommendation:'request_evidence'};
  assert.equal(recordedModelRecommendation(detail),'request evidence');
  detail.analysisFallback = true;
  assert.match(recordedModelRecommendation(detail),/No converged model decision/);
  assert.equal(recordedModelRecommendation({kind,declaration:{}}),'Model decision source not recorded');
  const processing={job_id:'fixture-run',status:'failed',review_summary:{kind:'provider_partial',admin_label:'Ready for manual review — AI unavailable.',message:'Local checks complete — AI analysis unavailable; human review required.'}};
  assert.equal(processingLabel(processing),processing.review_summary.admin_label);
  assert.ok(deskReviewSentences({kind,declaration:{},processing}).join(' ').includes(processing.review_summary.message));
  const audit=[{created_at:'2026-10-23T00:00:00Z',event:'processing_failed',detail:{run_id:'fixture-run'}}];
  assert.equal(readableTimeline(audit,'',processing)[0].title,'Available checks finished; AI analysis could not complete.');
  assert.equal(readableTimeline(audit,'',{...processing,job_id:'different-run'})[0].title,'Analysis incomplete');
}
assert.equal(formatShadowMetric(.30000000000000004),'0.30 / 1');
assert.equal(formatShadowMetric(1/3,true),'33.3%');
for (const invalid of [null,undefined,NaN,Infinity,-.1,1.01]) assert.equal(formatShadowMetric(invalid),'Not assessable');
console.log('Saved routing/fallback and shadow formatting: passed for both case types; no network.');
