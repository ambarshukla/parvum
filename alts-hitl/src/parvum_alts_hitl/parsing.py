"""Shared decimal parsing for extracted amount fields — used by
``extract.py`` (self-consistency), ``validate.py`` (cross-document checks),
and ``evaluate.py`` (ground-truth comparison), so a defensive fix (or a
bug) is made once, not independently in three places. That independence is
exactly how a real bug shipped: only one field's tool-schema description
told the model to omit currency symbols/commas, so every *other* amount
field came back as ``"$750,000.00"`` and three copies of a bare
``Decimal(str(value))`` all failed to parse it the same way (D-053).
"""

from decimal import Decimal, InvalidOperation


def parse_decimal(value: object) -> Decimal | None:
    """Parses a monetary value that should already be a plain decimal
    string, tolerating a stray currency symbol or thousands separator if a
    model didn't follow the schema's formatting instruction exactly —
    defense in depth, not a substitute for the instruction itself (which
    still matters: a `$` stripped here is one the model spent output
    tokens on for nothing)."""
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None
