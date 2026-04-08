from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import ListFlowable, ListItem
from reportlab.platypus import HRFlowable

def generate_pdf_report(filename: str, analysis_text: str, score_block: str):
    doc = SimpleDocTemplate(filename)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>MarketScope AI Report</b>", styles["Title"]))
    elements.append(Spacer(1, 0.5 * inch))

    elements.append(Paragraph("<b>AI Анализ</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(analysis_text.replace("\n", "<br/>"), styles["BodyText"]))
    elements.append(Spacer(1, 0.5 * inch))

    elements.append(HRFlowable(width="100%"))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>Score</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(score_block.replace("\n", "<br/>"), styles["BodyText"]))

    doc.build(elements)