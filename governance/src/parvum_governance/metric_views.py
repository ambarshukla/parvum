"""Read the semantic layer's declared measures out of the metric-view files.

A metric view (`spark/metric_views/*.sql`) is where a business measure is
defined once so SQL, BI and an AI assistant all resolve the term the same way.
That makes it exactly the kind of published surface the register exists to
govern — and it was not governed, because the gate only ever read the Spark
jobs' `COLUMN_COMMENTS`.

The failure mode this closes is specific. A measure whose name is
``Total wealth`` looks self-explanatory and is not: an AI reading the catalog
binds a term to whatever text sits beside it, so a measure with no comment is
a measure a model will guess about. Requiring the comment makes the semantic
contract a contract rather than a naming convention.

Parsing, not executing: these are SQL files with a YAML body between ``$$``
markers. The measure and dimension names come from the YAML, and the business
definitions from the ``COMMENT ON COLUMN`` statements that follow it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

#: The YAML spec sits between the `$$` markers of `LANGUAGE YAML AS $$ ... $$`.
_SPEC = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)

#: `COMMENT ON COLUMN <view>.`<name>` IS '<text>'` — backticked because measure
#: names are human phrases with spaces in them, which is the whole point.
_COMMENT = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+[\w.]+\.`([^`]+)`\s+IS\s+'(.*?)'\s*;",
    re.DOTALL | re.IGNORECASE,
)


class MetricViewScanError(RuntimeError):
    """A metric-view file could not be read for its declared measures."""


@dataclass(frozen=True)
class MetricViewField:
    """One measure or dimension a metric view publishes."""

    view: str
    name: str
    kind: str  # "measure" | "dimension"
    expr: str
    description: str
    source_file: str

    @property
    def key(self) -> str:
        return f"{self.view}.{self.name}"


def scan_metric_views(directory: Path) -> list[MetricViewField]:
    """Every measure and dimension declared in `directory`, with its comment."""
    if not directory.is_dir():
        raise MetricViewScanError(f"no metric-view directory at {directory}")

    fields: list[MetricViewField] = []
    for path in sorted(directory.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        spec_match = _SPEC.search(text)
        if spec_match is None:
            raise MetricViewScanError(
                f"{path.name}: no `$$ ... $$` YAML body — either this is not a metric "
                f"view or the shape this scan depends on has changed"
            )
        try:
            spec = yaml.safe_load(spec_match.group(1))
        except yaml.YAMLError as error:  # pragma: no cover - malformed file
            raise MetricViewScanError(f"{path.name}: spec is not valid YAML: {error}") from error

        view = path.stem
        comments = {name: body.strip() for name, body in _COMMENT.findall(text)}

        for kind in ("measures", "dimensions"):
            for item in spec.get(kind) or []:
                name = item.get("name", "")
                fields.append(
                    MetricViewField(
                        view=view,
                        name=name,
                        kind=kind.rstrip("s"),
                        expr=str(item.get("expr", "")),
                        description=comments.get(name, ""),
                        source_file=path.name,
                    )
                )

    if not fields:
        raise MetricViewScanError(
            f"no measures or dimensions found under {directory} — the metric-view "
            f"file shape this scan depends on has probably changed, and the gate "
            f"would silently stop governing the semantic layer"
        )
    return fields
