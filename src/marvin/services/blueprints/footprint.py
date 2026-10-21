"""An integration's footprint: everything its blueprints installed in a workspace.

Rows made by a blueprint carry ``source_integration_id`` (see ``InstalledByMixin``), so each kind is one
filtered select and the five of them go to the database as a single UNION ALL. Entry-type fields and form
settings are different: ``entry_fields`` blueprints change an existing row and leave no mark on it, so the
only honest answer is "the integration's field blueprints whose fields and settings are all in place on the
type now" (the same test the card's ticks use). A workspace that added the same fields by hand reads the same.
"""

from dataclasses import dataclass

import sqlalchemy as sa

from marvin.schemas.platform.blueprints import Blueprint

from .apply import BlueprintParameterError, _fields_target, _missing_fields, _missing_submission, resolve_parameters, substitute
from .catalog import list_blueprints

#: The kinds listed, keyed as the API names them. Order is the order a card shows them in.
KINDS = ("workflows", "incoming_webhooks", "outgoing_webhooks", "scheduled_tasks", "collections")


@dataclass(frozen=True)
class FootprintItem:
    id: object
    name: str
    enabled: bool | None  # None: the kind has no on/off (collections)


@dataclass(frozen=True)
class FieldChange:
    entry_type_slug: str
    entry_type_name: str
    label: str


def _selects(group_id, integration_id):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    sources = {
        "workflows": WorkspaceAutomationModel,
        "incoming_webhooks": WorkspaceIncomingWebhookModel,
        "outgoing_webhooks": GroupWebhooksModel,
        "scheduled_tasks": ScheduledTaskModel,
        "collections": Collections,
    }
    for kind, model in sources.items():
        enabled = model.enabled if hasattr(model, "enabled") else sa.null()
        yield sa.select(
            sa.literal(kind).label("kind"), model.id.label("id"), sa.func.coalesce(model.name, "").label("name"), enabled.label("enabled")
        ).where(model.group_id == group_id, model.source_integration_id == integration_id)


def installed_items(session, group_id, integration_id) -> dict[str, list[FootprintItem]]:
    """Every row this integration installed in the workspace, by kind: one query."""
    union = sa.union_all(*_selects(group_id, integration_id)).subquery()
    rows = session.execute(sa.select(union).order_by(union.c.kind, sa.func.lower(union.c.name), union.c.name)).all()
    found: dict[str, list[FootprintItem]] = {kind: [] for kind in KINDS}
    for kind, id_, name, enabled in rows:
        found[kind].append(FootprintItem(id=id_, name=name, enabled=None if enabled is None else bool(enabled)))
    return found


def field_changes(session, group_id, integration_id, provider: str, blueprints: list[Blueprint] | None = None) -> list[FieldChange]:
    """The entry types this provider's ``entry_fields`` blueprints have fully applied to (see the module note)."""
    if blueprints is None:
        blueprints = list_blueprints(kind="entry_fields", source=provider)
    changes: dict[str, FieldChange] = {}
    for blueprint in blueprints:
        if blueprint.kind != "entry_fields":
            continue
        try:
            params = resolve_parameters(session, group_id, blueprint, None)
        except BlueprintParameterError:
            continue  # a parameter with no default and nothing chosen: can't tell which type it means
        entry_type = _fields_target(session, group_id, blueprint, params)
        if entry_type is None or _missing_fields(entry_type, blueprint, params) or _missing_submission(entry_type, blueprint):
            continue
        payload = blueprint.payload or {}
        declared_fields = substitute(payload.get("fields") or [], params)
        verb = "Added fields to" if declared_fields else "Set form settings on"
        label = f"{verb} {entry_type.name}"
        # One type can be touched by several blueprints; say it once, with the strongest verb.
        previous = changes.get(entry_type.slug)
        if previous is None or (declared_fields and previous.label.startswith("Set form")):
            changes[entry_type.slug] = FieldChange(entry_type.slug, entry_type.name, label)
    return sorted(changes.values(), key=lambda c: c.entry_type_name.lower())
