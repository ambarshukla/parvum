"""Deterministic seed book: the 'truth' the feed generator renders.

One small portfolio of real, liquid securities (ISINs verified by their
check digits in tests). Deterministic on purpose: the same (as_of) input
always yields an identical statement, so renderers and parsers can be
round-trip tested against a stable fixture. Defect injection (a later PR)
will take this clean book and corrupt copies of it — the seed itself stays
pristine.

Prices are plausible constants, not market data: this book exists to
exercise formats and reconciliation, not to be current.
"""

from datetime import date, timedelta
from decimal import Decimal

from parvum_ingest.model import (
    Account,
    BalanceType,
    CashBalance,
    CashStatement,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Money,
    Position,
    SecurityIdentifier,
    Transaction,
    TransactionType,
)

_ACCOUNT = Account(
    account_id="ACC-GROWTH-001",
    name="Growth Portfolio",
    custodian_bic="CUSTGB2LXXX",
    base_currency="USD",
)

# (isin, name, quantity, price, price_ccy, cost_basis or None)
# Cost basis deliberately absent for two names even in the *clean* book:
# sparse optional data is normal, not only a defect condition.
_SEED_HOLDINGS: tuple[tuple[str, str, str, str, str, str | None], ...] = (
    ("US0378331005", "Apple Inc", "220", "185.40", "USD", "31570.00"),
    ("US5949181045", "Microsoft Corp", "150", "402.10", "USD", "48910.00"),
    ("US0231351067", "Amazon.com Inc", "180", "178.25", "USD", "27300.00"),
    ("US02079K3059", "Alphabet Inc Class A", "160", "156.80", "USD", "21120.00"),
    ("US46625H1005", "JPMorgan Chase & Co", "130", "198.55", "USD", "22750.00"),
    ("US4781601046", "Johnson & Johnson", "140", "147.30", "USD", "19460.00"),
    ("US30231G1022", "Exxon Mobil Corp", "170", "112.90", "USD", None),
    ("GB00BH4HKS39", "Vodafone Group Plc", "5200", "0.92", "USD", "5100.00"),
    ("CH0038863350", "Nestle SA", "90", "104.75", "USD", None),
    ("DE0007164600", "SAP SE", "75", "191.60", "USD", "12980.00"),
)


def build_book(as_of: date) -> HoldingsStatement:
    """Build the clean seed holdings statement as of a given date."""
    positions = []
    for isin, name, qty, price, ccy, cost in _SEED_HOLDINGS:
        quantity = Decimal(qty)
        price_money = Money(amount=Decimal(price), currency=ccy)
        positions.append(
            Position(
                account_id=_ACCOUNT.account_id,
                security=SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=isin),
                security_name=name,
                quantity=quantity,
                as_of=as_of,
                price=price_money,
                price_as_of=as_of,
                market_value=Money(
                    amount=(quantity * price_money.amount).quantize(Decimal("0.01")),
                    currency=ccy,
                ),
                cost_basis=None if cost is None else Money(amount=Decimal(cost), currency=ccy),
            )
        )
    return HoldingsStatement(
        statement_id=f"STMT-{as_of.isoformat()}-{_ACCOUNT.account_id}",
        account=_ACCOUNT,
        as_of=as_of,
        source_format=FeedFormat.SEMT_002,
        positions=tuple(positions),
    )


# (type, amount, days_before_as_of for booking, settle_lag_days, description)
_SEED_CASH: tuple[tuple[TransactionType, str, int, int, str], ...] = (
    (TransactionType.DIVIDEND, "484.00", 2, 0, "Dividend Apple Inc"),
    (TransactionType.INTEREST, "112.35", 2, 0, "Credit interest June"),
    (TransactionType.BUY, "30157.50", 4, 2, "Purchase 75 Microsoft Corp"),
    (TransactionType.SELL, "9051.30", 3, 2, "Sale 80 Exxon Mobil Corp"),
    (TransactionType.FEE, "45.00", 1, 0, "Custody fee Q2"),
    (TransactionType.TRANSFER_IN, "25000.00", 1, 0, "Client cash contribution"),
)

_OPENING_BALANCE = Decimal("50000.00")

# Money leaving the account. Mirrored in camt053.DEBIT_TYPES; kept here too so
# the book stays format-independent.
_DEBITS = frozenset({TransactionType.BUY, TransactionType.FEE, TransactionType.TRANSFER_OUT})


def build_cash_statement(as_of: date) -> CashStatement:
    """Build the clean seed cash statement as of a given date.

    Invariant of the clean book: closing = opening + net of entries. That
    arithmetic truth is what reconciliation will check — and what defect
    injection will deliberately break.
    """
    ccy = _ACCOUNT.base_currency or "USD"
    entries = []
    net = Decimal("0")
    for i, (txn_type, amount, days_ago, settle_lag, desc) in enumerate(_SEED_CASH, start=1):
        amt = Decimal(amount)
        booked = as_of - timedelta(days=days_ago)
        entries.append(
            Transaction(
                transaction_id=f"TXN-{as_of.isoformat()}-{i:04d}",
                account_id=_ACCOUNT.account_id,
                type=txn_type,
                trade_date=booked,
                settlement_date=booked + timedelta(days=settle_lag),
                amount=Money(amount=amt, currency=ccy),
                description=desc,
            )
        )
        net += -amt if txn_type in _DEBITS else amt

    period_start = as_of - timedelta(days=7)
    balances = (
        CashBalance(
            account_id=_ACCOUNT.account_id,
            balance_type=BalanceType.OPENING,
            balance=Money(amount=_OPENING_BALANCE, currency=ccy),
            as_of=period_start,
        ),
        CashBalance(
            account_id=_ACCOUNT.account_id,
            balance_type=BalanceType.CLOSING,
            balance=Money(amount=_OPENING_BALANCE + net, currency=ccy),
            as_of=as_of,
        ),
    )

    return CashStatement(
        statement_id=f"CASH-{as_of.isoformat()}-{_ACCOUNT.account_id}",
        account=_ACCOUNT,
        as_of=as_of,
        source_format=FeedFormat.CAMT_053,
        balances=balances,
        entries=tuple(entries),
    )
