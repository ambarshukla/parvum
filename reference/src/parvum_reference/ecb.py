"""ECB euro foreign exchange reference rates — the FX half of reference data.

Why this source: gold must add a family's USD and EUR wealth together, and
inventing an exchange rate would violate the small-real-slice rule (D-004).
The European Central Bank publishes daily reference rates — free, no key,
stable URL, full history back to 1999 — which makes it the cheapest *real*
rates source that exists. We take the USD column only: the universe holds
exactly two currencies, and slicing one real series beats hoarding thirty.

Semantics worth knowing (they shape the consumer, not just this module):
- Rates are EUR-based: one row says "1 EUR = X USD" for one business day.
- The ECB publishes around 16:15 CET on TARGET business days only — no
  weekends, no euro-area holidays. A calendar-complete consumer must carry
  the last published rate forward; `fill_forward` does that *at consumption
  time* so the stored file stays exactly what the ECB said, nothing more.
- These are *reference* rates: indicative, not tradeable quotes. For
  valuation reporting that is precisely what they are for.
"""

import csv
import io
import json
import urllib.request
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# The full-history zip (one small CSV, ~700 KB compressed). Chosen over the
# rolling 90-day file deliberately: the feed pile's window is a config knob
# (DAYS), and a source that silently stops covering the pile's earliest days
# the moment someone raises DAYS is a trap. Full history removes the edge.
_HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
_CSV_MEMBER = "eurofxref-hist.csv"

# Keep only what the universe needs: USD, from just before the earliest data
# this project generates. A smaller slice of a real series, on purpose.
_FLOOR = date(2026, 1, 1)


def _parse_history_csv(text: str) -> dict[date, Decimal]:
    """USD rates by publication date from the ECB history CSV.

    The CSV carries one row per TARGET business day (newest first) and one
    column per currency; empty cells mean "not published that day" (rare,
    but real — a currency can drop out of the reference list).
    """
    rates: dict[date, Decimal] = {}
    for row in csv.DictReader(io.StringIO(text)):
        raw = (row.get("USD") or "").strip()
        if not raw or raw == "N/A":
            continue
        day = date.fromisoformat(row["Date"].strip())
        if day >= _FLOOR:
            rates[day] = Decimal(raw)
    return rates


def fetch_rates(*, timeout: float = 60.0) -> dict[date, Decimal]:
    """Download and parse the ECB history (network). No key required."""
    req = urllib.request.Request(_HIST_URL, headers={"User-Agent": "parvum-reference/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        text = zf.read(_CSV_MEMBER).decode("utf-8")
    return _parse_history_csv(text)


def write_rates(rates: dict[date, Decimal], out: Path) -> dict:
    """Write the rates to JSON with a provenance header. Returns the summary.

    Stored exactly as published — no gap filling here. The store is the
    ECB's claim; calendar-completion is the consumer's interpretation and
    happens in `fill_forward`, where it is visible and tested.
    """
    days = sorted(rates)
    document = {
        "source": {
            "provider": "ECB euro foreign exchange reference rates",
            "base": "EUR",
            "quote": "USD",
            "first": days[0].isoformat() if days else None,
            "last": days[-1].isoformat() if days else None,
            "days": len(days),
        },
        "rates": {d.isoformat(): str(rates[d]) for d in days},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return document["source"]


def load_rates(path: Path) -> dict[date, Decimal]:
    """Read a written rates file back into typed form."""
    document = json.loads(path.read_text(encoding="utf-8"))
    return {date.fromisoformat(d): Decimal(v) for d, v in document["rates"].items()}


def fill_forward(
    rates: dict[date, Decimal], start: date, end: date
) -> dict[date, tuple[Decimal, date]]:
    """A rate for EVERY calendar day in [start, end]: the last published one.

    Returns {day: (rate, published_on)} so a consumer can show not just the
    rate it used but which ECB day it came from — a Saturday's valuation
    carries Friday's rate, and saying so is the difference between a
    carried-forward fact and a made-up one.

    Raises if the series cannot cover `start` (no rate on or before it):
    silently valuing at nothing is exactly the failure this layer exists to
    prevent.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    published = sorted(rates)
    if not published or published[0] > start:
        raise ValueError(
            f"no rate on or before {start}; series starts {published[0] if published else 'never'}"
        )

    filled: dict[date, tuple[Decimal, date]] = {}
    cursor = start
    # Walk the calendar once, advancing through publications as they occur.
    idx = 0
    while published[idx + 1 :] and published[idx + 1] <= start:
        idx += 1
    while cursor <= end:
        while published[idx + 1 :] and published[idx + 1] <= cursor:
            idx += 1
        filled[cursor] = (rates[published[idx]], published[idx])
        cursor += timedelta(days=1)
    return filled
