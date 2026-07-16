# Build log

Skimmable record of what was done and why. Newest entry last.

---

## 2026-07-16 — Kickoff + Phase 0

**Done:**
- Settled the founding decisions (D-001…D-005 in DECISIONS.md): all three feed formats in Phase 1; portfolios seeded from SEC 13F filings; Quarkus + jOOQ for serving; a small real reference-data slice; serving on real AWS provisioned by Terraform.
- Cloud accounts set up: AWS and Databricks Free Edition.
- Phase 0 scaffolding: monorepo layout (`ingest/ spark/ reference/ serving/ alts-hitl/ infra/ docs/`), `infra/docker-compose.yml` (Postgres 16, volume-backed, healthcheck, loopback-only port binding), `Makefile` (`up/down/psql/logs/status/clean/help`), `.env.example` + `.gitignore`, README with architecture diagram and phase table, the four docs/ files, `git init`.
- Verified: `make up` brings Postgres 16 to healthy; `psql` connects and answers queries.

- Published to GitHub. Engineering conventions adopted from here on: feature branches merged via PRs (no direct commits to main), tests with every component, CI (lint + tests) arriving with the first code in Phase 1.
- Enabled strict branch protection on `main` (no admin bypass) and verified it: a direct push is rejected; changes land only through pull requests.

**Notes:**
- The compose file publishes Postgres on `127.0.0.1` only — a dev database with default credentials should not be reachable from any network, whatever the host firewall allows.
- `make down` keeps the data volume; only `make clean` deletes it. The stop-working / destroy-state distinction is deliberate.

## 2026-07-16 — Phase 1 starts: Python scaffolding, CI, canonical model

**Done:**
- `ingest/` is now a uv-managed Python 3.12 package (src layout, lockfile committed); ruff + pytest wired in, `make test|lint|fmt` at the root (D-008).
- **CI arrives with the first line of code**: GitHub Actions runs format check, lint, and tests on every PR and on main.
- Canonical model v1 (Pydantic, immutable, Decimal-only money): `SecurityIdentifier` (per-scheme shape checks + ISIN Luhn checksum helper), `Money`, `Account`, `Position`, `Transaction`, `CashBalance`, `HoldingsStatement`, `CashStatement`. Models validate shape, never business sense (D-009) — defective data must reach the data-quality layer, not crash at the boundary.
- 10 tests documenting the guarantees: exact Decimal arithmetic, immutability, unknown-field rejection, mistyped-ISIN-carried-but-flagged, missing-cost-basis representable.
- Repo hygiene: `.editorconfig`, `.gitattributes` (LF normalisation across OSes).
- PR #2 merged with the first green CI run; branch protection extended to require the `ingest` status check.

## 2026-07-16 — Seed book + semt.002 render/parse (Phase 1, second slice)

- `book.py`: deterministic seed portfolio — 10 real securities with checksum-valid ISINs, plausible static prices, deliberately sparse cost basis (gaps are normal, not only defects).
- `formats/semt002.py`: ISO 20022 custody-statement subset, rendered and parsed (D-010 records where the spec-fidelity line is drawn and why). Parsers raise `FeedParseError` only for structurally unreadable input; implausible-but-parseable data flows through per D-009.
- Round-trip tests prove renderer and parser agree — including the honest gap: this format subset doesn't carry cost basis, so the field round-trips to None, exactly the kind of cross-feed inconsistency reconciliation exists for.
- 20 tests total, all green.
