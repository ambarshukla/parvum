"""Defect injection: deterministic, manifest-recorded, and the original
document is left untouched (defects apply to a copy)."""

from decimal import Decimal

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.defects import (
    DefectConfig,
    DefectType,
    inject_call,
    inject_distribution,
    inject_statement,
)
from parvum_alts_hitl.model import FundCommitment

COMMITMENT = FundCommitment(
    fund_id="FUND-TEST01",
    fund_name="Test Capital Partners I",
    account_id="TEST-ACC",
    currency="USD",
    vintage_year=2024,
    total_commitment=Decimal("1000000.00"),
)

ALL_CALL_DEFECTS = DefectConfig(
    seed=42,
    defects=(
        DefectType.MISSING_FIELD,
        DefectType.COMMITMENT_MISMATCH,
        DefectType.AMOUNT_TRANSPOSITION,
    ),
)
ALL_DISTRIBUTION_DEFECTS = DefectConfig(
    seed=42, defects=(DefectType.MISSING_FIELD, DefectType.AMOUNT_TRANSPOSITION)
)
ALL_STATEMENT_DEFECTS = DefectConfig(seed=42, defects=(DefectType.ARITHMETIC_ERROR,))


def _book():
    return build_fund_book(COMMITMENT)


def test_same_input_same_corruption() -> None:
    call = _book().calls[0]
    assert inject_call(call, ALL_CALL_DEFECTS) == inject_call(call, ALL_CALL_DEFECTS)


def test_original_document_is_untouched() -> None:
    call = _book().calls[0]
    inject_call(call, ALL_CALL_DEFECTS)
    assert call == _book().calls[0]


def test_every_injection_is_recorded_with_a_real_target() -> None:
    call = _book().calls[0]
    _, manifest = inject_call(call, ALL_CALL_DEFECTS)
    assert [r.defect for r in manifest] == list(ALL_CALL_DEFECTS.defects)
    assert all(r.target_id == f"{call.fund_id}/call-{call.call_number}" for r in manifest)


def test_missing_field_nulls_the_purpose() -> None:
    call = _book().calls[0]
    assert call.purpose is not None
    corrupted, _ = inject_call(call, DefectConfig(seed=1, defects=(DefectType.MISSING_FIELD,)))
    assert corrupted.purpose is None


def test_commitment_mismatch_breaks_the_running_total() -> None:
    call = _book().calls[0]
    corrupted, _ = inject_call(
        call, DefectConfig(seed=1, defects=(DefectType.COMMITMENT_MISMATCH,))
    )
    assert corrupted.cumulative_called != call.call_amount


def test_amount_transposition_changes_the_call_amount() -> None:
    call = _book().calls[0]
    corrupted, manifest = inject_call(
        call, DefectConfig(seed=1, defects=(DefectType.AMOUNT_TRANSPOSITION,))
    )
    assert corrupted.call_amount != call.call_amount
    assert len(manifest) == 1


def test_distribution_missing_field_nulls_the_source() -> None:
    distribution = _book().distributions[0]
    assert distribution.source is not None
    corrupted, _ = inject_distribution(
        distribution, DefectConfig(seed=1, defects=(DefectType.MISSING_FIELD,))
    )
    assert corrupted.source is None


def test_statement_arithmetic_error_breaks_the_reconciliation() -> None:
    statement = _book().statements[2]
    corrupted, manifest = inject_statement(statement, ALL_STATEMENT_DEFECTS)
    expected = (
        corrupted.beginning_balance
        + corrupted.contributions
        - corrupted.distributions
        - corrupted.management_fees
        + corrupted.realized_gain_loss
        + corrupted.unrealized_gain_loss
    )
    assert corrupted.ending_balance != expected
    assert len(manifest) == 1
    assert manifest[0].defect is DefectType.ARITHMETIC_ERROR


def test_a_defect_not_applicable_to_the_document_type_is_silently_ignored() -> None:
    # ARITHMETIC_ERROR only applies to statements — asking a call injector
    # for it should be a no-op, not an error.
    call = _book().calls[0]
    corrupted, manifest = inject_call(
        call, DefectConfig(seed=1, defects=(DefectType.ARITHMETIC_ERROR,))
    )
    assert corrupted == call
    assert manifest == []
