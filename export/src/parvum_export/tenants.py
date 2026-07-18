"""Tenant → client mapping for the serving projection (D-028).

Serving is schema-per-tenant: each advisory firm gets its own Postgres
schema. Two fictional firms partition the client families — Aldergate Wealth
Management advises the Hartwells; Stonefield Family Office advises the
Okafors and the Reyeses (both owners of the shared 60/40 account, so
cross-owner views stay inside one tenant).

This mapping is exporter configuration, not reference data: which firm
advises which family is a fact about the serving demo, not about the book.
It is validated against the canonical client universe in tests, so a new
family cannot appear without being assigned a firm.
"""

import re

TENANT_CLIENTS: dict[str, tuple[str, ...]] = {
    "aldergate": ("CLI-HARTWELL",),
    "stonefield": ("CLI-OKAFOR", "CLI-REYES"),
}

# Mirrors TenantSchemas.SAFE_TENANT_ID on the Java side: a schema name cannot
# be a bound parameter, so the id's shape is the injection defence.
_SAFE_TENANT_ID = re.compile(r"[a-z][a-z0-9_]*\Z")


def schema_for(tenant_id: str) -> str:
    if not _SAFE_TENANT_ID.match(tenant_id):
        raise ValueError(f"tenant id must match {_SAFE_TENANT_ID.pattern}: {tenant_id!r}")
    return f"tenant_{tenant_id}"


def client_tenants() -> dict[str, str]:
    """client_id → tenant id, refusing a client claimed by two firms."""
    mapping: dict[str, str] = {}
    for tenant_id, client_ids in TENANT_CLIENTS.items():
        for client_id in client_ids:
            if client_id in mapping:
                raise ValueError(
                    f"{client_id} is claimed by both {mapping[client_id]} and {tenant_id}"
                )
            mapping[client_id] = tenant_id
    return mapping
