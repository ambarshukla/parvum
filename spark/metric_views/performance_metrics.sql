-- performance_metrics — governed measures over gold_performance.
--
-- The most important thing about this view is what it deliberately does not
-- expose: **the returns themselves are not measures.**
--
-- `daily_twr_return` and `twr_index_since_inception` are on the source table
-- and are correct there. They are not aggregatable. A time-weighted return
-- over a period is the *chain-linked product* of its daily factors, not their
-- sum and not their average — and a metric view measure is an aggregate
-- expression. Exposing `AVG(daily_twr_return)` would produce a number for any
-- grain a consumer picked, and that number would be wrong in a way nothing on
-- the screen would reveal.
--
-- So this view exposes the additive components a return is built from —
-- wealth, the client's own flows, and any declared restatement — and the
-- chained figures stay in `gold_performance_summary`, computed once, by the
-- job that knows how (docs/PERFORMANCE_METHODOLOGY.md).
--
-- A semantic layer's job is to make the safe query the obvious one. Declining
-- to expose an unsafe measure is part of that, not a gap in coverage.

CREATE OR REPLACE VIEW workspace.parvum.performance_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: workspace.parvum.gold_performance
dimensions:
  - name: Client
    expr: client_name
  - name: As of
    expr: as_of
measures:
  - name: Wealth
    expr: SUM(total_wealth_usd)
  - name: Net external flow
    expr: SUM(external_flow_usd)
  - name: Restatement adjustment
    expr: SUM(restatement_adjustment_usd)
  - name: Days
    expr: COUNT(*)
$$;

COMMENT ON VIEW workspace.parvum.performance_metrics IS
  'Governed measures over the daily performance series: the additive components a return is built from. The returns themselves are deliberately not measures — a time-weighted return is a chain-linked product, not a sum or an average. See docs/SEMANTIC_LAYER.md.';

COMMENT ON COLUMN workspace.parvum.performance_metrics.`Wealth` IS
  'Total client wealth in USD. Additive across clients on one date; summing it across dates gives a meaningless total, so pick a date';
COMMENT ON COLUMN workspace.parvum.performance_metrics.`Net external flow` IS
  'Client contributions less withdrawals in USD — the money that moved in or out, which performance measurement exists to strip out. Additive at every grain';
COMMENT ON COLUMN workspace.parvum.performance_metrics.`Restatement adjustment` IS
  'Value change from a declared book restatement: a change of scale, not performance, excluded from every return figure and disclosed separately (D-070). Zero on every ordinary day, so it is safe to sum';
COMMENT ON COLUMN workspace.parvum.performance_metrics.`Days` IS
  'Number of client-days in the selected slice';
COMMENT ON COLUMN workspace.parvum.performance_metrics.`Client` IS
  'Client family display name';
COMMENT ON COLUMN workspace.parvum.performance_metrics.`As of` IS
  'Valuation date; the grain of the source is one row per client per date';
