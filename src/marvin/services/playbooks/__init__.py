"""Playbooks: written procedures an agent picks up when a task calls for one (Agent Skills, `SKILL.md` on the wire).

A Playbook is an entry of the internal ``playbook`` type (``listed: false``, not publishable to a site): its fields hold
the standard frontmatter and the markdown ``body``; drafts, history, trash and backup come from entries unchanged. Only a
*published* one steers an agent. Everything that decides what an agent may see or load lives here, so the registry tools
(``services/ai/tools/builtins_playbooks.py``), the system-frame catalog and the REST routes answer the same way:

* ``ensure_playbook_type``: the type, created the first time a Playbook is written (the pattern of Social's rule type);
* ``published_playbooks`` / ``published_playbook``: the one place that says which Playbooks a run may see. Later tickets
  narrow it there (an agent's chosen set, manual-only);
* ``catalog_block``: the paragraph the system frame adds, empty when there is nothing to list;
* ``playbooks_used``: which Playbooks a run loaded, read back from its trace for the execution record.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

PLAYBOOK_TYPE = "playbook"
PLAYBOOK_STATUS = "published"  # the only status that loads; draft, inbox, needs_review, approved, archived, trashed do not
LOAD_TOOL = "load_playbook"
LIST_TOOL = "list_playbooks"
USED_KEY = "playbooks"  # AIExecutionModel.metadata_json[USED_KEY] = [{"id", "name"}, …]

CATALOG_MAX = 50  # Playbooks named in the prompt; the rest are still found with list_playbooks
CATALOG_LINE_CHARS = 200

NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_FIELDS = [
    {
        "key": "name",
        "label": "Name",
        "type": "text",
        "required": True,
        "max": 64,
        "pattern": NAME_PATTERN,
        "helpText": "Lowercase words joined by hyphens. It is how an agent asks for the Playbook, and the entry's slug.",
    },
    {
        "key": "description",
        "label": "Description",
        "type": "text",
        "required": True,
        "max": 1024,
        "helpText": "One line the agent reads in its catalog: what the Playbook does and when to use it.",
    },
    {
        "key": "body",
        "label": "Instructions",
        "type": "markdown",
        "autoEmbed": False,
        "helpText": "What the agent follows once it loads the Playbook.",
    },
    {"key": "license", "label": "License", "type": "text"},
    {"key": "compatibility", "label": "Compatibility", "type": "text", "max": 500},
    {
        "key": "allowed_tools",
        "label": "Allowed tools",
        "type": "text",
        "helpText": "Tools the Playbook may use (narrows the agent, never widens it).",
    },
    {"key": "manual_only", "label": "Manual only", "type": "boolean", "defaultValue": False, "helpText": "Loaded only when a person names it."},
]

PLAYBOOK_TYPE_PAYLOAD = {
    "name": "Playbook",
    "icon": "📘",
    "color": "#0EA5E9",
    "description": "A written procedure agents load when a task calls for it. Only published Playbooks are used.",
    "schema_json": {"fields": _FIELDS},
    # Internal: edited from its own page, never listed with the workspace's content (services/entry_listing.py).
    "capabilities_json": {"publishable": False, "submittable": False, "routable": False, "listed": False},
}


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str
    description: str
    body: str


def ensure_playbook_type(session, group_id):
    """The workspace's ``playbook`` entry type, created when it is missing and brought up to date when it is not
    (committed). Returns its id.

    The type is made once, so a field added to ``PLAYBOOK_TYPE_PAYLOAD`` later would never reach an existing workspace:
    each call adds the payload's fields the stored schema lacks, and leaves everything else (the user's own fields,
    relabelled or changed ones, the type's name and settings) as it is.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from marvin.db.models.platform.entry_types import EntryTypes

    found = session.query(EntryTypes).filter_by(group_id=group_id, slug=PLAYBOOK_TYPE).one_or_none()
    if found is not None:
        schema = dict(found.schema_json or {})
        fields = list(schema.get("fields") or [])
        have = {f.get("key") for f in fields}
        missing = [f for f in _FIELDS if f["key"] not in have]
        if missing:
            found.schema_json = {**schema, "fields": [*fields, *(dict(f) for f in missing)]}
            flag_modified(found, "schema_json")
            session.commit()
            logger.info("playbooks: added %s to the %s entry type of workspace %s", [f["key"] for f in missing], PLAYBOOK_TYPE, group_id)
        return found.id
    created = EntryTypes(session=session, group_id=group_id, slug=PLAYBOOK_TYPE, **PLAYBOOK_TYPE_PAYLOAD)
    session.add(created)
    session.commit()
    logger.info("playbooks: created the %s entry type for workspace %s", PLAYBOOK_TYPE, group_id)
    return created.id


def is_playbook(session, entry) -> bool:
    """Whether ``entry`` is a Playbook (an entry of the workspace's ``playbook`` type)."""
    from marvin.db.models.platform.entry_types import EntryTypes

    slug = session.query(EntryTypes.slug).filter(EntryTypes.id == entry.entry_type_id).scalar()
    return slug == PLAYBOOK_TYPE


def agent_change_refusal(session, entry) -> str | None:
    """Why an agent's write tool may not change ``entry``, or None. A published Playbook steers every agent run, so
    changing, archiving or trashing it is a person's call (an Admin's), whoever the agent is working for."""
    if entry.status == PLAYBOOK_STATUS and is_playbook(session, entry):
        return f"'{entry.title}' is a published Playbook: agents can draft Playbooks but never change or remove a published one. An Admin does that from the Playbooks page."
    return None


def _published_rows(session, group_id):
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    return (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(
            Entries.group_id == group_id,
            EntryTypes.group_id == group_id,
            EntryTypes.slug == PLAYBOOK_TYPE,
            Entries.status == PLAYBOOK_STATUS,
        )
        .order_by(Entries.slug)
    )


def _of(row) -> Playbook:
    data = row.data_json or {}
    return Playbook(id=str(row.id), name=row.slug, description=str(data.get("description") or ""), body=str(data.get("body") or ""))


def published_playbooks(session, group_id) -> list[Playbook]:
    """The workspace's published Playbooks by name: what an agent may list. A workspace with none (or never written one) gets []."""
    return [_of(row) for row in _published_rows(session, group_id)]


def published_playbook(session, group_id, name: str) -> Playbook | None:
    """One published Playbook of this workspace by name, or None: a draft, another workspace's and a made-up name look the same."""
    from marvin.db.models.platform.entries import Entries

    row = _published_rows(session, group_id).filter(Entries.slug == str(name or "").strip().lower()).first()
    return _of(row) if row is not None else None


def catalog_block(playbooks: Iterable[Playbook]) -> str:
    """The system-frame paragraph naming the Playbooks, one line each; "" when there are none (nothing is added)."""
    listed = list(playbooks)
    if not listed:
        return ""
    lines = []
    for p in listed[:CATALOG_MAX]:
        text = " ".join(p.description.split())
        if len(text) > CATALOG_LINE_CHARS:
            text = text[: CATALOG_LINE_CHARS - 1].rstrip() + "…"
        lines.append(f"- {p.name}: {text}")
    more = f"\n({len(listed) - CATALOG_MAX} more: call {LIST_TOOL} to see them.)" if len(listed) > CATALOG_MAX else ""
    return (
        "## Playbooks\n"
        "This workspace keeps Playbooks: written procedures for particular tasks. When a request matches one of the "
        f"descriptions below, call {LOAD_TOOL} with its name before you start, then follow it using the tools you already "
        "have. A Playbook never gives you more tools or permissions, and one that does not fit the request is not loaded.\n" + "\n".join(lines) + more
    )


def playbooks_used(steps) -> list[dict]:
    """The Playbooks a run loaded, in first-load order, as ``{"id", "name"}``, read from its trace (a refused load is not a use)."""
    used: dict[str, dict] = {}
    for step in steps:
        if getattr(step, "tool", None) != LOAD_TOOL:
            continue
        try:
            out = json.loads(step.result)
        except (TypeError, ValueError):
            continue
        if isinstance(out, dict) and out.get("id") and not out.get("error"):
            used.setdefault(out["id"], {"id": out["id"], "name": out.get("name")})
    return list(used.values())
