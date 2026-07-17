"""Deterministic seed book: the 'truth' the feed generator renders.

The portfolio's *shape* is real. Positions, relative weights and prices come
from a committed SEC 13F extract (D-014) — Berkshire Hathaway's actual
disclosed holdings — rather than from names someone picked. Its *scale* is
honest fiction: share counts are divided by a constant so the book reads like
a private client's account rather than a $263bn institution's.

Deterministic on purpose: the same `as_of` always yields an identical
statement, so renderers, parsers and defect injection all have a stable
fixture, and any historical day regenerates byte-identically (D-011). Defect
injection corrupts *copies* of this book; the seed itself stays pristine.

What 13F does not carry, and how it's filled:

- **Prices** aren't reported, but `value / shares` recovers the real
  quarter-end price — which is where these come from. Static thereafter: this
  book exists to exercise formats and reconciliation, not to be current.
- **Cost basis** isn't reported at all. Synthesized deterministically from
  each security's own identifier, and left absent for roughly a fifth of
  positions, because sparse optional data is normal rather than only a defect.

Note that duplicate `security_name`s are deliberate and real: Alphabet is held
in two share classes, one issuer name across two distinct ISINs. Anything
downstream that keys on name rather than identifier deserves to break here
rather than in production.
"""

import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from importlib import resources
from random import Random
from typing import NamedTuple

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

# Berkshire's book is institutional: 227.9m Apple shares. Dividing by a
# constant preserves the relative weights — the thing that makes the book look
# real — while yielding a plausible private-client account of roughly $26m.
#
# The divisor applies to *shares*, uniformly. Scaling by value instead would
# look more principled and be wrong: NVR trades near $6,590, so its 11,112
# shares are $73m of the book yet round to nothing on any value-based scale
# that keeps Apple's 227.9m shares sensible.
_SHARE_DIVISOR = Decimal(10_000)

# Cost basis is absent for about a fifth of positions, and where present sits
# between roughly half and a little above market — a book of holdings bought
# at various times, mostly up.
_COST_BASIS_MISSING_RATE = 0.2
_COST_BASIS_MIN_FACTOR = Decimal("0.55")
_COST_BASIS_MAX_FACTOR = Decimal("1.15")


@lru_cache(maxsize=1)
def _seed_document() -> dict:
    """The committed 13F extract.

    Loaded lazily and cached, deliberately: `parvum_ingest/__init__` imports
    this module, and the Databricks bronze job imports the package purely for
    its parsers. Reading a data file at import time would make an unrelated
    job fail if that file were ever missing.
    """
    path = resources.files("parvum_ingest").joinpath("seed", "holdings_13f.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _cost_basis(cusip: str, market_value: Decimal) -> Money | None:
    """A deterministic, plausible cost basis — 13F reports none.

    Seeded from the security's own identifier via sha256 rather than
    `hash()`, which Python salts per process: a book that differed between
    runs would break byte-identical regeneration (D-011) in a way that only
    showed up on someone else's machine.
    """
    rng = Random(int.from_bytes(hashlib.sha256(cusip.encode()).digest()[:8], "big"))
    if rng.random() < _COST_BASIS_MISSING_RATE:
        return None
    spread = _COST_BASIS_MAX_FACTOR - _COST_BASIS_MIN_FACTOR
    factor = _COST_BASIS_MIN_FACTOR + spread * Decimal(str(rng.random()))
    return Money(amount=(market_value * factor).quantize(Decimal("0.01")), currency="USD")


class _SeedPosition(NamedTuple):
    isin: str
    name: str
    quantity: Decimal
    price: Money
    market_value: Money
    cost_basis: Money | None


@lru_cache(maxsize=1)
def _seed_positions() -> tuple[_SeedPosition, ...]:
    positions = []
    for holding in _seed_document()["holdings"]:
        shares = Decimal(holding["shares"])
        value = Decimal(holding["value_usd"])

        price = (value / shares).quantize(Decimal("0.01"))
        quantity = (shares / _SHARE_DIVISOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if quantity <= 0:
            # Refuse rather than silently drop: a zero-share position means the
            # divisor no longer suits the filer, which is a decision to make
            # consciously, not a hole to discover in the data later.
            raise ValueError(
                f"{holding['issuer']} ({holding['shares']} shares) scales to zero at a "
                f"divisor of {_SHARE_DIVISOR} — choose a divisor that fits this seed"
            )

        market_value = (quantity * price).quantize(Decimal("0.01"))
        positions.append(
            _SeedPosition(
                isin=holding["isin"],
                name=holding["issuer"],
                quantity=quantity,
                price=Money(amount=price, currency="USD"),
                market_value=Money(amount=market_value, currency="USD"),
                cost_basis=_cost_basis(holding["cusip"], market_value),
            )
        )
    return tuple(positions)


def build_book(as_of: date) -> HoldingsStatement:
    """Build the clean seed holdings statement as of a given date."""
    positions = tuple(
        Position(
            account_id=_ACCOUNT.account_id,
            security=SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=seed.isin),
            security_name=seed.name,
            quantity=seed.quantity,
            as_of=as_of,
            price=seed.price,
            price_as_of=as_of,
            market_value=seed.market_value,
            cost_basis=seed.cost_basis,
        )
        for seed in _seed_positions()
    )
    return HoldingsStatement(
        statement_id=f"STMT-{as_of.isoformat()}-{_ACCOUNT.account_id}",
        account=_ACCOUNT,
        as_of=as_of,
        source_format=FeedFormat.SEMT_002,
        positions=positions,
    )


# (type, amount, days_before_as_of for booking, settle_lag_days, description)
# Securities named here are ones the book actually holds, at quantities and
# prices consistent with it — a cash statement referencing a position the
# account doesn't own is the kind of detail that quietly undermines the whole
# fixture.
_SEED_CASH: tuple[tuple[TransactionType, str, int, int, str], ...] = (
    (TransactionType.DIVIDEND, "484.00", 2, 0, "Dividend Apple Inc"),
    (TransactionType.INTEREST, "112.35", 2, 0, "Credit interest June"),
    (TransactionType.BUY, "30420.00", 4, 2, "Purchase 400 Coca Cola Co"),
    (TransactionType.SELL, "9103.60", 3, 2, "Sale 44 Chevron Corporation"),
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
