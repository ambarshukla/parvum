"""MT535 (SWIFT / ISO 15022 Statement of Holdings) — render & parse.

Where semt.002 is XML, MT535 is a line-based fixed-tag format: fields are
`:TAG:content` lines, and `:16R:BLOCK` / `:16S:BLOCK` pairs open and close
named blocks (GENL for general statement info, FIN for each holding).
Numbers use a decimal COMMA and always carry one ("220," is the integer
220) — a SWIFT convention that has corrupted many a naive parser.

Scope honesty (D-010): a subset shaped after the real message — genuine
tags and qualifiers (:20C::SEME, :98A::STAT, :93B::AGGR, :90B::MRKT,
:19A::HOLD), rendered as the body text only (no SWIFT envelope blocks
{1:}{2:}), and field-length rules are not enforced.

Field-coverage notes (mirror-image of semt.002's gaps):
- Cost basis IS carried, via a narrative field — `:70E::HOLD//COST/USD…` —
  our documented convention. Stuffing structured data into narrative text
  is exactly how real feeds smuggle non-standard fields; parsing it back
  out is authentic work, not a hack.
- The account is referenced by id alone (:97A::SAFE//…): no display name,
  custodian BIC, or base currency. Those come back None; enrichment
  belongs to reference data (Phase 2).
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from parvum_ingest.formats import FeedParseError
from parvum_ingest.model import (
    Account,
    FeedFormat,
    HoldingsStatement,
    IdentifierScheme,
    Money,
    Position,
    SecurityIdentifier,
)

_TAG_RE = re.compile(r"^:(\d{2}[A-Z]?):(.*)$")


def _dec(value: Decimal) -> str:
    # SWIFT decimal comma; integers still end with one ("220,").
    text = f"{value:f}".replace(".", ",")
    return text if "," in text else text + ","


def _parse_dec(raw: str, context: str) -> Decimal:
    try:
        return Decimal(raw.rstrip(",").replace(",", "."))
    except InvalidOperation as exc:
        raise FeedParseError(f"MT535: {raw!r} is not a SWIFT number in {context}") from exc


def _money(value: Money) -> str:
    return f"{value.currency}{_dec(value.amount)}"


def _parse_money(raw: str, context: str) -> Money:
    if len(raw) < 4 or not raw[:3].isalpha():
        raise FeedParseError(f"MT535: {raw!r} is not a currency+amount in {context}")
    return Money(amount=_parse_dec(raw[3:], context), currency=raw[:3].upper())


def _parse_date(raw: str, context: str) -> date:
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise FeedParseError(f"MT535: {raw!r} is not a YYYYMMDD date in {context}") from exc


def render_mt535(stmt: HoldingsStatement) -> str:
    lines: list[str] = []
    lines.append(":16R:GENL")
    lines.append(f":20C::SEME//{stmt.statement_id}")
    lines.append(":23G:NEWM")
    lines.append(f":98A::STAT//{stmt.as_of.strftime('%Y%m%d')}")
    lines.append(f":97A::SAFE//{stmt.account.account_id}")
    lines.append(":16S:GENL")

    for pos in stmt.positions:
        lines.append(":16R:FIN")
        scheme = "ISIN " if pos.security.scheme is IdentifierScheme.ISIN else "/XX/"
        # :35B: is two lines: identifier, then free-text description.
        lines.append(f":35B:{scheme}{pos.security.value}")
        lines.append(pos.security_name)
        lines.append(f":93B::AGGR//UNIT/{_dec(pos.quantity)}")
        if pos.price is not None:
            lines.append(f":90B::MRKT//ACTU/{_money(pos.price)}")
        if pos.price_as_of is not None:
            lines.append(f":98A::PRIC//{pos.price_as_of.strftime('%Y%m%d')}")
        if pos.market_value is not None:
            lines.append(f":19A::HOLD//{_money(pos.market_value)}")
        if pos.cost_basis is not None:
            lines.append(f":70E::HOLD//COST/{_money(pos.cost_basis)}")
        lines.append(":16S:FIN")

    return "\n".join(lines) + "\n"


# --- parsing --------------------------------------------------------------


def _fields(block_lines: list[str]) -> list[tuple[str, str]]:
    """Group raw lines into (tag, content) pairs; untagged lines are
    continuations of the previous field (e.g. :35B:'s description line)."""
    fields: list[tuple[str, str]] = []
    for line in block_lines:
        m = _TAG_RE.match(line)
        if m:
            fields.append((m.group(1), m.group(2)))
        elif fields:
            tag, content = fields[-1]
            fields[-1] = (tag, content + "\n" + line)
        else:
            raise FeedParseError(f"MT535: content before any tag: {line!r}")
    return fields


def _qualified(fields: list[tuple[str, str]], tag: str, prefix: str) -> str | None:
    for t, content in fields:
        if t == tag and content.startswith(prefix):
            return content[len(prefix) :]
    return None


def _require(value: str | None, what: str, context: str) -> str:
    if value is None:
        raise FeedParseError(f"MT535: missing {what} in {context}")
    return value


def _split_blocks(text: str) -> tuple[list[str], list[list[str]]]:
    """Return (GENL block lines, one line-list per FIN block)."""
    genl: list[str] = []
    fins: list[list[str]] = []
    current: list[str] | None = None
    current_name: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            continue
        if line.startswith(":16R:"):
            if current is not None:
                raise FeedParseError(f"MT535: nested block at {line!r}")
            current, current_name = [], line[5:]
        elif line.startswith(":16S:"):
            if current is None or line[5:] != current_name:
                raise FeedParseError(f"MT535: unbalanced block end {line!r}")
            if current_name == "GENL":
                genl = current
            elif current_name == "FIN":
                fins.append(current)
            else:
                raise FeedParseError(f"MT535: unknown block {current_name!r}")
            current, current_name = None, None
        elif current is not None:
            current.append(line)
        else:
            raise FeedParseError(f"MT535: content outside any block: {line!r}")
    if current is not None:
        raise FeedParseError(f"MT535: unclosed block {current_name!r}")
    if not genl:
        raise FeedParseError("MT535: missing GENL block")
    return genl, fins


def _parse_position(block: list[str], account_id: str, as_of: date, idx: int) -> Position:
    ctx = f"FIN[{idx}]"
    fields = _fields(block)

    ident_raw = _require(_qualified(fields, "35B", ""), ":35B: instrument", ctx)
    ident_lines = ident_raw.split("\n")
    first = ident_lines[0].strip()
    if not first.startswith("ISIN "):
        raise FeedParseError(f"MT535: only ISIN identifiers supported in {ctx}: {first!r}")
    security = SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=first[5:].strip())
    name = " ".join(line.strip() for line in ident_lines[1:]).strip()
    if not name:
        raise FeedParseError(f"MT535: :35B: missing description line in {ctx}")

    qty_raw = _require(_qualified(fields, "93B", ":AGGR//UNIT/"), ":93B: quantity", ctx)
    price_raw = _qualified(fields, "90B", ":MRKT//ACTU/")
    price_dt_raw = _qualified(fields, "98A", ":PRIC//")
    mv_raw = _qualified(fields, "19A", ":HOLD//")
    cost_raw = _qualified(fields, "70E", ":HOLD//COST/")

    return Position(
        account_id=account_id,
        security=security,
        security_name=name,
        quantity=_parse_dec(qty_raw, ctx),
        as_of=as_of,
        price=None if price_raw is None else _parse_money(price_raw, f"{ctx} price"),
        price_as_of=(
            None if price_dt_raw is None else _parse_date(price_dt_raw, f"{ctx} price date")
        ),
        market_value=None if mv_raw is None else _parse_money(mv_raw, f"{ctx} holding value"),
        cost_basis=None if cost_raw is None else _parse_money(cost_raw, f"{ctx} cost basis"),
    )


def parse_mt535(text: str) -> HoldingsStatement:
    genl_lines, fin_blocks = _split_blocks(text)
    genl = _fields(genl_lines)

    statement_id = _require(_qualified(genl, "20C", ":SEME//"), ":20C::SEME reference", "GENL")
    as_of = _parse_date(
        _require(_qualified(genl, "98A", ":STAT//"), ":98A::STAT date", "GENL"), "GENL"
    )
    account_id = _require(_qualified(genl, "97A", ":SAFE//"), ":97A::SAFE account", "GENL")

    # Identifier-only account reference: name/BIC/base currency are simply
    # not part of this message — reference data enriches later (Phase 2).
    account = Account(account_id=account_id)

    positions = tuple(
        _parse_position(block, account_id, as_of, i) for i, block in enumerate(fin_blocks)
    )

    return HoldingsStatement(
        statement_id=statement_id,
        account=account,
        as_of=as_of,
        source_format=FeedFormat.MT535,
        positions=positions,
    )
