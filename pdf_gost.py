# pdf_gost.py — ГОСТ-совместимый PDF
import io
import re
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from gost_standards import get_format_info, WORK_TYPES
import config
from utils.diploma_utils import parse_diploma_text

def _register_fonts():
    candidates = config.FONT_CANDIDATES
    for name, reg_path, bold_path in candidates:
        if reg_path.exists() and bold_path.exists():
            pdfmetrics.registerFont(TTFont(name, str(reg_path)))
            pdfmetrics.registerFont(TTFont(f"{name}-Bold", str(bold_path)))
            return name, f"{name}-Bold"
    raise FileNotFoundError(
        "❌ Не найдены TTF-шрифты с кириллицей!\n\n"
        "Положите в папку fonts/:\n"
        "  LiberationSerif-Regular.ttf\n"
        "  LiberationSerif-Bold.ttf\n"
        "или другие поддерживаемые шрифты."
    )

FONT_REGULAR, FONT_BOLD = _register_fonts()

def make_styles(font_name: str, font_bold: str, font_size: int = 14, line_spacing: float = 1.5):
    leading = font_size * line_spacing
    return {
        'Title': ParagraphStyle(
            'GostTitle', fontName=font_bold, fontSize=font_size,
            alignment=TA_CENTER, leading=leading, spaceAfter=20, spaceBefore=20,
        ),
        'Heading1': ParagraphStyle(
            'GostH1', fontName=font_bold, fontSize=font_size,
            alignment=TA_CENTER, leading=leading, spaceAfter=16, spaceBefore=16,
        ),
        'Heading2': ParagraphStyle(
            'GostH2', fontName=font_bold, fontSize=font_size,
            alignment=TA_LEFT, leading=leading, spaceAfter=12, spaceBefore=12,
        ),
        'Body': ParagraphStyle(
            'GostBody', fontName=font_name, fontSize=font_size,
            alignment=TA_JUSTIFY, leading=leading, spaceAfter=0, spaceBefore=0,
            firstLineIndent=12.5 * mm,
        ),
        'Bibliography': ParagraphStyle(
            'GostBib', fontName=font_name, fontSize=font_size,
            alignment=TA_JUSTIFY, leading=leading, spaceAfter=6,
            leftIndent=10 * mm, firstLineIndent=-10 * mm,
        ),
        'Meta': ParagraphStyle(
            'GostMeta', fontName=font_name, fontSize=12,
            alignment=TA_LEFT, leading=14, spaceAfter=6,
        ),
        'TocText': ParagraphStyle(
            'GostTocText', fontName=font_name, fontSize=font_size,
            alignment=TA_LEFT, leading=leading, spaceAfter=0,
            firstLineIndent=0,
        ),
        'TocDots': ParagraphStyle(
            'GostTocDots', fontName=font_name, fontSize=font_size,
            alignment=TA_CENTER, leading=leading, spaceAfter=0,
            firstLineIndent=0, textColor=colors.grey,
        ),
        'TocPage': ParagraphStyle(
            'GostTocPage', fontName=font_name, fontSize=font_size,
            alignment=TA_RIGHT, leading=leading, spaceAfter=0,
            firstLineIndent=0,
        ),
    }

def _make_page_number_fn(skip_pages: int = 2):
    def _on_page(canvas, doc):
        page_num = canvas.getPageNumber()
        if page_num > skip_pages:
            canvas.saveState()
            canvas.setFont(FONT_REGULAR, 12)
            canvas.drawCentredString(A4[0] / 2, 15 * mm, str(page_num - skip_pages))
            canvas.restoreState()
    return _on_page

def _build_title_page(styles, title: str, meta: dict, work_type: str = "diploma"):
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    story = []
    s_meta = styles['Meta']
    s_title = styles['Title']

    story.append(Paragraph(meta.get('university', 'ФЕДЕРАЛЬНЫЙ УНИВЕРСИТЕТ').upper(), s_meta))
    story.append(Spacer(1, 4))
    if meta.get('faculty'):
        story.append(Paragraph(meta['faculty'], s_meta))
        story.append(Spacer(1, 4))
    if meta.get('department'):
        story.append(Paragraph(f"Кафедра {meta['department']}", s_meta))

    story.append(Spacer(1, 36))

    story.append(Paragraph(wt['name'].upper(), s_title))
    story.append(Spacer(1, 16))
    story.append(Paragraph("на тему:", s_meta))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>{title}</b>", s_title))
    story.append(Spacer(1, 50))

    author = meta.get('author', 'Иванов И. И.')
    group = meta.get('group', '')
    supervisor = meta.get('supervisor', 'Петров П. П.')
    supervisor_title = meta.get('supervisor_title', 'доцент, к.т.н.')

    data = [
        [Paragraph("Выполнил:", s_meta), Paragraph(author, s_meta)],
        [Paragraph("", s_meta), Paragraph(group, s_meta)],
        [Paragraph("", s_meta), Paragraph("", s_meta)],
        [Paragraph("Научный руководитель:", s_meta), Paragraph(supervisor, s_meta)],
        [Paragraph("", s_meta), Paragraph(supervisor_title, s_meta)],
    ]
    t = Table(data, colWidths=[60 * mm, 70 * mm])
    t.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Spacer(1, 50))

    city = meta.get('city', 'Екатеринбург')
    year = meta.get('year', datetime.now().year)
    story.append(Paragraph(f"{city} — {year}", s_meta))

    return story

def _build_abstract(styles, title: str, meta: dict, work_type: str = "diploma"):
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    story = []
    s_body = styles['Body']
    s_h1 = styles['Heading1']

    story.append(Paragraph("РЕФЕРАТ", s_h1))
    story.append(Spacer(1, 12))

    volume = meta.get('volume_pages', wt['min_pages'])
    chapters = meta.get('chapters_count', wt['chapters'])
    figures = meta.get('figures_count', 0)
    tables = meta.get('tables_count', 0)
    sources = meta.get('sources_count', 10)
    appendices = meta.get('appendices_count', 0)

    volume_line = (
        f"Пояснительная записка содержит {volume} стр., "
        f"{chapters} {'главы' if chapters < 5 else 'глав'}, "
        f"{figures} рис., {tables} табл., {sources} ист."
    )
    if appendices:
        volume_line += f", {appendices} прил."
    story.append(Paragraph(volume_line, s_body))
    story.append(Spacer(1, 12))

    fields = [
        ("Ключевые слова", meta.get('keywords', '')),
        ("Объект исследования", meta.get('object', '')),
        ("Предмет исследования", meta.get('subject', '')),
        ("Цель работы", meta.get('goal', '')),
        ("Методы исследования", meta.get('methods', '')),
        ("Результаты", meta.get('results', '')),
        ("Область применения", meta.get('application', '')),
    ]
    for label, value in fields:
        if value:
            story.append(Paragraph(f"<b>{label}:</b> {value}", s_body))
            story.append(Spacer(1, 4))

    return story

def _build_toc(styles, sections: list):
    story = []
    s_text = styles['TocText']
    s_dots = styles['TocDots']
    s_page = styles['TocPage']

    entries = [("Введение", "3")]
    page = 4
    for heading, _ in sections:
        if not heading:
            continue
        h_up = heading.upper()
        if any(x in h_up for x in ['ВВЕДЕНИЕ', 'ЗАКЛЮЧЕНИЕ', 'СПИСОК', 'ПРИЛОЖЕНИЕ']):
            continue
        entries.append((heading, str(page)))
        page += 3

    entries.append(("Заключение", str(page)))
    entries.append(("Список использованных источников", str(page + 2)))

    for text, pg in entries:
        t = Table(
            [[
                Paragraph(text, s_text),
                Paragraph("." * 90, s_dots),
                Paragraph(pg, s_page),
            ]],
            colWidths=[110 * mm, 40 * mm, 20 * mm],
        )
        t.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(t)

    return story

def build_gost_pdf(
    title: str,
    sections: list,
    standard_key: str = "gost_7.32-2017",
    meta: dict = None,
    work_type: str = "diploma",
) -> io.BytesIO:
    fmt = get_format_info(standard_key)
    fs = fmt.get('font_size', 14)
    ls = fmt.get('line_spacing', 1.5)
    margins = fmt.get('margins', {'left': 30, 'right': 15, 'top': 20, 'bottom': 20})

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=margins['right'] * mm,
        leftMargin=margins['left'] * mm,
        topMargin=margins['top'] * mm,
        bottomMargin=margins['bottom'] * mm,
    )

    styles = make_styles(FONT_REGULAR, FONT_BOLD, fs, ls)
    story = []

    if meta:
        story.extend(_build_title_page(styles, title, meta, work_type))
        story.append(PageBreak())

    has_abstract = meta and meta.get('include_abstract', True)
    if has_abstract:
        story.extend(_build_abstract(styles, title, meta, work_type))
        story.append(PageBreak())

    story.append(Paragraph("ОГЛАВЛЕНИЕ", styles['Heading1']))
    story.append(Spacer(1, 12))
    story.extend(_build_toc(styles, sections))
    story.append(PageBreak())

    for heading, body in sections:
        if heading:
            h_up = heading.upper()
            is_major = heading.isupper() or any(x in h_up for x in [
                'ВВЕДЕНИЕ', 'ЗАКЛЮЧЕНИЕ', 'СПИСОК', 'ЛИТЕРАТУР', 'ПРИЛОЖЕНИЕ'
            ])
            story.append(Paragraph(heading, styles['Heading1'] if is_major else styles['Heading2']))

        for line in body.split('\n'):
            line = line.strip()
            if not line:
                story.append(Spacer(1, ls * 2))
                continue
            if re.match(r'^\d+\.', line) or re.match(r'^\[\d+\]', line):
                story.append(Paragraph(line, styles['Bibliography']))
            else:
                story.append(Paragraph(line, styles['Body']))
        story.append(Spacer(1, ls * 4))

    skip = 2 if has_abstract else 1
    on_page = _make_page_number_fn(skip)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf