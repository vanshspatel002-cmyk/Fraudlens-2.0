import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/experience/reviewPresentation.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {recordedModelRecommendation,formatShadowMetric} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
for (const kind of ['claims','underwriting']) {
  const detail = {kind,declaration:{},assessmentExplanation:{routing:{source:'fallback',converged:false,model_recommendation:'approve',recommendation:'escalate'}}};
  assert.match(recordedModelRecommendation(detail), /No converged model decision/);
  detail.assessmentExplanation.routing = {source:'model',converged:true,model_recommendation:'request_evidence'};
  assert.equal(recordedModelRecommendation(detail),'request evidence');
  detail.analysisFallback = true;
  assert.match(recordedModelRecommendation(detail),/No converged model decision/);
  assert.equal(recordedModelRecommendation({kind,declaration:{}}),'Model decision source not recorded');
}
assert.equal(formatShadowMetric(.30000000000000004),'0.30 / 1');
assert.equal(formatShadowMetric(1/3,true),'33.3%');
for (const invalid of [null,undefined,NaN,Infinity,-.1,1.01]) assert.equal(formatShadowMetric(invalid),'Not assessable');
console.log('Saved routing/fallback and shadow formatting: passed for both case types; no network.');
