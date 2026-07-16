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

from xml.etree import ElementTree as ET

from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats._xml import (
    child,
    dec_str,
    find_text,
    opt_text,
    parse_decimal,
    parse_document,
    parse_iso_date,
    parse_money,
    qname,
)
from parvum_ingest.model import (
    Account,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Position,
    SecurityIdentifier,
)

FMT = "semt.002"
NS = "urn:iso:std:iso:20022:tech:xsd:semt.002.001.11"
_NSMAP = {"s": NS}


def render_semt002(stmt: HoldingsStatement) -> str:
    # Serialize with a default namespace (<Document xmlns=...>), matching how
    # real ISO 20022 messages are written, rather than ElementTree's ns0: prefixes.
    ET.register_namespace("", NS)
    root = ET.Element(qname(NS, "Document"))
    rpt = child(root, NS, "SctiesBalCtdyRpt")

    gnl = child(rpt, NS, "StmtGnlDtls")
    child(gnl, NS, "StmtId", stmt.statement_id)
    child(child(gnl, NS, "StmtDtTm"), NS, "Dt", stmt.as_of.isoformat())

    acct = child(rpt, NS, "SfkpgAcct")
    child(acct, NS, "Id", stmt.account.account_id)
    if stmt.account.name is not None:
        child(acct, NS, "Nm", stmt.account.name)
    if stmt.account.custodian_bic is not None:
        child(child(acct, NS, "AcctSvcr"), NS, "AnyBIC", stmt.account.custodian_bic)
    if stmt.account.base_currency is not None:
        child(acct, NS, "BaseCcy", stmt.account.base_currency)

    for pos in stmt.positions:
        bal = child(rpt, NS, "BalForAcct")
        fin = child(bal, NS, "FinInstrmId")
        if pos.security.scheme is IdentifierScheme.ISIN:
            child(fin, NS, "ISIN", pos.security.value)
        else:
            othr = child(fin, NS, "OthrId")
            child(othr, NS, "Id", pos.security.value)
            child(othr, NS, "Tp", pos.security.scheme.value)
        child(fin, NS, "Desc", pos.security_name)

        child(child(bal, NS, "AggtBal"), NS, "Unit", dec_str(pos.quantity))

        if pos.price is not None:
            pric = child(bal, NS, "PricDtls")
            child(pric, NS, "Val", dec_str(pos.price.amount), Ccy=pos.price.currency)
            if pos.price_as_of is not None:
                child(pric, NS, "Dt", pos.price_as_of.isoformat())

        if pos.market_value is not None:
            hldg = child(child(bal, NS, "AcctBaseCcyAmts"), NS, "HldgVal")
            child(hldg, NS, "Amt", dec_str(pos.market_value.amount), Ccy=pos.market_value.currency)

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# --- parsing --------------------------------------------------------------


def _parse_security(fin: ET.Element) -> SecurityIdentifier:
    isin = fin.find("s:ISIN", _NSMAP)
    if isin is not None and isin.text:
        return SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=isin.text)
    scheme_raw = find_text(fin, _NSMAP, "s:OthrId/s:Tp", "FinInstrmId/OthrId", FMT)
    try:
        scheme = IdentifierScheme(scheme_raw)
    except ValueError as exc:
        raise FeedParseError(f"{FMT}: unknown identifier scheme {scheme_raw!r}") from exc
    return SecurityIdentifier(
        scheme=scheme, value=find_text(fin, _NSMAP, "s:OthrId/s:Id", "OthrId", FMT)
    )


def parse_semt002(xml_text: str) -> HoldingsStatement:
    root = parse_document(xml_text, NS, FMT)

    rpt = root.find("s:SctiesBalCtdyRpt", _NSMAP)
    if rpt is None:
        raise FeedParseError(f"{FMT}: missing SctiesBalCtdyRpt")

    statement_id = find_text(rpt, _NSMAP, "s:StmtGnlDtls/s:StmtId", "StmtGnlDtls", FMT)
    as_of = parse_iso_date(
        find_text(rpt, _NSMAP, "s:StmtGnlDtls/s:StmtDtTm/s:Dt", "StmtGnlDtls", FMT),
        "StmtDtTm",
        FMT,
    )

    acct_el = rpt.find("s:SfkpgAcct", _NSMAP)
    if acct_el is None:
        raise FeedParseError(f"{FMT}: missing SfkpgAcct")
    account = Account(
        account_id=find_text(acct_el, _NSMAP, "s:Id", "SfkpgAcct", FMT),
        name=opt_text(acct_el, _NSMAP, "s:Nm"),
        custodian_bic=opt_text(acct_el, _NSMAP, "s:AcctSvcr/s:AnyBIC"),
        base_currency=opt_text(acct_el, _NSMAP, "s:BaseCcy"),
    )

    positions = []
    for i, bal in enumerate(rpt.findall("s:BalForAcct", _NSMAP)):
        ctx = f"BalForAcct[{i}]"
        fin = bal.find("s:FinInstrmId", _NSMAP)
        if fin is None:
            raise FeedParseError(f"{FMT}: missing FinInstrmId in {ctx}")

        price_el = bal.find("s:PricDtls/s:Val", _NSMAP)
        price_dt = opt_text(bal, _NSMAP, "s:PricDtls/s:Dt")
        mv_el = bal.find("s:AcctBaseCcyAmts/s:HldgVal/s:Amt", _NSMAP)

        positions.append(
            Position(
                account_id=account.account_id,
                security=_parse_security(fin),
                security_name=find_text(fin, _NSMAP, "s:Desc", ctx, FMT),
                quantity=parse_decimal(
                    find_text(bal, _NSMAP, "s:AggtBal/s:Unit", ctx, FMT), ctx, FMT
                ),
                as_of=as_of,
                price=None if price_el is None else parse_money(price_el, f"{ctx} price", FMT),
                price_as_of=(
                    None if price_dt is None else parse_iso_date(price_dt, f"{ctx} price date", FMT)
                ),
                market_value=(
                    None if mv_el is None else parse_money(mv_el, f"{ctx} holding value", FMT)
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
