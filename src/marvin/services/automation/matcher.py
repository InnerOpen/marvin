"""Condition matching + value interpolation for Flavor B automations.

Pure functions over a plain `context` dict (no DB, no I/O) so they are cheap and fully unit-testable.
The context the engine passes looks like::

    {
      "event":    {"event_type": "entry_published", "entry_id": "...", "entry_type": "recipe", ...},
      "previous": {"summary": "...", ...},   # output of the last action, if any
    }

Conditions reference fields by dotted path (e.g. ``"event.entry_type"``); action inputs may embed
``"$event.entry_id"`` / ``"$previous.summary"`` templates, resolved by :func:`interpolate`.
"""

import re
from typing import Any

# Supported condition operators. `changed*` key on an update's diff (event.changed_fields/before/
# after); the field's last segment names the field (so `entry.status` → the "status" diff key).
_OPS = ("eq", "neq", "contains", "in", "starts_with", "exists", "changed", "changed_from", "changed_to")

_BRACED = re.compile(r"\$\{([^}]+)\}")

_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})


def as_bool(text: str) -> bool | None:
    """`true`/`yes`/`on`/`1` → True, `false`/`no`/`off`/`0` → False (any case); else None."""
    word = text.strip().lower()
    return True if word in _TRUE_WORDS else False if word in _FALSE_WORDS else None


def as_number(text: str) -> int | float | None:
    """`45` → 45, `12.5` → 12.5; anything else → None."""
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def _like(actual: Any, expected: Any) -> Any:
    """Read a condition's typed-in text as the kind of value it is compared with: the editor sends
    every value as text, so `sellOnline != "true"` would otherwise never see the checkbox's True."""
    if not isinstance(expected, str) or isinstance(actual, str) or actual is None:
        return expected
    if isinstance(actual, bool):
        converted = as_bool(expected)
    elif isinstance(actual, int | float):
        converted = as_number(expected)
    else:
        converted = None
    return expected if converted is None else converted


def resolve_path(path: str, context: dict) -> Any:
    """Resolve a dotted path (``"event.entry_type"``) against the context; None if any hop misses.

    A numeric hop indexes a list (``"event.payload.data.object.inventory_counts.0.quantity"``) — senders
    such as Square put the interesting record inside an array.
    """
    cur: Any = context
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def interpolate(value: Any, context: dict) -> Any:
    """Resolve ``$event.*`` / ``$previous.*`` / ``$steps.<id>.output.*`` templates in a value
    (recursing dicts/lists). Three forms:

    * a whole-string bare template (``"$event.entry_id"``) → the raw referenced value (type preserved);
    * a whole-string braced template (``"${event.count}"``) → also the raw value (type preserved);
    * **embedded** braces (``"Summary: ${previous.summary}"``) → each ``${path}`` replaced by its
      stringified value, result is a string (None → empty string).

    Non-template values pass through unchanged; unknown references resolve to None (or "" when embedded).
    """
    if isinstance(value, str):
        if "${" in value:
            whole = _BRACED.fullmatch(value.strip())
            if whole:  # exactly "${path}" — preserve the referenced value's type
                return resolve_path(whole.group(1), context)
            return _BRACED.sub(lambda m: _stringify(resolve_path(m.group(1), context)), value)
        if value.startswith("$"):  # legacy bare whole-string "$path"
            return resolve_path(value[1:], context)
        return value
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    return value


def _stringify(v: Any) -> str:
    return "" if v is None else str(v)


def _match_one(cond: dict, context: dict) -> bool:
    field = cond.get("field")
    op = cond.get("op", "eq")
    expected = interpolate(cond.get("value"), context)

    # Change-aware operators key on an update's diff, not the live value: the field's last segment
    # names the diff key (so "entry.status" and "status" both mean the "status" field).
    if op in ("changed", "changed_from", "changed_to"):
        key = str(field or "").rsplit(".", 1)[-1]
        if op == "changed":
            return key in (resolve_path("event.changed_fields", context) or [])
        side = "after" if op == "changed_to" else "before"
        return (resolve_path(f"event.{side}", context) or {}).get(key) == expected

    actual = resolve_path(field, context) if field else None

    if op == "exists":
        # `value: false` inverts to "must not exist".
        want = expected if isinstance(expected, bool) else True
        return (actual is not None) == want
    if op == "eq":
        return actual == _like(actual, expected)
    if op == "neq":
        return actual != _like(actual, expected)
    if op == "contains":
        if actual is None:
            return False
        try:
            return expected in actual  # substring or membership
        except TypeError:
            return False
    if op == "in":
        # actual is one of a list; a comma-separated string is accepted for the guided UI.
        options = [v.strip() for v in expected.split(",")] if isinstance(expected, str) else expected
        try:
            return actual in options
        except TypeError:
            return False
    if op == "starts_with":
        return isinstance(actual, str) and actual.startswith(str(expected))
    # Unknown operator → fail closed (never silently "match everything").
    return False


def _eval(cond: dict, context: dict) -> bool:
    """Evaluate a condition node — a leaf ``{field, op, value}`` or a boolean group:
    ``{all: [...]}`` (AND), ``{any: [...]}`` (OR), ``{not: <cond>}``. Groups nest arbitrarily."""
    if not isinstance(cond, dict):
        return False
    if "all" in cond:
        return all(_eval(c, context) for c in (cond["all"] or []))
    if "any" in cond:
        return any(_eval(c, context) for c in (cond["any"] or []))
    if "not" in cond:
        return not _eval(cond["not"], context)
    return _match_one(cond, context)


def matches(conditions, context: dict) -> bool:
    """True if the conditions hold. A top-level LIST is an implicit AND (the common case); a single
    group dict (``{any: […]}`` etc.) is evaluated directly. No conditions → always matches."""
    if not conditions:
        return True
    if isinstance(conditions, list):
        return all(_eval(c, context) for c in conditions if isinstance(c, dict))
    return _eval(conditions, context)
