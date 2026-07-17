"""Canonical internal model — the hub every wire format maps to and from.

Design rule (D-009): models validate *shape* (types, formats, required
fields), not *sense* (business plausibility). A statement whose numbers lie
must be representable here, because detecting those lies downstream is the
platform's job. That is why e.g. cost_basis is optional and no cross-field
rules like settlement >= trade date are enforced — those are Phase 3
data-quality expectations, not parse-time rejections.

All monetary and quantity values are Decimal: float would silently corrupt
amounts (0.1 + 0.2 != 0.3) and financial data cannot tolerate that.
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

# --- vocabulary ----------------------------------------------------------


class IdentifierScheme(StrEnum):
    ISIN = "ISIN"
    CUSIP = "CUSIP"
    SEDOL = "SEDOL"
    TICKER = "TICKER"
    FIGI = "FIGI"


class FeedFormat(StrEnum):
    SEMT_002 = "semt.002"
    MT535 = "MT535"
    CAMT_053 = "camt.053"


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class BalanceType(StrEnum):
    OPENING = "OPENING"
    CLOSING = "CLOSING"


# Shape-only checks per scheme: length and character class, nothing more.
# Checksum validity is deliberately NOT enforced at construction (see
# SecurityIdentifier.has_valid_checksum).
_SCHEME_PATTERNS: dict[IdentifierScheme, re.Pattern[str]] = {
    IdentifierScheme.ISIN: re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"),
    IdentifierScheme.CUSIP: re.compile(r"^[A-Z0-9]{9}$"),
    IdentifierScheme.SEDOL: re.compile(r"^[A-Z0-9]{7}$"),
    IdentifierScheme.TICKER: re.compile(r"^[A-Z0-9.\-]{1,12}$"),
    IdentifierScheme.FIGI: re.compile(r"^[A-Z0-9]{12}$"),
}


class _Frozen(BaseModel):
    """Base for all model types: immutable, and unknown fields are errors.

    Immutability means a parsed statement cannot be quietly edited in
    place — corrections must produce new objects, which keeps audit trails
    honest. Forbidding unknown fields catches parser bugs (a misspelled
    field name fails loudly instead of vanishing).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- value objects -------------------------------------------------------


class Money(_Frozen):
    amount: Decimal
    currency: str

    @field_validator("currency")
    @classmethod
    def _currency_iso4217(cls, v: str) -> str:
        # Shape check only: three uppercase ASCII letters. Whether the code
        # is an *assigned* ISO 4217 currency is a reference-data question.
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError(f"currency must be a 3-letter uppercase code, got {v!r}")
        return v


class SecurityIdentifier(_Frozen):
    scheme: IdentifierScheme
    value: str

    @field_validator("value")
    @classmethod
    def _strip_upper(cls, v: str) -> str:
        return v.strip().upper()

    def model_post_init(self, __context: object) -> None:
        pattern = _SCHEME_PATTERNS[self.scheme]
        if not pattern.fullmatch(self.value):
            raise ValueError(f"{self.value!r} is not shaped like a {self.scheme} identifier")

    def has_valid_checksum(self) -> bool:
        """ISIN check-digit verification (ISO 6166: base-36 expansion + Luhn).

        A method, not a constructor rule: feeds really do deliver mistyped
        ISINs, and the pipeline must carry them to the exception queue
        rather than crash on arrival. Non-ISIN schemes return True (their
        checksum rules can be added when a format needs them).
        """
        if self.scheme is not IdentifierScheme.ISIN:
            return True
        # Letters expand to two digits (A=10 ... Z=35), digits pass through.
        digits = "".join(str(int(ch, 36)) for ch in self.value)
        total = 0
        for i, ch in enumerate(reversed(digits)):
            d = int(ch)
            if i % 2 == 1:  # double every second digit, right to left
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0


def is_cins(cusip: str) -> bool:
    """True if this is a CINS — a CUSIP-shaped code issued to a *foreign* issuer.

    The tell is a leading letter (H = Switzerland, and so on) where a
    US/Canadian CUSIP starts with a digit. It matters because a CINS states
    plainly that the issuer's country is not the US, which is exactly what
    `isin_from_cusip` needs and cannot otherwise know.
    """
    return bool(cusip) and not cusip[0].isdigit()


def _isin_check_digit(body: str) -> str:
    """The ISO 6166 check digit for an 11-character ISIN body.

    The inverse of `SecurityIdentifier.has_valid_checksum`: expand letters to
    base-36 digit pairs, then pick the digit that makes the Luhn sum a
    multiple of ten. Doubling starts at the body's rightmost digit here,
    rather than the second-rightmost, because appending the check digit
    shifts every position along by one.
    """
    digits = "".join(str(int(ch, 36)) for ch in body)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str(-total % 10)


def isin_from_cusip(cusip: str, country: str = "US") -> SecurityIdentifier:
    """Construct a North American security's ISIN from its CUSIP.

    This applies a real ISO 6166 rule rather than approximating one: a North
    American ISIN *is* the country code + the 9-character CUSIP + a check
    digit. That is why deriving it is legitimate where inventing an
    identifier would not be (D-004) — this is the standard's own arithmetic,
    not a guessed mapping.

    The honest limit is `country`, and it is the caller's problem on purpose:
    a CUSIP does not tell you where its issuer is domiciled. Numeric CUSIPs
    are issued to Canadian companies too, so a Canadian name derived with the
    default "US" yields a plausible-looking ISIN that does not exist
    anywhere. Knowing the domicile is the securities master's job (Phase 2);
    until then callers must supply what they actually know. CINS codes carry
    their own answer and are refused outright.
    """
    cusip = cusip.strip().upper()
    if is_cins(cusip):
        raise ValueError(
            f"{cusip!r} is a CINS (foreign issuer): the country prefix of its ISIN cannot "
            "be constructed from the code — it has to be looked up"
        )
    body = f"{country.strip().upper()}{cusip}"
    return SecurityIdentifier(scheme=IdentifierScheme.ISIN, value=body + _isin_check_digit(body))


# --- entities ------------------------------------------------------------


class Account(_Frozen):
    account_id: str
    # Optional because wire formats disagree: semt.002 carries these, MT535
    # references the account by id alone — enrichment is reference data's job.
    name: str | None = None
    custodian_bic: str | None = None  # BIC = the SWIFT identifier of the custodian bank
    base_currency: str | None = None


class Position(_Frozen):
    account_id: str
    security: SecurityIdentifier
    security_name: str
    quantity: Decimal
    as_of: date
    # Optional by design: their absence is a classic real-world feed defect
    # that Phase 3 data-quality rules must detect, so the model must admit it.
    price: Money | None = None
    price_as_of: date | None = None
    market_value: Money | None = None
    cost_basis: Money | None = None


class Transaction(_Frozen):
    transaction_id: str
    account_id: str
    type: TransactionType
    trade_date: date
    settlement_date: date
    amount: Money
    # None for pure cash movements (fees, interest) with no security leg.
    security: SecurityIdentifier | None = None
    quantity: Decimal | None = None
    description: str = ""


class CashBalance(_Frozen):
    account_id: str
    balance_type: BalanceType
    balance: Money
    as_of: date


# --- statements (what a feed file parses into) ---------------------------


class HoldingsStatement(_Frozen):
    """One custody holdings statement: semt.002 and MT535 both parse to this."""

    statement_id: str
    account: Account
    as_of: date
    source_format: FeedFormat
    positions: tuple[Position, ...]


class CashStatement(_Frozen):
    """One cash statement (camt.053): balances plus the entries between them."""

    statement_id: str
    account: Account
    as_of: date
    source_format: FeedFormat
    balances: tuple[CashBalance, ...]
    entries: tuple[Transaction, ...]
