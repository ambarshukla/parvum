"""Loading the register: shape errors, and how an entry resolves."""

from __future__ import annotations

import textwrap

import pytest

from parvum_governance.registry import RegistryError, load_registry

MINIMAL = """
version: 1
owners:
  platform-ops: the machinery
  client-reporting: what a client sees
slos:
  gold_freshness:
    objective: fresh
    measured_by: bronze_days_behind
    target: 2 days
    attainment_objective: 0.98
    window_days: 7
common_columns:
  rebuilt_at:
    tier: operational
    owner: platform-ops
tables:
  gold_thing:
    owner: client-reporting
    default_tier: supporting
    columns:
      as_of:
      rebuilt_at:
      value_usd:
        tier: critical
        definition: the money
        slo: gold_freshness
        quality_rules: [files_landed_rate]
"""


def write(tmp_path, text):
    path = tmp_path / "cde_registry.yml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_table_defaults_fill_in_the_boring_columns(tmp_path):
    registry = load_registry(write(tmp_path, MINIMAL))
    entry = registry.resolve("gold_thing", "as_of")
    assert entry is not None
    assert entry.tier == "supporting"
    assert entry.owner == "client-reporting"


def test_common_columns_beat_table_defaults(tmp_path):
    registry = load_registry(write(tmp_path, MINIMAL))
    entry = registry.resolve("gold_thing", "rebuilt_at")
    assert entry.tier == "operational"
    assert entry.owner == "platform-ops"


def test_a_columns_own_entry_beats_everything(tmp_path):
    registry = load_registry(write(tmp_path, MINIMAL))
    entry = registry.resolve("gold_thing", "value_usd")
    assert entry.tier == "critical"
    assert entry.definition == "the money"
    assert entry.quality_rules == ("files_landed_rate",)
    assert entry.has_control_coverage


def test_an_unlisted_column_resolves_to_nothing(tmp_path):
    # This is what makes a newly added column fail the gate: defaults can
    # fill in fields, but they cannot invent a key that is not there.
    registry = load_registry(write(tmp_path, MINIMAL))
    assert registry.resolve("gold_thing", "brand_new_column") is None
    assert registry.resolve("gold_unregistered_table", "as_of") is None


def test_a_stated_gap_counts_as_control_coverage(tmp_path):
    registry = load_registry(
        write(
            tmp_path,
            MINIMAL.replace(
                "        quality_rules: [files_landed_rate]",
                "        control_gap: nothing tests this yet",
            ),
        )
    )
    entry = registry.resolve("gold_thing", "value_usd")
    assert entry.quality_rules == ()
    assert entry.has_control_coverage


OWNERS_BLOCK = "owners:\n  platform-ops: the machinery\n  client-reporting: what a client sees\n"
RULES_LINE = "        quality_rules: [files_landed_rate]\n"


@pytest.mark.parametrize(
    ("mutation", "replacement", "message"),
    [
        ("version: 1\n", "version: 2\n", "unsupported register version"),
        (OWNERS_BLOCK, "owners: {}\n", "non-empty mapping"),
        ("      as_of:\n", "      as_of:\n        criticality: high\n", "unknown field"),
        (RULES_LINE, "        quality_rules: files_landed_rate\n", "must be a list"),
        ("    measured_by: bronze_days_behind\n", "", "is missing"),
    ],
)
def test_shape_errors_are_caught_on_load(tmp_path, mutation, replacement, message):
    text = textwrap.dedent(MINIMAL).replace(mutation, replacement, 1)
    with pytest.raises(RegistryError, match=message):
        load_registry(write(tmp_path, text))
