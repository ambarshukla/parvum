"""SEC EDGAR client: real institutional holdings from 13F-HR filings.

Why this is a plain Python module and not a Databricks notebook: Free
Edition's serverless compute has no open internet access (D-006), so every
external fetch runs where egress exists — a laptop, or a GitHub Actions
runner — and lands its output where the lakehouse can read it.

**Source:** SEC EDGAR, 13F-HR "information tables" — quarterly disclosures of
US institutional equity holdings. **Licence:** public domain (US government
work). **Volume:** one filing is ~45 KB; we read one.

Three things the real filings teach, each of which this module encodes:

- **An information table is not a position list.** Holdings are broken out
  per manager, so one security appears many times — Berkshire's 2026-Q1
  filing is 90 rows describing 29 securities, with Apple appearing twelve
  times. Aggregating by CUSIP isn't tidying up; skip it and Apple is counted
  twelve times over.
- **Not every row is a share position.** `sshPrnamtType` of `PRN` is a debt
  principal amount, and a row carrying `putCall` is an option. Neither is a
  holding of shares.
- **`value` is whole dollars** in modern filings — but it was *thousands*
  before the January 2023 rule change, so a historical filing read with
  today's assumption is wrong by a factor of 1000. We read current filings
  and say so rather than silently assuming.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}"

# SEC asks for no more than 10 requests/second. We make three, so this is
# politeness rather than necessity — but a fetch loop that ignores a
# publisher's stated limits is how access gets withdrawn for everyone.
_MIN_SECONDS_BETWEEN_REQUESTS = 0.11
_last_request_at = 0.0


class EdgarError(RuntimeError):
    """EDGAR could not be read: network, access policy, or an unexpected document."""


class Filing13F(BaseModel):
    """Identity and provenance of one 13F-HR filing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cik: int
    filer: str
    accession: str
    filing_date: date
    period: date  # quarter end the holdings describe — not when they were filed


class Holding13F(BaseModel):
    """One security in a filing, aggregated across the filer's managers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cusip: str
    issuer: str
    title_of_class: str
    shares: Decimal
    value_usd: Decimal


def _user_agent() -> str:
    """The contact string SEC requires on every request.

    Deliberately required config with no default. SEC's fair-access policy
    says traffic must identify its sender; a default baked into the repo
    would put whoever wrote it on the hook for everyone else's requests.
    """
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise EdgarError(
            "SEC_USER_AGENT is not set. SEC's fair-access policy requires every request "
            "to identify its sender, and refuses anonymous traffic with HTTP 403. Set it "
            "to a name and contact email, e.g. SEC_USER_AGENT='Your Name you@example.com'"
        )
    if "@" not in ua:
        # Verified against the live service: a User-Agent without an email is
        # rejected with 403. Failing here turns a baffling remote error into a
        # local one that says what to do.
        raise EdgarError(
            f"SEC_USER_AGENT must include a contact email — SEC rejects anything else with "
            f"HTTP 403. Got {ua!r}. Example: 'Your Name you@example.com'"
        )
    return ua


def _get(url: str, *, timeout: float = 30.0) -> bytes:
    global _last_request_at
    wait = _MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise EdgarError(
                f"EDGAR refused the request (HTTP 403) for {url}. This almost always means "
                "the User-Agent is unacceptable — check SEC_USER_AGENT names a real contact."
            ) from exc
        raise EdgarError(f"EDGAR returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise EdgarError(f"could not reach EDGAR ({url}): {exc.reason}") from exc
    finally:
        _last_request_at = time.monotonic()


def latest_13f(cik: int) -> Filing13F:
    """The most recent 13F-HR filed by `cik`.

    Amendments (`13F-HR/A`) are skipped: they restate an earlier filing, and
    stitching a restatement onto its original is a reconciliation exercise,
    not a fetch concern. Only EDGAR's `recent` window (roughly the last year)
    is searched, which is ample for a filer reporting quarterly.
    """
    payload = json.loads(_get(_SUBMISSIONS_URL.format(cik=cik)))
    recent = payload["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "13F-HR":
            return Filing13F(
                cik=cik,
                filer=payload["name"],
                accession=recent["accessionNumber"][i],
                filing_date=date.fromisoformat(recent["filingDate"][i]),
                period=date.fromisoformat(recent["reportDate"][i]),
            )
    raise EdgarError(f"no 13F-HR filing in EDGAR's recent window for CIK {cik}")


def information_table_url(filing: Filing13F) -> str:
    """Locate the information table within a filing's directory.

    It has no stable filename — Berkshire's 2026-Q1 table is `53405.xml` —
    so it's identified structurally: the one XML that isn't the cover page.
    If that ever stops being true the error says so instead of guessing.
    """
    base = _ARCHIVE_URL.format(cik=filing.cik, accession=filing.accession.replace("-", ""))
    listing = json.loads(_get(f"{base}/index.json"))
    xml_names = [
        item["name"]
        for item in listing["directory"]["item"]
        if item["name"].lower().endswith(".xml") and item["name"].lower() != "primary_doc.xml"
    ]
    if len(xml_names) != 1:
        raise EdgarError(
            f"expected exactly one information table XML in {base}, found {xml_names or 'none'}"
        )
    return f"{base}/{xml_names[0]}"


def _child(element: ET.Element, name: str) -> ET.Element | None:
    # Matched by local name, ignoring the namespace: filings are produced by
    # many different agents and the namespace prefix varies between them,
    # while the element names do not.
    return next((c for c in element.iter() if c.tag.rpartition("}")[2] == name), None)


def _text(element: ET.Element, name: str) -> str | None:
    found = _child(element, name)
    return None if found is None or found.text is None else found.text.strip()


def parse_information_table(xml: str) -> tuple[Holding13F, ...]:
    """Parse an information table into one entry per security, value-ordered.

    Rows are summed by CUSIP (the per-manager breakout described in the module
    docstring), and rows that aren't share positions — debt principal, options
    — are dropped. Share classes stay distinct because they carry distinct
    CUSIPs: Alphabet legitimately appears twice.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise EdgarError(f"information table is not well-formed XML: {exc}") from exc

    totals: dict[str, dict[str, object]] = {}
    for row in (e for e in root if e.tag.rpartition("}")[2] == "infoTable"):
        cusip = (_text(row, "cusip") or "").upper()
        if not cusip:
            raise EdgarError("an infoTable row has no cusip")
        if _child(row, "putCall") is not None:
            continue  # an option on the security, not a holding of it
        if (_text(row, "sshPrnamtType") or "SH") != "SH":
            continue  # PRN = debt principal amount, not a share count

        entry = totals.setdefault(
            cusip,
            {
                "issuer": _text(row, "nameOfIssuer") or "",
                "title_of_class": _text(row, "titleOfClass") or "",
                "shares": Decimal(0),
                "value_usd": Decimal(0),
            },
        )
        entry["shares"] += Decimal(_text(row, "sshPrnamt") or "0")
        entry["value_usd"] += Decimal(_text(row, "value") or "0")

    holdings = [
        Holding13F(
            cusip=cusip,
            issuer=str(e["issuer"]),
            title_of_class=str(e["title_of_class"]),
            shares=e["shares"],
            value_usd=e["value_usd"],
        )
        for cusip, e in totals.items()
    ]
    # Value-ordered, CUSIP breaking ties: a stable order keeps the committed
    # seed file's diffs meaningful rather than noise from dict ordering.
    return tuple(sorted(holdings, key=lambda h: (-h.value_usd, h.cusip)))


def fetch_13f_holdings(cik: int) -> tuple[Filing13F, tuple[Holding13F, ...]]:
    """Fetch and parse the latest 13F-HR holdings for a filer (three requests)."""
    filing = latest_13f(cik)
    xml = _get(information_table_url(filing)).decode("utf-8")
    return filing, parse_information_table(xml)
