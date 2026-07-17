"""Defect injection: deterministic, manifest-recorded, and — critically —
the defects survive the trip through a real wire format."""

from datetime import date

import pytest

from parvum_ingest.book import build_book, build_cash_statement
from parvum_ingest.defects import (
    DefectConfig,
    DefectType,
    inject_cash,
    inject_holdings,
    truncate_text,
)
from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats.camt053 import DEBIT_TYPES, parse_camt053, render_camt053
from parvum_ingest.formats.semt002 import parse_semt002, render_semt002
from parvum_ingest.model import BalanceType

AS_OF = date(2026, 7, 15)

ALL_HOLDINGS = DefectConfig(
    seed=42,
    defects=(DefectType.MISSING_COST_BASIS, DefectType.MISTYPED_ISIN, DefectType.STALE_PRICE),
)
ALL_CASH = DefectConfig(
    seed=42,
    defects=(
        DefectType.DUPLICATE_TRANSACTION,
        DefectType.DROPPED_TRANSACTION,
        DefectType.SETTLEMENT_SHIFT,
    ),
)


def test_same_seed_same_corruption() -> None:
    book = build_book(AS_OF)
    assert inject_holdings(book, ALL_HOLDINGS) == inject_holdings(book, ALL_HOLDINGS)


def test_original_statement_is_untouched() -> None:
    book = build_book(AS_OF)
    inject_holdings(book, ALL_HOLDINGS)
    assert book == build_book(AS_OF)


def test_every_injection_is_recorded_in_the_manifest() -> None:
    _, manifest = inject_holdings(build_book(AS_OF), ALL_HOLDINGS)
    assert [r.defect for r in manifest] == list(ALL_HOLDINGS.defects)
    _, cash_manifest = inject_cash(build_cash_statement(AS_OF), ALL_CASH)
    assert [r.defect for r in cash_manifest] == list(ALL_CASH.defects)
    # The manifest names real targets, not placeholders.
    assert all(r.target_id for r in manifest + cash_manifest)


def test_mistyped_isin_survives_the_wire() -> None:
    # The whole point: a semantic defect must travel through a real format
    # and still be detectable on the far side.
    config = DefectConfig(seed=7, defects=(DefectType.MISTYPED_ISIN,))
    corrupted, manifest = inject_holdings(build_book(AS_OF), config)
    parsed = parse_semt002(render_semt002(corrupted))

    bad = [p for p in parsed.positions if not p.security.has_valid_checksum()]
    assert len(bad) == 1
    assert bad[0].security.value == manifest[0].detail.split(" -> ")[1]


def test_duplicate_breaks_the_balance_invariant() -> None:
    config = DefectConfig(seed=7, defects=(DefectType.DUPLICATE_TRANSACTION,))
    corrupted, _ = inject_cash(build_cash_statement(AS_OF), config)
    (parsed,) = parse_camt053(render_camt053(corrupted))

    opening = next(b for b in parsed.balances if b.balance_type is BalanceType.OPENING)
    closing = next(b for b in parsed.balances if b.balance_type is BalanceType.CLOSING)
    net = sum(
        (-t.amount.amount if t.type in DEBIT_TYPES else t.amount.amount) for t in parsed.entries
    )
    # closing no longer explains the movement — reconciliation's signal.
    assert closing.balance.amount != opening.balance.amount + net


def test_dropped_transaction_shrinks_the_statement() -> None:
    config = DefectConfig(seed=7, defects=(DefectType.DROPPED_TRANSACTION,))
    clean = build_cash_statement(AS_OF)
    corrupted, manifest = inject_cash(clean, config)
    assert len(corrupted.entries) == len(clean.entries) - 1
    assert manifest[0].target_id not in {t.transaction_id for t in corrupted.entries}


def test_settlement_shift_is_exactly_one_day() -> None:
    config = DefectConfig(seed=7, defects=(DefectType.SETTLEMENT_SHIFT,))
    clean = build_cash_statement(AS_OF)
    corrupted, manifest = inject_cash(clean, config)
    (record,) = manifest
    before = next(t for t in clean.entries if t.transaction_id == record.target_id)
    after = next(t for t in corrupted.entries if t.transaction_id == record.target_id)
    assert (after.settlement_date - before.settlement_date).days == 1
    assert after.trade_date == before.trade_date


def test_missing_cost_basis_targets_a_position_that_had_one() -> None:
    config = DefectConfig(seed=7, defects=(DefectType.MISSING_COST_BASIS,))
    clean = build_book(AS_OF)
    corrupted, manifest = inject_holdings(clean, config)
    (record,) = manifest
    before = next(p for p in clean.positions if p.security.value == record.target_id)
    after = next(p for p in corrupted.positions if p.security.value == record.target_id)
    assert before.cost_basis is not None and after.cost_basis is None


def test_truncated_file_fails_at_the_parser_not_downstream() -> None:
    rendered = render_semt002(build_book(AS_OF))
    broken, record = truncate_text(rendered, seed=99)
    assert record.defect is DefectType.TRUNCATED_FILE
    with pytest.raises(FeedParseError):
        parse_semt002(broken)


def test_stale_price_moves_only_the_price_date() -> None:
    config = DefectConfig(seed=7, defects=(DefectType.STALE_PRICE,))
    clean = build_book(AS_OF)
    corrupted, manifest = inject_holdings(clean, config)
    (record,) = manifest
    before = next(p for p in clean.positions if p.security.value == record.target_id)
    after = next(p for p in corrupted.positions if p.security.value == record.target_id)
    assert before.price_as_of is not None and after.price_as_of is not None
    assert (before.price_as_of - after.price_as_of).days == 5
    assert after.price == before.price  # price value untouched: stale, not wrong
    assert after.quantity == before.quantity
