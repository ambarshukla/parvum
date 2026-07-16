# Decisions (ADR-lite)

Append-only. Format: context / choice / why / alternatives. Newest last.

---

## D-001 · 2026-07-16 · Phase 1 covers all three feed formats

- **Context:** the plan lists semt.002 + MT535 + camt.053 for Phase 1; starting with fewer parsers was considered as a smaller first slice.
- **Choice:** build all three in Phase 1.
- **Why:** the point of the phase is the multi-format story — the *same* portfolio expressed in three wire formats, parsed to one common model; doing it in one pass keeps that comparison honest.
- **Alternatives:** semt.002 + MT535 first with camt.053 as a fast follow; semt.002 alone.

## D-002 · 2026-07-16 · Seed portfolios from real SEC 13F filings

- **Context:** synthetic positions can be random tickers or modelled on real institutional books.
- **Choice:** seed from 13F-HR filings of 2–3 well-known filers.
- **Why:** positions look like a real book rather than noise; the EDGAR pull doubles as proof of the scheduled-fetch path; public-domain data, small volume.
- **Alternatives:** fully synthetic (simpler, looks artificial); defer 13F until the fetch path exists.

## D-003 · 2026-07-16 · Quarkus + jOOQ for the serving layer

- **Context:** the serving stack could be Quarkus or Spring Boot; either works with jOOQ.
- **Choice:** Quarkus + jOOQ.
- **Why:** fast startup and low memory in containers (with native image as a further option), which directly cuts hosting cost; jOOQ keeps the SQL explicit and reviewable instead of hidden behind an ORM — in a data platform, the queries *are* the product.
- **Alternatives:** Spring Boot + jOOQ (larger ecosystem, heavier footprint).

## D-004 · 2026-07-16 · Reference data = small real slice

- **Context:** the securities master could be invented, a small real slice, or a bulk pull.
- **Choice:** real data for ~50–100 securities: OpenFIGI mappings + SEC ticker/CIK + a handful of GLEIF LEIs.
- **Why:** real identifier-mapping pain at trivial volume, licence-safe; a fully synthetic master would mean reconciling against invented data.
- **Alternatives:** fully synthetic; full GLEIF golden copy (more scale, little extra value here).

## D-005 · 2026-07-16 · Serving runs on real AWS via Terraform; PaaS dropped

- **Context:** the original plan hosted the live site on a PaaS (Railway) with Terraform merely *describing* an AWS production target that would never be applied. Expected usage is tiny (a single owner plus occasional demos), so cost is not the binding constraint.
- **Choice:** RDS Postgres `db.t4g.micro` + AWS App Runner for the Quarkus container, frontend on Vercel free, all provisioned by Terraform. Deploy path: GitHub Actions → ECR → App Runner.
- **Why:** infrastructure-as-code that is never applied is fiction; running the real thing keeps the Terraform honest, uses one cloud instead of two, and App Runner covers the PaaS conveniences (public TLS endpoint, no load balancer to manage).
- **Alternatives:** Railway as planned (simplest ops, Terraform stays unapplied); hybrid PaaS + apply/destroy AWS demo cycles (two platforms to maintain).
- **Guardrails:** AWS budget alert before the first resource; no NAT gateway, no ALB, no always-on Aurora Serverless — each is a fixed monthly cost the workload doesn't justify. Verify App Runner availability on the account's plan before writing Terraform; fall back to ECS Fargate.

## D-006 · 2026-07-16 · External data fetching runs on GitHub Actions

- **Context:** Databricks Free Edition serverless compute has a restricted outbound-internet allowlist, so pipeline jobs cannot call external sources (SEC EDGAR, price APIs) directly. Something with open egress must fetch data and land it where Databricks can read it.
- **Choice:** GitHub Actions cron workflows on GitHub-hosted runners in this repo, pushing raw files into a Unity Catalog volume via the Databricks CLI/REST API. Databricks Workflows still schedules all lakehouse processing.
- **Why:** zero standing infrastructure and zero cost (free minutes for public repos); cron, secrets management, and run logs are built in; the fetch code lives beside the rest of the codebase and works from day 1 — before any AWS infra exists.
- **Alternatives:** fetching from Databricks Workflows directly (blocked by the egress restriction); AWS EventBridge Scheduler + Lambda (the cloud-native equivalent — viable, but requires AWS infra and Terraform earlier than needed; a reasonable later migration); an always-on personal machine (unreliable).

## D-007 · 2026-07-16 · Environments: local dev + CI + one live environment; no standing staging

- **Context:** production platforms typically run dev/staging/prod. This is a solo-maintained reference build with demo-scale traffic and no users at risk.
- **Choice:** three layers — local Docker dev (Postgres pinned to the RDS major version), CI on every PR (lint + tests, required before merge), and a single live AWS environment.
- **Why:** a standing staging stack would roughly double infra cost and maintenance for no risk reduction that CI + local parity doesn't already provide at this scale.
- **Alternatives:** permanent staging (cost/upkeep unjustified); ephemeral staging via Terraform workspaces — documented as the scale-up path: the same modules can stand up an identical stack briefly, then destroy it.

## D-008 · 2026-07-16 · Python toolchain: uv + ruff + pytest + Pydantic, pinned to 3.12

- **Context:** the first Python code (ingest/) needs environment management, linting, and testing that behave identically on a dev machine and in CI; the canonical model carries untrusted feed data.
- **Choice:** `uv` for environments + lockfile, `ruff` for lint + format, `pytest` for tests, Pydantic v2 for models. Python pinned to 3.12 via `.python-version` to stay close to Databricks serverless runtimes.
- **Why:** uv is a single fast binary with lockfile-first discipline; ruff replaces three legacy tools; Pydantic validates every record on construction — load-bearing in a data-quality project, not a convenience.
- **Alternatives:** pip + venv + requirements.txt (no lockfile discipline); Poetry (heavier, slower); dataclasses/attrs for models (no validation).

## D-009 · 2026-07-16 · Models validate shape, not sense

- **Context:** where should bad data be rejected? Feeds deliberately contain defects (missing cost basis, mistyped ISINs, implausible dates) that the reconciliation and data-quality layers exist to catch.
- **Choice:** the canonical model enforces *shape* only — types, formats, required fields (e.g. an ISIN must look like an ISIN). Business plausibility stays representable: checksum validity is a helper method (`has_valid_checksum`), cost basis is optional, no cross-field date rules.
- **Why:** rejecting defective data at parse time destroys the evidence the platform's whole value chain (detect → route → resolve → audit) is built on. The boundary guarantees integrity of *representation*; downstream layers judge *quality*.
- **Alternatives:** strict parse-time validation (simpler, but the wrong layer owns the rules); no validation anywhere (silent corruption).

## D-010 · 2026-07-16 · Wire formats as spec-shaped subsets, XSD validation deferred

- **Context:** full ISO 20022 messages are enormous (hundreds of optional elements, deep nesting); our model carries a focused field set. Somewhere between "toy XML" and "schema-perfect" a line must be drawn.
- **Choice:** renderers/parsers use the real message structure and element names for the fields we carry (e.g. `SctiesBalCtdyRpt`, `BalForAcct/FinInstrmId/ISIN`, `AcctBaseCcyAmts/HldgVal/Amt`), with documented simplifications (flattened nesting where the spec stacks identical wrappers). Validation against official XSD schemas is a recorded backlog item, not silently skipped.
- **Why:** the learning and the parsing work are genuine at subset fidelity; schema-perfect output would consume days on optional elements nothing downstream reads. Honesty is preserved by documenting the line (module docstrings) rather than pretending.
- **Alternatives:** full schema fidelity + XSD validation now (high cost, low marginal value); invented XML tags (would falsify the "real formats" premise).
