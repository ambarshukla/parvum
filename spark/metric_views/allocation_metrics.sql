-- allocation_metrics — governed measures over gold_asset_allocation.
--
-- Note what is NOT a measure here: `weight`. It is a share, and a share is
-- only meaningful at the grain it was computed for — summed across dates it
-- becomes a count of days, and summed across clients it becomes nonsense that
-- still renders as a number. The semantic-layer answer to a ratio is to
-- expose the additive component and let the consumer divide at whatever grain
-- they chose, which is exactly what `Allocated value` is for.
--
-- A semantic layer that refuses to expose a measure it cannot make safe is
-- doing its job. See docs/SEMANTIC_LAYER.md.

CREATE OR REPLACE VIEW workspace.parvum.allocation_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: workspace.parvum.gold_asset_allocation
dimensions:
  - name: Client
    expr: client_name
  - name: As of
    expr: as_of
  - name: Asset class
    expr: asset_class
measures:
  - name: Allocated value
    expr: SUM(value_usd)
  - name: Asset classes
    expr: COUNT(DISTINCT asset_class)
  - name: Clients
    expr: COUNT(DISTINCT client_id)
$$;

COMMENT ON VIEW workspace.parvum.allocation_metrics IS
  'Governed allocation measures: what client wealth is made of, by asset class and date. Semantic layer over gold_asset_allocation — see docs/SEMANTIC_LAYER.md.';

COMMENT ON COLUMN workspace.parvum.allocation_metrics.`Allocated value` IS
  'Owner-prorated USD value in an asset class. Additive at every grain, which is why share-of-wealth is derived from it rather than stored as its own measure';
COMMENT ON COLUMN workspace.parvum.allocation_metrics.`Asset classes` IS
  'How many distinct asset classes appear in the selected slice';
COMMENT ON COLUMN workspace.parvum.allocation_metrics.`Clients` IS
  'Distinct client families in the selected slice';
COMMENT ON COLUMN workspace.parvum.allocation_metrics.`Client` IS
  'Client family display name';
COMMENT ON COLUMN workspace.parvum.allocation_metrics.`As of` IS
  'Valuation date; the grain of the source is one row per client per date per asset class';
COMMENT ON COLUMN workspace.parvum.allocation_metrics.`Asset class` IS
  'Instrument class from the securities master; Cash and Alternatives are classes here, and Unknown is kept visible rather than hidden (D-022)';
