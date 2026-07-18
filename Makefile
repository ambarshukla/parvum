# Task runner for common dev commands — one documented place for them,
# identical across machines and Claude sessions.
#
# .env (gitignored) supplies machine-specific values like DATABRICKS_HOST;
# -include tolerates its absence.
-include .env
export DATABRICKS_HOST
export SEC_USER_AGENT
export ALERT_EMAIL
export OPENFIGI_API_KEY

# `--env-file .env` is passed only if .env exists (compose would error on a
# missing file); without it the compose file's ${VAR:-default} values apply.
COMPOSE = docker compose -f infra/docker-compose.yml $(if $(wildcard .env),--env-file .env)
PGUSER ?= parvum
PGDB   ?= parvum

# `?=` defers to the environment, so the daily-feeds workflow sets DAYS=1 and
# reuses `make generate` verbatim — no CI-only command to drift from this one.
# END blank means "today"; set it to replay a specific historical day.
DAYS ?= 90
END  ?=

.PHONY: help up down status logs psql clean test lint fmt generate land land-master fetch-fx land-fx deploy-job run-job fetch-13f build-master check-freshness

# Two traps here, both of which have already bitten:
#  -h        MAKEFILE_LIST is "Makefile .env" (from -include above), and grep
#            prefixes every match with its filename once given more than one
#            file — which awk then reads as the target name.
#  [a-z0-9-] the character class must cover every character a target name can
#            contain, or that target silently vanishes from the help. Hyphens
#            and digits both had to be added after a target went missing.
help: ## show available targets
	@grep -hE '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

up: ## start local Postgres (detached, waits until healthy)
	$(COMPOSE) up -d --wait

down: ## stop containers (data volume is kept)
	$(COMPOSE) down

status: ## show container status
	$(COMPOSE) ps

logs: ## tail Postgres logs
	$(COMPOSE) logs -f postgres

psql: ## open a psql shell in the running container
	$(COMPOSE) exec postgres psql -U $(PGUSER) -d $(PGDB)

clean: ## stop containers AND DELETE the data volume (destructive)
	$(COMPOSE) down -v

test: ## run Python tests, both workspace packages (mirrors CI)
	cd ingest && uv run pytest
	cd reference && uv run pytest

lint: ## lint + format check, both workspace packages (mirrors CI)
	cd ingest && uv run ruff format --check . && uv run ruff check .
	cd reference && uv run ruff format --check . && uv run ruff check .

fmt: ## auto-format and auto-fix lint findings, both workspace packages
	cd ingest && uv run ruff format . && uv run ruff check --fix .
	cd reference && uv run ruff format . && uv run ruff check --fix .

# Incremental: filings are immutable, so anything already in data/edgar is
# never re-fetched. SEC requires a contact in the User-Agent — see .env.example.
fetch-13f: ## sync the local 13F filing store from SEC EDGAR (needs SEC_USER_AGENT)
	@test -n "$(SEC_USER_AGENT)" || { echo "SEC_USER_AGENT not set — see .env.example (SEC rejects anonymous requests)"; exit 1; }
	cd ingest && uv run parvum-fetch-13f

# Maps the universe's ISINs -> FIGI + name/type/sector via OpenFIGI, writing
# the securities master (Unknown bucket included). Needs the 13F store first
# (that is where the ISINs come from). OPENFIGI_API_KEY is optional but raises
# the rate limit — see .env.example.
build-master: ## build the securities master from OpenFIGI (needs data/edgar; OPENFIGI_API_KEY optional)
	cd ingest && uv run parvum-build-master

generate: ## generate raw feed files into data/raw (DAYS=1 END=2026-07-10 replays one day)
	cd ingest && uv run parvum-generate --days $(DAYS) $(if $(END),--end $(END)) --out ../data/raw

land: ## upload data/raw to the Unity Catalog landing volume (needs DATABRICKS_HOST in .env)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks fs cp -r data/raw dbfs:/Volumes/workspace/parvum/landing/raw --overwrite

# ECB reference rates for gold's EUR->USD conversion (D-026). No key needed;
# the store is exactly what the ECB published (gap-filling happens at
# consumption, in fill_forward, where it is visible and tested).
fetch-fx: ## fetch ECB EUR/USD reference rates into data/reference
	cd reference && uv run parvum-fetch-fx --out ../data/reference/fx_rates.json

# Daily, unlike the securities master: rates change every business day, so the
# daily workflow lands this after fetching. Same D-018 note as the master:
# overwriting this path does not fire the trigger — gold picks fresh rates up
# when the day's feed arrival runs the job.
land-fx: ## upload the FX rates to the landing volume (needs DATABRICKS_HOST)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	@test -f data/reference/fx_rates.json || { echo "no local rates — run 'make fetch-fx' first"; exit 1; }
	databricks fs mkdir dbfs:/Volumes/workspace/parvum/landing/reference
	databricks fs cp data/reference/fx_rates.json dbfs:/Volumes/workspace/parvum/landing/reference/fx_rates.json --overwrite

# Manual and occasional, unlike the daily feed landing: the master changes on
# operator action (a rerun of build-master), not on a schedule. Overwriting
# this path deliberately does NOT fire the file-arrival trigger (D-018 —
# overwrites are invisible to it): a master refresh alone shouldn't rerun
# bronze, and silver picks the new master up on the next feed arrival — or
# immediately via `make run-job`.
land-master: ## upload the securities master to the landing volume (needs DATABRICKS_HOST)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	@test -f data/reference/securities_master.json || { echo "no local master — run 'make build-master' first"; exit 1; }
	databricks fs mkdir dbfs:/Volumes/workspace/parvum/landing/reference
	databricks fs cp data/reference/securities_master.json dbfs:/Volumes/workspace/parvum/landing/reference/securities_master.json --overwrite

deploy-job: ## deploy the Databricks job definitions in databricks.yml (needs DATABRICKS_HOST, ALERT_EMAIL)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	@test -n "$(ALERT_EMAIL)" || { echo "ALERT_EMAIL not set — add it to .env (job failure notifications are sent here)"; exit 1; }
	BUNDLE_VAR_alert_email="$(ALERT_EMAIL)" databricks bundle deploy

# Normally the file-arrival trigger runs this; the target exists for the first
# run after a deploy, and for reprocessing on demand (safe — the job is idempotent).
# Every `bundle` subcommand resolves the whole config, so the required
# alert_email variable must be supplied here exactly as in deploy-job — a
# `bundle run` with it missing fails before running anything.
run-job: ## run the ingest job (bronze → silver) now, without waiting for a file to land
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	@test -n "$(ALERT_EMAIL)" || { echo "ALERT_EMAIL not set — add it to .env (job failure notifications are sent here)"; exit 1; }
	BUNDLE_VAR_alert_email="$(ALERT_EMAIL)" databricks bundle run bronze_ingest

# Alarms (exit 1) only if bronze is confidently stale; warns and passes if it
# can't tell. The daily workflow runs this after landing; needs DATABRICKS_HOST
# + DATABRICKS_TOKEN + DATABRICKS_WAREHOUSE_ID (unset → skips with a warning).
check-freshness: ## fail if the bronze job has stopped updating (needs DATABRICKS_WAREHOUSE_ID)
	cd ingest && uv run parvum-check-freshness
