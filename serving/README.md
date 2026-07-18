# serving/

Quarkus REST API over a Postgres projection of the lakehouse gold tables,
querying through jOOQ. Will deploy via GitHub Actions → ECR → App Runner.

## Endpoints

Read-only, one advisory firm (tenant) per path prefix:

```
GET /tenants/{tenant}/wealth      # headline wealth per client (latest date)
GET /tenants/{tenant}/allocation  # asset-class breakdown (latest date)
GET /tenants/{tenant}/income      # monthly income series
GET /tenants/{tenant}/holdings    # top holdings (latest date)
```

`{tenant}` is `aldergate` or `stonefield`; an unknown one is a 404. Each
request resolves to that tenant's schema via a `SET LOCAL search_path`
(see `TenantQuery`), so a query never names a schema and never crosses one.

## jOOQ

The typed query classes are generated at build time from the Flyway
migrations by jOOQ's `DDLDatabase` — no database runs during codegen, and
the migration is the one schema source of truth (D-030). Generated sources
live in `target/` and are regenerated every build (never committed). The
`DSLContext` renders tables unqualified (`renderSchema=false`) so one
generated set of classes serves every tenant schema.

## Multi-tenancy

Schema-per-tenant: each advisory firm gets its own Postgres schema with an
identical layout, migrated by Flyway at startup (`TenantSchemas`). Two
fictional firms exercise the model:

- `tenant_aldergate` — Aldergate Wealth Management (advises the Hartwell family)
- `tenant_stonefield` — Stonefield Family Office (advises Okafor and Reyes)

`tenant_template` holds no data; it is the canonical schema jOOQ code
generation will read, with the real tenant schema substituted at render time.

## Building

```
make serving-test   # mvn verify: compile + tests + format check
make serving-fmt    # spotless: fix formatting
```

Needs a JDK 21 (`JAVA_HOME` or on PATH) and a running Docker daemon — tests
boot the app against a throwaway Postgres 16 container via Quarkus Dev
Services. Maven itself is downloaded by the committed wrapper (`./mvnw`).
Dev mode (`./mvnw quarkus:dev`) targets the docker-compose Postgres from
`make up`.

## Loading data

`make export-gold` (the `export/` package) fills the tenant schemas from the
lakehouse gold tables — start this app once first so Flyway has created
them. Flyway owns the DDL; the exporter only truncates and reloads (D-029).
