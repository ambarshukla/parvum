-- The Critical Data Element register, projected from governance_cde_registry
-- (spark/dq_recon.py, D-068), plus room in dq_metrics for the governance
-- dimension the same change introduced.
--
-- Like dq_metrics (V4) this is NOT scoped to one advisory firm's clients: it
-- describes the pipeline every firm's data flows through, so the same rows
-- are loaded into every tenant schema through the same exporter machinery.
-- The same tradeoff, taken for the same reason, at a similar size (~300 rows).
--
-- String columns are varchar (unbounded) rather than text for the reason V1
-- gives: jOOQ generates its classes by reading this DDL through an in-memory
-- H2, where text is a non-indexable CLOB and a primary key over it fails to
-- build.

-- V4 pinned the dimension set with an inline check, which is exactly why the
-- new dimension could not slip in unnoticed — the export would have failed on
-- the constraint. Extending it deliberately is the right way through.
--
-- `if exists` is not defensiveness about Postgres, where an inline column
-- check is reliably named <table>_<column>_check. It is for jOOQ's code
-- generator, which replays this DDL through an in-memory H2 that does not
-- give the V4 constraint that name; without `if exists` codegen fails before
-- it ever reaches the part it actually needs, which is the new table below.
-- The real drop is proven where it matters — an export test inserts a
-- 'governance' row against a real Postgres migrated with this DDL.
alter table dq_metrics drop constraint if exists dq_metrics_dimension_check;
alter table dq_metrics add constraint dq_metrics_dimension_check
    check (dimension in ('freshness', 'completeness', 'accuracy', 'exceptions', 'governance'));

create table cde_registry (
    table_name         varchar not null,
    column_name        varchar not null,
    layer              varchar not null,
    description        varchar not null,
    -- Nullable on purpose: the register covers every column the platform
    -- publishes, including any not yet classified. The CI gate keeps that
    -- set empty, and columns_classified_rate measures it independently
    -- rather than taking the producer's word for it.
    tier               varchar,
    owner              varchar,
    definition         varchar,
    -- Comma-joined rather than an array: this table exists to be read, and
    -- an array type stops the exporter's wire-format conversion dead.
    -- quality_rule_count carries what the flattening would otherwise cost.
    quality_rules      varchar,
    quality_rule_count integer not null,
    control_gap        varchar,
    slo                varchar,
    slo_measured_by    varchar,
    slo_target         varchar,
    rebuilt_at         timestamptz not null,
    primary key (table_name, column_name)
);
comment on table cde_registry is
    'The Critical Data Element register: one row per column the platform publishes, with its tier, owner, business definition, service level, and either the quality rules that test it or a stated control gap. Source of truth is governance/cde_registry.yml in the repo. Identical across every tenant schema — see the note above for why.';
