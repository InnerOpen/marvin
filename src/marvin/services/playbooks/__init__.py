"""Playbooks: written procedures an agent picks up when a task calls for one (Agent Skills, `SKILL.md` on the wire).

A Playbook is an entry of the internal ``playbook`` type (``listed: false``, not publishable to a site): its fields hold
the standard frontmatter and the markdown ``body``; drafts, history, trash and backup come from entries unchanged. Only a
*published* one steers an agent. Everything that decides what an agent may see or load lives here, so the registry tools
(``services/ai/tools/builtins_playbooks.py``), the system-frame catalog and the REST routes answer the same way:

* ``ensure_playbook_type``: the type, created the first time a Playbook is written (the pattern of Social's rule type);
* ``published_playbooks`` / ``published_playbook`` / ``find_published``: the one place that says which Playbooks a run may
  see (an agent's chosen set, manual-only). A run's catalog is the workspace's published Playbooks, then the system Playbooks
  its workspace gets (``system.py``: read from the installed packages, no rows, id ``system:<name>``);
* ``playbooks_used`` / ``playbooks_in_effect``: which Playbooks a run loaded, read back from its trace.

The rest is split by concern and re-exported here, so callers import from ``marvin.services.playbooks``:

* ``system``: system Playbooks (shipped by Marvin and its plugins), their lint and their switches;
* ``catalog``: the system-frame paragraphs (the catalog, the "always load" Playbooks);
* ``proposals``: an agent's proposed change to a published Playbook, and what agents may not change;
* ``files``: reference files, assets linked to the Playbook entry by their relative path;
* ``skill_md`` / ``importer`` / ``github`` / ``exporter`` / ``memory``: the file format, import, export and thread memory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from marvin.core.root_logger import get_logger
from marvin.services.playbooks.skill_md import COMPATIBILITY_MAX, DESCRIPTION_MAX, NAME_MAX, NAME_PATTERN

logger = get_logger(__name__)

PLAYBOOK_TYPE = "playbook"
PLAYBOOK_STATUS = "published"  # the only status that loads; draft, inbox, needs_review, approved, archived, trashed do not
PLAYBOOKS_NOT_ENTRIES = "Playbooks are not read as entries: call list_playbooks, then load_playbook with a name (published Playbooks only)."
LOAD_TOOL = "load_playbook"
LIST_TOOL = "list_playbooks"
READ_FILE_TOOL = "read_playbook_file"
USED_KEY = "playbooks"  # AIExecutionModel.metadata_json[USED_KEY] = [{"id", "name"}, …]

_FIELDS = [
    {
        "key": "name",
        "label": "Name",
        "type": "text",
        "required": True,
        "max": NAME_MAX,
        "pattern": NAME_PATTERN,
        "helpText": "Lowercase words joined by hyphens. It is how an agent asks for the Playbook, and the entry's slug.",
    },
    {
        "key": "description",
        "label": "Description",
        "type": "text",
        "required": True,
        "max": DESCRIPTION_MAX,
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
    {"key": "compatibility", "label": "Compatibility", "type": "text", "max": COMPATIBILITY_MAX},
    {
        "key": "allowed_tools",
        "label": "Allowed tools",
        "type": "text",
        "helpText": "Tools the Playbook may use (narrows the agent, never widens it).",
    },
    {"key": "manual_only", "label": "Manual only", "type": "boolean", "defaultValue": False, "helpText": "Loaded only when a person names it."},
    {
        "key": "replaces",
        "label": "Replaces",
        "type": "text",
        "helpText": "Set on a proposed change: the name of the published Playbook it would replace. Publishing the change updates that Playbook.",
    },
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
    manual_only: bool = False
    allowed_tools: str = ""  # the standard's `allowed-tools`: space-separated names, kept as written
    source: str = "workspace"  # "workspace" (an entry) | "core" | "plugin" (a system Playbook: read-only, ``system:<name>`` id)
    label: str = ""  # a system Playbook's "System · Marvin" / "System · S3 storage"
    version: str = ""  # a system Playbook's package version
    hash: str = ""  # a system Playbook's content hash

    @property
    def is_system(self) -> bool:
        return self.source != "workspace"


ALWAYS_MAX = 3  # "always load" Playbooks per agent


@dataclass(frozen=True)
class PlaybookScope:
    """What one run of one agent may see: the agent's settings plus the message it is answering.

    * ``names``: the chosen set (None = every published Playbook);
    * ``always``: Playbooks put in full in the system frame (at most ``ALWAYS_MAX``);
    * ``also``: Playbooks one run adds on top (a workflow's agent step names them): in the chosen set whatever it is, and
      put in full in the system frame after ``always`` (at most ``ALWAYS_MAX`` of their own);
    * ``asked``: the user's latest message. A manual-only Playbook is loadable only when this *names* it (see ``is_named``),
      when a workflow step named it in ``also``, or when the caller is ``direct``;
    * ``direct``: a person driving the tools themselves (MarvinMCP, the remote MCP server, the invoke route: no agent decides what
      to load), who may list and load a manual-only Playbook by name.

    The default scope is "all published, nothing asked": a manual-only Playbook loads only for a run that names it."""

    names: tuple[str, ...] | None = None
    always: tuple[str, ...] = ()
    asked: str = ""
    also: tuple[str, ...] = ()
    direct: bool = False

    @classmethod
    def of(cls, settings: dict | None, asked: str = "") -> PlaybookScope:
        """The scope of an agent's stored ``playbooks`` setting (``{"names": [...]|None, "always": [...]}``)."""
        settings = settings or {}
        names = settings.get("names")
        return cls(
            names=tuple(names) if names is not None else None,
            always=tuple(settings.get("always") or ()),
            asked=asked,
        )

    def allows(self, name: str) -> bool:
        return self.names is None or name in self.names or name in self.also

    def reaches(self, playbook: Playbook) -> bool:
        """May a run with this scope load ``playbook``? Manual-only ones only when named, chosen by a workflow step, or direct."""
        return self.allows(playbook.name) and (
            not playbook.manual_only or self.direct or playbook.name in self.also or is_named(playbook.name, self.asked)
        )

    def asking(self, message: str | None) -> PlaybookScope:
        """This scope for a run answering ``message`` (the user's latest message)."""
        return replace(self, asked=message or "")


def is_named(name: str, text: str | None) -> bool:
    """Did the user name this Playbook? Its name (``bench-note-voice``) appears in the text as whole words, in any case,
    with hyphens, underscores or spaces between them: ``Bench Note Voice`` and ``bench_note_voice`` count, ``bench-note-voices`` and
    ``mybench-note-voice`` do not. Only the user's latest message is read, never the agent's own output or a tool result."""
    parts = [re.escape(part) for part in name.lower().split("-") if part]
    if not parts or not text:
        return False
    return re.search(r"(?<![a-z0-9])(?<![a-z0-9][-_])" + r"[\s_-]+".join(parts) + r"(?![a-z0-9])(?![-_][a-z0-9])", text.lower()) is not None


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


def _playbook_from_row(row) -> Playbook:
    data = row.data_json or {}
    return Playbook(
        id=str(row.id),
        name=row.slug,
        description=str(data.get("description") or ""),
        body=str(data.get("body") or ""),
        manual_only=data.get("manual_only") is True,
        allowed_tools=str(data.get("allowed_tools") or ""),
    )


def playbook_type_id(session, group_id):
    """The workspace's ``playbook`` entry type id, or None when no Playbook was ever written. Never creates it (a read path)."""
    from marvin.db.models.platform.entry_types import EntryTypes

    return session.query(EntryTypes.id).filter_by(group_id=group_id, slug=PLAYBOOK_TYPE).scalar()


def all_playbooks(session, group_id) -> list:
    """Every Playbook entry of the workspace except those in the Trash, by name (the Playbooks page's list). Entry rows."""
    from marvin.db.models.platform.entries import Entries

    type_id = playbook_type_id(session, group_id)
    if type_id is None:
        return []
    return (
        session.query(Entries)
        .filter(Entries.group_id == group_id, Entries.entry_type_id == type_id, Entries.status != "trashed")
        .order_by(Entries.slug)
        .all()
    )


def _system_playbook(p) -> Playbook:
    return Playbook(
        id=p.id,
        name=p.name,
        description=p.description,
        body=p.body,
        manual_only=p.manual_only,
        allowed_tools=p.allowed_tools,
        source=p.source,
        label=p.label,
        version=p.version,
        hash=p.hash,
    )


def _candidates(session, group_id, scope: PlaybookScope | None, system: bool) -> list[Playbook]:
    """The workspace's published Playbooks by name, then (for a run, or when asked) the system ones its workspace gets."""
    found = [_playbook_from_row(row) for row in _published_rows(session, group_id)]
    if scope is not None or system:
        from marvin.services.playbooks.system import visible_system

        found += [_system_playbook(p) for p in visible_system(session, group_id)]
    return found


def published_playbooks(session, group_id, scope: PlaybookScope | None = None, *, system: bool = False) -> list[Playbook]:
    """The workspace's published Playbooks by name, then the system Playbooks it gets. A workspace with none gets [].

    With a ``scope`` this is what that run's catalog lists: the chosen set only, system Playbooks included, and no manual-only
    Playbook (those are never offered, only loaded when named) unless the caller is ``direct``. Without one it is the workspace's
    own published Playbooks, for the admin screens (``system=True`` adds the system ones)."""
    found = _candidates(session, group_id, scope, system)
    if scope is None:
        return found
    return [p for p in found if scope.allows(p.name) and (not p.manual_only or scope.direct)]


def find_published(session, group_id, name: str, scope: PlaybookScope | None = None, *, system: bool = False):
    """``(entry row | SystemPlaybook, Playbook)`` of the published Playbook called ``name`` that a run with ``scope`` may see, else
    None: a draft, another workspace's and a made-up name look the same. A workspace's own Playbook wins over a system one with the
    name. With a ``scope`` it is also None for one outside the agent's chosen set and for a manual-only one the run was not given
    (``PlaybookScope.reaches``). The one lookup behind ``published_playbook`` and the files. System Playbooks are looked up only
    with a ``scope`` (or ``system=True``)."""
    from marvin.db.models.platform.entries import Entries

    key = str(name or "").strip().lower()
    row = _published_rows(session, group_id).filter(Entries.slug == key).first()
    if row is not None:
        playbook = _playbook_from_row(row)
        found = (row, playbook)
    elif scope is not None or system:
        from marvin.services.playbooks.system import visible_system

        mine = next((p for p in visible_system(session, group_id) if p.name == key), None)
        if mine is None:
            return None
        found = (mine, _system_playbook(mine))
    else:
        return None
    if scope is not None and not scope.reaches(found[1]):
        return None
    return found


def published_playbook(session, group_id, name: str, scope: PlaybookScope | None = None, *, system: bool = False) -> Playbook | None:
    """One published Playbook of this workspace (or a system one it gets) by name, or None (see ``find_published``)."""
    found = find_published(session, group_id, name, scope, system=system)
    return found[1] if found is not None else None


def manual_only_refusal(session, group_id, name: str, scope: PlaybookScope) -> str | None:
    """The message for a load refused only because the Playbook is manual-only and unnamed; None for any other refusal
    (an outside-the-set Playbook must look like a made-up name, so it gets no message of its own)."""
    found = published_playbook(session, group_id, name, system=True)
    if found is not None and found.manual_only and scope.allows(found.name) and not scope.reaches(found):
        return f"'{found.name}' is a manual-only Playbook: it loads only when the user names it in their message. Ask them to name it."
    return None


def always_playbooks(session, group_id, scope: PlaybookScope) -> list[Playbook]:
    """The agent's "always load" Playbooks that can still be loaded (published or system, in its set, not manual-only), in its
    order, then the run's own (``also``: a workflow step names them, so a manual-only one counts)."""
    by_name = {p.name: p for p in _candidates(session, group_id, scope, True) if scope.allows(p.name) and (not p.manual_only or p.name in scope.also)}
    named = [*scope.always[:ALWAYS_MAX], *(n for n in scope.also[:ALWAYS_MAX] if n not in scope.always[:ALWAYS_MAX])]
    return [by_name[name] for name in named if name in by_name]


class PlaybookSettingsError(ValueError):
    """An agent's Playbook settings that can't be saved; the message says why and is safe to show."""


def check_agent_settings(session, group_id, settings: dict | None) -> None:
    """Refuse settings that name more than ``ALWAYS_MAX`` "always load" Playbooks, one outside the chosen set, or one that is
    not a published, non-manual-only Playbook of this workspace (an always-loaded Playbook must be able to load by itself).
    Names in the chosen set may be anything: a Playbook still being written can be chosen before it is published."""
    settings = settings or {}
    always, names = list(settings.get("always") or []), settings.get("names")
    if len(always) > ALWAYS_MAX:
        raise PlaybookSettingsError(f"An agent can always load at most {ALWAYS_MAX} Playbooks; remove one first.")
    if names is not None and (outside := [n for n in always if n not in names]):
        raise PlaybookSettingsError(f"Always-loaded Playbooks must be in the chosen set: {', '.join(outside)}.")
    loadable = {p.name for p in published_playbooks(session, group_id, PlaybookScope())}  # the workspace's and the system ones it gets
    if missing := [n for n in always if n not in loadable]:
        raise PlaybookSettingsError(f"Not a published Playbook that loads by itself (manual-only ones do not): {', '.join(missing)}.")


def playbooks_used(steps) -> list[dict]:
    """The Playbooks a run loaded, in first-load order, as ``{"id", "name"}`` (a system Playbook's id is ``system:<name>`` and it also
    has its ``version``), read from its trace (a refused load is not a use)."""
    used: dict[str, dict] = {}
    for step in steps:
        if getattr(step, "tool", None) != LOAD_TOOL:
            continue
        try:
            out = json.loads(step.result)
        except (TypeError, ValueError):
            continue
        if isinstance(out, dict) and out.get("id") and not out.get("error"):
            used.setdefault(out["id"], {"id": out["id"], "name": out.get("name"), **({"version": out["version"]} if out.get("version") else {})})
    return list(used.values())


def loaded_playbook_names(convo) -> list[str]:
    """Names of the Playbooks a conversation loaded, in first-load order, read from its messages: an assistant
    ``load_playbook`` call whose tool message is not an error. The run's own trace, so a run resumed after a park (whose
    loop starts with an empty step list) still knows what it loaded."""
    calls = {c.id: c for m in convo if getattr(m, "role", None) == "assistant" for c in (getattr(m, "tool_calls", None) or []) if c.name == LOAD_TOOL}
    names: list[str] = []
    for m in convo:
        if getattr(m, "role", None) != "tool" or m.tool_call_id not in calls:
            continue
        try:
            out = json.loads(m.content)
        except (TypeError, ValueError):
            continue
        if isinstance(out, dict) and out.get("name") and not out.get("error") and out["name"] not in names:
            names.append(out["name"])
    return names


def playbooks_in_effect(session, group_id, convo=(), thread=None, scope: PlaybookScope | None = None) -> list[Playbook]:
    """THE seam for "which Playbooks steer this run": what the tool limit (``allowed_tools``) and anything else that
    follows a loaded Playbook asks. The thread's (those its earlier replies recorded, ``memory.thread_playbooks``), then
    those loaded in this run's transcript (``convo``, see ``loaded_playbook_names``). Only ones still published count,
    with their current text. With the agent's ``scope``, its always-load Playbooks come first (they steer every run) and
    anything outside its chosen set is left out; a manual-only one that was loaded stays in effect for its thread."""
    from marvin.services.playbooks.memory import thread_playbooks

    names: dict[str, None] = {}
    if scope is not None:
        for p in always_playbooks(session, group_id, scope):
            names.setdefault(p.name, None)
    for entry in thread_playbooks(thread):
        names.setdefault(entry.get("name") or "", None)
    for name in loaded_playbook_names(convo):
        names.setdefault(name, None)
    found = (published_playbook(session, group_id, name, system=True) for name in names if name and (scope is None or scope.allows(name)))
    return [p for p in found if p is not None]


def parse_allowed_tools(raw) -> list[str]:
    """The tokens of an ``allowed-tools`` value, in order, without duplicates. The standard separates with spaces; a
    token may carry a parenthesised qualifier holding spaces (``Bash(git add:*)``), and commas also separate."""
    seen: dict[str, None] = {}
    for token in re.findall(r"[^\s,()]+(?:\([^)]*\))?", str(raw or "")):
        seen.setdefault(token, None)
    return list(seen)


# Re-exported so callers keep importing from ``marvin.services.playbooks``. Last, because each submodule imports names defined above.
from marvin.services.playbooks.catalog import (  # noqa: E402, F401
    ALWAYS_WARN_CHARS,
    CATALOG_LINE_CHARS,
    CATALOG_MAX,
    PROPOSE_HINT,
    always_block,
    always_warning,
    catalog_block,
    frame_block,
)
from marvin.services.playbooks.files import (  # noqa: E402, F401
    FILES_MAX,
    PATH_MAX,
    PlaybookFileError,
    ReferenceFile,
    SystemFile,
    attach_reference,
    normalize_path,
    published_playbook_file,
    published_playbook_files,
    reference_files,
    remove_reference,
)
from marvin.services.playbooks.proposals import (  # noqa: E402, F401
    CHANGE_KEYS,
    CHANGE_SUFFIX,
    REPLACES_KEY,
    agent_change_refusal,
    change_target,
    changed_data,
)
