"""Read the Ops page's curated display labels.

`dq_metrics` is deliberately open — adding a check means adding one more
`SELECT` to a `UNION ALL` — and the register's SLO block is open the same way.
Both are good properties for the pipeline and bad ones for the screen, because
nothing connects "publish a metric in Spark" to "name it for a reader".

That gap has now shipped to production twice. D-070's and D-073's metrics
arrived shouting `CROSS_FIELD_INVARIANT_RATE` beside neighbours reading "Cash
consistency"; the fix humanised the fallback and did not close the gap, so
D-075 and D-078 promptly did it again — and a humanising fallback cannot know
that `fx` is an acronym or that `gold` names a medallion layer rather than a
quality, so `fx_integrity` reached a live screen as "Fx integrity".

A fallback makes the symptom cosmetic. Only a gate makes it not happen. This
module reads the label maps so `check` can require one entry per published
metric and per declared service level.

Parsing, not executing: the maps are TypeScript object literals, read with a
regex over the source, in the same spirit as the `ast` scan of the Spark jobs.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `const NAME: Record<string, string> = { ... };`
_MAP = re.compile(
    r"const\s+(?P<name>DQ_METRIC_LABELS|SLO_LABELS)\s*:\s*Record<[^>]*>\s*=\s*\{(?P<body>.*?)\n\};",
    re.DOTALL,
)
#: `  some_identifier: "Some Label",` — comment lines have no bare key.
_KEY = re.compile(r"^\s{4}([a-z][a-z0-9_]*)\s*:", re.MULTILINE)

#: Both maps have carried entries since the day they were written. Zero keys
#: means the shape this scan depends on changed, not that the estate stopped
#: labelling things — and a gate that silently stops checking is worse than
#: one that was never added.
_MIN_LABELS = 4


class OpsLabelScanError(RuntimeError):
    """The Ops page's label maps could not be read."""


def scan_ops_labels(path: Path) -> dict[str, set[str]]:
    """`{"DQ_METRIC_LABELS": {...}, "SLO_LABELS": {...}}` from `internal/src/format.ts`."""
    if not path.is_file():
        raise OpsLabelScanError(f"no label source at {path}")

    text = path.read_text(encoding="utf-8")
    found = {m.group("name"): set(_KEY.findall(m.group("body"))) for m in _MAP.finditer(text)}

    for name in ("DQ_METRIC_LABELS", "SLO_LABELS"):
        if name not in found:
            raise OpsLabelScanError(
                f"{path.name}: no `{name}` map found — either it was renamed or the "
                f"`const NAME: Record<string, string> = {{...}}` shape this scan "
                f"depends on changed. Both would leave the gate passing while "
                f"checking nothing."
            )
        if len(found[name]) < _MIN_LABELS:
            raise OpsLabelScanError(
                f"{path.name}: only {len(found[name])} key(s) parsed out of {name} "
                f"({sorted(found[name])}) — the entry shape this scan depends on has "
                f"probably changed"
            )
    return found
