"""Renders alts documents to PDF via reportlab — the "real format" for this
slice, same spirit as ``ingest``'s ISO 20022/SWIFT renderers: a later
extraction step has to do real work reading a real document shape, not a
JSON fixture wearing a PDF extension.

``DocTemplate`` exists because one layout, one vocabulary, and one locale
made the extraction corpus too easy to be a real test: every PDF was the
same reportlab template in US English with US number formatting, so
extraction scored 100% field accuracy — a property of the fixture, not
evidence the extractor works. Each fund in ``generate.py``'s
``FUND_UNIVERSE`` now picks a template with its own title wording, field
labels, and money/date formatting, so the corpus spans more than one
administrator's conventions (D-061).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from parvum_alts_hitl.model import CapitalAccountStatement, CapitalCallNotice, DistributionNotice

_STYLES = getSampleStyleSheet()
_BODY = _STYLES["Normal"]


def _money_us(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _money_eur(value: Decimal) -> str:
    """European convention: '.' groups thousands, ',' is the decimal mark —
    the reverse of Python's own formatting, so format US-style first and
    swap the two characters via a placeholder (a direct .replace(",", ".")
    would collide with the mark it's about to produce).

    ``EUR`` as a prefix, not the ``€`` glyph: reportlab's standard Helvetica
    font has no embedded ToUnicode mapping for it, so pypdf's extractor (the
    same extraction path production uses) reads it back as U+FFFD — a
    document-rendering bug that would have quietly fed a mangled amount
    string to the LLM. ``EUR`` also happens to be exactly the ISO 4217 code
    the extraction schema asks for, visible verbatim in the text."""
    sign = "-" if value < 0 else ""
    us_formatted = f"{abs(value):,.2f}"
    swapped = us_formatted.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"{sign}EUR {swapped}"


def _date_iso(value: date) -> str:
    return value.isoformat()


def _date_dmy(value: date) -> str:
    """DD/MM/YYYY — genuinely ambiguous against the US convention for any
    day <= 12, on purpose: this is real extraction difficulty, not a defect
    injected into the document's content (see defects.py's docstring on
    that distinction)."""
    return value.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class DocTemplate:
    """One fund administrator's document conventions."""

    call_title: str
    call_amount_label: str
    call_cumulative_label: str
    call_remaining_label: str
    distribution_title: str
    distribution_amount_label: str
    distribution_cumulative_label: str
    statement_title: Callable[[date], str]
    money: Callable[[Decimal], str]
    date_fmt: Callable[[date], str]
    heading_color: colors.Color
    letterhead: str | None = None


# The original, unchanged layout/vocabulary — the default so every existing
# caller (and every test written against it) keeps behaving exactly as
# before.
PLAIN = DocTemplate(
    call_title="Capital Call Notice",
    call_amount_label="Call Amount",
    call_cumulative_label="Cumulative Called",
    call_remaining_label="Remaining Commitment",
    distribution_title="Distribution Notice",
    distribution_amount_label="Distribution Amount",
    distribution_cumulative_label="Cumulative Distributed",
    # A plain hyphen, not an em-dash: reportlab's standard fonts have no
    # embedded ToUnicode mapping for U+2014, so pypdf's extractor (the same
    # path production uses) reads it back as U+FFFD -- harmless here since
    # no schema field parses the title, but needlessly wrong to leave in.
    statement_title=lambda d: f"Capital Account Statement - Period Ended {d.isoformat()}",
    money=_money_us,
    date_fmt=_date_iso,
    heading_color=colors.black,
)

# Vocabulary drift, still US dollars/ISO dates — isolates "does extraction
# generalise past one wording" from the locale/currency question below.
DRAWDOWN = DocTemplate(
    call_title="Drawdown Notice",
    call_amount_label="Drawdown Amount",
    call_cumulative_label="Cumulative Drawn",
    call_remaining_label="Undrawn Commitment",
    distribution_title="Notice of Distribution",
    distribution_amount_label="Amount Distributed",
    distribution_cumulative_label="Cumulative Distributed to Date",
    statement_title=lambda d: f"Statement of Capital Account - As of {d.isoformat()}",
    money=_money_us,
    date_fmt=_date_iso,
    heading_color=colors.HexColor("#1a3a5c"),
    letterhead="Fund Administration Services",
)

# Locale + currency: European number/date formatting, its own vocabulary —
# attacks parse_decimal (D-053 already found one real bug there) and the
# extraction schema's date-normalisation instruction at once.
EURO = DocTemplate(
    call_title="Capital Contribution Notice",
    call_amount_label="Contribution Amount",
    call_cumulative_label="Cumulative Contributed",
    call_remaining_label="Undrawn Commitment",
    distribution_title="Distribution Advice",
    distribution_amount_label="Amount Distributed",
    distribution_cumulative_label="Cumulative Distributions",
    statement_title=(
        lambda d: f"Capital Account Statement - Period Ending {d.strftime('%d/%m/%Y')}"
    ),
    money=_money_eur,
    date_fmt=_date_dmy,
    heading_color=colors.HexColor("#5c1a2e"),
    # ASCII on purpose, same reason as the money formatter above — an
    # accented name here hit the identical reportlab/pypdf mojibake issue.
    letterhead="Continental Fund Administration Ltd",
)


def _title_style(color: colors.Color) -> ParagraphStyle:
    return ParagraphStyle("AltsTitle", parent=_STYLES["Heading1"], spaceAfter=4, textColor=color)


def _new_document(buffer: BytesIO) -> SimpleDocTemplate:
    return SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.9 * inch, bottomMargin=0.9 * inch)


def _figures_table(rows: list[tuple[str, str]]) -> Table:
    table = Table(rows, colWidths=[2.4 * inch, 3.4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.lightgrey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ]
        )
    )
    return table


def _letterhead(template: DocTemplate) -> list:
    if not template.letterhead:
        return []
    return [Paragraph(template.letterhead, _STYLES["Italic"]), Spacer(1, 6)]


def render_capital_call(notice: CapitalCallNotice, template: DocTemplate = PLAIN) -> bytes:
    buffer = BytesIO()
    story = [
        *_letterhead(template),
        Paragraph(notice.fund_name, _title_style(template.heading_color)),
        Paragraph(template.call_title, _STYLES["Heading2"]),
        Spacer(1, 12),
        Paragraph(
            "Dear Limited Partner, pursuant to the Fund's governing documents, a capital "
            f"contribution is hereby called with respect to your interest (account "
            f"{notice.account_id}). Please remit the amount below by the due date.",
            _BODY,
        ),
        Spacer(1, 14),
        _figures_table(
            [
                ("Call Number", str(notice.call_number)),
                ("Call Date", template.date_fmt(notice.call_date)),
                ("Due Date", template.date_fmt(notice.due_date)),
                (template.call_amount_label, template.money(notice.call_amount)),
                (template.call_cumulative_label, template.money(notice.cumulative_called)),
                (template.call_remaining_label, template.money(notice.remaining_commitment)),
            ]
        ),
    ]
    if notice.purpose:
        story += [Spacer(1, 14), Paragraph(f"Purpose: {notice.purpose}", _BODY)]
    _new_document(buffer).build(story)
    return buffer.getvalue()


def render_distribution(notice: DistributionNotice, template: DocTemplate = PLAIN) -> bytes:
    buffer = BytesIO()
    story = [
        *_letterhead(template),
        Paragraph(notice.fund_name, _title_style(template.heading_color)),
        Paragraph(template.distribution_title, _STYLES["Heading2"]),
        Spacer(1, 12),
        Paragraph(
            "The Fund is pleased to notify you of a distribution with respect to your "
            f"interest (account {notice.account_id}).",
            _BODY,
        ),
        Spacer(1, 14),
        _figures_table(
            [
                ("Distribution Number", str(notice.distribution_number)),
                ("Distribution Date", template.date_fmt(notice.distribution_date)),
                (template.distribution_amount_label, template.money(notice.distribution_amount)),
                (
                    template.distribution_cumulative_label,
                    template.money(notice.cumulative_distributed),
                ),
                ("Source", notice.source.value if notice.source else "Not specified"),
                ("Recallable", "Yes" if notice.recallable else "No"),
            ]
        ),
    ]
    _new_document(buffer).build(story)
    return buffer.getvalue()


def render_capital_account_statement(
    statement: CapitalAccountStatement, template: DocTemplate = PLAIN
) -> bytes:
    buffer = BytesIO()
    story = [
        *_letterhead(template),
        Paragraph(statement.fund_name, _title_style(template.heading_color)),
        Paragraph(template.statement_title(statement.period_end), _STYLES["Heading2"]),
        Spacer(1, 12),
        Paragraph(f"Account: {statement.account_id}", _BODY),
        Spacer(1, 14),
        _figures_table(
            [
                ("Beginning Balance", template.money(statement.beginning_balance)),
                ("Contributions", template.money(statement.contributions)),
                ("Distributions", template.money(statement.distributions)),
                ("Management Fees", template.money(statement.management_fees)),
                ("Realized Gain/Loss", template.money(statement.realized_gain_loss)),
                ("Unrealized Gain/Loss", template.money(statement.unrealized_gain_loss)),
                ("Ending Balance", template.money(statement.ending_balance)),
                ("Total Commitment", template.money(statement.total_commitment)),
                ("Unfunded Commitment", template.money(statement.unfunded_commitment)),
            ]
        ),
    ]
    _new_document(buffer).build(story)
    return buffer.getvalue()
