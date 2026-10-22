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

LEGACY_RENDERER_VERSION = "fraudlens-pdf-2026-10-18-v1"
READER_V2_VERSION = "fraudlens-pdf-2026-10-20-v2"
READER_V3_VERSION = "fraudlens-pdf-2026-10-21-v3"
READER_V4_VERSION = "fraudlens-pdf-2026-10-21-v4"
RENDERER_VERSION = "fraudlens-pdf-2026-10-22-v5"
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
            explicit = [f.get('evidence',{}).get('execution_state') for f in recorded]
            state = ('failed' if 'failed' in explicit or any(f.get('evidence', {}).get('error_type') or f.get('evidence', {}).get('error') for f in recorded)
                     else 'not_applicable' if all(value=='not_applicable' for value in explicit)
                     else 'not_run' if all(value=='not_run' for value in explicit)
                     else 'inconclusive' if 'inconclusive' in explicit or any(f['verdict'] == 'inconclusive' for f in recorded) else 'completed')
        else:
            state = 'not_applicable' if report.get('policy_version') == policy.policy_version and check_id not in applicable else 'not_run'
        coverage.append({'check_id': check_id, 'applicable': check_id in applicable, 'category': check.category.value,
                         'purpose': CHECK_PURPOSES.get(check_id, 'Inspect recorded case evidence using this registered check.'),
                         'state': state, 'finding_ids': [f['finding_id'] for f in recorded],
                         'limitation': check.limitation or None})
    report['check_inventory'] = coverage
    # Only database-owned internal references are eligible for a frozen image.
    # Never open a filename/path supplied by a finding or an external corpus.
    comparisons = []
    matched_ids = list(dict.fromkeys(f.get('evidence', {}).get('matched_image_id') for f in findings
                                   if f.get('check_id') == 'internal_duplicate' and isinstance(f.get('evidence', {}).get('matched_image_id'),str) and f['evidence']['matched_image_id']))
    for image_id in matched_ids[:8]:
        row = conn.execute('SELECT path,case_id FROM images WHERE image_id=?', (image_id,)).fetchone()
        if not row:
            continue
        item = {'image_id': image_id, 'case_id': row['case_id'], 'label': 'Internal reference', 'access_basis': 'reviewer_only'}
        try:
            with Image.open(_resolve_data_path(row['path'])) as original:
                thumb = ImageOps.exif_transpose(original).convert('RGB'); thumb.thumbnail((500, 340))
                buffer = BytesIO(); thumb.save(buffer, 'JPEG', quality=78)
                item['thumbnail_base64'] = base64.b64encode(buffer.getvalue()).decode()
        except Exception:
            item['thumbnail_unavailable'] = True
        comparisons.append(item)
    report['comparison_evidence'] = comparisons
    from .risk_presentation import assessment_presentation
    report['assessment_presentation'] = assessment_presentation(report)
    report['report_template_version'] = RENDERER_VERSION
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


def _render_pdf_v1(report, snapshot_id, generated_at):
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
        ('Analysis completion', state), ('Renderer', LEGACY_RENDERER_VERSION)], [width*.29, width*.71])
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


CHECK_LABELS = {
    'internal_duplicate':'Internal photograph reuse','external_corpus':'External photograph matches',
    'exif_metadata':'Capture metadata','c2pa_credentials':'Content credentials','plate_ocr':'Registration reading',
    'scene_consistency':'Scene, time and place','damage_plausibility':'Damage and claimed amount',
    'threshold_gaming':'Garage billing pattern','entity_graph':'Shared identifiers','baseline_linkage':'Earlier inspection link',
    'severity_progression':'Damage history','view_completeness':'Photographic coverage',
    'baseline_corruption':'Experimental baseline check','ai_generation':'Experimental synthetic image check',
    'digital_edit':'Experimental image editing check',
}


def _render_pdf_v2(report, snapshot_id, generated_at, keep_headings=False):
    """Reader-first report; technical identifiers stay in an optional appendix."""
    from collections import defaultdict, Counter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, Table, TableStyle, Image, KeepTogether, PageBreak
    regular,bold = _font_names()
    ink=colors.HexColor('#17313a'); teal=colors.HexColor('#14786d'); pale=colors.HexColor('#eef5f3')
    width=A4[0]-32*mm
    styles={
        'body':ParagraphStyle('reader-body',fontName=regular,fontSize=9,leading=12.5,textColor=ink,spaceAfter=5,splitLongWords=True),
        'small':ParagraphStyle('reader-small',fontName=regular,fontSize=7.5,leading=10.5,textColor=ink,spaceAfter=3,splitLongWords=True),
        'title':ParagraphStyle('reader-title',fontName=bold,fontSize=23,leading=28,textColor=ink,spaceAfter=7),
        'h1':ParagraphStyle('reader-section',fontName=bold,fontSize=12,leading=16,textColor=teal,spaceBefore=10,spaceAfter=6),
        'h2':ParagraphStyle('reader-label',fontName=bold,fontSize=9,leading=12,textColor=ink,spaceAfter=4),
    }
    if keep_headings:
        styles['h1'].keepWithNext = True
    declaration=report.get('declaration') or {}; processing=report.get('processing') or {}
    agent=report.get('agent_recommendation') or {}; human=report.get('admin_action') or {}
    human_current = bool(human.get('reviewed_run_id') and human.get('reviewed_run_id')==report.get('run_id'))
    human_earlier = bool(human.get('reviewed_run_id') and report.get('run_id') and not human_current)
    explanation=report.get('assessment_explanation') or {}
    inventory=report.get('evidence_inventory') or []
    findings=[f for values in report.get('findings_by_category',{}).values() for f in values]
    labels={item['image_id']:item.get('label') or f'Photograph {index+1}' for index,item in enumerate(inventory)}
    technical=False
    def clean(value):
        text=_display(value)
        for identifier,label in labels.items():
            if len(identifier)>=8:
                text=text.replace(identifier,label)
        text=re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b','[recorded reference]',text)
        return re.sub(r'\b[0-9a-fA-F]{32,64}\b','[recorded reference]',text)
    def p(value,style='body'):
        text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',_display(value) if technical else clean(value))
        return Paragraph(escape(text).replace('\n','<br/>'),styles[style])
    story=[]
    def section(title): story.append(p(title,'h1'))
    def table(headers,rows,widths):
        if not rows:return
        data=[[p(value,'h2') for value in headers]]+[[p(value,'small') for value in row] for row in rows]
        grid=LongTable(data,colWidths=widths,repeatRows=1,splitInRow=1,hAlign='LEFT')
        grid.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.6,teal),('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#dbe4e0')),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.append(grid)
    def label(check_id):return CHECK_LABELS.get(check_id,check_id.replace('_',' ').title())
    status=processing.get('status') or 'unrecorded'
    recorded_convergence=(explanation.get('routing') or {}).get('converged')
    operational_partial=status not in {'completed','done'}
    interpretation_unavailable = agent.get('provider_unavailable') or recorded_convergence is False or (recorded_convergence is None and operational_partial)
    coverage_partial = (explanation.get('coverage') or {}).get('material_complete') is False
    partial=operational_partial or interpretation_unavailable or coverage_partial
    completion = 'Partial analysis' if partial else 'Recorded analysis'
    review_state = 'human decision recorded' if human_current else 'human review required'
    story += [p('FraudLens','title'),p((declaration.get('agent_type') or 'Case').title()+' evidence review','h2'),
              p(completion+' · '+review_state,'h1'),
              p(f"Case {report['case_id']} · Submitted {_timestamp(report.get('submitted_at'))} · Report {_timestamp(generated_at)}",'small')]
    if human:
        human_label='Human decision for this analysis: ' if human_current else 'Historical human decision (earlier analysis): ' if human_earlier else 'Historical human decision (review basis unrecorded): '
        story.append(p(human_label+str(human.get('action') or 'unrecorded').replace('_',' '),'h2'))
        if not human_current:
            story.append(p('This new assessment has not received that decision. A reviewer must assess its current findings and evidence.' if human_earlier else 'The analysis and evidence basis of this older decision was not recorded. It cannot be treated as approval or rejection of this assessment.'))
    story.append(p(f"{len(inventory) or len(report.get('evidence_ids',[]))} photograph(s) available. Automated routing: "+str((explanation.get('routing') or {}).get('recorded_band') or agent.get('risk_band') or 'unavailable').replace('_',' ')+'.'))
    principal=list(dict.fromkeys(label(item['check_id']) for item in findings if item.get('verdict')=='concern'))
    story.append(p('Principal recorded concerns: '+', '.join(principal)+'.' if principal else 'No concerning finding was recorded. Missing or unavailable checks still require review.'))
    if partial:
        story.append(p('Automated interpretation is unavailable or incomplete. Saved rule findings remain available; missing analysis has not been marked as passed. A reviewer must decide whether the available evidence is sufficient.' if interpretation_unavailable else 'The recorded automated routing is available, with qualified missing inputs in some checks. Inconclusive evidence has not been marked as passed; review the unresolved inputs below.'))
    story.append(p('Automated routing is separate from human approval or rejection. Scores are not calibrated fraud probabilities.'))
    section('Submitted facts · applicant statements')
    field_labels={'person_name':'Applicant','person_contact':'Contact','person_dob':'Date of birth','person_address':'Address',
        'policy_number':'Policy / application reference','policy_type':'Policy type','policy_start_date':'Policy starts','policy_end_date':'Policy ends',
        'vehicle_registration':'Registration','vehicle_make':'Make','vehicle_model':'Model','vehicle_variant':'Variant','vehicle_year':'Year',
        'fuel_type':'Fuel','engine_number':'Engine reference','chassis_number':'Chassis reference','rto':'Registration office',
        'idv':'Insured value (INR)','claim_amount':'Claimed amount (INR)','declared_location':'Incident location',
        'incident_date':'Declared incident time','settlement_preference':'Settlement preference','fir_number':'FIR reference',
        'driving_license_number':'Driving licence','previous_policy_number':'Previous policy','policy_ncb_percent':'Declared no-claim bonus (%)','bank_account_last4':'Bank account last four digits'}
    facts=[(title,declaration[key]) for key,title in field_labels.items() if declaration.get(key) is not None and declaration.get(key)!='']
    table(['FIELD','SUBMITTED VALUE'],facts,[width*.30,width*.70])
    if declaration.get('declaration_notes'):
        story += [p('Applicant narrative / declarations','h2'),p(declaration['declaration_notes'])]
    section('Labeled photographs')
    if inventory:
        cells=[]
        for item in inventory:
            content=[p(item.get('label') or 'Photograph','h2')]
            if item.get('thumbnail_base64'):
                picture=Image(BytesIO(base64.b64decode(item['thumbnail_base64'])))
                picture._restrictSize(width/2-12*mm,39*mm);content.append(picture)
            else:content.append(p('Thumbnail unavailable in this saved report.','small'))
            content.append(p('Included in this analysis.' if item.get('considered_in_run') else 'Available; no completed analysis inventory was recorded.','small'))
            cells.append(content)
        rows=[cells[index:index+2]+([[]] if len(cells[index:index+2])==1 else []) for index in range(0,len(cells),2)]
        gallery=Table(rows,colWidths=[width/2,width/2],hAlign='LEFT')
        gallery.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(gallery)
    else:story.append(p('No frozen thumbnails were saved with this report version.'))
    section('Main findings')
    groups=defaultdict(list)
    for finding in findings:groups[finding['check_id']].append(finding)
    coverage=report.get('check_inventory') or []
    result_rows=[]
    for check_id,group in groups.items():
        states=Counter()
        for item in group:
            observed=item.get('evidence') or {};execution=observed.get('execution_state')
            state=execution if execution in {'failed','not_run','not_applicable'} else 'failed' if observed.get('error_type') or observed.get('error') else item.get('verdict','unrecorded')
            states[state]+=1
        result=', '.join(f'{count} {state.replace("_"," ")}' for state,count in states.items())
        texts=[];concern_texts=[]
        for finding in sorted(group,key=lambda item:item.get('verdict')!='concern'):
            text=clean(finding.get('explanation'))
            if text not in texts:texts.append(text)
            if finding.get('verdict')=='concern' and text not in concern_texts:concern_texts.append(text)
        # Repeated image findings are grouped here. Their exact values remain
        # in the persisted explanation and optional technical appendix.
        shown=concern_texts+[text for text in texts if text not in concern_texts][:2]
        detail=' '.join(shown)
        if len(texts)>len(shown):detail+=f' {len(texts)-len(shown)} additional non-concern observation(s) are retained in the saved findings.'
        result_rows.append((label(check_id),result,detail))
    if result_rows:table(['CHECK','RECORDED RESULT','OBSERVATION / LIMITATION'],result_rows,[width*.23,width*.19,width*.58])
    else:story.append(p('No completed findings were saved for this run. This is an evidence gap, not a clean result.'))
    states=Counter(item.get('state','not_run') for item in coverage)
    if states:story.append(p('Check coverage: '+', '.join(f'{count} {state.replace("_"," ")}' for state,count in states.items())+'. Completed describes execution, not a clean verdict.','small'))
    section('How the assessment was calculated')
    if not explanation:
        story.append(p('A structured calculation explanation was not recorded when this analysis ran. This report does not reconstruct a historical score or invent a contribution for missing checks.'))
    else:
        aggregation=explanation.get('aggregation') or {};routing=explanation.get('routing') or {}
        story.append(p(aggregation.get('rule')))
        if aggregation.get('valid_numeric_score'):
            story.append(p('Recorded heuristic score: '+str(aggregation['computed_value'])+'. This unbounded score is not a probability.'))
            if aggregation.get('band_comparison_basis')=='unrounded_concern_sum' and aggregation.get('unrounded_value') is not None:
                story.append(p('The saved score is rounded to '+str(aggregation.get('rounding_places',4))+' decimal places. Routing compares the unrounded concern sum ('+repr(aggregation['unrounded_value'])+') with the thresholds.','small'))
                if aggregation.get('matches_recorded_band') is False:
                    story.append(p('The reproduced threshold band differs from the recorded routing band. The recorded decision is preserved; this discrepancy requires review.','small'))
            thresholds=aggregation.get('thresholds') or {}
            story.append(p('Routing thresholds: clear below '+str(thresholds.get('clear_below'))+'; request evidence below '+str(thresholds.get('request_evidence_below'))+'; desk review below '+str(thresholds.get('desk_review_below'))+'; investigation at or above the final threshold.','small'))
        elif aggregation.get('method')=='weighted_concern_sum':story.append(p('Numeric score unavailable: the saved value could not be verified against the recorded contributions. No replacement score is invented.'))
        else:story.append(p('Numeric score: not computed. The recorded agent routing must not be presented as a weighted sum or a fraud percentage.'))
        calculations=defaultdict(list)
        for row in explanation.get('findings',[]):calculations[row['check_id']].append(row)
        calc_rows=[]
        observed_keys=('cosine_similarity','hamming_distance','plate_candidate','ocr_confidence','edit_distance','amount','claim_amount_inr','severity_used','ratio_to_ceiling','garage_in_band_pct','garage_claim_count','execution_state','comparison_status','ocr_status','metadata_status','credentials_status')
        for check_id,rows in calculations.items():
            values=[];parameters={}
            for row in rows:
                observed=row.get('observed_values') or {}
                summary=', '.join(key.replace('_',' ')+' = '+clean(observed[key]) for key in observed_keys if key in observed)
                if summary and summary not in values:values.append(summary)
                parameters.update(row.get('rule_parameters') or {})
            observed='; '.join(values[:2]) or 'See the recorded findings above.'
            if parameters:
                parameter_text=', '.join(key.replace('_',' ')+' = '+clean(value) for key,value in parameters.items() if not isinstance(value,(dict,list)))
                if parameter_text:observed+='\nRule: '+parameter_text
            if aggregation.get('method')=='weighted_concern_sum':
                contribution=sum(row.get('contribution') or 0 for row in rows)
                use=f"Weight {rows[0].get('registered_weight')}; total contribution {contribution:.4f}. "
            else:
                use=f"No numeric contribution. {sum(bool(row.get('cited_by_agent')) for row in rows)} finding(s) cited by the agent. "
            if all(not row.get('eligibility',{}).get('eligible') for row in rows):
                use+=str(rows[0].get('eligibility',{}).get('reason') or 'Not eligible for numeric scoring')+'.'
            calc_rows.append((label(check_id),observed,use))
        table(['CHECK','OBSERVED VALUE / RULE','CONTRIBUTION / ROUTING BASIS'],calc_rows,[width*.23,width*.44,width*.33])
        story.append(p('Recorded routing source: '+str(routing.get('source','unrecorded')).replace('_',' ')+'. Policy: '+str(explanation.get('policy_version') or 'unrecorded')+'.','small'))
        for override in routing.get('overrides',[]):story.append(p('Routing override: '+override))
    section('Material limitations')
    if interpretation_unavailable:story.append(p('Automated interpretation is unavailable or incomplete. A fallback is a request for human review, not a model assessment.'))
    elif operational_partial:story.append(p('Recorded routing converged, but processing did not fully complete. Review the unavailable steps before relying on this assessment.'))
    elif coverage_partial:story.append(p('Some applicable checks have qualified missing or inconclusive inputs. This limits evidence coverage and does not imply that the model provider failed.'))
    # Implementation/cache/research-run details stay out of the reader report.
    limits=[]
    for item in coverage:
        if item.get('state') in {'failed','inconclusive','not_run'}:limits.append(label(item['check_id'])+': '+item['state'].replace('_',' '))
    if limits:story.append(p('; '.join(limits)+'.'))
    if 'threshold_gaming' in groups:story.append(p('The INR 50,000 billing band is a research benchmark. Its current legal applicability and insurer procedures have not been verified. Garage patterns are attributed to the repairer, not to claimant guilt.'))
    if any(item.get('check_id') in {'ai_generation','digital_edit','baseline_corruption','view_completeness'} for item in coverage):story.append(p('Zero-weight experimental observations have no demonstrated production detection value and do not contribute a numeric score.'))
    if declaration.get('agent_type')=='underwriting':story.append(p('Applicant view labels do not independently establish that all photographs show the same vehicle or complete inspection coverage.'))
    story.append(p('Applicant statements, measured observations and model interpretations have different evidential value. Missing metadata or unavailable credentials alone do not establish manipulation. Automated findings do not establish claimant intent; a human approval does not prove absence of fraud.'))
    section('Next reviewer action')
    requested=agent.get('requested_artifacts') or []
    if requested:
        for item in dict.fromkeys(requested):story.append(p('Request: '+item))
    elif partial:story.append(p('Review the submitted photographs and unresolved checks. Request specific missing evidence, or record an explicit, reasoned manual review decision when permitted.'))
    else:story.append(p('Assess the supported concerns and evidence gaps, then record approval, rejection or a specific evidence request.'))
    if report.get('agent_narrative') and not interpretation_unavailable:
        narrative_source='Recorded baseline routing narrative' if (explanation.get('routing') or {}).get('source')=='rules_baseline' else 'Recorded model interpretation' if (explanation.get('routing') or {}).get('source')=='model' else 'Recorded routing narrative (provenance unrecorded)'
        story.append(p(narrative_source+': '+report['agent_narrative']))
    if human:
        section('Human decision · this saved version' if human_current else 'Historical human decision — earlier analysis' if human_earlier else 'Historical human decision — review basis not recorded')
        table(['RECORD','VALUE'],[('Decision',human.get('action')),('Reviewer',human.get('admin_id')),('Recorded',_timestamp(human.get('timestamp'))),('Internal reason',human.get('reason'))],[width*.25,width*.75])
        story.append(p('The original analysis and earlier decision versions are preserved separately.' if human_current else 'This historical action remains intact. The current assessment requires a separate review; it does not inherit the earlier outcome.','small'))
    if report.get('include_technical_appendix'):
        technical=True
        story.append(PageBreak());section('Technical appendix · traceable records')
        # Appendix explicitly requested in the saved snapshot; main-body
        # cleaning does not erase the authoritative stored JSON.
        table(['REFERENCE','RECORDED VALUE'],[('Report snapshot',snapshot_id),('Analysis run',report.get('run_id')),('Template',report.get('report_template_version')),('Policy',report.get('policy_version'))],[width*.25,width*.75])
        if human:table(['HUMAN REVIEW BASIS','RECORDED VALUE'],[('Reviewed run',human.get('reviewed_run_id')),('Reviewed evidence',human.get('reviewed_evidence_ids'))],[width*.25,width*.75])
        provenance_keys=('checks_revision','provider_request_profile','perception_sources','adjudication_sources','model_versions','provider_model_version','root_failure_detail')
        table(['PROCESSING PROVENANCE','RECORDED VALUE'],[(key.replace('_',' '),processing[key]) for key in provenance_keys if processing.get(key) is not None],[width*.30,width*.70])
        table(['PHOTOGRAPH','EVIDENCE REFERENCE / SHA-256'],[(item.get('label'),str(item.get('image_id'))+'\n'+str(item.get('sha256'))) for item in inventory],[width*.25,width*.75])
        for row in explanation.get('findings',[]):
            story.append(p(label(row['check_id'])+' · '+str(row.get('finding_id')),'h2'))
            table(['OBSERVED FIELD','RECORDED VALUE'],[(key,_display(value)) for key,value in (row.get('observed_values') or {}).items()],[width*.35,width*.65])
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=16*mm,leftMargin=16*mm,topMargin=19*mm,bottomMargin=18*mm,title='FraudLens review — '+report['case_id'],author='FraudLens')
    def page(canvas,document):
        canvas.saveState();canvas.setFillColor(teal);canvas.rect(0,A4[1]-5*mm,A4[0],5*mm,fill=1,stroke=0)
        canvas.setFillColor(ink);canvas.setFont(bold,7);canvas.drawString(16*mm,A4[1]-12*mm,'FRAUDLENS / PRIVATE EVIDENCE REVIEW')
        canvas.setFont(regular,7);canvas.drawString(16*mm,10*mm,report['case_id']);canvas.drawRightString(A4[0]-16*mm,10*mm,f'Page {document.page}');canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()


def render_pdf(report, snapshot_id, generated_at):
    if report.get('report_template_version') in {RENDERER_VERSION, READER_V4_VERSION}:
        from .report_visuals import render_visual_report
        return render_visual_report(report, snapshot_id, generated_at,
                                    revised=report.get('report_template_version')==RENDERER_VERSION)
    if report.get('report_template_version')==READER_V3_VERSION:
        return _render_pdf_v2(report,snapshot_id,generated_at,keep_headings=True)
    if report.get('report_template_version')==READER_V2_VERSION:
        return _render_pdf_v2(report,snapshot_id,generated_at)
    return _render_pdf_v1(report,snapshot_id,generated_at)


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
        declared_version = payload.get('report_template_version')
        renderer_version = declared_version if declared_version in {RENDERER_VERSION, READER_V4_VERSION, READER_V3_VERSION, READER_V2_VERSION} else LEGACY_RENDERER_VERSION
        try:
            content = render_pdf(payload,snapshot_id,created)
            checksum = hashlib.sha256(content).hexdigest()
            conn.execute('INSERT INTO report_artifacts(snapshot_id,renderer_version,pdf_base64,sha256,created_at,error_type) VALUES (?,?,?,?,?,NULL) ON CONFLICT(snapshot_id) DO UPDATE SET renderer_version=excluded.renderer_version,pdf_base64=excluded.pdf_base64,sha256=excluded.sha256,created_at=excluded.created_at,error_type=NULL WHERE report_artifacts.pdf_base64 IS NULL',
                         (snapshot_id,renderer_version,base64.b64encode(content).decode(),checksum,created))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.execute('INSERT INTO report_artifacts(snapshot_id,renderer_version,created_at,error_type) VALUES (?,?,?,?) ON CONFLICT(snapshot_id) DO UPDATE SET error_type=excluded.error_type WHERE report_artifacts.pdf_base64 IS NULL', (snapshot_id,renderer_version,created,type(exc).__name__))
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
