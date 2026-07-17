"""The ownership graph: validity, and effective ownership through the DAG."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from parvum_ingest.accounts import UNIVERSE
from parvum_ingest.ownership import (
    OWNERSHIP,
    Client,
    EntityKind,
    LegalEntity,
    OwnershipEdge,
    OwnershipGraph,
)

ALL_ACCOUNTS = [spec.account_id for spec in UNIVERSE]


def test_every_account_is_owned_totally() -> None:
    # The universe is self-contained: each account's effective ownership sums
    # to exactly 100% across clients, or something is unaccounted for.
    for account_id in ALL_ACCOUNTS:
        assert sum(OWNERSHIP.effective_ownership(account_id).values()) == Decimal(1), account_id


def test_single_client_through_a_trust() -> None:
    # 60011234 is held by the Hartwell trust, wholly Hartwell.
    assert OWNERSHIP.effective_ownership("60011234") == {"CLI-HARTWELL": Decimal(1)}


def test_split_ownership_through_a_shared_llc() -> None:
    # Meridian LLC is 60% Reyes / 40% Okafor and holds X4478210 outright, so
    # the account's assets are split 60/40 — the product-along-path, summed
    # calculation, on a real two-owner node.
    owners = OWNERSHIP.effective_ownership("X4478210")
    assert owners == {"CLI-REYES": Decimal("0.6"), "CLI-OKAFOR": Decimal("0.4")}


def test_one_client_reached_by_two_different_routes() -> None:
    # Okafor owns FQ5521 outright and 40% of X4478210 via Meridian — two
    # accounts, two paths, one client.
    accounts = OWNERSHIP.accounts_of("CLI-OKAFOR")
    assert accounts == {"FQ5521": Decimal(1), "X4478210": Decimal("0.4")}


def test_one_client_several_entities() -> None:
    # Hartwell holds three accounts through two entities (trust + foundation).
    assert OWNERSHIP.accounts_of("CLI-HARTWELL") == {
        "60011234": Decimal(1),
        "60018852": Decimal(1),
        "FQ9007": Decimal(1),
    }


def test_unknown_account_is_rejected() -> None:
    with pytest.raises(KeyError):
        OWNERSHIP.effective_ownership("NOPE-999")


# --- validation catches malformed reference data ---------------------------

_C = (Client(client_id="C1", name="One"),)
_E = (LegalEntity(entity_id="E1", name="Ent", kind=EntityKind.TRUST),)


def _graph(edges: tuple[OwnershipEdge, ...], **kw) -> OwnershipGraph:
    return OwnershipGraph(
        clients=kw.get("clients", _C), entities=kw.get("entities", _E), edges=edges
    )


def test_ownership_that_does_not_close_is_rejected() -> None:
    # 90% owned means 10% unaccounted for — a modelling error, not reality.
    with pytest.raises(ValidationError, match="100%"):
        _graph(
            (
                OwnershipEdge(owner_id="C1", owned_id="E1", percent=Decimal(1)),
                OwnershipEdge(owner_id="E1", owned_id="60011234", percent=Decimal("0.9")),
            )
        )


def test_unknown_owned_node_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown owned node"):
        _graph((OwnershipEdge(owner_id="C1", owned_id="NOT-AN-ACCOUNT", percent=Decimal(1)),))


def test_percent_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match=r"\(0, 1\]"):
        _graph((OwnershipEdge(owner_id="C1", owned_id="E1", percent=Decimal("1.5")),))


def test_a_cycle_is_rejected() -> None:
    entities = (
        LegalEntity(entity_id="E1", name="A", kind=EntityKind.LLC),
        LegalEntity(entity_id="E2", name="B", kind=EntityKind.LLC),
    )
    with pytest.raises(ValidationError, match="cycle"):
        _graph(
            (
                OwnershipEdge(owner_id="E1", owned_id="E2", percent=Decimal(1)),
                OwnershipEdge(owner_id="E2", owned_id="E1", percent=Decimal(1)),
            ),
            entities=entities,
        )


def test_immutability() -> None:
    with pytest.raises(ValidationError):
        OWNERSHIP.clients[0].name = "changed"  # type: ignore[misc]
