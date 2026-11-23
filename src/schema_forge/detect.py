"""Pure value detectors: candidate type matchers, PII checks, regex induction.

Every function in this module is side-effect free and deterministic. The
inference engine calls them on a bounded sample and again on the full file to
measure how many rows actually conform to the chosen type.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

INT_RE = re.compile(r"[+-]?\d+")
FLOAT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+(?:\.\d*)?[eE][+-]?\d+)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
URL_RE = re.compile(r"(?:https?|ftp)://\S+")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
CURRENCY_CODE = r"(?:USD|EUR|GBP|JPY|CNY|RMB|INR|AUD|CAD|CHF|KRW|BRL|SGD|HKD|SEK|NOK)"
CURRENCY_RE = re.compile(
    r"[-+]?[$€£¥₹₩]\s?[0-9][0-9,]*(?:\.[0-9]{1,2})?"
    r"|[-+]?[0-9][0-9,]*(?:\.[0-9]{1,2})?\s?"
    + CURRENCY_CODE
    + r"|"
    + CURRENCY_CODE
    + r"\s?[-+]?[0-9][0-9,]*(?:\.[0-9]{1,2})?"
)
DATE_SHAPES = (
    ("%Y-%m-%d", re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")),
    ("%Y/%m/%d", re.compile(r"[0-9]{4}/[0-9]{2}/[0-9]{2}")),
    ("%d/%m/%Y", re.compile(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}")),
    ("%m/%d/%Y", re.compile(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}")),
    ("%d-%m-%Y", re.compile(r"[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}")),
    ("%d.%m.%Y", re.compile(r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}")),
    ("%b %d, %Y", re.compile(r"[A-Za-z]{3} [0-9]{1,2}, [0-9]{4}")),
    ("%d %b %Y", re.compile(r"[0-9]{1,2} [A-Za-z]{3} [0-9]{4}")),
    ("%B %d, %Y", re.compile(r"[A-Za-z]{3,9} [0-9]{1,2}, [0-9]{4}")),
)
DATE_SHAPE_RE = re.compile(
    r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}/[0-9]{2}/[0-9]{2}"
    r"|[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{4}"
    r"|[A-Za-z]{3,9} [0-9]{1,2}, [0-9]{4}|[0-9]{1,2} [A-Za-z]{3,9} [0-9]{4})"
)
CARD_GROUPED_RE = re.compile(r"[0-9]{4}(?:[ -]?[0-9]{4}){3}")
IBAN_RE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}")
PHONE_RE = re.compile(r"\+?[0-9][0-9 ().-]{5,18}[0-9]")
SSN_RE = re.compile(r"(?!000|666|9[0-9]{2})[0-9]{3}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}")
DATE_PREFIX_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

BOOL_FAMILIES = (
    frozenset({"true", "false"}),
    frozenset({"yes", "no"}),
    frozenset({"y", "n"}),
    frozenset({"t", "f"}),
)

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
)

PII_ORDER = ("card", "iban", "ssn", "email", "phone")


def is_int(value: str) -> bool:
    """Return True when *value* is an optionally signed integer literal."""
    return INT_RE.fullmatch(value) is not None


def is_float(value: str) -> bool:
    """Return True when *value* is a decimal or scientific-notation float."""
    return FLOAT_RE.fullmatch(value) is not None


def is_bool(value: str) -> bool:
    """Return True when *value* belongs to one of the boolean token families."""
    low = value.lower()
    return any(low in family for family in BOOL_FAMILIES)


def parse_bool(value: str) -> bool | None:
    """Parse a boolean token, returning None when it is not a boolean."""
    low = value.lower()
    if low in {"true", "t", "yes", "y"}:
        return True
    if low in {"false", "f", "no", "n"}:
        return False
    return None


def date_formats_of(value: str) -> list[str]:
    """Return every date format that parses *value*, in deterministic order.

    A cheap shape regex gates each strptime call, which keeps the hot path fast:
    a column of ISO dates costs one regex match, not nine strptime calls.
    """
    if DATE_SHAPE_RE.fullmatch(value) is None:
        return []
    hits: list[str] = []
    for fmt, shape in DATE_SHAPES:
        if shape.fullmatch(value) is None:
            continue
        try:
            datetime.strptime(value, fmt)
        except ValueError:
            continue
        hits.append(fmt)
    return hits


def is_date(value: str) -> bool:
    """Return True when any supported date format parses *value*."""
    return bool(date_formats_of(value))


def parse_date(value: str, formats: Sequence[str]) -> datetime | None:
    """Parse *value* using the first matching format from *formats*."""
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def is_datetime(value: str) -> bool:
    """Return True for ISO-8601 style date-time values with a time component."""
    if ":" not in value or not DATE_PREFIX_RE.match(value):
        return False
    text = value[:-1] + "+00:00" if value[-1] in "Zz" else value
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return "T" in value or " " in value


def parse_datetime(value: str) -> datetime | None:
    """Parse an ISO-8601 date-time, returning None when it is malformed."""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_email(value: str) -> bool:
    """Return True for syntactically plausible email addresses."""
    return EMAIL_RE.fullmatch(value) is not None


def is_url(value: str) -> bool:
    """Return True for absolute http(s)/ftp URLs."""
    return URL_RE.fullmatch(value) is not None


def is_uuid(value: str) -> bool:
    """Return True for canonical 8-4-4-4-12 UUID strings."""
    return UUID_RE.fullmatch(value) is not None


def is_currency(value: str) -> bool:
    """Return True when *value* carries a currency symbol or ISO code."""
    return CURRENCY_RE.fullmatch(value) is not None


def parse_number(value: str) -> float | None:
    """Parse an int/float/currency value into a float for statistics."""
    if is_int(value):
        return float(int(value))
    if is_float(value):
        try:
            return float(value)
        except ValueError:
            return None
    return parse_currency(value)


def parse_currency(value: str) -> float | None:
    """Parse a currency amount such as $1,299.00 or 42.50 EUR."""
    if not is_currency(value):
        return None
    text = value.strip()
    negative = text.startswith("-") or text.startswith("(")
    text = text.lstrip("+-(").replace(")", "")
    text = re.sub(r"^\s*" + CURRENCY_CODE + r"\s*", "", text)
    text = re.sub(r"\s*" + CURRENCY_CODE + r"\s*$", "", text)
    text = text.replace(",", "").strip()
    text = re.sub(r"^[$€£¥₹₩]\s?", "", text)
    try:
        amount = float(text)
    except ValueError:
        return None
    return -amount if negative else amount


def structural_matches(value: str) -> list[str]:
    """Return the candidate kinds whose matcher accepts *value*.

    Cheap character gates run before each regex so that a 100k-row file costs a
    handful of substring checks per cell instead of nine full regexes.
    """
    hits: list[str] = []
    first = value[0]
    numeric_start = first.isdigit() or first in "+-"
    currency_start = first in "$€£¥₹₩" or value[:3] in ("USD", "EUR", "GBP", "JPY", "CNY", "RMB")
    if "@" in value and is_email(value):
        hits.append("email")
    if "://" in value and is_url(value):
        hits.append("url")
    if len(value) == 36 and value[8] == "-" and is_uuid(value):
        hits.append("uuid")
    if numeric_start:
        if is_int(value):
            hits.append("int")
        if is_float(value):
            hits.append("float")
        if ":" in value and is_datetime(value):
            hits.append("datetime")
        if is_date(value):
            hits.append("date")
        if is_currency(value):
            hits.append("currency")
    elif currency_start and is_currency(value):
        hits.append("currency")
    if not numeric_start and value[:1].isalpha():
        if is_bool(value):
            hits.append("bool")
        if is_date(value):
            hits.append("date")
    if not numeric_start and not value[:1].isalpha() and is_bool(value):
        hits.append("bool")
    return hits


def luhn_ok(digits: str) -> bool:
    """Return True when *digits* satisfies the Luhn checksum."""
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        if not char.isdigit():
            return False
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    """Validate an IBAN with the ISO 13616 mod-97 checksum."""
    compact = value.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34 or not IBAN_RE.fullmatch(compact):
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = []
    for char in rearranged:
        if char.isdigit():
            numeric.append(char)
        else:
            numeric.append(str(ord(char) - 55))
    try:
        return int("".join(numeric)) % 97 == 1
    except ValueError:
        return False


def is_card_number(value: str) -> bool:
    """Return True for 13-19 digit card numbers that pass the Luhn check."""
    if CARD_GROUPED_RE.fullmatch(value) is None and not value.isdigit():
        return False
    digits = re.sub(r"[ -]", "", value)
    return 13 <= len(digits) <= 19 and luhn_ok(digits)


def is_iban(value: str) -> bool:
    """Return True for IBAN strings with a valid mod-97 checksum."""
    return iban_ok(value)


def is_phone(value: str) -> bool:
    """Return True for phone-like strings with 7 to 15 digits.

    Date- and datetime-shaped values are rejected first: 2026-06-04 is a date,
    not a phone number. The check is pure regex so it stays cheap.
    """
    if PHONE_RE.fullmatch(value) is None:
        return False
    if DATE_SHAPE_RE.fullmatch(value) is not None or DATE_PREFIX_RE.match(value):
        return False
    digits = 0
    for char in value:
        if char.isdigit():
            digits += 1
    return 7 <= digits <= 15


def is_ssn(value: str) -> bool:
    """Return True for US SSN-shaped strings with a valid area/group pattern."""
    return SSN_RE.fullmatch(value) is not None


PII_MATCHERS = {
    "card": is_card_number,
    "iban": is_iban,
    "ssn": is_ssn,
    "email": is_email,
    "phone": is_phone,
}

MASK_ADVICE = {
    "card": "never log or export card numbers; keep the last 4 digits",
    "iban": "keep the country code and last 4 characters only",
    "ssn": "keep the last 4 digits only",
    "email": "mask the local part before export",
    "phone": "keep the last 4 digits only",
}


def mask_value(kind: str, value: str) -> str:
    """Return a deterministic masked rendering of a sensitive *value*."""
    if kind == "email" and "@" in value:
        local, _, domain = value.partition("@")
        head = local[0] if local else "*"
        return f"{head}***@{domain}"
    if kind == "iban":
        compact = value.replace(" ", "")
        if len(compact) <= 6:
            return "*" * len(compact)
        return compact[:2] + "*" * (len(compact) - 4) + compact[-4:]
    keep = 4
    digits_seen = sum(1 for char in value if char.isdigit())
    out: list[str] = []
    remaining = digits_seen
    for char in value:
        if char.isdigit():
            remaining -= 1
            out.append(char if remaining < keep else "*")
        else:
            out.append(char)
    return "".join(out)


_TOKEN_RE = re.compile(r"[0-9]+|[a-z]+|[A-Z]+|[^0-9A-Za-z]+")
_MAX_PATTERN_LEN = 120


def _token_run_pattern(kind: str, lengths: Sequence[int]) -> str:
    low, high = min(lengths), max(lengths)
    if kind == "digits":
        return r"\d{" + str(low) + ("" if low == high else "," + str(high)) + "}"
    if kind == "lower":
        return r"[a-z]{" + str(low) + ("" if low == high else "," + str(high)) + "}"
    if kind == "upper":
        return r"[A-Z]{" + str(low) + ("" if low == high else "," + str(high)) + "}"
    return r"\s"


def induce_pattern(values: Sequence[str]) -> str | None:
    """Induce a conservative anchored regex that matches all *values*.

    The induction only succeeds when every value decomposes into the same
    sequence of token classes (digits, lower-case words, upper-case words,
    literal punctuation, whitespace). Anything else returns None so that a
    confidently wrong pattern is never written into a contract.
    """
    unique = list(dict.fromkeys(values))
    if len(unique) < 3 or len(set(unique)) < 2:
        return None
    tokenised: list[list[str]] = []
    for value in unique:
        tokens = _TOKEN_RE.findall(value)
        if not tokens:
            return None
        tokenised.append(tokens)
    first = tokenised[0]
    if any(len(tokens) != len(first) for tokens in tokenised):
        return None
    if len(first) > 12:
        return None
    parts: list[str] = ["^"]
    literal_budget = 24
    for position in range(len(first)):
        column = [tokens[position] for tokens in tokenised]
        if all(token.isdigit() for token in column):
            parts.append(_token_run_pattern("digits", [len(token) for token in column]))
        elif all(token.isalpha() and token.islower() for token in column):
            parts.append(_token_run_pattern("lower", [len(token) for token in column]))
        elif all(token.isalpha() and token.isupper() for token in column):
            parts.append(_token_run_pattern("upper", [len(token) for token in column]))
        elif all(token.isspace() for token in column):
            parts.append(_token_run_pattern("space", [1]))
        elif len(set(column)) == 1:
            literal = column[0]
            literal_budget -= len(literal)
            if literal_budget < 0:
                return None
            parts.append(re.escape(literal))
        else:
            return None
    parts.append("$")
    pattern = "".join(parts)
    if len(pattern) > _MAX_PATTERN_LEN:
        return None
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    if any(compiled.fullmatch(value) is None for value in values):
        return None
    if pattern in {"^.*$", "^.+$"}:
        return None
    return pattern


def pattern_is_valid(pattern: str, values: Sequence[str]) -> bool:
    """Return True when *pattern* compiles and matches every value."""
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    return all(compiled.fullmatch(value) is not None for value in values)


def luhn_check_digit(payload: str) -> str:
    """Return the Luhn check digit that completes *payload*."""
    total = 0
    for index, char in enumerate(reversed(payload)):
        digit = int(char)
        if index % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)
