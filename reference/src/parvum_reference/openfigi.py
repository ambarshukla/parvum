"""OpenFIGI client: map security identifiers to FIGIs and instrument metadata.

The securities master's external source. Like EDGAR (D-006), this runs where
open egress exists — a laptop or a GitHub Actions runner — never inside
Databricks; the built master is landed for the lakehouse to read.

**Source:** OpenFIGI v3 mapping API (Bloomberg-operated, free). **What it
gives us:** for an ISIN, the FIGI (a stable open instrument id), the issuer
name, the security type (Common Stock, ADR…), and the market sector
(Equity…). **Why it matters:** feeds carry ISINs, which are proprietary-ish
and issuer-scoped; FIGI is the open, join-friendly key a securities master
normalises everything onto — and the metadata is what gold groups by.

Two real characteristics the client encodes:
- **Batching.** The mapping endpoint takes up to 100 jobs per request; a key
  raises the per-minute allowance. We chunk and pace accordingly.
- **A miss is data, not an error.** An ISIN OpenFIGI can't map comes back
  with an `error`, not a match — that unmapped security is exactly what the
  master's "Unknown" bucket exists to make visible (D-022), so the client
  surfaces misses rather than raising on them.
"""

import json
import os
import time
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict

_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
# The API caps a mapping request at 100 jobs.
_MAX_JOBS_PER_REQUEST = 100
# Without a key the limit is far lower; with one, ~25 requests/6s. We pace
# gently either way — a fetch loop that ignores a publisher's limits is how
# access gets pulled for everyone.
_SECONDS_BETWEEN_REQUESTS = 0.3


class OpenFigiError(RuntimeError):
    """OpenFIGI could not be reached or returned an unusable response."""


class FigiRecord(BaseModel):
    """One instrument's OpenFIGI metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    figi: str
    name: str | None = None
    security_type: str | None = None
    market_sector: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None


def _api_key() -> str | None:
    # Optional: the client works keyless (lower rate limit). Absent key is a
    # slower fetch, not an error — unlike SEC_USER_AGENT, which SEC requires.
    key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    return key or None


def _post(jobs: list[dict], *, timeout: float = 30.0) -> list[dict]:
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    request = urllib.request.Request(
        _MAPPING_URL, data=json.dumps(jobs).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise OpenFigiError(
                "OpenFIGI rate limit hit (HTTP 429). Set OPENFIGI_API_KEY for a higher "
                "allowance, or slow the request cadence."
            ) from exc
        raise OpenFigiError(f"OpenFIGI returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpenFigiError(f"could not reach OpenFIGI: {exc.reason}") from exc


def map_isins(isins: list[str]) -> dict[str, FigiRecord | None]:
    """Map each ISIN to its primary FIGI record, or None if OpenFIGI has no match.

    A None value is a real answer — the identifier is unmapped — and its
    handling (the "Unknown" bucket) belongs to the master, not here.
    """
    unique = sorted(set(isins))
    result: dict[str, FigiRecord | None] = {}

    for start in range(0, len(unique), _MAX_JOBS_PER_REQUEST):
        chunk = unique[start : start + _MAX_JOBS_PER_REQUEST]
        if start:
            time.sleep(_SECONDS_BETWEEN_REQUESTS)
        responses = _post([{"idType": "ID_ISIN", "idValue": isin} for isin in chunk])
        if len(responses) != len(chunk):
            raise OpenFigiError(f"OpenFIGI returned {len(responses)} results for {len(chunk)} jobs")
        for isin, res in zip(chunk, responses, strict=True):
            matches = res.get("data")
            if not matches:  # {'error': ...} or empty — an unmapped identifier
                result[isin] = None
                continue
            # The first match is the primary listing; alternates are other
            # venues of the same instrument, which the master doesn't need.
            m = matches[0]
            result[isin] = FigiRecord(
                figi=m["figi"],
                name=m.get("name"),
                security_type=m.get("securityType"),
                market_sector=m.get("marketSector"),
                ticker=m.get("ticker"),
                exchange_code=m.get("exchCode"),
            )
    return result
