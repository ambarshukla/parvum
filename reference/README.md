# reference/

The reference-data layer, as its own package (`parvum-reference`): the
data that gives meaning to what the feeds deliver, as opposed to the
feeds themselves.

- `accounts.py` — the account universe: every custodial account the firm
  oversees, with its filer, divisor, and currency.
- `domicile.py` — curated issuer-domicile overrides (the Canada trap:
  Canadian issuers carry US-looking numeric CUSIPs).
- `ownership.py` — the client → legal-entity → account graph with
  percentage edges, self-validating at construction.
- `openfigi.py` / `securities_master.py` — instrument identity via the
  OpenFIGI API, with unmappable ISINs kept as first-class Unknown rows.

The dependency points one way: `parvum-ingest` consumes this package,
never the reverse. The `parvum-build-master` CLI lives in ingest because
building the master takes its ISINs from the 13F store (pipeline data);
the client and model it calls live here. Both packages are members of the
uv workspace rooted one directory up, sharing a single lockfile.
