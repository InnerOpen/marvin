"""Template filters: ``${path|filter|filter:arg}`` turns a value before it is used.

A chain runs left to right on the value the path resolves to. A filter may take arguments after a colon, separated by
commas; an argument may be quoted ("…" or '…') to hold a comma, a colon or a bar: ``${entry.published_at|date:"%d %b
%Y"}``, ``${entry.title|truncate:60|default:"Untitled"}``, ``${steps.page.output.json.items|join:" · "}``.

The workflow save check (authoring.py) refuses an unknown filter or a wrong number of arguments; at run time an unknown
filter gives None, as it always has. Filters never raise on odd input: a date filter given text that isn't a date
passes the value through, a number filter given a word does too.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DATE_FORMAT = "%Y-%m-%d"
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str | list | dict) and not value)


def _truncate(value: Any, limit: str, end: str = "…") -> str:
    text, size = _text(value), max(int(limit), 1)
    if len(text) <= size:
        return text
    cut = text[: max(size - len(end), 0)]
    words = cut.rsplit(" ", 1)[0] if " " in cut else cut  # end on a whole word when there is one
    return (words if len(words) >= size // 2 else cut).rstrip(" ,.;:") + end


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if re.fullmatch(r"\d{9,11}(\.\d+)?", text):  # epoch seconds as text
            return datetime.fromtimestamp(float(text), tz=UTC)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _date(value: Any, fmt: str = DEFAULT_DATE_FORMAT, timezone: str | None = None) -> Any:
    moment = _as_datetime(value)
    if moment is None:
        return value
    if timezone:
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return value
        moment = (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(zone)
    return moment.isoformat() if fmt == "iso" else moment.strftime(fmt)


def _round(value: Any, digits: str = "0") -> Any:
    try:
        number = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return value
    if number is None:
        return value
    places = int(digits)
    return int(round(number)) if places == 0 else round(number, places)


def _strip_html(value: Any) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", _text(value)))).strip()


def _markdown(value: Any) -> str:
    from marvin.services.email.email_service import EmailService

    return EmailService._markdown_to_html(_text(value))


def _slug(value: Any) -> str:
    from slugify import slugify

    return slugify(_text(value))


def _split(value: Any, sep: str = ",") -> list:
    if isinstance(value, list):
        return value
    return [part.strip() for part in _text(value).split(sep)] if not _empty(value) else []


def _join(value: Any, sep: str = ", ") -> str:
    if isinstance(value, list):
        return sep.join(_text(v) for v in value if v is not None)
    return _text(value)


def _pick(value: Any, index: int) -> Any:
    if isinstance(value, list | str) and value:
        return value[index]
    return None


def _length(value: Any) -> int:
    return len(value) if isinstance(value, list | dict | str) else 0


# name → (function, how many arguments it takes beyond the value: (fewest, most), what it does for the guide)
FILTERS: dict[str, tuple[Callable[..., Any], tuple[int, int], str]] = {
    "default": (lambda v, fallback="": fallback if _empty(v) else v, (1, 1), "the argument when the value is missing or empty"),
    "upper": (lambda v: _text(v).upper(), (0, 0), "UPPER CASE"),
    "lower": (lambda v: _text(v).lower(), (0, 0), "lower case"),
    "capitalize": (lambda v: (lambda t: t[:1].upper() + t[1:])(_text(v)), (0, 0), "First letter capital"),
    "title": (lambda v: _text(v).title(), (0, 0), "Each Word Capital"),
    "trim": (lambda v: _text(v).strip(), (0, 0), "spaces off both ends"),
    "truncate": (_truncate, (1, 2), "at most N characters, ending on a whole word with … (or the second argument)"),
    "replace": (lambda v, old, new="": _text(v).replace(old, new), (1, 2), "every OLD replaced by NEW"),
    "slug": (_slug, (0, 0), "a-url-slug"),
    "strip_html": (_strip_html, (0, 0), "plain text from HTML (tags dropped, entities decoded)"),
    "escape": (lambda v: html.escape(_text(v)), (0, 0), "safe to put inside HTML"),
    "markdown": (_markdown, (0, 0), "markdown made into HTML (as emails do)"),
    "url": (lambda v: quote(_text(v), safe=""), (0, 0), "URL-encoded: for a link's text or a query string"),
    "join": (_join, (0, 1), "a list as text, separated by the argument (default ', ')"),
    "split": (_split, (0, 1), "text into a list at the argument (default ',')"),
    "first": (lambda v: _pick(v, 0), (0, 0), "a list's first item"),
    "last": (lambda v: _pick(v, -1), (0, 0), "a list's last item"),
    "length": (_length, (0, 0), "how many items (or characters)"),
    "date": (_date, (0, 2), 'a date formatted (strftime, default %Y-%m-%d; "iso"), optionally in a timezone'),
    "round": (_round, (0, 1), "a number rounded to N decimals (default 0)"),
    "json": (lambda v: json.dumps(v, ensure_ascii=False, default=str), (0, 0), "the value as JSON text"),
    "base64": (lambda v: base64.b64encode(_text(v).encode()).decode(), (0, 0), "base64-encoded"),
    "sha256": (lambda v: hashlib.sha256(_text(v).encode()).hexdigest(), (0, 0), "the SHA-256 hash (hex)"),
    "md5": (lambda v: hashlib.md5(_text(v).encode(), usedforsecurity=False).hexdigest(), (0, 0), "the MD5 hash (hex), e.g. a Gravatar"),
}
_NUMERIC_FIRST_ARG = {"truncate", "round"}


def split_expression(expr: str) -> list[str]:
    """``path|f1|f2:"a|b"`` → ``["path", "f1", 'f2:"a|b"']``: bars inside quotes don't split."""
    parts, cur, quote_char = [], [], ""
    for ch in expr:
        if quote_char:
            cur.append(ch)
            if ch == quote_char:
                quote_char = ""
        elif ch in "\"'":
            quote_char = ch
            cur.append(ch)
        elif ch == "|":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def parse_filter(text: str) -> tuple[str, list[str]]:
    """``truncate:60,"…"`` → ``("truncate", ["60", "…"])``. Commas inside quotes stay in the argument."""
    name, colon, rest = text.partition(":")
    if not colon:
        return name.strip(), []
    args, cur, quote_char, quoted = [], [], "", False
    for ch in rest:
        if quote_char:
            if ch == quote_char:
                quote_char = ""
            else:
                cur.append(ch)
        elif ch in "\"'":
            quote_char, quoted = ch, True
        elif ch == ",":
            args.append("".join(cur) if quoted else "".join(cur).strip())
            cur, quoted = [], False
        else:
            cur.append(ch)
    args.append("".join(cur) if quoted else "".join(cur).strip())
    return name.strip(), args


def apply_chain(value: Any, filters: list[str]) -> Any:
    """The value through each filter in turn; an unknown filter (or one given bad arguments) gives None."""
    for text in filters:
        name, args = parse_filter(text)
        entry = FILTERS.get(name)
        if entry is None:
            return None
        try:
            value = entry[0](value, *args)
        except (TypeError, ValueError, OverflowError):
            return None
    return value


def filter_problem(text: str) -> str | None:
    """Why a filter written in a template won't work, or None — the save check's wording."""
    name, args = parse_filter(text)
    entry = FILTERS.get(name)
    if entry is None:
        return f"there is no “{name}” filter. Filters: {', '.join(FILTERS)}."
    fewest, most = entry[1]
    if not fewest <= len(args) <= most:
        wants = f"{fewest}" if fewest == most else f"{fewest} to {most}"
        return f"“{name}” takes {wants} argument{'' if most == 1 and fewest == most else 's'}, not {len(args)}."
    if name in _NUMERIC_FIRST_ARG and args and not re.fullmatch(r"-?\d+", args[0]):
        return f"“{name}” needs a whole number first, not “{args[0]}”."
    if name == "date" and len(args) == 2:
        try:
            ZoneInfo(args[1])
        except (ZoneInfoNotFoundError, ValueError):
            return f"“{args[1]}” isn't a timezone (e.g. Europe/Madrid, America/New_York)."
    return None


def guide() -> dict[str, str]:
    """Each filter and what it does, for the workflow authoring guide."""
    return {name: about for name, (_, _, about) in FILTERS.items()}
