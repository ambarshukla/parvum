-- The alts HITL review queue and its audit trail (D-050/D-051). Firm-ops
-- data, not tenant data -- no advisory firm owns a review decision, the
-- firm's own back-office does -- so this lives in the single non-tenant
-- "internal" schema (InternalSchema), migrated separately from the
-- per-tenant set every other table here belongs to.
--
-- String columns are varchar (unbounded), not text, for the same reason as
-- the tenant migrations: jOOQ reads this DDL through an in-memory H2 to
-- generate its classes, where text is a non-indexable CLOB and the unique
-- constraint below would fail to build.
--
-- extracted_fields/decided_fields are jsonb rather than a fixed wide table:
-- the field set differs by doc_type (a capital call and a capital account
-- statement share almost no columns), the same reasoning
-- bronze_alts_extractions.fields_json already used on the Databricks side.
--
-- decided_by is deliberately absent: this app has one shared credential,
-- not per-user accounts (D-046), so there is no real identity to record
-- yet. Recording a constant string here would look like accountability
-- this system doesn't actually have. Add it if/when the auth model grows
-- real per-user accounts.

create table alts_review_queue (
    id                bigserial      primary key,
    fund_id           varchar        not null,
    document          varchar        not null,
    doc_type          varchar        not null,
    sequence_number   int,
    period_end        date,
    extracted_fields  jsonb          not null,
    confidence        numeric(4, 3)  not null,
    validation_notes  varchar,
    status             varchar       not null default 'pending',
    decided_fields     jsonb,
    decided_at         timestamptz,
    synced_at          timestamptz,
    loaded_at          timestamptz   not null default now(),
    unique (fund_id, document)
);
comment on table alts_review_queue is
    'Documents silver_alts_documents routed to needs_review, loaded from Databricks. status moves pending -> approved|corrected once a reviewer decides; synced_at is set once the reverse-sync has landed the decision back into the lakehouse.';

create table alts_review_audit (
    id            bigserial    primary key,
    queue_id      bigint       not null references alts_review_queue (id),
    action        varchar      not null,
    before_fields jsonb        not null,
    after_fields  jsonb        not null,
    decided_at    timestamptz  not null default now()
);
comment on table alts_review_audit is
    'Append-only: one row per review decision, never updated or deleted -- the audit trail a HITL workflow exists to provide.';
