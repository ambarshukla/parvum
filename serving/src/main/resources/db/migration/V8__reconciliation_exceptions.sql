-- The account-level drill-down behind a reconcile badge (D-064 follow-up):
-- reconcile_break_accounts/_variance_usd on client_wealth answer "how many,
-- how much"; this answers "which account, how much on that one". Grain: one
-- row per (client, account) currently failing the conformed cash check,
-- latest date only -- like alts_holdings/top_holdings, a client with a
-- clean day simply has no rows here.
--
-- Also drops alts_holdings.pending_review_doc_types (added in V6, unused
-- after the client dashboard stopped surfacing the internal doc-type
-- taxonomy -- an unused column left wired through four layers is dead
-- weight, not a hedge). Postgres is a disposable projection rebuilt from
-- the lakehouse (D-029); dropping and re-adding costs one reload, nothing
-- more.

create table reconciliation_exceptions (
    client_id    varchar        not null,
    client_name  varchar        not null,
    account_id   varchar        not null,
    as_of        date           not null,
    currency     varchar        not null,
    delta_native numeric(24, 2) not null,
    delta_usd    numeric(24, 2) not null,
    rebuilt_at   timestamptz    not null,
    primary key (client_id, account_id)
);
comment on table reconciliation_exceptions is
    'Per client per currently-broken account: this client''s prorated share of the account''s conformed-cash arithmetic gap, signed, in both native currency and USD. Latest date only -- a client with reconcile_break_accounts = 0 has no rows here.';

alter table alts_holdings drop column pending_review_doc_types;
