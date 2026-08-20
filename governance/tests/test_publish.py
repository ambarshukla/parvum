"""The landed snapshot is a contract with the lakehouse; its shape is tested."""

from __future__ import annotations

import json

from parvum_governance.check import find_repo_root
from parvum_governance.publish import build_snapshot, render, write_snapshot
from parvum_governance.schema_scan import scan_spark_jobs


def test_the_snapshot_covers_every_published_column():
    # Published, not registered: the lakehouse computes its own classification
    # coverage from these rows, so an unclassified column has to appear here
    # (with a NULL tier) rather than be silently absent.
    root = find_repo_root()
    assert len(build_snapshot(root)) == len(scan_spark_jobs(root / "spark"))


def test_a_critical_row_carries_its_whole_obligation():
    rows = {(r.table_name, r.column_name): r for r in build_snapshot(find_repo_root())}
    wealth = rows[("gold_client_wealth", "total_wealth_usd")]
    assert wealth.tier == "critical"
    assert wealth.owner == "client-reporting"
    assert wealth.definition
    assert wealth.quality_rule_count == len(wealth.quality_rules.split(", "))
    # The SLO is flattened, not referenced — one table that answers a question.
    assert wealth.slo == "gold_freshness"
    assert wealth.slo_measured_by == "bronze_days_behind"
    assert wealth.slo_target


def test_a_gapped_element_carries_the_gap_and_no_rules():
    rows = {(r.table_name, r.column_name): r for r in build_snapshot(find_repo_root())}
    fx = rows[("gold_client_wealth", "fx_rate_used")]
    assert fx.tier == "critical"
    assert fx.quality_rules == ""
    assert fx.quality_rule_count == 0
    assert fx.control_gap


def test_the_register_classifies_its_own_table():
    # governance_cde_registry is published like any other table, so the gate
    # requires it to appear in the very file it describes.
    tables = {r.table_name for r in build_snapshot(find_repo_root())}
    assert "governance_cde_registry" in tables


def test_render_is_json_lines_spark_can_read_without_a_multiline_flag():
    rows = build_snapshot(find_repo_root())
    text = render(rows)
    lines = text.splitlines()
    assert len(lines) == len(rows)
    first = json.loads(lines[0])
    assert set(first) == {
        "table_name",
        "column_name",
        "layer",
        "description",
        "tier",
        "owner",
        "definition",
        "quality_rules",
        "quality_rule_count",
        "control_gap",
        "slo",
        "slo_measured_by",
        "slo_target",
    }


def test_write_snapshot_round_trips(tmp_path):
    out = tmp_path / "nested" / "cde_registry.json"
    path, count = write_snapshot(find_repo_root(), out)
    assert path == out
    parsed = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(parsed) == count


def test_publishing_is_refused_when_the_gate_fails(tmp_path, monkeypatch, capsys):
    # A snapshot of a broken register would put wrong ownership into the
    # lakehouse and onto a screen — worse than publishing nothing.
    from parvum_governance import cli
    from parvum_governance.check import Coverage, Finding, GateResult

    broken = GateResult(
        findings=[Finding("unclassified", "gold_thing.new_column", "absent from the register")],
        coverage=Coverage(
            published=1,
            registered=0,
            by_tier={},
            critical_with_controls=0,
            critical_with_gap=0,
        ),
    )
    monkeypatch.setattr(cli, "check_repo", lambda root: broken)
    out = tmp_path / "cde_registry.json"
    assert cli.publish(["--repo-root", str(find_repo_root()), "--out", str(out)]) == 1
    assert not out.exists()
    assert "refusing to publish" in capsys.readouterr().err
