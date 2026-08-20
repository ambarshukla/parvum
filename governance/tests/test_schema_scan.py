"""The inventory scan has to be right, or the gate judges the wrong estate."""

from __future__ import annotations

import textwrap

import pytest

from parvum_governance.check import find_repo_root
from parvum_governance.schema_scan import (
    SchemaScanError,
    extract_column_comments,
    layer_for,
    scan_dq_metric_names,
    scan_spark_jobs,
)

NOTEBOOK = textwrap.dedent(
    """
    # Databricks notebook source
    # MAGIC %md ## a job

    # COMMAND ----------

    SCHEMA = "workspace.parvum"

    COLUMN_COMMENTS = {
        "gold_thing": {"as_of": "the date", "value_usd": "the money"},
    }

    for _table, _comments in COLUMN_COMMENTS.items():
        spark.sql("...")  # noqa: F821
    """
)


def test_extracts_the_dict_without_executing_the_notebook():
    # The notebook references `spark`, which does not exist here. Parsing
    # rather than importing is the whole point.
    assert extract_column_comments(NOTEBOOK, origin="job.py") == {
        "gold_thing": {"as_of": "the date", "value_usd": "the money"}
    }


def test_a_computed_comment_is_an_error_not_a_silent_skip():
    source = 'PREFIX = "x"\nCOLUMN_COMMENTS = {"gold_thing": {"a": PREFIX + "y"}}\n'
    with pytest.raises(SchemaScanError, match="not a plain literal"):
        extract_column_comments(source, origin="job.py")


def test_missing_assignment_is_an_error():
    with pytest.raises(SchemaScanError, match="no COLUMN_COMMENTS"):
        extract_column_comments("x = 1\n", origin="job.py")


@pytest.mark.parametrize(
    ("table", "layer"),
    [
        ("bronze_holdings", "bronze"),
        ("silver_positions", "silver"),
        ("dq_metrics", "dq"),
        ("gold_client_wealth", "gold"),
    ],
)
def test_layer_comes_from_the_table_name_prefix(table, layer):
    assert layer_for(table) == layer


def test_an_unrecognised_prefix_is_loud_rather_than_bucketed():
    # A new layer is an architectural event; it should be a deliberate edit,
    # not something that lands silently in an "other" bucket.
    with pytest.raises(SchemaScanError, match="no recognised layer prefix"):
        layer_for("platinum_something")


def test_two_jobs_publishing_the_same_column_is_an_error(tmp_path):
    for name in ("job_a.py", "job_b.py"):
        (tmp_path / name).write_text(
            'COLUMN_COMMENTS = {"gold_thing": {"as_of": "the date"}}\n', encoding="utf-8"
        )
    with pytest.raises(SchemaScanError, match="more than one job"):
        scan_spark_jobs(tmp_path)


def test_a_job_with_no_column_comments_is_skipped_not_failed(tmp_path):
    (tmp_path / "orchestration.py").write_text("print('no tables here')\n", encoding="utf-8")
    assert scan_spark_jobs(tmp_path) == []


def test_the_real_spark_jobs_scan_cleanly():
    columns = scan_spark_jobs(find_repo_root() / "spark")
    keys = {column.key for column in columns}
    assert "gold_client_wealth.total_wealth_usd" in keys
    assert "silver_positions.quantity" in keys
    assert all(column.description.strip() for column in columns)


def test_dq_metric_names_come_from_the_dq_job_itself():
    names = scan_dq_metric_names(find_repo_root() / "spark" / "dq_recon.py")
    assert "cash_conformed_consistency_rate" in names
    assert "holdings_cross_format_match_rate" in names


def test_a_restructured_dq_job_fails_loudly_instead_of_matching_nothing(tmp_path):
    # Silently matching nothing would make the gate reject every quality
    # rule the register cites — a confusing failure a long way from its cause.
    job = tmp_path / "dq_recon.py"
    job.write_text("SELECT 1 AS something_else\n", encoding="utf-8")
    with pytest.raises(SchemaScanError, match="has probably changed"):
        scan_dq_metric_names(job)
