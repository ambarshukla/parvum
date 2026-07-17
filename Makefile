# Task runner for common dev commands — one documented place for them,
# identical across machines and Claude sessions.
#
# .env (gitignored) supplies machine-specific values like DATABRICKS_HOST;
# -include tolerates its absence.
-include .env
export DATABRICKS_HOST
export SEC_USER_AGENT
export ALERT_EMAIL

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

.PHONY: help up down status logs psql clean test lint fmt generate land deploy-job run-job fetch-13f check-freshness

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

test: ## run Python tests (mirrors CI)
	cd ingest && uv run pytest

lint: ## lint + format check (mirrors CI)
	cd ingest && uv run ruff format --check . && uv run ruff check .

fmt: ## auto-format and auto-fix lint findings
	cd ingest && uv run ruff format . && uv run ruff check --fix .

# Incremental: filings are immutable, so anything already in data/edgar is
# never re-fetched. SEC requires a contact in the User-Agent — see .env.example.
fetch-13f: ## sync the local 13F filing store from SEC EDGAR (needs SEC_USER_AGENT)
	@test -n "$(SEC_USER_AGENT)" || { echo "SEC_USER_AGENT not set — see .env.example (SEC rejects anonymous requests)"; exit 1; }
	cd ingest && uv run parvum-fetch-13f

generate: ## generate raw feed files into data/raw (DAYS=1 END=2026-07-10 replays one day)
	cd ingest && uv run parvum-generate --days $(DAYS) $(if $(END),--end $(END)) --out ../data/raw

land: ## upload data/raw to the Unity Catalog landing volume (needs DATABRICKS_HOST in .env)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks fs cp -r data/raw dbfs:/Volumes/workspace/parvum/landing/raw --overwrite

deploy-job: ## deploy the Databricks job definitions in databricks.yml (needs DATABRICKS_HOST, ALERT_EMAIL)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	@test -n "$(ALERT_EMAIL)" || { echo "ALERT_EMAIL not set — add it to .env (job failure notifications are sent here)"; exit 1; }
	BUNDLE_VAR_alert_email="$(ALERT_EMAIL)" databricks bundle deploy

# Normally the file-arrival trigger runs this; the target exists for the first
# run after a deploy, and for reprocessing on demand (safe — the job is idempotent).
run-job: ## run the bronze ingest job now, without waiting for a file to land
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks bundle run bronze_ingest

# Alarms (exit 1) only if bronze is confidently stale; warns and passes if it
# can't tell. The daily workflow runs this after landing; needs DATABRICKS_HOST
# + DATABRICKS_TOKEN + DATABRICKS_WAREHOUSE_ID (unset → skips with a warning).
check-freshness: ## fail if the bronze job has stopped updating (needs DATABRICKS_WAREHOUSE_ID)
	cd ingest && uv run parvum-check-freshness
