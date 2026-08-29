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

## 2026-07-17 — Phase 2: the securities master (OpenFIGI)

- The *what-is-this-instrument* half of the reference layer, complementing the ownership *whose-is-it* half. `openfigi.py` (client: batches ≤100 ISINs/request, key-optional, a miss returns None) + `securities_master.py` (build entries, the Unknown bucket, write/load) + `build_master.py` CLI / `make build-master`.
- **The Unknown bucket is first-class (D-022):** every ISIN OpenFIGI can't map becomes a flagged `mapped: false` row, never a dropped one — a security the master can't identify still sits in a client's account and must stay visible (the product shows an "Unknown" asset class; dropping it would be silent loss, D-009 one layer up).
- Built for real against all **76 universe ISINs → 76 mapped, 0 unknown**, FIGI + name + type + sector. **A free cross-check:** the Canadian names whose ISINs D-020 derived from a curated domicile map *all mapped* — a fabricated `US…` ISIN would have failed and landed in Unknown, so the clean map independently confirms the domicile derivation.
- Storage mirrors the 13F store (D-017): gitignored `data/reference/securities_master.json`, fetched occasionally, reviewed — reference data is pipeline input, not source code. Landing it to the volume for silver is the next slice.
- **Scoping:** built as modules in `parvum_ingest` rather than extracting `reference/` into its own package now (D-021 amendment) — the securities master needs the universe ISINs from `parvum_ingest`, and the package split is one clean refactor better done during the silver build than ahead of need. `OPENFIGI_API_KEY` is optional config in `.env` (client works keyless at a lower limit). 125 tests, 1 live test skipped by default.

## 2026-07-17 — Phase 1 alerting (1/2): the bronze job announces its own failures

- The bronze job runs unattended on a file-arrival trigger — nobody watches it — so a failure or a hung run must announce itself. Added `email_notifications` (`on_failure` + `on_duration_warning_threshold_exceeded`) and a `health` rule (RUN_DURATION_SECONDS > 1200s; normal is ~2 min) to `databricks.yml`.
- **The alert address stays out of the public repo**: it's a bundle variable (`${var.alert_email}`) supplied at deploy time from `.env` via `make deploy-job` (which now guards `ALERT_EMAIL`, like it guards `DATABRICKS_HOST`). A real address in a public bundle is both a privacy leak and spam bait.
- Verified the way the trigger taught us to (accepted ≠ honoured): deployed, then read the live job back — `email_notifications` and `health` are stored on it. **Delivery on Free Edition is not yet confirmed** (would require forcing a real failure); the config is live and the first genuine failure will confirm it.
- This covers "ran and failed". It cannot cover "never fired" — a job that doesn't start sends nothing — which is the freshness gate's job (part 2/2).

## 2026-07-17 — Phase 1 alerting (2/2): the bronze freshness gate

- Email catches the bronze job when it runs and fails; it cannot catch the job **never firing** — the D-018 blind spot (file-arrival triggers ignore overwrites; a stopped trigger sends nothing). `parvum_ingest.freshness` closes that from the outside: after the daily feed lands, the GitHub Action asks the lakehouse *when bronze last did any work* (`MAX(ingested_at)` in the registry) and fails the workflow — which then emails via GitHub's built-in Actions notification — if it's older than a threshold (default 4 days).
- **Checks the outcome, not the process:** "when did bronze last ingest" catches a job that succeeded-but-did-nothing, was deleted, or stopped triggering — none of which a run-status check would see. It catches a dead *Databricks job*, not a dead *Action* (an Action that never runs can't run its own check — that's the external dead-man's-switch, parked for Phase 8).
- **Monitoring must not break the thing it monitors:** a confident stale reading exits 1 (alarm); anything uncertain — warehouse secret unset, transient query error, empty table — warns loudly in the job summary and exits 0. Crying wolf on transient issues trains people to ignore the alarm.
- Built as a tested module + `parvum-check-freshness` console script (not an untested heredoc in YAML): 5 tests on the pure `evaluate` (fresh / stale / threshold boundary / empty / space-vs-ISO timestamp). Verified live against real bronze with a short-lived PAT — FRESH exit 0, forced-stale exit 1, token deleted. Fixed one real bug found in the live run: emoji crashed a non-UTF-8 (Windows cp1252) console, so `_emit` now degrades to ASCII rather than crash (the runner is UTF-8, but the gate must not die on its own output).
- New repo secret needed to activate it: `DATABRICKS_WAREHOUSE_ID` (unset → the gate skips with a warning, so it never blocks the feed). 118 tests.

## 2026-07-17 — `make help` fix (found while adding job targets) `-include .env` puts `.env` into `MAKEFILE_LIST`, so grep gets two files and prefixes each match with its filename — which `awk` then read as the target name, printing "Makefile" for every line. It had been broken for anyone with a `.env` (i.e. anyone who had configured Databricks) and silently correct for everyone else. `grep -h` suppresses the prefix; the regex also widened to `^[a-z-]+:` so hyphenated targets appear at all.

## 2026-07-18 — `reference/` becomes its own package (the deferred D-021 refactor)

- Pure refactor, zero behaviour change, opening the silver slice: `accounts`, `domicile` (né `reference.py` — renamed because a module named "reference" inside a package about reference data explained nothing), `ownership`, `openfigi`, and `securities_master` moved from `parvum_ingest` into a new **`parvum-reference`** package under `reference/`, with their tests.
- **The dependency now points one way by construction:** ingest consumes reference, never the reverse. `accounts` moved too — the account universe *is* reference data (the firm's account master), and `ownership` binds to it; leaving it in ingest would have forced reference→ingest, the wrong direction. The `parvum-build-master` CLI stays in ingest deliberately: it feeds the master from the 13F store (pipeline data), so it lives with the pipeline and calls into reference.
- **Mechanics: a uv workspace** with a virtual root — one `uv.lock` at the repo top for both members, so the packages can never resolve different dependency versions. `cd <pkg> && uv run …` still works unchanged (uv walks up to the workspace root), which is why the Makefile targets kept their shape and just gained a second line each.
- **Ruff config moved to a shared root `ruff.toml`** — not only for one-source-of-truth: with two packages, ingest's local `src = ["src", "tests"]` made ruff classify `parvum_reference` as *third-party* in ingest files and mis-sort the imports (7 auto-fixes on first run proved it). The root config names both packages' src dirs, so both are first-party everywhere.
- **CI gains a `reference` job** — deliberately a second explicit job rather than a matrix, because a matrix renames the status checks and would silently detach the branch-protection rule requiring the check named `ingest`. (New repo setting needed: also require the `reference` check.)
- **The live bronze job was the real risk:** the notebook imports `parvum_ingest`, which now pulls `parvum_reference` — merging without touching the notebook would break the next file-arrival run. The notebook adds `reference/src` to `sys.path` in the same commit, and the fix was verified honestly: first attempt used the workspace venv (where both packages are *installed* — proving nothing), so it was rerun on a bare interpreter with nothing installed, confirming both packages resolve through `sys.path` alone, exactly as a `git_source` job run does. 107 + 23 tests green (130 total; the count moved between suites, none lost).

## 2026-07-18 — Silver: the first conformed layer (positions × master × owners)

- `spark/silver_positions.py`, running as a second task of the bronze job (`depends_on: bronze` — same file-arrival trigger, no new trigger to go dark, alerting inherited). Three tables per D-023: `silver_positions` (one row per date × account × security, master-enriched), `silver_account_owners` (the materialised bridge), `silver_position_owners` (value prorated across ultimately-owning clients).
- **The dedupe is the interesting join.** Bronze keeps one row per position per *file*, and every position arrives in two holdings formats. Silver keeps one per grain — semt.002 preferred, deterministically. A live probe of the window function found 14,930 rows → 7,629 grains with 328 single-copy grains: the seeded defects (mistyped ISINs splitting a pair into two singletons, dropped positions) made visible by the very query that conforms the grain. Cross-format reconciliation is now an obviously-shaped future slice.
- **Unknowns stay first-class through the join**: `instrument_status` = MAPPED / UNKNOWN (in the master, unmappable) / NOT_IN_MASTER (identifier the master has never seen — where mistyped-ISIN defects land); `asset_class` shows literal 'Unknown' rather than NULL.
- **The master was landed** (`make land-master` → `landing/reference/securities_master.json`, verified by reading it back through the volume); the ownership graph needs no landing — it is code, imported from the job's git checkout. The flattened account→client bridge (`ownership_bridge()`) lives in `parvum_reference` with offline tests (closure at 100%, the 60/40 split), so the notebook only turns rows into DataFrames.
- Live verification of the notebook itself follows the merge — the job runs `main` via git_source, so the silver task can't execute until the notebook exists there. Bundle validated; deploy + run + table verification is the recorded next step.

## 2026-07-18 — Silver verified live + a `make run-job` fix

- The two-task job deployed and read back (both tasks stored, `silver depends_on bronze`, alerting intact) and run to SUCCESS. Verified in the lakehouse: `silver_positions` **7,629 rows / 65 days / 5 accounts** — the exact numbers the pre-merge SQL probe predicted; `instrument_status` = 7,465 MAPPED + **164 NOT_IN_MASTER, which is precisely the seeded mistyped-ISIN count** (the master rejects what the defect injector forged — two independent systems agreeing again); bridge = 6 rows; `silver_position_owners` = 8,379 = every position once plus the 750 shared-account positions doubled. The shared account reassembles perfectly: **750/750 grains with two owner rows, prorated values summing back to market value, worst gap 0.00**. Bronze registry untouched by the re-run (325/325/65, all PARSED) — idempotency held.
- One expectation corrected by looking rather than assuming: FQ5521's *holdings* are USD in silver because they are USD in bronze — its US-listed securities are priced in dollars; **EUR is that account's cash currency** (`bronze_cash_balances`), and silver covers positions, not cash. The check was mis-aimed, not the data wrong.
- Found and fixed: `make run-job` broke when `alert_email` became a required bundle variable — every `bundle` subcommand resolves the whole config, so `bundle run` needs the variable exactly as `bundle deploy` does. The alerting change updated one target and not its sibling; the failure was loud (refused to run), which is the right way for a gap like this to surface.

## 2026-07-18 — Catalog metadata: the tables describe themselves (+ job renamed)

- Two things a user noticing them made obvious. First, the job was still named `parvum-bronze-ingest` while running bronze *and* silver — renamed to `parvum-ingest` in the bundle. The rename is display-name only: the bundle's resource key stays `bronze_ingest`, because changing a key destroys and recreates the resource (new job id, new trigger) for a rename nobody sees. Verified after deploy: same job id, both tasks, trigger intact.
- Second, every column in the catalog had an empty description. Fixed as code, not clicks: each notebook now carries a `COLUMN_COMMENTS` dict — one source of truth per layer — and applies it with the mechanics each layer needs. Bronze (`CREATE IF NOT EXISTS` never touches existing tables): idempotent sync with a sentinel check, so steady-state runs pay one DESCRIBE per table. Silver (`CREATE OR REPLACE` wipes metadata every rebuild): comments reapplied after every CTAS, unconditionally.
- Two syntax findings from probing the warehouse before writing the code: a commented column list on CTAS (`CREATE TABLE t (col COMMENT '…') AS SELECT`) does not parse here — the ALTER-after route is the supported one; and string escaping must be SQL-standard quote doubling (`''`), not backslash — 4 of the 82 comments (the ones containing apostrophes) failed under `\'` and passed under `''`. The notebook code uses `''` accordingly.
- All 82 column comments are applied to the live catalog (spot-checked in DESCRIBE); the notebooks will keep them true from the next run after merge — bronze's sentinel already matches, silver reapplies on every rebuild.

## 2026-07-18 — Silver cash: coverage completed, and a defect collision found by probing

- Silver now covers the whole account: `silver_cash_balances` + `silver_cash_transactions` (conformed, native currency) and their owner-attributed variants (D-024) — four tables, one grain each, same full-rebuild pattern, running as a third job task (`silver_cash`, depends on bronze, parallel to positions).
- **The probe-before-build habit earned its keep twice.** First: the assumed transaction grain was violated in real bronze — 80 duplicate reference groups, which is the seeded DUPLICATE_TRANSACTION defect surfacing. The conformance collapses them and keeps the collapse visible (`source_row_count`). Second: checking whether the copies at least agree found **6 pairs that don't** — settlement_date off by one day, meaning DUPLICATE_TRANSACTION and SETTLEMENT_SHIFT hit the same movement. A two-defect interaction nobody designed; the injector produced it and the probe caught it before the code assumed it away. Conflicting copies get a deterministic pick (earliest settlement date) and a `source_disagrees` flag for the quality layer to explain.
- Expected post-merge numbers, recorded ahead of the run: 650 balances / 1,874 transactions (80 collapsed, 6 flagged) / 780 balance-owner rows / 2,245 transaction-owner rows / 2 currencies (the EUR account's cash is where multi-currency actually lives).
- Deliberately NOT deployed before merge, unlike previous slices: the new task points at a notebook that exists only on this branch, and a file arriving pre-merge would fail the whole job (and email about it). Deploy + run + verify follows the merge.

## 2026-07-18 — Reconciliation: the seeded defects, caught and fully accounted for

- The last silver slice (D-025): `dq_holdings_recon` (cross-format findings) + `dq_cash_integrity` (opening+movements=closing, raw and conformed verdicts), as a fourth job task after silver_cash. Pure-SQL notebook — no packages, no pip, nothing to import.
- **Probed live before merge, and the numbers tie to ground truth end to end.** Holdings: 164 MISSING_IN_MT535 + 164 MISSING_IN_SEMT002 (the mistyped-identifier pairs, = silver's 328 singletons), 153 price_as_of mismatches (157 STALE_PRICE injections − 4 both-formats-hit-the-same-grain collisions), and **zero** quantity/price/value/name mismatches — the zeros were predictions too. Cash: 139 raw breaks / 76 conformed breaks / 63 raw-broken-but-conformed-clean days (the duplicate collapse vindicated row by row).
- **Two long-standing puzzles closed with one cause.** 84 duplicates injected vs 80 collapses observed; 80 drops injected vs 76 conformed breaks. The manifests show exactly **4 DROPPED_TRANSACTION injections that removed one copy of a duplicated pair** — each cancelling both defects at once. 84−4=80, 80−4=76, and raw breaks = 84+80−21 overlap days−4 cancels = 139. Every figure derived, none shrugged at.
- **The check itself had a bug the data caught**: the first integrity draft summed amounts as stored and declared all 325 account-days broken. Amounts are unsigned with direction in the type (camt.053 CdtDbtInd); a 100% failure rate means the check is wrong. Fixed with type-signed sums — and promoted into silver proper: `silver_cash_transactions` now carries `signed_amount`, the owner proration uses it, and the (wrong) "signed amounts" wording in silver's comments is corrected.
- Not deployed pre-merge (new task, notebook only on the branch — the silver-cash lesson). Post-merge expectations: findings 328+153=481 rows in dq_holdings_recon, dq_cash_integrity 325 rows / 139 / 76 / 63.

## 2026-07-18 — FX reference rates (gold's opening move)

- Gold's blocker dissolved first, as its own slice (D-026): `parvum_reference.ecb` fetches the ECB's EUR/USD reference rates (full history, USD column, 2026 floor), stores them as published, and `fill_forward` completes the calendar at consumption time — every day gets the last published rate *plus the date it came from*, so carried-forward valuations say so. 6 offline tests on a fixture carrying the real file's traps (newest-first rows, an unpublished cell, a pre-floor row, weekend gaps).
- **Fetched and landed for real**: 138 TARGET days, 2026-01-02 → 2026-07-17 (current through Friday; it is Saturday), read back through the volume. The daily workflow now fetches and lands rates before the feeds — non-fatally, because an ECB outage should degrade gold (carry-forward) rather than block the feed delivery. The Databricks CLI install in the workflow is no longer conditional on generated files: rates land on zero-file holidays too (a US holiday is not a TARGET holiday).
- `make fetch-fx` / `make land-fx`; the CLI is the reference package's first script. Gold itself is the next slice.

## 2026-07-18 — Gold: the reports (built; live run follows the merge)

- The product layer (D-027): four tables from a pure-SQL-plus-FX notebook as the fifth and final task. Wealth headlines in USD at each day's ECB rate with the rate's publication date on every row; allocation with Cash and Unknown as first-class classes; monthly dividend/interest income; top-10 holdings summed per security across a client's accounts. `books_reconcile` carries the DQ layer's verdict onto the number it qualifies. An unconvertible currency aborts the run — silently converting at par is the failure mode nobody catches.
- **Probed pre-merge with a stand-in rate** (structure and counts; real rates join at run time): wealth **195 rows = 3 clients × 65 days** exact, cash joined on every one; top holdings **30 = 3 × 10** exact; income **24 = 3 clients × 4 months × 2 types** exact — every client earned both dividends and interest every month; **77 unreconciled client-days** (the 76 broken account-days fanned through the shared account's two owners). Allocation expectation: 390 Equity+Cash rows plus Unknown rows only on client-days actually holding a mistyped instrument.
- Not deployed pre-merge (new task + notebook, the established rule). Post-merge: deploy 5 tasks, run, verify counts above plus: Okafor's wealth reflects EUR cash converted at the real landed rate; allocation weights sum to 1 per client-day; a Friday rate on no row dated before its publication.

## 2026-07-18 — Phase 5 starts: serving scaffold (Quarkus, Flyway, schema-per-tenant)

**Done:**
- `serving/` is now a real Maven project: Quarkus pinned to the 3.33 LTS platform on Java 21, Maven wrapper committed (only a JDK is assumed on the machine), Spotless/google-java-format enforcing formatting in `verify` — the Java mirror of the ruff arrangement.
- **Schema-per-tenant tenancy** (D-028): two fictional advisory firms — Aldergate Wealth Management (Hartwell) and Stonefield Family Office (Okafor + Reyes) — each get their own Postgres schema; `TenantSchemas` applies the shared Flyway migration set to every tenant schema plus the data-free `tenant_template` (jOOQ codegen's canonical schema) at startup. Tenant ids are validated against `[a-z][a-z0-9_]*` — schema names can't be bound parameters, so the id's shape is the injection defence.
- **V1 migration = the gold projection**: `client_wealth`, `asset_allocation`, `income`, `top_holdings` mirror the four gold tables (unqualified DDL, so one migration set serves every schema), with table comments carried over — the catalog-comments habit continues in Postgres.
- Smoke tests boot the whole app against a throwaway Postgres 16 via Quarkus Dev Services: readiness is UP, every schema has every table, hostile tenant ids are rejected. `make serving-test` / `make serving-fmt` wrap the wrapper; CI gains a `serving` job (mvn verify on Temurin 21).
- D-029 recorded: gold reaches Postgres via a Python exporter (next PR) that truncates and reloads per tenant — pull over the SQL Statements API from GitHub Actions, D-006's pattern reused; the Flyway SQL files are the single schema source of truth for both sides.

**Notes:**
- The serving store is a *projection*: rebuildable from gold at any time, nothing originates in Postgres. ARCHITECTURE's serving-lifecycle section updated from its pre-Phase-4 "upsert" sketch to match — gold is itself a full rebuild with complete history, so mirroring beats merging.
- New required-check candidate: the `serving` CI job exists but branch protection still requires only `ingest` and `reference`; add `serving` once this PR is merged.

## 2026-07-18 — Phase 5 exporter: gold → serving Postgres (D-029)

**Done:**
- New workspace member `export/` (`parvum_export`): pulls the four gold tables over the SQL Statements API — pull, not push, because Free Edition compute has no egress to Postgres (D-006) — and truncate-reloads each tenant schema in one transaction. Third uv member; depends on `reference`, never the reverse.
- **Tenant split lives in `tenants.py`**, validated against the canonical client universe: a family with no firm can't be exported (it would silently reach nobody), and a family claimed by two firms is refused. Tenant-id shape check mirrors the Java `SAFE_TENANT_ID` — one injection defence, stated on both sides.
- **Wire→typed conversion pinned against a live probe** of the real tables: DATE/DECIMAL/BOOLEAN/TIMESTAMP/LONG arrive as strings with a typed manifest; converted once in `gold_source`, exactly (Decimal, not float). An unknown wire type is a loud stop, and >1 result chunk aborts rather than silently truncating — the whole gold layer is a few hundred rows by design.
- **Loader tests run against a real Postgres migrated with the real Flyway DDL** — the serving `V*.sql` files are the single schema source of truth, applied from both sides. They prove: rows land per the tenant map, tenants can't see each other's data, a reload after a restatement leaves no ghost rows, reload is idempotent, and typed values round-trip. CI gets an `export` job with a Postgres 16 service container; locally the tests skip loudly without `make up` but **fail** (not skip) when `CI` is set.
- `make export-gold` / `make test|lint|fmt` now cover all three packages; `.env.example` and the Makefile gain `DATABRICKS_WAREHOUSE_ID`.

**Verified end-to-end against the live lakehouse** (not just tests): started the serving jar once to let Flyway create the schemas, then `make export-gold` loaded **aldergate** = client_wealth 65 / allocation 185 / income 8 / top_holdings 10 and **stonefield** = 130 / 326 / 16 / 20 — the 65-day, 3-client gold split cleanly by firm (Hartwell alone vs. Okafor+Reyes). Headline spot-check in Postgres: Hartwell $41,091,835.83 at 1.1435, `books_reconcile` true; Okafor $2,867,257.58; Reyes $1,694,300.83 — matching the gold tables.

**Notes:**
- Token resolution: `DATABRICKS_TOKEN` if set (CI), else the CLI mints one from its OAuth cache — so local runs need no PAT.
- Stacked on `feat/serving-scaffold` (unmerged): this branch contains that commit too. Merge the scaffold PR first, or rebase this onto main after it lands.
- New required-check candidate `export` (like `serving`): add to branch protection once merged.

## 2026-07-18 — Phase 5: jOOQ codegen + the read-only projection endpoints (D-030)

**Done:**
- **jOOQ code generation from the Flyway migrations** — `DDLDatabase` parses `serving/`'s `V*.sql` directly, so nothing runs a database at build time; generated classes land in `target/` (never committed, like Quarkus's own). CI's `serving` job stays a plain `mvn verify`.
- **One class set, every tenant.** The `DSLContext` is produced with `renderSchema=false`, so tables render as bare names; a per-request `SET LOCAL search_path` in `TenantQuery` points the connection at the right tenant schema. `LOCAL` scopes the change to the transaction, so a pooled connection can never leak one tenant's path into the next request. The schema name is both shape-validated (`TenantSchemas.schemaFor`) and rendered as a quoted identifier — one injection defence stated twice.
- **Four read-only endpoints** under `/tenants/{id}/…`: `wealth` and `allocation` (latest exported date), `income` (full monthly series, for a time chart), `holdings` (already latest-only in gold). Rows map to small Java records; `rebuilt_at` stays internal. An unknown or malformed tenant is a 404 before any identifier is built.
- **Tests seed rows straight into two tenant schemas** and read them back over HTTP — the exporter's real source (the lakehouse) is unreachable from a unit test, so this exercises the whole path routing → search_path → jOOQ → JSON. They prove latest-date filtering, that each tenant sees only its own rows, the other three projections map, and hostile tenant ids are rejected. `mvn verify` green: 7 tests (4 new + 3 smoke).
- **One accommodation, documented (D-030):** `DDLDatabase` interprets DDL in H2, where `text` is a non-indexable CLOB, so the projection's string columns became `varchar` (unbounded) — the same type in PostgreSQL. The V1 migration carries a one-line note; nothing about the exporter or its tests changes.

**Notes:**
- jOOQ pinned to 3.19.11 (open-source edition covers PostgreSQL) in the serving `pom.xml`, outside the Quarkus BOM.
- Endpoints are unauthenticated for now — tenant comes from the path. Auth and the ownership-graph view are the next serving slices.

## 2026-07-18 — Phase 5: the ownership-graph projection and endpoint (D-031)

**Done:**
- **A fifth gold table, `gold_ownership`** — the account→client edges from `silver_account_owners`, projected as-is with two derived columns (`owner_count`, `is_shared` via a window over the account). Structural, not monetary: the money is already prorated into the other four tables, so this one answers *who owns which accounts* and where the sharing is. This is the layer where the signature 60/40 shared account becomes directly visible.
- **Flows through the existing machinery end to end.** V2 Flyway migration adds an `ownership` projection table (unqualified, so it lands in every tenant schema; `varchar` for the same H2-codegen reason as V1); the exporter gains one line in `GOLD_TABLES` and one in `PROJECTION_TABLES` and otherwise reuses truncate-and-reload and the client_id→tenant routing unchanged; jOOQ regenerates the `OWNERSHIP` table from the migration automatically; a `/tenants/{id}/ownership` endpoint serves it, ordered so each account's owners group together, largest share first.
- **Tenant routing does the right thing on the shared account.** Both its edges (Reyes 60, Okafor 40) belong to Stonefield, so Stonefield sees the whole account; Aldergate's wholly-owned account shows `is_shared` false. A tenant never sees another firm's edges — and where a shared account is split across firms, `is_shared` stays true on each side even though the co-owner isn't visible.
- **Tests both sides:** export loader test seeds the shared account and asserts it truncate-reloads with typed values (fractions as `Decimal`, `owner_count`/`is_shared` intact); serving endpoint test seeds two tenant schemas and asserts the ordering, the shared flag, and cross-tenant isolation. `mvn verify` green (8 tests), export `pytest` green (18).

**Notes:**
- Not yet run on Databricks: `gold_ownership` is a new CTAS in the existing `gold_reports` notebook (not a new task), so it materialises the next time the `parvum-ingest` gold task runs from `main` after merge — no pre-merge deploy, and the real `/ownership` data appears then. Everything here is proven locally against seeded data.
- Docs that stated "four gold tables" as current fact (gold header, ARCHITECTURE, exporter/endpoint docstrings) now say five; the historical build-log entries that described the four-table state at their time are left as the record.

## 2026-07-18 — Phase 5: the web dashboard (D-032)

**Done:**
- **`web/`, a static SPA** (Vite + React + TypeScript, Recharts) — the fifth layer and the only one a non-engineer sees. It reads the serving API and shows one advisory firm at a time: a client sidebar, and per client five tabs onto the five gold projections (wealth tiles, allocation donut, monthly income, top holdings, and the ownership graph). The quality layer's `books_reconcile` verdict rides along as a badge on the client header — the number *and* whether it ties out.
- **No CORS, no BFF.** Dev proxies `/tenants` to the local Quarkus app (browser stays same-origin); production serves the app behind the same origin, or a build-time `VITE_API_BASE` points it at a separately hosted API. Typed models mirror the Java record shapes, so a projection change that reaches the JSON is a TypeScript error, not a blank cell.
- **Charts on the project's data-viz palette** — a validated, CVD-safe categorical set, always with a legend and direct labels (identity never rests on colour alone); animation off so the first paint is the data. The whole UI is theme-aware (light/dark, OS or explicit toggle), with a deliberately dark top bar in both.
- **Verified against the live stack, not just built.** Ran the gold job so `gold_ownership` materialised (free-edition Databricks), `make export-gold` loaded all five projections, then drove the app end to end in a headless browser: Aldergate's Hartwell $41,091,836 with the allocation donut and income bars; Stonefield's Okafor showing account **X4478210 — 40% held, "Shared · 2 owners", co-owner Reyes Family (60%)** and FQ5521 sole-owned; Okafor's reconciliation-variance badge (its real DQ flag); light and dark both.
- **Tooling and CI:** strict TypeScript, Prettier, Vitest (formatters + a dashboard render test that asserts the shared-account view). A `web` CI job runs format-check → typecheck → tests → build on Node 22. `package-lock.json` committed so CI's `npm ci` installs the resolved set.

**Notes:**
- Vitest 2.1 wants Vite 5, so Vite is pinned to 5.x (a Vite 6 pin pulled a second, type-incompatible Vite into vitest).
- The production bundle is ~555 kB (mostly Recharts); fine for a dashboard, code-splitting is a later optimisation if it matters.
- Next up per the plan: deploying the API + this app (AWS/App Runner + a static host), where CORS and `VITE_API_BASE` get settled for real.

## 2026-07-18 — Local-run hardening: Makefile portability, dependency audit, docs

**Done:**
- **The `make serving-*` targets now run from PowerShell too, not just a POSIX shell.** When make is launched from PowerShell it runs recipes through `cmd.exe`, which chokes on `./mvnw` and on the bash guard the exporter target used. The Maven-wrapper call is now picked by shell (`./mvnw` under a POSIX shell / Git Bash, `mvnw.cmd` under cmd — keyed on `MSYSTEM`, which only MSYS/Git Bash sets), and `export-gold`'s bash guard is dropped (the Python CLI already errors clearly on missing env). Verified the target resolutions with `make -n`.
- **`npm audit` is clean (0 of 5).** The findings were all dev-tooling — esbuild's dev-server request issue, Vite path-traversal/`launch-editor`, and Vitest's UI-server file-read — none in the shipped bundle. Cleared by moving to the current matched majors: **Vite 8, Vitest 4, `@vitejs/plugin-react` 6** (supersedes the earlier Vite-5/Vitest-2 pin note above; a matched pair, so no repeat of the nested-Vite type clash). Typecheck, the 6 tests, the production build, and a dev-server boot all pass on the new set.
- **A first-timer run guide:** [docs/RUNNING.md](RUNNING.md) — the three processes and their ports, prerequisites, `JAVA_HOME`, Git Bash vs PowerShell, step-by-step with what to expect, and a troubleshooting table. The README's local-run section now links to it.

**Notes:**
- `mvnw.cmd` still needs a JDK (`JAVA_HOME` or `java` on PATH) — documented, not something the Makefile can supply.
- Bundle still ~549 kB (Recharts); unchanged, and Vite 8 builds via rolldown now.

## 2026-07-19 — AWS deploy, step 1: auth + Terraform bootstrap + budget alert (D-033, D-034)

**Done:**
- **AWS CLI auth via a dedicated IAM user (`parvum-terraform`), not root or a static key.** Uses the newer `aws login` browser flow (temporary credentials, auto-rotate every 15 min, expire within the session) instead of a permanent access key. IAM Identity Center/SSO was tried first for the same expiring-credential property, but enabling it requires creating an AWS Organization, which immediately forfeits this account's free-tier credits — rejected for that reason alone, recorded as D-033.
- **A `credential_process` shim (`parvum-tf` CLI profile) lets Terraform consume that session** — Terraform's AWS SDK doesn't understand `login_session` directly, so `aws configure export-credentials` re-emits it as plain temporary keys on demand. Two gotchas worth remembering if this is touched again: the S3 **backend** block resolves credentials independently of the `provider "aws"` block (needs its own `profile =`), and a quoted Windows path with spaces in `credential_process` fails silently — the short (8.3) path fixed it.
- **Terraform state on S3, versioned + encrypted + public-access-blocked, with native locking** (`use_lockfile`, Terraform ≥1.10) instead of a DynamoDB table. `infra/terraform/bootstrap/` is a small separate config (its own local state) that creates just that bucket, solving the chicken-and-egg problem of state needing a bucket whose own creation would need tracking. D-034.
- **First resource applied in the main config: an AWS Budgets alert** ($20/month threshold, 50%/80% actual-spend email notifications) — the D-005 guardrail that a budget alert must exist before any billable resource does. Reuses the existing `ALERT_EMAIL` (same address already used for Databricks job failures).
- **`make tf-bootstrap` / `tf-init` / `tf-plan` / `tf-apply`** added, mirroring the existing `deploy-job`/`run-job` guard-clause style (fail loudly if `ALERT_EMAIL` is unset). Verified: `make tf-plan` against live state reports "No changes."

**Notes:**
- Both applied resources are live: state bucket `parvum-tfstate-656326303611`, budget `parvum-monthly`.
- Next: an ECR repo + a Dockerfile for the Quarkus serving app (none exists yet), then RDS + App Runner — where standing monthly cost begins, to be confirmed before applying.

## 2026-07-19 — AWS deploy, step 2: containerize serving, ECR repo

**Done:**
- **`serving/Dockerfile`** — first container image the project has built. Multi-stage: a JDK-only build stage runs the committed `./mvnw package -DskipTests` (same "only a JDK is assumed" contract as running it on a laptop; tests are skipped here because they boot Dev Services containers that would mean Docker-in-Docker, and `mvn verify` already gates every PR before an image is ever built from a merged commit), then a JRE-only runtime stage copies Quarkus's fast-jar layout (`lib/`, the runner jar, `app/`, `quarkus/`) and runs it directly — no build tooling in the shipped image.
- **`aws_ecr_repository.serving`** + a lifecycle policy expiring untagged images after 7 days (repeated local pushes during iteration shouldn't accumulate storage cost indefinitely).
- **Verified end-to-end, not just `docker build`:** ran the built image against the local compose Postgres (`host.docker.internal`, prod profile, real `QUARKUS_DATASOURCE_*` env vars — the same "no defaults, fail loudly" contract `application.properties` already documents) — Flyway migrated all three schemas on boot, `/tenants/aldergate/wealth` returned real data (Hartwell $41,091,835.83), `/q/health` reported UP. Then authenticated to the new ECR repo (`aws ecr get-login-password` via the `parvum-tf` profile) and pushed the same image — confirms the IAM user's permissions and the whole local-build-to-registry path work before any CI automation depends on it.

**Notes:**
- Image pushed manually this session only, to prove the path; the GitHub Actions step (next) is what makes this happen on every merge.
- Next: RDS Postgres + App Runner — this is where standing monthly cost begins.

## 2026-07-19 — AWS deploy, step 3: the API is live on the public internet (D-035, D-036)

**Done:**
- **App Runner turned out to be closed to new AWS customers** as of 2026-04-30 (maintenance mode) — the first `terraform apply` against it failed with `SubscriptionRequiredException`, not a config bug. Replaced it with **ECS Express Mode** (`aws_ecs_express_gateway_service`, needs AWS provider ≥6.23.0 — bumped off the `~> 5.0` constraint), AWS's own direct successor: same pitch (image in, public HTTPS endpoint out), its own managed ALB/ACM cert/autoscaling via an AWS-managed infrastructure role. D-035.
- **RDS Postgres (`db.t4g.micro`, engine 16.14 — matches local compose exactly) is live**, plus its subnet group and a security group. Originally built VPC-private; **amended to publicly accessible**, because the exporter needs to reach both Databricks and Postgres from GitHub Actions' hosted runners, whose IPs can't be allowlisted, and a NAT gateway for a private alternative was the exact fixed cost D-005 ruled out. Defended instead by `rds.force_ssl=1` (a parameter group) and the existing Terraform-generated password; the JDBC URL carries `?sslmode=require`. D-036.
- **The RDS password never touches a plain environment variable** — it's written to SSM Parameter Store as a SecureString and resolved by the ECS task's execution role at container start (`secret` block), not baked into the task definition as plaintext.
- **Verified fully end-to-end on the real public internet, not just `terraform apply`:** the live endpoint (`https://pa-7710e29f44ed4286bac12f4207a0b028.ecs.us-east-1.on.aws`) booted, ran Flyway against the fresh RDS (all three schemas migrated from zero), and reported `/q/health` UP. Ran `export-gold` from this laptop against the live RDS over `sslmode=require` to load real gold data (aldergate 65/185/8/10/3, stonefield 130/326/16/20/3) — the public API then served the real reloaded numbers (Hartwell $41,091,835.83), confirming the whole path: internet → ECS → RDS, and Databricks → exporter → RDS, both real.

**Notes:**
- A cosmetic `terraform plan` quirk on the brand-new Express Mode resource (phantom diffs on environment values / computed fields even right after a clean apply) is a known rough edge, confirmed harmless by checking the container's actual boot logs each time — recorded in D-035 rather than chased further.
- Git Bash gotcha hit again this session: `aws logs tail /aws/ecs/...` failed with an "invalid characters" error until `MSYS_NO_PATHCONV=1` was set — Git Bash was silently rewriting the leading `/` path.
- Next: the GitHub Actions deploy path (build → push ECR → Express Mode picks up `:latest` automatically, `auto_deployments_enabled = true`), then the frontend on Vercel + real CORS.

## 2026-07-19 — AWS deploy, step 4: the CI deploy path (D-037)

**Done:**
- **`.github/workflows/deploy-serving.yml`** — on push to `main` touching `serving/**` (or manual dispatch): build the Dockerfile from step 2, push `:latest` and `:$GITHUB_SHA` to ECR, then `aws ecs update-service --force-new-deployment`. That last step corrects last entry's assumption: **Express Mode has no `auto_deployments_enabled`** (verified against the actual provider schema, not by analogy with App Runner, which did have it) — it does not watch ECR for new pushes on its own, so the redeploy has to be asked for explicitly.
- **Auth is OIDC, not a repo-secret access key**: an `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com` plus a role (`parvum-github-actions`) whose trust policy's `sub` condition is pinned to `repo:ambarshukla/parvum:ref:refs/heads/main` — only a workflow run on this repo's main branch can assume it, and the permissions attached are exactly "push to the one ECR repo, redeploy the one ECS service," nothing broader. D-037.

**Notes:**
- The workflow itself can't be exercised from this machine (it needs a real push to trigger, and this session never runs `git push`) — the Terraform side (OIDC provider + role + policy) is applied and live, but the first real run is unverified until the branch is pushed and merged.
- Next: the frontend on Vercel + real `VITE_API_BASE`/CORS — the last piece of Phase 5.

## 2026-07-19 — AWS deploy, step 5: the frontend goes live, Phase 5 done (D-038)

**Done:**
- **`web/` deployed to Vercel** as project `parvum-dashboard` (`vercel link`, then `vercel --prod`) — production domain `https://parvum-dashboard.vercel.app`. `VITE_API_BASE` set as a Vercel project env var (Production + Preview) pointing at the live AWS endpoint, rather than committed — a deployment fact, not a build fact.
- **CORS finally turned on**, closing D-032's deferral: `%prod.quarkus.http.cors.enabled=true` baked into the image (a stable prod fact), allowed origins supplied at deploy time via `QUARKUS_HTTP_CORS_ORIGINS` (the production domain plus a regex for every Vercel preview subdomain) — the same dev/prod-fact split the datasource config already used.
- **Caught a real bug via actual verification, not just a green build:** the first attempt used `quarkus.http.cors=true`, which silently did nothing — Quarkus renamed that property to `quarkus.http.cors.enabled` back in 3.4, and this app is on 3.33. Curling the live endpoint with an `Origin` header (and a proper preflight `OPTIONS` request) showed no `Access-Control-Allow-Origin` header at all — first reproduced locally against the same image before touching AWS again, to rule out an ALB/networking explanation before assuming the app config was wrong. Fixed, rebuilt, repushed, redeployed; five consecutive live requests afterward all returned the correct header.

**Notes:**
- Phase 5 is now fully complete and live: lakehouse → export → RDS → ECS → the public internet → Vercel, both tenants, both themes, verified end to end on real infrastructure rather than just locally.
- The empty `apprunner.tf` stub (superseded by `ecs.tf`, D-035) is still sitting in the working tree, untracked — this session's sandbox couldn't delete it; harmless, never added to git, safe to remove by hand whenever convenient.

## 2026-07-19 — First real CI deploy run failed, fixed (D-037 correction)

**Done:**
- Merging the AWS-deploy PR triggered `deploy-serving.yml` for real for the first time — and it failed immediately at the `configure-aws-credentials` step: `Not authorized to perform sts:AssumeRoleWithWebIdentity`.
- Diagnosed by checking AWS CloudTrail for the actual OIDC identity GitHub presented, rather than assuming the trust policy was right: GitHub's newer **immutable subject claims** feature (shipped 2026-04-23, after D-037 was written) changed the `sub` claim's format to embed permanent owner/repo IDs — `repo:ambarshukla@59102691/parvum@1302835881:ref:refs/heads/main` — instead of the classic `repo:ambarshukla/parvum:ref:refs/heads/main` the trust policy's `StringEquals` condition expected. Updated the condition to the exact observed value and reapplied; `terraform plan`/`apply` showed only that one string changing.

**Notes:**
- A real-world instance of "the platform changed between decision and execution" — same shape of surprise as the App Runner closure (D-035), just smaller and in the same session. Both are now recorded as corrections rather than edited away, per this project's ADR discipline.
- The fix is applied on the AWS side; the actual workflow run hasn't been re-verified yet — needs a manual `workflow_dispatch` (the workflow already supports it) or the next push touching `serving/**`.

**Verified:** manually dispatched `deploy-serving.yml` after both fixes merged — green in 56s (build → push ECR → `aws ecs update-service --force-new-deployment`). Confirmed a genuinely new image landed (fresh digest, tagged `latest` + the merge commit SHA), the ECS rollout completed, and the live endpoint stayed healthy throughout (`/q/health` 200, CORS header still correct). The entire CI deploy path — the one piece that couldn't be exercised from this session directly — now works end to end. Phase 5 is fully built, deployed, and verified.

## 2026-07-19 — Automate the RDS reload: `export-gold.yml` (D-039)

**Done:**
- **`.github/workflows/export-gold.yml`** — weekdays 08:00 UTC (buffer after the 06:15 daily feed for the Databricks chain to finish) plus manual `workflow_dispatch`, reloading the serving Postgres from gold unattended. Closes the "automate export-gold" gap flagged as important since it was first parked, now revivable because a live consumer (the AWS deploy) exists.
- **Reuses the existing OIDC role** (`parvum-github-actions`) rather than a second one, extended with one new scoped permission: `ssm:GetParameter`/`kms:Decrypt` on `/parvum/rds/password` only. The workflow fetches the password fresh from SSM at runtime and masks it (`::add-mask::`) before composing the connection string — no duplicate copy of the secret in GitHub, one source of truth stays one source of truth.
- **Also corrected D-038's write-up** while in the area: it still described the pre-fix `quarkus.http.cors=true` property name from before the rename bug was found. Fixed the doc to match the actually-shipped `quarkus.http.cors.enabled`, and added the correction as its own bullet (matching the pattern D-037 already set) rather than silently editing history.

**Notes:**
- Terraform applied cleanly (1 add, 1 change — the latter the same recurring `aws_ecs_express_gateway_service` cosmetic-diff quirk noted since D-035).
- Not yet verified end-to-end — same limitation as the deploy workflow initially: needs a real dispatched run, which this session can't trigger itself (no `git push`, no `gh` CLI). Ask for `workflow_dispatch` once merged.

**Verified:** manually dispatched after merge — completed successfully in ~1 minute, first attempt, no OIDC surprise (this workflow inherits the trust-policy fix from D-037's correction). The live API still served correct figures afterward. This closes the AWS-deploy work arc started this session: the whole chain — lakehouse → export (now unattended) → RDS → ECS → Vercel — runs live and confirmed.

## 2026-07-19 — Cash-book continuity: the fixture learns to carry a ledger (D-040)

**Done:**
- **Probed before building:** the planned performance slice (TWR/IRR over gold) assumes flows reconcile with valuations. Predictions recorded first, then checked against the live warehouse: (1) no `TRANSFER_OUT` anywhere, (2) every account's opening/closing balance constant across all 65 days, (3) therefore day-over-day wealth deltas never equal recorded flows. All three confirmed — the fixture recorded a daily 25,000×scale contribution that never landed in any balance.
- **`book.py` rebuilt around a series epoch (2026-04-20):** openings now chain — each business day opens at the previous business day's accumulated closing; the epoch day opens at the old flat seed. Contributions became monthly (first business day), withdrawals monthly (first business day on/after the 18th, mid-month on purpose for the coming methodology comparison), and the daily BUY was resized so the book is solvent indefinitely (two-year positivity walked in a test, at every account's cash scale). Opening balances are now dated the previous business day instead of `as_of − 7`.
- **Defect injection untouched:** the chain accumulates from the *clean* book, so a dropped/duplicated entry in a delivered file now breaks statement-to-statement continuity detectably — the planned continuity DQ check gets a real target.
- **Tests: 118 ingest (11 new)** — chain continuity across plain days/weekends/month boundaries/withdrawal days for all five accounts, epoch anchoring, flow cadence (including July's withdrawal sliding Sat 18th → Mon 20th, and April's sliding onto the epoch day itself), the re-pinned deliberate closing value (75,211.85, verified against an independent walk of the flow calendar), two-year solvency.

**Verified locally (full regeneration, 65 business days):**
- Byte-level blast radius exactly as predicted: same 715-file set; only the 65 `CUSTGB2L.camt053.xml` files changed; all 650 semt.002/MT535 files byte-identical (sha256 inventory before/after).
- Parsed all 325 delivered statements with the repo's own parser: **zero continuity breaks, zero non-positive balances**; flow calendar exactly as designed. Account 60011234: opens 50,000.00 on 2026-04-20, closes 74,821.75 on 2026-07-17.
- Determinism (D-011): regenerating a single day reproduced the identical camt.053 sha256.

**Not yet done (post-merge):** re-land the 65 days (`make land` — overwrites don't fire the file-arrival trigger, D-018) and `make run-job` for the full bronze-restatement → silver → dq → gold rebuild; documented lakehouse/gold counts will shift and get re-verified then. The RDS reload follows automatically (D-039).

## 2026-07-19 — silver_positions was double-counting positions hit by MISTYPED_ISIN (D-041)

**Done:**
- **Found while probing before building** (same discipline as D-040, same session): validating live data ahead of the TWR/Dietz slice, the daily wealth chain showed spikes that fully reverted the next day — the classic signature of a data artifact, not a market move. Traced to `silver_positions`'s dedupe keying on `(as_of, account_id, security_scheme, security_id)`: a `MISTYPED_ISIN` defect changes one row's identifier, so the corrupted copy and its untouched sibling in the other format stop sharing a key and **both** survive the "prefer semt.002" logic instead of one replacing the other. Confirmed live: American Express double-counted ($4,585,899.28 × 2) for account 60011234 on 2026-07-01.
- **`silver_positions.py` fixed:** the winning format is now chosen per (date, account) as a whole delivery, before any per-security logic runs — file path stays as a residual tie-break inside the chosen format only. Matches the notebook's own pre-existing stated intent; the bug was granularity, not design.
- **Verified live** (SQL prototyped against the warehouse before and after touching the notebook): AMEX now appears once. Account 60011234's total positions value is now flat across all 65 days except 2026-05-15 — the documented filing boundary — exactly matching the clean book's designed invariant for the first time.

**Not yet done (post-merge):** `make run-job` to re-materialize silver_positions and every gold table built on it (same re-run as D-040 — the two fixes will be verified together in one pass).

## 2026-07-19 — Performance: TWR, Modified Dietz, and IRR side by side (D-042)

**Done:**
- **`gold_performance`** (spark/gold_reports.py): daily time-weighted return chain per client — `(wealth − flow) / prev_wealth − 1`, chain-linked into a growth-of-$1 index via `EXP(SUM(LN(1+r)))` (exact in a SQL window, no UDF).
- **`gold_performance_summary`**: since-inception TWR, Modified Dietz, and annualized money-weighted IRR in one row per client. IRR solved by hand-rolled bisection in Python (no external solver dependency), joined back via the same compute-then-`createDataFrame` pattern the FX section already uses.
- **`docs/PERFORMANCE_METHODOLOGY.md`**: explains why the three methods diverge (manager-return vs. approximation vs. investor-experience, and the annualization-convention gap), with real figures from the corrected data.
- **Prerequisite work that came first, same session:** validating this slice's own arithmetic against live data surfaced two upstream bugs — cash-book continuity (D-040) and a holdings-dedupe double-count (D-041) — both fixed and merged/pending-merge before this table's numbers could be trusted. `PERFORMANCE_METHODOLOGY.md`'s example figures were computed by re-running the corrected dedupe logic as an ad hoc probe against live bronze data, not the (still-to-be-rebuilt) live gold table.

**Verified (pre-merge, ad hoc against live warehouse data using the corrected logic):** TWR and Modified Dietz agree to within a few basis points for all three clients (Hartwell −4.49%/−4.49%, Okafor −11.24%/−11.23%, Reyes −10.77%/−10.79%); annualized IRR reads far more negative for all three purely from the annualization convention on a ~89-day window (Hartwell −17.34%, Okafor −38.98%, Reyes −37.71%).

**Verified again post-merge (materialized `gold_performance_summary`, after `make run-job`):** wealth/TWR/Dietz/IRR all match the pre-merge probe exactly (Hartwell to the cent). One correction caught by comparing against the live table rather than trusting the pre-merge doc: the methodology doc's "Net flow" column had been hand-approximated for Okafor (+$100,000) and Reyes (+$25,000) rather than derived from the corrected query — the live figures are +$159,853.12 and +$22,500.00. Fixed in `docs/PERFORMANCE_METHODOLOGY.md`; TWR/Dietz/IRR, which *were* computed from the real series, needed no correction.

**Not yet done (post-merge, after D-040/D-041 land and `make run-job` reruns):** materialize `gold_performance`/`gold_performance_summary` for real and confirm the live figures match this doc's pre-validated numbers. Natural follow-ups once this is live: a jOOQ serving endpoint, an exporter loader into the tenant Postgres schemas, and a dashboard panel.

## 2026-07-19 — Serving: performance endpoints

**Done:**
- **`V3__performance.sql`**: `performance` and `performance_summary` tables, mirroring `gold_performance`/`gold_performance_summary`'s columns exactly (D-042). `daily_twr_return`, `dietz_since_inception`, and `irr_since_inception_annualized` are nullable, matching gold's own nullability (inception-day return, and IRR's no-root case).
- **`ProjectionResource.java`**: `/tenants/{id}/performance` (full series, like `income`) and `/tenants/{id}/performance-summary` (one row per client, like `ownership`) — no new pattern, same tenant-scoped `TenantQuery.inTenant` + jOOQ `selectFrom` shape as every existing endpoint.
- **Tests**: seeded Hartwell with two performance dates (inception + one real return) and a summary row; asserted the full series returns (not latest-only), the inception row's `dailyTwrReturn` is `null`, and an unseeded tenant (Stonefield) returns `[]` rather than erroring. `ServingSmokeTest`'s `PROJECTION_TABLES` extended to cover every projection table, not just the original four.

**Verified:** `mvn verify` green — 10/10 tests (7 `ProjectionEndpointsTest` + 3 `ServingSmokeTest`), spotless clean, jOOQ codegen picked up the new migration automatically (no config change needed — it globs `V*.sql`).

## 2026-07-19 — Export: loader support for performance tables

**Done:**
- `GOLD_TABLES` and `PROJECTION_TABLES` extended with `gold_performance`→`performance` and `gold_performance_summary`→`performance_summary`. No other change needed: `fetch_table`, `load_tenant`, and the orchestrator all iterate `GOLD_TABLES` generically, and both new tables carry `client_id` so `.filtered()`/`.client_ids()` work unmodified.
- Test fixtures (`test_loader.py`): `performance_table`/`performance_summary_table` helpers, and a dedicated test asserting the inception-day `NULL` `daily_twr_return` (and `dietz_since_inception`/`irr_since_inception_annualized`, both nullable per D-042) round-trip through Postgres as `NULL`, not a sentinel value.

**Verified:** `uv run pytest -rs` — 19/19 (was 17), against a real Postgres migrated with serving's actual Flyway DDL including `V3__performance.sql` (D-042's serving PR). `ruff format`/`ruff check` clean.

## 2026-07-19 — Web: Performance dashboard panel

**Done:**
- `types.ts`/`api.ts`: `PerformanceRow`/`PerformanceSummaryRow` interfaces, `TenantData` extended, `fetchTenant` pulls both new endpoints alongside the existing five.
- `Charts.tsx`: `PerformanceChart` — a single-line growth-of-$1 chart (`twrIndexSinceInception` over `asOf`) with a dashed reference line at 1.0, following the same recharts/palette/chrome conventions as `AllocationDonut`/`IncomeChart`.
- `ClientDashboard.tsx`: new "Performance" tab — the chart plus a since-inception comparison of all three methodologies (TWR, Modified Dietz, IRR annualized) and net external flow, in the existing `Tile` layout. Nullable Dietz/IRR render as "—".
- Test: seeded a two-point performance series (inception + one return) and a summary row for Reyes, asserted all three methodology figures and net flow render on the new tab.

**Verified:** `npm run typecheck` clean, `npm test` 7/7 (was 6), `npm run format:check` clean, `npm run build` succeeds. End-to-end with real data: started serving locally (`make serving-run`), loaded real gold data via `make export-gold` against the local Postgres (aldergate performance=65/performance_summary=1, stonefield 130/2), confirmed the exact JSON shape through both the direct API and the Vite dev proxy matches the TypeScript types and the live figures match `PERFORMANCE_METHODOLOGY.md` exactly. Browser tools were unavailable this session, so the rendered page itself was not visually inspected — the API contract, typecheck, and component tests are the verification that exists; a visual check is recommended before merge.

## 2026-07-19 — Performance chart: mark the 13F filing boundary

**Done:**
- User feedback after the first visual check of the Performance tab: a long flat stretch between mid-May and July looked like a stalled chart. Confirmed against the live lakehouse it's real — after the 2026-05-15 filing boundary, positions are (correctly, per D-041) perfectly static, and the only daily movement is the structural cash drain (~$487/day against $41M for Hartwell), invisible at the chart's percent scale. Verified this boundary is shared by every filer in the universe (Berkshire, Gates Trust, Pershing Square all filed Q1-2026 by 2026-05-15 — the shared SEC 45-day deadline).
- `PerformanceChart` now marks known 13F filing boundaries with a labeled vertical reference line ("13F filing"), alongside the existing horizontal 1.0 reference line — so the flat stretch reads as "quarterly filing, price frozen between filings" rather than "is this broken?" Only boundaries inside the rendered date range are drawn.

**Verified:** typecheck/tests(7/7)/format/build all green.

## 2026-07-19 — DQ metrics: the declarative rollup, and the promised continuity check (D-043)

**Done:**
- **`dq_cash_continuity`** (spark/dq_recon.py): new detail table, day-over-day cash continuity per account — does today's opening equal yesterday's closing? Different question from `dq_cash_integrity`'s intra-day check. This is the exact check D-040 flagged as "planned" once the cash book had real continuity to break.
- **`dq_metrics`**: declarative rollup, one row per (date, dimension, metric) — freshness (one row per rebuild, dated at run time), completeness (files-landed rate), accuracy (three rates: cross-format match, intra-day cash, day-over-day continuity), exceptions (the raw counts behind those rates). Adding a future check costs one more `UNION ALL` branch, never a schema change.
- COLUMN_COMMENTS and a KPI-scorecard display cell added, matching house style.

**Verified live** (full query prototyped against the warehouse before writing the notebook): 454 rows across 8 metric series; completeness is a clean 100% on all 65 days (all 11 expected files parsed every day — the defect pool never drops a whole file); the continuity check reports 0 breaks against the clean silver chain, confirming it's correctly wired before a corrupted delivery ever reaches it; accuracy rates genuinely range 40–100% day to day, the honest signature of deliberately-injected defects (D-011) rather than a dashboard chasing 100%.

**Not yet done (post-merge):** `make run-job` to materialize both tables for real; a natural follow-up slice (not started) is the KPI dashboard band in web/ surfacing break trends, aging, and SLA attainment over time.

## 2026-07-19 — Serving: DQ metrics endpoint

**Done:**
- `V4__dq_metrics.sql`: `dq_metrics` table, mirroring the gold rollup (D-043). Deliberately duplicated into every tenant schema via the same Flyway/exporter machinery every other table uses, rather than building a second non-tenant schema-management path — the data isn't tenant-scoped (it's a fact about the whole pipeline), and this is the smaller, more honest cost for a table this size.
- `/tenants/{id}/dq-metrics`: full series, same `TenantQuery` pattern as every other endpoint. Returns identical rows regardless of which tenant is selected — documented in the migration and the endpoint's javadoc.
- Tests: seeded three metric rows (accuracy/completeness/exceptions) including the exceptions row's `NULL` `passed`, asserted ordering and the nullable field round-trips correctly. `ServingSmokeTest`'s table list extended.

**Verified:** `mvn verify` green — 11/11 tests, spotless clean.

## 2026-07-19 — Export: unscoped-table loader path for dq_metrics

**Done:**
- `gold_source.py`: `UNSCOPED_TABLES = ("dq_metrics",)`, fetched the same way as `GOLD_TABLES` but never filtered by client — `dq_metrics` has no `client_id` column, since it's a fact about the whole pipeline, not any one firm's clients.
- `loader.py`: `PROJECTION_TABLES["dq_metrics"] = "dq_metrics"`.
- `export_gold.py`: fetches `UNSCOPED_TABLES` once, appends the same unfiltered rows to every tenant's load list (`filtered + unscoped`) instead of calling `.filtered()`/`.client_ids()` on them.
- Test fixtures (`test_loader.py`): `dq_metrics_table`/`dq_metric_row` helpers, a dedicated test asserting the exceptions row's `passed=NULL` round-trips through Postgres correctly. Caught and fixed a self-inflicted test-structure bug while writing this: an edit had split `test_performance_series_and_summary_load_with_nulls_intact` across two tests by inserting in the wrong place — its tail assertions were misplaced into the new dq_metrics test. Fixed before running anything, confirmed by rerunning: 20/20 pass, with the performance test's own assertions restored to where they belong.

**Verified:** `uv run pytest -rs` — 20/20 (was 19), `ruff format`/`ruff check` clean. Stacked on `feat/dq-metrics-serving`: the loader tests migrate throwaway schemas from serving's real Flyway DDL, which must include `V4__dq_metrics.sql`.

## 2026-07-19 — Web: standalone Ops page

**Done:**
- `types.ts`/`api.ts`: `DqMetricRow` interface, `TenantData.dqMetrics`, fetched alongside everything else in `fetchTenant`.
- **New top-level view, not a client tab**: `App.tsx` gains a `view` state ("clients" | "ops") toggled from the topbar, no router needed — same Vercel deployment, same API, same `TenantData` fetch (`dqMetrics` just rides along, identical regardless of which tenant is selected, per D-044's serving-layer design). Chose this over a fully separate app + Vercel project after weighing the effort tradeoff with the user: a separate app would need a new non-tenant Postgres schema, a new exporter code path, and a new deployment — real infra work not justified for a solo demo project.
- `OpsPage.tsx`: freshness + completeness tiles, one SLA-attainment tile per accuracy metric (% of days passed), and two trend charts (`AccuracyTrendChart`, `ExceptionsChart` in `Charts.tsx`) — directly answers the brief's "break trends/aging and SLA attainment" ask.
- `dqMetricLabel()` in `format.ts`: the rollup's raw metric identifiers (`holdings_cross_format_match_rate`) get one display label each; unknown metrics fall back to the raw name rather than hiding.
- Caught and fixed a test-authoring bug of my own before running anything: `getByText("Cross-format match")` matched twice (tile label + chart legend) — switched to `getAllByText` with an explicit note on why two matches are expected by design.

**Verified:** typecheck clean, 9/9 tests (was 7 — new `OpsPage.test.tsx`), `format:check` clean, `npm run build` succeeds. Real end-to-end verification with live data isn't possible yet — `dq_metrics` doesn't exist in Databricks until the gold-layer PR (`feat/dq-metrics`) merges — so this waits for the same post-merge verification pass as the other three PRs in this slice.

## 2026-07-19 — The web dashboard now deploys on push (D-045)

**Done:**
- Diagnosed a real gap: the Performance tab and Ops page had been live on `main` for hours, but `parvum-dashboard.vercel.app` was still serving a stale pre-Performance-tab build — confirmed by comparing the deployed bundle hash against a fresh local build, not guessed.
- Ran one manual `vercel --prod` to get the current code live immediately.
- Connected the Vercel project to GitHub (`vercel git connect`) and set **Root Directory = `web`** (Vercel had it at `.`, the repo root, which would have failed to build once Git-triggered deploys started). One step needed the user directly — authorizing a GitHub "Login Connection" on their Vercel account, browser-only, no CLI path around it.
- Verified the new pipeline for real: triggered a Vercel Deploy Hook (rather than waiting for the next PR merge), confirmed the resulting build completed in 12s and matched the manual deploy's bundle byte-for-byte.

**Not yet done:** production RDS still has zero rows in `performance`/`performance_summary`/`dq_metrics` — confirmed live (`/tenants/aldergate/performance` returns `200 []`). ECS *has* redeployed with the new Flyway migrations (the endpoint exists), but `export-gold.yml` hasn't run against production since these tables were created. Needs a manual `workflow_dispatch` of `export-gold.yml` (or the next scheduled 08:00 UTC run) — this laptop can't do it directly, the RDS password is deliberately scoped to the CI role only (D-039).

## 2026-07-20 — Phase 6 kickoff: internal app + minimal auth (D-046)

**Done:**
- New `serving/.../internal/` package: `SessionToken` (stateless HMAC-signed session cookie, no session table), `AuthResource` (`POST /internal/auth/login`, `POST /internal/auth/logout`, `GET /internal/auth/session`), `InternalAuthFilter` (a `@PreMatching` `ContainerRequestFilter` gating every `/internal/**` path except login/logout, plus a custom-header CSRF check on all of them). One shared credential compared via constant-time equality against an SSM-stored secret — not a hashed-password table, see D-046 for why that's the right tool here.
- New `internal/` app: Vite/React/TS/Vitest, same toolchain as `web/`, dev port 5174 (so both dashboards run locally at once). `LoginPage` + `App` shell (checks the session on load, shows login or a signed-in placeholder), `api.ts` wraps every call with `credentials: "include"` and the CSRF header.
- `infra/terraform/ecs.tf`: two new SSM `SecureString` parameters (`internal_password`, `internal_session_secret`, Terraform-generated via `random_password`), wired into the ECS task as `secret` env vars; CORS origins extended for an assumed `parvum-internal` Vercel project (fixup pending the real `vercel git connect`); `access-control-allow-credentials=true` added now that a cross-site cookie is in play.
- Caught and fixed a real bug before it shipped: the filter's path-prefix check compared against `ctx.getUriInfo().getPath()` assuming no leading slash (per the JAX-RS javadoc), but this Quarkus REST stack returns one — the filter silently let every request through unblocked until a real `mvn verify` run caught both negative-path tests failing (403/401 expected, got 204). Fixed by stripping the leading slash defensively rather than trusting the javadoc's stated convention.

**Verified:** `mvn verify` 16/16 green; `internal/`'s `typecheck`/`test`(4/4)/`format:check`/`build` all green; `terraform validate` clean. End-to-end against a real running stack (not just unit tests): started the serving dev server and the internal app's Vite dev server, drove the full login → session → logout flow with curl through both the direct API and the Vite proxy — 403 (no CSRF header) → 401 (no cookie) → 401 (wrong password) → 204 (correct password, real cookie captured) → 204 (session valid) → 204 (logout).

**Not yet done:** `terraform apply` (creates the new SSM parameters for real — held for explicit go, not run speculatively) and the new Vercel project's one-time `vercel git connect` (needs the account's browser-only GitHub OAuth step, same as D-045) are both real checkpoints, not yet done. Ops page migration into `internal/` (D-046 names this as the next slice) hasn't started.

## 2026-07-20 — Ops page moves into internal/ (mechanical execution of D-046)

**Done:**
- Serving: `dq-metrics` moved from the public `ProjectionResource` (`/tenants/{id}/dq-metrics`) to a new `InternalProjectionResource` (`/internal/tenants/{id}/dq-metrics`), gated by `InternalAuthFilter` automatically via the path prefix. `DqMetricRow` moved with it (it's a shape only this endpoint returns).
- `internal/`: `OpsPage.tsx` + its test moved from `web/` verbatim; the two DQ-only chart components (`AccuracyTrendChart`, `ExceptionsChart`) moved from `web/src/components/Charts.tsx` into a new `internal/src/components/Charts.tsx`, alongside copies of `palette.ts`/`format.ts` (the DQ-metric label map moved with them, deleted from `web/`'s copy). `App.tsx` now fetches `dq-metrics` once signed in and renders `OpsPage` in place of the earlier placeholder.
- `web/`: the "Ops" topbar toggle, `view` state, and the whole `dq-metrics` fetch/type are gone — `App.tsx` is back to a single client view, `TenantData` no longer carries `dqMetrics`. `fetchTenant` now makes 7 calls, not 8.
- README: stack table gains `internal/`, the performance-screenshot caption no longer describes an Ops tab inside the client dashboard, repo layout table gains `internal/` alongside the original Phase-0 `alts-hitl/` placeholder (which the next slice, the alts document generator, will actually fill in — under that established name, not a new one).

**Verified:** `mvn verify` 17/17 (was 16 — `InternalProjectionResourceTest` replaces the moved assertions, `ProjectionEndpointsTest` down to 7 from 8). `web/`: typecheck/7-tests(was 9)/format/build all green. `internal/`: typecheck/6-tests(was 4)/format/build all green (needed `recharts` added as a dependency, and the `ResizeObserver` jsdom stub copied into `test-setup.ts` — both were previously only in `web/`). End-to-end against a real running stack: seeded a real `dq_metrics` row directly into `tenant_aldergate` via psql, confirmed the old public route now 404s and the new authenticated route returns exactly that row through a real login → cookie → fetch flow.

**Not yet done:** `docs/img/dashboard-performance.png` still shows the old in-dashboard Ops toggle — stale until the next screenshot pass (not blocking, cosmetic).

## 2026-07-20 — Alts document generator (D-047)

**Done:**
- New workspace member `alts-hitl/` (`parvum_alts_hitl`), filling in the Phase-0 placeholder directory: `model.py` (`FundCommitment`, `CapitalCallNotice`, `DistributionNotice`, `CapitalAccountStatement`), `book.py` (`build_fund_book` — a deterministic, self-reconciling fund waterfall), `defects.py` (four `DefectType`s + injectors), `render.py` (reportlab PDF rendering), `generate.py` (the `parvum-generate-alts-docs` CLI + `FUND_UNIVERSE`).
- Wired into the shared tooling: `pyproject.toml` workspace members, `ruff.toml` src paths, `Makefile` (`test`/`lint`/`fmt` extended, new `make generate-alts-docs`), CI `alts-hitl` job mirroring `ingest`'s.
- Caught two real bugs before they shipped, both via a real `uv run pytest` run rather than by inspection: (1) `unfunded_commitment` test wrongly assumed no call lands in the first statement's quarter — it does (calls and statements share the quarter-1 slot) — fixed the test, not the code, once traced; (2) `AMOUNT_TRANSPOSITION` swapping the *trailing* two digits was silently a no-op on this fixture's round dollar amounts (...000.00 stays ...000.00) — switched to swapping the *leading* two digits, which is also the more realistic OCR/data-entry error shape.

**Verified:** 23/23 tests green, lint clean, `make test`/`make lint` green across all four Python packages. Real end-to-end run (not just tests): `make generate-alts-docs` produced 32 real PDFs (16 per fund) + 2 manifests; read a real corrupted PDF back with `pypdf` and confirmed both an injected `COMMITMENT_MISMATCH` and `AMOUNT_TRANSPOSITION` are legible in the extracted document text, matching the manifest exactly.

**Not yet done:** landing these documents into the Databricks volume + a bronze registry table (next slice); LLM extraction, deterministic validation, and the review queue itself are all still ahead.

## 2026-07-20 — Alts bronze: landing, and a registration-only notebook (D-048)

**Done:**
- `spark/bronze_alts_ingest.py`: new notebook, `bronze_alts_documents` table (file_path, fund_id, doc_type, size_bytes, sha256, status, ingested_at), same restatement discipline (path + sha256, not path alone) as `bronze_ingest.py`. Registration only — no parser, since there is none for a PDF; content extraction is a later, separate LLM step.
- `databricks.yml`: new job resource `alts_bronze_ingest`, deliberately a *separate* job/trigger from the existing `bronze_ingest` (the one job in this project that must never break) — own landing path (`landing/alts/raw/`), own file-arrival trigger, own failure email.
- `Makefile`: `make land-alts-docs` (upload `data/alts/raw` to the volume), `make run-alts-job` (manual kick, documented as usable only once deployed post-merge).

**Verified live:** the real 32-document set generated in the previous slice was uploaded to `dbfs:/Volumes/workspace/parvum/landing/alts/raw/` for real (`databricks fs cp`, confirmed via `databricks fs ls`) — a pure data operation, no job or trigger involved, safe regardless of merge state. `databricks bundle validate` confirmed the new job resource is syntactically sound.

**Not yet done, deliberately:** `databricks bundle deploy` and the first run of `alts_bronze_ingest` are deferred until *after* this merges to `main` — the bundle's `git_source` always runs `main`'s code, so deploying now would arm a live trigger against a notebook that doesn't exist there yet (the standing rule this project has hit before: a pre-merge deploy of a new-notebook task risks a failed run and an alert email). Once merged: `make deploy-job` then `make run-alts-job`, then confirm `bronze_alts_documents` shows 32 rows correctly split by `fund_id`/`doc_type`.

**Post-merge follow-up, done this session:** all four PRs above merged; deployed the bundle for real (`make deploy-job`) and ran `make run-alts-job` against the live workspace. Verified via the SQL Statements API: `bronze_alts_documents` has exactly the predicted 32 rows — `capital_call`=4, `distribution`=2, `capital_account_statement`=10 per fund, both funds — confirming the registration notebook, the separate job/trigger, and the whole landing→registry path all work end to end against the real lakehouse.

## 2026-07-20 — LLM extraction pipeline (D-049)

**Done:**
- `alts-hitl/src/parvum_alts_hitl/`: `naming.py` (shared doc-type-from-filename mapping — also refactored into `bronze_alts_ingest.py`, replacing its own inline copy), `extract.py` (`parvum-extract-alts-docs` — forced tool-use extraction via Claude, hybrid confidence), `evaluate.py` (`parvum-eval-alts-extraction` — scores extraction against the generator's ground truth: document exact-match rate, field accuracy).
- `generate.py`: each manifest document entry now carries the full as-rendered `fields` (not just the injected-defect diff) — extraction eval's ground truth, decoupled from re-deriving it via the defect-injection functions.
- `.github/workflows/alts-extract.yml`: manual-dispatch only (every run is a real, billed API call) — generates a fresh document set, extracts, evaluates, uploads the eval report as an artifact.
- `Makefile`: `make alts-extract`, `make alts-eval`; `ANTHROPIC_API_KEY` added to the exported `.env` vars.
- `.env.example` documents the new `ANTHROPIC_API_KEY` var.

**Verified:** 37/37 tests green (14 new), all against a mocked Anthropic client — the test suite makes zero real API calls by design, matching how `alts-extract`/`alts-eval` are kept out of per-PR CI. Lint clean.

**Not verified — a real, honestly-reported blocker:** a single live extraction call was attempted before considering this slice done. It failed: `Your credit balance is too low to access the Anthropic API` — the Console account has no credit loaded (separate from a Claude Pro subscription, which doesn't include API credit). The extraction/eval code is believed correct from the mocked tests, but no real document has yet been successfully extracted end to end. `bronze_alts_ingest.py`'s naming-refactor is similarly unverified live until it merges and the job runs post-merge (git_source always runs `main`). Follow-up once credits are added: a single-document smoke call, then a full `make alts-extract` + `make alts-eval` run, with the real numbers recorded here — not assumed.

## 2026-07-20 — Cross-document validation: silver_alts_documents (D-050)

**Done:**
- `alts-hitl/src/parvum_alts_hitl/validate.py`: `validate_calls`/`validate_distributions`/`validate_statements` (cascading running-sum and statement-chaining checks) + `route()` (auto_accept vs needs_review, confidence-threshold + structural-validity gated) + `validate_fund_documents()` (dispatch by doc_type, handles unknown types by routing to review rather than dropping silently).
- `bronze_alts_ingest.py` extended (not a new notebook): now registers `bronze_alts_extractions` alongside `bronze_alts_documents`, sharing a new `discover`/`supersede`/`register` helper trio instead of duplicating the restatement logic per table.
- `spark/silver_alts_documents.py`: new notebook, orchestration only — loads `bronze_alts_extractions`, groups by fund, calls `parvum_alts_hitl.validate.validate_fund_documents`, writes `silver_alts_documents` (routing decision + validation notes per document).
- `databricks.yml`: `alts_bronze_ingest` job gains a `silver_alts` task (depends on `bronze_alts`); display name updated to `parvum-alts-ingest` to match (resource key unchanged — renaming a key destroys/recreates the job).
- `Makefile`: `make land-alts-extracted`.

**Two real bugs, caught by the integration test testing itself, not by inspection:** writing `test_validate_integration.py` (validate.py against the real generator's own manifest output, not hand-picked fixtures) failed twice before it passed — both times because the *test's* assumptions were wrong, not the code: (1) assumed a document with no defect of its own could never be flagged, missing that a running-sum check legitimately cascades a single early defect forward through every later cumulative check; (2) hardcoded `self_consistent=True` for the simulated extraction, missing that a faithfully-read `ARITHMETIC_ERROR` statement should compute `self_consistent=False` via `extract.py`'s own check — a different mechanism than `validate.py`'s chaining check, which only compares consecutive statements and wouldn't independently notice one statement's own bad arithmetic. Fixed by computing `self_consistent` in the test via the real `extract.self_consistency_ok` instead of assuming it.

**Verified:** 53/53 tests green (16 new). `databricks bundle validate` confirms the new `silver_alts` task and updated job config are syntactically sound.

**Not yet verified live, for two compounding reasons — see D-050:** the deploy-after-merge rule (this branch's notebooks don't exist on `main` yet), and no real `bronze_alts_extractions` data exists regardless, since D-049's live extraction is still blocked on the Anthropic credit balance. The 53 passing tests, including the integration test against real generator output, are strong evidence the logic is correct; they are not the same claim as "ran against real Claude output," and this entry doesn't pretend otherwise.

## 2026-07-20 — Alts review queue: Postgres schema + Quarkus backend (D-051)

**Done:**
- New non-tenant `internal` Postgres schema: `InternalSchema` (Flyway, migrates one schema from `db/migration_internal`, mirrors `TenantSchemas`) + `InternalQuery` (`SET LOCAL search_path`, mirrors `TenantQuery`). `V1__alts_review_queue.sql`: `alts_review_queue` (JSONB extracted/decided fields, `status` pending→approved|corrected, `synced_at` reserved for the reverse-sync follow-up) + `alts_review_audit` (append-only).
- `pom.xml`: jOOQ codegen gained a second execution targeting `db/migration_internal` into `dev.parvum.serving.jooq.internal` — the Maven plugin supports per-execution `<configuration>`, confirmed by using it rather than assumed.
- `AltsReviewResource`: `GET /internal/alts/queue` (optional `status` filter), `GET .../queue/{id}`, `POST .../queue/{id}/approve`, `POST .../queue/{id}/correct` — each write records an audit row in the same transaction. A non-`pending` item can't be decided again (409).
- Design choice recorded in D-051, confirmed with the user before building: the reverse-sync back to Databricks is a land-file job (mirrors the existing fetch/land contract, reversed), not a direct Quarkus→Databricks write and not a break from "Postgres is always a disposable projection." This slice ships the queue mechanics only; the sync job is a follow-up commit.

**Verified:** `mvn verify` 26/26 green (9 new), Testcontainers Postgres. Real run against the local docker-compose database, not just automated tests: logged in, listed the seeded queue, corrected an item, confirmed `decidedFields`/`decidedAt` set correctly in the response, confirmed a second decide attempt on the same item is correctly rejected with 409.

**Not yet done:** the export-side queue loader (Databricks `silver_alts_documents` needs_review rows → `alts_review_queue`) and the reverse-sync job itself — both deliberately deferred to a follow-up slice, per D-051's small-reviewable-steps reasoning. The internal app's frontend for this queue is also still ahead.

## 2026-07-20 — Two LLM providers behind one interface (D-052)

**Done:**
- `extract.py`: new `LLMProvider` abstract base + `AnthropicProvider` (unchanged native Anthropic API) + `OpenRouterProvider` (OpenAI-compatible gateway, tool-schema translation, JSON-string argument parsing) + `build_provider(name, model)`. Default provider is now `openrouter` (`PARVUM_LLM_PROVIDER`/`--provider`), with `anthropic` available as an explicit override for a harder document — a real default change from D-049, made at the user's direction after the Anthropic Console billing wall.
- `.env.example`, `Makefile` (`make alts-extract` now provider-aware — checks whichever provider's key is actually needed), `.github/workflows/alts-extract.yml` (`workflow_dispatch` inputs for provider/model) all updated to carry the new plumbing through.

**Verified:** 59/59 tests green (17 new/changed), all against mocked SDK clients or a fake `LLMProvider` — zero real API cost, same discipline as D-049. Caught and fixed one real snag before it shipped: the installed `openai` SDK validates credential presence at *construction*, not call time, which broke a test that only wanted to check the default model string — fixed by resolving to a placeholder key when unconfigured rather than requiring a real one just to build the object.

**Not yet verified live for either provider:** the Anthropic blocker (D-049) is unresolved; OpenRouter is new this slice and has no live smoke test yet either — needs a working key for one of the two before extraction can be verified end to end.

## 2026-07-20 — Full Phase 6 pipeline verified live, and a real schema bug fixed (D-053)

**Done:**
- Fixed the tool schemas: `_AMOUNT_DESC` ("no currency symbol or thousands separators") now applied to every monetary field across all three tools, not just `call_amount` — a real batch run had shown every single capital-account statement failing self-consistency, traced to unformatted amounts (`"$750,000.00"`) that `Decimal()` couldn't parse.
- New `parvum_alts_hitl/parsing.py`: `parse_decimal()`, tolerating a stray `$`/comma as defense in depth — replaces three independent copies of `Decimal(str(value))` in `extract.py`, `validate.py`, `evaluate.py`.

**Verified live, closing out every "not yet verified" note from D-046 through D-052:**
- `make alts-extract`: 32/32 real documents extracted via OpenRouter (`anthropic/claude-haiku-4.5`).
- `make alts-eval`: **100% document exact-match rate, 100% field accuracy** against the generator's ground truth.
- Landed into the real Databricks volume; `alts_bronze_ingest`/`silver_alts` ran for real. `silver_alts_documents` routing, live: `capital_account_statement` 11 auto_accept / 9 needs_review, `capital_call` 1 / 7, `distribution` 2 / 2 — **14/32 (43.75%) auto_accept overall**, the pipeline's first real straight-through-processing number.
- The lopsided `capital_call` split (mostly needs_review) confirmed the cascading behavior D-050's integration test predicted: one early defect breaks the running-sum check for every later call in that fund too, even individually-clean ones — live evidence the checker behaves exactly as designed, not a red flag.

**Verified:** 59/59 tests still green after centralizing the parsing logic.

## 2026-07-22 — Alts review queue: the export-side loader (D-054)

**Done:**
- `export/src/parvum_export/review_queue_source.py`: `fetch_needs_review()` joins `silver_alts_documents` (`routing = 'needs_review'`) with `bronze_alts_extractions` (`fields_json`) over the Databricks SQL Statements API, reusing `gold_source.convert_rows` for the typed-value conversion.
- `export/src/parvum_export/review_queue_loader.py`: `load_review_queue()` — upserts keyed on `(fund_id, document)`, gated by `WHERE status = 'pending'` so a decided row is never touched by a reload; a pending row that drops out of the fresh needs_review set is flagged `stale = true` rather than deleted, un-flagged automatically if it reappears (D-054 weighs flag-vs-delete with the user before building).
- `serving/src/main/resources/db/migration_internal/V2__alts_review_queue_stale_flag.sql`: adds `stale boolean not null default false` to `alts_review_queue`. `AltsReviewResource.QueueItem` carries the new field.
- `export/src/parvum_export/load_review_queue.py`: new `parvum-load-review-queue` CLI, same shape as `export_gold.py` but targeting the single `internal` schema instead of iterating tenants.
- `export/src/parvum_export/databricks_auth.py`: `resolve_token()` extracted out of `export_gold.py` (now shared by both CLIs, rather than duplicated for the second one).
- `Makefile`: `make load-review-queue`.

**Verified:** `export` tests 29/29 (11 new — pure-Python join-row-shaping tests plus a real-Postgres suite against a throwaway schema migrated with the real `migration_internal` DDL, via a new `internal_schema` fixture in `conftest.py`). `mvn verify` 26/26 (`AltsReviewResourceTest`'s 9 tests unaffected by the added column; jOOQ codegen picked up `stale` automatically from the migration). `make lint`/`make fmt` clean across all four Python packages.

**Not yet done, deliberately:** no real needs_review data has been loaded from a live Databricks run yet this session (the loader's real-Postgres tests exercise the write-side logic directly against constructed `ReviewItem`s, not a live fetch) — a real `make load-review-queue` run against the live lakehouse is a natural next check once this merges. The review queue's frontend and the reverse-sync job (D-051's other two deferred pieces) remain unbuilt.

**Post-merge follow-up, done this session:** ran `make load-review-queue` for real against the live lakehouse — 18 real needs_review documents loaded (9 capital_account_statement + 7 capital_call + 2 distribution, matching D-053's live routing numbers exactly), JSONB `extracted_fields` confirmed round-tripping real content, a second run confirmed idempotent (still 18 pending, 0 stale). Local dev data truncated afterward.

## 2026-07-22 — Alts review-decision reverse-sync, and the Anthropic provider's first live call (D-055)

**Done:**
- `export/src/parvum_export/review_decision_source.py`: `fetch_unsynced_decisions()` reads every `approved`/`corrected` `alts_review_queue` row with `synced_at IS NULL`.
- `export/src/parvum_export/review_decision_sync.py`: `decision_payload()` (pure), `write_decision_files()` (one JSON per decision, staged locally), `mark_synced()` — only ever called after a real land succeeds.
- `export/src/parvum_export/sync_review_decisions.py`: new `parvum-sync-review-decisions` CLI, combining fetch → write → `databricks fs cp` (subprocess) → mark-synced in one run, the same combined shape D-054's loader used.
- `spark/bronze_alts_ingest.py`: third registration table, `bronze_alts_review_decisions`, extending the existing `discover`/`supersede`/`register` trio — no new notebook or job task, just a third landing subdirectory (`landing/alts/reviewed/`).
- `spark/silver_alts_documents.py`: driver-side dict lookup (matching its existing style) folds a decision, if any, into three new columns — `reviewed_status`, `final_fields_json`, `reviewed_at` — additively; `routing`/`cross_document_valid`/`validation_notes` are untouched, still the automated pipeline's own verdict.
- `Makefile`: `make sync-review-decisions`.

**Verified live, export half:** two real decisions made against local dev Postgres (an approve and a correct), `make sync-review-decisions` landed both JSON files to the real Databricks volume (confirmed via `databricks fs cat`) and marked both `synced_at`; a second run correctly reported "nothing to sync." `export` tests 36/36 (7 new). `make lint`/`make fmt` clean across all four Python packages. `databricks bundle validate` clean (no job-config changes were needed).

**Not verified live, Databricks half — and can't be until merge:** `alts_bronze_ingest` runs `main`'s notebook code via `git_source`, not this branch's local content (same constraint D-048 hit first). `bronze_alts_review_decisions` registration and the `silver_alts_documents` join are unverified against real data until this merges and the job runs post-merge.

**Post-merge follow-up, done this session:** deployed (`make deploy-job`, config unchanged, expected no-op) and ran `make run-alts-job` for real — `parvum-alts-ingest` TERMINATED SUCCESS. `bronze_alts_review_decisions` registered both real decisions from the export-side verification above, correctly. `silver_alts_documents` confirmed additive: exactly the 2 documents with a real decision show `reviewed_status`/`final_fields_json` populated, every other row (including same-named documents in the *other* fund — document names are only unique per fund, not globally, which the first check without `fund_id` in the query briefly and correctly surfaced) shows them NULL, and `routing` is unchanged at `needs_review` for both — the automated verdict, exactly as designed, sitting untouched next to the human one.

**Also this session:** the Anthropic Console credit blocker that stalled D-049 since 2026-07-20 was resolved (a small top-up). One real single-document call via `--provider anthropic` on `capital_call_01.pdf` succeeded (`claude-haiku-4-5-20251001`, confidence 0.98, self-consistent) and matched the earlier live OpenRouter extraction of the same document field-for-field. A full batch was deliberately not run to keep spend minimal — the provider is now confirmed working, not just plumbed.

## 2026-07-22 — The review queue's frontend (D-056)

**Done:**
- `internal/src/types.ts`: `QueueItem`/`QueueStatus`/`DocType` (mirrors `AltsReviewResource.QueueItem`).
- `internal/src/api.ts`: `fetchQueue()`, `approveQueueItem()`, `correctQueueItem()`.
- `internal/src/ReviewQueuePage.tsx`: new page — a filterable list (pending/approved/corrected/all) plus a detail panel per selected document: extracted fields as editable inputs (pending) or read-only decided values (`decidedFields`, if any), a validation-notes callout, and Approve/Save-correction actions. `stale` renders as its own badge, taking precedence over the status badge.
- `internal/src/App.tsx`: a `page` state + `.tabs` nav switching between Review Queue (new default) and Ops; Ops's data fetch is now lazy (fires once, on first visit to that tab).
- `internal/src/styles.css`: `.queue-layout`/`.queue-list`/`.queue-detail`/`.field-input`/`.queue-actions`/`.badge.neutral` — reuses existing card/table/badge tokens, no new design system.

**Verified:** `internal` tests 10/10 (4 new). `tsc --noEmit`, `vite build`, `prettier --check` all green. Live end-to-end: `make load-review-queue` loaded 18 real needs_review documents; the running serving API served them correctly through an authenticated session (confirmed via curl — real JSON, `stale` field present and typed correctly); the Vite dev proxy correctly forwarded an authenticated request through to serving. A leftover Java process from earlier in the session was found squatting on port 8080 and killed; a genuine local-environment issue was also hit and fixed — the JVM's default timezone reports as the deprecated alias `Asia/Calcutta`, which Postgres's JDBC driver sends verbatim and Postgres rejects (`FATAL: invalid value for parameter "TimeZone"`) — fixed for this session with `JAVA_TOOL_OPTIONS=-Duser.timezone=UTC`; worth a `-Duser.timezone=UTC` in the Maven wrapper's default args if this machine keeps hitting it.

**Not done this session:** no browser-automation tool was available, so the page was not visually confirmed by eye — verification stopped at the API/proxy layer plus the component test suite. Both dev servers were left running for a manual check. The reverse-sync's Postgres→Databricks direction now has a real UI in front of it, but nothing yet consumes `reviewed_status`/`final_fields_json` downstream — gold alts metrics in the client dashboard remains the next and last item on Phase 6's original list.

## 2026-07-22 — Review queue list: a real clipping bug from actually looking at it

The user's first real look at the page (localhost) found what the component tests couldn't: the status badge's text was getting cut off against the right edge of the list panel — "Pending" clipped mid-letter. Root cause was `overflow: hidden` on `.queue-list` (added to keep the table's corners inside the card's rounded border) combined with three columns (Document, Type, Status) too tight for 340px, so the badge's text wrapped onto a second line the `overflow: hidden` then sliced off. Fixed three ways together: dropped `overflow: hidden` (a clipping bug should never be silent again), added `white-space: nowrap` to `.badge` generally (the real fix — a status word should never wrap), and dropped the list's redundant "Type" column (already shown in the detail panel) into the fund-id subline, freeing enough width that the fix holds with margin rather than exactly at the wire. `internal` tests 10/10 (one updated for the merged subline text), build/format clean.

## 2026-07-22 — `internal/` gets the same deployment story as `web/`, and three parity gaps closed

`internal/` had been deployed once as a direct file upload, which left it diverging from `web/` in exactly the way D-045 had already fixed once for the dashboard: no Git connection, so a merge to `main` did not redeploy it. Brought to parity, and the rest of the app audited for other drift while there.

**Vercel (`parvum-internal`), now matching `parvum-dashboard` field for field:** Root Directory `internal` (was unset — the file upload had put `package.json` at the deployment root, which would have failed the moment a Git build looked for it in the repo root); Git connection to `ambarshukla/parvum`, production branch `main`; `VITE_API_BASE` as a project environment variable on production+preview. The Git link went through the API without the browser OAuth step D-045 needed, because the GitHub credential created for `parvum-dashboard` is account-wide and was reused (`gitCredentialId` is identical on both projects).

**The trap this closed:** the one-off upload had carried `VITE_API_BASE` in a `.env.production` file that exists only in that upload, not in the repo (`.env*` is gitignored). Connecting Git without also setting the project env var would have produced a build with no API base at all — the app would have silently fallen back to same-origin and been broken in a way that looks like a CORS or auth failure. Setting the env var was therefore part of the same change, not a follow-up.

**Verified, not assumed:** triggered a real Git-source deployment (`gitSource: {ref: main}`, sha `87f015b`) rather than another file upload, and confirmed from the built artifacts that the ECS API origin is compiled into the JS bundle (so the env var, not the absent `.env.production`, supplied it) and that the previous commit's clipping fix is present in the CSS (`.badge{white-space:nowrap}`, `table-layout:fixed`). The `parvum-internal-git-main-*` branch alias now exists, mirroring the dashboard's.

**Parity gaps closed in this repo:**
- `Makefile` gained `internal-install` / `internal-dev` — `web/` had `web-install`/`web-dev` since Phase 5 and `internal/` had nothing, so the documented way to run it was "cd internal && npm run dev" or nothing at all.
- `internal/README.md`'s "What's here" still said the Ops page and the review queue would "land on top of this in later slices" — both have since landed (D-044, D-056). Replaced with what the app actually does.

**One deliberate remaining difference:** `parvum-dashboard` stores `VITE_API_BASE` as a *sensitive* variable (write-only, unreadable afterwards); `internal`'s is a normal encrypted one. `VITE_API_BASE` is compiled into a public JS bundle, so marking it sensitive protects nothing and only makes the value impossible to read back when debugging a deploy — which is exactly what this session needed to do more than once. Left as-is rather than propagated; if the two are ever squared up, the honest direction is relaxing the dashboard's, not tightening this one.

**Not done (noted, not silently skipped):** neither project sets an Ignored Build Step, so a push touching only `internal/` still rebuilds `parvum-dashboard` and vice versa. Harmless (both builds are seconds and free at this scale), and fixing it means changing both projects together to avoid trading one divergence for another.

## 2026-07-22 — The source PDF beside the extraction (D-057)

**Done:**
- `serving/.../migration_internal/V3__alts_documents.sql`: `alts_documents` (fund_id, document, `content bytea`, byte_size, sha256, loaded_at), keyed `(fund_id, document)` — document names repeat across funds, so the fund has to be part of the key.
- `export/src/parvum_export/alts_document_source.py`: `fetch_document_index()` (SQL join of `bronze_alts_documents` × `silver_alts_documents` for the reviewable set, returning the volume path + landed sha256) and `download_document()` (Databricks Files API, `GET /api/2.0/fs/files{volume_path}`, refusing anything that doesn't start with `%PDF` so a truncated or error response can't be stored and surface later as an unreadable viewer).
- `export/src/parvum_export/alts_document_loader.py`: `load_documents()` — digest-gated upsert, `download` injected so the skip/fetch/replace logic is testable offline.
- `load_review_queue.py`: the same CLI now loads the queue *and* mirrors its documents; one command, so the two can't drift apart.
- `AltsReviewResource`: `GET /internal/alts/documents/{fundId}/{document}` streaming `application/pdf`, with the `Content-Disposition` filename sanitised (the value comes from a DB row, but a header built by concatenation shouldn't be where that assumption gets tested).
- `internal/`: `fetchDocumentPdf()` + a `DocumentViewer` that fetches the blob, renders it in an iframe via an object URL, and revokes the URL on change. `.queue-detail-body` is a two-column grid (fields | document) collapsing to one column under 1300px.

**Verified live, end to end:** probed the Files API *before* writing code against it (2131 bytes, `%PDF-1.4`), then confirmed the same document exits the serving API at exactly 2131 bytes with the magic intact — byte-level agreement across the whole chain. `make load-review-queue`: `18 referenced, 18 fetched` (37,412 bytes, all 18 confirmed to start with `%PDF` by SQL), then an immediate re-run reporting `18 referenced, 0 fetched` — the digest gate doing its job. `mvn verify` 29/29 (3 new), `export` 40/40 (4 new), `internal` 11/11 (1 new), lint/format clean everywhere.

**A constraint worth recording because it shaped the UI:** `InternalAuthFilter` requires a custom header on every `/internal/**` request and an `<iframe src>` cannot send one, so the viewer *had* to go via `fetch` → blob → object URL rather than pointing the frame at the endpoint. Discovering that after building the simple version would have meant rewriting it.

**Not done:** source-linking (click a field → highlight where it was read from). Genuinely larger — the extraction pipeline captures no positional data, so it needs a different PDF library, a re-extraction, value→position matching, and a real PDF renderer to overlay on. Scoped in D-057 rather than left as a vague "later".

## 2026-07-22 — The status badge, fixed properly this time, and a PDF that fits its pane

**The earlier clipping fix was half a fix, and a screenshot proved it.** Dropping `overflow: hidden` and adding `white-space: nowrap` stopped the badge *text* wrapping, but the fix also pinned the status column at a flat `width: 92px` under `table-layout: fixed`. A "Pending" badge needs ~86px of content box and the cell only offered 64px after padding, so the pill still ran past the card's right edge — the word was legible, the bubble around it was sliced. Replaced the magic number with `width: 1%` + `white-space: nowrap` (the shrink-to-fit idiom: a cell can't render below its content's minimum width, so the browser settles exactly there) and dropped `table-layout: fixed` so the document column takes the remainder. This is the shape of fix the problem actually wanted: "Corrected" is wider than "Pending", so *any* single fixed number clips one badge or wastes space on the other — the column has to size itself.

**PDF now fits the pane width** — `#view=FitH` on the iframe's source. In a half-width pane the browser's viewer was rendering at its default zoom and hiding the right-hand column behind a horizontal scrollbar, which is precisely where the figures a reviewer is checking live. A viewer that ignores the fragment falls back to its own default, so this costs nothing where it isn't supported.

**On the viewer itself, recorded because it's a real limitation and not obvious from the code:** rendering is the *browser's* built-in PDF viewer, not something this app ships. Every current desktop browser has one and needs no separately installed PDF software, so in practice a reviewer on a laptop always sees the document — but the app does not control the toolbar (the chrome in a screenshot is the browser's, which is why it looks unbranded), and mobile browsers handle inline PDF in an iframe inconsistently. Shipping PDF.js would make rendering identical everywhere and put the toolbar under our control, at roughly +350 KB gzipped on a bundle currently around 150 KB. Not taken: the reviewer tool is a desktop workflow and the tradeoff isn't worth it yet.

## 2026-07-22 — The PDF viewer becomes the app's own (D-058)

**Done:**
- `internal/src/components/PdfViewer.tsx`: pdf.js rendering onto app-owned canvases, replacing the `<iframe>`. Own toolbar (page count + zoom steps 75%–300%) built from existing tokens; fit-to-pane by default via a `ResizeObserver` on the wrapper (never on the canvas host, so appending pages can't feed back into the observer); HiDPI-aware rasterisation; pages composed in a detached fragment and swapped in whole.
- `pdfjs-dist` imported dynamically, promise cached at module scope — the main bundle moved 150.67 → 152.05 KB gzipped, with pdf.js in its own 126.73 KB chunk fetched on first document open.
- `vite.config.ts`: a small `pdfjs-standard-fonts` plugin copying `pdfjs-dist/standard_fonts` into `public/` at `buildStart`; the directory is gitignored rather than vendored. `tsconfig.json` gains the `node` type lib (for the config file only — noted in a comment that `src/` is browser code).
- `ReviewQueuePage`: `DocumentViewer` now fetches bytes and hands an `ArrayBuffer` to `PdfViewer`; the object-URL dance is gone with the iframe.
- README: the internal app is now listed alongside the dashboard under **Live**, with a line on why it's password-gated.

**The bug the probe caught before any of it shipped:** running pdf.js against a real generated document (not a fixture) printed `Ensure that the standardFontDataUrl API parameter is provided`. The documents reference `Helvetica`/`Helvetica-Bold` with no `FontFile` — base-14 fonts, which PDF lets a document reference without embedding because the viewer supplies them. Browsers' built-in viewers have them; pdf.js ships the data but doesn't bundle it. Left unconfigured, **every page would have rendered with no text** — indistinguishable from a corrupt document, and invisible to a mocked test. This is the second time this slice that probing the real thing first (rather than after) turned a silent failure into a config line.

**Verified:** pdf.js parses all three real document types (1 page, 612×792pt, real text). `/standard_fonts/FoxitSans.pfb` served 200 at the exact URL the viewer requests; all 16 font files emitted to `dist/`. `internal` 11/11 (pdf.js mocked at the module boundary — jsdom has no canvas, so a test that appeared to rasterise would only be testing the mock), typecheck/build/format clean.

**Not verified by eye:** no browser-automation tool is available in this session, so the rendered output hasn't been looked at directly — the evidence is that pdf.js parses these exact documents, the font data resolves, and the wiring is under test. Worth a glance before relying on it in a demo.

**2026-07-23 addendum:** the user looked at the pdf.js viewer in a real browser and confirmed it renders correctly, closing the one gap D-058 flagged as unverified.

## 2026-07-23 — A demo link that logs a viewer in without a shared password (D-059)

**Done:**
- `serving/src/main/resources/application.properties`: new checked-in `parvum.internal.demo-password` default (`parvum-showcase`) — public by design, unlike the real password/session-secret above it which fail closed with no default.
- `AuthResource.login()`: accepts either the real password or the demo password, both via constant-time compare.
- `internal/src/api.ts`: `demoLogin()` wraps the existing `login()` with the (frontend-side, equally public) demo constant.
- `internal/src/App.tsx`: on mount, a `?demo=1` query param triggers `demoLogin()` instead of the normal `checkSession()` check, then strips the param via `history.replaceState` so it doesn't linger in the address bar.
- README: the internal-app line now points to `parvum-internal.vercel.app/?demo=1` as the no-friction entry point, alongside the plain URL.

**Why not just remove the login:** `InternalAuthFilter` gates everything under `/internal/**` by path prefix, including the review queue's `approve`/`correct` mutation endpoints — removing auth entirely would leave those open to the public internet, not just the page. This keeps every request, demo or not, behind a real session; only how a viewer *obtains* one got easier.

**Verified:** `serving` 30/30 (new: demo password logs in and returns a valid session cookie); `internal` 12/12 (new: a `?demo=1` load reaches the signed-in shell with no login screen shown, and the URL is clean afterward). `mvn verify` and `internal`'s format/typecheck/build all clean.

## 2026-07-23 — Alts join the client dashboard's wealth number (D-060)

**Done, across all four layers:**
- `spark/silver_alts_documents.py`: two new columns, `account_id` (from the extracted `FundCommitment.account_id` — the join key into `silver_account_owners`, the same one every other gold table uses) and `confirmed_fields_json` (the extraction's own fields when `routing` is `auto_accept`, `final_fields_json` once a `needs_review` document is decided, NULL while still awaiting review). Only additive columns — the routing/review columns keep meaning exactly what they meant before.
- `spark/gold_reports.py`: a new "small data, computed in Python" section (same pattern as the FX and IRR sections) turns confirmed alts documents into two things — **`gold_alts_holdings`** (owner-prorated commitment/called/distributed/unfunded/NAV/MOIC per client per fund, the private-markets analogue of `gold_top_holdings`) and **`alts_daily`** (a per-client, per-date NAV series, forward-filled from the most recent confirmed capital account statement, reused by both `gold_client_wealth` — new `alts_usd` column, folded into `total_wealth_usd` — and `gold_asset_allocation` — new `'Alternatives'` class, named to match the color slot `web/src/palette.ts` already reserved for it).
- `serving`: `V5__alts.sql` (additive — `ALTER TABLE client_wealth ADD COLUMN alts_usd`, new `alts_holdings` table; V1-V4 untouched, since editing an already-applied Flyway migration breaks its checksum in every environment that ran it). `ProjectionResource`: `WealthRow` gains `altsUsd`; new `GET /tenants/{id}/alts-holdings`.
- `export`: `gold_alts_holdings` added to `GOLD_TABLES`/`PROJECTION_TABLES` — the pipeline is fully generic over the table list, so this was the entire change.
- `web`: new "Alternatives" tab (fund-level detail table, a `pendingReviewDocuments` badge surfacing what's deliberately excluded) and a "Private markets" tile on Overview. `format.ts` gains `multiple()` (MOIC as "1.44x").

**Only confirmed values count.** A document still sitting in `needs_review` with no human decision contributes nothing to any figure — the same DQ-honesty stance the rest of gold takes. `pending_review_documents` makes that omission visible instead of silent.

**The forward-fill's real edge case, handled on purpose:** alts statements go back to 2024 (`generate.py`'s `FUND_UNIVERSE`, ten quarters of history); the custodial feed's wealth-reporting window is much shorter and more recent. A naive forward-fill keyed only to dates already in `silver_position_owners` would miss any statement that landed *before* the window starts, reading alts as \$0 for the whole window instead of the last confirmed mark. `alts_daily` unions in the statement dates before filling, then restricts back down to the wealth date grid — so a statement outside the window still seeds it correctly.

**Named, not hidden:** NAV updates quarterly, wealth is reported daily. On the day a statement's date falls inside the window, `daily_twr_return` will show a real, not fake, jump — a private-markets mark landing all at once, the same "flat-then-a-jump" shape the 13F price data already produces elsewhere in this project.

**Verified:** `export` 41/41 (2 new: `alts_usd` round-trips through `wealth_row`, nullable `inception_date`/`as_of`/`moic` round-trip through `alts_holdings`). `mvn verify` 32/32 (2 new: `alts_usd` on the wealth endpoint, `alts-holdings` returns `[]` for an empty tenant not 404). `web` 9/9 (2 new: `multiple()` formatter, the Alternatives tab's fund detail + pending-review badge), typecheck/build/format clean. `make lint`/`make test` clean across all four Python workspace packages.

**Not yet verified: the actual live Databricks numbers.** Every check above is local/mechanical — real syntax, real Postgres round-trips, real HTTP responses against seeded fixtures. The Databricks job that would run these two modified notebooks pulls its code from `main` via `git_source` at run time (D-018/D-058's lesson), so it cannot see an unpushed branch's changes; there is no way to exercise `gold_alts_holdings`/`alts_daily` against the real lakehouse before this branch is on GitHub. Worth a real run — checking the actual MOIC values, whether the forward-fill's date-union logic behaves as designed against the real statement/wealth-date overlap, and whether `parse_decimal` handles every real extracted string — before treating the numbers as trustworthy in a demo.

## 2026-07-23 — D-060's live run found the bug the local checks couldn't (`gold` task failing on main)

Ran the two jobs post-merge (`make run-alts-job` then `make run-job`) exactly as flagged in the prior entry. `alts_bronze_ingest` confirmed the silver layer correct against real data — `account_id` resolved right (`X4478210`/`FQ5521`, matching `generate.py`'s `FUND_UNIVERSE`), `confirmed_fields_json` populated for every `auto_accept` row and every decided `needs_review` row, NULL for the rest. `bronze_ingest`'s `gold` task then failed: `KeyError: 'fund_id'`.

**Root cause:** `fund_id` is never a key inside a document's extracted `fields` JSON — `parvum_alts_hitl.extract.process_directory` attaches it alongside `fields` from the landing directory name (`record["fund_id"] = fund_dir.name`), not from anything the LLM was asked to read off the page. `gold_reports.py`'s new alts section parsed `confirmed_fields_json` and tried to group by `_fields["fund_id"]`, which was never going to be there for *any* document, confirmed or not — not specific to a review correction as first suspected. No local check caught this because nothing in `export`/`serving`/`web`'s test suites exercises `gold_reports.py` itself; only a real run against real `bronze_alts_extractions` rows could have (and did).

**Fix:** group by the silver row's own `fund_id` column (`SELECT fund_id, doc_type, confirmed_fields_json FROM silver_alts_documents ...`), never by parsing it back out of the JSON. `account_id`/`fund_name` are untouched — both are real LLM-extracted fields, required by every doc type's tool schema, and confirmed preserved through a reviewer correction (`internal/src/ReviewQueuePage.tsx`'s `handleCorrect` resubmits every original key, not a sparse diff).

**Lesson for next time this pattern comes up:** a field a pipeline stage *injects* (not one the data source itself carries) has to be sourced from wherever it was injected, every time downstream — parsing it back out of a JSON blob that never had it is an easy, silent-until-runtime mistake, and the `bronze_alts_extractions`/`silver_alts_documents` split makes exactly this kind of column real easy to reach for instead.

## 2026-07-23 — A harder alts corpus: three funds, three templates, two currencies (D-061)

**Done:**
- `alts-hitl/src/parvum_alts_hitl/render.py`: a `DocTemplate` dataclass (title wording, field labels, money/date formatters, light visual styling) with three instances — `PLAIN` (the original, kept as the default), `DRAWDOWN` (vocabulary drift only), `EURO` (European number/date formatting on a genuinely EUR-denominated fund). Every render function takes an optional `template` param defaulting to `PLAIN`, so every existing test kept passing unmodified.
- `model.py`/`book.py`: `currency` threaded onto every notice type from `FundCommitment.currency` (already present).
- `generate.py`: a third fund, `FUND-EU01` ("Alpenrose Capital Fund III", €1,500,000, rolls up to `FQ5521` alongside Bramwell), and a `_TEMPLATE_BY_FUND` map wiring each fund to its template.
- `extract.py`: every tool schema gains a required `currency` field; date field descriptions now warn the model the source may use a non-US convention and to convert, not assume.
- `spark/silver_alts_documents.py`: new `currency` column, sourced from the original extraction's own fields (same reasoning as `account_id` — reliable even pre-review).
- `spark/gold_reports.py`: `gold_alts_holdings`'s money fields now convert native-currency amounts to USD via `fx`, at the rate for each figure's own as-of date; `gold_client_wealth`'s alts fold-in and `gold_asset_allocation`'s `'Alternatives'` class convert the same way per statement date; the FX date-range query widened to cover the alts corpus's full history, not just the custodial feed's window.
- `reference/src/parvum_reference/ecb.py`: `_FLOOR` moved from 2026-01-01 to 2024-01-01 to actually cover that widened range.
- `serving`: `V6__alts_currency.sql` (additive — V5 is already applied) adds `alts_holdings.currency`; `ProjectionResource`'s `AltsHoldingRow` carries it through.
- `web`: the Alternatives tab annotates a non-USD fund's row with `(EUR)`; a USD fund gets no annotation.

**A real bug, found by actually looking at the output:** the first generated EUR-fund PDFs extracted with `�` in place of both the `€` symbol and an accented character in the letterhead — reportlab's standard Helvetica font has no embedded ToUnicode mapping for either, so `pypdf` (the same extraction path production uses) silently produced U+FFFD. Fixed by using `EUR` as a text prefix instead of the glyph (which also happens to be the exact ISO 4217 code the schema now asks for) and an ASCII-only letterhead for the EURO template. The same root cause turned out to already be sitting in the *original* PLAIN/DRAWDOWN templates too — an em-dash in the statement title, never previously noticed because nothing reads that field into a schema. Fixed there as a one-line drive-by. All 48 regenerated documents were scanned by hand afterward for stray replacement characters; none found.

**A second real blocker, environmental rather than a code bug:** re-fetching ECB's FX history to the new, wider floor requires a network call to `ecb.europa.eu` that this session could not complete — Python's `urllib`, then `curl` with increasing timeouts and retries, all had the connection reset mid-download. The same session earlier hit a blocked `.exe` spawn from a Windows Application Control policy, so this is most likely the same class of environment restriction rather than anything wrong with the fetch code. **Consequence: `make fetch-fx && make land-fx` need to succeed once, from a machine with a working path to ECB, before the gold job can run past the widened FX range without `fill_forward` raising** ("no rate on or before" the corpus's earliest alts date).

**Verified:** `alts-hitl` 65/65 (6 new tests), `reference` 31/31 (one fixture date moved to stay below the new floor), `export` 41/41, `mvn verify` clean (V6 migration applies across all three schemas), `web` 10/10, `make lint`/`make test` clean across all four Python packages. The regenerated corpus (48 documents, 3 funds) was inspected by hand: all three templates render with the right vocabulary/formatting, all extract clean.

**Not yet verified against live Databricks data** — same D-018/D-058/D-060 constraint (the job runs `main` via `git_source`), compounded this time by the FX-fetch blocker above. Both need to clear before the real numbers — actual MOIC, whether the widened forward-fill behaves as designed against the real 2024-2026 statement history — can be trusted.

## 2026-07-23 — D-061's live run found a second bug: multi-fund clients lost a fund's NAV silently

Landing the real corpus (real ECB history sourced by hand from ECB's Data Portal export after `ecb.europa.eu`'s zip endpoint proved unreachable from this network entirely — every automated fetch attempt, `.exe` and `python -c` alike, had the connection reset; a browser download of the equivalent SDMX CSV worked where nothing else did) and running the full pipeline (`alts_bronze_ingest` then `bronze_ingest`) surfaced a second real bug, this time in the wealth fold-in rather than the extraction realism itself.

**Symptom:** `gold_alts_holdings` correctly showed Okafor holding all three funds, including the new Alpenrose (EUR). But `gold_client_wealth.alts_usd` for Okafor was unchanged from before Alpenrose existed — the new fund's NAV never reached the headline number.

**Root cause:** `alts_nav_points` grouped by `(client_id, statement_date)`, summing every fund's NAV that happened to report *on that exact date*. `alts_daily`'s forward fill then took the single most recent date with any row and carried that row's value forward. Fine when a client holds one fund, or when every fund a client holds reports on the same schedule — wrong the moment they don't: Bramwell and Meridian's Okafor-share both had their latest confirmed statement on 2026-06-30, but Alpenrose's was 2025-12-31. The forward fill picked 2026-06-30 (later), which only ever had a row for Bramwell+Meridian — Alpenrose's still-current mark was never summed in, because it lived on a date the per-date grouping had already collapsed away.

**Fix:** forward-fill *per (client, fund)* first, then sum across a client's funds second — never the other way round. `alts_nav_points` now stays at fund grain; `alts_daily` builds a date grid per (client, fund) pair (wealth dates × each fund the client holds, unioned with that fund's own statement dates), fills each fund's series independently with `LAST_VALUE`, then `GROUP BY as_of, client_id` sums the filled per-fund values. Re-verified live: Okafor's `alts_usd` moved from $2,479,845.54 (Bramwell + Meridian only) to the correct sum including Alpenrose's forward-filled contribution.

**Why local tests didn't catch this:** nothing in `export`/`serving`/`web`'s suites exercises `gold_reports.py`'s own SQL, and the D-060 session's manual verification only ever had two funds, both landing on the same statement dates by coincidence (same vintage year, same quarter schedule) — the exact condition that hides this class of bug. Only a client actually holding two funds with genuinely different statement schedules exposes it, which the corpus didn't have until D-061 added Alpenrose.

## 2026-07-23 — The review queue and its PDFs go stale without a laptop (D-062)

After `export-gold` was run manually this session, the internal app still showed the old-template alts PDFs. Diagnosis: `export-gold` only ever reloads the four wealth/allocation/performance-shaped projections — the review-queue schema and the mirrored PDF bytes (D-057) are filled by two entirely separate `make` targets, `load-review-queue` (D-054) and `sync-review-decisions` (D-055), and neither had ever been automated. Both were still local-only, meaning every future needs_review document and every reviewer decision would sit invisible on the live app until someone happened to run them from this machine — exactly the drift the user flagged as unacceptable going forward.

**Done:**
- New workflow `.github/workflows/sync-review-queue.yml` — same OIDC-to-AWS/SSM-password pattern as `export-gold.yml`, weekday schedule offset ten minutes later (no ordering dependency, just log hygiene), plus `workflow_dispatch`. One job, two steps: `sync-review-decisions` then `load-review-queue` (`if: always()`, so a sync hiccup never blocks the queue/PDF refresh — the two touch disjoint state).
- `databricks.yml`: widened `parvum-alts-ingest`'s file-arrival trigger from `landing/alts/raw/` to the `landing/alts/` parent. Found while wiring the new workflow: `bronze_alts_ingest.py` has always read three subdirectories (`raw/`, `extracted/`, `reviewed/`), but the trigger only ever watched the first — a decision landed in `reviewed/` (what the new scheduled `sync-review-decisions` step now does) would never have fired the job at all, automated or not. The exact D-018 blind spot, just not yet found in this corner. Config-only change, so per this project's own deploy-order rule it was safe to `databricks bundle deploy` ahead of merge — `databricks bundle validate` confirmed it, live redeploy recorded once run.
- `docs/DECISIONS.md`: D-062.

**Verified:** `databricks bundle validate` clean. Not yet verified against a live scheduled firing (first run is the next weekday 08:10 UTC after merge, or an immediate manual dispatch) — recorded once confirmed.

**Update, same day — merged and run for real via `workflow_dispatch`, verified end to end.** Logged into the live API the same way a browser session would (`POST /internal/auth/login` with the demo password plus the `X-Parvum-Internal` CSRF header the filter requires) and pulled the review queue directly: all three funds present, `FUND-EU01`'s rows carrying `"currency": "EUR"` fields, confirming `load-review-queue` picked up the full D-061 corpus. Fetched two PDFs back out of Postgres (`GET /internal/alts/documents/{fundId}/{document}`) and extracted their text with `pypdf` — the same library the extraction pipeline itself uses — rather than just checking the files existed: `FUND-EU01/capital_call_04.pdf` opened with the `EURO` template's letterhead ("Continental Fund Administration Ltd"), `30/06/2025`-style dates, and `EUR 150.000,00` formatting; `FUND-VC01/capital_call_04.pdf` opened with the `DRAWDOWN` template's vocabulary ("Drawdown Notice", "Drawdown Amount", "Cumulative Drawn"). No U+FFFD in either — the D-061 encoding fix holds in production. Both the sync-decisions and load-review-queue steps completed without error.

## 2026-07-24 — Aldergate/Hartwell gets its own alts fund (D-063)

The user caught this ahead of sharing the demo link externally: the client dashboard defaults to Aldergate (Hartwell), and Aldergate's Alternatives tab was empty — all three existing alts funds rolled up to Stonefield-owned accounts, so Hartwell genuinely had zero private-fund exposure. Not a bug, but a bad first impression for anyone opening the link cold.

**Done:**
- `alts-hitl/src/parvum_alts_hitl/generate.py`: added `FUND-PE02` ("Wraithmoor Endowment Partners III", $3,000,000 USD) to `FUND_UNIVERSE`, rolling up to `FQ9007` — the account owned outright by the Hartwell Family Foundation, chosen over the Trust-owned accounts for its single-owner simplicity. Reuses the `PLAIN` template. Appended last, so the existing three funds' `fund_index` (and therefore every seeded defect decision) is unchanged.
- `docs/DECISIONS.md`: D-063.

**Verified, same session, end to end against live production:**
- `alts-hitl` 65/65 (parametric over `FUND_UNIVERSE`, no hardcoded fund count — no test changes needed).
- Regenerated all 64 documents; diffed extracted *text* (not raw bytes — reportlab stamps a real `CreationDate`/`ModDate` per run) against a same-session control regeneration: the three existing funds' content is byte-for-byte identical, only `FUND-PE02`'s 16 documents are new.
- Landed `FUND-PE02`'s raw PDFs to the alts volume; extracted via `--provider anthropic` (`claude-haiku-4-5-20251001`): 16/16 documents, 100% field accuracy and exact-match against the generator's own ground truth.
- Landed the extracted JSON and ran `alts_bronze_ingest` (already-merged, fund-count-agnostic — no spark changes needed): 8/16 documents routed `auto_accept` (including the latest, 2026-06-30, statement), 8 `needs_review`.
- Ran `parvum-ingest` (bronze → silver → dq_recon → gold, also unmodified) to fold confirmed documents into gold: `gold_client_wealth` for `CLI-HARTWELL` now carries `alts_usd = $1,859,884.15`; `gold_alts_holdings` shows `FUND-PE02` at MOIC 4.13x, 7 documents still pending review.
- Manually dispatched `export-gold.yml` (today's scheduled 08:00 UTC run predated this data) and confirmed against the live production API: `GET /tenants/aldergate/wealth` → `altsUsd: 1859884.15`, `GET /tenants/aldergate/alts-holdings` → `FUND-PE02` present with the same NAV/MOIC as the lakehouse. `GET /tenants/stonefield/wealth` → Okafor/Reyes figures unchanged from before this change, confirming the addition is genuinely additive in production.

**A session-local environment issue, unrelated to the code change:** the project's `uv`-managed Python 3.12 interpreter (and a Chocolatey-installed one) hit a newly-appeared Windows Application Control policy blocking their own `_socket` DLL — would have blocked `pytest`, LLM extraction, and `export-gold` outright. The officially-signed system Python was unaffected. Worked around for this session only by building a throwaway venv on the system interpreter (`uv venv --python "C:\Python314\python.exe"`) and installing the same dependencies into it; nothing in the repo depends on this, and it's worth a closer look in a future session since it will otherwise block routine `make test`/`make lint` work going forward.

## 2026-07-28 — Gold-layer detail behind the reconcile badge and the alts pending chip (D-064)

The user opened the client dashboard and pointed at two spots that state a verdict with no way to interpret it: "Reconciliation variance" (a bare boolean-derived badge) and "N pending review" (a bare count, no real tooltip). First PR of a two-PR slice — this one is the gold layer only; serving/export/web land on top once this is merged.

**Done:**
- `spark/gold_reports.py`: `gold_client_wealth` gains `reconcile_break_accounts` (count of this client's accounts failing `dq_cash_integrity.conformed_consistent` on this date) and `reconcile_variance_usd` (this client's ownership-prorated share of those accounts' `|delta_conformed|`, converted to USD), computed in the existing `quality` CTE. `gold_alts_holdings` gains `pending_review_doc_types` (distinct pending `doc_type`s, comma-separated) and `pending_review_latest_period` (latest `period_end` among pending statements), computed alongside the existing `pending_review_documents` count from the same `silver_alts_documents` query rather than collapsing straight to `COUNT(*)`.
- `docs/DECISIONS.md`: D-064.

**Verified:** `databricks bundle deploy` + `databricks bundle run bronze_ingest` (the full `parvum-ingest` job) ran clean against the *current* `main` — deploy/run mechanics confirmed working, auth via the `dbc-8a8be026-0247` CLI profile (the `parvum` profile's cached credentials had gone stale; `databricks current-user me --profile dbc-8a8be026-0247` is the one that works this session). That run necessarily executed the pre-change notebook, since `parvum-ingest`'s tasks pull from `main` via `git_source` (D-018) — confirmed directly by querying `gold_client_wealth` for the new columns immediately after and getting `UNRESOLVED_COLUMN`. **A live run against the actual new columns is owed post-merge**, same structural gap D-060/D-061/D-062 already recorded for notebook-content changes.

## 2026-07-28 — Serving/export/web carry the reconcile and alts-pending detail through to the dashboard (D-064, part 2)

Second PR of the two-PR slice; stacked on the gold-layer PR above. Plumbs `reconcile_break_accounts`/`reconcile_variance_usd` and `pending_review_doc_types`/`pending_review_latest_period` from Postgres through jOOQ and the API to the two dashboard spots that prompted the whole slice.

**Done:**
- `serving/src/main/resources/db/migration/V7__reconcile_alts_detail.sql`: additive migration, same pattern as V2-V6 — two new `client_wealth` columns (`not null default 0`), two new nullable `alts_holdings` columns.
- `serving/.../api/ProjectionResource.java`: `WealthRow` and `AltsHoldingRow` records gain the four fields; jOOQ regenerates its typed getters from the new DDL automatically (no hand-written jOOQ classes to touch).
- `export/src/parvum_export/gold_source.py` and `loader.py` needed **no code changes** — both are fully column-name-driven (`SELECT *` + a manifest-typed `GoldTable`, then a by-name `INSERT`), so new gold columns just flow through. Confirmed by reading both files, not assumed.
- Tests updated at both layers to actually exercise the new fields rather than rely on that pass-through going untested: `ProjectionEndpointsTest` gives Stonefield/Okafor a real reconcile break (1 account, $2,480.15) so a FALSE `booksReconcile` has real detail behind it in an assertion, not just in the schema; `export/tests/test_loader.py`'s `wealth_row`/`alts_holding_row` helpers grew optional params for the new columns, with one non-default case each round-tripped through real Postgres.
- `web/src/types.ts`: the four fields added to `WealthRow`/`AltsHoldingRow`.
- `web/src/ClientDashboard.tsx`: `ReconcileBadge` now renders `Reconciliation variance · 1 of 3 accounts · $2,480` (was just the bare label) with a fuller explanation in its `title`; the alts pending chip now renders `N pending review · <doc types> · through <date>` (was just the bare count) with its own `title`. `ownedAccounts.length` (already computed for the Ownership tab) supplies the badge's account denominator — no new data fetch needed.
- `web/src/ClientDashboard.test.tsx`: new test asserting the reconcile badge's account count and dollar variance; the existing pending-review test tightened to assert the doc types and period, not just the count.

**Verified:**
- `mvn verify`: 31/31 (clean, including Spotless). Hit the known local `Asia/Calcutta`/Postgres timezone mismatch (`FATAL: invalid value for parameter "TimeZone"`) — same fix as before, `JAVA_TOOL_OPTIONS=-Duser.timezone=UTC`.
- `export`: 41/41 against real local Postgres (`make up`), migrated with the actual V7 DDL. Ran via a throwaway system-Python venv (`export/.venv-sys`) — the `uv`-managed interpreter still hits the documented Application Control block. `ruff format`/`ruff check` clean (ruff itself is a native binary, unaffected by the Python DLL block).
- `web`: 11/11 tests, `tsc --noEmit` clean, `vite build` clean, `prettier --check` clean.
- **Visually confirmed in a real browser**, not just asserted in tests: `make up` (Postgres) + `make serving-run` (Quarkus dev, applied V7 live) + `make web-dev`, then seeded a synthetic reconcile break and a synthetic pending alts document directly into local Postgres (real gold doesn't have these columns' data yet — see the gold-layer PR's note) via `docker exec ... psql`, drove the app with a throwaway Playwright install (`chromium-cli` wasn't available this session), and screenshotted both spots: the badge reads "Reconciliation variance · 1 of 2 accounts · $1,875" for Okafor, the alts chip reads "1 pending review · capital_account_statement · through 30 Sept 2026" for Meridian Capital Partners IV. Zero console errors. The synthetic seed rows were reverted afterward so local Postgres matches real exported data again.
- Real production numbers for both spots are still owed: they depend on the gold-layer PR merging, `make run-job`, and `export-gold` — recorded as owed on that PR, not repeated here.

**Update, same day — both PRs merged, run for real, verified end to end against live production.** `git pull`, `databricks bundle deploy` + `databricks bundle run bronze_ingest` against merged `main` (auth via `--profile dbc-8a8be026-0247`): `parvum-ingest` succeeded, bronze → gold. Queried the lakehouse directly and got real, non-placeholder numbers on both new column pairs — proof this isn't just schema-shaped, the SQL actually computes something:
- `gold_client_wealth`: Hartwell `books_reconcile=false, reconcile_break_accounts=1, reconcile_variance_usd=$22.50` (a small, real cash-integrity gap on one account) — Okafor and Reyes both clean (`0`/`$0.00`).
- `gold_alts_holdings`: every fund shows real pending detail, e.g. Hartwell/Wraithmoor `pending_review_documents=7, pending_review_doc_types='capital_account_statement, capital_call, distribution', pending_review_latest_period=2025-12-31`.

User manually dispatched `export-gold.yml` (today's scheduled run predated the new gold data). Confirmed against the live production API:
- `GET /tenants/aldergate/wealth` → Hartwell `booksReconcile: false, reconcileBreakAccounts: 1, reconcileVarianceUsd: 22.5` — matches the lakehouse exactly.
- `GET /tenants/stonefield/wealth` → Okafor/Reyes both `booksReconcile: true, reconcileBreakAccounts: 0` — clean, as expected.
- `GET /tenants/aldergate/alts-holdings` → Wraithmoor Endowment Partners III carries `pendingReviewDocuments: 7, pendingReviewDocTypes: "capital_account_statement, capital_call, distribution", pendingReviewLatestPeriod: "2025-12-31"` — matches the lakehouse exactly.

The whole D-064 slice — user complaint → gold columns → serving/export/web → merge → live production — is now closed with real numbers behind both dashboard spots, not just the synthetic ones used to visually verify the UI pre-merge.

## 2026-07-28 — The per-account drill-down D-064 deferred, and dropping the doc-type taxonomy from the client view (D-065)

Live within hours of D-064 shipping, the user pushed back on both spots it had just fixed: the reconcile badge's "1 of 3 accounts · $23" didn't say *which* account, and the alts chip's "7 pending review · capital_account_statement, capital_call · through 31 Mar 2026" exposed this project's internal document taxonomy to a wealth client who has no reason to know it.

**Done:**
- `spark/gold_reports.py`: new table `gold_reconciliation_exceptions` — one row per (client, account) currently failing the conformed cash check, latest date only (baked in, same pattern as `gold_top_holdings`), with a *signed* USD/native delta. Removed `gold_alts_holdings.pending_review_doc_types` entirely (added in D-064, dead once the client chip stops showing it).
- `serving/.../V8__reconciliation_exceptions.sql`: new `reconciliation_exceptions` table; drops `alts_holdings.pending_review_doc_types`. New `/tenants/{id}/reconciliation-exceptions` endpoint + `ReconciliationExceptionRow` DTO; `AltsHoldingRow` loses `pendingReviewDocTypes`.
- `export`: `gold_reconciliation_exceptions` added to `GOLD_TABLES`/`PROJECTION_TABLES` — the one place in this slice that needed real code (unlike D-064's additive columns, a brand-new table isn't absorbed for free by the column-name-driven loader).
- `web/src/ClientDashboard.tsx`: `ReconcileBadge` is now a real `<button>` (fixes the "tooltip only fires on the dot" report as a side effect — the whole pill is one hoverable/clickable target) that toggles an inline panel listing each broken account and its signed delta. The "ok" state stays a plain `<span>` — nothing to click into. The alts chip drops doc-type enumeration for plain language: "Newer figures pending · through 31 Mar 2026."
- `docs/DECISIONS.md`: D-065 (records the reversal of D-064's own "defer this to the internal app" call, honestly — the assumption behind that deferral didn't survive contact with a real user reacting to the shipped feature).

**Verified:**
- `mvn verify` 32/32 (new test: `GET /tenants/{id}/reconciliation-exceptions` names the account and signed delta behind a real seeded break; an empty tenant returns `[]`, not 404).
- `export` 42/42 (new test round-trips a *negative* signed delta through real Postgres, proving the column isn't silently assumed unsigned; `empty_other_tables()`'s existing tail-slice convention for new tables — insert early, never append at the end — followed for the new table too).
- `web` 12/12 (new test: the account panel is absent until the badge is clicked, present with the right account id and dollar amount after; the pending-review test now asserts the doc-type string is *absent*, not just that the date is present). `tsc --noEmit`, `vite build`, `prettier --check` all clean.
- **Visually confirmed in a real browser**, same technique as D-064 (synthetic rows seeded into local Postgres via `docker exec ... psql`, since gold doesn't have this table's real data pre-merge; throwaway Playwright install in the scratchpad; reverted after): clicking "Reconciliation variance · 1 of 2 accounts · $1,875" reveals a panel reading "Accounts behind this variance / X4478210 · $1,875" — no tooltip precision needed. The alts chip renders "Newer figures pending · through 30 Sept 2026" with no document-type text anywhere on the page. Zero console errors on either screenshot.
- Real production numbers for the new table are owed post-merge, the same structural gap (`git_source` pulls `main`) recorded on every prior gold-layer change in this project.

**Update, same day — merged, run for real, verified end to end against live production.** `git pull` + `databricks bundle deploy` + `databricks bundle run bronze_ingest` against merged `main`: `parvum-ingest` succeeded. Queried `gold_reconciliation_exceptions` directly — one real row: Hartwell / account `60018852` / USD `22.50` — the exact account and dollar figure behind the aggregate `reconcile_break_accounts=1, reconcile_variance_usd=$22.50` that D-064 already put on the badge. Confirmed `gold_alts_holdings`'s column list no longer includes `pending_review_doc_types` (17 columns, ending `pending_review_latest_period, rebuilt_at`).

User dispatched `export-gold.yml`. Confirmed against the live production API:
- `GET /tenants/aldergate/reconciliation-exceptions` → `[{accountId: "60018852", currency: "USD", deltaNative: 22.5, deltaUsd: 22.5, ...}]` — matches the lakehouse exactly. Clicking the reconcile badge on the live site now reveals this exact account and figure.
- `GET /tenants/aldergate/wealth` → `reconcileBreakAccounts: 1, reconcileVarianceUsd: 22.5` unchanged from before this change, confirming the new endpoint is additive, not a replacement.
- `GET /tenants/aldergate/alts-holdings` → no `pendingReviewDocTypes` field in the response; `pendingReviewLatestPeriod: "2025-12-31"` intact.

D-065's own live-verification gap is closed. The whole arc for this slice — same-day user feedback on D-064 → gold table → serving/export/web → merge → live production — took under 24 hours end to end.

## 2026-08-17 — Daily CI break: a new Berkshire 13F position outgrew the share divisor (D-066)

The scheduled daily GitHub Action failed at `make generate`: `D R HORTON INC (3564 shares) scales to zero at a divisor of 10000 — choose a divisor that fits account 60011234's filer`. Berkshire's 2026-Q2 13F (period 2026-06-30, filed 2026-08-14) opened a 3,564-share D.R. Horton stake — smaller than NVR's 11,112 shares, the constraint D-015 originally calibrated both Berkshire accounts' divisors against. `_seed_position` raised exactly as designed rather than silently dropping the position.

`reference/src/parvum_reference/accounts.py`: `60011234` (Growth Portfolio) `10,000 → 2,000`; `60018852` (Retirement) `20,000 → 4,000` — same 1:2 ratio as before, with more rounding margin against D.R. Horton than the old pair had against NVR. Module docstring updated to point at this decision instead of the now-superseded NVR-at-~22k example. Stale `10k vs 20k` comment in `ingest/tests/test_book.py::test_same_filer_two_accounts_differ_only_in_scale` corrected to `2k vs 4k` (the assertion itself, `r[isin] <= g[isin]`, only depends on relative ordering and needed no change).

**Verified:**
- `make generate` (the exact failing step) reran clean against the full 90-day/64-business-day window, which now spans the new filing regime.
- `ingest` 118/118, `reference` 31/31 (+1 skip). `make fmt` then `make lint` clean across `ingest`/`reference`/`export`/`alts-hitl`.
- Confirmed via the real cached 13F XML (`make fetch-13f` pulled the new filing locally) that D.R. Horton is genuinely the new smallest position (3,564 shares, ahead of NVR's unchanged 11,112) and that no other Berkshire holding is smaller across any of the five cached filing periods.

**Merged (PR #97), then run for real, verified end to end against live production, same day.** User re-ran `daily-feeds.yml` manually post-merge; the file-arrival trigger picked up the new `date=2026-08-17` directory automatically (D-018 — no `make run-job` needed) and `parvum-ingest` ran all five tasks to `SUCCESS`. Queried `silver_positions` directly: `DR HORTON INC` now has real, non-zero rows for `2026-08-17` — `60011234` at quantity `2` ($325.76), `60018852` at quantity `1` ($162.88) — exactly what `3564/2000` and `3564/4000` round to. User dispatched `export-gold.yml`; the live production API (`GET /tenants/aldergate/wealth`) now returns `asOf: "2026-08-17"`, confirming the reload picked up today's corrected book. Stonefield's tenant (Gates Trust/Pershing Square accounts, unaffected by this change) confirmed unchanged in shape.

**A real, sizeable side effect worth recording plainly:** lowering both divisors 5x (10,000→2,000, 20,000→4,000) scales up every position's `market_value` in those two accounts by roughly the same factor, since `market_value ≈ real_filing_value / divisor`. Hartwell's `totalWealthUsd` — the two accounts' sole owner — moved from ~$41.1M to ~$221.2M on this run. This is the direct, expected arithmetic consequence of the D-066 choice (real margin against further trims, at the cost of scale), not a defect; flagged here because it's exactly the kind of figure that goes stale in any external reference material quoting it verbatim.

## 2026-08-20 — A Critical Data Element register, and a CI gate that keeps it honest (D-067)

The platform could say whether a number was right; it could not say who was accountable for it. `governance/` is a fifth uv workspace member (`parvum-governance`) holding the register and the gate — a package rather than a folder because a control should not live inside the thing it controls, and because it earns its own CI status check.

`governance/cde_registry.yml` classifies **all 295 published columns** across the 28 tables the Spark jobs write. Every column carries a tier and an owner; `critical` also owes a business definition, a named SLO, and either the quality rules that test it or an explicit `control_gap`. Six owner roles (`client-reporting`, `reference-data`, `custody-ingestion`, `alts-operations`, `data-quality`, `platform-ops`) and five SLOs, each of which must be `measured_by` a metric `dq_metrics` really computes. Repeated column names (`rebuilt_at`, `client_id`, `ownership_pct`) are declared once under `common_columns` and inherited, so a name that means the same thing everywhere is defined in one place.

`parvum-check-governance` (also `make check-governance`, also a `governance` CI job) reconciles the register against reality on every pull request. Five rules fail the build: `unclassified` (a column reached the catalog with no entry — the rule that makes the register keep up with the code), `orphan` (an entry for a column no job publishes any more), `missing_description`, `incomplete_obligation` (a critical element with no owner, definition, SLO, or statement about controls), and `invalid_reference` (an unknown owner, tier or SLO, or a quality rule the DQ layer does not compute — a control you cannot execute reads as covered, which is worse than an admitted gap).

The inventory is read out of the jobs themselves rather than from Unity Catalog: `schema_scan.py` parses each `spark/*.py` with `ast.literal_eval` to lift its `COLUMN_COMMENTS` dict, and pulls the `dq_metrics` metric names out of the SQL that builds them. Parsing rather than importing, because these notebooks call `spark.sql` at module scope and cannot be imported off-cluster — and because a gate that needed a live warehouse would fail whenever the network did. A guard (`_MIN_DQ_METRICS`) turns "the SQL was restructured and we now match nothing" into a loud failure instead of a gate that silently rejects every rule the register cites.

**First run, and the honest number it produced:**

```
columns published        295
classified in register   295 (100.0%)
  critical               28
  operational            42
  supporting             225
critical with a control  10/28 (35.7%)
critical with a known gap 18
```

The critical list stops at the layer the business consumes — `gold_client_wealth.total_wealth_usd` is critical, the `silver_positions.market_value` behind it is `supporting`. `ownership_pct` is the one cross-cutting exception, critical in all five tables it appears in, because every prorated figure in the estate is multiplied by it.

The 18 control gaps are the point, not an embarrassment. Four are real findings this exercise surfaced: nothing re-checks a landed ECB FX rate against its source or a plausibility band (a wrong rate would misstate every EUR-denominated figure while every other control still passed); the alts chain is validated document-to-document in silver but none of it rolls up into `dq_metrics`; nothing recomputes TWR/Dietz/IRR independently on a schedule; and the ownership graph's acyclic-and-fully-allocated invariants are proven at build time but never surface as a daily signal.

**Verified:** `governance` 36/36 tests, including one that runs the real gate against the real repository so `make test` catches a broken register too, and one that asserts the critical list stays under 15% of published columns. `make fmt` then `make lint` clean across all five workspace packages. `uv.lock` regenerated for the new member (one new dependency, `pyyaml`).

## 2026-08-20 — The register lands in the lakehouse and gets a `governance` dimension (D-068)

D-067's register was enforced in CI and invisible everywhere else. This makes it queryable without giving up the property that made it worth building: the YAML in the repo is still the source of truth, and an ownership change is still a reviewable diff.

`parvum-publish-registry` resolves the register against the live column scan and writes JSON Lines to `data/reference/cde_registry.json` — **one row per column the platform publishes, not per column the register claims**, so the lakehouse computes classification coverage from the rows rather than being told a number. It refuses to write at all if the gate fails: a snapshot of a broken register would put wrong ownership on a screen. `make land-registry` uploads it next to `fx_rates.json`, and the daily Action lands it beside the FX rates (`continue-on-error`, same reasoning — the previous snapshot is still a usable register). Overwriting a reference file deliberately does not fire the file-arrival trigger (D-018), so a governance change is picked up by the next scheduled run rather than starting one of its own.

`spark/dq_recon.py` gains one cell that reads the snapshot under an **explicit `StructType`** (a landed file is a contract; inference would silently retype an all-NULL column) into `governance_cde_registry` — 14 columns, one row per published column, with tier, owner, business definition, flattened SLO, and either the quality rules that test it or the stated control gap.

Then `dq_metrics` gains a fifth dimension, **`governance`**, dated at the rebuild's own run date like freshness because the register describes the estate as it is now:

| metric | passed |
| --- | --- |
| `columns_classified_rate` | true when every published column is classified |
| `critical_control_coverage_rate` | against a stated 80% target — currently **false** at 35.7% |
| `critical_element_count` | NULL (trend) |
| `control_gap_count` | NULL (trend) |

A target set to today's number is not a target, so this ships red on purpose.

**The recursion, which is the nicest part.** `governance_` is a new layer prefix, because the register is not a check and should not be named like one. The moment `governance_cde_registry` got its `COLUMN_COMMENTS`, the gate failed with 14 `unclassified` findings — the register was refusing to publish a table it had not classified, in the very file that describes it. Classifying those 14 columns (and adding a `data-governance` owner role for them) fixed it. The control is subject to itself.

The cell lives in `dq_recon.py` rather than a new notebook on purpose: a new notebook means a new bundle task, and a task pointing at a notebook that is not yet on `main` fails the whole job if a trigger fires before merge — a rule this project has learned twice. Folding it into an existing task removes the hazard, and `dq_metrics` is the natural consumer two cells down.

**Verified:** `governance` 43/43 tests (7 new, including one that asserts the register classifies its own table and one that proves publishing is refused on a failing gate). Gate re-run after the change: **309 published columns, 309 classified (100%), 28 critical, 10 with a control (35.7%), 18 with a stated gap.** `make fmt` then `make lint` clean; `spark/dq_recon.py` syntax-checked. Not yet run against the live lakehouse — that happens after merge, since the job runs `main`.

## 2026-08-20 — Governance on the Ops page: the gaps, not the score (D-069)

The projection half of D-068. `V9__governance_registry.sql` adds a `cde_registry` table to every tenant schema and extends `dq_metrics`' dimension check from four values to five; `/internal/tenants/{id}/cde-registry` serves it; the exporter gains one `UNSCOPED_TABLES` entry and one `PROJECTION_TABLES` mapping (`governance_cde_registry` → `cde_registry`); the internal app's Ops page gains a Governance section.

**The V4 check constraint paid for itself before this shipped.** Adding a fifth dimension in the lakehouse meant the first export would have failed on the constraint rather than quietly loading a value the schema did not recognise. Extending it deliberately is the point of having written the allowed values down. The drop is `alter table ... drop constraint if exists` for one specific reason, recorded in the migration: jOOQ replays this DDL through an in-memory H2 that never gave V4's inline check its Postgres name, so without `if exists` code generation fails before it reaches the new table. The real drop-and-recreate is proven by an export test that inserts a `governance` row against a real Postgres migrated with this DDL.

**The page leads with the gaps, not the percentage.** Four tiles (register coverage, critical elements tested — red against its 80% target, critical element count, stated control gaps) sit above a table listing every critical element with no automated control: the element, its owner, and the written statement of what is missing. A percentage is a verdict; the list is a work item. Same correction D-065 made to the reconciliation badge, from the same instinct.

Both halves of the page load in one `Promise.all` — a page that shows the coverage rate before the gaps arrive is briefly a verdict with no evidence, which is the exact failure this design exists to avoid.

**Verified:** `internal` 14/14 tests (3 new: the governance tiles render, only gapped critical elements are listed, and the whole section is absent when the dimension has no rows — a pipeline whose job predates D-068 still renders), typecheck, prettier and build clean. `export` 18 passed / 26 skipped locally (the two new DB tests need Postgres and run in CI): one inserts a `governance` dimension row to prove the constraint change took, the other round-trips a register row alongside an unclassified column whose NULL tier must survive. jOOQ codegen regenerated and `mvn verify -DskipTests` plus spotless clean — the full serving test suite needs Docker, which was unavailable this session, so it runs first in CI.

## 2026-08-23 — A restatement is not a return (D-070)

The live client dashboard was showing Hartwell at **+392.70% since inception**, with a single daily return of **+414.12%** on 2026-08-17 and a blank IRR. None of it was a rendering bug. D-066 had rescaled both Berkshire share divisors fivefold that day so a new 3,564-share position would not round to zero, and the performance chain — which knows only "wealth yesterday, wealth today, cash flow between" — read a change of ruler as a change in value.

**Third time, third layer.** D-016 fixed restatement handling at bronze. D-018 found the same blind spot at the file-arrival trigger and wrote down that fixing a bug class at one layer says nothing about the others. This is that sentence collecting on its debt at gold.

**The CDE register had flagged the area and proposed the wrong fix.** Its `control_gap` on the five performance columns said nothing recomputed the returns independently. Recomputing them would not have caught this: the formula was never wrong, and a second implementation fed the same wealth series reproduces +414.123% faithfully. What changed was what an input *meant*. The gap text is rewritten to say so rather than being quietly marked closed.

**The fix is two halves, because either alone is unsound.** `parvum_reference.restatements` declares each book restatement — effective date, account, divisor before and after, reason, decision reference — published by `parvum-publish-restatements`, landed beside the FX rates and the CDE register, read by `gold_reports.py` under an explicit schema. On a declared day `daily_twr_return` goes NULL, the chained index links straight through, and the day's whole non-flow move is booked to `restatement_adjustment_usd` with `restatement_detail` naming the account, the divisors and D-066. Modified Dietz weights it exactly like a flow and IRR takes it as a contribution — arithmetically identical roles — but it is disclosed in its own column in both tables, because it is emphatically not the client's money.

Declaration alone would be a licence to explain away any inconvenient number, so `dq_return_plausibility` is the other half: it recomputes the raw non-flow move for every client-day **from the wealth series, not from the published return** (so a restatement cannot hide inside the NULL it causes) and flags anything outside a 25% band with no declaration on file. It rolls into `dq_metrics` as `daily_return_plausibility_rate` and `return_plausibility_breaks_count`.

Detection alone would be wrong too: on 2026-05-15 all three clients moved 4–6% on zero flow, which is a new 13F filing regime landing a quarter of movement on one day — real return, arriving lumpily. Identical shape, opposite meaning. Only the book knows which is which.

**Three things now have to fail before a silent rescale reaches a client:** a test comparing every declared `divisor_after` against what `accounts.py` actually carries, a publisher that refuses to write a snapshot while those disagree, and the plausibility bound.

Because `dq_recon` runs *before* gold, a metric derived from gold cannot be computed there without reporting the previous run's numbers as today's — so gold appends those two rows itself, preceded by a `DELETE` of exactly those metric names so a gold-only re-run cannot double-count. The governance gate's metric scanner now reads both jobs and fails loudly if either stops publishing.

**Verified against the live lakehouse before merge**, by extracting the job's own SQL and running it on the warehouse rather than retyping it. Every prediction recorded beforehand matched: `restatement_adjustment_usd` **$178,175,109.88**, `daily_twr_return` NULL, `twr_index_since_inception` unchanged across the boundary at 0.95831694, `restatement_detail` naming both accounts. Since-inception moves from **TWR +392.70% / Dietz +393.41% / IRR NULL** to **TWR −4.17% / Dietz −3.69% / IRR −10.54%**; Okafor and Reyes untouched, including Okafor's genuine +2.13% on the same day, which is preserved rather than swallowed. `dq_return_plausibility`: 0 breaks, 100% every day, 3 first-date NULLs. The negative control — same query, declaration removed — turns 2026-08-17 into a break, which is what proves the detector bites instead of rubber-stamping whatever is declared.

A pleasing side effect: Hartwell's TWR and Dietz now differ by 48bp where the other two families agree to within 4bp. `docs/PERFORMANCE_METHODOLOGY.md` predicted exactly that — Dietz's linear day-weighting approximates poorly when a mid-period adjustment is large relative to the portfolio, and $178M against a $45M opening balance is as large as that gets.

**Verified:** `reference` 40 passed / 1 skipped (9 new), `governance` 47 (5 new, including a negative control that a job which stops publishing metrics fails even when the other job covers the minimum), `ingest` 118, `alts-hitl` 65, `export` 18 passed / 26 skipped (DB tests run in CI). `make fmt` then `make lint` clean on all five packages. Gate after the change: **324 published columns, 324 classified (100%), 32 critical, 19 with a control (59.4%, up from 35.7%), 13 with a stated gap** — still short of the 80% target, which remains the honest number.

## 2026-08-23 — The restatement reaches the screen (D-071)

The projection half of D-070. `V10__restatement_disclosure.sql` puts `restatement_adjustment_usd` and `restatement_detail` on `performance` and `restatement_adjustment_usd` on `performance_summary`; both DTOs carry them; the client dashboard's Performance tab gains one conditional tile.

**The migration was mandatory, not cosmetic.** The exporter selects `*` from each gold table and inserts by source column name, and its loader documents that schema drift "fails loudly at INSERT". The moment D-070 merged, `export-gold` was one gold run away from failing — gold and serving have to move together. Worth knowing before scheduling the production rebuild rather than after.

**On whether to disclose at all.** The question came up and deserved a real answer rather than a reflex. It was settled by what the tab already renders: a "Net external flow" tile reading `$44,722,729 → $221,166,594` with `$137,500` of client money, sitting beside a TWR of `−4.17%`. Wealth quintuples, nearly nothing comes in, and the return is negative. Those cannot all be true without a fourth number, so the missing number was *already* generating the question — the tile answers it instead of raising it. With the disclosure the row reconciles exactly:

```
 44,722,729  opening
    +137,500  client flows
+178,175,110  book restatement
  −1,868,745  market loss (the −4.17%)
────────────
 221,166,594  closing
```

The tile is conditional — it renders only when the adjustment is non-zero, which is almost never. A disclosure showing `$0` on every ordinary client teaches readers to ignore it, and the one time it mattered they would. Both halves are pinned by tests.

`restatement_detail` lives on the daily series rather than the summary, so the dashboard joins the two and hangs the provenance on the tile as a hover: account, divisors, decision. Not a click-to-expand panel like D-065's reconcile badge — that one revealed a *list* a reader might act on, this is one sentence of provenance.

**No `internal/` change was needed and none was made.** The Ops page derives its accuracy metrics generically from whatever `dq_metrics` contains, and `dq_metrics` already loads unscoped into every tenant schema (D-044), so `daily_return_plausibility_rate` and `return_plausibility_breaks_count` will appear there on their own once the data flows. `dq_return_plausibility`'s per-client detail table is deliberately left unprojected — the rollup is what a Data Operations reader consumes, and the detail stays queryable in the lakehouse.

**Verified:** `web` 14/14 (2 new — the tile appears with the right figure, sentence and hover provenance when restated, and is absent when not), typecheck, prettier and production build clean. `export` 18 passed / 27 skipped locally, one more skip than before because the new restatement round-trip test needs Postgres and runs in CI; its fixtures now carry the new columns so every existing performance test exercises the real row shape. Serving `mvn verify -DskipTests` and spotless clean, with jOOQ codegen regenerated — the generated getters compiling is itself the proof that V10 replayed correctly through the in-memory H2. Docker was unavailable this session, so the full serving suite and the export DB tests run first in CI.

## 2026-08-23 — V10 exposed a latent ordering bug in the export test fixture

CI's `export` job failed on the D-071 branch with twelve errors, all
`UndefinedTable: relation "performance" does not exist`. The cause was not V10
itself but how the loader tests build their throwaway schemas:

```python
migrations = sorted(_MIGRATIONS.glob("V*.sql"))
```

Flyway orders migrations by parsed version **number**. A filename sort orders
them as strings. Those agree only while every version is a single digit — so
`V1 … V9` never exposed the difference, and `V10` sorted directly after `V1`,
running its `alter table performance` three migrations before `V3` created the
table.

**Production was never at risk, and that is worth stating rather than
assuming.** Real Flyway parses the version, so the serving app has always
applied these correctly — confirmed by running the full serving suite once
Docker was available: 32/32, which boots the app and migrates every tenant
schema for real. The divergence was entirely in the fixture, which makes it
precisely the bug these tests exist to prevent: they are the "one schema, both
sides" guarantee (D-029), and a fixture that applies the same files in a
different order than Flyway quietly stops being evidence of anything.

Fixed by parsing the version the way Flyway does, in both the projection and
internal fixtures, with an unparseable filename raising rather than sorting
somewhere arbitrary — silently ordering a file the fixture cannot understand
would reintroduce the same class of bug in a new shape.

`export/tests/test_migration_order.py` pins it, in pure Python so it runs
everywhere the suite does rather than only where Postgres is reachable: that
double-digit versions sort after single-digit ones, that both real migration
directories are version-ordered, that the projection series is gapless, that
whichever migration creates `performance` precedes any that alters it (the
exact invariant CI caught), and that an unversioned filename fails loudly.

**Verified with Docker up, so nothing was left to CI this time:** `export`
**50 passed, 0 skipped** — the twelve previously-erroring tests now pass, the
new restatement round-trip test runs against real Postgres rather than being
skipped, and the five ordering guards are green. Serving `mvn verify` 32/32 and
spotless clean. `ingest` 118, `reference` 40 (+1 skip), `alts-hitl` 65,
`governance` 47; gate unchanged and passing.

## 2026-08-23 — D-070/D-071 verified against the live lakehouse

Both halves merged (PRs #101, #102), then run for real: `make land-registry` and `make land-restatements` to refresh the two reference snapshots, then `make run-job` — all five tasks SUCCESS in about nine minutes. No `databricks bundle deploy` was needed; neither change touched the bundle.

Every prediction recorded before the run matched.

**The defect itself, gone.** `gold_performance` for Hartwell across the boundary:

| as_of | wealth | restatement adj. | daily TWR | index |
|---|---:|---:|---:|---:|
| 2026-08-14 | 43,024,684.90 | 0.00 | −0.00001100 | 0.95833621 |
| 2026-08-17 | 221,199,794.78 | **178,175,109.88** | **NULL** | **0.95833621** |
| 2026-08-18 | 221,168,057.16 | 0.00 | −0.00000200 | 0.95833429 |

The index is identical on 08-14 and 08-17 — the chain links straight through the restatement rather than compounding it. `restatement_detail` reads `60011234: divisor 10000 -> 2000 (D-066) | 60018852: divisor 20000 -> 4000 (D-066)`.

**`gold_performance_summary`**, where the wrong number lived:

| Client | TWR | Dietz | IRR | restatement adj. |
|---|---:|---:|---:|---:|
| Hartwell | **−4.167%** | **−3.693%** | **−10.543%** | 178,175,109.88 |
| Okafor | −2.572% | −2.529% | −7.319% | 0.00 |
| Reyes | −4.855% | −4.857% | −13.734% | 0.00 |

Hartwell was **+392.70% / +393.41% / NULL** before this. Okafor and Reyes are untouched, which is the control: neither owns a Berkshire account, so neither has a restatement to declare, and Okafor's genuine +2.13% on 2026-08-17 stays in its return.

The 47bp gap between Hartwell's TWR and Dietz — against 4bp and 2bp for the other two families — is Modified Dietz's linear day-weighting approximating poorly against an adjustment four times the opening balance, exactly as `docs/PERFORMANCE_METHODOLOGY.md` predicted before there was anything large enough to show it.

**The detector.** `dq_return_plausibility`: 270 client-days, **0 breaks**, 3 first-date NULLs (one per client, nothing to compare). In `dq_metrics`, `daily_return_plausibility_rate` is 1.000000 and passing on all 89 days, and `return_plausibility_breaks_count` is 0 on all 89. All five dimensions intact (accuracy 358, completeness 90, exceptions 358, freshness 1, governance 4).

The idempotency guard was checked rather than assumed: no `(as_of, metric)` pair appears twice, confirming the `DELETE`-then-`INSERT` in the gold job survives being re-run alongside `dq_recon`'s own full rebuild.

**Governance moved, and stayed honest.** With the refreshed register landed: `governance_cde_registry` 324 rows, `columns_classified_rate` 1.000000 passing, `critical_element_count` 32, `control_gap_count` 13, and `critical_control_coverage_rate` **0.593750 — still `passed = false`** against the stated 80% target, reading "19 of 32 critical elements have a quality rule". Coverage rose from 35.7% because five performance columns gained a real control and four new critical columns arrived with one; the target did not move to meet it.

**Still outstanding:** the production RDS reload (`export-gold.yml`, manual dispatch) and visual confirmation on the live dashboard. Until that runs, the lakehouse is correct and the served figures are not.

## 2026-08-23 — A repo path was being shown to clients

The Performance tab's subheading ended with "— see docs/PERFORMANCE_METHODOLOGY.md for why these differ." That sentence is written for someone with a checkout. On a client dashboard it points at a file the reader cannot open, in a repository they have never heard of, to explain a difference the three tiles already explain in their own subtitles ("Manager's return, flow timing excluded", "Flow-weighted approximation of TWR", "Investor's return, annualized").

Removed. The date range stays, which is what that line was actually for.

The identical reference in `web/src/components/Charts.tsx` is a source comment, not rendered copy, and stays — a developer reading the chart code is exactly who it is for.

A scan of the rest of the client app for internal vocabulary in rendered strings (decision references, layer-prefixed table names, pipeline nouns) turned up two more candidates, both left alone deliberately and recorded here so the judgement is visible rather than silent:

- **The "13F filing" boundary markers on the performance chart** are load-bearing. They exist because the chart otherwise reads as broken: 13F data is a quarterly snapshot, so prices are static within a filing regime and the series is flat between steps. The label is the difference between "this chart is stale" and "this is when new holdings were published". It is public SEC vocabulary rather than internal jargon, and removing it would regress a deliberate earlier fix.
- **The restatement tile's hover text** carries `restatement_detail` verbatim — "60011234: divisor 10000 -> 2000 (D-066)". That *is* internal: an account number, a modelling parameter, and a decision-log reference, on a client-facing surface. It is the same defect class as the line removed here, and it is not a copy tweak to fix — the string is produced in the gold job, so changing what a client sees means either changing the column or translating it in the web layer, and D-071 chose that text precisely for its provenance value. Flagged, not fixed, pending a decision on what a client should see instead.

The same scan's second finding is now also fixed: the restatement tile's hover carried `restatement_detail` verbatim — "60011234: divisor 10000 -> 2000 (D-066)" — putting an account number, a modelling parameter and a decision-log reference on a client screen. The hover is gone, along with the derivation that fed it and the optional `title` prop added for it two commits earlier. The tile's own sentence already carries the meaning a client needs; the full provenance remains in `gold_performance.restatement_detail` and on the internal side, which is where it belongs. The test that asserted the hover's presence now asserts its absence, so the decision is pinned rather than merely done.

## 2026-08-23 — MOIC was measuring the review queue, not the funds (D-072)

A question about the client dashboard — why is every fund at a positive multiple while every client's return is negative? — turned out to have a boring answer and an interesting one.

The boring answer: they are unrelated. MOIC is one fund, alts only, since that fund's 2024 inception, divided by capital *called*. TWR/Dietz/IRR are whole-portfolio, over four months in 2026, divided by portfolio *value*. And the decomposition showed no contradiction anyway — within the window alts **rose** (+2.0% Okafor, +1.6% Reyes) while the listed book fell (−6.4%, −11.7%) and outweighed them. The lazy version of that answer, "alts are a small slice", would have been wrong: alts are 53% of Okafor's wealth and 52% of Reyes'.

The interesting answer: MOIC was wrong, for a reason with nothing to do with the question.

**A ratio built from two different states of the world.** The NAV came from the latest confirmed capital account statement — which reports the fund as it stands and therefore already embeds every call the fund ever made. The denominator summed only the call notices a reviewer had confirmed. Gold's "only confirmed values count" rule was being applied per document type independently, so a fully-loaded numerator sat over a partially-confirmed denominator.

**The tell is that MOIC tracked review progress rather than performance.** The generator calls 60% of commitment over a fund's life. FUND-EU01 had 2 of 4 notices confirmed → 35% called → 1.90×. Every other fund had 1 of 4 → 15% called → 4.13–4.65×. Approving a pending capital call would have pushed MOIC *down*: a fund looking worse because someone did their job.

**And a symptom that had been sitting in gold the whole time:** `called_to_date_usd + unfunded_commitment_usd` never equalled `total_commitment_usd`. Wraithmoor was short by $1,350,000. `unfunded` came from the statement, `called` from the notices, so the two were never required to agree and nothing checked.

Fixed by sourcing every term from the same statement: `called = total_commitment − unfunded_commitment`. Notices remain the source only when no statement is confirmed, where they are the only account of the fund that exists. Distributions are now bounded by the statement's own period end as well — a distribution after the NAV snapshot has not yet been deducted from that carried-forward NAV, and FUND-EU01 was live proof, with a 2025-12-31 statement and a 2026-03-31 distribution being added to it.

**Verified before merge** by pulling the confirmed documents out of the live lakehouse and running both the old and new logic over them. The old path reproduced all four live MOICs to six decimals, which is what makes the new numbers trustworthy rather than merely plausible:

| fund | before | after |
|---|---:|---:|
| Alpenrose (FUND-EU01) | 1.900249 | **1.028479** |
| Meridian (FUND-PE01) | 4.653076 | **1.163269** |
| Wraithmoor (FUND-PE02) | 4.133076 | **1.033269** |
| Bramwell (FUND-VC01) | 4.333076 | **1.083269** |

`called + unfunded − commitment` is now exactly 0.00 for every fund. Multiples of ~1.03–1.16× are what funds a couple of years in with modest markups should look like.

No new quality rule was added, deliberately: the obvious one — "called + unfunded must equal commitment" — is now true by construction, and a control that cannot fail is not a control. The useful check is cross-document (statement-derived called versus notice-derived called), which is precisely the register's existing control gap on the alts chain and belongs to that slice.

**No schema change**, so no migration and no exporter change: same column names, same types, correct values. `gold_reports.py` compiles; the governance gate still passes at 324/324 with coverage 59.4%.

## 2026-08-23 — Asserting the additions, and catching the register grading itself (D-073)

Two defects in one week (D-070, D-072) were both found by a person looking at a screen, not by a control, and they share a shape: **every figure individually correct, two figures disagreeing about what happened.** Every existing check validates a number against its own source. None compared two published numbers to each other.

`dq_cross_field_invariants` does that. Seven identities, one row per (date, invariant, scope), each carrying both sides, the delta, and its own tolerance — money to the cent, fractions to an epsilon, because a sum of rounded divisions has no obligation to land exactly on 1. Rolled into `dq_metrics` as `cross_field_invariant_rate` and `cross_field_invariant_breaks_count`.

The rate counts **invariants, not rows**: `position_owner_proration_sums` is 10,210 of 11,033 rows, and row-weighting would let it swallow a total failure of anything else without moving the number.

**Which of the seven are real, stated rather than implied.** `account_ownership_totals_one` and `allocation_value_matches_wealth` are genuine — the latter is the best of them, because `gold_asset_allocation` and `gold_client_wealth` aggregate the same silver at different grains, so agreement is two independent paths agreeing. `position_owner_proration_sums` catches a dropped owner row; `reconcile_variance_matches_exceptions` ties the dashboard badge to its own drill-down. But `wealth_components_sum` and `allocation_weights_sum_one` are near-tautological — `total_wealth_usd` *is* the sum of its parts, so only independent rounding can break it — and `alts_commitment_splits` became tautological the moment D-072 fixed it, kept as a regression guard. Cheap rounding guards are worth having. They are not worth claiming.

**And that distinction caught a real mistake, in this commit, by the person who wrote the register's rules.** Citing the new metric against every column carrying the alts control gap took coverage from 59.4% to **97.0%** and gaps from 13 to 1. That number felt wrong and was: the invariant does not touch `distributed_to_date_usd`, `current_nav_usd`, `moic`, or `gold_client_wealth.alts_usd`. Four of ten citations were loosely-related metrics wearing the costume of controls — the exact failure D-067 wrote itself a warning about. Walked back. **Honest coverage: 28 of 33, 84.8%, five gaps stated.**

The defence that worked, worth reusing: for every citation, ask *which specific row of this check fails if that column is wrong?* Four of them had no answer.

**The ownership gap closes outright.** It has said since D-067 that the graph proves itself at build time but "neither assertion reaches `dq_metrics` — so there is no daily measured signal. Closing it needs an ownership dimension in the DQ rollup." That signal now exists, daily, so the gap is removed rather than narrowed.

**Coverage crosses 80% for the first time**, against 35.7% at D-067 — and the target has not moved since it was set. `critical_control_coverage_rate` flips to `passed = true`, the first green that tile has shown.

**Verified before merge** by running the table's own SQL against the live lakehouse: **11,033 rows, 7 invariants, 0 breaks**, worst delta 0.000001 and inside its stated epsilon. Every candidate was probed against live data before being written, which is how one got corrected during design — `allocation_value_matches_wealth` was first drafted against `positions + alts` and failed on all 270 rows, because allocation carries Cash as an asset class and reconstructs total wealth instead. The probe was wrong, not the data.

Checks: ingest 118, reference 40 (+1 skip), export 50, alts-hitl 65, governance 47; ruff clean on all five; gate PASS at 333/333 classified.

## 2026-08-24 — D-073 verified live, and the governance tile turns green

`make land-registry` (333 records, up from 324) then `make run-job` — all five tasks SUCCESS. Every prediction recorded before the run matched.

**`dq_cross_field_invariants`: 11,155 rows across 7 invariants, 0 breaks.**

| invariant | rows | breaks | worst delta |
|---|---:|---:|---:|
| `account_ownership_totals_one` | 5 | 0 | 0.000000 |
| `allocation_value_matches_wealth` | 273 | 0 | 0.000000 |
| `allocation_weights_sum_one` | 273 | 0 | 0.000001 |
| `alts_commitment_splits` | 5 | 0 | 0.000000 |
| `position_owner_proration_sums` | 10,323 | 0 | 0.000000 |
| `reconcile_variance_matches_exceptions` | 3 | 0 | 0.000000 |
| `wealth_components_sum` | 273 | 0 | 0.000000 |

The only non-zero delta is a sum of rounded allocation weights, one millionth off 1 and inside its stated epsilon — which is exactly why fractions carry an epsilon and money does not.

`cross_field_invariant_rate` is 1.000000 and passing on all 91 days; `cross_field_invariant_breaks_count` is 0 on all 91. No `(as_of, metric)` pair appears twice, so the `DELETE`-then-`INSERT` guard still holds now that it covers four metric names rather than two.

**The governance tile is green for the first time.** `critical_control_coverage_rate` reads **0.848485, `passed = true`** — "28 of 33 critical elements have a quality rule; target 80%". It has shipped red since D-068 at 35.7%. The target was set when the estate delivered 35.7%, deliberately as a figure that would fail, and has not been touched since; what moved was the estate. `columns_classified_rate` 1.000000 over 333 columns, `critical_element_count` 33, `control_gap_count` **5** — down from 18 at D-067, and every one of the five is a gap this session declined to paper over.

**No regressions across the week's fixes.** `gold_performance_summary` still carries Hartwell's $178,175,109.88 restatement adjustment with TWR −4.167%; all five MOICs hold at 1.03–1.16×; `dq_return_plausibility` reports 0 breaks; all five `dq_metrics` dimensions intact (accuracy 453, completeness 91, exceptions 453, freshness 1, governance 4). Hartwell's IRR moved from −10.54% to −9.55% purely because a new feed day extended the annualisation window — arithmetic, not drift.

**Operational note:** `make run-job` now runs past the ten-minute mark, so the CLI wait can be killed while the Databricks job continues unaffected. The two are not coupled; read the run state from `/api/2.1/jobs/runs/get` rather than inferring failure from a dead CLI. And when polling that endpoint, parse the run-level `state` object — a `grep` for `TERMINATED` matches the first *task* that finished and reports success several minutes early.

## 2026-08-25 — Four metrics reached production without names

The Ops page renders each DQ metric through a curated label map, falling back to the raw identifier. `dq_metrics` is deliberately open — adding a check means adding one more `SELECT` to a `UNION ALL` — and nothing connects that to naming the result. So D-070's two metrics and D-073's two shipped to production shouting `CROSS_FIELD_INVARIANT_RATE` and `DAILY_RETURN_PLAUSIBILITY_RATE` beside neighbours reading "Cash consistency" and "Cross-format match".

It went unnoticed for a week for a specific reason worth recording: `/internal/**` returns 403 to an unauthenticated probe because `InternalAuthFilter` pre-matches, so every verification of these slices was done against the lakehouse and the API, never against the rendered page. The data was right every time. The page was not, and nothing that could be checked without a password would have said so.

Named all four, and changed the fallback: an unknown metric is now humanised (underscores to spaces, first letter capitalised) rather than rendered raw. Explicit entries stay preferred — `holdings_cross_format_match_rate` humanises to "Holdings cross format match rate" and is curated to "Cross-format match", which is the whole reason the map exists — but the next unnamed metric will look like a blemish instead of a seam.

`internal` 18/18 (4 new, including one asserting no label ever renders an underscore), typecheck, prettier and build clean.

## 2026-08-25 — The gap list reads as one problem, not four copies

The Ops page's work list — critical elements with no automated control — printed one row per column, and four of the five carried the same alts paragraph word for word. Accurate, since those four columns genuinely share one root cause, but it read as a copy-paste glitch on the one table a reader is most likely to actually read.

Grouped on the written statement itself: same words, same cause. The five columns now render as two rows — one naming the four alts columns together with the single paragraph that explains all of them, one for the FX rate. The heading still counts columns (`(5)`), because the number of uncovered *elements* is the governance fact; how many distinct causes they collapse into is presentation.

A test pins it: three gapped columns sharing two causes must render the shared statement exactly once while still naming every column it covers.

`internal` 19/19, typecheck, prettier and build clean.

## 2026-08-28 — A governed semantic layer, and a Genie space that reads it

Gold has always handed every consumer the same tables and left them to
re-derive the same definitions. "Total wealth" is `SUM(total_wealth_usd)` at
the right grain, written out by hand in the dashboard, the exporter, and every
ad-hoc query — agreeing only by luck. The CDE register governs the columns;
nothing governed the measures.

Added `workspace.parvum.wealth_metrics`, a Unity Catalog **metric view**: six
measures and three dimensions over `gold_client_wealth`, each carrying a
`COMMENT` that is the business definition rather than the catalog description.
The definition is in the repo at `spark/metric_views/wealth_metrics.sql` and
applied with `make metric-views` (`apply.py` posts it through the SQL
Statements API) — a metric view is a catalog object, not a Delta table, so the
bronze → gold job does not build it and it is versioned on its own. Not wired
into CI: it needs live warehouse credentials, like the `land-*` targets.

An AI/BI **Genie space** ("Client Wealth Analytics") is pointed at the metric
view. Plain-language questions resolve to the governed measure — not an
aggregation the model reinvented — and answers cite the view as their source.

Verified live on the Free Edition workspace: `MEASURE()` on "Total wealth"
returns Hartwell $221,164,643.82 / Okafor $6,575,195.46 / Reyes $3,567,622.02,
matching `gold_client_wealth` on the latest date. Lineage shows the metric view
and the Genie agent downstream of `gold_client_wealth`, the silver tables
upstream. Genie answered "total wealth by client for the latest date" and
"which clients' books don't reconcile" — the second crossing from the headline
number into the DQ columns on the same view, one vocabulary for both.

Full write-up with screenshots: `docs/SEMANTIC_LAYER.md`. Decision and
alternatives: D-074. New glossary terms: semantic layer, metric view, measure
vs. dimension, `MEASURE()`, AI/BI Genie.

Held honestly: the metric view's measures are not in the CDE register (they
inherit classification from their 1:1 source columns, but the gate does not see
them); the Genie space's instruction text lives in the workspace, not git.
Both are natural next slices, not done here.

## 2026-08-29 — Service levels that can be missed, and a rule that found two nobody was holding

The register has named seven service levels since D-067. None was measured.
Its own comment said so — "objectives the estate is held to, not claims about
current attainment" — and a target nobody measures can be quoted in a review
forever without ever being missed.

Each SLO now carries a machine-readable half (`attainment_objective`,
`window_days`) beside its target sentence, and gold computes
`dq_slo_attainment` from those against the `dq_metrics` series: one row per
service level, with attainment, the error budget, and how much of it is spent.
`V11` projects it, `/internal/tenants/{id}/slo-attainment` serves it, and the
Ops page renders a **Service levels** section with breaches sorted first.
`docs/RUNBOOK.md` is the other half: per alert, what it means, the first three
checks, what to do, and when to escalate — plus an explicit ownership boundary
(an operator can always re-run; an operator never edits gold).

**A sixth gate rule paid for itself immediately.** `unheld_slo` fails the build
when a declared service level has no critical element citing it — the mirror of
`orphan`, and, since attainment is derived from what elements cite, an unheld
SLO would also never be measured. It found two: `feed_completeness` and
`cash_continuity`, declared since D-067 and held by nothing at all. Both were
real promises, so both were assigned rather than deleted, using the D-073 test
pointed at SLOs: *if this service level is breached, is this element's value
affected?* `total_wealth_usd` moved to `feed_completeness`; `external_flow_usd`
to `cash_continuity`.

**Verified against the live warehouse before merge**, predictions first, by
running the table's own SQL with the objectives substituted as literals. All
seven matched. 22 business days inside the 30-day window. Four SLOs at
1.000000 and met. `holdings_agreement` at 0.000000 with 22 days consumed
against a 1.10-day budget; `cash_ledger_integrity` at 0.454545 — both breached
by design, because the defect injector is doing its job (D-011), and both left
visibly red rather than exempted. `gold_freshness` came back with one day of
history and no verdict, which is the third state working: `bronze_days_behind`
is published as a single as-of-now row rather than a series, so it *cannot*
have seven days to judge. A real limitation of that metric's shape, surfaced
rather than smoothed into a fake 100%.

Both designed edge cases behaved on live data: an objective of 1.0 produced a
zero error budget and a NULL remaining-percentage (a budget that does not exist
cannot be part-spent), and insufficient history produced a NULL verdict in grey
rather than a green pass.

Checks: governance 48 (5 new), ingest 118, reference 40(+1), export 50, alts-hitl
65, ruff clean on all five; serving `mvn verify` 32/32 with V11 replaying
through jOOQ's H2 and every tenant schema migrating for real; internal 22/22
(3 new), typecheck, prettier and build clean. Gate: **353 published / 353
classified, 35 critical, 30 controlled (85.7%), 5 stated gaps.**

## 2026-08-29 — Four personas, and a roadmap with a review date on it

Two documents, no code. `docs/PERSONAS.md` names the four people the platform
already serves — consumer, producer, operator, analyst — and gives each a
surface, an enablement path, and a **self-serve ceiling**. The ceiling is the
interesting column: what a persona cannot do for themselves is the design
decision, and a consumer's inability to ask a new question is deliberate rather
than a gap.

`docs/ROADMAP.md` publishes the plan with a named next review date
(2026-10-01), a changelog, a parked list where every entry carries the trigger
that would revive it, and an **explicitly not doing** section — real client
data, production-scale benchmarks, a second orchestrator. Parked and refused
are different commitments, and a roadmap that only ever grows is a wish list.

An executive persona is named as a deliberate omission rather than left out
silently: real in a bigger organisation, architecture theatre at this size.

D-076. Both linked from the README and from `RUNBOOK.md`.

## 2026-08-29 — Contracts the gate checks, instead of comments that rot

The register knew what each column meant and who owned it, and nothing about
how the tables fit together: what one row represents, which columns join to
which, whether a join can fan out. That is exactly the metadata an analyst
needs before using a dataset unaided and a model needs before generating a
correct join — and the conventional home for it is a catalog comment, which is
also the problem. A comment saying "joins to silver_account_owners" reads as
authoritative, is checked by nothing, and rots the moment a column is renamed.

Tables now declare `grain`, `foreign_keys` (with a cardinality from a closed
set) and a `context` sentence, and a seventh gate rule, `broken_contract`,
resolves every one of them against the scanned inventory on each pull request.
Sixteen tables — the ones carrying a critical element — got a paragraph saying
what they are for; the rest owe nothing, because requiring it everywhere is how
a metadata field becomes noise.

**Proven by negative control, not just by tests.** Renaming one end of a real
declared join in a copy of the register (`gold_ownership.account_id` →
`.acct_id`) produced exactly one finding naming the broken reference. Five new
unit tests pin the rest: a resolving contract passes; a phantom grain column, a
foreign key to a column nobody publishes, an unknown cardinality, and a missing
context each fail.

Writing the base test fixture's own `context` was itself the rule working — the
fixture publishes a critical element, so it owed one like any other table.

Held honestly: the contracts are verified in CI and stop there. Pushing them
into `COLUMN_COMMENTS` so an AI reading Unity Catalog inherits them is the
obvious next step and is not claimed. D-077. governance 53 tests (5 new).
