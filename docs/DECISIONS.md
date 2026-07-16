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
