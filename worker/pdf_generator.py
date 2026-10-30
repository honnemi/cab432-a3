
import os
import re
import boto3
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Flowable,
)

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
BUCKET_NAME = os.environ.get(
    "PHRASEBOOK_BUCKET",
    "n11496096-phrasebooks",
)
FONT_DIR = os.environ.get(
    "FONT_DIR",
    os.path.join(os.path.dirname(__file__), "fonts"),
)

FONT_FILES = {
    "Inter": "Inter-Regular.ttf",
    "Inter-SemiBold": "Inter-SemiBold.ttf",
    "NotoSansJP": "NotoSansJP-Regular.ttf",
    "NotoSansKR": "NotoSansKR-Regular.ttf",
    "NotoSansSC": "NotoSansSC-Regular.ttf",
    "NotoSansThai": "NotoSansThai-Regular.ttf",
}

# Wayword's warm cream and teal palette
PAGE_BG = colors.HexColor("#F7F2E9")
CARD = colors.white
INK = colors.HexColor("#1B2128")
MUTED = colors.HexColor("#6B7380")
TEAL = colors.HexColor("#287D77")
TEAL_DARK = colors.HexColor("#1F635E")
TEAL_TINT = colors.HexColor("#E3EFEC")
SAND = colors.HexColor("#F1EBDD")
BORDER = colors.HexColor("#E6DFD0")
TRACK = colors.HexColor("#E7E1D3")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
CARD_PAD = 6 * mm
INNER_W = CONTENT_W - 2 * CARD_PAD


def _register_font(font_name, filename, fallback):
    path = os.path.join(FONT_DIR, filename)

    if not os.path.isfile(path):
        print(
            f"Font not found: {path}; using {fallback}. "
            "Add the font to the fonts directory for full language support."
        )
        return fallback

    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, path))
        return font_name
    except Exception as exc:
        print(f"Could not register {font_name}: {exc}; using {fallback}")
        return fallback


FONT_REGULAR = _register_font(
    "Inter", FONT_FILES["Inter"], "Helvetica"
)
FONT_SEMIBOLD = _register_font(
    "Inter-SemiBold", FONT_FILES["Inter-SemiBold"], "Helvetica-Bold"
)
FONT_JP = _register_font(
    "NotoSansJP", FONT_FILES["NotoSansJP"], FONT_REGULAR
)
FONT_KR = _register_font(
    "NotoSansKR", FONT_FILES["NotoSansKR"], FONT_REGULAR
)
FONT_SC = _register_font(
    "NotoSansSC", FONT_FILES["NotoSansSC"], FONT_REGULAR
)
FONT_THAI = _register_font(
    "NotoSansThai", FONT_FILES["NotoSansThai"], FONT_REGULAR
)


def _safe(value):
    """Escape text before inserting it into a ReportLab Paragraph."""
    return escape(str(value if value is not None else ""))


def _translation_font(target_language):
    language = str(target_language).strip().lower()

    if any(word in language for word in ("korean", "한국어", "한국")):
        return FONT_KR

    if any(word in language for word in ("japanese", "日本語", "日本")):
        return FONT_JP

    if any(
        word in language
        for word in ("chinese", "中文", "mandarin", "simplified")
    ):
        return FONT_SC

    if any(word in language for word in ("thai", "ไทย")):
        return FONT_THAI

    return FONT_REGULAR


def _formality_details(value):
    """Return a formality score, label, and explanation."""
    explanation = ""
    raw = value

    if isinstance(value, dict):
        raw = value.get("score", value.get("level", ""))
        explanation = str(value.get("explanation") or "")

    if isinstance(raw, (int, float)):
        level = max(1, min(3, int(raw)))
    else:
        text = str(raw).strip().lower()

        if text.isdigit():
            level = max(1, min(3, int(text)))
        else:
            mapping = {
                "very casual": 1,
                "casual": 1,
                "informal": 1,
                "neutral": 2,
                "polite": 2,
                "formal": 3,
                "very formal": 3,
            }
            level = mapping.get(text, 2)

    labels = {
        1: "Casual",
        2: "Polite",
        3: "Formal",
    }

    return level, labels[level], explanation


class FormalityScale(Flowable):
    """Three-segment formality meter with labels."""

    SEG_W = 15 * mm
    GAP = 1.6 * mm
    BAR_H = 2.6 * mm
    LABEL_H = 5 * mm

    def __init__(self, level):
        super().__init__()
        self.level = level
        self.width = 3 * self.SEG_W + 2 * self.GAP
        self.height = self.BAR_H + self.LABEL_H

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        canvas = self.canv

        shades = [
            colors.HexColor("#8DBDB8"),
            colors.HexColor("#4F9A93"),
            TEAL_DARK,
        ]
        names = ("Casual", "Polite", "Formal")
        bar_y = self.LABEL_H

        for i in range(3):
            x = i * (self.SEG_W + self.GAP)
            filled = (i + 1) <= self.level

            canvas.setFillColor(shades[i] if filled else TRACK)
            canvas.roundRect(
                x,
                bar_y,
                self.SEG_W,
                self.BAR_H,
                self.BAR_H / 2,
                stroke=0,
                fill=1,
            )

            active = (i + 1) == self.level
            canvas.setFillColor(TEAL_DARK if active else MUTED)
            canvas.setFont(
                FONT_SEMIBOLD if active else FONT_REGULAR,
                6.3,
            )
            canvas.drawCentredString(
                x + self.SEG_W / 2,
                0.8 * mm,
                names[i].upper(),
            )


def _make_styles(translation_font):
    base = getSampleStyleSheet()

    def style(name, **kwargs):
        return ParagraphStyle(
            name,
            parent=base["Normal"],
            **kwargs,
        )

    return {
        "eyebrow": style(
            "Eyebrow",
            fontName=FONT_SEMIBOLD,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            alignment=TA_LEFT,
            spaceAfter=3 * mm,
            charSpace=2,
        ),
        "title": style(
            "BookTitle",
            fontName=FONT_SEMIBOLD,
            fontSize=30,
            leading=34,
            textColor=INK,
            spaceAfter=3 * mm,
            wordWrap="CJK",
        ),
        "subtitle": style(
            "Subtitle",
            fontName=FONT_REGULAR,
            fontSize=10,
            leading=15,
            textColor=MUTED,
        ),
        "num": style(
            "Num",
            fontName=FONT_SEMIBOLD,
            fontSize=8,
            leading=10,
            textColor=TEAL_DARK,
            alignment=1,
        ),
        "english": style(
            "English",
            fontName=FONT_SEMIBOLD,
            fontSize=9.5,
            leading=13,
            textColor=MUTED,
        ),
        "translation": style(
            "Translation",
            fontName=translation_font,
            fontSize=20,
            leading=27,
            textColor=INK,
            wordWrap="CJK",
        ),
        "key": style(
            "Key",
            fontName=FONT_SEMIBOLD,
            fontSize=6.8,
            leading=10,
            textColor=TEAL,
            charSpace=0.8,
        ),
        "value": style(
            "Value",
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=14,
            textColor=INK,
        ),
        "value_native": style(
            "ValueNative",
            fontName=translation_font,
            fontSize=9.5,
            leading=14,
            textColor=INK,
            wordWrap="CJK",
        ),
        "alt_translation": style(
            "AltTranslation",
            fontName=translation_font,
            fontSize=12.5,
            leading=18,
            textColor=INK,
            wordWrap="CJK",
        ),
        "alt_detail": style(
            "AltDetail",
            fontName=FONT_REGULAR,
            fontSize=8.3,
            leading=12,
            textColor=MUTED,
        ),
        "alt_detail_native": style(
            "AltDetailNative",
            fontName=translation_font,
            fontSize=8.3,
            leading=12,
            textColor=MUTED,
            wordWrap="CJK",
        ),
        "formality_text": style(
            "FormalityText",
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=12.5,
            textColor=MUTED,
        ),
        "section_label": style(
            "SectionLabel",
            fontName=FONT_SEMIBOLD,
            fontSize=6.8,
            leading=10,
            textColor=MUTED,
            charSpace=1,
        ),
    }


def _info_rows(rows, styles):
    """Render label/value rows with a fixed label column."""
    if not rows:
        return None

    data = [
        [Paragraph(label, styles["key"]), value]
        for label, value in rows
    ]

    table = Table(
        data,
        colWidths=[28 * mm, INNER_W - 28 * mm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
    ]))

    return table


def _alternatives_panel(alternatives, styles):
    """Render casual, polite, and formal alternative translations."""
    rows = []

    for key, label in (
        ("casual", "CASUAL"),
        ("polite", "POLITE"),
        ("formal", "FORMAL"),
    ):
        alt = alternatives.get(key)

        if not isinstance(alt, dict) or not alt.get("translation"):
            continue

        stack = [
            Paragraph(
                _safe(alt["translation"]),
                styles["alt_translation"],
            )
        ]

        for field, prefix, native in (
            ("romanisation", "Romanisation", False),
            ("pronunciation_guide", "Pronunciation", False),
            ("context", "Usage", True),
        ):
            if alt.get(field):
                detail_style = (
                    styles["alt_detail_native"]
                    if native
                    else styles["alt_detail"]
                )
                stack.append(
                    Paragraph(
                        f"<font name='{FONT_SEMIBOLD}'>{prefix}:</font> "
                        f"{_safe(alt[field])}",
                        detail_style,
                    )
                )

        rows.append([
            Paragraph(label, styles["key"]),
            stack,
        ])

    if not rows:
        return None

    table = Table(
        rows,
        colWidths=[22 * mm, INNER_W - 22 * mm - 8 * mm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SAND),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#E2DAC8")),
    ]))

    return table


def _build_card(index, phrase, styles):
    level, level_label, explanation = _formality_details(
        phrase.get("formality")
    )

    inner = []

    header = Table(
        [[
            Paragraph(f"{index:02d}", styles["num"]),
            Paragraph(
                _safe(phrase.get("english", "")),
                styles["english"],
            ),
        ]],
        colWidths=[10 * mm, INNER_W - 12 * mm],
        rowHeights=[6.5 * mm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), TEAL_TINT),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 3.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    inner.append(header)
    inner.append(Spacer(1, 4 * mm))

    inner.append(
        Paragraph(
            _safe(phrase.get("translation", "")),
            styles["translation"],
        )
    )
    inner.append(Spacer(1, 2.5 * mm))

    rows = []

    if phrase.get("romanisation"):
        rows.append((
            "ROMANISATION",
            Paragraph(
                _safe(phrase["romanisation"]),
                styles["value"],
            ),
        ))

    if phrase.get("pronunciation_guide"):
        rows.append((
            "PRONUNCIATION",
            Paragraph(
                _safe(phrase["pronunciation_guide"]),
                styles["value"],
            ),
        ))

    if phrase.get("context"):
        rows.append((
            "WHEN TO USE",
            Paragraph(
                _safe(phrase["context"]),
                styles["value_native"],
            ),
        ))

    info = _info_rows(rows, styles)

    if info is not None:
        inner.append(info)

    inner.append(Spacer(1, 3 * mm))

    formality_text = (
        f"<font name='{FONT_SEMIBOLD}' "
        f"color='{TEAL_DARK.hexval()}'>"
        f"{level_label} &nbsp;·&nbsp; {level}/3</font>"
    )

    if explanation:
        formality_text += f"<br/>{_safe(explanation)}"

    scale = FormalityScale(level)

    formality = Table(
        [[
            scale,
            Paragraph(formality_text, styles["formality_text"]),
        ]],
        colWidths=[
            scale.width + 8 * mm,
            INNER_W - scale.width - 8 * mm,
        ],
    )
    formality.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    inner.append(
        Paragraph("FORMALITY", styles["section_label"])
    )
    inner.append(Spacer(1, 1.6 * mm))
    inner.append(formality)

    alternatives = phrase.get("alternatives", {})

    if isinstance(alternatives, dict):
        panel = _alternatives_panel(alternatives, styles)

        if panel is not None:
            inner.append(Spacer(1, 4 * mm))
            inner.append(
                Paragraph("ALTERNATIVES", styles["section_label"])
            )
            inner.append(Spacer(1, 1.6 * mm))
            inner.append(panel)

    # Compatibility with older worker output
    elif phrase.get("alternative"):
        inner.append(Spacer(1, 3 * mm))
        inner.append(
            Paragraph("ALTERNATIVE", styles["key"])
        )
        inner.append(
            Paragraph(
                _safe(phrase["alternative"]),
                styles["value_native"],
            )
        )

    card = Table([[inner]], colWidths=[CONTENT_W])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("LEFTPADDING", (0, 0), (-1, -1), CARD_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), CARD_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5 * mm),
    ]))

    return card


def _title_block(phrasebook_name, target_language, count, styles):
    """Build the cover header using the user's custom phrasebook name."""
    pill_style = ParagraphStyle(
        "Pill",
        fontName=FONT_SEMIBOLD,
        fontSize=8,
        leading=10,
        textColor=WHITE,
        alignment=1,
    )

    label = f"{count} phrase" + ("" if count == 1 else "s")

    pill = Table(
        [[Paragraph(label.upper(), pill_style)]],
        colWidths=[26 * mm],
        rowHeights=[7 * mm],
    )
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL),
        ("ROUNDEDCORNERS", [3.5, 3.5, 3.5, 3.5]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    pill.hAlign = "LEFT"

    return [
        Paragraph("TRAVEL PHRASEBOOK", styles["eyebrow"]),
        Paragraph(_safe(phrasebook_name), styles["title"]),
        Paragraph(
            f"Useful {_safe(target_language)} phrases for getting around, "
            "connecting and exploring.",
            styles["subtitle"],
        ),
        Spacer(1, 5 * mm),
        pill,
        Spacer(1, 9 * mm),
    ]


def _draw_page(canvas, doc):
    """Draw the cream page background and understated footer."""
    canvas.saveState()

    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN_X, 10 * mm, "Wayword")
    canvas.drawRightString(
        PAGE_W - MARGIN_X,
        10 * mm,
        str(canvas.getPageNumber()),
    )

    canvas.restoreState()


def _safe_filename(name):
    """Create a safe filename from the custom phrasebook name."""
    filename = re.sub(r"[^\w\- ]+", "", str(name), flags=re.UNICODE)
    filename = re.sub(r"\s+", "-", filename.strip())
    filename = filename.strip("-_")

    return filename[:80] or "phrasebook"


def generate_phrasebook(
    data,
    job_id,
    output_path=None,
    phrasebook_name="My Phrasebook",
):
    target_language = data.get("target_language", "Target language")
    phrases = data.get("phrases", [])

    phrasebook_name = (
        str(phrasebook_name).strip() or "My Phrasebook"
    )

    if output_path is None:
        filename = _safe_filename(phrasebook_name)
        output_path = os.path.join(
            "outputs",
            job_id,
            f"{filename}.pdf",
        )

    os.makedirs(
        os.path.dirname(os.path.abspath(output_path)),
        exist_ok=True,
    )

    styles = _make_styles(_translation_font(target_language))

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=20 * mm,
        bottomMargin=19 * mm,
        title=phrasebook_name,
        author="Wayword",
        subject="Translated travel phrases and pronunciation notes",
    )

    story = _title_block(
        phrasebook_name,
        target_language,
        len(phrases),
        styles,
    )

    for index, phrase in enumerate(phrases, start=1):
        if not isinstance(phrase, dict):
            phrase = {"english": str(phrase)}

        story.append(_build_card(index, phrase, styles))
        story.append(Spacer(1, 5 * mm))

    doc.build(
        story,
        onFirstPage=_draw_page,
        onLaterPages=_draw_page,
    )

    return output_path


def upload_pdf(pdf_path, job_id):
    """Upload the generated PDF to a unique S3 key for this job."""
    s3 = boto3.client("s3", region_name=REGION)
    s3_key = f"outputs/{job_id}/booklet.pdf"

    s3.upload_file(
        pdf_path,
        BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )

    return {
        "job_id": job_id,
        "bucket": BUCKET_NAME,
        "key": s3_key,
    }
