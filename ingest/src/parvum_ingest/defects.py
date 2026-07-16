"""Config-driven defect injection: turning the clean book into realistic lies.

Two kinds of defect, injected at different points (this split is the
design):

- **Semantic** defects corrupt the *statement* before rendering. The file
  remains perfectly parseable; its content lies. These are what
  reconciliation and data-quality rules (Phase 3) exist to catch.
- **Syntactic** defects corrupt the *rendered text*. These fail at the
  parser with FeedParseError — caught at the door, not downstream.

Everything is deterministic from `DefectConfig.seed`, so any defective
feed can be regenerated exactly, in a test or an investigation.

Every injection is appended to a **manifest** (`InjectionRecord`): the
ground truth against which defect *detection* is later measured. A
data-quality framework that can't answer "did we catch all seeded
defects?" is decoration (brief of the project, rule 9).
"""

import random
from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from parvum_ingest.model import (
    CashStatement,
    HoldingsStatement,
    IdentifierScheme,
    SecurityIdentifier,
)


class DefectType(StrEnum):
    # Semantic — holdings statements
    MISSING_COST_BASIS = "MISSING_COST_BASIS"
    MISTYPED_ISIN = "MISTYPED_ISIN"
    STALE_PRICE = "STALE_PRICE"
    # Semantic — cash statements
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    DROPPED_TRANSACTION = "DROPPED_TRANSACTION"
    SETTLEMENT_SHIFT = "SETTLEMENT_SHIFT"
    # Syntactic — rendered text
    TRUNCATED_FILE = "TRUNCATED_FILE"


_HOLDINGS_DEFECTS = frozenset(
    {DefectType.MISSING_COST_BASIS, DefectType.MISTYPED_ISIN, DefectType.STALE_PRICE}
)
_CASH_DEFECTS = frozenset(
    {
        DefectType.DUPLICATE_TRANSACTION,
        DefectType.DROPPED_TRANSACTION,
        DefectType.SETTLEMENT_SHIFT,
    }
)


class InjectionRecord(BaseModel):
    """One line of ground truth: what was corrupted, where, and how."""

    model_config = ConfigDict(frozen=True)

    defect: DefectType
    target_id: str  # ISIN / transaction id the defect landed on
    detail: str  # human-readable before → after


class DefectConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int
    defects: tuple[DefectType, ...]


def inject_holdings(
    stmt: HoldingsStatement, config: DefectConfig
) -> tuple[HoldingsStatement, list[InjectionRecord]]:
    """Apply the config's holdings-applicable defects; non-holdings defect
    types in the config are ignored here (they belong to the cash/text
    injectors). Returns the corrupted copy and the manifest."""
    rng = random.Random(config.seed)
    positions = list(stmt.positions)
    manifest: list[InjectionRecord] = []

    for defect in config.defects:
        if defect not in _HOLDINGS_DEFECTS:
            continue

        if defect is DefectType.MISSING_COST_BASIS:
            candidates = [i for i, p in enumerate(positions) if p.cost_basis is not None]
            if not candidates:
                continue
            i = rng.choice(candidates)
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=positions[i].security.value,
                    detail=f"cost_basis {positions[i].cost_basis} -> None",
                )
            )
            positions[i] = positions[i].model_copy(update={"cost_basis": None})

        elif defect is DefectType.MISTYPED_ISIN:
            candidates = [
                i for i, p in enumerate(positions) if p.security.scheme is IdentifierScheme.ISIN
            ]
            if not candidates:
                continue
            i = rng.choice(candidates)
            old = positions[i].security.value
            # Bump the check digit: still shaped like an ISIN, but the
            # checksum no longer holds — a typo, not garbage.
            new = old[:-1] + str((int(old[-1]) + 1) % 10)
            manifest.append(InjectionRecord(defect=defect, target_id=old, detail=f"{old} -> {new}"))
            positions[i] = positions[i].model_copy(
                update={"security": SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=new)}
            )

        elif defect is DefectType.STALE_PRICE:
            candidates = [i for i, p in enumerate(positions) if p.price_as_of is not None]
            if not candidates:
                continue
            i = rng.choice(candidates)
            assert positions[i].price_as_of is not None
            stale = positions[i].price_as_of - timedelta(days=5)
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=positions[i].security.value,
                    detail=f"price_as_of {positions[i].price_as_of} -> {stale}",
                )
            )
            positions[i] = positions[i].model_copy(update={"price_as_of": stale})

    return stmt.model_copy(update={"positions": tuple(positions)}), manifest


def inject_cash(
    stmt: CashStatement, config: DefectConfig
) -> tuple[CashStatement, list[InjectionRecord]]:
    """Apply the config's cash-applicable defects. Balances are left
    untouched on purpose: a duplicated or dropped entry makes the closing
    balance stop explaining the movement — the invariant break IS the
    defect."""
    rng = random.Random(config.seed)
    entries = list(stmt.entries)
    manifest: list[InjectionRecord] = []

    for defect in config.defects:
        if defect not in _CASH_DEFECTS or not entries:
            continue

        if defect is DefectType.DUPLICATE_TRANSACTION:
            txn = rng.choice(entries)
            # Same id, same everything — how a re-sent file duplicates.
            entries.append(txn)
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=txn.transaction_id,
                    detail=f"entry duplicated ({txn.type}, {txn.amount.amount})",
                )
            )

        elif defect is DefectType.DROPPED_TRANSACTION:
            i = rng.randrange(len(entries))
            txn = entries.pop(i)
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=txn.transaction_id,
                    detail=f"entry dropped ({txn.type}, {txn.amount.amount})",
                )
            )

        elif defect is DefectType.SETTLEMENT_SHIFT:
            i = rng.randrange(len(entries))
            shifted = entries[i].settlement_date + timedelta(days=1)
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=entries[i].transaction_id,
                    detail=f"settlement_date {entries[i].settlement_date} -> {shifted}",
                )
            )
            entries[i] = entries[i].model_copy(update={"settlement_date": shifted})

    return stmt.model_copy(update={"entries": tuple(entries)}), manifest


def truncate_text(rendered: str, seed: int) -> tuple[str, InjectionRecord]:
    """Syntactic defect: cut the rendered file off mid-stream (a failed
    transfer). The parser, not the data-quality layer, must reject this."""
    rng = random.Random(seed)
    cut = rng.randrange(len(rendered) // 2, (len(rendered) * 9) // 10)
    return rendered[:cut], InjectionRecord(
        defect=DefectType.TRUNCATED_FILE,
        target_id="<file>",
        detail=f"truncated at byte {cut} of {len(rendered)}",
    )
