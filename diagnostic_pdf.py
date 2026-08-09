"""Generate a branded client-facing PDF for a vehicle diagnostic card."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image as PILImage, ImageDraw

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


APEX = colors.HexColor("#FFD600")
INK = colors.HexColor("#080D12")
PANEL = colors.HexColor("#111A23")
MUTED = colors.HexColor("#93A3B5")
LINE = colors.HexColor("#2A3846")
SOFT = colors.HexColor("#182431")
GREEN = colors.HexColor("#16A36A")
RED = colors.HexColor("#E34850")

STATUS_LABELS = {
    "unchecked": "Не проверено",
    "ok": "Норма",
    "attention": "Внимание",
    "critical": "Неисправно",
}
SECTION_LABELS = {
    "general": "Основное",
    "front_suspension": "Передняя подвеска",
    "rear_suspension": "Задняя подвеска",
    "brakes": "Тормозная система",
    "engine": "Двигатель",
    "body": "Кузов и салон",
    "electrics": "Электрика",
    "ac": "Климат",
}


def _register_fonts() -> tuple[str, str]:
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    bold_candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]
    regular = next((path for path in candidates if path.is_file()), None)
    bold = next((path for path in bold_candidates if path.is_file()), None)
    if regular and bold:
        pdfmetrics.registerFont(TTFont("ApexRegular", str(regular)))
        pdfmetrics.registerFont(TTFont("ApexBold", str(bold)))
        return "ApexRegular", "ApexBold"
    return "Helvetica", "Helvetica-Bold"


def _worst_status(item: Mapping[str, object]) -> str:
    values = [item.get("status"), item.get("left_status"), item.get("right_status")]
    if "critical" in values:
        return "critical"
    if "attention" in values:
        return "attention"
    if "ok" in values:
        return "ok"
    return "unchecked"


def _rounded_logo(path: Path, radius: int = 70) -> BytesIO:
    source = PILImage.open(path).convert("RGBA")
    mask = PILImage.new("L", source.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *source.size), radius=radius, fill=255)
    source.putalpha(mask)
    output = BytesIO()
    source.save(output, format="PNG")
    output.seek(0)
    return output


def build_diagnostic_pdf(
    diagnostic: Mapping[str, object],
    *,
    logo_path: Path | None = None,
    photo_dir: Path | None = None,
) -> bytes:
    """Return a complete branded PDF as bytes."""
    regular, bold = _register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=regular, fontSize=8.5, leading=11, textColor=colors.white)
    small = ParagraphStyle("Small", parent=body, fontSize=7.5, leading=9, textColor=MUTED)
    heading = ParagraphStyle("Heading", parent=body, fontName=bold, fontSize=13, leading=16, spaceAfter=5)
    title = ParagraphStyle("Title", parent=body, fontName=bold, fontSize=18, leading=21, textColor=colors.white)
    center = ParagraphStyle("Center", parent=body, alignment=TA_CENTER)
    table_head = ParagraphStyle("TableHead", parent=small, fontName=bold, textColor=INK)

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"Диагностическая карта #{diagnostic['id']}",
        author="Apex Auto",
    )
    story: list[object] = []

    brand: object = Paragraph("<b><font color='#F7FAFC'>APEX</font> <font color='#FFD600'>AUTO</font></b><br/><font size='8' color='#FFD600'>ДИАГНОСТИЧЕСКАЯ КАРТА</font>", title)
    if logo_path and logo_path.is_file():
        brand = Table([[Image(_rounded_logo(logo_path), 25 * mm, 25 * mm), brand]], colWidths=[30 * mm, 120 * mm])
        brand.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    vehicle = Paragraph(
        f"<b>{diagnostic.get('brand', '')} {diagnostic.get('model', '')}</b><br/>"
        f"<font size='9'>{diagnostic.get('plate_number') or 'Без госномера'}"
        f"{(' · ' + str(diagnostic.get('vin'))) if diagnostic.get('vin') else ''}</font>",
        title,
    )
    header = Table([[brand, vehicle]], colWidths=[95 * mm, 91 * mm], hAlign="LEFT")
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#34404B")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 6 * mm)])

    items = list(diagnostic.get("items", []))
    counts = {key: sum(1 for item in items if _worst_status(item) == key) for key in STATUS_LABELS}
    summary = Table([
        [Paragraph(f"<b>{counts['attention']}</b><br/><font color='#9A7B00'>Требует внимания</font>", center),
         Paragraph(f"<b>{counts['critical']}</b><br/><font color='#E34850'>Неисправно</font>", center)],
    ], colWidths=[93 * mm] * 2)
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary, Spacer(1, 5 * mm)])

    details = [
        [Paragraph("Клиент", small), Paragraph(str(diagnostic.get("customer_name") or "Не указан"), body)],
        [Paragraph("Пробег", small), Paragraph(f"{diagnostic.get('mileage') or 'Не указан'} км", body)],
        [Paragraph("Заказ-наряд", small), Paragraph(f"#{diagnostic['service_order_id']}" if diagnostic.get("service_order_id") else "Не связан", body)],
        [Paragraph("Статус", small), Paragraph("Завершена" if diagnostic.get("status") == "completed" else "В работе", body)],
    ]
    info = Table(details, colWidths=[36 * mm, 150 * mm])
    info.setStyle(TableStyle([("ROWBACKGROUNDS", (0, 0), (-1, -1), [PANEL, SOFT]), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend([info, Spacer(1, 6 * mm)])

    issue_items = [item for item in items if _worst_status(item) in {"attention", "critical"}]
    if not issue_items:
        no_issues = Table([[Paragraph("<b>По результатам диагностики замечаний не выявлено.</b>", body)]], colWidths=[186 * mm])
        no_issues.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10271F")), ("BOX", (0, 0), (-1, -1), 0.8, GREEN), ("TEXTCOLOR", (0, 0), (-1, -1), GREEN), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
        story.extend([no_issues, Spacer(1, 5 * mm)])

    for section_key, section_label in SECTION_LABELS.items():
        section_items = [item for item in issue_items if item.get("section_key") == section_key]
        if not section_items:
            continue
        rows = [[Paragraph("Проверяемый узел", table_head), Paragraph("Состояние", table_head), Paragraph("Комментарий / рекомендация", table_head)]]
        for item in section_items:
            status = _worst_status(item)
            sided = item.get("left_status") is not None or item.get("right_status") is not None
            status_text = STATUS_LABELS[status]
            if sided:
                status_text = f"Л: {STATUS_LABELS.get(str(item.get('left_status')), 'Не проверено')}<br/>П: {STATUS_LABELS.get(str(item.get('right_status')), 'Не проверено')}"
            notes = "<br/>".join(filter(None, [str(item.get("comment") or ""), str(item.get("recommendation") or "")])) or "-"
            if item.get("estimated_cost") is not None:
                notes += f"<br/><b>Оценка: {int(item['estimated_cost']):,} ₽</b>".replace(",", " ")
            rows.append([Paragraph(str(item.get("label", "")), body), Paragraph(status_text, body), Paragraph(notes, body)])
        table = Table(rows, colWidths=[68 * mm, 39 * mm, 79 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), APEX),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK),
            ("FONTNAME", (0, 0), (-1, 0), bold),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PANEL, SOFT]),
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([KeepTogether([Paragraph(section_label, heading), table]), Spacer(1, 5 * mm)])

    if diagnostic.get("notes"):
        story.extend([Paragraph("Комментарий мастера", heading), Table([[Paragraph(str(diagnostic["notes"]), body)]], colWidths=[186 * mm], style=[("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("PADDING", (0, 0), (-1, -1), 8)]), Spacer(1, 5 * mm)])

    photos: Sequence[Mapping[str, object]] = diagnostic.get("photos", [])  # type: ignore[assignment]
    existing_photos = [photo_dir / str(photo["filename"]) for photo in photos if photo_dir and (photo_dir / str(photo["filename"])).is_file()]
    if existing_photos:
        story.append(Paragraph("Фотографии диагностики", heading))
        cells = [Image(str(path), 43 * mm, 43 * mm, kind="proportional") for path in existing_photos]
        photo_rows = [cells[index:index + 4] for index in range(0, len(cells), 4)]
        story.append(Table(photo_rows, colWidths=[46.5 * mm] * 4, style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("PADDING", (0, 0), (-1, -1), 4)]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


class _VehicleCard(Flowable):
    def __init__(self, diagnostic: Mapping[str, object], issues_count: int, regular: str, bold: str):
        super().__init__()
        self.width = 186 * mm
        self.height = 31 * mm
        self.data = diagnostic
        self.issues_count = issues_count
        self.regular = regular
        self.bold = bold

    def draw(self):
        c = self.canv
        c.setFillColor(SOFT)
        c.setStrokeColor(LINE)
        c.roundRect(0, 0, self.width, self.height, 13, fill=1, stroke=1)
        c.setFillColor(colors.white)
        c.setFont(self.bold, 19)
        c.drawString(7 * mm, 20 * mm, f"{self.data.get('brand', '')} {self.data.get('model', '')}".upper())
        c.setFillColor(MUTED)
        c.setFont(self.regular, 8)
        vehicle_line = f"{self.data.get('plate_number') or 'Без госномера'}  ·  {self.data.get('vin') or 'VIN не указан'}"
        c.drawString(7 * mm, 11 * mm, vehicle_line)
        c.setFillColor(APEX)
        c.setFont(self.bold, 11)
        c.drawRightString(self.width - 7 * mm, 19 * mm, f"{self.issues_count} ЗАМЕЧАНИЯ")
        c.setFillColor(MUTED)
        c.setFont(self.bold, 7.5)
        order = f"Заказ-наряд #{self.data['service_order_id']}" if self.data.get("service_order_id") else "Без заказ-наряда"
        c.drawRightString(self.width - 7 * mm, 11 * mm, order)


class _IssueCard(Flowable):
    def __init__(self, item: Mapping[str, object], regular: str, bold: str):
        super().__init__()
        self.width = 186 * mm
        self.height = 25 * mm
        self.item = item
        self.regular = regular
        self.bold = bold

    def draw(self):
        c = self.canv
        status = _worst_status(self.item)
        accent = RED if status == "critical" else colors.HexColor("#FFBD2E")
        c.setFillColor(SOFT)
        c.setStrokeColor(LINE)
        c.roundRect(0, 0, self.width, self.height, 11, fill=1, stroke=1)
        c.setFillColor(accent)
        c.roundRect(5 * mm, 5 * mm, 1.7 * mm, 15 * mm, 1.5, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont(self.bold, 6.5)
        section = SECTION_LABELS.get(str(self.item.get("section_key")), str(self.item.get("section_key", ""))).upper()
        c.drawString(10 * mm, 18.2 * mm, section)
        c.setFillColor(colors.white)
        c.setFont(self.bold, 10)
        c.drawString(10 * mm, 12.6 * mm, str(self.item.get("label", ""))[:62])
        notes = " · ".join(filter(None, [str(self.item.get("comment") or ""), str(self.item.get("recommendation") or "")])) or "Без комментария"
        note_style = ParagraphStyle("IssueNote", fontName=self.regular, fontSize=7.2, leading=8.3, textColor=MUTED)
        note = Paragraph(notes, note_style)
        note.wrapOn(c, 118 * mm, 8 * mm)
        note.drawOn(c, 10 * mm, 3.5 * mm)
        c.setFillColor(accent)
        c.setFont(self.bold, 7.5)
        c.drawRightString(self.width - 6 * mm, 17.5 * mm, STATUS_LABELS[status])
        if self.item.get("estimated_cost") is not None:
            price = f"{int(self.item['estimated_cost']):,} ₽".replace(",", " ")
            c.setFillColor(APEX)
            c.setFont(self.bold, 10)
            c.drawRightString(self.width - 6 * mm, 7.5 * mm, price)


def build_diagnostic_pdf(
    diagnostic: Mapping[str, object],
    *,
    logo_path: Path | None = None,
    photo_dir: Path | None = None,
) -> bytes:
    """Generate the selected dark card-style client report."""
    regular, bold = _register_fonts()
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"Диагностическая карта #{diagnostic['id']}",
        author="Apex Auto",
    )
    story: list[object] = []
    brand_style = ParagraphStyle("CardBrand", fontName=bold, fontSize=18, leading=19, textColor=colors.white)
    brand = Paragraph("<font color='#F7FAFC'>APEX</font> <font color='#FFD600'>AUTO</font><br/><font size='7' color='#FFD600'>ДИАГНОСТИЧЕСКАЯ КАРТА</font>", brand_style)
    if logo_path and logo_path.is_file():
        brand_row: object = Table([[Image(_rounded_logo(logo_path), 22 * mm, 22 * mm), brand]], colWidths=[28 * mm, 158 * mm])
        brand_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        story.append(brand_row)
    else:
        story.append(brand)
    story.append(Spacer(1, 6 * mm))

    items = list(diagnostic.get("items", []))
    issue_items = [item for item in items if _worst_status(item) in {"attention", "critical"}]
    story.extend([_VehicleCard(diagnostic, len(issue_items), regular, bold), Spacer(1, 7 * mm)])
    section_style = ParagraphStyle("CardSection", fontName=bold, fontSize=10, leading=12, textColor=colors.white)
    story.extend([Paragraph("ВЫЯВЛЕННЫЕ ЗАМЕЧАНИЯ", section_style), Spacer(1, 4 * mm)])
    if issue_items:
        for item in issue_items:
            story.extend([_IssueCard(item, regular, bold), Spacer(1, 3 * mm)])
    else:
        ok_style = ParagraphStyle("NoIssues", fontName=bold, fontSize=10, textColor=GREEN)
        no_issues = Table([[Paragraph("По результатам диагностики замечаний не выявлено.", ok_style)]], colWidths=[186 * mm])
        no_issues.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10271F")), ("BOX", (0, 0), (-1, -1), 0.8, GREEN), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story.append(no_issues)

    if diagnostic.get("notes"):
        story.extend([Spacer(1, 4 * mm), Paragraph("КОММЕНТАРИЙ МАСТЕРА", section_style), Spacer(1, 3 * mm)])
        note_style = ParagraphStyle("MasterNote", fontName=regular, fontSize=8.5, leading=11, textColor=colors.white)
        note = Table([[Paragraph(str(diagnostic["notes"]), note_style)]], colWidths=[186 * mm])
        note.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(note)

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    document.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
