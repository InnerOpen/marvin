"""Packages: install, preview, group, export, switch on and remove a labelled bundle of blueprints.

A package (`schemas/platform/packages.py`) is a list of blueprints under one name. Installing applies them with `apply_many`, so the rules
are the blueprints' own: create what is missing, never overwrite what exists, and everything that acts when on starts **disabled**. Each
row created is stamped with the package's slug (`source_package`), which is what groups it on the Workflows page. The whole manifest is kept
so the package can be downloaded again as it was installed.

Nothing here commits, except a Playbook (which brings files, so its writers commit): the caller commits the rest once it has the result, and a
preview rolls its work back instead and only checks a Playbook.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.orm.attributes import flag_modified

from marvin.core.root_logger import get_logger
from marvin.schemas.platform.blueprints import Blueprint, BlueprintApplyResult
from marvin.schemas.platform.packages import (
    MAX_MANIFEST_BYTES,
    PackageEnableResult,
    PackageExportRequest,
    PackageItem,
    PackageManifest,
    PackageRead,
    PackageResult,
)
from marvin.services.playbooks import PLAYBOOK_STATUS
from marvin.services.playbooks.blueprint import PROVENANCE_KEY

from .apply import apply_many

logger = get_logger(__name__)

#: Columns an entry type / collection blueprint may carry out of this workspace's own rows. Ids, the workspace and timestamps are not here.
ENTRY_TYPE_COLUMNS = (
    "name", "icon", "color", "description", "sort_order", "is_rendered", "schema_json", "rendering_json", "capabilities_json", "recipe_json",
    "page_url_pattern",
)  # fmt: skip
COLLECTION_COLUMNS = (
    "name",
    "description",
    "icon",
    "color",
    "sort_order",
    "is_smart",
    "smart_rules",
    "target_type",
    "is_public",
    "in_sidebar",
    "metadata_json",
)


#: What a Playbook in a package does on install, said where the person reads the preview.
PLAYBOOK_NOTE = "arrives as a draft; read it and publish it on the Playbooks page before agents can use it"


class PackageError(ValueError):
    """Something wrong with the package or the request, in words the person can act on."""


def _models() -> dict:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return {
        "workflow": WorkspaceAutomationModel,
        "collection": Collections,
        "scheduled_task": ScheduledTaskModel,
        "incoming_webhook": WorkspaceIncomingWebhookModel,
    }


def _package_row(session, group_id, slug: str):
    from marvin.db.models.groups.packages import WorkspacePackageModel

    return session.query(WorkspacePackageModel).filter_by(group_id=group_id, slug=slug).first()


# --- reading a file ---------------------------------------------------------------------------------------------------------------------


def parse_manifest(raw: str | bytes | dict) -> PackageManifest:
    """A package file (or its parsed JSON) as a manifest, or a PackageError saying what is wrong with it."""
    if isinstance(raw, dict):
        data = raw
        if len(json.dumps(raw)) > MAX_MANIFEST_BYTES:
            raise PackageError(f"the package is larger than {MAX_MANIFEST_BYTES // 1_000_000} MB")
    else:
        if len(raw) > MAX_MANIFEST_BYTES:
            raise PackageError(f"the package is larger than {MAX_MANIFEST_BYTES // 1_000_000} MB")
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise PackageError(f"this is not a package file (not valid JSON: {e})") from e
    if not isinstance(data, dict):
        raise PackageError("this is not a package file (expected a JSON object)")
    try:
        return PackageManifest.model_validate(data)
    except ValidationError as e:
        raise PackageError("; ".join(_readable(err) for err in e.errors()[:6])) from e


def _readable(err: dict) -> str:
    where = ".".join(str(part) for part in err["loc"] if part != "__root__")
    return f"{where}: {err['msg']}".removeprefix("Value error, ") if where else err["msg"].removeprefix("Value error, ")


# --- preview and install ----------------------------------------------------------------------------------------------------------------


def workflow_summary(definition: dict | None) -> str:
    """When a workflow runs and what its steps are, in one line, so whoever installs it can read what they would be switching on."""
    definition = definition or {}
    trigger = definition.get("trigger") or {}
    kind = trigger.get("type")
    when = {"manual": "run by hand", "schedule": "on a schedule"}.get(kind) or (
        f"on {trigger.get('event')}" if trigger.get("event") else (kind or "no trigger")
    )
    steps = [str(a.get("kind") or "step") for a in definition.get("actions") or []]
    return f"{when}: {', '.join(steps)}" if steps else when


def _item(blueprint: Blueprint, result: BlueprintApplyResult, *, preview: bool) -> PackageItem:
    if result.created:
        status = "create" if preview else "created"
    elif "left as it is" in (result.detail or ""):
        status = "exists"
    else:
        status = "blocked"
    summary = workflow_summary((blueprint.payload or {}).get("definition")) if blueprint.kind == "workflow" else ""
    if blueprint.kind == "playbook":
        summary = PLAYBOOK_NOTE
    return PackageItem(
        slug=result.slug, kind=blueprint.kind, name=result.name or blueprint.name, status=status, detail=result.detail or "", summary=summary
    )


def _result(manifest: PackageManifest, results: list[BlueprintApplyResult], *, preview: bool) -> PackageResult:
    by_key = {(b.kind, b.slug): b for b in manifest.blueprints}
    items = [_item(by_key[(r.kind, r.slug)], r, preview=preview) for r in results if (r.kind, r.slug) in by_key]
    made = ("create", "created")
    return PackageResult(
        package=manifest.slug,
        name=manifest.name,
        items=items,
        created=sum(i.status in made for i in items),
        existing=sum(i.status == "exists" for i in items),
        blocked=sum(i.status == "blocked" for i in items),
    )


def preview(session, group_id, manifest: PackageManifest, actor_id=None) -> PackageResult:
    """What installing would do, per blueprint. Applies for real inside the transaction and rolls it back, so the answer is exactly what an
    install would do (requirements, existing slugs, a workflow that fails validation) and nothing is left behind. A Playbook is the one kind
    whose apply commits, so it is only checked here (is the name free?), never made."""
    rest = [b for b in manifest.blueprints if b.kind != "playbook"]
    results = apply_many(session, group_id, rest, actor_id=actor_id, event_bus=None, package=manifest.slug)
    results += [_playbook_outcome(session, group_id, b) for b in manifest.blueprints if b.kind == "playbook"]
    outcome = _result(manifest, results, preview=True)
    session.rollback()
    return outcome


def _playbook_outcome(session, group_id, blueprint: Blueprint) -> BlueprintApplyResult:
    """What installing this Playbook would do, from the same checks the install makes before it creates anything."""
    from .playbook_apply import applied_row, blueprint_conflict

    result = BlueprintApplyResult(slug=blueprint.slug, kind="playbook", created=False, name=blueprint.name)
    if applied_row(session, group_id, blueprint) is not None:
        result.detail = f"a playbook with slug '{blueprint.slug}' already exists — left as it is"
    elif conflict := blueprint_conflict(session, group_id, blueprint):
        result.detail = conflict
    else:
        result.created = True
    return result


def install(session, group_id, manifest: PackageManifest, actor_id=None, event_bus=None) -> PackageResult:
    """Apply the blueprints (stamped with the package) and keep the manifest. Installing a slug again adds what is missing; what exists is left."""
    results = apply_many(session, group_id, manifest.blueprints, actor_id=actor_id, event_bus=event_bus, package=manifest.slug)
    _keep(session, group_id, manifest, actor_id)
    logger.info("Package '%s' installed to %s: %s", manifest.slug, group_id, [(r.kind, r.slug, r.created) for r in results])
    return _result(manifest, results, preview=False)


def _keep(session, group_id, manifest: PackageManifest, actor_id=None) -> None:
    from marvin.db.models.groups.packages import WorkspacePackageModel

    stored = manifest.model_dump(mode="json", by_alias=True)
    row = _package_row(session, group_id, manifest.slug)
    if row is None:
        session.add(
            WorkspacePackageModel(
                group_id=group_id,
                slug=manifest.slug,
                name=manifest.name,
                description=manifest.description,
                version=manifest.version,
                manifest=stored,
                created_by=actor_id,
            )
        )
    else:
        row.name, row.description, row.version, row.manifest = manifest.name, manifest.description, manifest.version, stored
    session.flush()


# --- listing, downloading, switching on, removing -----------------------------------------------------------------------------------------


def list_packages(session, group_id) -> list[PackageRead]:
    from marvin.db.models.groups.packages import WorkspacePackageModel

    models = _models()
    rows = session.query(WorkspacePackageModel).filter_by(group_id=group_id).order_by(WorkspacePackageModel.name).all()
    return [_read(session, group_id, row, models) for row in rows]


def _read(session, group_id, row, models: dict) -> PackageRead:
    def count(kind: str, *extra) -> int:
        model = models[kind]
        return session.query(model).filter(model.group_id == group_id, model.source_package == row.slug, *extra).count()

    playbooks = _playbooks_of(session, group_id, row.slug)
    return PackageRead(
        slug=row.slug,
        name=row.name,
        description=row.description,
        version=row.version,
        entry_types=[b["slug"] for b in (row.manifest or {}).get("blueprints", []) if b.get("kind") == "entry_type"],
        playbooks=[b["slug"] for b in (row.manifest or {}).get("blueprints", []) if b.get("kind") == "playbook"],
        playbooks_published=sum(1 for entry in playbooks if entry.status == PLAYBOOK_STATUS),
        workflows=count("workflow"),
        workflows_on=count("workflow", models["workflow"].enabled.is_(True)),
        collections=count("collection"),
        scheduled_tasks=count("scheduled_task"),
        incoming_webhooks=count("incoming_webhook"),
    )


def _playbooks_of(session, group_id, package_slug: str) -> list:
    """The Playbook entries this package made here: they carry its slug in their install record, a person's own Playbook of that name does not."""
    from marvin.services.playbooks import all_playbooks
    from marvin.services.playbooks.blueprint import PROVENANCE_KEY

    return [e for e in all_playbooks(session, group_id) if ((e.metadata_json or {}).get(PROVENANCE_KEY) or {}).get("package") == package_slug]


def manifest_of(session, group_id, slug: str) -> PackageManifest:
    row = _package_row(session, group_id, slug)
    if row is None:
        raise LookupError(f"No package '{slug}'.")
    return PackageManifest.model_validate(row.manifest)


def enable(session, group_id, slug: str, actor_id=None, event_bus=None) -> PackageEnableResult:
    """Switch on the package's workflows, the one deliberate step after an install (a workflow runs with its installer's privileges). Scheduled
    tasks and webhooks stay as they are: a task needs its schedule computed and a webhook needs a token minted, both done where they live."""
    from marvin.services.automation.toggle import VIA_UI, WORKFLOW, find, set_enabled

    if _package_row(session, group_id, slug) is None:
        raise LookupError(f"No package '{slug}'.")
    workflow = _models()["workflow"]
    on = already = 0
    for row in session.query(workflow).filter(workflow.group_id == group_id, workflow.source_package == slug).order_by(workflow.slug).all():
        target = find(session, group_id, WORKFLOW, row.id)
        if target is None:
            continue
        try:
            switched = set_enabled(session, group_id, target, True, actor_id=actor_id, via=VIA_UI, reason=f"package {slug}", event_bus=event_bus)
        except Exception as e:  # noqa: BLE001 - whatever stops a workflow switching on is what the person needs told
            raise PackageError(f"'{row.slug}' could not be switched on: {e}") from e
        on, already = on + switched, already + (not switched)
    return PackageEnableResult(switched_on=on, already_on=already)


def remove(session, group_id, slug: str) -> int:
    """Ungroup: the rows stay exactly as they are, in no package; the package record goes. Returns how many rows were ungrouped."""
    row = _package_row(session, group_id, slug)
    if row is None:
        raise LookupError(f"No package '{slug}'.")
    ungrouped = 0
    for model in _models().values():
        ungrouped += (
            session.query(model)
            .filter(model.group_id == group_id, model.source_package == slug)
            .update({"source_package": None}, synchronize_session=False)
        )
    for entry in _playbooks_of(session, group_id, slug):
        installed = {k: v for k, v in entry.metadata_json[PROVENANCE_KEY].items() if k != "package"}
        entry.metadata_json = {**entry.metadata_json, PROVENANCE_KEY: installed}
        flag_modified(entry, "metadata_json")
        ungrouped += 1
    session.delete(row)
    session.flush()
    return ungrouped


# --- building a package from what the workspace already has --------------------------------------------------------------------------------


def _carry(row, columns: tuple[str, ...]) -> dict:
    return {c: getattr(row, c) for c in columns if getattr(row, c, None) is not None}


def _blueprint_for(kind: str, row, payload: dict) -> Blueprint:
    return Blueprint(kind=kind, slug=row.slug, name=row.name, description=getattr(row, "description", None) or "", payload=payload)


def export(session, group_id, request: PackageExportRequest, actor_id=None) -> PackageManifest:
    """Bundle chosen workflows, entry types and collections of this workspace into a manifest. With `adopt`, also group the chosen workflows and
    collections into the package here (nothing is recreated) and keep the manifest. Ids and secret values are refused, not silently dropped."""
    models = _models()
    from marvin.db.models.platform.entry_types import EntryTypes

    blueprints: list[Blueprint] = []
    adopted = []

    def fetch(model, slug: str, noun: str):
        row = session.query(model).filter_by(group_id=group_id, slug=slug).first()
        if row is None:
            raise PackageError(f"there is no {noun} '{slug}' in this workspace")
        return row

    for slug in request.entry_types:
        row = fetch(EntryTypes, slug, "entry type")
        if row.is_system:
            raise PackageError(f"'{slug}' is a built-in entry type and is not packaged")
        blueprints.append(_blueprint_for("entry_type", row, _carry(row, ENTRY_TYPE_COLUMNS)))
    for slug in request.collections:
        row = fetch(models["collection"], slug, "collection")
        if row.is_system:
            raise PackageError(f"'{slug}' is a built-in collection and is not packaged")
        blueprints.append(_blueprint_for("collection", row, _carry(row, COLLECTION_COLUMNS)))
        adopted.append(row)
    for slug in request.workflows:
        row = fetch(models["workflow"], slug, "workflow")
        blueprints.append(_blueprint_for("workflow", row, {"name": row.name, "definition": row.definition or {}}))
        adopted.append(row)

    if not blueprints:
        raise PackageError("choose at least one workflow, entry type or collection")
    try:
        manifest = PackageManifest(
            slug=request.slug, name=request.name, description=request.description, version=request.version, blueprints=blueprints
        )
    except ValidationError as e:
        raise PackageError("; ".join(_readable(err) for err in e.errors()[:6])) from e

    if request.adopt:
        taken = [r.slug for r in adopted if r.source_package not in (None, request.slug)]
        if taken:
            raise PackageError(f"already in another package: {', '.join(taken)}")
        for row in adopted:
            row.source_package = request.slug
        _keep(session, group_id, manifest, actor_id)
    return manifest
