"""Tests for the EDGAR client, ISIN derivation, and the seed extract.

Deliberately offline: every test reads the committed fixture. CI must never
depend on SEC being reachable — an unpinned network call in CI is a random
failure waiting for someone else's outage (we already learned this the hard
way when a GitHub API blip failed a run).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from parvum_ingest.edgar import (
    EdgarError,
    Filing13F,
    Holding13F,
    _user_agent,
    parse_information_table,
)
from parvum_ingest.model import IdentifierScheme, is_cins, isin_from_cusip
from parvum_ingest.seed_13f import build_seed

FIXTURE = Path(__file__).parent / "fixtures" / "13f_information_table.xml"


@pytest.fixture
def holdings() -> tuple[Holding13F, ...]:
    return parse_information_table(FIXTURE.read_text(encoding="utf-8"))


# --- ISIN derivation -----------------------------------------------------

# Real (CUSIP, ISIN) pairs. These are the check: the derivation is worthless
# if it merely produces something ISIN-shaped, so it is measured against
# identifiers whose true values are independently known.
KNOWN_PAIRS = [
    ("037833100", "US0378331005", "Apple"),
    ("594918104", "US5949181045", "Microsoft"),
    ("023135106", "US0231351067", "Amazon"),
    ("02079K305", "US02079K3059", "Alphabet A"),
    ("46625H100", "US46625H1005", "JPMorgan"),
    ("478160104", "US4781601046", "Johnson & Johnson"),
    ("30231G102", "US30231G1022", "Exxon Mobil"),
    ("191216100", "US1912161007", "Coca-Cola"),
]


@pytest.mark.parametrize(("cusip", "expected_isin", "name"), KNOWN_PAIRS)
def test_isin_derived_from_cusip_matches_the_real_isin(cusip, expected_isin, name):
    assert isin_from_cusip(cusip).value == expected_isin, name


@pytest.mark.parametrize(("cusip", "expected_isin", "name"), KNOWN_PAIRS)
def test_derived_isins_pass_the_independent_checksum(cusip, expected_isin, name):
    # Construction and verification are separate implementations; agreement
    # between them is what makes either trustworthy.
    assert isin_from_cusip(cusip).has_valid_checksum(), name


def test_derived_isin_is_a_well_formed_isin_identifier():
    identifier = isin_from_cusip("037833100")
    assert identifier.scheme is IdentifierScheme.ISIN
    assert len(identifier.value) == 12


def test_country_prefix_is_not_assumed_to_be_us():
    # A Canadian issuer's CUSIP is numeric exactly like a US one, so the
    # domicile cannot be read off the code — Shopify's 82509L107 yields a CA
    # ISIN, and deriving it with the default "US" would invent one.
    canadian = isin_from_cusip("82509L107", country="CA")
    assert canadian.value == "CA82509L1076"
    assert canadian.has_valid_checksum()
    # The check digit is a function of the country prefix too, so the two
    # differ by more than their first two characters — which is precisely why
    # guessing the domicile cannot be made safe.
    assert isin_from_cusip("82509L107").value != canadian.value.replace("CA", "US", 1)


def test_cins_is_refused_rather_than_fabricated():
    # Chubb is Swiss: its real ISIN is CH0044328745. "US" + CINS would be a
    # plausible-looking identifier that exists nowhere, which is worse than
    # an error.
    assert is_cins("H1467J104")
    with pytest.raises(ValueError, match="CINS"):
        isin_from_cusip("H1467J104")


def test_us_domestic_cusips_are_not_mistaken_for_cins():
    assert not is_cins("037833100")


# --- parsing the information table ---------------------------------------


def test_per_manager_rows_are_aggregated_by_cusip(holdings):
    # Apple is two rows in the fixture (twelve in the real filing). One
    # security, or Apple gets counted twice.
    apple = next(h for h in holdings if h.cusip == "037833100")
    assert apple.shares == Decimal("10000")  # 8000 + 2000
    assert apple.value_usd == Decimal("2500000")  # 2,000,000 + 500,000
    assert sum(1 for h in holdings if h.cusip == "037833100") == 1


def test_share_classes_stay_separate(holdings):
    # Same issuer, different CUSIPs: two real positions, not a duplicate.
    alphabet = [h for h in holdings if h.issuer == "ALPHABET INC"]
    assert {h.cusip for h in alphabet} == {"02079K305", "02079K107"}
    assert {h.title_of_class for h in alphabet} == {"CAP STK CL A", "CAP STK CL C"}


def test_debt_principal_rows_are_dropped(holdings):
    # sshPrnamtType PRN is a principal amount, not a share count. Summing it
    # into a share position would be nonsense.
    assert not any(h.cusip == "111111100" for h in holdings)


def test_option_rows_are_dropped(holdings):
    # A put on Coca-Cola is not a holding of Coca-Cola.
    assert not any(h.cusip == "191216100" for h in holdings)


def test_holdings_are_ordered_by_value(holdings):
    values = [h.value_usd for h in holdings]
    assert values == sorted(values, reverse=True)


def test_implied_price_is_recoverable(holdings):
    # 13F carries no price, but value/shares gives the quarter-end price —
    # which is where the seed's plausible prices come from.
    apple = next(h for h in holdings if h.cusip == "037833100")
    assert apple.value_usd / apple.shares == Decimal("250")


def test_unreadable_xml_raises_edgar_error():
    with pytest.raises(EdgarError, match="not well-formed"):
        parse_information_table("<informationTable><infoTable>")


def test_namespace_prefix_does_not_matter():
    # Filings come from many agents and the prefix varies; element names
    # don't. Parsing by local name keeps that variation harmless.
    xml = FIXTURE.read_text(encoding="utf-8").replace(
        'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"',
        'xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable"',
    )
    xml = xml.replace("<infoTable>", "<ns1:infoTable>").replace("</infoTable>", "</ns1:infoTable>")
    xml = xml.replace("<informationTable ", "<ns1:informationTable ").replace(
        "</informationTable>", "</ns1:informationTable>"
    )
    for tag in (
        "nameOfIssuer",
        "titleOfClass",
        "cusip",
        "value",
        "shrsOrPrnAmt",
        "sshPrnamt",
        "sshPrnamtType",
        "putCall",
    ):
        xml = xml.replace(f"<{tag}>", f"<ns1:{tag}>").replace(f"</{tag}>", f"</ns1:{tag}>")
    assert len(parse_information_table(xml)) == 4


# --- the seed extract ----------------------------------------------------


@pytest.fixture
def filing() -> Filing13F:
    return Filing13F(
        cik=1067983,
        filer="BERKSHIRE HATHAWAY INC",
        accession="0001193125-26-226661",
        filing_date="2026-05-15",
        period="2026-03-31",
    )


def test_seed_excludes_cins_and_says_why(filing, holdings):
    seed = build_seed(filing, holdings)
    assert [e["cusip"] for e in seed["excluded"]] == ["H1467J104"]
    assert "CINS" in seed["excluded"][0]["reason"]
    # Excluded means excluded — not silently carried with a fabricated ISIN.
    assert not any(h["cusip"] == "H1467J104" for h in seed["holdings"])


def test_seed_carries_derived_isins(filing, holdings):
    seed = build_seed(filing, holdings)
    apple = next(h for h in seed["holdings"] if h["cusip"] == "037833100")
    assert apple["isin"] == "US0378331005"


def test_seed_records_provenance(filing, holdings):
    seed = build_seed(filing, holdings)
    # The accession pins the exact immutable filing — the one fact that makes
    # this extract reproducible by anyone else.
    assert seed["source"]["accession"] == "0001193125-26-226661"
    assert seed["source"]["period"] == "2026-03-31"


def test_seed_has_no_retrieval_timestamp(filing, holdings):
    # A timestamp would make the file differ on every fetch, turning the
    # scheduled check into a source of meaningless pull requests.
    seed = build_seed(filing, holdings)
    assert "retrieved_at" not in seed["source"]


def test_seed_keeps_exact_numbers_as_strings(filing, holdings):
    # JSON numbers are floats; share counts and dollar values must not be.
    seed = build_seed(filing, holdings)
    assert all(isinstance(h["shares"], str) for h in seed["holdings"])
    assert all(isinstance(h["value_usd"], str) for h in seed["holdings"])


# --- SEC's access policy -------------------------------------------------


def test_missing_user_agent_fails_locally_with_guidance(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(EdgarError, match="SEC_USER_AGENT is not set"):
        _user_agent()


def test_user_agent_without_a_contact_is_rejected_before_the_request(monkeypatch):
    # Verified against the live service: SEC answers 403 to a User-Agent with
    # no email. Catching it here turns a baffling remote error into a local
    # one that says what to do.
    monkeypatch.setenv("SEC_USER_AGENT", "parvum-reference-build")
    with pytest.raises(EdgarError, match="contact email"):
        _user_agent()


def test_valid_user_agent_is_accepted(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Parvum Reference Build someone@example.com")
    assert _user_agent() == "Parvum Reference Build someone@example.com"


def test_parsing_needs_neither_network_nor_credentials(monkeypatch):
    # Guards the offline property: parsing works with no SEC_USER_AGENT set at
    # all. If this ever fails, something on the parse path has started
    # reaching for the network — and CI would then depend on SEC's uptime.
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert len(parse_information_table(FIXTURE.read_text(encoding="utf-8"))) == 4
