"""Vector-first v4 reader report. Consumes saved data only; never runs checks."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, SimpleDocTemplate, Paragraph, Spacer, Table, LongTable, TableStyle, KeepTogether, PageBreak, Image

from .risk_presentation import assessment_presentation

INK = colors.HexColor('#203941')
TEAL = colors.HexColor('#236d67')
MUTED = colors.HexColor('#64757b')
LINE = colors.HexColor('#dce4e5')
PALE = colors.HexColor('#f1f5f5')
RISK = [('Low', '#d7eadb', '#18492a'), ('Medium', '#f8e5a5', '#4c3900'), ('High', '#f1cccc', '#762428')]
GROUPS = [('Identity', ['plate_ocr', 'view_completeness']), ('History and relationships', ['internal_duplicate', 'external_corpus', 'entity_graph', 'baseline_linkage', 'severity_progression']),
          ('Provenance', ['exif_metadata', 'c2pa_credentials', 'ai_generation', 'digital_edit']),
          ('Context', ['scene_consistency', 'damage_plausibility', 'baseline_corruption']), ('Economic', ['threshold_gaming'])]
STATES = {'pass': 'No concern found', 'concern': 'Concern', 'inconclusive': 'Inconclusive', 'failed': 'Unavailable', 'not_run': 'Not run', 'not_applicable': 'Not applicable'}


def safe_text(value, technical=False):
    if value is None or value == '':
        return 'Not recorded'
    text = str(value)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text = re.sub(r'(?i)(?:[A-Z]:[\\/]|\\\\)[^\s<>\"\']+', '[private path]', text)
    text = re.sub(r'/(?:home|Users|app|data|tmp|mnt|private)/[^\s<>\"\']+', '[private path]', text)
    text = re.sub(r'(?i)(Bearer\s+|(?:api[_ -]?key|password|session[_ -]?token|receipt|connection[_ -]?string)\s*[:=]\s*)[^\s,;]+', '[credential redacted]', text)
    text = re.sub(r'(?i)postgres(?:ql)?://[^\s]+', '[connection redacted]', text)
    if not technical:
        text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{22,}\b|\b[0-9a-f]{32,64}\b', '[saved reference]', text)
        text = re.sub(r'\bcase-[A-Za-z0-9_-]+', 'linked case', text)
    return text


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def finding_state(finding):
    evidence = finding.get('evidence') or {}
    state = evidence.get('execution_state')
    if state in {'failed', 'not_run', 'not_applicable'}:
        return state
    if evidence.get('error') or evidence.get('error_type'):
        return 'failed'
    return finding.get('verdict', 'inconclusive')


def check_status(findings, inventory):
    counts = Counter(finding_state(f) for f in findings)
    if not counts:
        state = (inventory or {}).get('state', 'not_run')
        state = 'inconclusive' if state == 'completed' else state
        counts[state] = 1
    text = ', '.join(f'{count} {STATES.get(state, state.replace("_", " ")).lower()}' for state, count in counts.items())
    dominant = 'failed' if 'failed' in counts else 'concern' if 'concern' in counts else next(iter(counts))
    return dominant, text


class RiskBar(Flowable):
    def __init__(self, assessment, width):
        super().__init__(); self.assessment = assessment; self.width = width; self.height = 87

    def draw(self):
        c = self.canv; a = self.assessment; active = a.get('category') if a.get('complete') or a.get('provisional') else None
        c.setFillColor(INK); c.setFont('FraudLens-Bold', 13); c.drawString(0, 72, safe_text(a['label']))
        if a.get('risk_index') is not None:
            c.setFont('FraudLens-Bold', 9); c.drawRightString(self.width, 73, f"Risk index: {a['risk_index']}%")
        elif a.get('score') is not None:
            c.setFont('FraudLens', 9); c.drawRightString(self.width, 73, f"Heuristic score {a['score']}")
        elif a.get('historical'):
            c.setFont('FraudLens', 8); c.setFillColor(MUTED); c.drawRightString(self.width, 73, "Not calculated for this historical assessment")
        segment = (self.width - 8) / 3
        for index, (label, bg, fg) in enumerate(RISK):
            x = index * (segment + 4)
            c.setFillColor(colors.HexColor(bg) if active else PALE)
            c.setStrokeColor(colors.HexColor(fg) if active == label else LINE)
            c.setLineWidth(1.7 if active == label else .6)
            c.roundRect(x, 29, segment, 27, 5, fill=1, stroke=1)
            c.setFillColor(colors.HexColor(fg) if active else MUTED); c.setFont('FraudLens-Bold', 10)
            c.drawCentredString(x + segment / 2, 38, label)
            if active == label:
                c.setFillColor(INK); path = c.beginPath(); path.moveTo(x + segment/2 - 4, 65); path.lineTo(x + segment/2 + 4, 65); path.lineTo(x + segment/2, 58); path.close(); c.drawPath(path, fill=1, stroke=0)
                c.setStrokeColor(INK); c.line(x + 12, 33, x + segment - 12, 33)
        c.setFont('FraudLens', 7.5); c.setFillColor(MUTED)
        c.drawString(0, 14, 'Risk index expresses the strength of findings under this assessment policy; it is not a statistical probability of fraud.')
        c.drawString(0, 4, 'Band boundaries: LOW [0–29%], MEDIUM [30–69%], HIGH [70–100%].')


class RelationshipGraph(Flowable):
    def __init__(self, links, width):
        super().__init__(); self.links = list(links.items())[:4]; self.width = width; self.height = max(64, len(self.links)*30)

    def draw(self):
        c = self.canv; middle = self.height/2
        c.setStrokeColor(LINE); c.setFillColor(PALE); c.roundRect(0, middle-15, 95, 30, 6, fill=1)
        c.setFillColor(INK); c.setFont('FraudLens-Bold', 8); c.drawCentredString(47, middle-3, 'Submitted case')
        for index, (_case, fields) in enumerate(self.links):
            y = self.height - 16 - index*30
            c.setStrokeColor(MUTED); c.line(96, middle, self.width-115, y)
            c.setFillColor(PALE); c.roundRect(self.width-114, y-12, 114, 24, 5, fill=1, stroke=0)
            c.setFillColor(INK); c.setFont('FraudLens', 8); c.drawString(self.width-108, y-3, f'Linked case {index+1}')
            c.setFont('FraudLens', 7); c.drawCentredString(self.width*.51, y+5, safe_text(', '.join(fields))[:48])


class AmountComparison(Flowable):
    """A labelled INR axis; neither damage percentage nor risk score."""
    def __init__(self, amount, threshold, width):
        super().__init__(); self.amount=amount; self.threshold=threshold; self.width=width; self.height=58

    def draw(self):
        c=self.canv; w=self.width-8; scale=max(self.amount,self.threshold,1)*1.15
        c.setFillColor(PALE);c.rect(0,20,w,13,fill=1,stroke=0)
        c.setFillColor(TEAL);c.rect(0,20,w*self.amount/scale,13,fill=1,stroke=0)
        x=w*self.threshold/scale;c.setStrokeColor(INK);c.setDash(2,2);c.line(x,17,x,39);c.setDash()
        c.setFont('FraudLens',8);c.setFillColor(INK)
        c.drawString(0,45,f'Declared INR {self.amount:,.0f} | Heuristic concern threshold INR {self.threshold:,.0f}')
        c.drawString(0,5,'0 INR');c.drawRightString(w,5,f'{scale:,.0f} INR (axis maximum)')


class PatternBar(Flowable):
    def __init__(self, value, benchmark, width):
        super().__init__(); self.value = value; self.benchmark = benchmark; self.width = width; self.height = 47

    def draw(self):
        c = self.canv; w = self.width-6
        c.setFillColor(PALE); c.roundRect(0, 17, w, 14, 4, fill=1, stroke=0)
        c.setFillColor(TEAL); c.roundRect(0, 17, max(1, w*max(0,min(100,self.value))/100), 14, 4, fill=1, stroke=0)
        x = w*max(0,min(100,self.benchmark))/100
        c.setStrokeColor(INK); c.setDash(2, 2); c.line(x, 13, x, 35); c.setDash()
        c.setFillColor(INK); c.setFont('FraudLens', 8)
        c.drawString(0, 2, f'Observed share: {self.value:g}%')
        c.drawRightString(w, 2, f'Rule benchmark: {self.benchmark:g}%')
        c.setFont('FraudLens', 7); c.drawRightString(w, 37, '0–100% of this garage’s recorded claims; not risk')


def render_visual_report(report, snapshot_id, generated_at, revised=False):
    from .report_pdf import _font_names, _timestamp, CHECK_LABELS, CHECK_PURPOSES, RENDERER_VERSION
    regular, bold = _font_names()
    latest=report.get('report_template_version','').endswith(('-v8','-v9','-v10','-v11','-v12','-v13','-v14'))
    polished=report.get('report_template_version','').endswith(('-v9','-v10','-v11','-v12','-v13','-v14'))
    width = A4[0]-32*mm
    styles = {
        'body': ParagraphStyle('v4-body',fontName=regular,fontSize=9,leading=13,textColor=INK,spaceAfter=6,splitLongWords=True),
        'small': ParagraphStyle('v4-small',fontName=regular,fontSize=8,leading=11,textColor=INK,spaceAfter=4,splitLongWords=True),
        'caption': ParagraphStyle('v4-caption',fontName=regular,fontSize=7.7,leading=10.8,textColor=MUTED,spaceAfter=5,splitLongWords=True),
        'title': ParagraphStyle('v4-title',fontName=bold,fontSize=27,leading=33,textColor=INK,spaceAfter=7),
        'h1': ParagraphStyle('v4-h1',fontName=bold,fontSize=14,leading=19,textColor=TEAL,spaceBefore=13,spaceAfter=7,keepWithNext=True),
        'h2': ParagraphStyle('v4-h2',fontName=bold,fontSize=10.2,leading=14,textColor=INK,spaceBefore=7,spaceAfter=5,keepWithNext=True),
        'cardtitle': ParagraphStyle('v4-cardtitle',fontName=bold,fontSize=10.2,leading=14,textColor=INK),
        'cell': ParagraphStyle('v4-cell',fontName=regular,fontSize=8,leading=11,textColor=INK,splitLongWords=True),
    }
    def p(text, style='body', technical=False):
        return Paragraph(escape(safe_text(text,technical)).replace('\n','<br/>'),styles[style])
    def grid(headers, rows, fractions=None):
        if not rows: return p('No usable measurements were saved.','caption')
        fractions = fractions or [1/len(headers)]*len(headers)
        data = [[p(text,'cell') for text in headers]] + [[p(text,'cell') for text in row] for row in rows]
        t = LongTable(data,colWidths=[width*f for f in fractions],repeatRows=1,splitInRow=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.6,TEAL),('LINEBELOW',(0,1),(-1,-1),.3,LINE),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    def picture(item, max_width, max_height):
        if item and item.get('thumbnail_base64'):
            try:
                image = Image(BytesIO(base64.b64decode(item['thumbnail_base64'],validate=True)))
                image._restrictSize(max_width,max_height); return image
            except Exception: pass
        return p('No authorized image was frozen in this snapshot.','caption')
    def short(text, limit=250):
        text = safe_text(text)
        return text if len(text)<=limit else text[:limit].rsplit(' ',1)[0]+'…'

    declaration = report.get('declaration') or {}; processing = report.get('processing') or {}
    explanation = report.get('assessment_explanation') or {}; aggregation = explanation.get('aggregation') or {}; routing = explanation.get('routing') or {}
    assessment = report.get('assessment_presentation') or assessment_presentation(report)
    inventory = report.get('evidence_inventory') or []; comparisons = report.get('comparison_evidence') or []
    images = {item['image_id']:item for item in inventory if item.get('image_id')}
    reference_images = {item['image_id']:item for item in comparisons if item.get('image_id')}
    findings = [f for group in (report.get('findings_by_category') or {}).values() for f in group]
    by_check = defaultdict(list)
    for finding in findings: by_check[finding['check_id']].append(finding)
    calculations = defaultdict(list)
    for row in explanation.get('findings') or []: calculations[row['check_id']].append(row)
    coverage = {row['check_id']:row for row in report.get('check_inventory') or []}
    expected = set((explanation.get('coverage') or {}).get('expected_check_ids') or [])
    check_ids = set(by_check) | expected | {key for key,row in coverage.items() if row.get('applicable',True)}
    check_ids -= {key for key in check_ids if coverage.get(key,{}).get('applicable') is False
                  and by_check.get(key) and all(finding_state(f)=='not_applicable' for f in by_check[key])}
    # All frozen registered checks remain represented, including excluded ones.
    excluded_ids = set(coverage)-check_ids
    required_ids = set((explanation.get('coverage') or {}).get('eligible_check_ids') or expected or check_ids)
    requirements = (explanation.get('coverage') or {}).get('requirements') or {}
    if revised and requirements:
        required_ids = {key for key, row in requirements.items() if row.get('required') and row.get('applicable')}
    count_states = Counter((coverage.get(key) or {}).get('state', ((explanation.get('coverage') or {}).get('check_states') or {}).get(key,'not_run')) for key in required_ids)
    required_executed = sum(bool(requirements[key].get('executed')) for key in required_ids) if revised and requirements else count_states.get('completed',0)
    required_unresolved = len((explanation.get('coverage') or {}).get('material_gap_ids', [])) if revised and requirements else sum(value for key,value in count_states.items() if key not in {'completed','not_applicable'})
    concern_count = sum(finding_state(f)=='concern' for f in findings)
    human = report.get('admin_action') or {}; human_current = bool(human and human.get('reviewed_run_id') == report.get('run_id') and report.get('run_id'))
    kind = declaration.get('agent_type','case')
    registration = declaration.get('vehicle_registration') or 'Registration not recorded'
    story = [p('FraudLens','title'),p(kind.title()+' / '+str(registration),'h1'),
             p('PRIVATE EVIDENCE REVIEW · SAVED RUN / HISTORICAL RECORD','caption'),
             p('Case '+str(report.get('case_id'))+' · Report '+_timestamp(generated_at),'small',True),
             Spacer(1,7),RiskBar(assessment,width)]
    if report.get('illustrative_fixture'):
        story.insert(2,p('CONTROLLED LAYOUT FIXTURE · NO LIVE AI VALIDATION','h2'))
    if assessment.get('display_policy_version'):
        story.append(p(assessment['basis'] + '. ' + assessment['explanation'], 'small'))
        saved_coverage = assessment.get('coverage') or {}
        story.append(p(f"Material evidence: {saved_coverage.get('sufficient',0)} / {saved_coverage.get('required_applicable',0)} applicable requirements sufficient. "
                       + assessment.get('next_action',''), 'small'))
    if assessment.get('method')=='Local rules assessment':
        story.append(p(assessment['status_label'],'h2'))
        story.append(p(assessment['method_note'],'small'))
    elif (processing.get('review_summary') or {}).get('kind')=='provider_partial':
        story.append(p('Partial analysis — local checks complete; AI analysis unavailable. Human review required.','h2'))
        story.append(p('Provider availability is an operational limitation, not evidence of customer fraud. Replace photographs only for an identified evidence gap.','small'))
    else:
        story.append(p(assessment['basis']+' · '+('Partial analysis · human review required' if not assessment.get('complete') else 'Recorded analysis · human review required'),'small'))
        if not assessment.get('complete'):
            story.append(p(short(assessment['explanation'],470)))
        story.append(p('This assessment covers only the saved run and evidence. Earlier reports remain historical when new evidence arrives. No heuristic score is a calibrated fraud probability.','caption'))
    summary = f"{kind.title()} application for {registration}. "
    if kind=='claims' and finite(declaration.get('claim_amount')): summary += f"Declared claim: INR {declaration['claim_amount']:,.0f}. "
    concern_checks=len({f.get('check_id') for f in findings if finding_state(f)=='concern'})
    summary += f'{len(inventory) or len(report.get("evidence_ids",[]))} saved photograph(s); '+(f'{concern_count} concern observation(s) across {concern_checks} check(s).' if latest else f'{concern_count} recorded concern finding(s).')+' Applicant statements and automated observations require independent review.'
    story.append(p('One-minute case summary','h2'))
    if inventory:
        summary_card=Table([[p(summary),[picture(inventory[0],width*.32,94),p('Saved evidence preview','caption')]]],colWidths=[width*.65,width*.35])
        summary_card.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0)]));story.append(summary_card)
    else:story.append(p(summary))
    candidate=(report.get('assessment_explanation') or {}).get('shadow_assessment')
    if candidate and report.get('report_template_version','').endswith(('-v6','-v7','-v8','-v9','-v10','-v11','-v12','-v13','-v14')):
        concern_display=f"{candidate['concern_index']:.2f} / 1" if latest and finite(candidate.get('concern_index')) else str(candidate.get('concern_index'))
        coverage_display=f"{candidate['coverage']:.1%}" if latest and finite(candidate.get('coverage')) else str(candidate.get('coverage'))
        story.append(p('SHADOW ONLY · candidate concern R: '+concern_display+'; material evidence coverage C: '+coverage_display+'. Unvalidated; production risk and human review unchanged.','small'))
    saved_support = assessment.get('supporting_findings') or []
    use_saved_support = report.get('report_template_version','').endswith(('-v13','-v14')) and assessment.get('display_policy_version')
    story.append(p('Findings supporting the display band' if use_saved_support else 'Main supported findings','h2'))
    concerns = list(dict.fromkeys(short((CHECK_LABELS.get(f.get('check_id'),f.get('check_id','Finding')) + ' [' + str(f.get('attributed_to') or 'attribution unrecorded') + ']: ' if use_saved_support else '') + str(f.get('explanation') or ''),220 if use_saved_support else 175)
                                 for f in (saved_support if use_saved_support else findings) if use_saved_support or finding_state(f)=='concern'))
    for text in concerns[:3]: story.append(p('• '+text,'small'))
    if not concerns: story.append(p('No eligible supporting finding was cited in the saved display summary. Missing or unavailable checks are not cleared.' if use_saved_support else 'No concerning finding was recorded. This does not clear missing or unavailable checks.','small'))
    if len(concerns)>3: story.append(p(f'{len(concerns)-3} further concern observation(s) are grouped in the check results.','caption'))
    story += [p('Evidence / check coverage — separate from risk','h2'),
              grid(['Photographs','Recorded required checks' if polished else 'Required execution coverage','Required unresolved inputs'],[(str(len(inventory)),
                    str(required_executed)+(' check record(s)' if polished else ' executed check(s)' if revised else ' completed check(s)'),
                    str(required_unresolved)+' unresolved check(s)')]),
              p('Optional and zero-weight experimental results are shown separately; they do not create a numerical risk score.','caption')]
    if polished:story.append(p('A recorded result may be unavailable or inconclusive; it does not establish that a measurement succeeded.','caption'))
    next_action = 'Review the evidence and missing inputs; request specific new evidence before relying on an incomplete assessment.' if not assessment.get('complete') else (report.get('agent_recommendation') or {}).get('recommendation','Human review required').replace('_',' ')
    if revised:
        if report.get('assessment_context')=='historical':
            story.append(p('Retrospective assessment: history comparisons use the recorded submission cutoff. Previous reports and human decisions are retained.','small'))
        gaps = (explanation.get('coverage') or {}).get('material_gap_ids', assessment.get('missing_check_ids', []))
        story += [p('Material missing evidence','h2'),p(', '.join(CHECK_LABELS.get(key,key) for key in gaps) or 'No unresolved material check recorded. Optional evidence limitations still apply.','small')]
        effective_action = str(routing.get('effective_recommendation') or 'Human review required').replace('_',' ')
        next_action = ('System routing: '+effective_action+'. '+next_action if not assessment.get('complete')
                       else 'System routing: '+effective_action+'. A reviewer must independently decide the application.')
    if assessment.get('method')=='Local rules assessment':
        next_action=assessment['next_action']+' Human approval/rejection is separate.'
    if assessment.get('method')!='Local rules assessment':
        story += [p('Recommended reviewer action','h2'),p(next_action)]
    if human and assessment.get('method')!='Local rules assessment':
        label = 'Human decision for this analysis: ' if human_current else 'Historical human decision: '
        story.append(p(label+str(human.get('action','unrecorded')).replace('_',' '),'small'))
        if not human_current: story.append(p('The current assessment requires a separate review. The new assessment has not received that decision; an unrecorded review basis cannot be treated as approval or rejection of this assessment.','caption'))
    story += [PageBreak(),p('Submitted facts · Applicant statements','h1')]
    facts = [('Registration',registration),('Case type',kind),('Submitted',_timestamp(report.get('submitted_at')))]
    labels = {'person_name':'Applicant','vehicle_make':'Make','vehicle_model':'Model','vehicle_variant':'Variant','vehicle_year':'Year','policy_number':'Policy reference',
              'claim_amount':'Claimed amount (INR)','idv':'Insured declared value (INR)','declared_location':'Declared incident location','incident_date':'Declared incident time','declaration_notes':'Applicant declaration'}
    if report.get('report_template_version','').endswith(('-v7','-v8','-v9','-v10','-v11','-v12','-v13','-v14')):
        labels.update(latitude='Declared incident latitude (unverified)',longitude='Declared incident longitude (unverified)')
    facts += [(label,declaration[key]) for key,label in labels.items() if declaration.get(key) is not None and declaration[key]!='']
    story.append(grid(['Field','Declared / recorded value'],facts,[.3,.7]))
    story += [p('Labeled photographs · evidence overview','h1')]
    if any(item.get('slot') for item in inventory):
        story.append(p('Slot names are applicant assignments. Exact angle, same-vehicle identity and capture date have not been independently authenticated.','caption'))
    if inventory:
        cells = []
        for item in inventory:
            cells.append([p(item.get('label','Photograph'),'h2'),picture(item,width/2-18,78),
                          p('Included in this analysis.' if item.get('considered_in_run') else 'Available; no completed analysis inventory was recorded.','caption')])
        rows = [cells[i:i+2]+([[]] if len(cells[i:i+2])==1 else []) for i in range(0,len(cells),2)]
        gallery = Table(rows,colWidths=[width/2]*2,hAlign='LEFT'); gallery.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),8)])); story.append(gallery)
    else: story.append(p('No frozen thumbnails were saved. Evidence has not been recreated for this report.'))
    story += ([] if latest else [PageBreak()])+[p('Main findings · check results','h1'),p('Labels distinguish concern, no concern found, inconclusive, unavailable, not run and not applicable. A completed check is not necessarily a clean result.','small')]

    def contribution(check_id):
        rows = calculations.get(check_id,[])
        if rows and all(row.get('registered_weight')==0 for row in rows): return 'EXCLUDED / ZERO WEIGHT. No contribution to risk.'
        if not rows: return 'Contribution not recorded; no value is invented.'
        if aggregation.get('method')=='weighted_concern_sum':
            values = [row.get('contribution') for row in rows]
            if all(finite(value) for value in values): return f"Saved contribution: {sum(values):.4f} · registered weight {rows[0].get('registered_weight')}."
            return 'Numeric contribution was not recorded; no value is reconstructed.'
        if aggregation.get('method')=='local_review_priority':
            cited=sum(bool(row.get('cited_by_local_policy')) for row in rows)
            return f'No numeric contribution. {cited} finding(s) cited by the saved local rules policy.'
        cited = sum(bool(row.get('cited_by_agent')) for row in rows)
        return f'No numeric contribution. {cited} finding(s) cited by the agent.'

    def measurements(group, keys):
        rows=[]
        for finding in group:
            observed=finding.get('evidence') or {}
            label=images.get(observed.get('image_id'),{}).get('label','Case-level observation')
            values=[f'{key.replace("_"," ")}: {safe_text(observed[key])}' for key in keys if key in observed and observed[key] is not None]
            if values: rows.append((label,'; '.join(values)))
        return rows

    def check_graphic(check_id, group, state):
        if not group or state in {'failed','not_run','not_applicable'}:
            reason = next((f.get('explanation') for f in group if f.get('explanation')),None)
            return [grid(['Saved state','Missing requirement / reason'],[(STATES.get(state,state),short(reason or 'The saved snapshot contains no applicable completed measurement.',260))],[.23,.77])]
        observed = [finding.get('evidence') or {} for finding in group]
        calculation_rows=calculations.get(check_id,[])
        if (polished and check_id in {'ai_generation','digital_edit','view_completeness','baseline_corruption'}
                and calculation_rows and all(row.get('registered_weight')==0 for row in calculation_rows)):
            return [grid(['Saved experimental observations','Use in production'],[(str(len(group))+' '+STATES.get(state,state)+' record(s)',
                'EXCLUDED / ZERO WEIGHT. Raw classifier measurements are retained in the saved record; they are not fraud probabilities.')],[.35,.65])]
        if check_id in {'internal_duplicate','external_corpus'}:
            item = next((entry for entry in observed if entry.get('matched_image_id') or entry.get('cosine_similarity') is not None),observed[0])
            submitted = images.get(item.get('image_id')); reference = reference_images.get(item.get('matched_image_id'))
            pair = Table([[p('Submitted photograph','small'),p('Authorized saved reference','small')],
                          [picture(submitted,width/2-18,69),picture(reference,width/2-18,69)]],colWidths=[width/2]*2)
            pair.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
            rows = measurements(group,('cosine_similarity','hamming_distance','images_compared','corpus_size'))
            comparison=([pair] if not polished or reference else [])+[grid(['Evidence','Measured comparison'],rows,[.25,.75])]
            if polished and not reference:comparison.append(p('No authorized matching reference photograph was saved. No visual match is fabricated.','caption'))
            return comparison+[p('Similarity is not proof of reused evidence or claimant intent. Reference images are shown only when frozen from an authorized internal record; external filenames are never opened.','caption')]
        if check_id=='plate_ocr':
            rows=[]
            for item in observed:
                confidence=item.get('ocr_confidence')
                rows.append((images.get(item.get('image_id'),{}).get('label','Photograph'),registration,
                             item.get('plate_candidate') or 'Unreadable / not recorded',item.get('comparison_status') or item.get('ocr_status') or 'Unverified',
                             str(confidence) if finite(confidence) else 'Not returned'))
            return [grid(['Evidence','Declared plate','Extracted text','Comparison','OCR confidence'],rows,[.16,.22,.23,.23,.16]),p('Confidence describes OCR text recognition only. No evidence crop was saved; this report does not fabricate one.','caption')]
        if check_id=='exif_metadata':
            rows=[]
            for item in observed:
                metadata=(images.get(item.get('image_id')) or {}).get('extracted_metadata') or {}
                rows.append((images.get(item.get('image_id'),{}).get('label','Photograph'),
                             item.get('exif_capture_time') or metadata.get('DateTimeOriginal') or 'Not recorded',
                             'Recorded' if item.get('exif_gps') else 'Not recorded',
                             metadata.get('Make') or 'Not recorded',item.get('software') or metadata.get('Software') or 'Not recorded'))
            return [grid(['Evidence','Captured time','GPS','Camera','Software'],rows,[.16,.28,.16,.19,.21]),
                    grid(['Evidence','Usable comparison'],measurements(group,('gps_distance_km','hours_apart','exif_present')),[.25,.75]),
                    p('Missing metadata does not imply manipulation. Capture time and GPS are extracted fields, not independently authenticated facts.'+(' An editor tag records software, not what changed or whether a claim is fraudulent.' if polished else ''),'caption')]
        if check_id=='entity_graph':
            links={key:fields for item in observed for key,fields in (item.get('linked_cases') or {}).items() if isinstance(fields,list)}
            return ([RelationshipGraph(links,width),p(f'{len(links)} recorded linked case(s); the graph shows up to four. Shared identifiers have innocent explanations and are not proof of fraud.','caption')]
                    if links else [grid(['Relationship','Saved observation'],[('Linked cases','No linked-case graph was saved; see the recorded interpretation below.')],[.25,.75])])
        if check_id in {'baseline_linkage','severity_progression'}:
            sequence = next((item.get('sequence') or item.get('inspections') for item in observed if item.get('sequence') or item.get('inspections')),[])
            rows = [(f'Observation {index+1}',item.get('declared_time') or item.get('inspection_time') or item.get('days_before_claim'),item.get('severity') or item.get('damage_severity') or 'Not comparable') for index,item in enumerate(sequence)]
            return [grid(['Saved sequence','Date / days before claim','Recorded severity'],rows,[.24,.42,.34]),
                    p('Dates and severity labels are shown as recorded. No continuous physical damage percentage is inferred from labels or image area. Missing chronology or a comparable scale prevents a severity plot.','caption')]
        if check_id=='threshold_gaming':
            item=observed[0]; graph=[]
            if finite(item.get('garage_in_band_pct')) and finite(item.get('garage_concern_pct')):
                graph.append(PatternBar(item['garage_in_band_pct'],item['garage_concern_pct'],width))
            graph += [grid(['Evidence','Recorded amount / pattern'],measurements(group,('amount','band_low','band_high','garage_claim_count','garage_in_band_pct','minimum_garage_claims')),[.24,.76]),
                      p('The implemented billing band is a research benchmark, not a verified legal rule. This is a garage pattern, not a claimant fraud probability.','caption')]
            return graph
        if revised and check_id=='damage_plausibility':
            item=observed[0]; band=item.get('plausible_range_inr') or []
            amount=item.get('claim_amount_inr')
            if polished and amount is None:amount=declaration.get('claim_amount')
            rows=[('Observed severity',item.get('severity_used')),('Declared amount (INR)',amount)]
            if len(band)==2:
                rows += [('Configured heuristic band (INR)',str(band)),('Concern threshold (INR)',band[1]*item.get('ceiling_tolerance',1.5) if finite(band[1]) else 'No finite ceiling')]
            return [grid(['Saved input / benchmark','Value'],rows,[.55,.45]),
                AmountComparison(item.get('claim_amount_inr'),band[1]*item.get('ceiling_tolerance',1.5),width) if len(band)==2 and finite(band[1]) and finite(item.get('claim_amount_inr')) else p('No comparable finite amount scale was recorded.','caption'),
                p('Configured severity/amount research heuristic only. No independent repair estimate or invoice has been verified; vehicle value, parts and labour can differ.','caption')]
        keys = {
            'damage_plausibility':('claim_amount_inr','severity_used','observed_severities','ratio_to_ceiling','ceiling_tolerance'),
            'scene_consistency':('declared_time_basis','observed_shadow_direction','expected_shadow_direction','shadow_bearing_difference_deg','observed_weather','expected_weather','weather_status','lighting_status','shadow_status'),
            'c2pa_credentials':('credentials_present','validation_state','credentials_status','manifest_present'),
            'ai_generation':('artificial_probability','reporting_band','model','execution_state'),
            'digital_edit':('combined_score','calibrated','concern_threshold','execution_state'),
            'view_completeness':('distinct_views','missing_views','required_views','plate_seen','execution_state'),
            'baseline_corruption':('comparison_status','declared_condition','contradicting_severity','execution_state'),
        }.get(check_id,('comparison_status','execution_state'))
        result=[grid(['Evidence / declaration','Recorded observation'],measurements(group,keys),[.27,.73])]
        if check_id in {'ai_generation','digital_edit','baseline_corruption','view_completeness'}:
            result.append(p('Experimental / excluded where the saved registered weight is zero. Raw classifier outputs are not fraud probabilities. View labels do not verify the same vehicle.','caption'))
        elif check_id in {'damage_plausibility','scene_consistency'}:
            result.append(p('Structured comparison of saved observations only. No damage boxes, heatmap, map or annotation was available; none has been invented.','caption'))
        return result

    numbered=0
    for group_title, members in GROUPS:
        present=[key for key in members if key in check_ids]
        if not present: continue
        for group_index,check_id in enumerate(present):
            numbered+=1; group=by_check.get(check_id,[]); meta=coverage.get(check_id,{})
            state,status=check_status(group,meta)
            badge_color=colors.HexColor('#762428') if state=='concern' else TEAL if state=='pass' else MUTED
            heading=Table([[p(f'{numbered:02d} / '+CHECK_LABELS.get(check_id,check_id.replace('_',' ').title()),'cardtitle'),p(status,'cell')]],colWidths=[width*.58,width*.42])
            heading.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('LINEBEFORE',(0,0),(0,0),3,badge_color),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            content=([p(group_title,'h1')] if group_index==0 else [])+[heading,p(meta.get('purpose') or CHECK_PURPOSES.get(check_id,'Examine the saved evidence for this check.'),'small')]
            evidence_labels=list(dict.fromkeys(images.get((f.get('evidence') or {}).get('image_id'),{}).get('label','Case / linked records') for f in group))
            content.append(p(('Evidence referenced: ' if polished else 'Evidence examined: ')+(', '.join(evidence_labels) if evidence_labels else 'No completed evidence measurement was recorded.'),'caption'))
            content += check_graphic(check_id,group,state)
            parameters={key:value for row in calculations.get(check_id,[]) for key,value in (row.get('rule_parameters') or {}).items() if not isinstance(value,(list,dict))}
            if parameters and (not revised or check_id in {'internal_duplicate','external_corpus','plate_ocr'}):
                content.append(p('Saved decision parameters: '+ '; '.join(key.replace('_',' ')+' = '+str(value) for key,value in parameters.items()),'caption'))
            statements=list(dict.fromkeys(safe_text(f.get('explanation')) for f in group if f.get('explanation')))
            if statements: content.append(p('Interpretation: '+' '.join(short(text,230) for text in statements[:2]),'small'))
            content.append(p(contribution(check_id),'small'))
            if not group: uncertainty='Missing requirement: this check was not run; its result cannot be treated as a pass.'
            elif state in {'failed','not_run','not_applicable','inconclusive'}: uncertainty='Uncertain: the recorded state does not establish an applicable clean or concerning conclusion.'
            else: uncertainty='Uncertain: this observation does not establish the full application or intent.'
            if revised and check_id in requirements:
                req=requirements[check_id]
                uncertainty = ('Coverage: material requirement; '+('sufficient for this comparison.' if req.get('evidence_sufficient') else 'evidence remains insufficient.')
                               if req.get('required') else 'Coverage: optional / advisory; does not block material completeness.')
                if not req.get('applicable'):uncertainty += ' No applicable historical comparison is established; this is not a passed history check.'
            content += [p(uncertainty,'caption'),Spacer(1,7)]
            story.append(KeepTogether(content))
    unknown=check_ids-set(key for _,members in GROUPS for key in members)
    if unknown: story.append(grid(['Other saved check','State'],[(key,check_status(by_check.get(key,[]),coverage.get(key))[1]) for key in sorted(unknown)],[.45,.55]))
    if excluded_ids:
        story += [p('Checks outside this run’s applicable policy','h2'),grid(['Registered check','Result / use'],[(CHECK_LABELS.get(key,key),'Not applicable to this policy / no contribution') for key in sorted(excluded_ids)],[.5,.5])]

    shadow=explanation.get('shadow_assessment') if report.get('report_template_version','').endswith(('-v6','-v7','-v8','-v9','-v10','-v11','-v12','-v13','-v14')) else None
    shadow_start=len(story)
    if assessment.get('method')!='Local rules assessment' and report.get('report_template_version','').endswith(('-v6','-v7','-v8','-v9','-v10','-v11','-v12','-v13','-v14')):
        story.append(p('Candidate assessment — SHADOW ONLY','h1'))
        if not shadow:
            story.append(p('This saved snapshot has no candidate calculation. No missing values are reconstructed.'))
        else:
            story.append(p('Unvalidated heuristic comparison. This does not replace production routing, the risk bar or human review. Neither axis is a fraud probability.'))
            story.append(grid(['Concern index R (0–1)','Material coverage C','Candidate action'],[(
                f"{shadow['concern_index']:.2f}" if finite(shadow.get('concern_index')) else 'Unavailable',
                f"{shadow['coverage']:.1%}" if finite(shadow.get('coverage')) else 'Unavailable',shadow.get('candidate_recommendation'))],[.30,.30,.40]))
            story.append(p('R = 1 - product(1 - grouped maximum). C = sufficient applicable material requirements / applicable material requirements. Mandatory gaps prevent candidate clearance regardless of the average.','small'))
            story.append(grid(['Correlation group','Saved maximum a × e'],[(k,str(v)) for k,v in shadow.get('groups',{}).items()],[.65,.35]))
            coverage_display=f"{shadow['coverage']:.1%}" if latest and finite(shadow.get('coverage')) else str(shadow.get('coverage'))
            story.append(p('Worked saved calculation: R = 1 - '+ ' × '.join('('+str(round(1-v,4))+')' for v in shadow.get('groups',{}).values())+' = '+str(shadow.get('concern_index'))+'. C = '+str(shadow.get('coverage_numerator'))+' / '+str(shadow.get('coverage_denominator'))+' = '+coverage_display+'.','small'))
            story.append(grid(['Check / group','Strength / parameter','Coverage sufficient'],[(row['check_id']+' / '+str(row['group']),str(row['e'])+' / '+str(row['a']),str((shadow.get('material_requirements',{}).get(row['check_id']) or {}).get('evidence_sufficient','Optional / not applicable'))) for row in shadow.get('checks',[])],[.45,.25,.30]))
            story.append(p('Mandatory gaps: '+(', '.join(shadow.get('mandatory_gaps') or []) or 'None recorded')+'. Garage alerts are separate. All candidate operating points are unvalidated.','small'))
    if shadow:
        story.insert(shadow_start,PageBreak())
    story += [p('How the assessment was calculated','h1')]
    if not explanation:
        story.append(p('A structured calculation explanation was not recorded. No score or contribution is reconstructed.'))
    else:
        story.append(p(aggregation.get('rule') or 'No aggregation rule was saved.'))
        if revised:
            model_recorded=routing.get('source')=='model' and routing.get('converged') is True
            saved_output=str(routing.get('recorded_band'))+' / '+str(routing.get('model_recommendation',routing.get('recommendation')))
            if routing.get('source')=='local_rules':
                saved_output='Local rules assessment; AI-dependent interpretation not performed.'
            elif not model_recorded and latest:
                saved_output='Saved rules baseline; no model decision.' if routing.get('source')=='rules_baseline' else 'No converged model decision. Saved system fallback only.'
            story.append(grid([('Recorded model output' if model_recorded else 'Automated decision availability') if latest else 'Model output (unchanged)','Effective system routing','Guard / human boundary'],[(
                saved_output,
                routing.get('effective_recommendation') or 'Unrecorded in this snapshot',
                (routing.get('guard_policy') or 'No guard policy recorded')+'. Human approval/rejection is separate.')],[.34,.30,.36]))
        if aggregation.get('valid_numeric_score') and finite(aggregation.get('computed_value')):
            story.append(p('Saved heuristic score: '+str(aggregation['computed_value'])+'. Not a fraud probability.'))
            if not assessment.get('complete'):
                story.append(p('Recorded arithmetic is retained for audit only. Incomplete processing prevents a current risk classification.','small'))
        elif assessment.get('risk_index') is not None:
            story.append(p(f"Saved risk index: {assessment['risk_index']}%. Risk index expresses the strength of findings under this assessment policy; it is not a statistical probability of fraud."))
            story.append(p('Formula: Risk index I = min(100, S_concerns + U_gaps). Band boundaries: LOW [0–29%], MEDIUM [30–69%], HIGH [70–100%].','small'))
            if assessment.get('concern_score') is not None or assessment.get('uncertainty_adjustment') is not None:
                story.append(p(f"Concern contribution: {assessment.get('concern_score', 0)} points across domains {', '.join(assessment.get('concern_domains') or []) or 'none'}. Evidence uncertainty adjustment: {assessment.get('uncertainty_adjustment', 0)} points.", 'small'))
        elif assessment.get('historical'):
            story.append(p("Not calculated for this historical assessment."))
        else: story.append(p('Numeric score: not computed. The saved local policy assigns review priority categories.' if assessment.get('method')=='Local rules assessment' else 'Numeric score: not computed. Production model routing does not assign numerical contributions.'))
        rows=[]
        for key, entries in calculations.items():
            eligibility=('Non-completed concern retained by the saved baseline; review the recorded inconsistency' if any((row.get('eligibility') or {}).get('eligible') and row.get('execution_state')!='completed' for row in entries) else
                         'Eligible saved concern(s)' if any((row.get('eligibility') or {}).get('eligible') for row in entries) else
                         'Excluded: zero weight' if all(row.get('registered_weight')==0 for row in entries) else 'No eligible concern contribution')
            rows.append((CHECK_LABELS.get(key,key),short(eligibility,200),contribution(key)))
        story.append(grid(['Check','Eligibility / exclusions','Recorded contribution / routing basis'],rows,[.25,.38,.37]))
        if aggregation.get('thresholds'):
            thresholds=aggregation['thresholds']
            story.append(p('Saved thresholds: clear < '+str(thresholds.get('clear_below'))+'; request evidence < '+str(thresholds.get('request_evidence_below'))+'; desk review < '+str(thresholds.get('desk_review_below'))+'; investigation at or above the last threshold.','small'))
        for override in routing.get('overrides') or []:
            label=safe_text(override)
            if latest and routing.get('source')=='fallback' and 'model output retained' in label:
                label='Material-evidence guard: no converged model decision; fallback routing cannot establish clearance.'
            story.append(p('Recorded override: '+label,'small'))
    story += [p('Material limitations and next reviewer action','h1'),p('Coverage measures execution, not risk. Missing metadata is not proof of manipulation; similarity and shared identifiers are not proof of fraud. Automated routing is separate from human approval or rejection.')]
    if not assessment.get('complete'): story.append(p('Partial analysis: '+assessment['explanation']))
    for text in list(dict.fromkeys(report.get('limitations') or []))[:4]: story.append(p('• '+short(text,260),'small'))
    requested=(report.get('agent_recommendation') or {}).get('requested_artifacts') or []
    story.append(p('Next reviewer action: '+('; '.join(requested) if requested else next_action)))
    if human:
        story.append(p(('Human decision · this saved version: ' if human_current else 'Historical human decision: ')+str(human.get('action','unrecorded')).replace('_',' '),'h2'))
        if human.get('public_message'): story.append(p(human['public_message']))
    story += [PageBreak(),p('Technical appendix · saved basis and thresholds','h1')]
    references=[('Snapshot',snapshot_id),('Analysis run',report.get('run_id')),('Policy',report.get('policy_version') or explanation.get('policy_version')),('Renderer',report.get('report_template_version') or RENDERER_VERSION),('Presentation contract',assessment.get('version'))]
    references.append(('Stored execution status',processing.get('status','not recorded')))
    for key,value in references: story.append(p(key+': '+safe_text(value,True),'caption',True))
    for failure in processing.get('failures') or []:
        story.append(p('AI diagnostic: '+str(failure.get('error_category','unavailable'))+'; stage '+str(failure.get('stage','unrecorded'))+'; '+str(failure.get('timestamp','time unrecorded'))+'; attempts '+str(failure.get('attempt_count','unrecorded'))+'; retryable '+str(failure.get('retryable','unrecorded')),'caption',True))
    additional_labels={'person_contact':'Applicant contact','person_dob':'Date of birth','person_address':'Applicant address',
        'policy_type':'Policy type','policy_start_date':'Policy start','policy_end_date':'Policy end','previous_policy_number':'Previous policy',
        'policy_ncb_percent':'Declared no-claim bonus (%)','fuel_type':'Fuel type','rto':'Registration office','engine_number':'Engine reference',
        'chassis_number':'Chassis reference','fir_number':'FIR reference','driving_license_number':'Driving licence','settlement_preference':'Settlement preference',
        'bank_account_last4':'Bank account last four digits','garage_id':'Garage reference'}
    additional=[(label,declaration[key]) for key,label in additional_labels.items() if declaration.get(key) is not None and declaration[key]!='']
    if additional:
        story += [p('Additional submitted facts · applicant statements','h2'),grid(['Field','Submitted value'],additional,[.32,.68])]
    for check_id,rows in calculations.items():
        parameters={key:value for row in rows for key,value in (row.get('rule_parameters') or {}).items()}
        if parameters: story.append(p(CHECK_LABELS.get(check_id,check_id)+': '+json.dumps(parameters,ensure_ascii=False,default=str),'caption'))
    story.append(p('Full evidence hashes and provider internals remain in the authorized saved records. Credentials, raw exceptions and filesystem paths are not printed.','caption'))
    output=BytesIO(); doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,topMargin=19*mm,bottomMargin=18*mm,title='FraudLens '+kind+' review',author='FraudLens')
    def page(canvas, document):
        canvas.saveState();canvas.setFillColor(TEAL);canvas.rect(0,A4[1]-5*mm,A4[0],5*mm,fill=1,stroke=0)
        canvas.setFillColor(MUTED);canvas.setFont(regular,7);canvas.drawString(16*mm,A4[1]-12*mm,'FRAUDLENS / PRIVATE SAVED EVIDENCE REVIEW')
        canvas.drawString(16*mm,10*mm,('CONTROLLED FIXTURE / ' if report.get('illustrative_fixture') else '')+safe_text(str(registration))[:55]);canvas.drawRightString(A4[0]-16*mm,10*mm,'Page '+str(document.page));canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
