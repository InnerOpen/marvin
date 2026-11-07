"""Wizards: a package's guided, multi-page setups, shipped as plain data.

A wizard is a list of steps that walks a person through making content, e.g. Screenplay Studio's "narrate a story": pick or create a
world, then a story, upload a script, cast the characters. Core knows nothing about stories: it only knows how to draw the five kinds of
step below and to carry a *context* from one step to the next (the slug of the world chosen, the story created). A package supplies the
definition; nothing in it is code, it names entry types and fields by slug and reads the context as ``${name}``.

Steps (each has ``id``, ``title`` and optional ``help`` and ``when``):

- ``option``: pick one of a few labelled values (``options: [{value, label}]``); sets the context key ``as``. Only there to branch on.
- ``choose``: pick an entry of ``entry_type`` (or create one), sets the context key ``as`` to its slug. ``scope`` ({field: "${key}"})
  narrows the list to entries whose field holds an earlier choice; ``create`` ({fields: [...], data: {field: "${key}" | literal}}) lets
  the person make a new one, arriving with ``data`` filled in; ``optional`` lets them skip it.
- ``form``: edit some ``fields`` of the entry in context key ``entry``.
- ``upload``: a file for the entry in context key ``entry``. ``mode: "asset"`` stores it as an asset in ``field``; ``mode: "text"``
  reads it as text into ``field`` (a script, a beat sheet). ``accept`` lists extensions.
- ``list``: the entries of ``entry_type`` whose ``parent_field`` holds context key ``parent``, with the ``columns`` editable in place and
  ``add`` to make another.
- ``review``: ``checks``, each ``{label, query, op, value}``: the query (entry-query spec: ``entry_type``, ``fields``, ``where``…) is
  counted and compared (``gt gte eq lte lt``) to a number; all passing means the wizard is done.

``when`` ({ctx, op: eq|neq|set|unset, value?}) hides a step unless it holds, which is how an upload step follows the option chosen.
Progress is never stored: the context rides in the page's address and each step shows done from what exists.
"""

from __future__ import annotations

import re
from typing import Any

MAX_STEPS = 40
STEP_KINDS = ("option", "choose", "form", "upload", "list", "review")
WHEN_OPS = ("eq", "neq", "set", "unset")
CHECK_OPS = ("gt", "gte", "eq", "lte", "lt")
UPLOAD_MODES = ("asset", "text")

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_STEP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_REF = re.compile(r"\$\{([^}]*)\}")
_EXT = re.compile(r"^\.[a-z0-9]{1,10}$")


def _refs(value: Any) -> list[str]:
    """Every ``${name}`` inside a string, list or dict value."""
    if isinstance(value, str):
        return _REF.findall(value)
    if isinstance(value, list):
        return [r for item in value for r in _refs(item)]
    if isinstance(value, dict):
        return [r for item in value.values() for r in _refs(item)]
    return []


def _keys(value: Any, what: str) -> str | None:
    if not isinstance(value, list) or not value or not all(isinstance(k, str) and _NAME.match(k) for k in value):
        return f"{what} must be a non-empty list of field keys"
    return None


def payload_problem(payload: dict, slug: str) -> str | None:
    """Why this wizard payload is not acceptable (None when it is). Pure: it looks at the definition alone, never at the workspace, so a
    package installs even before its entry types exist; a missing type is the wizard page's message to give."""
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return f"wizard {slug!r} needs a title"
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return f"wizard {slug!r} needs at least one step"
    if len(steps) > MAX_STEPS:
        return f"wizard {slug!r} has more than {MAX_STEPS} steps"
    known: set[str] = set()  # context keys set by an earlier step
    entries: set[str] = set()  # the ones a `choose` set: the only keys that name an entry
    seen: set[str] = set()
    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            return f"step {n} of wizard {slug!r} is not an object"
        sid = step.get("id")
        label = f"step {sid!r} of wizard {slug!r}"
        if not isinstance(sid, str) or not _STEP_ID.match(sid):
            return f"step {n} of wizard {slug!r} needs an id of lowercase letters, digits, - or _"
        if sid in seen:
            return f"{label} is used twice"
        seen.add(sid)
        if not isinstance(step.get("title"), str) or not step["title"].strip():
            return f"{label} needs a title"
        kind = step.get("kind")
        if kind not in STEP_KINDS:
            return f"{label} has kind {kind!r}; it must be one of {', '.join(STEP_KINDS)}"
        if (problem := _check_when(step.get("when"), known, label)) or (problem := _check_step(step, kind, known, entries, label)):
            return problem
        if kind in ("option", "choose"):
            known.add(step["as"])
        if kind == "choose":
            entries.add(step["as"])
    return None


def _check_when(when: Any, known: set[str], label: str) -> str | None:
    if when is None:
        return None
    if not isinstance(when, dict) or when.get("op") not in WHEN_OPS:
        return f"{label}: when must be {{ctx, op}} with op one of {', '.join(WHEN_OPS)}"
    if when.get("ctx") not in known:
        return f"{label}: when names {when.get('ctx')!r}, which no earlier step sets"
    if when["op"] in ("eq", "neq") and not isinstance(when.get("value"), str):
        return f"{label}: when {when['op']} needs a text value"
    return None


class _Step:
    """One step being checked: its label for messages, and the context keys the steps before it set."""

    def __init__(self, step: dict, known: set[str], entries: set[str], label: str):
        self.step, self.known, self.entries, self.label = step, known, entries, label

    def ctx(self, key: str) -> str | None:
        """`key` of this step names the entry an earlier `choose` step picked."""
        value = self.step.get(key)
        if value in self.entries:
            return None
        if value in self.known:
            return f"{self.label}: {key} names {value!r}, which is an option, not an entry an earlier step chose"
        return f"{self.label}: {key} names {value!r}, which no earlier step sets"

    def refs_known(self, value: Any, what: str) -> str | None:
        bad = next((r for r in _refs(value) if r not in self.known), None)
        return None if bad is None else f"{self.label}: {what} uses ${{{bad}}}, which no earlier step sets"

    def entry_type(self) -> str | None:
        found = self.step.get("entry_type")
        return None if isinstance(found, str) and _SLUG.match(found) else f"{self.label} needs an entry_type slug"

    def sets_context(self) -> str | None:
        return None if _NAME.match(str(self.step.get("as"))) else f"{self.label} needs `as`, the context key it sets"


def _check_option(s: _Step) -> str | None:
    options = s.step.get("options")
    valid = isinstance(options, list) and all(
        isinstance(o, dict) and isinstance(o.get("value"), str) and o["value"] and isinstance(o.get("label"), str) for o in options
    )
    if not valid or len(options) < 2:
        return f"{s.label} needs at least two options, each with a value and a label"
    if len({o["value"] for o in options}) != len(options):
        return f"{s.label} has two options with the same value"
    return s.sets_context()


def _check_create(s: _Step, create: Any) -> str | None:
    if not isinstance(create, dict):
        return f"{s.label}: create must be an object like {{fields: [...], data: {{...}}}}"
    if create.get("fields") is not None and (problem := _keys(create["fields"], f"{s.label}: create.fields")):
        return problem
    if create.get("data") is not None and not isinstance(create["data"], dict):
        return f"{s.label}: create.data must be an object"
    return s.refs_known(create.get("data"), "create.data")


def _check_choose(s: _Step) -> str | None:
    scope, create = s.step.get("scope"), s.step.get("create")
    if scope is not None and (not isinstance(scope, dict) or not all(_NAME.match(str(k)) for k in scope)):
        return f"{s.label}: scope must map field keys to values"
    return s.sets_context() or s.entry_type() or s.refs_known(scope, "scope") or (create is not None and _check_create(s, create)) or None


def _check_form(s: _Step) -> str | None:
    return s.ctx("entry") or _keys(s.step.get("fields"), f"{s.label}: fields")


def _check_upload(s: _Step) -> str | None:
    accept = s.step.get("accept", [])
    if s.step.get("mode") not in UPLOAD_MODES:
        return f"{s.label}: mode must be asset or text"
    if not _NAME.match(str(s.step.get("field"))):
        return f"{s.label} needs the field key the file goes into"
    if not isinstance(accept, list) or not all(isinstance(a, str) and _EXT.match(a) for a in accept):
        return f"{s.label}: accept is a list of extensions like .fountain"
    return s.ctx("entry")


def _check_list(s: _Step) -> str | None:
    if not _NAME.match(str(s.step.get("parent_field"))):
        return f"{s.label} needs parent_field, the field that holds the parent's slug"
    return (
        s.entry_type()
        or s.ctx("parent")
        or _keys(s.step.get("columns"), f"{s.label}: columns")
        or s.refs_known(s.step.get("create_data"), "create_data")
    )


def _check_one_check(s: _Step, check: Any) -> str | None:
    if not isinstance(check, dict) or not isinstance(check.get("label"), str) or not isinstance(check.get("query"), dict):
        return f"{s.label}: each check needs a label and a query"
    value = check.get("value")
    if check.get("op") not in CHECK_OPS or not isinstance(value, int) or isinstance(value, bool):
        return f"{s.label}: each check compares with one of {', '.join(CHECK_OPS)} to a whole number"
    if not isinstance(check["query"].get("entry_type"), str):
        return f"{s.label}: each check's query needs an entry_type"
    return s.refs_known(check["query"], "a check")


def _check_review(s: _Step) -> str | None:
    checks = s.step.get("checks")
    if not isinstance(checks, list) or not checks:
        return f"{s.label} needs checks"
    return next((problem for check in checks if (problem := _check_one_check(s, check))), None)


_CHECKS = {
    "option": _check_option,
    "choose": _check_choose,
    "form": _check_form,
    "upload": _check_upload,
    "list": _check_list,
    "review": _check_review,
}


def _check_step(step: dict, kind: str, known: set[str], entries: set[str], label: str) -> str | None:
    return _CHECKS[kind](_Step(step, known, entries, label))
