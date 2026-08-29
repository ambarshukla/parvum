"""The semantic layer is a published surface, so the gate governs it too."""

from __future__ import annotations

import pytest

from parvum_governance.check import check, find_repo_root
from parvum_governance.metric_views import MetricViewScanError, scan_metric_views
from parvum_governance.registry import load_registry

VIEW = """
-- a metric view
CREATE OR REPLACE VIEW workspace.parvum.thing_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: workspace.parvum.gold_thing
dimensions:
  - name: Client
    expr: client_name
measures:
  - name: Total wealth
    expr: SUM(value_usd)
$$;

COMMENT ON COLUMN workspace.parvum.thing_metrics.`Total wealth` IS
  'what a client statement leads with';
COMMENT ON COLUMN workspace.parvum.thing_metrics.`Client` IS
  'client family display name';
"""


def write(tmp_path, text=VIEW, name="thing_metrics.sql"):
    directory = tmp_path / "metric_views"
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_measures_and_dimensions_are_read_with_their_definitions(tmp_path):
    fields = scan_metric_views(write(tmp_path))
    by_name = {f.name: f for f in fields}
    assert by_name["Total wealth"].kind == "measure"
    assert by_name["Total wealth"].expr == "SUM(value_usd)"
    assert by_name["Total wealth"].description == "what a client statement leads with"
    assert by_name["Client"].kind == "dimension"


def test_a_measure_with_no_definition_fails_the_gate(tmp_path):
    # The rule that makes a semantic contract a contract: a measure called
    # "Total wealth" looks self-explanatory and is not, and an AI binds the
    # term to whatever text sits beside it.
    stripped = VIEW.replace(
        "COMMENT ON COLUMN workspace.parvum.thing_metrics.`Total wealth` IS\n"
        "  'what a client statement leads with';\n",
        "",
    )
    fields = scan_metric_views(write(tmp_path, stripped))
    registry_path = tmp_path / "cde_registry.yml"
    registry_path.write_text(
        "version: 1\nowners: {a: b}\nslos: {}\ncommon_columns: {}\ntables: {}\n",
        encoding="utf-8",
    )
    result = check([], load_registry(registry_path), set(), fields)
    assert {f.rule for f in result.findings} == {"undefined_measure"}
    assert result.findings[0].key == "thing_metrics.Total wealth"


def test_a_file_that_is_not_a_metric_view_fails_loudly(tmp_path):
    # Silence here would mean the gate quietly stopped governing the semantic
    # layer, which is the failure mode every scan in this package guards.
    with pytest.raises(MetricViewScanError, match="YAML body"):
        scan_metric_views(write(tmp_path, "SELECT 1;", name="not_a_view.sql"))


def test_an_empty_directory_fails_rather_than_passing_vacuously(tmp_path):
    directory = tmp_path / "metric_views"
    directory.mkdir()
    with pytest.raises(MetricViewScanError, match="no measures or dimensions"):
        scan_metric_views(directory)


def test_the_real_semantic_layer_defines_every_measure_it_publishes():
    fields = scan_metric_views(find_repo_root() / "spark" / "metric_views")
    undefined = [f.key for f in fields if not f.description.strip()]
    assert not undefined, f"no business definition for: {undefined}"
    # A metric view with no measures is a view, not a semantic layer.
    assert any(f.kind == "measure" for f in fields)
