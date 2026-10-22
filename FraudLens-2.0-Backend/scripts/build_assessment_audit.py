"""Read source/installed metadata and authored fixtures; never calls a provider."""
import ast,json,re,sys,math
from pathlib import Path
from importlib import metadata
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));DOC=ROOT.parent/'docs'
from src.checks import REGISTRY
from src.agent.production_policy import production_policy
from src.assessment_explanation import rule_parameters
from src.shadow_assessment import calculate

def table(headers,rows):
 return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+''.join('| '+' | '.join(str(c).replace('|','/').replace('\n',' ') for c in row)+' |\n' for row in rows)

def build():
 sources={p.relative_to(ROOT).as_posix():p.read_text(encoding='utf-8-sig') for area in ['src','scripts'] for p in (ROOT/area).rglob('*.py')}
 imports={}
 for name,text in sources.items():
  try:tree=ast.parse(text)
  except SyntaxError:continue
  for node in ast.walk(tree):
   roots=([node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [n.name.split('.')[0] for n in node.names] if isinstance(node,ast.Import) else [])
   for key in roots:imports.setdefault(key,set()).add(name)
 distributions=metadata.packages_distributions();packages={}
 for root,dists in distributions.items():
  for dist in dists:packages.setdefault(dist.lower().replace('_','-'),set()).update(imports.get(root,set()))
 rows=[]
 for manifest in sorted(ROOT.glob('requirements*.txt')):
  for line in manifest.read_text().splitlines():
   match=re.match(r'([\w.-]+)(?:\[[^]]+\])?==(.+)',line)
   if not match:continue
   pkg,pinned=match.groups();refs=sorted(packages.get(pkg.lower().replace('_','-'),set()))
   try:version=metadata.version(pkg)
   except metadata.PackageNotFoundError:version='NOT INSTALLED'
   role='Runtime source reference' if any(p.startswith('src/') and 'generate' not in p for p in refs) else 'Research/tooling reference' if refs else 'Transitive pin or unconfirmed; not direct application use'
   tests={'torch':'test_dependency_smoke.py::test_actual_clip_and_torchvision','torchvision':'test_dependency_smoke.py::test_actual_clip_and_torchvision','open_clip_torch':'test_dependency_smoke.py::test_actual_clip_and_torchvision','easyocr':'test_dependency_smoke.py::test_actual_ocr_labeled_plate_and_abstention','pillow':'test_dependency_smoke.py::test_pixels_exif_hash_and_numeric_search','ImageHash':'test_dependency_smoke.py::test_pixels_exif_hash_and_numeric_search','numpy':'test_dependency_smoke.py::test_pixels_exif_hash_and_numeric_search','opencv-python-headless':'test_dependency_smoke.py::test_pixels_exif_hash_and_numeric_search','pysolar':'test_dependency_smoke.py::test_solar_and_authentication_primitives','google-genai':'test_schema_correction.py (wire), test_llm.py (parsing)','psycopg':'test_postgres.py disposable schema','reportlab':'test_shadow_assessment.py saved PDF','pymupdf':'all-page sample extraction/render','c2pa-python':'test_checks.py / test_analysis_recovery.py controlled verifier states; native signed-fixture validation unverified'}
   test=tests.get(pkg,'No dedicated functional test; inspect callers/suite before claiming verified')
   rows.append([pkg+' / '+version+' (pin '+pinned+')',role,'; '.join(refs) or 'No first-party direct import located',test,'See run results below; import presence alone is not functional verification','Retain; no blind removals'])
 frontend=json.loads((ROOT.parent/'FraudLens-2.0-Frontend/package.json').read_text());frontsrc=list((ROOT.parent/'FraudLens-2.0-Frontend/src').rglob('*.tsx'))+list((ROOT.parent/'FraudLens-2.0-Frontend/src').rglob('*.ts'))
 for role in ['dependencies','devDependencies']:
  for pkg,version in frontend[role].items():
   installed=ROOT.parent/'FraudLens-2.0-Frontend/node_modules'/pkg/'package.json'
   installed_version=json.loads(installed.read_text(encoding='utf8')).get('version','unknown') if installed.exists() else 'not installed'
   refs=[p.relative_to(ROOT.parent/'FraudLens-2.0-Frontend').as_posix() for p in frontsrc if re.search(r'''["']'''+re.escape(pkg)+r'''(?:/|["'])''',p.read_text(encoding='utf8'))]
   rows.append([pkg+' / '+installed_version+' (manifest '+version+')',role+'; '+('source/component reference; entrypoint reachability varies' if refs else 'tooling or unconfirmed'),'; '.join(refs[:8]) or 'No src import located','Typecheck/build; no independent widget behavior claim','Read frontend results','Retain; audit reachability before removal'])
 (DOC/'DEPENDENCY_VERIFICATION.md').write_text('# Dependency verification — 22 October 2026\n\nBaseline `f35aa755db6d5cc88c7746a3672a1aa118761ea1`. Requirements are largely a frozen environment, not a curated direct-only manifest. Transitive pins are explicitly distinguished from first-party imports below. Versions are installed Python metadata and frontend manifest ranges; no upgrades/removals performed. Caller evidence is static, not proof every branch executes.\n\n'+table(['Package/version','Purpose/classification','Callers','Functional test','Result basis','Action'],rows)+'\n## Functional results\n\nSee `ASSESSMENT_EVALUATION.md` for executed commands/results. Tests exercise actual cached CLIP/Torchvision, OCR, pixels/EXIF, hashes, numeric operations and solar calculations. C2PA controlled valid/invalid/absent/error tests are not proof of native signed-file verification; no authorized signed valid/invalid pair was located. ExifTool is research-only (`src/generate_dataset.py`/scripts when referenced), not required for customer analysis. Dataset generators and synthetic labels are research, not independent truth. PostgreSQL remains the pilot store; SQLite is research/test/rollback. Password hashing is application scrypt, not Supabase Auth. Optional SDKs are not automatically active integrations.\n',encoding='utf8')
 api=ast.parse(sources['src/api.py']);fn=next(n for n in ast.walk(api) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='submit_case')
 fields=[a.arg for a in fn.args.args if a.arg not in {'conn','request','background','idempotency_key'}]
 fieldrows=[]
 for name in fields:
  callers=[p for p,t in sources.items() if p.startswith(('src/checks/','src/agent/')) and re.search(r'\b'+re.escape(name)+r'\b',t)]
  front=[p.relative_to(ROOT.parent/'FraudLens-2.0-Frontend').as_posix() for p in frontsrc if re.search(r'\b'+name+r'\b',p.read_text(encoding='utf8'))]
  classification='Direct assessment input' if name in {'images','latitude','longitude','declared_time','claim_amount','agent_type','declaration_notes','vehicle_registration'} else 'Identity/history linkage' if name in {'claimant_id','garage_id','policy_number','engine_number','chassis_number','bank_account_last4','person_contact'} else 'Operational/reviewer context'
  missing=('Scene comparisons unavailable without incident coordinates/time; no geocoding is fabricated' if name in {'latitude','longitude','declared_time'} else 'Insufficient evidence / no matching history is not clearance' if callers else 'Not independently verified; retained as applicant/reviewer context')
  fieldrows.append([name,'; '.join(front[:2]) or 'Not exposed by current customer UI / API-only','submit_case Form annotation and shared validation; inspect src/api.py:'+str(fn.lineno),'images/evidence persistence' if name=='images' else 'Case field via _draft_case; declaration fields mapped to Case','; '.join(callers) or 'No direct deterministic check reference located','_report_declaration / saved applicant facts; images in evidence inventory',missing,classification])
 (DOC/'PARAMETER_USAGE_MATRIX.md').write_text('# Parameter-use audit\n\n'+table(['Field','Frontend','API validation','Persistence','Check/tool references','Report use','Missing/limitation','Classification'],fieldrows)+'\nSource-reference rows are an audit index, not invented external verification. `declared_time` is an aware instant in production; the legacy generated corpus uses local wall-clock semantics. Underwriting amount zero is not a claims-damage input: production policy excludes damage_plausibility and threshold_gaming. Current customer UI does not collect coordinates; location text is not geocoded. Scene assessment consequently abstains, a material limitation. Bank last four is a weak relationship, never proof of identity. Policy, DOB, licence, address, RTO and FIR declarations have no authoritative external verification. No field is artificially forced into risk. Image labels do not authenticate views or same vehicle.\n',encoding='utf8')
 checkrows=[]
 for key,c in REGISTRY.items():
  kinds=[k for k in ['claims','underwriting'] if key in production_policy(k).check_ids]
  testrefs=[]
  for testfile in ROOT.glob('test_*.py'):
   if testfile.name=='test_api_connectivity.py':continue
   try:testtree=ast.parse(testfile.read_text(encoding='utf-8-sig'))
   except (SyntaxError,UnicodeError):continue
   for node in testtree.body:
    if isinstance(node,ast.FunctionDef) and node.name.startswith('test_'):
     text=ast.get_source_segment(testfile.read_text(encoding='utf-8-sig'),node) or ''
     if key in text or type(c).__name__ in text:testrefs.append(testfile.name+'::'+node.name)
  checkrows.append([key,', '.join(kinds) or 'outside production policy',c.weight,c.attributed_to,str(c.requires_perception),json.dumps(rule_parameters(key,c,{})),(getattr(c,'limitation','') or 'Heuristic; independent verification unavailable')+' Source: '+type(c).__module__+'.'+type(c).__name__+'; test references: '+('; '.join(testrefs) or 'No direct named test reference found')])
 (DOC/'CHECK_VERIFICATION_MATRIX.md').write_text('# Check policy and verification matrix\n\n'+table(['Check','Case types','Research weight','Attribution','Needs perception','Exact configured defaults/formulas','Limitation'],checkrows)+'\nVerification commands/results: `ASSESSMENT_EVALUATION.md`. `test_checks.py`, `test_severity_chronology.py`, `test_analysis_recovery.py`, `test_engine_reliability.py` and `test_postgres.py` exercise controlled target/control/missing/error, boundaries, chronology and saved-run paths. This does not imply each detector has independent accuracy evidence. Missing EXIF/C2PA is inconclusive; invalid C2PA integrity versus trust failures is classified separately. Local corpus lookup is not internet reverse search. Similar appearance alone is not proof of reuse. Earlier duplicates do not establish victims. Temporal/panel comparisons need repaired-condition context; clean baseline followed by damage is not fraud by itself. Zero-weight view/baseline/edit/AI observations remain experimental. A fabricated baseline cannot be authenticated without trusted original evidence.\n',encoding='utf8')

if __name__=='__main__':build()
