"""Config-driven defect injection for alts documents — the same discipline
as ``parvum_ingest.defects``: deterministic, every corruption recorded in
an ``InjectionRecord`` so later detection quality (a deterministic
validation step, and eventually an LLM-extraction eval harness) can be
measured against ground truth.

Semantic only for now: every defect here corrupts the *model* before
rendering, so the PDF stays perfectly well-formed — it is what a human or
an LLM reading it would get wrong, not a corrupted file. Unlike
``parvum_ingest.defects`` (which injects into a *collection* — one of many
positions or cash entries — and so needs a seeded RNG to pick which one),
each function here operates on a single already-selected document: there is
no "which one" choice to make, so no RNG is needed at this layer. The seed
in ``DefectConfig`` exists only so callers (``generate.py``) can decide
*whether* a defect type is present in a given document's delivery,
mirroring ``parvum_ingest``'s ``_pick_defects`` pattern.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from parvum_alts_hitl.model import CapitalAccountStatement, CapitalCallNotice, DistributionNotice


class DefectType(StrEnum):
    MISSING_FIELD = "MISSING_FIELD"
    ARITHMETIC_ERROR = "ARITHMETIC_ERROR"
    COMMITMENT_MISMATCH = "COMMITMENT_MISMATCH"
    AMOUNT_TRANSPOSITION = "AMOUNT_TRANSPOSITION"


_CALL_DEFECTS = frozenset(
    {DefectType.MISSING_FIELD, DefectType.COMMITMENT_MISMATCH, DefectType.AMOUNT_TRANSPOSITION}
)
_DISTRIBUTION_DEFECTS = frozenset({DefectType.MISSING_FIELD, DefectType.AMOUNT_TRANSPOSITION})
_STATEMENT_DEFECTS = frozenset({DefectType.ARITHMETIC_ERROR})


class InjectionRecord(BaseModel):
    """One line of ground truth: what was corrupted, where, and how."""

    model_config = ConfigDict(frozen=True)

    defect: DefectType
    target_id: str
    detail: str


class DefectConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int
    defects: tuple[DefectType, ...]


def _transpose_amount(value: Decimal) -> Decimal:
    """Swap the two leading digits of the whole-dollar part — a classic
    data-entry/OCR error ($150,000 -> $510,000). Leading digits, not
    trailing ones: fund amounts here are round to the nearest hundred or
    thousand, so the *trailing* digits are usually zeros and swapping them
    would silently be a no-op. A no-op on amounts with fewer than two
    integer digits, since there is nothing to swap."""
    text = f"{value:.2f}"
    sign = ""
    whole, _, frac = text.partition(".")
    if whole.startswith("-"):
        sign, whole = "-", whole[1:]
    if len(whole) < 2:
        return value
    swapped = whole[1] + whole[0] + whole[2:]
    return Decimal(f"{sign}{swapped}.{frac}")


def inject_call(
    notice: CapitalCallNotice, config: DefectConfig
) -> tuple[CapitalCallNotice, list[InjectionRecord]]:
    manifest: list[InjectionRecord] = []
    updated = notice
    target = f"{notice.fund_id}/call-{notice.call_number}"

    for defect in config.defects:
        if defect not in _CALL_DEFECTS:
            continue

        if defect is DefectType.MISSING_FIELD and updated.purpose is not None:
            manifest.append(
                InjectionRecord(
                    defect=defect, target_id=target, detail=f"purpose '{updated.purpose}' -> None"
                )
            )
            updated = updated.model_copy(update={"purpose": None})

        elif defect is DefectType.COMMITMENT_MISMATCH:
            wrong = updated.cumulative_called + Decimal("1000.00")
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=target,
                    detail=f"cumulative_called {updated.cumulative_called} -> {wrong}",
                )
            )
            updated = updated.model_copy(update={"cumulative_called": wrong})

        elif defect is DefectType.AMOUNT_TRANSPOSITION:
            transposed = _transpose_amount(updated.call_amount)
            if transposed != updated.call_amount:
                manifest.append(
                    InjectionRecord(
                        defect=defect,
                        target_id=target,
                        detail=f"call_amount {updated.call_amount} -> {transposed}",
                    )
                )
                updated = updated.model_copy(update={"call_amount": transposed})

    return updated, manifest


def inject_distribution(
    notice: DistributionNotice, config: DefectConfig
) -> tuple[DistributionNotice, list[InjectionRecord]]:
    manifest: list[InjectionRecord] = []
    updated = notice
    target = f"{notice.fund_id}/distribution-{notice.distribution_number}"

    for defect in config.defects:
        if defect not in _DISTRIBUTION_DEFECTS:
            continue

        if defect is DefectType.MISSING_FIELD and updated.source is not None:
            manifest.append(
                InjectionRecord(
                    defect=defect, target_id=target, detail=f"source {updated.source} -> None"
                )
            )
            updated = updated.model_copy(update={"source": None})

        elif defect is DefectType.AMOUNT_TRANSPOSITION:
            transposed = _transpose_amount(updated.distribution_amount)
            if transposed != updated.distribution_amount:
                manifest.append(
                    InjectionRecord(
                        defect=defect,
                        target_id=target,
                        detail=f"distribution_amount {updated.distribution_amount} -> {transposed}",
                    )
                )
                updated = updated.model_copy(update={"distribution_amount": transposed})

    return updated, manifest


def inject_statement(
    statement: CapitalAccountStatement, config: DefectConfig
) -> tuple[CapitalAccountStatement, list[InjectionRecord]]:
    manifest: list[InjectionRecord] = []
    updated = statement
    target = f"{statement.fund_id}/statement-{statement.period_end.isoformat()}"

    for defect in config.defects:
        if defect not in _STATEMENT_DEFECTS:
            continue

        if defect is DefectType.ARITHMETIC_ERROR:
            wrong = updated.ending_balance + Decimal("500.00")
            manifest.append(
                InjectionRecord(
                    defect=defect,
                    target_id=target,
                    detail=(
                        f"ending_balance {updated.ending_balance} -> {wrong} (no longer reconciles)"
                    ),
                )
            )
            updated = updated.model_copy(update={"ending_balance": wrong})

    return updated, manifest
