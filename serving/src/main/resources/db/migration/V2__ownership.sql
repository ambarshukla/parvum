-- The ownership graph, projected from gold_ownership. Structural, not
-- monetary: the account→client edges and whether each account is shared.
-- Like the V1 tables it is rebuilt by the exporter (truncate-and-reload) and
-- unqualified, so the same migration runs in every tenant schema.
--
-- String columns are varchar (unbounded) for the same reason as V1: jOOQ reads
-- this DDL through an in-memory H2 to generate its classes, where text is a
-- non-indexable CLOB and the primary key below would fail to build.

create table ownership (
    account_id    varchar       not null,
    client_id     varchar       not null,
    client_name   varchar       not null,
    ownership_pct numeric(9, 6) not null,
    owner_count   integer       not null,
    is_shared     boolean       not null,
    rebuilt_at    timestamptz   not null,
    primary key (account_id, client_id)
);
comment on table ownership is
    'The ownership graph: one row per (account, owning client) with the effective fraction, the number of owners on the account, and whether it is shared. Fractions per account sum to 1. A tenant sees only the edges of clients it advises — a shared account split across firms shows is_shared true even where the co-owner is not visible.';
