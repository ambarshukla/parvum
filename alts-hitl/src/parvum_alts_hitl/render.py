"""Renders alts documents to PDF via reportlab — the "real format" for this
slice, same spirit as ``ingest``'s ISO 20022/SWIFT renderers: a later
extraction step has to do real work reading a real document shape, not a
JSON fixture wearing a PDF extension.
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from parvum_alts_hitl.model import CapitalAccountStatement, CapitalCallNotice, DistributionNotice

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("AltsTitle", parent=_STYLES["Heading1"], spaceAfter=4)
_BODY = _STYLES["Normal"]


def _money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


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


def render_capital_call(notice: CapitalCallNotice) -> bytes:
    buffer = BytesIO()
    story = [
        Paragraph(notice.fund_name, _TITLE),
        Paragraph("Capital Call Notice", _STYLES["Heading2"]),
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
                ("Call Date", notice.call_date.isoformat()),
                ("Due Date", notice.due_date.isoformat()),
                ("Call Amount", _money(notice.call_amount)),
                ("Cumulative Called", _money(notice.cumulative_called)),
                ("Remaining Commitment", _money(notice.remaining_commitment)),
            ]
        ),
    ]
    if notice.purpose:
        story += [Spacer(1, 14), Paragraph(f"Purpose: {notice.purpose}", _BODY)]
    _new_document(buffer).build(story)
    return buffer.getvalue()


def render_distribution(notice: DistributionNotice) -> bytes:
    buffer = BytesIO()
    story = [
        Paragraph(notice.fund_name, _TITLE),
        Paragraph("Distribution Notice", _STYLES["Heading2"]),
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
                ("Distribution Date", notice.distribution_date.isoformat()),
                ("Distribution Amount", _money(notice.distribution_amount)),
                ("Cumulative Distributed", _money(notice.cumulative_distributed)),
                ("Source", notice.source.value if notice.source else "Not specified"),
                ("Recallable", "Yes" if notice.recallable else "No"),
            ]
        ),
    ]
    _new_document(buffer).build(story)
    return buffer.getvalue()


def render_capital_account_statement(statement: CapitalAccountStatement) -> bytes:
    buffer = BytesIO()
    story = [
        Paragraph(statement.fund_name, _TITLE),
        Paragraph(
            f"Capital Account Statement — Period Ended {statement.period_end.isoformat()}",
            _STYLES["Heading2"],
        ),
        Spacer(1, 12),
        Paragraph(f"Account: {statement.account_id}", _BODY),
        Spacer(1, 14),
        _figures_table(
            [
                ("Beginning Balance", _money(statement.beginning_balance)),
                ("Contributions", _money(statement.contributions)),
                ("Distributions", _money(statement.distributions)),
                ("Management Fees", _money(statement.management_fees)),
                ("Realized Gain/Loss", _money(statement.realized_gain_loss)),
                ("Unrealized Gain/Loss", _money(statement.unrealized_gain_loss)),
                ("Ending Balance", _money(statement.ending_balance)),
                ("Total Commitment", _money(statement.total_commitment)),
                ("Unfunded Commitment", _money(statement.unfunded_commitment)),
            ]
        ),
    ]
    _new_document(buffer).build(story)
    return buffer.getvalue()
