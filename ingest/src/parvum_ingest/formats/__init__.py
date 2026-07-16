"""Wire-format renderers and parsers — the spokes around the canonical model.

Each format module exposes `render_*(statement) -> str` and
`parse_*(text) -> statement`. Parsers raise FeedParseError on structurally
broken input (not-XML, missing required elements); *plausibility* problems
travel through in the model, per D-009.
"""


class FeedParseError(ValueError):
    """Input cannot be parsed into the canonical model at all.

    Distinct from a data-quality issue: a file that parses but lies is DQ's
    job; a file we cannot even read raises this.
    """
