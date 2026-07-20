# alts-hitl/

Synthetic private-fund ("alts") document generator, and — in later slices —
the extraction, confidence-scoring, and human-review pipeline built on top
of it. Phase 6, the project's centrepiece; see `docs/DECISIONS.md` D-046 for
why the review queue itself lives in the authenticated `internal/` app
rather than here.

## Why synthetic

Custodial feeds (Phase 1) at least have open wire-format specs to build
against. Private-fund documents — capital call notices, distribution
notices, capital account statements — don't: they're private, bilateral
documents between a fund and its limited partners. That opacity is
deliberate and is itself the point (see the project brief and D-046): this
package generates documents in a realistic shape and renders them as real
PDFs, with the same "clean book, then seed deliberate defects, then record
ground truth" discipline `ingest/` already established.

## What's here

- `model.py` — the canonical shapes: `FundCommitment`, `CapitalCallNotice`,
  `DistributionNotice`, `CapitalAccountStatement`.
- `book.py` — `build_fund_book`: a small, deterministic fund waterfall.
  Every capital account statement's `ending_balance` reconciles exactly
  against its own beginning balance and that period's flows, and one
  statement's ending balance chains into the next one's beginning balance —
  by construction, before any defect is injected.
- `defects.py` — `DefectType` (`MISSING_FIELD`, `ARITHMETIC_ERROR`,
  `COMMITMENT_MISMATCH`, `AMOUNT_TRANSPOSITION`) and the injectors. Every
  injection is recorded in an `InjectionRecord` — the ground truth a later
  extraction/validation eval harness measures detection against.
- `render.py` — renders each document type to a real PDF (reportlab).
- `generate.py` — the `parvum-generate-alts-docs` CLI: generates the whole
  document history for a small fixed fund universe (two funds, each rolling
  up to an existing custody account from `parvum_reference.accounts`) in
  one call — private-fund documents are episodic, not a daily feed, so this
  doesn't take a `--days` argument the way `parvum-generate` does.

## Running it

```
uv run parvum-generate-alts-docs --out ../data/alts/raw
```

Writes each fund's PDFs to `<out>/<fund_id>/` and a manifest per fund to
`<out>/../manifests/<fund_id>.json` — outside the landing directory, same
rule as `ingest/`'s manifests: the pipeline must never read it, only
detection-quality evaluation may.

## Tests

```
uv run pytest
```

`test_render.py` reads the rendered PDFs back to text (via `pypdf`) and
asserts the real figures are present — not just "a PDF got produced."
