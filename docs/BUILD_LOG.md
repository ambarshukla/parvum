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

## 2026-07-16 — MT535 render/parse (Phase 1, third slice)

- `formats/mt535.py`: the same holdings statement in SWIFT's ISO 15022 style — `:16R:`/`:16S:` blocks, qualified tags (`:20C::SEME`, `:93B::AGGR`), decimal commas, and cost basis carried through a `:70E:` narrative convention (structured data smuggled through free text, as real feeds do).
- Model change: `Account.name/custodian_bic/base_currency` became optional — MT535 references accounts by id alone; descriptive attributes are reference-data enrichment (Phase 2), not message content.
- Cross-format test: one book → two formats → complementary gaps (semt.002 lacks cost basis, MT535 lacks account details) with quantities agreeing exactly — reconciliation's raw material, proven in a test before the reconciler exists.
- 27 tests, all green.

## 2026-07-16 — camt.053 render/parse; cash seed book (Phase 1, fourth slice)

- `book.py` grows `build_cash_statement`: opening/closing balances + six entries whose net movement exactly explains the balance change — the invariant (closing = opening + net) is pinned by a test, ready for defect injection to break.
- `formats/camt053.py`: ISO 20022 cash statement — OPBD/CLBD balance codes, booking vs value dates (→ trade/settlement), transaction types as proprietary bank codes (`BkTxCd/Prtry`), `CdtDbtInd` derived from type and deliberately not cross-checked on parse (D-009).
- Shared XML helpers extracted to `formats/_xml.py` (second XML format = time to stop duplicating); semt.002 refactored onto them. Namespace check moved into the shared `parse_document` — a semt.002 file fed to the camt parser is rejected by its namespace, proven in a test.
- 33 tests, all green. All three Phase 1 formats now round-trip.
- CI actions bumped to Node-24 targets (checkout@v5, setup-uv@v6) after runner deprecation warnings.

## 2026-07-16 — Defect injection with ground-truth manifest (Phase 1, fifth slice)

- `defects.py`: seven defect types, deterministic from a seed. Semantic defects corrupt the statement before rendering (missing cost basis, mistyped ISIN via check-digit bump, stale price, duplicated/dropped/settlement-shifted entries) — files that parse fine but lie. Syntactic defects corrupt the rendered text (truncation) — rejected at the parser.
- **Every injection is recorded in a manifest** (defect, target, before→after): the ground truth against which Phase 3's detection will be measured. Tests already prove defects survive the wire: a mistyped ISIN travels through semt.002 and is still flagged on the far side; a duplicated entry demonstrably breaks the closing-balance invariant after a camt.053 round trip.
- Balances are deliberately not adjusted when entries are corrupted — the broken invariant *is* the defect.
- 43 tests, all green. Feed generation for Phase 1 is complete; next: bronze landing on Databricks.

## 2026-07-16 — Generator CLI: the raw pile exists (Phase 1, sixth slice)

- `parvum-generate` CLI (`make generate`): for each business day, one delivery — semt.002 + MT535 + camt.053 — into Hive-style `date=` directories; ~90-day backfill produces 64 business days × 3 = 192 files (~1.6 MB).
- Corruption policy per D-011: each day's defect mix derives deterministically from the date; the two holdings renditions are corrupted independently, so cross-format disagreements exist by construction.
- Ground-truth manifests (checksums, sizes, every injection) land *outside* the raw directory — the pipeline can't read them; only detection evaluation may.
- Tests: weekend skipping, byte-identical regeneration, all three files parse back, ground truth out-of-band, independence of holdings corruption across 60 days. 48 tests green.

## 2026-07-16 — Raw pile landed on Databricks (Phase 1, seventh slice)

- Unity Catalog objects created in the `workspace` catalog: schema `parvum`, managed volume `landing`. The full raw pile (64 business days × 3 files) uploaded to `/Volumes/workspace/parvum/landing/raw/date=…/` via the Databricks CLI.
- `make land` re-uploads idempotently (`--overwrite`); workspace URL comes from `.env` (gitignored), with a placeholder in `.env.example`. CLI auth = OAuth browser login once, then the cached token.
- Ground-truth manifests deliberately NOT uploaded — the pipeline's environment contains only what a real one would have.
- Next: bronze notebooks — file registry + parsed bronze tables (Delta).

## 2026-07-16 — Bronze ingest notebook (Phase 1, eighth slice)

- `spark/bronze_ingest.py` (Databricks notebook source): walks the landing volume, registers every file in `bronze_file_registry` (path, format, statement date, size, sha256, status, error), parses all three formats into `bronze_holdings` / `bronze_cash_entries` / `bronze_cash_balances` — **reusing the repo's own parsers** via a Databricks Git folder (`sys.path` to `../ingest/src`).
- Idempotent (anti-join against the registry; registry written last so a mid-run crash reprocesses cleanly); parse failures are recorded as FAILED rows, not fatalities; every bronze row carries `file_path` lineage.
- Driver-side parsing, deliberately: hundreds of small files don't need distribution — the `mapInPandas` scale-up is a recorded later exercise.

## 2026-07-17 — Scheduled daily delivery (Phase 1, ninth slice)

- `.github/workflows/daily-feeds.yml`: weekdays at 06:15 UTC, generate the day's delivery and land it in the Unity Catalog volume — the fetch/process split (D-006) now running on a timer rather than by hand. Synthetic feeds ride the route today; Phase 2's real EDGAR pull joins the same one, so the mechanism is proven before it carries anything that matters.
- **CI runs the same two commands a laptop runs** — `make generate` and `make land`, unchanged. `DAYS`/`END` became Makefile variables whose `?=` defaults yield to the environment, so the workflow sets `DAYS: 1` and no CI-only code path exists to drift. The same knobs give `workflow_dispatch` a replay button: re-running a date is safe because generation is byte-identical per date (D-011).
- **Auth: PAT, chosen with eyes open (D-012).** Verified before committing rather than after: token creation *is* enabled on Free Edition, and `make land` was run for real against the workspace with `DATABRICKS_AUTH_TYPE=pat` forced, so a cached OAuth session couldn't mask a failure. The verification token was deleted immediately; today's delivery landed as a side effect, taking the volume from 64 date partitions to 65.
- Weekends need no cron-side calendar logic — the generator skips them, so a weekend run produces zero files and the upload step is skipped rather than failing on an empty directory. Ground-truth manifests stay unuploaded for free, since `make land` only ever copies `data/raw` (D-011).
- The run's job summary reports what landed, per date — the "what ran, what changed, what failed" a data-ops reader needs without opening Databricks.
- No unit test here, deliberately and not silently: the artifact is declarative config whose behaviour only exists inside GitHub's runner, and the Python it drives is already covered by the 48 existing tests. It is verified instead by rehearsing every step locally (including the weekend no-op and the real PAT upload) and by a manual dispatch run before the first cron fires. Linting workflows with `actionlint` is on the backlog.
- **First live run** reported `date=2026-07-16` while the UK clock read the 17th — correct, not a bug: runners are UTC and BST is UTC+1, so at 00:46 BST the runner's "today" was still the 16th. The 06:15 UTC cron always sees the intended weekday. It also re-landed an existing day byte-identically, leaving the volume at 65 partitions with no duplicates — D-011's determinism demonstrating itself in production rather than in a test.

## 2026-07-17 — Bronze on a trigger: the loop closes (Phase 1, tenth slice)

- `databricks.yml`: the bronze job as code — a Databricks Asset Bundle deployed with `make deploy-job`, plus `make run-job` for on-demand reprocessing (safe, because the notebook was already idempotent). A job clicked together in the Workflows UI would be invisible to review and absent from git; the same objection D-005 makes to un-applied Terraform.
- **Event-driven, not timed (D-013).** A `file_arrival` trigger watches the landing volume, so bronze follows the data instead of guessing how long after 06:15 UTC the feed finishes landing — a guess whose failure mode is silent (job runs, finds nothing, reports success, data is a day late). `wait_after_last_change_seconds: 60` coalesces a three-file delivery into one run; `min_time_between_triggers_seconds: 300` floors the frequency, protecting a free-tier quota.
- **The job runs `main` via `git_source`**, not bundle-synced files: the notebook imports the repo's own parsers through a relative path, so it needs the whole repo tree — a checkout is exactly the layout it expects. And since `main` is branch-protected and CI-gated, "the job runs `main`" already has a review gate; file sync is off so the deploy carries the job definition alone, leaving no third copy of the code.
- **Verified by real firing, not by the API accepting the config** — the distinction mattered: `jobs create` accepting a `file_arrival` trigger proves nothing about whether it polls. A probe file landed at the volume root (outside any `date=` directory, so the notebook would ignore it) produced a `FILE_ARRIVAL` run 118 seconds later, SUCCESS, with the registry unchanged — proving both that the trigger fires and that non-delivery files are harmless. Probe removed afterwards.
- The first job run also confirmed the notebook's `os.getcwd()`-relative import survives a git-checkout run — an assumption worth testing rather than trusting, since it had only ever run interactively from a Git folder. Bronze now reaches `2026-07-17`: 65 files per format, all PARSED.
- Fixed a pre-existing `make help` bug found while adding the new targets (see below).

## 2026-07-17 — Reading real holdings from SEC EDGAR (Phase 1, eleventh slice)

- `edgar.py`: fetches a filer's latest 13F-HR from EDGAR and parses the information table; `seed_13f.py` applies identifier policy and writes the committed extract (`make fetch-13f`). Source: SEC EDGAR 13F-HR, **public domain**, ~45 KB per filing, one filing read. No new dependency — three GETs need nothing beyond stdlib `urllib`.
- **The real filing taught things a synthetic fixture never would**, and each is now encoded and tested: an information table is a **per-manager breakout**, not a position list (Berkshire's 2026-Q1 filing = 90 rows → 29 securities, Apple appearing twelve times), so aggregating by CUSIP is load-bearing rather than tidy-up; `PRN` rows are debt principal and `putCall` rows are options, neither being a share holding; share classes share an issuer but not a CUSIP, so Alphabet legitimately appears twice; and `value` is whole dollars only since the 2023 rule change (thousands before — a 1000× error waiting for anyone reading a historical filing with today's assumption).
- **Identifiers: derive where the rule is real, refuse where it isn't (D-014).** A North American ISIN *is* country + CUSIP + check digit, so deriving one is ISO 6166's arithmetic rather than invented reference data (D-004). It stops where knowledge stops: Chubb's `H1467J104` is a CINS whose true ISIN (`CH0044328745`) is knowable only by lookup, so it is **excluded and counted** rather than turned into a plausible-looking identifier that exists nowhere. `country` is an explicit parameter for the same reason — numeric CUSIPs are issued to Canadian issuers too, and the code cannot tell you the domicile.
- **The derivation is measured against known truth**: eight real (CUSIP, ISIN) pairs, cross-checked by the pre-existing checksum verifier — a separate implementation, so their agreement is what makes either trustworthy. A wrong expectation in a Canadian test case was caught this way and corrected against the verifier rather than against the code under test.
- The extract is **committed, and carries no retrieval timestamp**: generation must never depend on the network (D-011 byte-identical replay), the accession number already pins the exact immutable filing, and a timestamp would make the file differ on every fetch — turning the scheduled check into a source of meaningless pull requests.
- SEC's fair-access policy requires a contact in the User-Agent and answers 403 to anything else (verified live). `SEC_USER_AGENT` is therefore **required config with no default** — a shared default would put one person's name on everyone's traffic — and an unusable value fails locally with guidance instead of as a baffling remote 403.
- 85 tests, all green and all **offline**: they read a committed fixture carrying every trap above. CI must never depend on SEC's uptime.
- `book.py` is deliberately untouched: swapping the seed regenerates every historical file, which bronze's `file_path` anti-join would not notice. That reprocess gets its own slice.

## 2026-07-17 — The book becomes real, and bronze learns restatements (Phase 1, twelfth slice)

- `book.py` now builds from the committed 13F extract instead of ten hand-picked names: **28 positions, ~$25.2M, Apple at 23.0%** — Berkshire's genuine relative weights at a private-client scale (D-015). Prices are the real quarter-end `value / shares`; cost basis (which 13F doesn't report) is synthesized deterministically from each CUSIP via sha256 — *not* `hash()`, which Python salts per process and would have broken byte-identical regeneration only on someone else's machine.
- The scale is a single share divisor rather than a value-based one, because the data refuses to be tidy: NVR trades near $6,590, so its 11,112 shares are $73M of the filing yet round to zero on any value scale that keeps Apple's 227.9M shares sensible. A position scaling to zero now raises rather than vanishing quietly.
- **Bronze detects restatements by content (D-016).** The registry has stored a `sha256` since PR 8 and nothing ever read it; the anti-join asked "seen this path?", which assumes bytes never change. The seed swap rewrites all 195 files at the same paths — so under the old check the job would have skipped everything, reported success, and left bronze permanently disagreeing with the volume. Now: digest differs → delete that file's rows → re-parse. The swap became the pipeline's **first real restatement**, handled by the mechanism rather than by a human dropping tables. Both the cost (hashing every file per run) and the limitation (landing overwrites the raw, so superseded bytes are already gone) are recorded rather than glossed.
- Verified locally before any data moved: regeneration is still byte-identical across runs (D-011 intact), all three formats parse back at 28 positions, and the same day's file demonstrably changed digest — the restatement bronze must catch.
- Two tests were pinned to the old book and became more honest for it: MT535's decimal-comma check asserted Apple's `185,4`, now replaced by the invariant it was really testing (no `:90B:` amount ever contains a decimal point). And the sub-$1 leading-zero case — which Vodafone's $0.92 had covered incidentally — is now pinned explicitly, since a 13F book holds nothing under a dollar and the edge case would otherwise have silently disappeared.
- The seed moved into the package (`parvum_ingest/seed/`) and loads lazily: `parvum_ingest/__init__` imports `book`, and the bronze job imports the package purely for its parsers — reading a data file at import time would make an unrelated job fail if it were ever missing.
- 87 tests green. **Note on sequencing:** the job runs `main` via `git_source`, so the notebook change only takes effect once merged — the pile can't be re-landed before then, or the live job would skip it under the old path-only check.

## 2026-07-17 — The 13F swap lands; the trigger's blind spot; books go point-in-time (Phase 1, thirteenth slice)

- **The PR-12 reprocess ran and verified**: 195 files re-landed, the job superseded every restated file, registry stayed at 65/format ALL PARSED (not 130 — the deletes worked), and `bronze_holdings` showed the 13F book (Apple 22,792 @ $253.79).
- **Finding, confirmed by controlled experiment (D-018): file-arrival triggers don't fire on overwritten paths.** 195 overwrites at 11:09 → nothing; a control probe at a *new* path at 11:23 → `FILE_ARRIVAL` run in 86 seconds. The trigger watches for paths appearing, not bytes changing — precisely the blind spot D-016 removed from bronze, one layer up. The same bug class hides at multiple layers; fixing one layer proves nothing about the rest. Operational rule adopted: re-lands of existing paths are chased with `make run-job` (idempotent, so always safe).
- **13F left git (D-017).** The committed seed extract — reference data living as source code, where every refresh is a PR and rewrites all history — is replaced by a gitignored **filing store** (`data/edgar/`, `make fetch-13f`, incremental because filings are immutable) read **point-in-time**: a statement for `as_of` builds from the latest filing *public* by then (filed-at, not period-end — the bitemporal distinction). Determinism needed git only apparently; it really rests on EDGAR filings being immutable and accession-pinned. A new filing now touches only future dates: the quarterly mass restatement is retired by construction.
- **The backfill genuinely straddles a filing boundary now**, verified end to end: Berkshire's Q4-2025 book (37 securities — Amazon, Diageo, Domino's…) through 2026-05-14, the Q1-2026 book (28) from 2026-05-15; bronze restated exactly the pre-boundary days and skipped the rest as unchanged. The daily workflow syncs the store before generating (new repo secret: `SEC_USER_AGENT`).
- Fixture store committed for tests (two trimmed filings with real accession metadata straddling the boundary); 92 tests, all offline, all green. Amendments (13F-HR/A) remain skipped — recorded limitation.

## 2026-07-17 — The account universe: five books, three filers, one custodian (Phase 1, fourteenth slice)

- One account was a proof; it wasn't a feed. A custodian services many accounts and knows nothing of clients — so the universe is now **five accounts across three real 13F filers** (Berkshire ×2 at different scales, Gates Foundation Trust ×2, Pershing Square ×1): five genuinely distinct books from ~$1.6M to ~$25M, one **EUR-based** so multi-currency enters bronze now (D-019). Client grouping is deliberately absent custodian-side; it arrives as WM reference data in Phase 2.
- **Account ids went opaque** (`60011234`, `FQ5521`, `X4478210`…): custodians issue numbers, not descriptions, and "what is account FQ5521?" is the question reference data exists to answer. The daily delivery is now 11 files — per-account semt.002/MT535 (those formats are one-account-per-message) plus **one consolidated camt.053** whose repeating `Stmt` blocks carry every account's cash. Parsers and bronze now handle one-file-many-statements; corruption is independent per (account, format).
- **The identifier trap fired in real data (D-020).** Gates' and Pershing's *top* holdings — Canadian National, Brookfield — are Canadian issuers with numeric, US-looking CUSIPs; default-US derivation would have minted checksum-valid ISINs that exist nowhere. A curated domicile map now covers the known cross-listings, pinned against the issuers' real ISINs; ADRs need no entry (a depositary receipt is genuinely US). The fetch-time audit over every cached filing **caught a fourth the map had missed**: Waste Connections, Canadian since 2016, one CUSIP character from the US Waste Management.
- Cash statements became per-account: amounts scale per account, currency follows the account, and entry narratives name securities the account actually holds (a Pershing account collects Brookfield dividends, not Apple's).
- 102 tests green. Cost basis now varies per (account, security) — identical cost bases across a universe would be a fingerprint no real book has.
- **Migration note:** filenames changed, so the volume raw area is wiped and re-landed after merge (the old single-account files aren't restatements — they're a retired layout), bronze rows for retired paths are deleted, and the trigger-blind-to-overwrites rule (D-018) doesn't apply since every new path is new. The bronze notebook's camt change ships in this PR, so landing waits for merge (`git_source` runs `main` — the running job would silently read only the first `Stmt` of a consolidated file).

## 2026-07-17 — Phase 2 opens: the ownership graph (who owns each account)

- Phase 1 is complete end to end — the migration to the five-account universe landed and verified in bronze (715 files, EUR account, filing boundary, Canadian ISINs all correct).
- **`parvum_ingest.ownership`**: the first reference-data component, answering the question custodial feeds can't — *who owns account FQ5521?* A validated client → legal-entity → account DAG with percentage edges (D-021). Three families, four entities (trusts/foundation/LLC), the five universe accounts.
- **Effective ownership resolves on demand**, not as a stored column: product of edge percentages along a path, summed across paths. Modelled on the target product's ownership map — transactions owned by *entities* not people, roll-ups by top-level entity, a percentage per node (see private PRODUCT_NOTES). Two cases earn their keep: one family holding three accounts through two entities, and one account (X4478210) owned 60/40 by two families through a shared LLC.
- **The graph validates itself at construction**: known endpoints, acyclic, every owned node closes at exactly 100%, every account reachable — a malformed ownership structure is a reference-data error caught here, not a silent mis-attribution in silver later. 11 tests cover the resolver (incl. the split) and every rejection; 113 total, green.
- Lives in the ingest package, not the empty `reference/` dir: it binds to `accounts.UNIVERSE`. `reference/` becomes its own package with the securities master (OpenFIGI), the next slice. Silver — joining bronze positions to owners in a notebook — is the slice after.

## 2026-07-17 — `make help` fix (found while adding job targets) `-include .env` puts `.env` into `MAKEFILE_LIST`, so grep gets two files and prefixes each match with its filename — which `awk` then read as the target name, printing "Makefile" for every line. It had been broken for anyone with a `.env` (i.e. anyone who had configured Databricks) and silently correct for everyone else. `grep -h` suppresses the prefix; the regex also widened to `^[a-z-]+:` so hyphenated targets appear at all.
