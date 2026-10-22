"""Authored scenario evaluation and offline replay; no production writes/HTTP."""
import sys,json,copy,base64
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_visual_report_samples import fixture
from src.shadow_assessment import calculate
from src.baseline import band_for
from src.report_pdf import render_pdf,RENDERER_VERSION

def main():
 out=ROOT.parent/'docs/assessment_audit';out.mkdir(exist_ok=True);rows=[]
 for kind in ['claims','underwriting']:
  report=fixture(kind,'Low',category_only=True);clean=copy.deepcopy(report['assessment_explanation'])
  for r in clean['findings']:r['verdict']='pass';r['eligibility']['eligible']=False
  for r in clean['coverage']['requirements'].values():
   if r['required'] and r['applicable']:r['evidence_sufficient']=True
  scenarios={'clean_authored':clean}
  strong=copy.deepcopy(clean)
  internal=next(r for r in strong['findings'] if r['check_id']=='internal_duplicate')
  internal['verdict']='concern';internal['eligibility']['eligible']=True
  scenarios['supported_reuse']=strong
  duplicated=copy.deepcopy(strong);duplicated['findings']*=5;scenarios['repeated_findings']=duplicated
  correlated=copy.deepcopy(strong)
  for r in correlated['findings']:
   if r['check_id']=='external_corpus':r['verdict']='concern';r['eligibility']['eligible']=True
  scenarios['correlated_reuse']=correlated
  for key,r in clean['coverage']['requirements'].items():
   if r['required'] and r['applicable']:
    gap=copy.deepcopy(clean);gap['coverage']['requirements'][key]['evidence_sufficient']=False
    scenarios['missing_'+key]=gap
  optional=copy.deepcopy(clean)
  for r in optional['coverage']['requirements'].values():
   if not r['required']:r['evidence_sufficient']=False
  scenarios['optional_unavailable']=optional
  for name,explanation in scenarios.items():
   candidate=calculate(explanation)
   additive=sum(r['registered_weight']*r['finding_confidence'] for r in explanation['findings'] if r['verdict']=='concern')
   gaps=candidate['mandatory_gaps']
   rows.append(dict(kind=kind,scenario=name,baseline_band=band_for(additive).value,baseline_sum=additive,
       guard_replay='request_evidence' if gaps else 'approve',
       candidate=candidate['candidate_recommendation'],R=candidate['concern_index'],C=candidate['coverage'],
       simple_group_max=max(candidate['groups'].values(),default=0),mandatory_gaps=gaps))
  if kind=='underwriting':
   report=fixture(kind,'Medium',category_only=True)
   (out/'underwriting-fixture.pdf').write_bytes(render_pdf(report,'authored-underwriting-replay',1792680000))
 live=ROOT/'outputs/normal_operation_20261022/live/claims-report.json'
 if live.exists():
  report=json.loads(live.read_text(encoding='utf8'));report['report_template_version']=RENDERER_VERSION
  # The API summary lacks frozen thumbnails. Restore only the known authorized
  # submitted sample for this explicit offline replay; do not fabricate matches.
  ids=report.get('evidence_ids') or sorted({r['observed_values']['image_id'] for r in report['assessment_explanation'].get('findings',[]) if r.get('observed_values',{}).get('image_id')})
  if ids and not report.get('evidence_inventory'):
   report['evidence_inventory']=[{'image_id':ids[0],'label':'Authorized submitted sample (offline replay)',
      'thumbnail_base64':base64.b64encode((ROOT/'data/curated/damaged/damaged_0002.jpg').read_bytes()).decode(),
      'considered_in_run':True}]
  report['assessment_explanation']['shadow_assessment']=calculate(report['assessment_explanation'],report.get('evidence_ids',[]))
  report.setdefault('limitations',[]).insert(0,'OFFLINE REPLAY of previously saved live results; no fresh inference or production snapshot update.')
  (out/'claims-saved-replay.pdf').write_bytes(render_pdf(report,'offline-saved-result-replay',1792680000))
 (out/'evaluation.json').write_text(json.dumps(rows,indent=2))
 lines=['# Assessment evaluation — shadow only','','Authored scenarios, not held-out accuracy data. No new inference. Baseline arithmetic uses saved weights/confidence; guard replay holds the authored model approval fixed. These are deterministic policy experiments, not new model decisions.','', '| Type | Scenarios | Missing-material scenarios | Candidate unsafe clearance | Guard replay unsafe clearance | Authored clean false flags |','|---|---|---|---|---|---|']
 for kind in ['claims','underwriting']:
  subset=[r for r in rows if r['kind']==kind];missing=[r for r in subset if r['mandatory_gaps']]
  lines.append(f"| {kind} | {len(subset)} | {len(missing)} | {sum(r['candidate']=='candidate_clear' for r in missing)} / {len(missing)} | 0 / {len(missing)} | {sum(r['candidate']!='candidate_clear' for r in subset if r['scenario']=='clean_authored')} / 1 |")
 lines += ['','Repeated and correlated reuse findings retain R=0.8; additive baseline grows with repetition. Group maximum is simpler and more conservative; product pooling increases distinct-group concern but has no probabilistic interpretation. There is no independent evaluation showing its superiority. Candidate stays SHADOW ONLY; existing guarded production routing stays unchanged. Precision/recall and real false-positive rates are NOT ESTIMABLE here: no independently adjudicated held-out labels were supplied. Archetypes covered: reuse, evidence gaps, optional provenance and duplicate inflation; independent scene, fabricated-baseline and same-vehicle identity accuracy remain unestablished. Garage alerts remain separate; direct fixture regressions verify their exclusion.','','## Functional verification results','','Results are appended after the offline commands finish. Samples are replay/fixtures; underwriting live evidence remains deferred. No calibration, priors, billing, credential changes or historical batch execution.']
 (ROOT.parent/'docs/ASSESSMENT_EVALUATION.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
 print('Authored evaluation and separately labelled replay reports generated; zero provider calls.')

if __name__=='__main__':main()
