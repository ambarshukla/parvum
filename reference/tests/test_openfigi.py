"""OpenFIGI client: batching, miss-handling, and errors — all offline.

The HTTP layer (`_post`) is stubbed, so these prove the client's logic
without a network call. One test hits the real API and is skipped unless
PARVUM_OPENFIGI_LIVE is set — kept out of CI, available for a manual check.
"""

import os

import pytest

from parvum_reference import openfigi
from parvum_reference.openfigi import OpenFigiError, map_isins


def _stub_post(monkeypatch, responder):
    monkeypatch.setattr(openfigi, "_post", responder)
    # Neutralise the inter-request pause so batching tests stay fast.
    monkeypatch.setattr(openfigi.time, "sleep", lambda _s: None)


def test_maps_hits_and_records_misses(monkeypatch) -> None:
    def responder(jobs):
        out = []
        for job in jobs:
            if job["idValue"] == "US9999999999":
                out.append({"error": "No identifier found."})
            else:
                out.append({"data": [{"figi": "BBG-" + job["idValue"], "name": "X"}]})
        return out

    _stub_post(monkeypatch, responder)
    result = map_isins(["US0378331005", "US9999999999"])
    assert result["US0378331005"].figi == "BBG-US0378331005"
    assert result["US9999999999"] is None  # a miss is None, not an exception


def test_requests_are_chunked_to_the_api_limit(monkeypatch) -> None:
    monkeypatch.setattr(openfigi, "_MAX_JOBS_PER_REQUEST", 2)
    seen_batch_sizes = []

    def responder(jobs):
        seen_batch_sizes.append(len(jobs))
        return [{"data": [{"figi": "BBG-" + j["idValue"]}]} for j in jobs]

    _stub_post(monkeypatch, responder)
    result = map_isins([f"US{i:010d}" for i in range(5)])
    assert seen_batch_sizes == [2, 2, 1]  # 5 jobs, cap 2 -> three requests
    assert len(result) == 5


def test_duplicate_isins_are_mapped_once(monkeypatch) -> None:
    calls = []

    def responder(jobs):
        calls.extend(j["idValue"] for j in jobs)
        return [{"data": [{"figi": "BBG-" + j["idValue"]}]} for j in jobs]

    _stub_post(monkeypatch, responder)
    map_isins(["US0378331005", "US0378331005", "US0378331005"])
    assert calls == ["US0378331005"]  # deduplicated before the request


def test_result_count_mismatch_is_an_error(monkeypatch) -> None:
    _stub_post(monkeypatch, lambda jobs: [])  # API returned nothing for 1 job
    with pytest.raises(OpenFigiError, match="results for"):
        map_isins(["US0378331005"])


@pytest.mark.skipif(
    not os.environ.get("PARVUM_OPENFIGI_LIVE"),
    reason="live OpenFIGI check; set PARVUM_OPENFIGI_LIVE=1 to run",
)
def test_live_mapping_of_a_known_isin() -> None:
    result = map_isins(["US0378331005"])  # Apple
    assert result["US0378331005"] is not None
    assert result["US0378331005"].market_sector == "Equity"
