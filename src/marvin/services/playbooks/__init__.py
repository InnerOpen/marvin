"""Playbooks: written procedures an agent picks up when a task calls for one (Agent Skills, `SKILL.md` on the wire).

A Playbook is an entry of the internal ``playbook`` type (``listed: false``, not publishable to a site): its fields hold
the standard frontmatter and the markdown ``body``; drafts, history, trash and backup come from entries unchanged. Only a
*published* one steers an agent. Everything that decides what an agent may see or load lives here, so the registry tools
(``services/ai/tools/builtins_playbooks.py``), the system-frame catalog and the REST routes answer the same way:

* ``ensure_playbook_type``: the type, created the first time a Playbook is written (the pattern of Social's rule type);
* ``published_playbooks`` / ``published_playbook``: the one place that says which Playbooks a run may see. Later tickets
  narrow it there (an agent's chosen set, manual-only);
* ``catalog_block``: the paragraph the system frame adds, empty when there is nothing to list;
* ``playbooks_used``: which Playbooks a run loaded, read back from its trace for the execution record;
* reference files: assets linked to the Playbook entry whose junction ``role`` is the file's relative path
  (``references/tone.md``). ``attach_reference`` / ``reference_files`` / ``remove_reference`` manage them and
  ``published_playbook_file`` is the one place that says which one an agent may read. No column of its own: the junction
  already has ``role``, and the existing attach/detach tools and routes keep working with it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

PLAYBOOK_TYPE = "playbook"
PLAYBOOK_STATUS = "published"  # the only status that loads; draft, inbox, needs_review, approved, archived, trashed do not
LOAD_TOOL = "load_playbook"
LIST_TOOL = "list_playbooks"
READ_FILE_TOOL = "read_playbook_file"
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
    manual_only: bool = False
    allowed_tools: str = ""  # the standard's `allowed-tools`: space-separated names, kept as written


ALWAYS_MAX = 3  # "always load" Playbooks per agent
ALWAYS_WARN_CHARS = 12_000  # about 3,000 tokens of instructions in every run's system prompt


@dataclass(frozen=True)
class PlaybookScope:
    """What one run of one agent may see: the agent's settings plus the message it is answering.

    * ``names``: the chosen set (None = every published Playbook);
    * ``always``: Playbooks put in full in the system frame (at most ``ALWAYS_MAX``);
    * ``asked``: the user's latest message. A manual-only Playbook is loadable only when this *names* it (see ``is_named``).

    The default scope (no agent: MarvinMCP, the remote MCP server, the invoke route) is "all published, nothing asked", so a
    manual-only Playbook never loads for those callers."""

    names: tuple[str, ...] | None = None
    always: tuple[str, ...] = ()
    asked: str = ""

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
        return self.names is None or name in self.names


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
    return Playbook(
        id=str(row.id),
        name=row.slug,
        description=str(data.get("description") or ""),
        body=str(data.get("body") or ""),
        manual_only=data.get("manual_only") is True,
        allowed_tools=str(data.get("allowed_tools") or ""),
    )


def _visible(playbook: Playbook, scope: PlaybookScope) -> bool:
    """May a run with this scope load it? In the chosen set, and when manual-only, named in the user's message."""
    return scope.allows(playbook.name) and (not playbook.manual_only or is_named(playbook.name, scope.asked))


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


def published_playbooks(session, group_id, scope: PlaybookScope | None = None) -> list[Playbook]:
    """The workspace's published Playbooks by name. A workspace with none (or never written one) gets [].

    With a ``scope`` this is what that run's catalog lists: the chosen set only, and no manual-only Playbook (those are
    never offered, only loaded when named). Without one it is every published Playbook, for the admin screens."""
    found = [_of(row) for row in _published_rows(session, group_id)]
    if scope is None:
        return found
    return [p for p in found if scope.allows(p.name) and not p.manual_only]


def published_playbook(session, group_id, name: str, scope: PlaybookScope | None = None) -> Playbook | None:
    """One published Playbook of this workspace by name, or None: a draft, another workspace's and a made-up name look the same.

    With a ``scope``, also None for one outside the agent's chosen set and for a manual-only one the user did not name."""
    from marvin.db.models.platform.entries import Entries

    row = _published_rows(session, group_id).filter(Entries.slug == str(name or "").strip().lower()).first()
    found = _of(row) if row is not None else None
    if found is not None and scope is not None and not _visible(found, scope):
        return None
    return found


def manual_only_refusal(session, group_id, name: str, scope: PlaybookScope) -> str | None:
    """The message for a load refused only because the Playbook is manual-only and unnamed; None for any other refusal
    (an outside-the-set Playbook must look like a made-up name, so it gets no message of its own)."""
    found = published_playbook(session, group_id, name)
    if found is not None and found.manual_only and scope.allows(found.name) and not is_named(found.name, scope.asked):
        return f"'{found.name}' is a manual-only Playbook: it loads only when the user names it in their message. Ask them to name it."
    return None


def always_playbooks(session, group_id, scope: PlaybookScope) -> list[Playbook]:
    """The agent's "always load" Playbooks that can still be loaded (published, in its set, not manual-only), in its order."""
    by_name = {p.name: p for p in published_playbooks(session, group_id, scope)}
    return [by_name[name] for name in scope.always[:ALWAYS_MAX] if name in by_name]


def always_block(playbooks: Iterable[Playbook]) -> str:
    """The system-frame section with each "always load" Playbook in full; "" when there are none."""
    listed = list(playbooks)
    if not listed:
        return ""
    parts = ["## Playbooks to follow in every conversation\nThese Playbooks are already loaded: follow them without calling " + LOAD_TOOL + "."]
    parts += [f"### {p.name}\n{p.body.strip()}" for p in listed]
    return "\n\n".join(parts)


def always_warning(playbooks: Iterable[Playbook]) -> str | None:
    """A warning when the "always load" Playbooks are long (they ride along with every run); None when they are not."""
    size = sum(len(p.body) for p in playbooks)
    if size <= ALWAYS_WARN_CHARS:
        return None
    return (
        f"These always-loaded Playbooks add about {size // 4:,} tokens ({size:,} characters) to every run of this agent. "
        "Consider loading the long ones on demand instead."
    )


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
    loadable = {p.name for p in published_playbooks(session, group_id, PlaybookScope())}
    if missing := [n for n in always if n not in loadable]:
        raise PlaybookSettingsError(f"Not a published Playbook that loads by itself (manual-only ones do not): {', '.join(missing)}.")


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


def playbooks_in_effect(session, group_id, convo=(), thread=None) -> list[Playbook]:
    """THE seam for "which Playbooks steer this run": what the tool limit (``allowed_tools``) and anything else that
    follows a loaded Playbook asks. The thread's (those its earlier replies recorded, ``memory.thread_playbooks``), then
    those loaded in this run's transcript (``convo``, see ``loaded_playbook_names``). Only ones still published count,
    with their current text. Later sources (an agent's always-load Playbooks, ticket 05) are added here."""
    from marvin.services.playbooks.memory import thread_playbooks

    names: dict[str, None] = {}
    for entry in thread_playbooks(thread):
        names.setdefault(entry.get("name") or "", None)
    for name in loaded_playbook_names(convo):
        names.setdefault(name, None)
    found = (published_playbook(session, group_id, name) for name in names if name)
    return [p for p in found if p is not None]


def parse_allowed_tools(raw) -> list[str]:
    """The tokens of an ``allowed-tools`` value, in order, without duplicates. The standard separates with spaces; a
    token may carry a parenthesised qualifier holding spaces (``Bash(git add:*)``), and commas also separate."""
    seen: dict[str, None] = {}
    for token in re.findall(r"[^\s,()]+(?:\([^)]*\))?", str(raw or "")):
        seen.setdefault(token, None)
    return list(seen)


# ── Reference files ──────────────────────────────────────────────────────────

PATH_MAX = 255
FILES_MAX = 100  # reference files per Playbook


class PlaybookFileError(ValueError):
    """A reference file that can't be attached; the message says why and is safe to show."""


def normalize_path(path) -> str:
    """A reference file's path as kept: relative, forward slashes, no ``.``/``..`` parts (``references/tone.md``).

    Raises PlaybookFileError for anything that could point outside the Playbook's own folder."""
    raw = str(path or "").strip()
    if not raw or len(raw) > PATH_MAX or "\\" in raw or "\x00" in raw or raw.startswith("/"):
        raise PlaybookFileError("A reference file's path is relative, like 'references/tone.md' (at most 255 characters).")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PlaybookFileError("A reference file's path stays inside the Playbook: no '..' and no leading '/'.")
    return "/".join(parts)


@dataclass(frozen=True)
class ReferenceFile:
    path: str
    asset_id: str
    name: str
    mime_type: str | None
    size: int


def _playbook_entry(session, group_id, entry_id):
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    return (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.id == entry_id, Entries.group_id == group_id, EntryTypes.group_id == group_id, EntryTypes.slug == PLAYBOOK_TYPE)
        .first()
    )


def _links(session, entry_id):
    """(junction, asset) pairs of a Playbook's reference files: live assets whose role is a valid path, by path."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets

    rows = (
        session.query(EntryAssets, Assets)
        .join(Assets, EntryAssets.asset_id == Assets.id)
        .filter(EntryAssets.entry_id == entry_id, Assets.trashed_at.is_(None), EntryAssets.role.isnot(None))
        .all()
    )
    found = []
    for link, asset in rows:
        try:
            found.append((normalize_path(link.role), link, asset))
        except PlaybookFileError:
            continue  # some other role ('hero'): not a reference file
    return sorted(found, key=lambda t: t[0])


def _file(path, asset) -> ReferenceFile:
    return ReferenceFile(path=path, asset_id=str(asset.id), name=asset.name, mime_type=asset.mime_type, size=int(asset.file_size or 0))


def reference_files(session, entry_id) -> list[ReferenceFile]:
    """A Playbook entry's reference files by path (not workspace-checked: callers hold an entry they may see)."""
    return [_file(path, asset) for path, _link, asset in _links(session, entry_id)]


def attach_reference(session, group_id, entry_id, asset_id, path) -> ReferenceFile:
    """Attach a workspace asset to a Playbook under ``path`` (committed). Linking the same asset again moves it to the new path.

    Raises PlaybookFileError: not a Playbook of this workspace, not a live asset of it, a bad or taken path, too many files."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets

    clean = normalize_path(path)
    if _playbook_entry(session, group_id, entry_id) is None:
        raise PlaybookFileError("No such Playbook in this workspace.")
    asset = session.get(Assets, asset_id)
    if asset is None or str(asset.group_id) != str(group_id) or asset.trashed_at is not None:
        raise PlaybookFileError("No such asset in this workspace.")
    current = _links(session, entry_id)
    mine = next((link for _p, link, a in current if a.id == asset.id), None)
    if any(p == clean and a.id != asset.id for p, _l, a in current):
        raise PlaybookFileError(f"The Playbook already has a file at '{clean}'.")
    if mine is None and len(current) >= FILES_MAX:
        raise PlaybookFileError(f"A Playbook holds at most {FILES_MAX} reference files.")
    if mine is None:
        mine = session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset.id).first()  # linked, but not as a reference
    if mine is None:
        top = session.query(sa.func.max(EntryAssets.position)).filter(EntryAssets.entry_id == entry_id).scalar()
        mine = EntryAssets(entry_id=entry_id, asset_id=asset.id, position=0 if top is None else top + 1)
        session.add(mine)
    mine.role = clean
    session.commit()
    return _file(clean, asset)


def remove_reference(session, group_id, entry_id, path) -> bool:
    """Take the file at ``path`` off a Playbook (committed; the asset itself stays). False when there was none."""
    if _playbook_entry(session, group_id, entry_id) is None:
        return False
    try:
        wanted = normalize_path(path)
    except PlaybookFileError:
        return False
    for found, link, _asset in _links(session, entry_id):
        if found == wanted:
            session.delete(link)
            session.commit()
            return True
    return False


def _visible_row(session, group_id, name: str, scope: PlaybookScope | None):
    """The published Playbook entry called ``name`` that ``scope`` (when given) lets a run see, else None."""
    from marvin.db.models.platform.entries import Entries

    row = _published_rows(session, group_id).filter(Entries.slug == str(name or "").strip().lower()).first()
    if row is not None and scope is not None and not _visible(_of(row), scope):
        return None
    return row


def published_playbook_files(session, group_id, name: str, scope: PlaybookScope | None = None) -> list[ReferenceFile] | None:
    """The reference-file index of a published Playbook by name, or None when it isn't one (draft, other workspace, made up,
    or outside the ``scope`` the run has)."""
    row = _visible_row(session, group_id, name, scope)
    return reference_files(session, row.id) if row is not None else None


def published_playbook_file(session, group_id, name: str, path: str, scope: PlaybookScope | None = None):
    """The asset at ``path`` of a published Playbook of this workspace, or None: a draft, another workspace's Playbook,
    one outside the ``scope``, a path it doesn't hold and a malformed path all look the same."""
    row = _visible_row(session, group_id, name, scope)
    if row is None:
        return None
    try:
        wanted = normalize_path(path)
    except PlaybookFileError:
        return None
    for found, _link, asset in _links(session, row.id):
        if found == wanted and str(asset.group_id) == str(group_id):
            return asset
    return None
