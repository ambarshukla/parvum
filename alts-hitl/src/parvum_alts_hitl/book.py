"""A small, deterministic synthetic fund waterfall: capital calls,
distributions, and capital account statements that all reconcile with each
other by construction — the same "build the clean book first, corrupt it
later" discipline as ``parvum_ingest.book``.

Not a real PE/VC cashflow model (no J-curve calibration against real
vintage benchmarks) — just internally consistent enough that deterministic
validation (a later slice) has genuine arithmetic to check, and an LLM
extraction step has genuine numbers to get right.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from parvum_alts_hitl.model import (
    CapitalAccountStatement,
    CapitalCallNotice,
    DistributionNotice,
    DistributionSource,
    FundCommitment,
)

_CENTS = Decimal("0.01")

# Fraction of total commitment called at each of four calls (sums to 0.60 —
# a realistic partial-deployment stage for a fund still in its investment
# period), spaced unevenly in quarters-since-vintage-start so the schedule
# doesn't look mechanically regular.
_CALL_QUARTERS = (1, 2, 4, 6)
_CALL_FRACTIONS = (Decimal("0.15"), Decimal("0.20"), Decimal("0.15"), Decimal("0.10"))
_CALL_PURPOSES = (
    "New platform acquisition",
    "Follow-on investment in existing portfolio companies",
    "Bridge financing for a portfolio company",
    "Fund operating expenses and management fee",
)

# Distributions land after calls 3 and 4, sized off cumulative called
# capital — a return of capital first, then a capital gain once the fund
# has had time to realize something.
_DISTRIBUTION_QUARTERS = (7, 9)
_DISTRIBUTION_FRACTIONS = (Decimal("0.05"), Decimal("0.08"))
_DISTRIBUTION_SOURCES = (DistributionSource.RETURN_OF_CAPITAL, DistributionSource.CAPITAL_GAIN)

_ANNUAL_MGMT_FEE_RATE = Decimal("0.02")
_STATEMENT_QUARTERS = range(1, 11)  # ten quarters of history

# A fixed unrealized-gain-as-percent-of-NAV walk, applied each quarter to
# whatever's in the account after that quarter's cash flows. Fixed rather
# than random so the book never depends on an RNG the defect-injection path
# could disagree with — the "randomness" in this generator lives entirely
# in *whether* a defect is picked (generate.py), never in the clean book.
_UNREALIZED_PCT_WALK = (
    Decimal("0"),
    Decimal("0"),
    Decimal("1.5"),
    Decimal("2.0"),
    Decimal("1.0"),
    Decimal("3.5"),
    Decimal("-1.0"),
    Decimal("4.0"),
    Decimal("2.5"),
    Decimal("5.0"),
)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quarter_end(year: int, quarter: int) -> date:
    month = quarter * 3
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _quarter_date(vintage_year: int, quarter_index: int) -> date:
    """``quarter_index=1`` is Q1 of ``vintage_year``, ``quarter_index=5`` is
    Q1 of ``vintage_year + 1``, and so on — lets the call/distribution/
    statement schedules be defined as a flat sequence of quarter offsets
    regardless of whether they cross a calendar year boundary."""
    year = vintage_year + (quarter_index - 1) // 4
    quarter = (quarter_index - 1) % 4 + 1
    return _quarter_end(year, quarter)


@dataclass(frozen=True)
class FundBook:
    commitment: FundCommitment
    calls: tuple[CapitalCallNotice, ...]
    distributions: tuple[DistributionNotice, ...]
    statements: tuple[CapitalAccountStatement, ...]


def build_fund_book(commitment: FundCommitment) -> FundBook:
    calls: list[CapitalCallNotice] = []
    cumulative_called = Decimal(0)
    call_amount_by_quarter: dict[int, Decimal] = {}
    for i, (quarter_index, fraction) in enumerate(
        zip(_CALL_QUARTERS, _CALL_FRACTIONS, strict=True), start=1
    ):
        call_amount = _money(commitment.total_commitment * fraction)
        cumulative_called += call_amount
        call_date = _quarter_date(commitment.vintage_year, quarter_index)
        calls.append(
            CapitalCallNotice(
                fund_id=commitment.fund_id,
                fund_name=commitment.fund_name,
                account_id=commitment.account_id,
                call_number=i,
                call_date=call_date,
                due_date=call_date + timedelta(days=14),
                call_amount=call_amount,
                cumulative_called=cumulative_called,
                remaining_commitment=_money(commitment.total_commitment - cumulative_called),
                purpose=_CALL_PURPOSES[(i - 1) % len(_CALL_PURPOSES)],
            )
        )
        call_amount_by_quarter[quarter_index] = call_amount

    distributions: list[DistributionNotice] = []
    cumulative_distributed = Decimal(0)
    distribution_amount_by_quarter: dict[int, Decimal] = {}
    distribution_source_by_quarter: dict[int, DistributionSource] = {}
    for i, (quarter_index, fraction, source) in enumerate(
        zip(_DISTRIBUTION_QUARTERS, _DISTRIBUTION_FRACTIONS, _DISTRIBUTION_SOURCES, strict=True),
        start=1,
    ):
        distribution_amount = _money(cumulative_called * fraction)
        cumulative_distributed += distribution_amount
        distribution_date = _quarter_date(commitment.vintage_year, quarter_index)
        distributions.append(
            DistributionNotice(
                fund_id=commitment.fund_id,
                fund_name=commitment.fund_name,
                account_id=commitment.account_id,
                distribution_number=i,
                distribution_date=distribution_date,
                distribution_amount=distribution_amount,
                cumulative_distributed=cumulative_distributed,
                source=source,
                recallable=(source is DistributionSource.RETURN_OF_CAPITAL),
            )
        )
        distribution_amount_by_quarter[quarter_index] = distribution_amount
        distribution_source_by_quarter[quarter_index] = source

    statements: list[CapitalAccountStatement] = []
    balance = Decimal(0)
    called_so_far = Decimal(0)
    quarterly_fee = _money(commitment.total_commitment * _ANNUAL_MGMT_FEE_RATE / 4)

    for quarter_index in _STATEMENT_QUARTERS:
        period_end = _quarter_date(commitment.vintage_year, quarter_index)
        contributions = call_amount_by_quarter.get(quarter_index, Decimal(0))
        called_so_far += contributions
        distributed = distribution_amount_by_quarter.get(quarter_index, Decimal(0))
        realized = (
            distributed
            if distribution_source_by_quarter.get(quarter_index) is DistributionSource.CAPITAL_GAIN
            else Decimal(0)
        )
        # No fee before the fund has called any capital — nothing to charge
        # a management fee against yet.
        fee = quarterly_fee if called_so_far > 0 else Decimal(0)
        unrealized_pct = _UNREALIZED_PCT_WALK[quarter_index - 1] / Decimal(100)
        unrealized = _money((balance + contributions - distributed - fee) * unrealized_pct)

        beginning = balance
        ending = _money(beginning + contributions - distributed - fee + realized + unrealized)

        statements.append(
            CapitalAccountStatement(
                fund_id=commitment.fund_id,
                fund_name=commitment.fund_name,
                account_id=commitment.account_id,
                period_end=period_end,
                beginning_balance=beginning,
                contributions=contributions,
                distributions=distributed,
                management_fees=fee,
                realized_gain_loss=realized,
                unrealized_gain_loss=unrealized,
                ending_balance=ending,
                total_commitment=commitment.total_commitment,
                unfunded_commitment=_money(commitment.total_commitment - called_so_far),
            )
        )
        balance = ending

    return FundBook(
        commitment=commitment,
        calls=tuple(calls),
        distributions=tuple(distributions),
        statements=tuple(statements),
    )
