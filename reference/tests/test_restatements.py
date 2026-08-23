"""The book-restatement register: does it still describe the book it claims to?"""

import json
from datetime import date
from decimal import Decimal

import pytest

from parvum_reference.accounts import UNIVERSE
from parvum_reference.publish_restatements import render, write_snapshot
from parvum_reference.restatements import (
    RESTATEMENTS,
    declared_divisors,
    undeclared_divisor_changes,
)

LIVE_DIVISORS = {spec.account_id: spec.share_divisor for spec in UNIVERSE}


def test_register_matches_the_live_divisors() -> None:
    # The control that makes declaration more than a comment: change a divisor
    # in accounts.py without recording the restatement here and this fails,
    # rather than the change reaching the performance chain as a market return.
    assert undeclared_divisor_changes() == {}


def test_every_restatement_names_a_real_account() -> None:
    for entry in RESTATEMENTS:
        assert entry.account_id in LIVE_DIVISORS, entry.account_id


def test_every_restatement_actually_changes_the_ruler() -> None:
    # A restatement that restates nothing would break the performance chain
    # for no reason — the day would lose a real return and gain nothing.
    for entry in RESTATEMENTS:
        assert entry.divisor_before != entry.divisor_after, entry.account_id
        assert entry.divisor_before > 0 and entry.divisor_after > 0


def test_every_restatement_cites_a_decision() -> None:
    # A restatement is a judgement call, and an uncited one is indistinguishable
    # from someone making an inconvenient number go away.
    for entry in RESTATEMENTS:
        assert entry.decision_ref.startswith("D-"), entry.decision_ref
        assert len(entry.reason) > 40, entry.account_id


def test_d066_is_on_the_register() -> None:
    # The restatement that produced the +414% day, pinned: both Berkshire
    # accounts, one date, a fivefold rescale each.
    d066 = [e for e in RESTATEMENTS if e.decision_ref == "D-066"]
    assert {e.account_id for e in d066} == {"60011234", "60018852"}
    for entry in d066:
        assert entry.effective_date == date(2026, 8, 17)
        assert entry.divisor_before / entry.divisor_after == Decimal(5)


def test_declared_divisors_resolve_to_the_latest() -> None:
    assert declared_divisors() == {"60011234": Decimal(2_000), "60018852": Decimal(4_000)}


def test_snapshot_is_json_lines_with_string_decimals(tmp_path) -> None:
    path = tmp_path / "book_restatements.json"
    count = write_snapshot(path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()

    assert count == len(RESTATEMENTS) == len(lines)
    for line in lines:
        record = json.loads(line)
        assert set(record) == {
            "effective_date",
            "account_id",
            "divisor_before",
            "divisor_after",
            "reason",
            "decision_ref",
        }
        # Strings, not JSON numbers: a divisor that round-tripped through a
        # float is a divisor nobody can reconcile against accounts.py.
        assert isinstance(record["divisor_before"], str)
        assert isinstance(record["divisor_after"], str)


def test_snapshot_is_byte_identical_across_runs() -> None:
    # Same regeneration guarantee the rest of the landable reference data has.
    assert render() == render()


def test_publish_refuses_when_the_book_has_drifted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "parvum_reference.publish_restatements.undeclared_divisor_changes",
        lambda: {"60011234": (Decimal(2_000), Decimal(500))},
    )
    with pytest.raises(ValueError, match="disagrees with the live divisors"):
        write_snapshot(tmp_path / "book_restatements.json")
