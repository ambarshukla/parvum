"""The ownership layer: who actually owns each custodial account.

Custodial feeds carry an opaque account number and nothing else about
ownership — a custodian services accounts and knows nothing of the wealth
manager's clients or their legal structure. This module is that missing
knowledge, and it is the wealth manager's own reference data: a graph from
**clients** down through **legal entities** (trusts, foundations, LLCs) to
the **accounts** the feeds deliver.

Why a graph rather than a flat account → client column: real ownership is
layered and shared. A family holds accounts through a revocable trust and a
foundation; an investment LLC is owned jointly by two families and holds an
account between them. The interesting question — *what fraction of this
account's assets does each client ultimately own?* — is answered by walking
the graph: the effective ownership along one path is the product of its
edge percentages, and a client's total is the sum across every path that
reaches them. This is the analogue of the "visual ownership map" wealth
platforms surface, and the calculation silver needs to attribute a
position to its owners.

The structure here is synthetic but shaped like the real thing. It is not
derived from the feeds (it cannot be — that is the whole point); it is
declared, validated, and joined to feed data downstream on `account_id`.
"""

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from parvum_ingest.accounts import UNIVERSE

_KNOWN_ACCOUNTS = frozenset(spec.account_id for spec in UNIVERSE)


class EntityKind(StrEnum):
    TRUST = "TRUST"
    FOUNDATION = "FOUNDATION"
    LLC = "LLC"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Client(_Frozen):
    """A wealth-management relationship — the top of an ownership tree."""

    client_id: str
    name: str


class LegalEntity(_Frozen):
    """A trust, foundation or company through which clients hold accounts."""

    entity_id: str
    name: str
    kind: EntityKind


class OwnershipEdge(_Frozen):
    """`owner` holds `percent` of `owned`.

    `owner_id` is a client or an entity; `owned_id` is an entity or an
    account. `percent` is a fraction in (0, 1].
    """

    owner_id: str
    owned_id: str
    percent: Decimal


class OwnershipGraph(_Frozen):
    """A validated client → entity → account ownership DAG.

    Invariants enforced on construction (a malformed ownership structure is a
    reference-data error, caught here, not a silent mis-attribution later):

    - every edge endpoint is a known client, entity, or universe account;
    - the graph is acyclic (ownership cannot loop);
    - every owned node is owned exactly 100% — incoming percentages sum to
      1. Our universe is self-contained, so an account owned 90% would mean
      10% is unaccounted for, which is a modelling mistake, not reality;
    - every universe account is reachable from some client.
    """

    clients: tuple[Client, ...]
    entities: tuple[LegalEntity, ...]
    edges: tuple[OwnershipEdge, ...]

    @model_validator(mode="after")
    def _validate(self) -> "OwnershipGraph":
        client_ids = {c.client_id for c in self.clients}
        entity_ids = {e.entity_id for e in self.entities}
        owner_ids = client_ids | entity_ids
        owned_ids = entity_ids | _KNOWN_ACCOUNTS

        for edge in self.edges:
            if edge.owner_id not in owner_ids:
                raise ValueError(f"ownership edge has unknown owner {edge.owner_id!r}")
            if edge.owned_id not in owned_ids:
                raise ValueError(
                    f"ownership edge points at unknown owned node {edge.owned_id!r} "
                    "(not an entity, and not an account in the universe)"
                )
            if not (Decimal(0) < edge.percent <= Decimal(1)):
                raise ValueError(f"ownership percent must be in (0, 1], got {edge.percent}")

        self._reject_cycles()

        incoming: dict[str, Decimal] = defaultdict(Decimal)
        for edge in self.edges:
            incoming[edge.owned_id] += edge.percent
        for owned_id, total in incoming.items():
            if total != Decimal(1):
                raise ValueError(
                    f"{owned_id!r} is owned {total:%}, not 100% — ownership must close"
                )

        unowned = _KNOWN_ACCOUNTS - set(incoming)
        if unowned:
            raise ValueError(f"accounts have no owner: {sorted(unowned)}")

        return self

    def _reject_cycles(self) -> None:
        children: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            children[edge.owner_id].append(edge.owned_id)

        visited: set[str] = set()
        on_path: set[str] = set()

        def walk(node: str) -> None:
            if node in on_path:
                raise ValueError(f"ownership graph has a cycle through {node!r}")
            if node in visited:
                return
            on_path.add(node)
            for child in children[node]:
                walk(child)
            on_path.discard(node)
            visited.add(node)

        for owner in list(children):
            walk(owner)

    def effective_ownership(self, account_id: str) -> dict[str, Decimal]:
        """Each client's ultimate fractional ownership of `account_id`.

        Product of edge percentages along a path, summed across paths. The
        returned fractions sum to 1 for any account in the universe.
        """
        if account_id not in _KNOWN_ACCOUNTS:
            raise KeyError(f"unknown account {account_id!r}")

        parents: dict[str, list[OwnershipEdge]] = defaultdict(list)
        for edge in self.edges:
            parents[edge.owned_id].append(edge)
        client_ids = {c.client_id for c in self.clients}

        result: dict[str, Decimal] = defaultdict(Decimal)

        def walk(node: str, weight: Decimal) -> None:
            for edge in parents[node]:
                share = weight * edge.percent
                if edge.owner_id in client_ids:
                    result[edge.owner_id] += share
                else:
                    walk(edge.owner_id, share)

        walk(account_id, Decimal(1))
        return dict(result)

    def accounts_of(self, client_id: str) -> dict[str, Decimal]:
        """The reverse view: each account this client owns, and by how much."""
        return {
            account_id: pct
            for account_id in sorted(_KNOWN_ACCOUNTS)
            if (pct := self.effective_ownership(account_id).get(client_id))
        }


# --- the (synthetic) ownership structure ----------------------------------
# Three families, four legal entities, the five universe accounts. Two cases
# worth their weight: the Hartwell family holds two accounts through a trust
# and a third through a foundation (one client, several entities); and
# Meridian Investment LLC is owned 60/40 by two different families and holds
# one account between them (one account, several clients).

_CLIENTS = (
    Client(client_id="CLI-HARTWELL", name="Hartwell Family"),
    Client(client_id="CLI-OKAFOR", name="Okafor Family"),
    Client(client_id="CLI-REYES", name="Reyes Family"),
)

_ENTITIES = (
    LegalEntity(
        entity_id="ENT-HARTWELL-TRUST", name="Hartwell Revocable Trust", kind=EntityKind.TRUST
    ),
    LegalEntity(
        entity_id="ENT-HARTWELL-FDN", name="Hartwell Family Foundation", kind=EntityKind.FOUNDATION
    ),
    LegalEntity(entity_id="ENT-OKAFOR-TRUST", name="Okafor Family Trust", kind=EntityKind.TRUST),
    LegalEntity(entity_id="ENT-MERIDIAN-LLC", name="Meridian Investment LLC", kind=EntityKind.LLC),
)

_EDGES = (
    # Hartwell: two accounts via the trust, one via the foundation.
    OwnershipEdge(owner_id="CLI-HARTWELL", owned_id="ENT-HARTWELL-TRUST", percent=Decimal(1)),
    OwnershipEdge(owner_id="CLI-HARTWELL", owned_id="ENT-HARTWELL-FDN", percent=Decimal(1)),
    OwnershipEdge(owner_id="ENT-HARTWELL-TRUST", owned_id="60011234", percent=Decimal(1)),
    OwnershipEdge(owner_id="ENT-HARTWELL-TRUST", owned_id="60018852", percent=Decimal(1)),
    OwnershipEdge(owner_id="ENT-HARTWELL-FDN", owned_id="FQ9007", percent=Decimal(1)),
    # Okafor: one account via a trust, outright.
    OwnershipEdge(owner_id="CLI-OKAFOR", owned_id="ENT-OKAFOR-TRUST", percent=Decimal(1)),
    OwnershipEdge(owner_id="ENT-OKAFOR-TRUST", owned_id="FQ5521", percent=Decimal(1)),
    # Meridian LLC: jointly owned by Reyes (60%) and Okafor (40%), holds one
    # account — so that account's assets are 60/40 across two families.
    OwnershipEdge(owner_id="CLI-REYES", owned_id="ENT-MERIDIAN-LLC", percent=Decimal("0.6")),
    OwnershipEdge(owner_id="CLI-OKAFOR", owned_id="ENT-MERIDIAN-LLC", percent=Decimal("0.4")),
    OwnershipEdge(owner_id="ENT-MERIDIAN-LLC", owned_id="X4478210", percent=Decimal(1)),
)

OWNERSHIP = OwnershipGraph(clients=_CLIENTS, entities=_ENTITIES, edges=_EDGES)
