-- Projection of the lakehouse gold layer. The lakehouse stays the system of
-- record; every table here is rebuilt by the exporter (truncate-and-reload),
-- so nothing originates in Postgres and losing it costs one reload.
--
-- Tables are deliberately unqualified: the same migration set runs once per
-- tenant schema (see TenantSchemas), which is what schema-per-tenant means —
-- identical layout, disjoint data, isolation enforced by the schema boundary.
--
-- String columns are `varchar` (unbounded), not `text`. In PostgreSQL the two
-- are the same type; `varchar` is chosen because jOOQ generates its typed
-- classes by interpreting this DDL in an in-memory H2 database, where `text`
-- becomes a non-indexable CLOB and the primary keys below would fail to build.

create table client_wealth (
    as_of            date           not null,
    client_id        varchar        not null,
    client_name      varchar        not null,
    positions_usd    numeric(24, 2) not null,
    cash_usd         numeric(24, 2) not null,
    total_wealth_usd numeric(24, 2) not null,
    fx_rate_used     numeric(12, 6) not null,
    fx_rate_date     date           not null,
    books_reconcile  boolean        not null,
    rebuilt_at       timestamptz    not null,
    primary key (client_id, as_of)
);
comment on table client_wealth is
    'Per client per day: owner-prorated positions + cash in USD; the headline number is total_wealth_usd. fx_rate_date earlier than as_of means a carried-forward rate (labelled, not hidden).';

create table asset_allocation (
    as_of       date           not null,
    client_id   varchar        not null,
    client_name varchar        not null,
    asset_class varchar        not null,
    value_usd   numeric(24, 2) not null,
    weight      numeric(12, 10) not null,
    rebuilt_at  timestamptz    not null,
    primary key (client_id, as_of, asset_class)
);
comment on table asset_allocation is
    'Per client per day per asset class: owner-prorated USD value and weight (weights per client-day sum to 1). ''Cash'' and ''Unknown'' are real classes, kept visible.';

create table income (
    client_id   varchar        not null,
    client_name varchar        not null,
    month       date           not null,
    type        varchar        not null check (type in ('DIVIDEND', 'INTEREST')),
    income_usd  numeric(24, 2) not null,
    movements   integer        not null,
    rebuilt_at  timestamptz    not null,
    primary key (client_id, month, type)
);
comment on table income is
    'Per client per calendar month (month = first day) per income type: owner-prorated USD income and the number of underlying cash movements. Income only — fees and trades are flows.';

create table top_holdings (
    as_of           date           not null,
    client_id       varchar        not null,
    client_name     varchar        not null,
    rank            integer        not null check (rank between 1 and 10),
    security_name   varchar        not null,
    security_scheme varchar        not null,
    security_id     varchar        not null,
    asset_class     varchar        not null,
    owned_usd       numeric(24, 2) not null,
    weight          numeric(12, 10) not null,
    rebuilt_at      timestamptz    not null,
    primary key (client_id, rank)
);
comment on table top_holdings is
    'Per client: top 10 positions by owned USD value on the latest date. Weight is the share of the client''s positions value (conventional holdings-report basis), not total wealth.';
