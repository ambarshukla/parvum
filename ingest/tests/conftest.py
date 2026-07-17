"""Shared test wiring.

The book builder resolves its 13F filing store from PARVUM_EDGAR_CACHE when
no explicit path is given. Pointing it at the committed fixture store here
keeps every test offline and byte-stable: the fixtures are trimmed filings
with real accession metadata (Q4-2025 filed 2026-02-17, Q1-2026 filed
2026-05-15), so point-in-time selection is exercised for real — tests dated
2026-07-15 build from the Q1 fixture; boundary tests reach both.

Set at import time rather than per-test because it is process-wide test
topology, not a per-test knob — a test that needs a different store passes
`cache_dir` explicitly.
"""

import os
from pathlib import Path

os.environ["PARVUM_EDGAR_CACHE"] = str(Path(__file__).parent / "fixtures" / "edgar")
