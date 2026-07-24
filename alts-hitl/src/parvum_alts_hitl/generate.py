"""CLI: manufacture the synthetic private-fund document set — capital call
notices, distribution notices, and capital account statements — for a small
fixed fund universe.

Unlike the custodial feed generator (one delivery per business day), private
-fund documents are episodic: this generates each fund's whole document
history in one call, not one day at a time. Ground truth (what was injected,
where) is written to ``<out>/../manifests/``, outside the landing directory
— the same discipline as ``parvum_ingest.generate``, so the eventual
extraction/validation pipeline can never read it, only a detection-quality
eval harness may.
"""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from random import Random

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.defects import (
    DefectConfig,
    DefectType,
    inject_call,
    inject_distribution,
    inject_statement,
)
from parvum_alts_hitl.model import FundCommitment
from parvum_alts_hitl.render import (
    DRAWDOWN,
    EURO,
    PLAIN,
    DocTemplate,
    render_capital_account_statement,
    render_capital_call,
    render_distribution,
)

# Each fund's account_id rolls up to an existing custody account from
# parvum_reference.accounts.UNIVERSE (X4478210, FQ5521, FQ9007) — alts
# holdings join the same client rollup as everything else, not a parallel
# universe of their own. FQ5521 hosts two funds deliberately (Bramwell, then
# the EUR fund below) — a real LP can hold more than one fund interest
# through one custody account, and FQ5521's own base currency is EUR
# (accounts.py), which is why the EUR fund pairs with it rather than a
# USD-only account. FQ9007 is the fourth fund's account: it's the one
# account owned outright by the Hartwell Family Foundation (ownership.py),
# so it gives Aldergate/Hartwell its own alts exposure without the
# cross-family entanglement FQ5521/X4478210 have.
FUND_UNIVERSE: tuple[FundCommitment, ...] = (
    FundCommitment(
        fund_id="FUND-PE01",
        fund_name="Meridian Capital Partners IV",
        account_id="X4478210",
        currency="USD",
        vintage_year=2024,
        total_commitment=Decimal("5000000.00"),
    ),
    FundCommitment(
        fund_id="FUND-VC01",
        fund_name="Bramwell Ventures Fund II",
        account_id="FQ5521",
        currency="USD",
        vintage_year=2024,
        total_commitment=Decimal("2000000.00"),
    ),
    FundCommitment(
        fund_id="FUND-EU01",
        fund_name="Alpenrose Capital Fund III",
        account_id="FQ5521",
        currency="EUR",
        vintage_year=2024,
        total_commitment=Decimal("1500000.00"),
    ),
    FundCommitment(
        fund_id="FUND-PE02",
        fund_name="Wraithmoor Endowment Partners III",
        account_id="FQ9007",
        currency="USD",
        vintage_year=2024,
        total_commitment=Decimal("3000000.00"),
    ),
)

# One administrator's document conventions per fund (D-061): a single
# layout/vocabulary/locale made every extraction trivially easy, which was a
# property of the fixture rather than evidence the extractor works. FUND-PE02
# reuses PLAIN rather than a new template — the corpus already spans three
# distinct conventions, and a fourth doesn't teach the extractor anything new.
_TEMPLATE_BY_FUND: dict[str, DocTemplate] = {
    "FUND-PE01": PLAIN,
    "FUND-VC01": DRAWDOWN,
    "FUND-EU01": EURO,
    "FUND-PE02": PLAIN,
}

_CALL_DEFECT_POOL = (
    DefectType.MISSING_FIELD,
    DefectType.COMMITMENT_MISMATCH,
    DefectType.AMOUNT_TRANSPOSITION,
)
_DISTRIBUTION_DEFECT_POOL = (DefectType.MISSING_FIELD, DefectType.AMOUNT_TRANSPOSITION)
_STATEMENT_DEFECT_POOL = (DefectType.ARITHMETIC_ERROR,)
# Per document, the chance a given defect type from its pool is present —
# same value and same shape as parvum_ingest.generate's _DEFECT_PROBABILITY.
_DEFECT_PROBABILITY = 0.25


def _pick_defects(pool: tuple[DefectType, ...], rng: Random) -> tuple[DefectType, ...]:
    return tuple(d for d in pool if rng.random() < _DEFECT_PROBABILITY)


def _doc_seed(fund_index: int, doc_kind: int, doc_number: int) -> int:
    # Derived from fixed, small integers rather than a date (unlike
    # ingest's feeds, these documents aren't dated day-by-day) — still
    # fully deterministic and unique per (fund, document-kind, sequence).
    return fund_index * 100_000 + doc_kind * 10_000 + doc_number


def generate_fund(fund_index: int, commitment: FundCommitment, out_dir: Path) -> dict:
    book = build_fund_book(commitment)
    template = _TEMPLATE_BY_FUND[commitment.fund_id]
    fund_dir = out_dir / commitment.fund_id
    fund_dir.mkdir(parents=True, exist_ok=True)

    documents = []

    for call in book.calls:
        seed = _doc_seed(fund_index, 1, call.call_number)
        config = DefectConfig(seed=seed, defects=_pick_defects(_CALL_DEFECT_POOL, Random(seed)))
        corrupted, injections = inject_call(call, config)
        pdf = render_capital_call(corrupted, template)
        name = f"capital_call_{call.call_number:02d}.pdf"
        (fund_dir / name).write_bytes(pdf)
        documents.append(_doc_entry(name, "capital_call", pdf, corrupted, injections))

    for distribution in book.distributions:
        seed = _doc_seed(fund_index, 2, distribution.distribution_number)
        config = DefectConfig(
            seed=seed, defects=_pick_defects(_DISTRIBUTION_DEFECT_POOL, Random(seed))
        )
        corrupted, injections = inject_distribution(distribution, config)
        pdf = render_distribution(corrupted, template)
        name = f"distribution_{distribution.distribution_number:02d}.pdf"
        (fund_dir / name).write_bytes(pdf)
        documents.append(_doc_entry(name, "distribution", pdf, corrupted, injections))

    for i, statement in enumerate(book.statements, start=1):
        seed = _doc_seed(fund_index, 3, i)
        config = DefectConfig(
            seed=seed, defects=_pick_defects(_STATEMENT_DEFECT_POOL, Random(seed))
        )
        corrupted, injections = inject_statement(statement, config)
        pdf = render_capital_account_statement(corrupted, template)
        name = f"capital_account_{statement.period_end.isoformat()}.pdf"
        (fund_dir / name).write_bytes(pdf)
        documents.append(_doc_entry(name, "capital_account_statement", pdf, corrupted, injections))

    return {
        "fund_id": commitment.fund_id,
        "fund_name": commitment.fund_name,
        "account_id": commitment.account_id,
        "documents": documents,
    }


def _doc_entry(name: str, doc_type: str, pdf: bytes, corrupted, injections: list) -> dict:
    return {
        "name": name,
        "type": doc_type,
        "bytes": len(pdf),
        # The full as-rendered field values (post-corruption) — extraction's
        # ground truth for a later eval harness. Extraction's job is to read
        # what is actually printed, defects and all; correcting a defect is
        # deterministic validation's job, not extraction's, so eval compares
        # against these values, not the clean book.
        "fields": corrupted.model_dump(mode="json"),
        "injections": [r.model_dump(mode="json") for r in injections],
    }


def generate(out_dir: Path) -> list[dict]:
    manifest_dir = out_dir.parent / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifests = []
    for fund_index, commitment in enumerate(FUND_UNIVERSE):
        manifest = generate_fund(fund_index, commitment, out_dir)
        (manifest_dir / f"{commitment.fund_id}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
        )
        manifests.append(manifest)
    return manifests


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic alts (private-fund) documents."
    )
    parser.add_argument(
        "--out", type=Path, default=Path("../data/alts/raw"), help="landing directory"
    )
    args = parser.parse_args()

    manifests = generate(args.out)
    total_documents = sum(len(m["documents"]) for m in manifests)
    print(f"{len(manifests)} funds -> {total_documents} documents under {args.out}")


if __name__ == "__main__":
    main()
