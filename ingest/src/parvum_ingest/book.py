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

from datetime import date
from decimal import Decimal

from parvum_ingest.model import (
    Account,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Money,
    Position,
    SecurityIdentifier,
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
