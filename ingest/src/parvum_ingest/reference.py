"""The smallest honest securities-master slice: curated issuer domiciles.

Why this exists — the trap that forced it: a CUSIP does not reveal its
issuer's country. CINS codes (leading letter) announce themselves, but
Canadian issuers get ordinary numeric CUSIPs, indistinguishable from US
ones. Two of our real 13F filers hold exactly such names — Canadian
National Railway and Brookfield — and deriving their ISINs with the default
"US" would mint identifiers that exist nowhere while passing every check we
have (`US1363751029` instead of the real `CA1363751027`).

So: a hand-curated override map, checked against the issuers' real published
ISINs in tests. This is deliberately a *few real facts*, not a dataset —
D-004's "small real slice" rule. Phase 2's securities master (OpenFIGI +
SEC/GLEIF data) replaces it; until then, any CUSIP not listed here is
treated as US-domiciled, and that default is the recorded risk: a
newly-added filer holding an uncurated cross-listed name would fabricate an
ISIN silently. The mitigation is the review step in `make fetch-13f`'s
output plus the checksum tests pinning the names we do know.

Note what does NOT belong here: ADRs. A depositary receipt is a US
instrument with a genuine US CUSIP and US ISIN, whatever the underlying
company's home (Diageo's ADR is legitimately `US25243Q…`). Only issuers
whose *ordinary shares* trade in the US under a home-country ISIN need an
entry.
"""

# CUSIP → ISO country code of the issuer's domicile, where it is not "US".
ISSUER_DOMICILES: dict[str, str] = {
    "136375102": "CA",  # Canadian National Railway — ordinary shares, NYSE cross-listed
    "11271J107": "CA",  # Brookfield Corp
    "76131D103": "CA",  # Restaurant Brands International
    # Redomiciled to Ontario in 2016; found by the fetch-time audit, not by
    # the name — which sits one character from the (US) Waste Mgmt 94106L109.
    "94106B101": "CA",  # Waste Connections
}


def domicile_of(cusip: str) -> str:
    """The issuer's country for ISIN construction. Defaults to US (see module doc)."""
    return ISSUER_DOMICILES.get(cusip.strip().upper(), "US")
