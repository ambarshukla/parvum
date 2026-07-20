# Task runner for common dev commands — one documented place for them,
# identical across machines and Claude sessions.
#
# .env (gitignored) supplies machine-specific values like DATABRICKS_HOST;
# -include tolerates its absence.
-include .env
export DATABRICKS_HOST
export DATABRICKS_WAREHOUSE_ID
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

# The Maven wrapper is invoked differently depending on the shell make runs its
# recipes in. A POSIX shell needs `./mvnw`; cmd.exe — what make uses when it's
# launched from PowerShell — searches the current directory and wants
# `mvnw.cmd`. MSYSTEM is set by Git Bash/MSYS and unset under PowerShell/cmd, so
# it tells the two Windows cases apart; everywhere else (Linux/macOS, CI) it's
# POSIX. This lets the serving targets run from either shell on Windows.
ifeq ($(OS),Windows_NT)
  ifdef MSYSTEM
    MVNW := ./mvnw
  else
    MVNW := mvnw.cmd
  endif
else
  MVNW := ./mvnw
endif

.PHONY: help up down status logs psql clean test lint fmt generate generate-alts-docs land land-master fetch-fx land-fx deploy-job run-job fetch-13f build-master check-freshness serving-test serving-fmt export-gold serving-run web-install web-dev tf-bootstrap tf-init tf-plan tf-apply

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

# export's loader tests want the compose Postgres (`make up`); without it
# they skip loudly and only the pure-Python tests run — CI always runs both.
test: ## run Python tests, all workspace packages (mirrors CI; export DB tests need `make up`)
	cd ingest && uv run pytest
	cd reference && uv run pytest
	cd export && uv run pytest
	cd alts-hitl && uv run pytest

lint: ## lint + format check, all workspace packages (mirrors CI)
	cd ingest && uv run ruff format --check . && uv run ruff check .
	cd reference && uv run ruff format --check . && uv run ruff check .
	cd export && uv run ruff format --check . && uv run ruff check .
	cd alts-hitl && uv run ruff format --check . && uv run ruff check .

fmt: ## auto-format and auto-fix lint findings, all workspace packages
	cd ingest && uv run ruff format . && uv run ruff check --fix .
	cd reference && uv run ruff format . && uv run ruff check --fix .
	cd export && uv run ruff format . && uv run ruff check --fix .
	cd alts-hitl && uv run ruff format . && uv run ruff check --fix .

# The Java side has its own toolchain: the Maven wrapper (mvnw) downloads the
# pinned Maven, so only a JDK 21 on PATH/JAVA_HOME is assumed. Tests boot the
# app against a throwaway Postgres container — Docker must be running.
serving-test: ## build + test the Java serving layer (mvn verify; needs JDK 21 + Docker)
	cd serving && $(MVNW) -B verify

serving-fmt: ## auto-format the Java serving layer (spotless)
	cd serving && $(MVNW) -B spotless:apply

# Runs the API in dev mode (hot reload) on :8080. Needs JDK 21 (JAVA_HOME or on
# PATH) and Docker; the projection tables must be filled once (make export-gold).
serving-run: ## run the serving API locally in dev mode on :8080
	cd serving && $(MVNW) -B quarkus:dev

web-install: ## install the web dashboard's dependencies (one-time)
	cd web && npm install

# Vite dev server on :5173, proxying API calls to the serving app on :8080.
web-dev: ## run the web dashboard locally on :5173
	cd web && npm run dev

# Pulls the four gold tables over the SQL Statements API and truncate-reloads
# each tenant schema (D-029). The serving app must have started once against
# the target database first — Flyway owns the schemas, this only fills them.
# Local OAuth is fine (the CLI mints a token); CI would set DATABRICKS_TOKEN.
export-gold: ## reload the serving Postgres projection from gold (needs DATABRICKS_HOST, DATABRICKS_WAREHOUSE_ID)
	cd export && uv run parvum-export-gold

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

generate-alts-docs: ## generate synthetic capital-call/distribution/statement PDFs into data/alts/raw
	cd alts-hitl && uv run parvum-generate-alts-docs --out ../data/alts/raw

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

# One-time only: creates the S3 bucket the main config's state lives in. Its
# own state stays local (see infra/terraform/bootstrap/main.tf for why).
# Assumes the `parvum-tf` AWS CLI profile — see docs/DECISIONS.md D-033.
tf-bootstrap: ## one-time: create the S3 bucket for Terraform's remote state
	cd infra/terraform/bootstrap && terraform init -input=false && terraform apply -input=false

tf-init: ## initialize the main Terraform config (S3 backend)
	cd infra/terraform && terraform init -input=false

# ALERT_EMAIL doubles as the AWS Budgets alert address (same person gets
# paged for Databricks job failures and AWS spend — one address, not two).
tf-plan: ## preview Terraform changes (needs ALERT_EMAIL in .env)
	@test -n "$(ALERT_EMAIL)" || { echo "ALERT_EMAIL not set — add it to .env (AWS Budgets alerts are sent here)"; exit 1; }
	cd infra/terraform && TF_VAR_alert_email="$(ALERT_EMAIL)" terraform plan -input=false

tf-apply: ## apply Terraform changes (needs ALERT_EMAIL in .env)
	@test -n "$(ALERT_EMAIL)" || { echo "ALERT_EMAIL not set — add it to .env (AWS Budgets alerts are sent here)"; exit 1; }
	cd infra/terraform && TF_VAR_alert_email="$(ALERT_EMAIL)" terraform apply -input=false
