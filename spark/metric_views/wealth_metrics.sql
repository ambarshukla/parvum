-- wealth_metrics — the governed semantic layer over gold_client_wealth.
--
-- A Unity Catalog metric view: a YAML spec of dimensions and measures over one
-- source table. It stores no data — it is a governed query surface. The
-- bronze -> gold job does NOT create it (a metric view is a catalog object, not
-- a Delta table), so the definition lives here, is code-reviewed, and is
-- (re)applied on its own with `make metric-views`.
--
-- Query it through MEASURE(); see spark/metric_views/README.md and
-- docs/SEMANTIC_LAYER.md.

CREATE OR REPLACE VIEW workspace.parvum.wealth_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: workspace.parvum.gold_client_wealth
dimensions:
  - name: Client
    expr: client_name
  - name: As of
    expr: as_of
  - name: Books reconcile
    expr: books_reconcile
measures:
  - name: Total wealth
    expr: SUM(total_wealth_usd)
  - name: Positions
    expr: SUM(positions_usd)
  - name: Cash
    expr: SUM(cash_usd)
  - name: Alts NAV
    expr: SUM(alts_usd)
  - name: Reconcile variance
    expr: SUM(reconcile_variance_usd)
  - name: Clients
    expr: COUNT(DISTINCT client_id)
$$;

-- Descriptions are a separate step: CREATE OR REPLACE drops and recreates the
-- object, so these run every apply. The comment is the *business* definition,
-- not the technical one (see docs/GLOSSARY.md, "business definition vs. catalog
-- description").
COMMENT ON VIEW workspace.parvum.wealth_metrics IS
  'Governed client-wealth measures, one row per client per valuation date. Semantic layer over gold_client_wealth — see docs/SEMANTIC_LAYER.md.';

COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Total wealth` IS
  'positions + cash + alts, owner-prorated, USD — the headline number a client statement leads with';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Positions` IS
  'Owner-prorated securities value in USD, converted at the day''s ECB rate';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Cash` IS
  'Owner-prorated closing cash in USD';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Alts NAV` IS
  'Owner-prorated private-fund NAV in USD, forward-filled from the most recent confirmed capital account statement';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Reconcile variance` IS
  'USD arithmetic gap on accounts failing the conformed cash check; 0 when the client''s books reconcile';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Clients` IS
  'Distinct client families in scope for the selected slice';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Client` IS
  'Client family display name (gold_client_wealth.client_name)';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`As of` IS
  'Valuation date (gold_client_wealth.as_of); grain is one row per client per date';
COMMENT ON COLUMN workspace.parvum.wealth_metrics.`Books reconcile` IS
  'TRUE when the conformed cash check passes for every account this client owns on this date';
