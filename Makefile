# Task runner for common dev commands — one documented place for them,
# identical across machines and Claude sessions.
#
# .env (gitignored) supplies machine-specific values like DATABRICKS_HOST;
# -include tolerates its absence.
-include .env
export DATABRICKS_HOST

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

.PHONY: help up down status logs psql clean test lint fmt generate land deploy-job run-job

# -h: MAKEFILE_LIST is "Makefile .env" (from -include above), and grep prefixes
# every match with its filename once given more than one file — which awk then
# reads as the target name. Suppress the prefix.
help: ## show available targets
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

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

generate: ## generate raw feed files into data/raw (DAYS=1 END=2026-07-10 replays one day)
	cd ingest && uv run parvum-generate --days $(DAYS) $(if $(END),--end $(END)) --out ../data/raw

land: ## upload data/raw to the Unity Catalog landing volume (needs DATABRICKS_HOST in .env)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks fs cp -r data/raw dbfs:/Volumes/workspace/parvum/landing/raw --overwrite

deploy-job: ## deploy the Databricks job definitions in databricks.yml (needs DATABRICKS_HOST)
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks bundle deploy

# Normally the file-arrival trigger runs this; the target exists for the first
# run after a deploy, and for reprocessing on demand (safe — the job is idempotent).
run-job: ## run the bronze ingest job now, without waiting for a file to land
	@test -n "$(DATABRICKS_HOST)" || { echo "DATABRICKS_HOST not set — copy .env.example to .env and fill it in"; exit 1; }
	databricks bundle run bronze_ingest
