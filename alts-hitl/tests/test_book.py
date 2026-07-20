"""The clean fund book: deterministic, and internally consistent by
construction — every statement's ending balance must equal its own
beginning balance plus that period's flows."""

from decimal import Decimal

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.model import DistributionSource, FundCommitment

COMMITMENT = FundCommitment(
    fund_id="FUND-TEST01",
    fund_name="Test Capital Partners I",
    account_id="TEST-ACC",
    currency="USD",
    vintage_year=2024,
    total_commitment=Decimal("1000000.00"),
)


def test_deterministic() -> None:
    assert build_fund_book(COMMITMENT) == build_fund_book(COMMITMENT)


def test_call_amounts_sum_to_the_expected_fraction_of_commitment() -> None:
    book = build_fund_book(COMMITMENT)
    assert sum((c.call_amount for c in book.calls), Decimal(0)) == Decimal("600000.00")
    assert book.calls[-1].remaining_commitment == Decimal("400000.00")


def test_call_numbers_and_cumulative_called_are_sequential() -> None:
    book = build_fund_book(COMMITMENT)
    assert [c.call_number for c in book.calls] == [1, 2, 3, 4]
    running = Decimal(0)
    for call in book.calls:
        running += call.call_amount
        assert call.cumulative_called == running


def test_every_statement_reconciles() -> None:
    book = build_fund_book(COMMITMENT)
    for statement in book.statements:
        expected = (
            statement.beginning_balance
            + statement.contributions
            - statement.distributions
            - statement.management_fees
            + statement.realized_gain_loss
            + statement.unrealized_gain_loss
        )
        assert statement.ending_balance == expected


def test_statements_chain_ending_balance_into_next_beginning_balance() -> None:
    book = build_fund_book(COMMITMENT)
    for prior, current in zip(book.statements, book.statements[1:], strict=False):
        assert current.beginning_balance == prior.ending_balance


def test_unfunded_commitment_tracks_cumulative_calls() -> None:
    book = build_fund_book(COMMITMENT)
    # The first call lands in the same quarter as the first statement, so
    # unfunded commitment is already down by that call's amount.
    assert book.statements[0].unfunded_commitment == (
        COMMITMENT.total_commitment - book.calls[0].call_amount
    )
    # By the last statement, all four calls have landed.
    assert book.statements[-1].unfunded_commitment == Decimal("400000.00")


def test_distribution_sources_are_return_of_capital_then_capital_gain() -> None:
    book = build_fund_book(COMMITMENT)
    assert [d.source for d in book.distributions] == [
        DistributionSource.RETURN_OF_CAPITAL,
        DistributionSource.CAPITAL_GAIN,
    ]
    assert book.distributions[0].recallable is True
    assert book.distributions[1].recallable is False
