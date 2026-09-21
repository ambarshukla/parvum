#!/usr/bin/env bash
# Forced command for the CI deploy key (see ~/.ssh/authorized_keys).
#
# This key cannot get a shell. sshd runs THIS script instead of whatever the
# client asked for, and puts the client's requested command in
# SSH_ORIGINAL_COMMAND, which we match against a closed allowlist below.
# Anything unrecognised is refused and logged.
#
# Two modes:
#   (no command)  ssh -N ... -L 5432:127.0.0.1:5432
#                 Tunnel only. We just hold the session open so the forward
#                 stays up; permitopen= in authorized_keys is what actually
#                 constrains where the tunnel may point.
#   deploy        Rebuild the serving image from origin/main and restart it.
set -euo pipefail

STACK=/opt/parvum
LOG=/opt/parvum/ci.log
cmd="${SSH_ORIGINAL_COMMAND:-}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [$$] $*" >> "$LOG"; }

case "$cmd" in
  "")
    # Tunnel session. Bounded rather than `sleep infinity` so a hung CI job
    # cannot pin an open forward to this box indefinitely.
    log "tunnel opened"
    exec sleep 1800
    ;;

  deploy)
    log "deploy requested"
    cd "$STACK/repo"
    git fetch --quiet origin main
    git reset --quiet --hard origin/main
    sha=$(git rev-parse --short HEAD)
    log "building $sha"
    docker build --quiet -t parvum-serving:latest "$STACK/repo/serving" >/dev/null
    cd "$STACK"
    docker compose up -d --no-deps serving >/dev/null 2>&1
    # Wait for the app to answer before reporting success, so a failed boot
    # is a failed deploy rather than a green one.
    for _ in $(seq 1 60); do
      if docker exec parvum-serving sh -c 'command -v wget >/dev/null && wget -qO- http://127.0.0.1:8080/q/health || true' 2>/dev/null | grep -q '"status": *"UP"'; then
        log "deploy ok $sha"
        echo "deployed $sha"
        exit 0
      fi
      sleep 2
    done
    log "deploy FAILED to become healthy $sha"
    echo "deploy failed: serving did not become healthy" >&2
    exit 1
    ;;

  *)
    log "REFUSED: $cmd"
    echo "refused: this key may only run 'deploy' or open a tunnel" >&2
    exit 1
    ;;
esac
