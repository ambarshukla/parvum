# parity/

Holds the two implementations of the internal API — Java
([`serving/`](../serving/)) and ASP.NET Core
([`serving-dotnet/`](../serving-dotnet/)) — to one contract (D-093).

```
make parity
```

That builds both services, starts them against one throwaway Postgres, seeds
it, sends each service the same requests, and exits non-zero if any answer
differs. Only Docker is needed. The first run takes a few minutes because it
builds the Java image.

## What is compared

| Area | Checks |
|---|---|
| The gate | Missing header → 403 and missing session → 401, for real and nonexistent routes; a forged cookie |
| Login | Wrong, empty, real and demo passwords; cookie attributes; **a cookie from either service works on the other**; logout |
| Operations views | `dq-metrics`, `cde-registry`, `slo-attainment` row for row, in order; unknown and malformed tenants |
| Queue reads | The list, each status filter, single items, missing and non-numeric ids, the PDF's bytes and headers |
| Decisions | Approve and correct on twin rows: same answer, same audit row; a second decision → 409; malformed corrections → 400 |
| Concurrency | Twenty simultaneous approvals of one item: exactly one accepted, exactly one audit row |

## How writes are compared

A read can be sent to both services and the answers compared directly. A write
cannot: the second service would find the row already decided. So each write
case seeds two identical rows, decides one through each service, and compares
the responses with the fields that are meant to differ (ids, timestamps)
removed, then compares the audit rows each left in the database.

## What "the same" means

Values, not text. The two runtimes print `0.850` and `0.85`, and the same
instant with different fractional digits; both are parsed before comparing, so
only a genuinely different number or time is a failure.

## Files

- `compose.yml` — Postgres, both services, and the runner. Nothing is
  published to the host; the credentials exist only inside this network.
- `parity.py` — the seed data and every check, top to bottom.
- `Dockerfile` — the runner image: Python and a Postgres driver.
