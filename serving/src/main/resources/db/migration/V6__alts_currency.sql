-- The alts corpus is no longer USD-only (D-061): one fund is EUR-denominated.
-- alts_holdings.*_usd columns are already converted; this adds the fund's
-- own native currency alongside them, for transparency (what did the
-- reviewer actually read on the page). Additive, like V5 -- V1-V5 are
-- already applied and Flyway checksums them, so this cannot edit V5 itself.
-- `default 'USD'` only matters for the ALTER succeeding against whatever
-- rows already exist before the next export reload overwrites them.

alter table alts_holdings add column currency varchar not null default 'USD';
comment on column alts_holdings.currency is
    'ISO 4217 currency code the fund''s own documents are denominated in -- the *_usd columns are converted from this.';
