"""semt.002 (ISO 20022 Securities Balance Custody Report) — render & parse.

Scope honesty (D-010): this emits/reads a *subset shaped after* the
semt.002.001 message — real element names and nesting for the fields our
model carries, but simplified (e.g. one level of Qty nesting, not three)
and not yet validated against the official XSD schema. Spec-exact fidelity
is a recorded backlog item; the parsing lessons are real either way.

Field-coverage note: this subset does not carry cost basis at all — as in
real custody statements, where acquisition cost typically arrives on other
feeds or not at all. Round-tripping a Position through semt.002 therefore
yields cost_basis=None; reconciliation must live with that.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from parvum_ingest.formats import FeedParseError
from parvum_ingest.model import (
    Account,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Money,
    Position,
    SecurityIdentifier,
)

NS = "urn:iso:std:iso:20022:tech:xsd:semt.002.001.11"
_NSMAP = {"s": NS}


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _child(parent: ET.Element, tag: str, text: str | None = None, **attrib: str) -> ET.Element:
    el = ET.SubElement(parent, _q(tag), attrib)
    if text is not None:
        el.text = text
    return el


def _dec(value: Decimal) -> str:
    # :f suppresses scientific notation — "1E+2" is not a wire-format number.
    return f"{value:f}"


def render_semt002(stmt: HoldingsStatement) -> str:
    # Serialize with a default namespace (<Document xmlns=...>), matching how
    # real ISO 20022 messages are written, rather than ElementTree's ns0: prefixes.
    ET.register_namespace("", NS)
    root = ET.Element(_q("Document"))
    rpt = _child(root, "SctiesBalCtdyRpt")

    gnl = _child(rpt, "StmtGnlDtls")
    _child(gnl, "StmtId", stmt.statement_id)
    _child(_child(gnl, "StmtDtTm"), "Dt", stmt.as_of.isoformat())

    acct = _child(rpt, "SfkpgAcct")
    _child(acct, "Id", stmt.account.account_id)
    if stmt.account.name is not None:
        _child(acct, "Nm", stmt.account.name)
    if stmt.account.custodian_bic is not None:
        _child(_child(acct, "AcctSvcr"), "AnyBIC", stmt.account.custodian_bic)
    if stmt.account.base_currency is not None:
        _child(acct, "BaseCcy", stmt.account.base_currency)

    for pos in stmt.positions:
        bal = _child(rpt, "BalForAcct")
        fin = _child(bal, "FinInstrmId")
        if pos.security.scheme is IdentifierScheme.ISIN:
            _child(fin, "ISIN", pos.security.value)
        else:
            othr = _child(fin, "OthrId")
            _child(othr, "Id", pos.security.value)
            _child(othr, "Tp", pos.security.scheme.value)
        _child(fin, "Desc", pos.security_name)

        _child(_child(bal, "AggtBal"), "Unit", _dec(pos.quantity))

        if pos.price is not None:
            pric = _child(bal, "PricDtls")
            _child(pric, "Val", _dec(pos.price.amount), Ccy=pos.price.currency)
            if pos.price_as_of is not None:
                _child(pric, "Dt", pos.price_as_of.isoformat())

        if pos.market_value is not None:
            hldg = _child(_child(bal, "AcctBaseCcyAmts"), "HldgVal")
            _child(hldg, "Amt", _dec(pos.market_value.amount), Ccy=pos.market_value.currency)

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# --- parsing --------------------------------------------------------------


def _find_text(parent: ET.Element, path: str, context: str) -> str:
    el = parent.find(path, _NSMAP)
    if el is None or el.text is None:
        raise FeedParseError(f"semt.002: missing required element {path!r} in {context}")
    return el.text


def _opt_text(parent: ET.Element, path: str) -> str | None:
    el = parent.find(path, _NSMAP)
    return None if el is None or el.text is None else el.text


def _parse_decimal(raw: str, context: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise FeedParseError(f"semt.002: {raw!r} is not a number in {context}") from exc


def _parse_date(raw: str, context: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise FeedParseError(f"semt.002: {raw!r} is not an ISO date in {context}") from exc


def _parse_security(fin: ET.Element) -> SecurityIdentifier:
    isin = fin.find("s:ISIN", _NSMAP)
    if isin is not None and isin.text:
        return SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=isin.text)
    scheme_raw = _find_text(fin, "s:OthrId/s:Tp", "FinInstrmId/OthrId")
    try:
        scheme = IdentifierScheme(scheme_raw)
    except ValueError as exc:
        raise FeedParseError(f"semt.002: unknown identifier scheme {scheme_raw!r}") from exc
    return SecurityIdentifier(scheme=scheme, value=_find_text(fin, "s:OthrId/s:Id", "OthrId"))


def _parse_money(el: ET.Element, context: str) -> Money:
    ccy = el.get("Ccy")
    if not ccy:
        raise FeedParseError(f"semt.002: missing Ccy attribute in {context}")
    if el.text is None:
        raise FeedParseError(f"semt.002: empty amount in {context}")
    return Money(amount=_parse_decimal(el.text, context), currency=ccy)


def parse_semt002(xml_text: str) -> HoldingsStatement:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedParseError(f"semt.002: not well-formed XML: {exc}") from exc
    if root.tag != _q("Document"):
        raise FeedParseError(f"semt.002: unexpected root element {root.tag!r}")

    rpt = root.find("s:SctiesBalCtdyRpt", _NSMAP)
    if rpt is None:
        raise FeedParseError("semt.002: missing SctiesBalCtdyRpt")

    statement_id = _find_text(rpt, "s:StmtGnlDtls/s:StmtId", "StmtGnlDtls")
    as_of = _parse_date(_find_text(rpt, "s:StmtGnlDtls/s:StmtDtTm/s:Dt", "StmtGnlDtls"), "StmtDtTm")

    acct_el = rpt.find("s:SfkpgAcct", _NSMAP)
    if acct_el is None:
        raise FeedParseError("semt.002: missing SfkpgAcct")
    account = Account(
        account_id=_find_text(acct_el, "s:Id", "SfkpgAcct"),
        name=_opt_text(acct_el, "s:Nm"),
        custodian_bic=_opt_text(acct_el, "s:AcctSvcr/s:AnyBIC"),
        base_currency=_opt_text(acct_el, "s:BaseCcy"),
    )

    positions = []
    for i, bal in enumerate(rpt.findall("s:BalForAcct", _NSMAP)):
        ctx = f"BalForAcct[{i}]"
        fin = bal.find("s:FinInstrmId", _NSMAP)
        if fin is None:
            raise FeedParseError(f"semt.002: missing FinInstrmId in {ctx}")

        price_el = bal.find("s:PricDtls/s:Val", _NSMAP)
        price_dt_el = bal.find("s:PricDtls/s:Dt", _NSMAP)
        mv_el = bal.find("s:AcctBaseCcyAmts/s:HldgVal/s:Amt", _NSMAP)

        positions.append(
            Position(
                account_id=account.account_id,
                security=_parse_security(fin),
                security_name=_find_text(fin, "s:Desc", ctx),
                quantity=_parse_decimal(_find_text(bal, "s:AggtBal/s:Unit", ctx), ctx),
                as_of=as_of,
                price=None if price_el is None else _parse_money(price_el, f"{ctx} price"),
                price_as_of=(
                    None
                    if price_dt_el is None or price_dt_el.text is None
                    else _parse_date(price_dt_el.text, f"{ctx} price date")
                ),
                market_value=(
                    None if mv_el is None else _parse_money(mv_el, f"{ctx} holding value")
                ),
                # Not carried by this format subset — see module docstring.
                cost_basis=None,
            )
        )

    return HoldingsStatement(
        statement_id=statement_id,
        account=account,
        as_of=as_of,
        source_format=FeedFormat.SEMT_002,
        positions=tuple(positions),
    )
