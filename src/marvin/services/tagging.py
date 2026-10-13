"""Attach/detach a shared-vocabulary Tag to any taggable entity — entry, asset, or resource.

Tags are one workspace vocabulary (the ``tags`` table) shared across three junctions
(``entry_tags`` / ``asset_tags`` / ``resource_tags``). This is the single place that links a tag to
any of them: find-or-create the tag on attach, link/unlink via the right junction (idempotent), and
emit the entity-appropriate event so automations can react. EntryService.attach_tag/detach_tag
delegate here; the registry's attach_tag/detach_tag tools call it with an ``entity_type``.
"""

from marvin.core.root_logger import get_logger
from marvin.repos.all_repositories import get_repositories
from marvin.services.event_bus_service.event_types import (
    EventAssetData,
    EventEntryData,
    EventOperation,
    EventResourceData,
    EventTypes,
)

logger = get_logger("tagging")

TAGGABLE = ("entry", "asset", "resource")


def _spec(entity_type: str):
    """(JunctionModel, fk_column, EntityModel, attach_event, detach_event) for a taggable type."""
    from marvin.db.models.platform.asset_tags import AssetTags
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_tags import EntryTags
    from marvin.db.models.platform.resource_tags import ResourceTags
    from marvin.db.models.platform.resources import Resources
    from marvin.db.models.platform.tags import Tags  # noqa: F401 — imported for the detach resolver

    return {
        # entries have dedicated tag events; assets/resources reuse their generic *_updated event.
        "entry": (EntryTags, "entry_id", Entries, EventTypes.entry_tag_attached, EventTypes.entry_tag_detached),
        "asset": (AssetTags, "asset_id", Assets, EventTypes.asset_updated, EventTypes.asset_updated),
        "resource": (ResourceTags, "resource_id", Resources, EventTypes.resource_updated, EventTypes.resource_updated),
    }.get(entity_type)


def _resolve_existing_tag(session, group_id, tag_ref):
    from marvin.db.models.platform.tags import Tags

    return session.query(Tags).filter(Tags.group_id == group_id).filter((Tags.slug == str(tag_ref)) | (Tags.name == str(tag_ref))).first()


def link_tag(
    session, group_id, entity_type: str, entity_id, tag_ref, *, attach: bool, actor_id=None, event_bus=None, reaction_depth: int = 0
) -> str | None:
    """Attach (``attach=True``, find-or-creates the tag) or detach a tag from an entry/asset/resource.
    Idempotent — returns ``"attached"``/``"exists"`` or ``"detached"``/``"absent"``, or ``None`` when
    the entity (or, on detach, the tag) isn't found in this workspace."""
    spec = _spec(entity_type)
    if not spec or not entity_id:
        return None
    Junction, fk, Model, ev_attach, ev_detach = spec
    entity = session.get(Model, entity_id)
    if not entity or entity.group_id != group_id:
        return None

    if attach:
        tag = get_repositories(session, group_id=group_id).tags.find_or_create(str(tag_ref))
        if not tag:
            return None
        exists = session.query(Junction).filter(getattr(Junction, fk) == entity.id, Junction.tag_id == tag.id).first()
        if exists:
            return "exists"
        session.add(Junction(**{fk: entity.id, "tag_id": tag.id}))
        session.commit()
        _emit(session, group_id, entity_type, entity, tag, ev_attach, actor_id, event_bus, reaction_depth)
        return "attached"

    tag = _resolve_existing_tag(session, group_id, tag_ref)
    if not tag:
        return None
    deleted = session.query(Junction).filter(getattr(Junction, fk) == entity.id, Junction.tag_id == tag.id).delete()
    if not deleted:
        return "absent"
    session.commit()
    _emit(session, group_id, entity_type, entity, tag, ev_detach, actor_id, event_bus, reaction_depth)
    return "detached"


def _emit(session, group_id, entity_type, entity, tag, event_type, actor_id, event_bus, reaction_depth) -> None:
    """Dispatch the entity-appropriate event for a tag change. Best-effort — never breaks the write."""
    if event_bus is None:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)

    group = get_repositories(session, group_id=group_id).groups.get_one(group_id)
    workspace_name = group.name if group else None
    verb = (
        "attached to"
        if "attached" in getattr(event_type, "name", "")
        else ("detached from" if "detached" in getattr(event_type, "name", "") else "on")
    )

    if entity_type == "entry":
        doc = EventEntryData(
            operation=EventOperation.update,
            entry_id=entity.id,
            entry_title=entity.title,
            entry_type=entity.entry_type.slug if entity.entry_type else None,
            workspace_id=group_id,
            workspace_name=workspace_name,
            author_id=actor_id,
        )
        message = f"Tag '{tag.name}' {verb} entry '{entity.title}'"
    elif entity_type == "asset":
        doc = EventAssetData(
            operation=EventOperation.update,
            asset_id=entity.id,
            slug=entity.slug,
            name=entity.name,
            mime_type=entity.mime_type,
            asset_type=entity.asset_type,
            storage_key=entity.storage_key,
            workspace_id=group_id,
            workspace_name=workspace_name,
            uploader_id=actor_id,
        )
        message = f"Tag '{tag.name}' {verb} asset '{entity.name}'"
    else:  # resource
        doc = EventResourceData(
            operation=EventOperation.update,
            resource_id=entity.id,
            resource_name=entity.name,
            resource_slug=entity.slug,
            resource_type=entity.resource_type,
            workspace_id=group_id,
            workspace_name=workspace_name,
        )
        message = f"Tag '{tag.name}' {verb} resource '{entity.name}'"

    try:
        event_bus.dispatch(
            integration_id="tagging",
            group_id=group_id,
            event_type=event_type,
            document_data=doc,
            message=message,
            user_id=actor_id,
            entity_id=entity.id,
            entity_type=entity_type,
            reaction_depth=reaction_depth,
        )
    except Exception as e:  # noqa: BLE001 — event dispatch is best-effort
        logger.error(f"Failed to dispatch {getattr(event_type, 'name', event_type)} for {entity_type}: {e}", exc_info=True)
