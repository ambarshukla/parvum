# Running the site locally

A step-by-step guide to running the whole read stack — database, API, and
dashboard — on your own machine. It assumes no prior front-end or Java setup.

## What you're starting

Three processes talk to each other over local ports:

```
Postgres (Docker)      the projection database, port 5432
      ▲
      │ jOOQ
Quarkus API            the serving layer, port 8080   →  make serving-run
      ▲
      │ HTTP (proxied in dev)
Vite dev server        the React dashboard, port 5173 →  make web-dev
```

You open **http://localhost:5173** in a browser. The dashboard asks the API on
`:8080`, which reads Postgres on `:5432`. Nothing leaves your machine.

## Prerequisites

| Need | Why | Check |
|------|-----|-------|
| **Docker Desktop** (running) | hosts the Postgres container | `docker ps` |
| **JDK 21** | builds and runs the Java API | `java -version` (or set `JAVA_HOME`, below) |
| **Node 20+** | runs the dashboard | `node -v` |
| **`.env`** (only to *reload* data) | Databricks credentials for `export-gold` | — |

The Maven wrapper (`mvnw`) downloads Maven itself, so you don't install it. The
dashboard's dependencies come from `npm install` (via `make web-install`).

### Which terminal?

Use **Git Bash** — then `make` runs every target correctly. (Windows
PowerShell also works now, but `make` there runs commands through `cmd`, which
a couple of targets used to trip over. Both are supported.)

### Pointing at your JDK (`JAVA_HOME`)

If `java -version` already works, skip this. Otherwise tell the tools where the
JDK is, once per terminal — in **Git Bash**:

```bash
export JAVA_HOME="/c/Program Files/Java/jdk-21.0.11"   # adjust to your path
```

in **PowerShell**:

```powershell
$env:JAVA_HOME = "C:\Program Files\Java\jdk-21.0.11"
```

To avoid doing this every time, set `JAVA_HOME` as a permanent Windows
environment variable (System Properties → Environment Variables).

## Step by step

Open **three terminals**, all in the repo root (`C:\work\github\parvum`).

### 1 · Database — `make up`

```bash
make up
```

Starts Postgres in Docker and waits until it reports healthy. It keeps its data
in a Docker volume, so it survives restarts (only `make clean` erases it). Leave
it; you won't touch this terminal again.

### 2 · API — `make serving-run`

```bash
export JAVA_HOME="/c/Program Files/Java/jdk-21.0.11"   # if java isn't already on PATH
make serving-run
```

The first run downloads Maven and the Java dependencies (a minute or two), then
prints a Quarkus banner and **`Listening on: http://localhost:8080`**. Leave it
running — it hot-reloads if code changes. This terminal stays busy; that's
expected.

> The projection tables were filled during setup, so you normally **skip the
> data load**. If the dashboard shows a client with no numbers, reload it (needs
> `.env` with `DATABRICKS_HOST`/`DATABRICKS_WAREHOUSE_ID` and a Databricks
> login) in a spare terminal: `make export-gold`.

### 3 · Dashboard — `make web-dev`

```bash
make web-install     # first time only — installs dependencies
make web-dev
```

Vite prints **`Local: http://localhost:5173/`**. Open that in your browser.

## Using it

- Pick an advisory firm in the top bar (**Aldergate** or **Stonefield**).
- Pick a client in the left sidebar.
- Move through the tabs: **Overview, Allocation, Income, Holdings, Ownership**.
  The Ownership tab is where the account shared 60/40 between two families shows
  up, with its co-owner named.
- The light/dark toggle is top-right.

## Stopping

- In the API and dashboard terminals, press **Ctrl+C**.
- `make down` stops Postgres but keeps its data; `make clean` also deletes the
  data (you'd then need `make export-gold` to refill after next `make up`).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard shows "Could not reach the serving API" | the API (terminal 2) isn't up yet | wait for its `Listening on :8080`, then refresh |
| `serving-run` fails: *JAVA_HOME not found* / *not recognized* | JDK not located | set `JAVA_HOME` as shown above |
| `'.' is not recognized` from `make serving-run` (PowerShell) | old Makefile | `git pull` — the current Makefile handles PowerShell |
| Port 8080 or 5173 "already in use" | a previous run is still going | close the old terminal, or find and stop that process |
| A client shows empty numbers | projection not loaded | `make export-gold` (needs `.env` + Databricks login) |
| `make up` fails | Docker Desktop isn't running | start Docker Desktop, retry |

## The short version

Once set up, three terminals from the repo root:

```bash
make up            # 1 · Postgres
make serving-run   # 2 · API on :8080  (JAVA_HOME set if needed)
make web-dev       # 3 · dashboard on :5173  (make web-install once, first)
```

Then open **http://localhost:5173**.
