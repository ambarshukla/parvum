"""Declared restatements of the synthetic book — value changes that are not returns.

Every account here is a scale model of a real 13F filer's portfolio: the
filer's share counts divided by that account's `share_divisor` (see
`accounts.py`). The divisor is a modelling parameter, not a market fact, and
when it changes the account's reported wealth changes with it — same holdings,
same prices, a different ruler.

A performance chain cannot tell that apart from a market move on its own. It
sees yesterday's wealth, today's wealth, and no cash flow between them, and
concludes the manager earned the difference. On 2026-08-17 that produced a
single daily time-weighted return of **+414%** on a book that had not earned a
cent (D-066 recalibrated both Berkshire divisors so a new 3,564-share position
would not round to zero). The number was arithmetically correct and completely
false.

So a restatement is *declared*, not inferred. Inferring it — "any suspiciously
large move must be a restatement" — would also swallow the legitimate quarterly
step every 13F filing regime produces, which is a real return arriving all at
once rather than a fake one. The two look identical on a chart and mean
opposite things; only the book knows which is which, so the book says so here.

Declaration alone would be a licence to explain away any inconvenient number,
which is why it is only half the control. `dq_return_plausibility` (built in
`spark/gold_reports.py`) independently flags any zero-flow day that moves more
than the stated band **without** a declaration on file, so a divisor changed
and never recorded here shows up as an exception instead of as performance.

`test_restatements.py` closes the third side: the divisors this module claims
each account ended up with must equal the divisors `accounts.py` actually
carries today. Changing a divisor without recording it here fails the suite.
"""

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from parvum_reference.accounts import UNIVERSE


class BookRestatement(NamedTuple):
    """One account's book, restated on one date.

    `divisor_before`/`divisor_after` are the audit trail: they say what the
    ruler was and what it became, so the size of the step is explainable from
    the register rather than only from the wealth series it produced.
    """

    effective_date: date
    account_id: str
    divisor_before: Decimal
    divisor_after: Decimal
    reason: str
    decision_ref: str


RESTATEMENTS: tuple[BookRestatement, ...] = (
    BookRestatement(
        effective_date=date(2026, 8, 17),
        account_id="60011234",
        divisor_before=Decimal(10_000),
        divisor_after=Decimal(2_000),
        reason=(
            "Berkshire share divisor recalibrated 10,000 to 2,000 so the 2026-Q2 13F's "
            "3,564-share D.R. Horton position would not scale to zero. Same holdings, "
            "five times the scale — a change of unit, not an investment result."
        ),
        decision_ref="D-066",
    ),
    BookRestatement(
        effective_date=date(2026, 8, 17),
        account_id="60018852",
        divisor_before=Decimal(20_000),
        divisor_after=Decimal(4_000),
        reason=(
            "Berkshire share divisor recalibrated 20,000 to 4,000 alongside account "
            "60011234, preserving the 1:2 ratio between the two Berkshire accounts. "
            "Same holdings, five times the scale — a change of unit, not a result."
        ),
        decision_ref="D-066",
    ),
)


def declared_divisors() -> dict[str, Decimal]:
    """The divisor each restated account should carry today, per this register.

    The last declaration wins, so an account restated more than once resolves
    to its most recent `divisor_after`.
    """
    resolved: dict[str, Decimal] = {}
    for entry in sorted(RESTATEMENTS, key=lambda r: r.effective_date):
        resolved[entry.account_id] = entry.divisor_after
    return resolved


def undeclared_divisor_changes() -> dict[str, tuple[Decimal, Decimal]]:
    """Accounts whose live divisor disagrees with the register: {id: (declared, live)}.

    Empty is the healthy state. A non-empty result means someone changed a
    divisor in `accounts.py` and did not record the restatement, which would
    let the change reach the performance chain disguised as a market return.
    """
    live = {account.account_id: account.share_divisor for account in UNIVERSE}
    declared = declared_divisors()
    return {
        account_id: (divisor, live[account_id])
        for account_id, divisor in declared.items()
        if account_id in live and live[account_id] != divisor
    }
