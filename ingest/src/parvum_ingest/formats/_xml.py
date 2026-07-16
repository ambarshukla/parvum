"""Shared ElementTree helpers for the ISO 20022 XML formats.

Extracted once a second XML format (camt.053) arrived — the helpers are
identical across messages except for the namespace and the error prefix,
which every function takes explicitly.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from parvum_ingest.formats import FeedParseError
from parvum_ingest.model import Money


def qname(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def child(
    parent: ET.Element, ns: str, tag: str, text: str | None = None, **attrib: str
) -> ET.Element:
    el = ET.SubElement(parent, qname(ns, tag), attrib)
    if text is not None:
        el.text = text
    return el


def dec_str(value: Decimal) -> str:
    # :f suppresses scientific notation — "1E+2" is not a wire-format number.
    return f"{value:f}"


def find_text(parent: ET.Element, nsmap: dict[str, str], path: str, context: str, fmt: str) -> str:
    el = parent.find(path, nsmap)
    if el is None or el.text is None:
        raise FeedParseError(f"{fmt}: missing required element {path!r} in {context}")
    return el.text


def opt_text(parent: ET.Element, nsmap: dict[str, str], path: str) -> str | None:
    el = parent.find(path, nsmap)
    return None if el is None or el.text is None else el.text


def parse_decimal(raw: str, context: str, fmt: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise FeedParseError(f"{fmt}: {raw!r} is not a number in {context}") from exc


def parse_iso_date(raw: str, context: str, fmt: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise FeedParseError(f"{fmt}: {raw!r} is not an ISO date in {context}") from exc


def parse_money(el: ET.Element, context: str, fmt: str) -> Money:
    ccy = el.get("Ccy")
    if not ccy:
        raise FeedParseError(f"{fmt}: missing Ccy attribute in {context}")
    if el.text is None:
        raise FeedParseError(f"{fmt}: empty amount in {context}")
    return Money(amount=parse_decimal(el.text, context, fmt), currency=ccy)


def parse_document(xml_text: str, ns: str, fmt: str) -> ET.Element:
    """Parse and verify the root is <Document> in the expected namespace —
    which is how an XML message declares *which* message it claims to be."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedParseError(f"{fmt}: not well-formed XML: {exc}") from exc
    if root.tag != qname(ns, "Document"):
        raise FeedParseError(f"{fmt}: unexpected root element {root.tag!r}")
    return root
