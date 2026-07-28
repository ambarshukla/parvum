-- Detail behind two bare verdicts on the client dashboard (D-064): the
-- reconcile badge only ever said TRUE/FALSE, and the alts pending chip only
-- ever said a count. client_wealth gains how many accounts and how much;
-- alts_holdings gains what kind of document and through what period.
-- Additive, like V2-V6 -- V1-V6 are already applied and Flyway checksums
-- them. `default 0` only matters for the ALTERs succeeding against whatever
-- rows already exist before the next export reload overwrites them.

alter table client_wealth add column reconcile_break_accounts integer not null default 0;
comment on column client_wealth.reconcile_break_accounts is
    'Count of this client''s accounts where the conformed cash check fails on this date; 0 when books_reconcile is TRUE.';

alter table client_wealth add column reconcile_variance_usd numeric(24, 2) not null default 0;
comment on column client_wealth.reconcile_variance_usd is
    'This client''s prorated share of the broken accounts'' own arithmetic gap (opening + movements vs. closing), summed in USD; 0 when books_reconcile is TRUE.';

alter table alts_holdings add column pending_review_doc_types varchar;
comment on column alts_holdings.pending_review_doc_types is
    'Distinct doc types among this fund''s pending documents (comma-separated); NULL if none pending.';

alter table alts_holdings add column pending_review_latest_period date;
comment on column alts_holdings.pending_review_latest_period is
    'Latest period_end among pending capital account statements; NULL if no statement is pending.';
