# serving-dotnet/

The internal API (`/internal/**`) implemented a second time, in ASP.NET Core
on .NET 10. It serves the same contract as the Java service in
[`serving/`](../serving/), against the same Postgres, and the
[parity suite](../parity/) holds the two to the same answers (D-093).

Production runs the Java service. This one is built, tested and compared on
every pull request, and runs locally.

## Endpoints

```
POST /internal/auth/login                 # password -> signed session cookie
POST /internal/auth/logout
GET  /internal/auth/session               # 204 if the cookie is still good

GET  /internal/alts/queue[?status=]       # the review queue
GET  /internal/alts/queue/{id}
GET  /internal/alts/documents/{fund}/{document}   # the source PDF
POST /internal/alts/queue/{id}/approve    # accept the extraction as read
POST /internal/alts/queue/{id}/correct    # record the reviewer's fields

GET  /internal/tenants/{tenant}/dq-metrics
GET  /internal/tenants/{tenant}/cde-registry
GET  /internal/tenants/{tenant}/slo-attainment

GET  /healthz                             # liveness, not gated
```

Every `/internal/**` request must carry the `X-Parvum-Internal` header (403
without it) and, apart from login and logout, a valid session cookie (401
without it). The gate runs before routing, so a path that does not exist is
refused the same way as one that does.

## The files

| File | What is in it |
|---|---|
| `Program.cs` | Configuration, the gate, and every endpoint. Read this first |
| `SessionToken.cs` | The signed token, in the exact format the Java service issues |
| `Stores.cs` | The two interfaces the endpoints depend on, and tenant-to-schema mapping |
| `PostgresStores.cs` | The seven SQL statements, and the one transaction scope they share |
| `Models.cs` | The JSON shapes, which are the contract with the internal app |

## What it deliberately does not do

- **It owns no schema.** The Java service's Flyway migrations create every
  table. Start that service once against a database before pointing this one
  at it.
- **It has no ORM.** One dependency, the Postgres driver. Each query is SQL in
  a string and each row is read by position, so a reviewer sees exactly what
  runs.
- **It does not serve `/tenants/**`.** The client-facing read endpoints exist
  only in Java.

## Deciding an item

Approve and correct each run one statement that checks the item is still
pending, records the decision and writes the audit row. Because the check is
in the `UPDATE`'s `WHERE` clause, two reviewers deciding the same item at the
same moment cannot both succeed. The parity suite sends twenty simultaneous
approvals to prove it.

## Running

Only Docker is needed; the .NET SDK is not assumed on the machine.

```
make internal-api-test    # build + 52 unit tests, inside the SDK image
make internal-api-run     # serve on :8081 against the local Postgres (make up)
make parity               # compare with the Java service, end to end

PARVUM_INTERNAL_API=http://localhost:8081 make internal-dev   # the React app, on .NET
```

## Configuration

| Setting (environment variable) | Meaning |
|---|---|
| `ConnectionStrings__Parvum` | Postgres connection string. Required |
| `Parvum__Internal__Password` | The login password. Required; no default |
| `Parvum__Internal__SessionSecret` | Key that signs session tokens. Required; must equal the Java service's for cookies to interchange |
| `Parvum__Tenants` | Comma-separated tenant ids, e.g. `aldergate,stonefield` |
| `Parvum__Internal__DemoPassword` | The public demo credential (D-059). Defaults to `parvum-showcase` |
| `Parvum__Internal__CookieSecure` / `CookieSameSite` | `true` / `None` by default; `false` / `Lax` for plain-http local use |
| `Parvum__Cors__Origins` | Comma-separated origins allowed to send the cookie cross-site |
