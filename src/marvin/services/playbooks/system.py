"""System Playbooks: written procedures the platform offers every workspace, read-only, with no rows.

A plugin (an integration provider's ``system_playbooks``, a storage or AI plugin's ``playbooks``, SDK 0.16.0) or Marvin core
(``src/marvin/system_playbooks/<area>/<name>/SKILL.md``, areas ``marvin`` and ``social``) ships each one in its package. They are
read from the installed packages once per process (the pattern of ``services/integrations/guides.py``), so a release replaces the text
everywhere and uninstalling a plugin removes its Playbooks. A workspace's own Playbooks are entries (``services/playbooks``); these
are never copied into the database, backups skip them, and only the switches are stored.

* ``build``: the pure loader. Core's folder first, then integration providers, storage plugins and AI plugins; each is checked with
  ``payload_problem`` (caps, text only, no scripts) and the lint below, a bad one is skipped and reported, and a repeated name keeps
  the first source's. It never needs the SDK: core's skills load with core's own parser.
* ``lint``: what the SDK's ``check_playbook(scope="system")`` checks, again, because a plugin is not trusted (Rules 3, 7 and 8 refuse;
  6 and 7's body half warn). The manual's "System Playbooks" page lists the Rules.
* ``visible_system`` / ``system_states``: what one workspace gets once the switches (this workspace's, the server's), a workspace
  Playbook with the same name (it shadows) and a published copy (it replaces) are applied.

A system Playbook is manual-only unless its frontmatter says ``disable-model-invocation: false`` (Rule 5).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from marvin.core.root_logger import get_logger
from marvin.services.playbooks.blueprint import payload_problem, playbook_hash
from marvin.services.playbooks.skill_md import declares_invocation, parse_skill_md, split_tools

logger = get_logger(__name__)

ID_PREFIX = "system:"
SERVER_KEY = "system_playbooks"  # platform_settings: {"off": [name, …]}
COPIED_FROM = "copiedFrom"  # metadata_json of a copy: {name, label, version, hash}
SOURCE_CORE = "core"
SOURCE_PLUGIN = "plugin"
AREAS = {"marvin": "System · Marvin", "social": "System · Social"}
CORE_LABELS_PREFIX = "System · "
WORKFLOW_SKILL_MAX_LINES = 20  # Rule 3: a skill that calls the workflow tools stays this short
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_AI_WRITERS = ("compose_entry", "revise_entry")
_NEGATION = re.compile(r"\b(not|never|don'?t|instead|no)\b", re.IGNORECASE)
_WORKFLOW_TOOLS = ("draft_workflow", "workflow_authoring_guide")


@dataclass(frozen=True)
class SystemPlaybook:
    name: str
    description: str
    body: str
    source: str  # SOURCE_CORE | SOURCE_PLUGIN
    label: str  # "System · Marvin", "System · S3 storage"
    owner: str  # the area ("social") or the plugin's slug ("s3"): what the name starts with
    version: str
    hash: str
    manual_only: bool = True
    allowed_tools: str = ""
    files: tuple[tuple[str, str], ...] = ()  # (relative path, text), by path
    warnings: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return ID_PREFIX + self.name

    def file(self, path: str) -> str | None:
        return next((text for p, text in self.files if p == path), None)


@dataclass(frozen=True)
class Skipped:
    """A system Playbook that was not taken (or a repeated name), for the platform admin page's "Couldn't load" list."""

    name: str
    label: str
    reason: str


@dataclass(frozen=True)
class SystemCatalog:
    playbooks: dict[str, SystemPlaybook] = field(default_factory=dict)
    skipped: tuple[Skipped, ...] = ()


@dataclass(frozen=True)
class Declared:
    """One declaration before it is checked: where it came from and its payload (``{"skill_md", "files"}``)."""

    slug: str  # the declared name
    payload: dict
    source: str
    label: str
    owner: str
    version: str


def is_system_id(playbook_id: str | None) -> bool:
    return str(playbook_id or "").startswith(ID_PREFIX)


# ── Lint ─────────────────────────────────────────────────────────────────────


def lint(doc, payload: dict) -> tuple[list[str], list[str]]:
    """``(refusals, warnings)`` for a system Playbook: the Rules a program can check (the manual's "System Playbooks" page)."""
    refusals: list[str] = []
    warnings: list[str] = []
    tools = split_tools(doc.allowed_tools)
    for tool in tools:
        if tool in _AI_WRITERS:
            refusals.append(f"allowed-tools '{tool}': a system Playbook writes drafts itself (create_draft / update_draft)")
    texts = {"SKILL.md": payload["skill_md"], **(payload.get("files") or {})}
    for path, text in texts.items():
        for token in sorted(set(_UUID.findall(text))):
            refusals.append(f"{path} has the id '{token}'; name things by slug, ids differ in every workspace")
    lines = [line for line in doc.body.split("\n") if line.strip()]
    if any(t in doc.body for t in _WORKFLOW_TOOLS) and len(lines) > WORKFLOW_SKILL_MAX_LINES:
        refusals.append(
            f"it is a workflow-authoring skill of {len(lines)} lines; workflow authoring stays with workflow_authoring_guide and the Builder "
            f"(a skill may only call them, in at most {WORKFLOW_SKILL_MAX_LINES} lines)"
        )
    if tools:
        warnings.append("allowed-tools is set: it limits the agent's tools while this Playbook is loaded")
    for line in doc.body.split("\n"):
        if any(w in line for w in _AI_WRITERS) and not _NEGATION.search(line):
            warnings.append(f"the body points at compose_entry / revise_entry ('{line.strip()[:60]}'); write the text yourself")
    return refusals, warnings


def check(declared: Declared, *, prefix: str) -> SystemPlaybook | str:
    """The checked Playbook, or the reason it can't be taken."""
    problem = payload_problem(declared.payload, declared.slug)
    if problem:
        return problem
    text = declared.payload["skill_md"]
    doc = parse_skill_md(text)
    if not doc.name.startswith(prefix):
        return f"the name '{doc.name}' must start with '{prefix}'"
    refusals, warnings = lint(doc, declared.payload)
    if refusals:
        return refusals[0]
    manual_only = doc.manual_only or not declares_invocation(text)
    files = tuple(sorted((declared.payload.get("files") or {}).items()))
    data = {**doc.to_entry_data(), "manual_only": manual_only}
    from marvin.services.playbooks.blueprint import sha

    return SystemPlaybook(
        name=doc.name,
        description=doc.description,
        body=doc.body,
        source=declared.source,
        label=declared.label,
        owner=declared.owner,
        version=declared.version,
        hash=playbook_hash(data, {p: sha(t) for p, t in files}),
        manual_only=manual_only,
        allowed_tools=doc.allowed_tools,
        files=files,
        warnings=tuple(warnings),
    )


# ── Reading the packages ─────────────────────────────────────────────────────


def _read_folder(folder) -> dict | str:
    """``{"skill_md", "files"}`` of a skill folder in package data, or why it can't be read."""
    skill = None
    files: dict[str, str] = {}

    def walk(node, prefix=""):
        nonlocal skill
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            path = f"{prefix}{child.name}"
            if child.is_dir():
                walk(child, f"{path}/")
                continue
            try:
                text = child.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"'{path}' is not UTF-8 text") from None
            if path == "SKILL.md":
                skill = text
            else:
                files[posixpath.normpath(path)] = text

    try:
        walk(folder)
    except ValueError as e:
        return str(e)
    return {"skill_md": skill, "files": files} if skill is not None else "no SKILL.md"


def core_declarations(root=None) -> tuple[list[Declared], list[Skipped]]:
    """Every skill folder under ``system_playbooks/<area>/<name>/`` in Marvin's own package (or ``root``, a ``Traversable``)."""
    from marvin import __version__

    root = root if root is not None else resources.files("marvin").joinpath("system_playbooks")
    found: list[Declared] = []
    skipped: list[Skipped] = []
    if not root.is_dir():
        return found, skipped
    for area in sorted(root.iterdir(), key=lambda c: c.name):
        if not area.is_dir() or area.name.startswith((".", "_")):
            continue
        label = AREAS.get(area.name)
        for folder in sorted(area.iterdir(), key=lambda c: c.name):
            if not folder.is_dir() or folder.name.startswith((".", "_")):
                continue
            if label is None:
                skipped.append(
                    Skipped(folder.name, f"{CORE_LABELS_PREFIX}{area.name}", f"'{area.name}' is not a system Playbook area ({', '.join(AREAS)})")
                )
                continue
            payload = _read_folder(folder)
            if isinstance(payload, str):
                skipped.append(Skipped(folder.name, label, payload))
                continue
            found.append(Declared(folder.name, payload, SOURCE_CORE, label, area.name, __version__))
    return found, skipped


def _declared_from_blueprints(blueprints, *, label: str, owner: str, version: str) -> list[Declared]:
    return [
        Declared(
            getattr(b, "slug", ""),
            getattr(b, "payload", None),
            SOURCE_PLUGIN,
            label,
            owner,
            version,
        )
        for b in blueprints or ()
    ]


def _provider_prefix(slug: str) -> str:
    return f"{str(slug).replace('_', '-')}-"


def plugin_declarations() -> list[tuple[Declared, str]]:
    """``(declaration, required prefix)`` for every installed provider and storage / AI plugin that ships system Playbooks. Each
    registry is read only when its package is importable, so core runs without the SDK."""
    found: list[tuple[Declared, str]] = []
    try:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if INTEGRATIONS_AVAILABLE:
            from marvin_integration_sdk import INTEGRATION_REGISTRY

            from marvin.services.integrations.loader import load_providers, source_of

            load_providers()
            for slug in sorted(INTEGRATION_REGISTRY):
                provider = INTEGRATION_REGISTRY[slug]
                blueprints = getattr(provider, "system_playbooks", ())
                if blueprints:
                    version = (source_of(slug) or {}).get("version") or ""
                    label = f"{CORE_LABELS_PREFIX}{provider.name}"
                    found += [(d, _provider_prefix(slug)) for d in _declared_from_blueprints(blueprints, label=label, owner=slug, version=version)]
    except Exception as e:  # noqa: BLE001 — a broken plugin never takes the catalog down
        logger.warning("system playbooks: could not read the integration providers: %s", e)
    for kind, reader in (("storage", _storage_plugins), ("AI provider", _ai_plugins)):
        try:
            for slug, plugin, version in reader():
                blueprints = getattr(plugin, "playbooks", ())
                if blueprints:
                    label = f"{CORE_LABELS_PREFIX}{plugin.name}"
                    found += [(d, _provider_prefix(slug)) for d in _declared_from_blueprints(blueprints, label=label, owner=slug, version=version)]
        except Exception as e:  # noqa: BLE001
            logger.warning("system playbooks: could not read the %s plugins: %s", kind, e)
    return found


def _version_of(reports, slug: str) -> str:
    return next((r.version or "" for r in reports if r.ok and slug in r.slugs), "")


def _storage_plugins():
    from marvin.services.storage import registry

    reports = registry.load_plugins()
    return [(slug, plugin, _version_of(reports, slug)) for slug, plugin in sorted(registry.plugins().items())]


def _ai_plugins():
    from marvin.services.ai import registry

    reports = registry.load_plugins()
    return [(slug, plugin, _version_of(reports, slug)) for slug, plugin in sorted(registry.plugins().items())]


def build(core: tuple[list[Declared], list[Skipped]], plugins: list[tuple[Declared, str]]) -> SystemCatalog:
    """The catalog from declarations in source order (core, then the plugins as given). The first source to use a name keeps it."""
    taken: dict[str, SystemPlaybook] = {}
    skipped: list[Skipped] = list(core[1])
    for declared, prefix in [(d, f"{d.owner}-") for d in core[0]] + list(plugins):
        got = check(declared, prefix=prefix) if isinstance(declared.payload, dict) else "the declaration has no payload"
        if isinstance(got, str):
            skipped.append(Skipped(declared.slug, declared.label, got))
            logger.warning("system playbook %s (%s) skipped: %s", declared.slug, declared.label, got)
            continue
        if got.name in taken:
            skipped.append(Skipped(got.name, declared.label, f"the name is already used by {taken[got.name].label}"))
            logger.warning("system playbook %s (%s) skipped: name already used by %s", got.name, declared.label, taken[got.name].label)
            continue
        taken[got.name] = got
    return SystemCatalog(dict(sorted(taken.items())), tuple(skipped))


@lru_cache(maxsize=1)
def catalog() -> SystemCatalog:
    """Every system Playbook of the installed packages, built once per process (after the plugin registries load)."""
    return build(core_declarations(), plugin_declarations())


def reset() -> None:
    """Forget what was read, so the next call reads the packages again (tests; nothing hot-reloads in production)."""
    catalog.cache_clear()


def system_playbooks() -> dict[str, SystemPlaybook]:
    return catalog().playbooks


def system_playbook(name: str) -> SystemPlaybook | None:
    return system_playbooks().get(str(name or "").strip().lower())


def name_clash_message(name: str) -> str | None:
    """Why a workspace Playbook may not take ``name`` (it is an installed system Playbook's), else None."""
    found = system_playbook(name)
    if found is None:
        return None
    return f"'{found.name}' is a system Playbook ({found.label}) and is read-only: copy it instead (Playbooks > System > Copy)."


# ── Switches and visibility ──────────────────────────────────────────────────


def off_here(session, group_id) -> list[str]:
    """The names this workspace switched off (kept even when no longer installed)."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    return [str(n) for n in (getattr(row, "system_playbooks_off", None) or [])]


def off_server(session) -> list[str]:
    from marvin.services.platform_settings import PlatformSettingsService

    return [str(n) for n in ((PlatformSettingsService(session).get(SERVER_KEY) or {}).get("off") or [])]


def _workspace_playbooks(session, group_id):
    """``(slug, status, metadata)`` of the workspace's Playbook entries outside the Trash."""
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import playbook_type_id

    type_id = playbook_type_id(session, group_id)
    if type_id is None:
        return []
    return (
        session.query(Entries.slug, Entries.status, Entries.metadata_json)
        .filter(Entries.group_id == group_id, Entries.entry_type_id == type_id, Entries.status != "trashed")
        .all()
    )


@dataclass(frozen=True)
class State:
    playbook: SystemPlaybook
    state: str  # "on" | "off" | "off_server" | "hidden" | "replaced"
    detail: str = ""
    enabled_here: bool = True  # this workspace's own switch, whatever the platform's is


def system_states(session, group_id) -> list[State]:
    """Every installed system Playbook with whether this workspace gets it and why not (the Playbooks page's System section)."""
    found = system_playbooks()
    if not found:
        return []
    here, server = set(off_here(session, group_id)), set(off_server(session))
    mine = _workspace_playbooks(session, group_id)
    shadowing = {slug for slug, status, _ in mine if status == "published"}
    replaced = {str(((meta or {}).get(COPIED_FROM) or {}).get("name") or ""): slug for slug, status, meta in mine if status == "published"}
    out = []
    for name, p in found.items():
        if name in server:
            out.append(State(p, "off_server", "Off for this platform", name not in here))
        elif name in here:
            out.append(State(p, "off", "Off for this workspace", False))
        elif name in shadowing:
            out.append(State(p, "hidden", f"Hidden: your Playbook {name} has this name"))
        elif name in replaced:
            out.append(State(p, "replaced", f"Replaced by your copy, {replaced[name]}"))
        else:
            out.append(State(p, "on"))
    return out


def visible_system(session, group_id) -> list[SystemPlaybook]:
    """The system Playbooks this workspace gets: installed, minus the server's and the workspace's switches, a workspace Playbook that
    has the name, and a published copy."""
    return [s.playbook for s in system_states(session, group_id) if s.state == "on"]


def switch_here(session, group_id, name: str, enabled: bool) -> list[str]:
    """Switch one system Playbook on or off for a workspace (committed); returns the workspace's off list. Unknown names are kept."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    if row is None:
        row = WorkspaceAISettingsModel(session=session, group_id=group_id)
        session.add(row)
    off = [n for n in (row.system_playbooks_off or []) if n != name]
    if not enabled:
        off.append(name)
    row.system_playbooks_off = sorted(set(off)) or None
    session.commit()
    return list(row.system_playbooks_off or [])


def switch_server(session, name: str, enabled: bool) -> list[str]:
    from marvin.services.platform_settings import PlatformSettingsService

    service = PlatformSettingsService(session)
    off = {n for n in off_server(session) if n != name}
    if not enabled:
        off.add(name)
    service.set(SERVER_KEY, {"off": sorted(off)})
    return sorted(off)


def switched_off_counts(session) -> dict[str, int]:
    """How many workspaces switched each system Playbook off (the platform admin page)."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    counts: dict[str, int] = {}
    for (off,) in session.query(WorkspaceAISettingsModel.system_playbooks_off).filter(WorkspaceAISettingsModel.system_playbooks_off.isnot(None)):
        for name in set(off or []):
            counts[str(name)] = counts.get(str(name), 0) + 1
    return counts


__all__ = [
    "AREAS",
    "COPIED_FROM",
    "ID_PREFIX",
    "SystemPlaybook",
    "SystemCatalog",
    "build",
    "catalog",
    "check",
    "is_system_id",
    "lint",
    "name_clash_message",
    "reset",
    "system_playbook",
    "system_playbooks",
    "system_states",
    "visible_system",
]
