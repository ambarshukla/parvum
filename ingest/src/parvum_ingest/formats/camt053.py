"""camt.053 (ISO 20022 Bank-to-Customer Statement) — render & parse.

The cash side of the feed pair: balances (opening/closing) plus the
entries that explain the movement between them. Same D-010 scope rules as
semt.002: real element names and structure for the fields we carry,
simplified nesting, XSD validation deferred.

Mapping notes:
- Balance types use the real ISO codes: OPBD (opening booked) / CLBD
  (closing booked).
- Each entry's transaction type travels in `BkTxCd/Prtry/Cd` — the
  message's slot for a bank's *proprietary* transaction code. Using our
  own vocabulary there is exactly how real banks use it, and mapping
  proprietary codes to a canonical taxonomy is a genuine feed-onboarding
  task (here the map is the identity; real onboarding is rarely so kind).
- `CdtDbtInd` (credit/debit indicator) is rendered from the transaction
  type's cash direction. The parser does NOT cross-check it against the
  type: an inconsistent pair is a lie to detect downstream (D-009), not a
  parse failure.
- Booking date → trade_date, value date → settlement_date.
"""

from xml.etree import ElementTree as ET

from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats._xml import (
    child,
    dec_str,
    find_text,
    opt_text,
    parse_document,
    parse_iso_date,
    parse_money,
    qname,
)
from parvum_ingest.model import (
    Account,
    BalanceType,
    CashBalance,
    CashStatement,
    FeedFormat,
    Transaction,
    TransactionType,
)

FMT = "camt.053"
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
_NSMAP = {"c": NS}

_BALANCE_CODES = {BalanceType.OPENING: "OPBD", BalanceType.CLOSING: "CLBD"}
_BALANCE_TYPES = {v: k for k, v in _BALANCE_CODES.items()}

# Cash direction per transaction type: money leaving the account is a debit.
DEBIT_TYPES = frozenset({TransactionType.BUY, TransactionType.FEE, TransactionType.TRANSFER_OUT})


def render_camt053(stmt: CashStatement) -> str:
    ET.register_namespace("", NS)
    root = ET.Element(qname(NS, "Document"))
    b2c = child(root, NS, "BkToCstmrStmt")

    grp = child(b2c, NS, "GrpHdr")
    child(grp, NS, "MsgId", stmt.statement_id)
    child(grp, NS, "CreDtTm", f"{stmt.as_of.isoformat()}T00:00:00")

    st = child(b2c, NS, "Stmt")
    child(st, NS, "Id", stmt.statement_id)

    acct = child(st, NS, "Acct")
    child(child(child(acct, NS, "Id"), NS, "Othr"), NS, "Id", stmt.account.account_id)
    if stmt.account.base_currency is not None:
        child(acct, NS, "Ccy", stmt.account.base_currency)
    if stmt.account.name is not None:
        child(acct, NS, "Nm", stmt.account.name)
    if stmt.account.custodian_bic is not None:
        svcr = child(child(acct, NS, "Svcr"), NS, "FinInstnId")
        child(svcr, NS, "BICFI", stmt.account.custodian_bic)

    for bal in stmt.balances:
        b = child(st, NS, "Bal")
        cd = child(child(b, NS, "Tp"), NS, "CdOrPrtry")
        child(cd, NS, "Cd", _BALANCE_CODES[bal.balance_type])
        child(b, NS, "Amt", dec_str(bal.balance.amount), Ccy=bal.balance.currency)
        child(b, NS, "CdtDbtInd", "CRDT")
        child(child(b, NS, "Dt"), NS, "Dt", bal.as_of.isoformat())

    for txn in stmt.entries:
        ntry = child(st, NS, "Ntry")
        child(ntry, NS, "NtryRef", txn.transaction_id)
        child(ntry, NS, "Amt", dec_str(txn.amount.amount), Ccy=txn.amount.currency)
        child(ntry, NS, "CdtDbtInd", "DBIT" if txn.type in DEBIT_TYPES else "CRDT")
        child(child(ntry, NS, "Sts"), NS, "Cd", "BOOK")
        child(child(ntry, NS, "BookgDt"), NS, "Dt", txn.trade_date.isoformat())
        child(child(ntry, NS, "ValDt"), NS, "Dt", txn.settlement_date.isoformat())
        child(child(child(ntry, NS, "BkTxCd"), NS, "Prtry"), NS, "Cd", txn.type.value)
        if txn.description:
            child(ntry, NS, "AddtlNtryInf", txn.description)

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# --- parsing --------------------------------------------------------------


def _parse_balance(b: ET.Element, account_id: str, idx: int) -> CashBalance:
    ctx = f"Bal[{idx}]"
    code = find_text(b, _NSMAP, "c:Tp/c:CdOrPrtry/c:Cd", ctx, FMT)
    bal_type = _BALANCE_TYPES.get(code)
    if bal_type is None:
        raise FeedParseError(f"{FMT}: unknown balance code {code!r} in {ctx}")
    amt_el = b.find("c:Amt", _NSMAP)
    if amt_el is None:
        raise FeedParseError(f"{FMT}: missing Amt in {ctx}")
    return CashBalance(
        account_id=account_id,
        balance_type=bal_type,
        balance=parse_money(amt_el, ctx, FMT),
        as_of=parse_iso_date(find_text(b, _NSMAP, "c:Dt/c:Dt", ctx, FMT), ctx, FMT),
    )


def _parse_entry(ntry: ET.Element, account_id: str, idx: int) -> Transaction:
    ctx = f"Ntry[{idx}]"
    type_raw = find_text(ntry, _NSMAP, "c:BkTxCd/c:Prtry/c:Cd", ctx, FMT)
    try:
        txn_type = TransactionType(type_raw)
    except ValueError as exc:
        raise FeedParseError(f"{FMT}: unknown transaction code {type_raw!r} in {ctx}") from exc
    amt_el = ntry.find("c:Amt", _NSMAP)
    if amt_el is None:
        raise FeedParseError(f"{FMT}: missing Amt in {ctx}")
    return Transaction(
        transaction_id=find_text(ntry, _NSMAP, "c:NtryRef", ctx, FMT),
        account_id=account_id,
        type=txn_type,
        trade_date=parse_iso_date(
            find_text(ntry, _NSMAP, "c:BookgDt/c:Dt", ctx, FMT), f"{ctx} booking date", FMT
        ),
        settlement_date=parse_iso_date(
            find_text(ntry, _NSMAP, "c:ValDt/c:Dt", ctx, FMT), f"{ctx} value date", FMT
        ),
        amount=parse_money(amt_el, ctx, FMT),
        description=opt_text(ntry, _NSMAP, "c:AddtlNtryInf") or "",
    )


def parse_camt053(xml_text: str) -> CashStatement:
    root = parse_document(xml_text, NS, FMT)

    st = root.find("c:BkToCstmrStmt/c:Stmt", _NSMAP)
    if st is None:
        raise FeedParseError(f"{FMT}: missing BkToCstmrStmt/Stmt")

    statement_id = find_text(st, _NSMAP, "c:Id", "Stmt", FMT)

    acct_el = st.find("c:Acct", _NSMAP)
    if acct_el is None:
        raise FeedParseError(f"{FMT}: missing Acct")
    account = Account(
        account_id=find_text(acct_el, _NSMAP, "c:Id/c:Othr/c:Id", "Acct", FMT),
        name=opt_text(acct_el, _NSMAP, "c:Nm"),
        custodian_bic=opt_text(acct_el, _NSMAP, "c:Svcr/c:FinInstnId/c:BICFI"),
        base_currency=opt_text(acct_el, _NSMAP, "c:Ccy"),
    )

    balances = tuple(
        _parse_balance(b, account.account_id, i) for i, b in enumerate(st.findall("c:Bal", _NSMAP))
    )
    if not balances:
        raise FeedParseError(f"{FMT}: statement has no balances")

    entries = tuple(
        _parse_entry(n, account.account_id, i) for i, n in enumerate(st.findall("c:Ntry", _NSMAP))
    )

    # Statement date = closing balance date (how camt consumers read it).
    closing = [b for b in balances if b.balance_type is BalanceType.CLOSING]
    as_of = closing[0].as_of if closing else balances[-1].as_of

    return CashStatement(
        statement_id=statement_id,
        account=account,
        as_of=as_of,
        source_format=FeedFormat.CAMT_053,
        balances=balances,
        entries=entries,
    )
