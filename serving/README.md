# serving/

Quarkus REST API over a Postgres projection of the lakehouse gold tables
(jOOQ arrives with the first real endpoints). Will deploy via GitHub
Actions → ECR → App Runner.

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
