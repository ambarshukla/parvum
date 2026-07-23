"""Canonical models for private-fund ("alts") documents: capital calls,
distributions, and capital account statements. Plays the same role as
``parvum_ingest.model`` — the internal shape every later step (rendering,
defect injection, and eventually extraction/validation) is built against,
independent of any one document's rendered layout.

There is deliberately little open data for this asset class — real capital
call notices, distributions, and capital account statements are private,
bilateral documents between a fund and its limited partners. That opacity
is the point (see ``docs/DECISIONS.md`` D-046 and the project brief): these
are synthetic documents in a realistic shape, not scraped or sourced data.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DistributionSource(StrEnum):
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    CAPITAL_GAIN = "CAPITAL_GAIN"
    INCOME = "INCOME"


class FundCommitment(BaseModel):
    """One LP's commitment to one fund — the static facts every document
    for this fund/account pair is generated against. ``account_id`` rolls
    up to an existing custody account from the wealth manager's universe
    (``parvum_reference.accounts``), so alts holdings join the same client
    rollup as everything else, the same way a real LP's fund interests sit
    alongside their brokerage accounts on one statement."""

    model_config = ConfigDict(frozen=True)

    fund_id: str
    fund_name: str
    account_id: str
    currency: str
    vintage_year: int
    total_commitment: Decimal


class CapitalCallNotice(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_id: str
    fund_name: str
    account_id: str
    currency: str
    call_number: int
    call_date: date
    due_date: date
    call_amount: Decimal
    cumulative_called: Decimal
    remaining_commitment: Decimal
    purpose: str | None


class DistributionNotice(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_id: str
    fund_name: str
    account_id: str
    currency: str
    distribution_number: int
    distribution_date: date
    distribution_amount: Decimal
    cumulative_distributed: Decimal
    source: DistributionSource | None
    recallable: bool


class CapitalAccountStatement(BaseModel):
    """A periodic NAV rollforward: ``ending_balance`` should always equal
    ``beginning_balance + contributions - distributions - management_fees
    + realized_gain_loss + unrealized_gain_loss`` — the exact invariant a
    seeded ``ARITHMETIC_ERROR`` defect (see ``defects.py``) breaks, and
    deterministic validation (a later slice) will check."""

    model_config = ConfigDict(frozen=True)

    fund_id: str
    fund_name: str
    account_id: str
    currency: str
    period_end: date
    beginning_balance: Decimal
    contributions: Decimal
    distributions: Decimal
    management_fees: Decimal
    realized_gain_loss: Decimal
    unrealized_gain_loss: Decimal
    ending_balance: Decimal
    total_commitment: Decimal
    unfunded_commitment: Decimal
