"""The custodian-side account universe: what the feed sender knows.

A custodian services *accounts* — it has no concept of the wealth manager's
clients, households, or legal entities. That is why this registry carries
only what a custodian would print on a statement: an opaque account number,
a mandate-style name, the servicing BIC, and a base currency. The
client → legal entity → account mapping is the wealth manager's own
reference data and arrives in Phase 2, where accounts get joined to owners
the feeds never mention.

Account numbers are deliberately opaque (custodians issue identifiers, not
descriptions). The mapping from number to anything meaningful is exactly the
kind of knowledge that lives in reference data — losing it is why real feed
onboarding starts with "what is account FQ5521 again?".

Each account's book is seeded from a different real 13F filer and scale, so
the five books are genuinely distinct portfolios with different
concentration profiles — not five copies of one book. Divisors are
calibrated per filer so no position scales to zero (`_seed_position`
refuses); the smallest real positions are the binding constraint (e.g.
Berkshire's 11,112 NVR shares cap its divisor at ~22k).
"""

from decimal import Decimal
from typing import NamedTuple

BERKSHIRE_CIK = 1067983
GATES_TRUST_CIK = 1166559
PERSHING_SQUARE_CIK = 1336528

CUSTODIAN_BIC = "CUSTGB2LXXX"


class AccountSpec(NamedTuple):
    """One custody account as the custodian knows it, plus generation config.

    The first four fields are statement content; `cik`, `share_divisor` and
    `cash_scale` are generator configuration (which real filer's book seeds
    the account, and at what scale).
    """

    account_id: str
    name: str
    base_currency: str
    cik: int
    share_divisor: Decimal
    cash_scale: Decimal


UNIVERSE: tuple[AccountSpec, ...] = (
    AccountSpec("60011234", "Growth Portfolio", "USD", BERKSHIRE_CIK, Decimal(10_000), Decimal(1)),
    AccountSpec(
        "FQ5521", "Income Reserve", "EUR", GATES_TRUST_CIK, Decimal(20_000), Decimal("2.5")
    ),
    AccountSpec(
        "X4478210",
        "Concentrated Equity SMA",
        "USD",
        PERSHING_SQUARE_CIK,
        Decimal(5_000),
        Decimal("1.5"),
    ),
    AccountSpec("60018852", "Retirement", "USD", BERKSHIRE_CIK, Decimal(20_000), Decimal("0.5")),
    AccountSpec("FQ9007", "Foundation Legacy", "USD", GATES_TRUST_CIK, Decimal(10_000), Decimal(1)),
)

# The default account keeps single-account call sites (fixtures, format
# round-trip tests) meaningful without repeating universe plumbing.
DEFAULT_ACCOUNT = UNIVERSE[0]
