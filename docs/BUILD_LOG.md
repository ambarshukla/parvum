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
- **Checks the outcome, not the process:** "when did bronze last ingest" catches a job that succeeded-but-did-nothing, was deleted, or stopped triggering — none of which a run-status check would see. It catches a dead *Databricks job*, not a dead *Action* (an Action that never runs can't run its own check — that's the external dead-man's-switch, parked for Phase 9).
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
