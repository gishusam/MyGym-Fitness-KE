"""Simple A4 workout export; requires the free ReportLab Python package."""
from __future__ import annotations

from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from xml.sax.saxutils import escape

GREEN = colors.HexColor('#285d43')


def create_workout_pdf(data: dict) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=38, bottomMargin=42, leftMargin=42, rightMargin=42, title='MyGym workout program')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='GymTitle', fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=GREEN, spaceAfter=12))
    styles.add(ParagraphStyle(name='GymSection', fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=GREEN, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name='GymBody', fontName='Helvetica', fontSize=9, leading=13, spaceAfter=6, textColor=colors.HexColor('#33453b')))
    elements = [Paragraph('MYGYM FITNESS KE', styles['GymSection']), Paragraph(escape(data['programName']), styles['GymTitle'])]
    p = lambda text: Paragraph(escape(str(text or '')), styles['GymBody'])
    elements.extend([p('Member: ' + data['memberName']), p('Goal: ' + data['goal']), p(f"Schedule: {data['daysPerWeek']} days per week  |  {data['sessionMinutes']} minutes per session"), p('Starts: ' + data['startsOn'])])
    if data.get('description'): elements.append(p(data['description']))
    elements.append(Paragraph('Exercises', styles['GymSection']))
    rows = [[p('Exercise'), p('Sets'), p('Reps / Duration'), p('Rest')]]
    for exercise in data['exercises']:
        target = f"{exercise['repetitions']} reps" if exercise['repetitions'] else f"{exercise['durationSeconds']} seconds"
        rows.append([p(exercise['name']), p(exercise['sets']), p(target), p(f"{exercise['restSeconds'] or 0}s")])
    table = Table(rows, colWidths=[220, 50, 145, 60], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4ef')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),0.5,GREEN),('BOTTOMPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,1),(-1,-1),0.2,colors.HexColor('#dce6df'))]))
    elements.append(table)
    if data.get('trainerNotes'):
        elements.extend([Paragraph('Trainer notes', styles['GymSection']), p(data['trainerNotes'])])
    elements.extend([Spacer(1,12), Paragraph('Guidance from your trainers', styles['GymSection']), p(data['trainerGuidance']), p('Follow your coach’s instructions. Stop an exercise and seek guidance if you experience pain or unusual symptoms.')])
    doc.build(elements)
    return output.getvalue()
