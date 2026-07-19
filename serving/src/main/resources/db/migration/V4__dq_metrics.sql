-- The DQ metrics rollup, projected from gold_dq_metrics (spark/dq_recon.py,
-- D-043). Like V1-V3 this is rebuilt by the exporter and unqualified.
--
-- Unlike every other projection, this data is NOT scoped to one advisory
-- firm's clients — it's a fact about the whole pipeline (freshness,
-- completeness, accuracy, exceptions), identical across every tenant by
-- construction. Rather than build a second, non-tenant schema-management
-- path for one small table, it is deliberately duplicated into every tenant
-- schema through the same Flyway/exporter machinery every other table
-- already uses — the smaller, more honest cost for a dataset this size.
-- The API and dashboard read it from whichever tenant happens to be
-- selected; it would show the same rows regardless.
--
-- String columns are varchar (unbounded) for the same reason as V1: jOOQ
-- reads this DDL through an in-memory H2 to generate its classes, where
-- text is a non-indexable CLOB and a primary key over it would fail to build.

create table dq_metrics (
    as_of      date           not null,
    dimension  varchar        not null check (dimension in ('freshness', 'completeness', 'accuracy', 'exceptions')),
    metric     varchar        not null,
    value      numeric(14, 6) not null,
    passed     boolean,
    detail     varchar        not null,
    rebuilt_at timestamptz    not null,
    primary key (as_of, dimension, metric)
);
comment on table dq_metrics is
    'Declarative DQ rollup: one row per (date, dimension, metric) across freshness/completeness/accuracy/exceptions. passed is NULL for exceptions metrics (trend data, not pass/fail). Identical across every tenant schema — see the note above for why.';
