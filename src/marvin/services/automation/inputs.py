"""Run inputs: what a manual workflow asks for when someone runs it (the Run button's form, the API's body, the agent's
run_workflow `inputs`), read as ``${input.<name>}``.

A manual trigger declares them (``trigger.inputs``: name, label, type text | number | choice | entry, options, required,
default). ``resolve`` checks what a caller passed against those declarations — an unknown name, a missing required
one, a choice outside its options or a number that isn't one is refused with a message saying so — and returns the
values plus the entry an ``entry`` input names, which the run then acts on (``${entry.*}``, entry steps) as if it had
been triggered by it. A dry run fills a missing value with a stand-in instead of refusing.
"""

from __future__ import annotations

from typing import Any

MAX_TEXT_CHARS = 2000


class RunInputError(ValueError):
    """What the caller passed doesn't fit the workflow's inputs; the message says what to fix."""


def declared(automation) -> list[dict]:
    """The workflow's run inputs (a manual trigger's), in order; [] for any other workflow."""
    trigger = getattr(automation, "trigger", None) or {}
    if trigger.get("type") != "manual":
        return []
    return [i for i in trigger.get("inputs") or [] if isinstance(i, dict) and i.get("name")]


def resolve(session, group_id, automation, given: dict | None, *, dry_run: bool = False) -> tuple[dict, str | None]:
    """(values by name, the id of the entry an entry input names or None). Raises RunInputError."""
    inputs = declared(automation)
    given = dict(given or {})
    if unknown := sorted(set(given) - {i["name"] for i in inputs}):
        takes = ", ".join(i["name"] for i in inputs) or "none"
        raise RunInputError(f"this workflow has no input {', '.join(unknown)} (its inputs: {takes})")
    values: dict[str, Any] = {}
    entry_id = None
    for spec in inputs:
        name, kind = spec["name"], spec.get("type") or "text"
        raw = given.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raw = spec.get("default")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if spec.get("required", True) and not dry_run:
                raise RunInputError(f"“{spec.get('label') or name}” is needed to run this workflow")
            values[name] = f"‹{name}›" if dry_run and spec.get("required", True) and kind != "entry" else None
            continue
        values[name] = _value(session, group_id, spec, raw)
        if kind == "entry":
            entry_id = values[name]
    return values, entry_id


def _value(session, group_id, spec: dict, raw):
    name, kind = spec["name"], spec.get("type") or "text"
    label = spec.get("label") or name
    if kind == "number":
        try:
            number = float(str(raw).replace(",", "").strip())
        except ValueError as e:
            raise RunInputError(f"“{label}” is a number, not {raw!r}") from e
        return int(number) if number.is_integer() else number
    if kind == "choice":
        options = [str(o) for o in spec.get("options") or []]
        if str(raw) not in options:
            raise RunInputError(f"“{label}” is one of {', '.join(options)} — not {raw!r}")
        return str(raw)
    if kind == "entry":
        return _entry_id(session, group_id, label, str(raw).strip())
    text = str(raw)
    if len(text) > MAX_TEXT_CHARS:
        raise RunInputError(f"“{label}” is longer than {MAX_TEXT_CHARS:,} characters")
    return text


def _entry_id(session, group_id, label: str, ref: str) -> str:
    from marvin.db.models.platform.entries import Entries
    from marvin.services.entries.query import _uuids

    found = (
        session.query(Entries.id)
        .filter(Entries.group_id == group_id, Entries.status != "trashed", (Entries.slug == ref) | Entries.id.in_(_uuids([ref])))
        .first()
    )
    if found is None:
        raise RunInputError(f"“{label}”: no entry {ref!r} in this workspace")
    return str(found[0])


def describe(automation) -> list[dict]:
    """The inputs as the agent's tools and the Run form show them: name, label, type, options, required, default."""
    keys = ("name", "label", "type", "options", "required", "default", "description")
    return [{k: spec[k] for k in keys if spec.get(k) is not None} for spec in declared(automation)]
