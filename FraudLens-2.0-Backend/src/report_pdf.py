"""Private, immutable PDF artifacts rendered only from saved report snapshots.

No model invocation lives here. PDF bytes are stored in the configured database,
so a browser download does not depend on the backend host's temporary filesystem.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from importlib.util import find_spec
from io import BytesIO
import json
from pathlib import Path
import re
import time
from xml.sax.saxutils import escape

from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from . import db, runtime_store

RENDERER_VERSION = "fraudlens-pdf-2026-10-18-v1"
ARTIFACT_SCHEMA = """CREATE TABLE IF NOT EXISTS report_artifacts (
    snapshot_id TEXT PRIMARY KEY REFERENCES report_snapshots(snapshot_id),
    renderer_version TEXT NOT NULL, pdf_base64 TEXT, sha256 TEXT,
    created_at REAL, error_type TEXT)"""

CHECK_PURPOSES = {
    'internal_duplicate': 'Compare submitted photographs with the indexed internal evidence corpus.',
    'external_corpus': 'Look for matching photographs in the configured external reference corpus.',
    'exif_metadata': 'Examine extracted capture metadata and its availability or consistency.',
    'c2pa_credentials': 'Inspect available content provenance credentials; absence is not proof of manipulation.',
    'plate_ocr': 'Compare readable registration text with the applicant declaration.',
    'scene_consistency': 'Compare available time, place, weather and scene observations.',
    'damage_plausibility': 'Assess whether recorded damage observations support the incident account.',
    'threshold_gaming': 'Summarize the repairing garage billing pattern against a research benchmark.',
    'entity_graph': 'Inspect recorded identifier relationships; a relationship does not establish intent.',
    'baseline_linkage': 'Compare linked underwriting and claims evidence where a baseline exists.',
    'severity_progression': 'Compare recorded damage severity across linked observations.',
    'view_completeness': 'Inspect declared photographic coverage; view labels require verification.',
    'baseline_corruption': 'Inspect observations against the actual underwriting declaration.',
    'ai_generation': 'Experimental synthetic-image screening, excluded where its weight is zero.',
    'digital_edit': 'Experimental editing screening, excluded where its weight is zero.',
}


class ReportVersionOut(BaseModel):
    snapshot_id: str
    run_id: str | None = None
    snapshot_created_at: float
    pdf_status: str
    generated_at: float | None = None
    renderer_version: str | None = None
    sha256: str | None = None


class ReportVersionsOut(BaseModel):
    reports: list[ReportVersionOut]


def init_schema(conn):
    if not db.is_postgres(conn):
        conn.execute(ARTIFACT_SCHEMA)


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def enrich_snapshot(conn, report):
    """Freeze inventory and check coverage alongside the existing immutable JSON."""
    from .api import _resolve_data_path
    from .agent.production_policy import production_policy
    from .checks import REGISTRY
    from PIL import Image, ImageOps
    case = db.get_case(conn, report['case_id'])
    report['submitted_at'] = _iso(case.created_at)
    wanted = set(report.get('evidence_ids', []))
    result = runtime_store.current_result(conn,case.case_id)
    inventory = []
    for image in db.get_images_for_case(conn, case.case_id):
        if image.image_id not in wanted:
            continue
        item = {'image_id': image.image_id, 'label': f'Photograph {len(inventory) + 1}',
                'uploaded_at': _iso(image.created_at), 'sha256': image.content_hash,
                'considered_in_run': bool(result)}
        # Freeze a small derivative, never a host path or mutable cached vision.
        try:
            path = _resolve_data_path(image.path)
            with Image.open(path) as original:
                item['width'], item['height'] = original.size
                thumb = ImageOps.exif_transpose(original).convert('RGB')
                thumb.thumbnail((500, 340))
                buffer = BytesIO(); thumb.save(buffer, 'JPEG', quality=78)
                item['thumbnail_base64'] = base64.b64encode(buffer.getvalue()).decode()
        except Exception:
            item['thumbnail_unavailable'] = True
        # EXIF is extracted evidence, not independent proof of capture time/place.
        metadata = {key: image.exif[key] for key in ('DateTimeOriginal', 'Make', 'Model', 'Software')
                    if key in image.exif and isinstance(image.exif[key], (str, int, float))}
        if metadata:
            item['extracted_metadata'] = metadata
        inventory.append(item)
    report['evidence_inventory'] = inventory
    policy = production_policy(case.agent_type)
    applicable = set(policy.check_ids)
    findings = [f for values in report.get('findings_by_category', {}).values() for f in values]
    coverage = []
    for check_id, check in REGISTRY.items():
        recorded = [f for f in findings if f['check_id'] == check_id]
        if recorded:
            state = ('failed' if any(f.get('evidence', {}).get('error_type') or f.get('evidence', {}).get('error') for f in recorded)
                     else 'inconclusive' if any(f['verdict'] == 'inconclusive' for f in recorded) else 'completed')
        else:
            state = 'not_applicable' if report.get('policy_version') == policy.policy_version and check_id not in applicable else 'not_run'
        coverage.append({'check_id': check_id, 'purpose': CHECK_PURPOSES.get(check_id, 'Inspect recorded case evidence using this registered check.'),
                         'state': state, 'finding_ids': [f['finding_id'] for f in recorded],
                         'limitation': check.limitation or None})
    report['check_inventory'] = coverage
    return report


def _font_names():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if 'FraudLens' not in pdfmetrics.getRegisteredFontNames():
        spec = find_spec('matplotlib')
        roots = [Path(spec.origin).parent / 'mpl-data/fonts/ttf'] if spec and spec.origin else []
        roots += [Path('/usr/share/fonts/truetype/dejavu')]
        root = next((p for p in roots if (p / 'DejaVuSans.ttf').is_file()), None)
        if root is None:
            raise RuntimeError('Unicode PDF fonts unavailable')
        pdfmetrics.registerFont(TTFont('FraudLens', str(root / 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('FraudLens-Bold', str(root / 'DejaVuSans-Bold.ttf')))
    return 'FraudLens', 'FraudLens-Bold'


def _display(value):
    if value is None or value == '':
        return 'Not recorded'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _timestamp(value):
    try:
        instant = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return instant.astimezone(timezone.utc).strftime('%d %b %Y, %H:%M:%S UTC')
    except (ValueError, TypeError):
        return _display(value)


def render_pdf(report, snapshot_id, generated_at):
    """Render recorded facts with deterministic prose; missing inputs remain missing."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, Table, TableStyle, Image
    regular, bold = _font_names()
    navy = colors.HexColor('#172e38'); teal = colors.HexColor('#167c72'); pale = colors.HexColor('#eef5f4')
    styles = {
        'body': ParagraphStyle('body', fontName=regular, fontSize=9, leading=13, textColor=navy, spaceAfter=7, splitLongWords=True),
        'small': ParagraphStyle('small', fontName=regular, fontSize=7.4, leading=10.5, textColor=navy, spaceAfter=4, splitLongWords=True),
        'title': ParagraphStyle('title', fontName=bold, fontSize=25, leading=31, textColor=navy, spaceAfter=10),
        'h1': ParagraphStyle('h1', fontName=bold, fontSize=14, leading=19, textColor=teal, spaceBefore=14, spaceAfter=8, keepWithNext=True),
        'h2': ParagraphStyle('h2', fontName=bold, fontSize=10, leading=14, textColor=navy, spaceBefore=8, spaceAfter=6, keepWithNext=True),
    }
    def p(value, style='body'):
        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', _display(value))
        return Paragraph(escape(value).replace('\n', '<br/>'), styles[style])
    story = []
    width = A4[0] - 34 * mm
    def section(title):
        story.append(p(title, 'h1'))
    def table(headers, rows, widths=None):
        data = [[p(h, 'small') for h in headers]] + [[p(v, 'small') for v in row] for row in rows]
        t = LongTable(data, colWidths=widths, repeatRows=1, hAlign='LEFT', splitInRow=1)
        t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), pale), ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LINEBELOW', (0,0), (-1,0), 0.7, teal), ('LINEBELOW', (0,1), (-1,-1), 0.3, colors.HexColor('#dbe4e4')),
            ('LEFTPADDING', (0,0), (-1,-1), 7), ('RIGHTPADDING', (0,0), (-1,-1), 7),
            ('TOPPADDING', (0,0), (-1,-1), 7), ('BOTTOMPADDING', (0,0), (-1,-1), 7)]))
        story.append(t)
    declaration = report.get('declaration') or {}
    processing = report.get('processing') or {}
    recommendation = report.get('agent_recommendation') or {}
    human = report.get('admin_action') or {}
    findings = [f for fs in report.get('findings_by_category', {}).values() for f in fs]
    inventory = report.get('evidence_inventory') or []
    state = processing.get('status') or 'unrecorded (legacy)'
    partial = state not in {'completed','done'} or recommendation.get('provider_unavailable')
    story += [p('FraudLens', 'title'), p('EVIDENCE REVIEW · ' + declaration.get('agent_type', 'case').upper(), 'h2'),
              p('Partial analysis · human review required' if partial else 'Recorded analysis · human review required', 'h1')]
    table(['REPORT IDENTITY', 'RECORDED VALUE'], [
        ('Case', report['case_id']), ('Report / snapshot version', snapshot_id),
        ('Analysis run', report.get('run_id') or 'Legacy result without run association'),
        ('Submitted', _timestamp(report.get('submitted_at'))), ('PDF generated', _timestamp(generated_at)),
        ('Analysis completion', state), ('Renderer', RENDERER_VERSION)], [width*.29, width*.71])
    section('Executive summary')
    story.append(p(f"{declaration.get('person_name') or 'The applicant'} submitted a {declaration.get('agent_type') or 'case'} application for {declaration.get('vehicle_registration') or 'a vehicle without a recorded registration'}. The recorded analysis inventory contains {len(report.get('evidence_ids', []))} photograph(s) and {len(findings)} finding(s). Applicant declarations are statements to be reviewed; they are not independently verified facts."))
    concerns = [f for f in findings if f.get('verdict') == 'concern']
    incomplete = [f for f in findings if f.get('verdict') == 'inconclusive']
    cards = Table([[p('Supported concerns\n' + str(len(concerns)), 'h2'), p('Inconclusive findings\n' + str(len(incomplete)), 'h2'), p('Automated routing\n' + (recommendation.get('recommendation') or 'Unavailable'), 'h2')]], colWidths=[width/3]*3)
    cards.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#dbe4e4')),('LEFTPADDING',(0,0),(-1,-1),10)])); story.append(cards); story.append(Spacer(1,3*mm))
    if partial:
        story.append(p('Automated processing did not fully complete. Saved findings and any fallback recommendation do not establish a successful model assessment. ' + _display(processing.get('detail'))))
    story.append(p('Automated recommendations and human decisions are separate. No score in this report is a calibrated fraud probability. A human approval does not prove absence of fraud.'))
    section('Application details · applicant statements')
    labels = {'idv':'Insured declared value (INR)', 'claim_amount':'Claim amount (INR)', 'declaration_notes':'Applicant narrative / declarations', 'incident_date':'Declared incident time'}
    table(['FIELD', 'SUBMITTED VALUE'], [(labels.get(k,k.replace('_',' ').title()),_display(v)) for k,v in declaration.items() if v is not None and v != '' and k not in {'case_id','status'}], [width*.32,width*.68])
    section('Evidence inventory · this analysis run')
    if not inventory:
        story.append(p('This historical snapshot does not contain a frozen image inventory. Recorded evidence IDs: ' + ', '.join(report.get('evidence_ids', [])) + '. Thumbnails and extracted metadata are unavailable for this report version.'))
    for item in inventory:
        title = f"{item.get('label','Photograph')} · {item.get('image_id')}"
        story.append(p(title, 'h2'))
        if item.get('thumbnail_base64'):
            picture = Image(BytesIO(base64.b64decode(item['thumbnail_base64'])))
            picture._restrictSize(width, 65*mm)
            story.append(picture); story.append(Spacer(1, 3*mm))
        else:
            story.append(p('Thumbnail unavailable in the saved snapshot.'))
        basis = 'Included in the recorded analysis inventory.' if item.get('considered_in_run') else 'Available at this snapshot; no completed analysis inventory was recorded.'
        story.append(p('Uploaded: ' + _timestamp(item.get('uploaded_at')) + ' · ' + basis + '\nSHA-256: ' + _display(item.get('sha256')), 'small'))
        if item.get('extracted_metadata'):
            story.append(p('Extracted metadata (not independently authenticated): ' + _display(item['extracted_metadata']), 'small'))
    section('Check coverage')
    coverage = report.get('check_inventory') or []
    if coverage:
        table(['CHECK', 'EXECUTION STATE', 'FINDINGS'], [(c['check_id'],c['state'].replace('_',' '),len(c['finding_ids'])) for c in coverage], [width*.43,width*.37,width*.2])
        story.append(p('Completed describes execution, not a clean verdict. Inconclusive includes missing inputs. Failed means a recorded check error. Not run has no saved result. Not applicable means excluded by the recorded case-type policy.', 'small'))
    else:
        story.append(p('Check coverage was not frozen in this historical snapshot. Only saved findings below can be reported; absence of a finding does not establish that a check passed.'))
    section('Detailed recorded results')
    for finding in findings:
        check_id = finding['check_id']; observed = finding.get('evidence') or {}
        story.append(p(check_id.replace('_',' ').title() + ' · ' + finding.get('verdict','unrecorded').upper(), 'h2'))
        purpose = next((c['purpose'] for c in coverage if c['check_id']==check_id), CHECK_PURPOSES.get(check_id, 'Inspect recorded case evidence.'))
        story += [p('Purpose: ' + purpose), p(finding.get('explanation')),
                  p('Finding: ' + finding.get('finding_id','unrecorded') + ' · Attributed to: ' + finding.get('attributed_to','unrecorded'), 'small')]
        if observed:
            # Deliberately omit raw exception strings: these can contain local paths.
            safe = {k:v for k,v in observed.items() if k not in {'error','traceback','stack_trace'}}
            table(['OBSERVED VALUE / EVIDENCE', 'RECORDED DETAIL'], [(k.replace('_',' '),_display(v)) for k,v in safe.items()], [width*.34,width*.66])
        else:
            story.append(p('No structured supporting values were saved with this finding.', 'small'))
        if finding.get('check_limitation'):
            story.append(p('Limitation: ' + finding['check_limitation']))
    if not findings:
        story.append(p('No findings were saved for this run. This is an evidence gap, not a clean result.'))
    section('Case narrative and next steps')
    if declaration.get('declaration_notes'):
        story.append(p('Applicant statement: ' + declaration['declaration_notes']))
    if report.get('agent_narrative'):
        label = 'Recorded fallback narrative' if recommendation.get('provider_unavailable') else 'Recorded model / agent interpretation'
        story.append(p(label + ': ' + report['agent_narrative']))
    else:
        story.append(p('Deterministic narrative: the application and available photographs were saved. The recorded checks are listed above. No completed automated interpretation is available; a reviewer must assess the evidence and any missing information.'))
    for finding in concerns:
        story.append(p('Recorded concern (' + finding['check_id'] + ', attributed to ' + finding.get('attributed_to','unrecorded') + '): ' + finding['explanation']))
    requested = recommendation.get('requested_artifacts') or []
    if requested:
        for artifact in requested:
            story.append(p('Requested follow-up: ' + artifact))
    elif incomplete or partial:
        story.append(p('Reviewer action: inspect the unavailable or inconclusive checks and request the specific missing evidence needed to resolve them. No unrecorded follow-up request is implied.'))
    else:
        story.append(p('Reviewer action: corroborate the recorded findings and record an accountable approval, rejection or evidence request separately.'))
    section('Human decision · at this report version')
    if human:
        table(['DECISION RECORD', 'VALUE'], [('Action',human.get('action')),('Reviewer',human.get('admin_id')),('Recorded',_timestamp(human.get('timestamp'))),('Internal reviewer reason',human.get('reason')),('Reviewed run',human.get('reviewed_run_id')),('Reviewed evidence IDs',human.get('reviewed_evidence_ids'))], [width*.32,width*.68])
        story.append(p('This section records the action present in this immutable snapshot. Later decisions are separate report versions; the original analysis is preserved.'))
    else:
        story.append(p('No human decision was recorded in this report version.'))
    section('Provenance and material limitations')
    table(['PROVENANCE', 'RECORDED VALUE'], [('Agent policy',report.get('policy_version')),('Run started',_timestamp(processing.get('started_at'))),('Run updated',_timestamp(processing.get('updated_at'))),('Check revision',processing.get('checks_revision')),('Provider request profile',processing.get('provider_request_profile')),('Vision sources',processing.get('perception_sources')),('Agent response sources',processing.get('adjudication_sources')),('Processing error type',processing.get('error_type'))], [width*.32,width*.68])
    for limitation in dict.fromkeys(report.get('limitations') or []):
        story.append(p('• ' + limitation))
    story.append(p('This report is generated from a saved run-specific snapshot. Opening or downloading it does not rerun AI, OCR or checks. The evidence review does not determine claimant intent or guarantee detection accuracy.'))
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=17*mm, leftMargin=17*mm, topMargin=22*mm, bottomMargin=20*mm, title='FraudLens evidence report — '+report['case_id'], author='FraudLens')
    def page(canvas, _doc):
        canvas.saveState(); canvas.setFillColor(teal); canvas.rect(0,A4[1]-7*mm,A4[0],7*mm,fill=1,stroke=0)
        canvas.setFont(bold,8); canvas.setFillColor(navy); canvas.drawString(17*mm,A4[1]-15*mm,'FRAUDLENS  /  PRIVATE EVIDENCE REVIEW')
        canvas.setFont(regular,7); canvas.drawString(17*mm,12*mm,report['case_id'][:65] + ' · ' + snapshot_id[:12]); canvas.drawRightString(A4[0]-17*mm,12*mm,f'Page {_doc.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()


def _metadata(row, artifact=None):
    artifact = dict(artifact) if artifact else {}
    return {'snapshot_id':row['snapshot_id'], 'run_id':row['run_id'], 'snapshot_created_at':row['created_at'],
            'pdf_status':'ready' if artifact.get('pdf_base64') else 'failed' if artifact.get('error_type') else 'pending',
            'generated_at':artifact.get('created_at'), 'renderer_version':artifact.get('renderer_version'),
            'sha256':artifact.get('sha256')}


def install(app):
    from .api import ApiError, _snapshot_report, get_conn, require_admin

    @app.get('/v1/cases/{case_id}/reports', response_model=ReportVersionsOut, tags=['cases'])
    def list_reports(case_id: str, _admin: str = Depends(require_admin), conn=Depends(get_conn)):
        if not db.get_case(conn,case_id):
            raise ApiError(404,'CASE_NOT_FOUND','Case not found.')
        rows = conn.execute('SELECT snapshot_id,run_id,created_at FROM report_snapshots WHERE case_id=? ORDER BY rowid DESC',(case_id,)).fetchall()
        return {'reports':[_metadata(row,conn.execute('SELECT * FROM report_artifacts WHERE snapshot_id=?',(row['snapshot_id'],)).fetchone()) for row in rows]}

    @app.post('/v1/cases/{case_id}/reports/prepare', response_model=ReportVersionOut, tags=['cases'])
    def prepare_report(case_id: str, snapshot_id: str | None = Query(default=None), _admin: str = Depends(require_admin), conn=Depends(get_conn)):
        if not db.get_case(conn,case_id):
            raise ApiError(404,'CASE_NOT_FOUND','Case not found.')
        conn.execute('BEGIN IMMEDIATE'); db.lock_case(conn,case_id)
        if snapshot_id is None:
            job = runtime_store.latest_job(conn,case_id)
            if job and job['status'] in {'queued','running'}:
                raise ApiError(409,'REPORT_PENDING','Analysis is still running. Saved historical versions remain available.')
            snapshot_id = _snapshot_report(conn,case_id)
        row = conn.execute('SELECT * FROM report_snapshots WHERE case_id=? AND snapshot_id=?',(case_id,snapshot_id)).fetchone()
        if not row:
            raise ApiError(404,'REPORT_NOT_FOUND','Report version not found for this case.')
        artifact = conn.execute('SELECT * FROM report_artifacts WHERE snapshot_id=?',(snapshot_id,)).fetchone()
        payload = json.loads(row['payload']); conn.commit()
        if artifact and artifact['pdf_base64']:
            return _metadata(row,artifact)
        created = time.time()
        try:
            content = render_pdf(payload,snapshot_id,created)
            checksum = hashlib.sha256(content).hexdigest()
            conn.execute('INSERT INTO report_artifacts(snapshot_id,renderer_version,pdf_base64,sha256,created_at,error_type) VALUES (?,?,?,?,?,NULL) ON CONFLICT(snapshot_id) DO UPDATE SET renderer_version=excluded.renderer_version,pdf_base64=excluded.pdf_base64,sha256=excluded.sha256,created_at=excluded.created_at,error_type=NULL WHERE report_artifacts.pdf_base64 IS NULL',
                         (snapshot_id,RENDERER_VERSION,base64.b64encode(content).decode(),checksum,created))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.execute('INSERT INTO report_artifacts(snapshot_id,renderer_version,created_at,error_type) VALUES (?,?,?,?) ON CONFLICT(snapshot_id) DO UPDATE SET error_type=excluded.error_type WHERE report_artifacts.pdf_base64 IS NULL', (snapshot_id,RENDERER_VERSION,created,type(exc).__name__))
            conn.commit()
            raise ApiError(503,'PDF_GENERATION_FAILED','PDF generation failed. The saved analysis is intact; retry report generation without rerunning analysis.') from exc
        artifact = conn.execute('SELECT * FROM report_artifacts WHERE snapshot_id=?',(snapshot_id,)).fetchone()
        return _metadata(row,artifact)

    @app.get('/v1/cases/{case_id}/reports/{snapshot_id}/pdf', tags=['cases'])
    def download_report(case_id: str, snapshot_id: str, download: bool = Query(default=False), _admin: str = Depends(require_admin), conn=Depends(get_conn)):
        row = conn.execute('SELECT a.* FROM report_artifacts a JOIN report_snapshots s ON s.snapshot_id=a.snapshot_id WHERE a.snapshot_id=? AND s.case_id=?',(snapshot_id,case_id)).fetchone()
        if not row or not row['pdf_base64']:
            raise ApiError(404,'PDF_NOT_READY','Generate this saved report before opening its PDF.')
        filename = 'FraudLens-' + re.sub(r'[^A-Za-z0-9_-]','_',case_id)[:85] + '-' + snapshot_id[:12] + '.pdf'
        return Response(base64.b64decode(row['pdf_base64']),media_type='application/pdf',headers={
            'Content-Disposition':('attachment' if download else 'inline') + '; filename="' + filename + '"',
            'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff', 'ETag':'"'+row['sha256']+'"'})
