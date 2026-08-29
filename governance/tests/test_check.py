"""Each gate rule, proven to fire — and proven not to fire on the real repo."""

from __future__ import annotations

import textwrap

from parvum_governance.check import check, check_repo, find_repo_root
from parvum_governance.registry import load_registry
from parvum_governance.schema_scan import PublishedColumn

DQ_METRICS = {"files_landed_rate", "cash_conformed_consistency_rate"}

REGISTER = """
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
common_columns: {}
tables:
  gold_thing:
    owner: client-reporting
    default_tier: supporting
    context: what this table is for, in prose
    columns:
      as_of:
      value_usd:
        tier: critical
        definition: the money
        slo: gold_freshness
        quality_rules: [files_landed_rate]
"""


def published(*columns, table="gold_thing", description="a description"):
    return [
        PublishedColumn(
            table=table,
            column=column,
            description=description,
            layer="gold",
            source_file="gold_reports.py",
        )
        for column in columns
    ]


def run(tmp_path, columns, register=REGISTER):
    path = tmp_path / "cde_registry.yml"
    path.write_text(textwrap.dedent(register), encoding="utf-8")
    return check(columns, load_registry(path), DQ_METRICS)


def rules(result):
    return {finding.rule for finding in result.findings}


def test_a_clean_estate_passes(tmp_path):
    result = run(tmp_path, published("as_of", "value_usd"))
    assert result.passed, [str(f) for f in result.findings]
    assert result.coverage.registered == 2
    assert result.coverage.by_tier == {"supporting": 1, "critical": 1}


def test_a_new_column_fails_until_it_is_classified(tmp_path):
    # The rule that makes the register keep up with the code.
    result = run(tmp_path, published("as_of", "value_usd", "brand_new_column"))
    assert rules(result) == {"unclassified"}
    assert "brand_new_column" in result.findings[0].key
    assert result.coverage.classified_pct < 100


def test_a_dropped_column_leaves_an_orphan_entry(tmp_path):
    result = run(tmp_path, published("value_usd"))
    assert rules(result) == {"orphan"}
    assert result.findings[0].key == "gold_thing.as_of"


def test_a_column_with_no_catalog_description_fails(tmp_path):
    columns = published("value_usd") + published("as_of", description="   ")
    result = run(tmp_path, columns)
    assert rules(result) == {"missing_description"}


def test_a_critical_element_must_say_what_it_means(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("        definition: the money\n", ""),
    )
    assert rules(result) == {"incomplete_obligation"}
    assert "'definition'" in result.findings[0].message


def test_a_critical_element_must_name_a_service_level(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("        slo: gold_freshness\n", ""),
    )
    # Removing the citation breaks two things at once, and both are reported:
    # the element owes an SLO, and the SLO it used to cite is now held by
    # nothing at all.
    assert rules(result) == {"incomplete_obligation", "unheld_slo"}
    assert "'slo'" in result.findings[0].message


def test_a_critical_element_may_not_stay_silent_about_controls(tmp_path):
    # It may say "nothing tests this yet" — it may not say nothing at all.
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("        quality_rules: [files_landed_rate]\n", ""),
    )
    assert rules(result) == {"incomplete_obligation"}
    assert "control_gap" in result.findings[0].message


def test_an_admitted_gap_satisfies_the_control_obligation(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace(
            "        quality_rules: [files_landed_rate]",
            "        control_gap: no rule re-derives this yet",
        ),
    )
    assert result.passed
    assert result.coverage.critical_with_gap == 1
    assert result.coverage.critical_with_controls == 0
    assert result.coverage.control_coverage_pct == 0.0


def test_a_quality_rule_the_dq_layer_does_not_compute_is_rejected(tmp_path):
    # A control you cannot execute is worse than an admitted gap: it reads
    # as covered.
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("files_landed_rate]", "rate_that_does_not_exist]"),
    )
    assert rules(result) == {"invalid_reference"}
    assert "not a metric the DQ layer computes" in result.findings[0].message


def test_an_unknown_owner_role_is_rejected(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("owner: client-reporting", "owner: nobody"),
    )
    assert rules(result) == {"invalid_reference"}
    assert all("unknown owner" in finding.message for finding in result.findings)


def test_an_unknown_slo_is_rejected(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("slo: gold_freshness", "slo: made_up"),
    )
    # Two rules fire, and both are right: the element cites an SLO that does
    # not exist, and the SLO that does exist is now held by nothing.
    assert rules(result) == {"invalid_reference", "unheld_slo"}


def test_a_service_level_nobody_is_held_to_fails(tmp_path):
    # The mirror of `orphan`, pointed at the SLO block: a promise with no
    # element on the hook for it is decoration — and, because attainment is
    # computed from the SLOs the register's own elements cite, an unheld one
    # would never be measured either. Everything else here stays valid, so the
    # unheld SLO is the only finding.
    second_slo = (
        "  cash_ledger_integrity:\n"
        "    objective: it adds up\n"
        "    measured_by: cash_conformed_consistency_rate\n"
        "    target: 99%\n"
        "    attainment_objective: 0.95\n"
        "    window_days: 30\n"
        "common_columns: {}"
    )
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("common_columns: {}", second_slo),
    )
    assert rules(result) == {"unheld_slo"}
    assert result.findings[0].key == "cash_ledger_integrity"


def test_an_unknown_tier_is_rejected_and_obligations_are_not_guessed(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        REGISTER.replace("tier: critical", "tier: extremely"),
    )
    # No element is `critical` any more, so nothing is held to the SLO either.
    assert rules(result) == {"invalid_reference", "unheld_slo"}
    assert result.coverage.by_tier == {"supporting": 1}


def test_the_real_repository_passes_its_own_gate():
    # The same reconciliation CI runs, so `make test` catches a broken
    # register too — not only the dedicated check.
    result = check_repo(find_repo_root())
    assert result.passed, "\n".join(str(finding) for finding in result.findings)
    assert result.coverage.classified_pct == 100.0
    # The critical list is meant to stay a small, defensible minority.
    assert 0 < result.coverage.critical < result.coverage.published * 0.15


CONTRACT_REGISTER = REGISTER.replace(
    "    context: what this table is for, in prose\n",
    "    context: what this table is for, in prose\n"
    "    grain: [as_of]\n"
    "    foreign_keys:\n"
    "      - column: as_of\n"
    "        references: gold_thing.as_of\n"
    "        cardinality: many_to_one\n",
)


def test_a_declared_contract_that_resolves_passes(tmp_path):
    result = run(tmp_path, published("as_of", "value_usd"), CONTRACT_REGISTER)
    assert result.passed


def test_a_foreign_key_pointing_at_a_column_nobody_publishes_fails(tmp_path):
    # The rule that earns this whole block. Join keys usually live in catalog
    # comments where nothing checks them, so they rot the first time a column
    # is renamed and the reader cannot tell.
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        CONTRACT_REGISTER.replace("references: gold_thing.as_of", "references: gold_thing.renamed"),
    )
    assert rules(result) == {"broken_contract"}
    assert "no job publishes that column" in result.findings[0].message


def test_a_grain_column_the_table_does_not_publish_fails(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        CONTRACT_REGISTER.replace("grain: [as_of]", "grain: [as_of, dropped_column]"),
    )
    assert rules(result) == {"broken_contract"}
    assert "does not publish it" in result.findings[0].message


def test_an_unknown_join_cardinality_is_rejected(tmp_path):
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        CONTRACT_REGISTER.replace("cardinality: many_to_one", "cardinality: sort_of_one"),
    )
    assert rules(result) == {"broken_contract"}
    assert "unknown cardinality" in result.findings[0].message


def test_a_table_with_a_critical_element_must_say_what_it_is_for(tmp_path):
    # A table nobody consumes directly can be read from its column comments.
    # One carrying a critical element is being read by people and models
    # making decisions, and a column list does not say what it is *for*.
    result = run(
        tmp_path,
        published("as_of", "value_usd"),
        CONTRACT_REGISTER.replace("    context: what this table is for, in prose\n", ""),
    )
    assert rules(result) == {"broken_contract"}
    assert result.findings[0].key == "gold_thing"
