-- Alts NAV becomes part of the headline wealth number (D-060): client_wealth
-- gains alts_usd, additive so it does not disturb V1-V4 (Flyway checksums an
-- already-applied migration; editing one breaks every environment that has
-- run it). A new table, alts_holdings, projects gold_alts_holdings -- the
-- detail behind that number. Like V1-V4 this is unqualified and rebuilt by
-- the exporter (truncate-and-reload); `default 0` only matters for the ALTER
-- itself succeeding against whatever rows already exist before the next
-- reload overwrites them.
--
-- String columns are varchar (unbounded) for the same reason as V1: jOOQ
-- reads this DDL through an in-memory H2 to generate its classes, where text
-- is a non-indexable CLOB and the primary key below would fail to build.

alter table client_wealth add column alts_usd numeric(24, 2) not null default 0;
comment on column client_wealth.alts_usd is
    'Owner-prorated private-fund NAV in USD, forward-filled from the most recent confirmed capital account statement; 0 before a client''s first confirmed statement or if they hold no alts fund.';

create table alts_holdings (
    client_id                varchar        not null,
    client_name               varchar        not null,
    fund_id                   varchar        not null,
    fund_name                 varchar        not null,
    account_id                varchar        not null,
    inception_date            date,
    as_of                     date,
    total_commitment_usd      numeric(24, 2) not null,
    called_to_date_usd        numeric(24, 2) not null,
    distributed_to_date_usd   numeric(24, 2) not null,
    unfunded_commitment_usd   numeric(24, 2) not null,
    current_nav_usd           numeric(24, 2) not null,
    moic                      numeric(14, 6),
    pending_review_documents  integer        not null,
    rebuilt_at                timestamptz    not null,
    primary key (client_id, fund_id)
);
comment on table alts_holdings is
    'Owner-prorated private-fund holdings, one row per (client, fund): commitment, capital called and distributed to date, unfunded commitment, current NAV, and MOIC. Only confirmed documents are reflected -- pending_review_documents counts what is deliberately left out.';
