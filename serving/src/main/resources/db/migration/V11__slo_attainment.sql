-- Service levels, measured (D-075).
--
-- Two changes, and they must land together with the gold change that causes
-- them. The exporter selects every column of a source table and inserts by
-- name, so a gold column with nowhere to land fails the export loudly (the
-- lesson D-071 records): `governance_cde_registry` gaining three columns is
-- not "additive" on its own — additive is a property of the producer and the
-- consumer together.
--
-- Unscoped, like dq_metrics (V4) and cde_registry (V9): these describe the
-- pipeline every firm's data flows through, not any one firm's clients, so
-- the same rows load into every tenant schema. Same tradeoff, same reason,
-- and at seven rows the cost is nil.
--
-- String columns are varchar (unbounded) rather than text for the reason V1
-- gives: jOOQ generates its classes by reading this DDL through an in-memory
-- H2, where text is a non-indexable CLOB and a primary key over it fails to
-- build.

-- The register now carries the machine-readable half of each service level,
-- which is what makes attainment computable in the lakehouse without a second
-- landed file to keep in step with the first.
alter table cde_registry add column slo_objective varchar;
alter table cde_registry add column slo_attainment_objective numeric(14, 6);
alter table cde_registry add column slo_window_days integer;

comment on column cde_registry.slo_objective is
    'What the service level promises, in one sentence.';
comment on column cde_registry.slo_attainment_objective is
    'The share of measured days on which the SLO''s metric must have passed.';
comment on column cde_registry.slo_window_days is
    'Trailing window, in calendar days, that the service level is judged over.';

create table slo_attainment (
    slo                  varchar not null,
    objective            varchar not null,
    measured_by          varchar not null,
    target               varchar not null,
    attainment_objective numeric(14, 6) not null,
    window_days          integer not null,
    window_start         date not null,
    window_end           date not null,
    days_measured        integer not null,
    days_met             integer not null,
    attainment           numeric(14, 6) not null,
    -- Nullable on purpose, and the nullability is the point: too little
    -- history to judge is not the same as passing. A metric published as a
    -- single as-of-now row rather than a daily series lands here.
    meets_objective      boolean,
    insufficient_history boolean not null,
    error_budget_days    numeric(14, 2) not null,
    budget_consumed_days integer not null,
    -- Also nullable, for a different reason: an objective of 1.0 has no error
    -- budget by construction, and a budget that does not exist cannot be
    -- part-spent. Reporting 0% or 100% there would both be lies.
    budget_remaining_pct numeric(14, 6),
    rebuilt_at           timestamptz not null,
    primary key (slo)
);
comment on table slo_attainment is
    'Attainment and error-budget consumption for every named service level in the CDE register, over the trailing window each one declares. One row per service level. Objectives come from the register; the evidence comes from dq_metrics. Identical across every tenant schema — see the note above for why.';
