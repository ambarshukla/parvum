-- The disclosure half of D-070. A book restatement -- a change to how the
-- synthetic book is constructed, such as an account's share_divisor -- moves
-- reported value with no market event and no client cash flow behind it. It
-- is removed from all three return methodologies upstream, which is what
-- stopped the client dashboard reporting +392.70% for a book that had earned
-- nothing. These columns are what let the page *say so* rather than leaving a
-- reader to reconcile a quintupled wealth figure against a negative return.
--
-- Additive, like V2-V9. `default 0` only matters for the ALTERs succeeding
-- against rows that already exist before the next export reload overwrites
-- them.
--
-- Note the shape of the obligation these close: without them the exporter
-- fails loudly at INSERT (a column in the lakehouse with nowhere to land),
-- which is the drift-detection behaviour the loader documents. This migration
-- is therefore not optional dressing -- gold and serving have to agree.

alter table performance add column restatement_adjustment_usd numeric(24, 2) not null default 0;
comment on column performance.restatement_adjustment_usd is
    'Value change on a declared book-restatement day that the market did not produce -- the day''s whole non-flow move, booked here instead of to return. 0 on every other day, so the column is safe to sum.';

alter table performance add column restatement_detail varchar;
comment on column performance.restatement_detail is
    'Which account was restated, from which divisor to which, and the decision that authorised it; NULL on days with no declared restatement.';

alter table performance_summary add column restatement_adjustment_usd numeric(24, 2) not null default 0;
comment on column performance_summary.restatement_adjustment_usd is
    'Sum of restatement_adjustment_usd over the reported window -- total value change from declared book restatements, removed from TWR, Dietz and IRR alike and disclosed separately because it is neither the client''s money nor the market''s doing.';
