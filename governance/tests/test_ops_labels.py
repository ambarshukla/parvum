"""A figure put in front of a person has to be named for that person.

`dq_metrics` and the register's SLO block are both open by design, and nothing
connects publishing a metric to naming it. That gap reached production twice
before this rule existed, so these tests pin both halves: that the maps are
read correctly, and that the gate fails when something published is unnamed.
"""

from __future__ import annotations

import pytest

from parvum_governance.check import check, find_repo_root
from parvum_governance.ops_labels import OpsLabelScanError, scan_ops_labels
from parvum_governance.registry import load_registry

FORMAT_TS = """
const DQ_METRIC_LABELS: Record<string, string> = {
    files_landed_rate: "Files landed",
    // a comment line, which is not a key
    cash_conformed_consistency_rate: "Cash consistency",
    cross_field_invariant_rate: "Cross-field invariants",
    fx_rate_plausibility_rate: "FX rate plausibility",
};

const SLO_LABELS: Record<string, string> = {
    feed_completeness: "Feed completeness",
    gold_freshness: "Data freshness",
    cash_ledger_integrity: "Cash ledger integrity",
    cash_continuity: "Cash continuity",
    fx_integrity: "FX integrity",
};
"""

REGISTER = """
version: 1
owners:
  client-reporting: what a client sees
slos:
  gold_freshness:
    objective: fresh
    measured_by: bronze_days_behind
    target: 2 days
    attainment_objective: 0.98
    window_days: 7
common_columns: {}
tables: {}
"""


def write(tmp_path, text=FORMAT_TS):
    path = tmp_path / "format.ts"
    path.write_text(text, encoding="utf-8")
    return path


def registry_at(tmp_path, text=REGISTER):
    path = tmp_path / "cde_registry.yml"
    path.write_text(text, encoding="utf-8")
    return load_registry(path)


def test_both_label_maps_are_read_and_comments_are_not_keys(tmp_path):
    labels = scan_ops_labels(write(tmp_path))
    assert labels["DQ_METRIC_LABELS"] == {
        "files_landed_rate",
        "cash_conformed_consistency_rate",
        "cross_field_invariant_rate",
        "fx_rate_plausibility_rate",
    }
    assert "fx_integrity" in labels["SLO_LABELS"]


def test_a_published_metric_with_no_label_fails_the_gate(tmp_path):
    # The exact shape that shipped twice: a metric reaches production and the
    # page renders its identifier rather than its name.
    result = check(
        [],
        registry_at(tmp_path),
        {"files_landed_rate", "brand_new_metric_rate"},
        ops_labels=scan_ops_labels(write(tmp_path)),
    )
    unlabelled = [f for f in result.findings if f.rule == "unlabelled_metric"]
    assert [f.key for f in unlabelled] == ["brand_new_metric_rate"]
    assert "internal/src/format.ts" in unlabelled[0].message


def test_a_declared_service_level_with_no_label_fails_the_gate(tmp_path):
    # `fx_integrity` reached a live screen as "Fx integrity", because a
    # humanising fallback cannot know that fx is an acronym.
    stripped = FORMAT_TS.replace('    gold_freshness: "Data freshness",\n', "")
    result = check(
        [],
        registry_at(tmp_path),
        {"files_landed_rate"},
        ops_labels=scan_ops_labels(write(tmp_path, stripped)),
    )
    unlabelled = [f for f in result.findings if f.rule == "unlabelled_metric"]
    assert [f.key for f in unlabelled] == ["gold_freshness"]


def test_a_fully_labelled_estate_raises_no_label_findings(tmp_path):
    result = check(
        [],
        registry_at(tmp_path),
        {"files_landed_rate"},
        ops_labels=scan_ops_labels(write(tmp_path)),
    )
    assert not [f for f in result.findings if f.rule == "unlabelled_metric"]


def test_labels_are_not_checked_when_not_supplied(tmp_path):
    # `check` is called directly by other tests with three arguments; the rule
    # is opt-in so those keep exercising what they are about.
    result = check([], registry_at(tmp_path), {"anything_at_all"})
    assert not [f for f in result.findings if f.rule == "unlabelled_metric"]


def test_a_renamed_map_is_a_loud_stop_rather_than_a_silent_pass(tmp_path):
    # A gate that quietly stops checking is worse than one never added: the
    # coverage number keeps reading green while nothing is enforced.
    with pytest.raises(OpsLabelScanError, match="SLO_LABELS"):
        scan_ops_labels(write(tmp_path, FORMAT_TS.replace("SLO_LABELS", "SLO_NAMES")))


def test_the_real_repository_labels_everything_it_publishes():
    labels = scan_ops_labels(find_repo_root() / "internal" / "src" / "format.ts")
    assert len(labels["DQ_METRIC_LABELS"]) >= 16
    assert len(labels["SLO_LABELS"]) >= 8
