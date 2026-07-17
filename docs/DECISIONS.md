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

## D-011 · 2026-07-16 · Raw landing layout and generation policy

- **Context:** the generator turns from library into data factory; the layout and corruption policy shape everything downstream.
- **Choice:** (a) Hive-style `date=YYYY-MM-DD/` directories so Spark partition-prunes naturally; (b) business days only; (c) the two holdings renditions (semt.002, MT535) are corrupted **independently** — the same day's views genuinely disagree sometimes, which is what cross-feed reconciliation exists to catch; (d) everything derives deterministically from the calendar date, so any historical day regenerates byte-identically; (e) ground-truth manifests are written **outside** the raw landing directory — the pipeline must never read them; only detection-quality evaluation may.
- **Why:** each choice removes a future argument: pruning comes free, weekends don't fake volume, cross-format breaks exist by construction, investigations can reproduce any file exactly, and the DQ layer can't accidentally cheat.
- **Alternatives:** flat directories (no pruning); same corruption for both holdings formats (reconciliation would only ever catch format-coverage gaps); random non-reproducible corruption (untestable).

## D-012 · 2026-07-17 · CI authenticates to Databricks with a personal access token

- **Context:** the scheduled delivery job must authenticate to Databricks with no human present. Local dev uses a cached OAuth browser login (user-to-machine), which by definition needs a person. Machine auth offers two routes: a **personal access token** (PAT) tied to my user, or **OAuth machine-to-machine** against a **service principal** (client id + secret).
- **Choice:** a PAT, stored as a GitHub Actions repository secret alongside the workspace host. Verified end to end before committing: token creation is enabled on Free Edition, and `make land` uploads successfully with `DATABRICKS_AUTH_TYPE=pat` forced (so a cached OAuth session could not mask a failure).
- **Why:** it works on Free Edition today, needs one secret and no second identity to manage, and keeps the CI upload command byte-identical to the local one. The tradeoff is real and worth stating plainly: a PAT is a long-lived bearer credential carrying **my user's full permissions**, which is strictly weaker than a scoped service principal. It is acceptable *here* because the workspace holds nothing but synthetic data, and it is the only credential in play.
- **Mitigations:** create it with a bounded lifetime (~90 days) and rotate; GitHub masks secret values in run logs; a scheduled run failing on expiry is loud (GitHub emails on failed scheduled workflows), which is the right failure mode — better a broken job than an immortal credential.
- **Alternatives:** *OAuth M2M service principal* — the correct answer once anything real is at stake: a non-human identity, scoped, revocable without disturbing my own login. Rejected for now because Free Edition's service-principal support is unverified and it buys nothing at this scale; this is the documented upgrade path. *OIDC workload-identity federation* — no stored secret at all, the ideal end state; Databricks supports it for service principals on some tiers, unverified here and moot until a service principal exists.

## D-013 · 2026-07-17 · Bronze runs on a file-arrival trigger, defined as a bundle

- **Context:** landing files was automated (D-006), but parsing them into bronze still required a human to open the notebook and run it — half a pipeline. Automating it raises two separate questions: *what starts the job*, and *how the job is defined*.
- **Choice (what starts it):** a **file-arrival trigger** watching `/Volumes/workspace/parvum/landing/raw/`, with `wait_after_last_change_seconds: 60` and `min_time_between_triggers_seconds: 300` — not a cron.
- **Why:** a timer would have to *guess* the gap between the feed landing and the job starting, and guessing wrong is silent — the job runs, finds nothing, reports success, and the data is simply a day late. The trigger follows the data instead of a clock, so the fetch schedule can move without anything downstream needing to know. The `wait_after_last_change` window coalesces a three-file delivery into one run rather than three; `min_time_between_triggers` is a floor on frequency, protecting a free-tier compute quota from a pathological upload loop. Verified by real firing before being committed to, not merely accepted by the API.
- **Choice (how it's defined):** a **Databricks Asset Bundle** (`databricks.yml`) deployed with `make deploy-job`, with the job pulling code via `git_source` from `main` rather than from bundle-synced files.
- **Why:** a job clicked together in the Workflows UI is invisible to review, unreproducible, and absent from git — the same objection as un-applied Terraform in D-005. As for `git_source`: the notebook imports the repo's own parsers through a relative path (`../ingest/src`), so it needs the whole repo tree, not just `spark/`; a checkout gives it exactly the layout it already expects. And because `main` is branch-protected and CI-gated, "the job runs `main`" *already has* a review gate in front of it — a separate code-deploy step would add ceremony without adding control. File sync is switched off (`sync: paths: []`) so the deploy carries the job definition alone, leaving no third copy of the code to wonder about.
- **Alternatives:** *Quartz cron ~07:00 UTC* (simple and predictable, but couples to the fetch's timing and fails silently when that assumption breaks); *bundle-synced files* (the canonical bundle pattern, and the right answer if the job's code ever diverges from the repo layout — but here it would deploy a third copy of code that git already versions and CI already gates); *the UI* (rejected: not code); *Lakeflow/DLT declarative pipelines* (a heavier abstraction than a single idempotent notebook needs today).
- **Note:** the trigger fires on arrival, so it will not reprocess the 65 days already in the volume — history was loaded by the runs that preceded it, and the registry anti-join makes that distinction moot anyway.
