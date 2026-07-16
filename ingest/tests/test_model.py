"""Tests as documentation: each test states a property the model guarantees."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from parvum_ingest import (
    Account,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Money,
    Position,
    SecurityIdentifier,
)


def apple_isin() -> SecurityIdentifier:
    return SecurityIdentifier(scheme=IdentifierScheme.ISIN, value="US0378331005")


def a_position(**overrides: object) -> Position:
    defaults: dict = {
        "account_id": "ACC-001",
        "security": apple_isin(),
        "security_name": "Apple Inc",
        "quantity": Decimal("100"),
        "as_of": date(2026, 7, 15),
        "cost_basis": Money(amount=Decimal("15000.00"), currency="USD"),
    }
    return Position(**{**defaults, **overrides})


class TestMoney:
    def test_amounts_are_exact_decimals(self) -> None:
        # 0.1 + 0.2 in float is 0.30000000000000004 — Decimal must not do that.
        m = Money(amount=Decimal("0.1") + Decimal("0.2"), currency="USD")
        assert m.amount == Decimal("0.3")

    def test_currency_must_be_three_uppercase_letters(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="usd")
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="US")


class TestSecurityIdentifier:
    def test_wrong_shape_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            SecurityIdentifier(scheme=IdentifierScheme.ISIN, value="NOT-AN-ISIN")

    def test_value_is_normalised(self) -> None:
        sec = SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=" us0378331005 ")
        assert sec.value == "US0378331005"

    def test_valid_isin_checksums(self) -> None:
        # Real ISINs: Apple, Microsoft, Vodafone.
        for isin in ("US0378331005", "US5949181045", "GB00BH4HKS39"):
            sec = SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=isin)
            assert sec.has_valid_checksum(), isin

    def test_mistyped_isin_is_constructable_but_flagged(self) -> None:
        # Shape-valid, checksum-invalid: the model must CARRY it (real feeds
        # contain typos) while has_valid_checksum exposes the defect for the
        # data-quality layer. This split is decision D-009.
        sec = SecurityIdentifier(scheme=IdentifierScheme.ISIN, value="US0378331006")
        assert not sec.has_valid_checksum()


class TestPosition:
    def test_missing_cost_basis_is_representable(self) -> None:
        # A classic feed defect the pipeline must detect, not reject.
        pos = a_position(cost_basis=None)
        assert pos.cost_basis is None

    def test_positions_are_immutable(self) -> None:
        pos = a_position()
        with pytest.raises(ValidationError):
            pos.quantity = Decimal("999")  # type: ignore[misc]

    def test_unknown_fields_fail_loudly(self) -> None:
        # Catches parser bugs: a misspelled field must not silently vanish.
        with pytest.raises(ValidationError):
            a_position(quantty=Decimal("1"))


class TestHoldingsStatement:
    def test_round_trippable_construction(self) -> None:
        stmt = HoldingsStatement(
            statement_id="STMT-2026-07-15-001",
            account=Account(
                account_id="ACC-001",
                name="Growth Portfolio",
                custodian_bic="CUSTGB2LXXX",
                base_currency="USD",
            ),
            as_of=date(2026, 7, 15),
            source_format=FeedFormat.SEMT_002,
            positions=(a_position(),),
        )
        assert stmt.positions[0].security.value == "US0378331005"
