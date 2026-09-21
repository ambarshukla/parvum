# infra/hetzner/

The production stack, as deployed on a single Hetzner VM (D-092). These files
are the source of truth; `/opt/parvum/` on the host holds a copy, plus a
`.env` that is generated there and never committed.

| File | What it is |
|---|---|
| `docker-compose.yml` | Postgres, the Quarkus API, and Caddy |
| `Caddyfile` | Shared reverse proxy — one site block per hostname |
| `bin/ci-run.sh` | Forced command the CI deploy key is pinned to |

## The shape, and why

```
internet ──443──▶ caddy ──▶ serving ──▶ postgres
                  (TLS)     (8080)      (5432)
                            not published  bound to 127.0.0.1
```

Only Caddy publishes ports. `serving` is reachable solely over the compose
network; `postgres` is additionally bound to loopback on the host so that CI
can reach it through an SSH tunnel.

**The database is not on the internet.** On AWS it had to be (D-036): a
GitHub-hosted runner could not reach a private subnet without a NAT gateway,
the one fixed cost D-005 had ruled out. Moving hosts removed that constraint,
so `export-gold` and `sync-review-queue` now forward a local port over SSH
instead of dialling a public database.

## The CI key cannot get a shell

`authorized_keys` pins the deploy key to `bin/ci-run.sh` with `restrict`,
re-enabling only port forwarding and only to `127.0.0.1:5432`:

```
command="/opt/parvum/bin/ci-run.sh",restrict,port-forwarding,permitopen="127.0.0.1:5432" ssh-ed25519 AAAA...
```

So the key can do exactly two things — run `deploy`, or open a tunnel to
Postgres. Everything else is refused and appended to `/opt/parvum/ci.log`.
Verified by trying: an arbitrary command, a shell, and a `sudo` attempt are
all refused, and a forward aimed at port 22 is rejected by sshd itself with
`administratively prohibited`.

## Operating it

```bash
cd /opt/parvum
docker compose ps
docker compose logs -f serving
docker compose up -d                       # apply a compose change
docker exec parvum-caddy caddy reload --config /etc/caddy/Caddyfile
```

⚠️ A change to `Caddyfile` alone does **not** take effect on
`docker compose up -d` — the container spec is unchanged, so nothing is
recreated and the bind-mounted file is simply re-read on reload. Reload
explicitly, or the old config keeps serving and looks like a code problem.

## Adding another site to this box

Append a block to `Caddyfile` and reload. Nothing else changes — the proxy is
shared deliberately so a second project does not need its own port 443.

```
yard.ambarshukla.dev {
	reverse_proxy some-container:3000
}
```

## What is NOT here

- **Secrets.** `/opt/parvum/.env` (chmod 600) holds the Postgres password and
  the internal app's login and session secret. Generated on the host.
- **Backups.** The Postgres content is a projection of the lakehouse and is
  rebuilt by `export-gold`, so it is deliberately treated as disposable. The
  one exception is review-queue decisions, which are human input — those are
  landed back to Databricks by `sync-review-decisions` (D-055), which is what
  makes them recoverable.
- **The database's own TLS.** Nothing reaches Postgres except over loopback or
  an authenticated SSH tunnel, so `rds.force_ssl`'s job is already done by the
  transport.
