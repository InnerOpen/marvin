"""Library recipes a workspace's runners offer: one "run this on a worker" recipe per kind of job an online worker can do.

A worker's heartbeat (a ``worker`` entry) lists its ``kinds``, each with a contract: what it takes (``inputs``: type, required,
description, the file types an asset accepts), what it makes and what it needs. That is enough to write the workflow that asks for those
inputs and queues the job, so the worker supplies no workflow text of its own: nothing it sends is ever run as a definition, only read
as labels. A recipe is offered while a worker that can do the kind is online, and it is built from that contract each time, so it
follows the worker.

The workflow is the one a person would write by hand (Screenplay Studio's "transcribe a recording" is the model): a manual trigger whose
inputs mirror the contract, and a ``job`` entry (``kind``, ``args``, ``status: queued``) a worker claims.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from marvin.services.worker_health import QUIET_AFTER

RECIPE_PREFIX = "runner."
MAX_INPUTS = 12
MAX_LABEL_CHARS = 200  # a worker's words are shown as labels: cut, never trusted for length

_KIND = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_INPUT_NAME = re.compile(r"[^a-z0-9_]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NUMBER_TYPES = {"number", "integer", "int", "float"}


def _label(value: Any) -> str:
    """A worker's text as a one-line label: control characters out, length capped."""
    return _CONTROL.sub(" ", str(value or "")).strip()[:MAX_LABEL_CHARS]


def _seen(value: Any) -> datetime | None:
    try:
        seen = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return seen.replace(tzinfo=UTC) if seen.tzinfo is None else seen.astimezone(UTC)


def online_kinds(session, group_id, now: datetime | None = None) -> dict[str, dict]:
    """``{kind: {"contract": {...}, "offered_by": [host, …]}}`` for every kind a worker that has reported in recently can do. The
    first worker to name a kind sets the contract, as the Workers page does."""
    from marvin.db.models.platform import Entries, EntryTypes

    now = now or datetime.now(UTC)
    rows = (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.group_id == group_id, EntryTypes.slug == "worker", Entries.status != "trashed")
        .all()
    )
    found: dict[str, dict] = {}
    for row in rows:
        data = row.data_json or {}
        seen = _seen(data.get("last_seen"))
        if seen is None or now - seen > QUIET_AFTER:
            continue
        host = _label(data.get("host")) or row.title
        for contract in data.get("kinds") or []:
            kind = contract.get("kind") if isinstance(contract, dict) else None
            if not isinstance(kind, str) or not _KIND.match(kind):
                continue
            item = found.setdefault(kind, {"contract": contract, "offered_by": []})
            if host not in item["offered_by"]:
                item["offered_by"].append(host)
    return found


def _input_for(name: str, spec: dict, taken: set[str]) -> tuple[dict, str] | None:
    """(the run input, the job argument it fills) for one input of a contract; None for one a form can't ask for."""
    safe = _INPUT_NAME.sub("_", name.lower()).strip("_")[:40]
    if not re.match(r"^[a-z]", safe) or safe in taken:
        return None
    taken.add(safe)
    kind = str(spec.get("type") or "string").lower()
    accepts = [_label(a) for a in spec.get("accepts") or [] if isinstance(a, str)][:6]
    hint = _label(spec.get("description"))
    if kind == "asset" and accepts:
        hint = f"{hint} ({', '.join(accepts)})".strip()
    run_input = {
        "name": safe,
        "label": name.replace("_", " ").capitalize(),
        "type": "asset" if kind == "asset" else "entry" if kind == "entry" else "number" if kind in _NUMBER_TYPES else "text",
        "required": spec.get("required") is not False,
    }
    if hint:
        run_input["description"] = hint
    return run_input, name


def _recipe(kind: str, contract: dict, offered_by: list[str]) -> dict | None:
    taken: set[str] = set()
    inputs, args = [], {}
    spec_by_name = contract.get("inputs") if isinstance(contract.get("inputs"), dict) else {}
    for name, spec in list(spec_by_name.items())[:MAX_INPUTS]:
        made = _input_for(str(name), spec if isinstance(spec, dict) else {}, taken)
        if made is None:
            continue
        run_input, arg = made
        inputs.append(run_input)
        args[arg] = f"${{input.{run_input['name']}}}"
    if sum(1 for i in inputs if i["type"] == "entry") > 1:
        return None  # a run acts on one entry at most
    first = next((i for i in inputs if i["required"]), None)
    label = kind.replace("-", " ").replace("_", " ").capitalize()
    title = f"{label}: ${{input.{first['name']}|truncate:60}}" if first else label
    definition = {
        "trigger": {"type": "manual", "inputs": inputs},
        "actions": [
            {
                "kind": "entry",
                "op": "create",
                "entry_type": "job",
                "title": title,
                "status": "draft",
                "data": {"kind": kind, "args": args, "status": "queued"},
            }
        ],
    }
    return {"name": f"Run {kind} on a worker", "definition": definition}


def _entry(kind: str, contract: dict, offered_by: list[str]) -> dict:
    said = _label(contract.get("description"))
    makes = ", ".join(_label(p) for p in contract.get("produces") or [] if isinstance(p, str))
    who = ", ".join(offered_by[:3])
    result = f"the result and log are on the job entry, and it makes {makes}" if makes else "the result and log are on the job entry"
    outcome = f"{said + ' ' if said else ''}A worker ({who}) picks the job up; {result}."
    return {
        "id": f"{RECIPE_PREFIX}{kind}",
        "title": f"Run “{kind}” on a worker",
        "outcome": outcome,
        "category": "Workers",
        "category_slug": "workers",
        "tags": ["workers", kind],
        "trigger": {"type": "manual", "event": None},
        "status": "supported-after-configuration",
        "shape": "workflow",
        "runnable": True,
        "setup_variables": [],
        "prerequisites": {"integrations": []},
        "side_effects": [
            {"kind": "content_mutation", "description": "Queues a job for a worker, which may take a while and use that machine's time."}
        ],
        "supporting_objects": [],
        "dependencies": [],
        "source": {"provider": "workers", "name": who, "package": None, "version": None},
    }


def recipes(session, group_id, now: datetime | None = None) -> dict[str, dict]:
    """``{"runner.<kind>": {"entry", "document", "variables"}}`` for this workspace, the shape ``recipes.plugin_recipes`` has."""
    out: dict[str, dict] = {}
    for kind, item in sorted(online_kinds(session, group_id, now).items()):
        document = _recipe(kind, item["contract"], item["offered_by"])
        if document is not None:
            out[f"{RECIPE_PREFIX}{kind}"] = {"entry": _entry(kind, item["contract"], item["offered_by"]), "document": document, "variables": {}}
    return out
