-- Performance measurement, projected from gold_performance and
-- gold_performance_summary. Like V1/V2 this is rebuilt by the exporter
-- (truncate-and-reload) and unqualified, so the same migration runs in
-- every tenant schema.
--
-- String columns are varchar (unbounded) for the same reason as V1: jOOQ
-- reads this DDL through an in-memory H2 to generate its classes, where
-- text is a non-indexable CLOB and the primary keys below would fail to
-- build.

create table performance (
    as_of                      date           not null,
    client_id                  varchar        not null,
    client_name                varchar        not null,
    total_wealth_usd           numeric(24, 2) not null,
    external_flow_usd          numeric(24, 2) not null,
    daily_twr_return           numeric(14, 8),
    twr_index_since_inception  numeric(14, 8) not null,
    rebuilt_at                 timestamptz    not null,
    primary key (client_id, as_of)
);
comment on table performance is
    'Daily time-weighted return chain per client. daily_twr_return excludes that day''s external_flow_usd from the market-return calculation and is NULL on the client''s first date (no prior day to compare); twr_index_since_inception is the chain-linked growth-of-$1 index, 1.0 on the first date.';

create table performance_summary (
    client_id                       varchar        not null,
    client_name                     varchar        not null,
    inception_date                  date           not null,
    as_of                           date           not null,
    wealth_begin_usd                numeric(24, 2) not null,
    wealth_end_usd                  numeric(24, 2) not null,
    net_external_flow_usd           numeric(24, 2) not null,
    twr_since_inception             numeric(14, 8) not null,
    dietz_since_inception           numeric(14, 8),
    irr_since_inception_annualized  numeric(14, 8),
    rebuilt_at                      timestamptz    not null,
    primary key (client_id)
);
comment on table performance_summary is
    'One row per client: since-inception return by three methodologies (time-weighted, Modified Dietz, money-weighted IRR) — see docs/PERFORMANCE_METHODOLOGY.md for why they differ. dietz_since_inception and irr_since_inception_annualized are nullable: IRR has no root for some cash-flow shapes, and neither method is defined before a second date exists.';
