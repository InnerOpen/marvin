"""Published content changes queue a site rebuild on their own — no workflow, no manual call.

Regression: a new venue published and added to a collection never reached the static site, because
only the Square workflows ever asked for a rebuild.
"""

import uuid
from types import SimpleNamespace

from pytest import fixture
from sqlalchemy import delete

from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.event_bus_service.event_bus_listener import SiteRebuildReactionListener
from marvin.services.event_bus_service.event_types import EventTypes


@fixture
def site(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes
    from marvin.services.event_bus_service.event_types import WebhookMode

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"sr-{gid.hex[:8]}", slug=f"sr-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    # The site's deploy hook: without one a rebuild builds nothing, so none is queued.
    db_session.add(
        GroupWebhooksModel(
            session=db_session,
            group_id=gid,
            name="Deploy",
            url="https://hooks.example.test/deploy",
            webhook_type=WebhookMode.event_driven,
            enabled=True,
            subscribed_events=["webhook_triggered"],
        )
    )
    et = EntryTypes(session=db_session, group_id=gid, name="Venue", slug="venue", schema_json={})
    # A submission type: its entries are never served, whatever their status (publishing_controller).
    signup = EntryTypes(
        session=db_session,
        group_id=gid,
        name="Newsletter",
        slug="newsletter",
        schema_json={},
        capabilities_json={"publishable": False, "submittable": True},
    )
    db_session.add_all([et, signup])
    db_session.flush()
    live = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Live", slug=f"live-{gid.hex[:6]}", status="published")
    draft = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Draft", slug=f"draft-{gid.hex[:6]}", status="draft")
    subscriber = Entries(session=db_session, group_id=gid, entry_type_id=signup.id, title="a@b.c", slug=f"sub-{gid.hex[:6]}", status="published")
    public = Collections(session=db_session, group_id=gid, name="Venues", slug="venues")
    private = Collections(session=db_session, group_id=gid, name="Confirmed subscribers", slug="confirmed", is_public=False)
    db_session.add_all([live, draft, subscriber, public, private])
    db_session.flush()
    db_session.add(EntryCollections(entry_id=live.id, collection_id=private.id))
    db_session.commit()
    yield SimpleNamespace(gid=gid, live=live.id, draft=draft.id, subscriber=subscriber.id, public=public.id, private=private.id)
    db_session.execute(delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == gid))
    # The request that opens a batch logs `site_rebuild_queued` against the workspace.
    db_session.query(EventLogModel).filter_by(workspace_id=gid).delete()
    db_session.query(EntryCollections).filter(EntryCollections.collection_id.in_([public.id, private.id])).delete()
    db_session.query(Collections).filter_by(group_id=gid).delete()
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(GroupPreferencesModel).filter_by(group_id=gid).delete()
    db_session.query(GroupWebhooksModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _event(event_type, entry_id=None, before=None, **data):
    document = SimpleNamespace(entry_id=entry_id, before=before or {}, **data)
    return SimpleNamespace(event_type=event_type, document_data=document, entity_id=entry_id, message=SimpleNamespace(body=f"{event_type.name}"))


def _collection_event(event_type, collection_id, **data):
    document = SimpleNamespace(collection_id=collection_id, **data)
    return SimpleNamespace(event_type=event_type, document_data=document, entity_id=collection_id, message=SimpleNamespace(body=event_type.name))


def _fire(gid, event):
    listener = SiteRebuildReactionListener(gid)
    if listener.get_subscribers(event):
        listener.publish_to_subscribers(event, ["site_rebuild"])


def _queued(db_session, gid) -> int:
    db_session.expire_all()
    row = db_session.query(SiteRebuildRequestModel).filter_by(group_id=gid).first()
    return row.request_count if row else 0


def test_publishing_queues_a_rebuild(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_published, site.live))
    assert _queued(db_session, site.gid) == 1


def test_a_published_entry_joining_a_collection_queues_a_rebuild(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_added_to_collection, site.live))
    assert _queued(db_session, site.gid) == 1


def test_a_draft_saved_or_moved_between_collections_does_not(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_updated, site.draft))
    _fire(site.gid, _event(EventTypes.entry_added_to_collection, site.draft))
    assert _queued(db_session, site.gid) == 0


def test_leaving_published_is_visible(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_updated, site.draft, before={"status": "published"}))
    _fire(site.gid, _event(EventTypes.entry_archived, site.draft))
    assert _queued(db_session, site.gid) == 2


def test_site_settings_and_shared_media_always_count(db_session, site):
    for event_type in (EventTypes.workspace_settings_changed, EventTypes.asset_updated, EventTypes.collection_updated):
        _fire(site.gid, _event(event_type))
    assert _queued(db_session, site.gid) == 3


def test_an_audit_settings_change_does_not_queue_a_rebuild(db_session, site):
    """Which event types the Event Log records is no part of any site."""
    _fire(site.gid, _event(EventTypes.workspace_settings_changed, changed_fields=["audit_overrides"]))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _event(EventTypes.workspace_settings_changed, changed_fields=["audit_overrides", "site_title"]))
    assert _queued(db_session, site.gid) == 1


def test_an_agent_edit_does_not_queue_a_rebuild(db_session, site):
    """No site renders an agent: every `agents.<slug>[.<field>]` an agent edit names is unseen."""
    for fields in (["agents.marvin.tool_policy"], ["agents.writer"], ["agents.writer.name", "agents.writer.tool_policy"]):
        _fire(site.gid, _event(EventTypes.workspace_settings_changed, changed_fields=fields))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _event(EventTypes.workspace_settings_changed, changed_fields=["agents.writer", "site_title"]))
    assert _queued(db_session, site.gid) == 1


def test_unrelated_events_are_ignored(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_created, site.live))  # published only when it says so
    _fire(site.gid, _event(EventTypes.webhook_triggered))  # the rebuild itself must never loop
    assert _queued(db_session, site.gid) == 0


# --- Maintenance no site can see: private records and collections not "Visible to sites" ---


def test_anything_done_to_a_non_publishable_entry_does_not_queue_a_rebuild(db_session, site):
    # Confirming a newsletter signup publishes it and files it under "Confirmed subscribers".
    for event_type in (
        EventTypes.entry_published,
        EventTypes.entry_updated,
        EventTypes.entry_added_to_collection,
        EventTypes.entry_tag_attached,
        EventTypes.entry_unpublished,
        EventTypes.entry_archived,
    ):
        _fire(site.gid, _event(event_type, site.subscriber, before={"status": "published"}))
    _fire(site.gid, _event(EventTypes.entry_deleted, uuid.uuid4(), entry_type="newsletter"))
    assert _queued(db_session, site.gid) == 0


def test_deleting_an_entry_of_a_publishable_type_still_queues_a_rebuild(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_deleted, uuid.uuid4(), entry_type="venue"))
    assert _queued(db_session, site.gid) == 1


def test_a_private_collection_membership_change_does_not_queue_a_rebuild(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_added_to_collection, site.live, collection_id=site.private))
    _fire(site.gid, _event(EventTypes.entry_removed_from_collection, site.live, collection_id=site.private))
    assert _queued(db_session, site.gid) == 0


def test_a_public_collection_membership_change_still_queues_a_rebuild(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_added_to_collection, site.live, collection_id=site.public))
    assert _queued(db_session, site.gid) == 1


def test_a_private_collection_updated_reordered_or_deleted_does_not_queue_a_rebuild(db_session, site):
    _fire(site.gid, _collection_event(EventTypes.collection_updated, site.private))  # visibility read from the row
    _fire(site.gid, _collection_event(EventTypes.collection_updated, site.private, is_public=False, before={}))
    _fire(site.gid, _collection_event(EventTypes.collection_deleted, uuid.uuid4(), is_public=False))  # row already gone
    assert _queued(db_session, site.gid) == 0


def test_a_public_collection_updated_still_queues_a_rebuild(db_session, site):
    _fire(site.gid, _collection_event(EventTypes.collection_updated, site.public))
    assert _queued(db_session, site.gid) == 1


def test_turning_visible_to_sites_off_or_on_queues_a_rebuild(db_session, site):
    _fire(site.gid, _collection_event(EventTypes.collection_updated, site.private, is_public=False, before={"is_public": True}))
    _fire(site.gid, _collection_event(EventTypes.collection_updated, site.public, is_public=True, before={"is_public": False}))
    assert _queued(db_session, site.gid) == 2


def test_a_published_entry_only_in_private_collections_still_queues_a_rebuild(db_session, site):
    # Entry endpoints serve it whatever collections it's in.
    _fire(site.gid, _event(EventTypes.entry_published, site.live))
    _fire(site.gid, _event(EventTypes.entry_updated, site.live))
    assert _queued(db_session, site.gid) == 2


def test_a_skip_is_logged_at_debug(db_session, site, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        _fire(site.gid, _event(EventTypes.entry_published, site.subscriber))
    assert any("Site rebuild skipped: entry_published" in r.getMessage() and r.levelno == logging.DEBUG for r in caplog.records)


def test_a_workspace_with_no_deploy_target_queues_nothing(db_session, site):
    """Nothing would build the site, so a content change queues no rebuild (and no "Site rebuild" toast)."""
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    db_session.query(GroupWebhooksModel).filter_by(group_id=site.gid).update({"enabled": False})
    db_session.commit()
    _fire(site.gid, _event(EventTypes.entry_published, site.live))
    assert _queued(db_session, site.gid) == 0


def test_the_workspace_can_turn_it_off(db_session, site):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).update({"site_auto_rebuild": False})
    db_session.commit()
    _fire(site.gid, _event(EventTypes.entry_published, site.live))
    assert _queued(db_session, site.gid) == 0


# --- What changed: the rebuild lists each change so the admin's toast can show (and link) it ---


def _entry_event(event_type, entry_id, gid, body):
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventEntryData, EventOperation

    data = EventEntryData(operation=EventOperation.update, entry_id=entry_id, entry_title="Live", workspace_id=gid)
    return Event(message=EventBusMessage.from_type(event_type, body), event_type=event_type, integration_id="test", document_data=data)


def _listed(db_session, gid) -> list[dict]:
    db_session.expire_all()
    return db_session.query(SiteRebuildRequestModel).filter_by(group_id=gid).one().changes


def test_an_entry_change_is_listed_with_the_entry_to_link_to(db_session, site):
    _fire(site.gid, _entry_event(EventTypes.entry_published, site.live, site.gid, "Entry 'Live' published"))

    assert _listed(db_session, site.gid) == [
        {"label": "Entry 'Live' published", "event": "entry_published", "entity_type": "entry", "entity_id": str(site.live)}
    ]


def test_a_message_that_does_not_name_the_entry_gets_its_title(db_session, site):
    _fire(site.gid, _entry_event(EventTypes.entry_tag_attached, site.live, site.gid, "Tag 'summer' attached"))

    assert _listed(db_session, site.gid)[0]["label"] == "Tag 'summer' attached — Live"


def test_the_first_change_logs_the_queued_rebuild_and_later_ones_join_it(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_published, site.live))
    _fire(site.gid, _event(EventTypes.entry_updated, site.live))

    db_session.expire_all()
    logged = db_session.query(EventLogModel).filter_by(workspace_id=site.gid, event_type="site_rebuild_queued").all()
    assert _queued(db_session, site.gid) == 2 and len(logged) == 1


# --- The producers record what the listener needs: which collection, and whether it was visible ---


class _SpyBus:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, *, event_type, document_data, **_):
        self.dispatched.append((event_type, document_data))


def test_membership_events_name_their_collection(db_session, site):
    from marvin.services.entries import EntryService

    bus = _SpyBus()
    EntryService(db_session, site.gid, event_bus=bus, integration_id="test").add_to_collection(site.subscriber, site.private)

    [(event_type, data)] = bus.dispatched
    assert (event_type, data.collection_id, data.collection_name) == (EventTypes.entry_added_to_collection, site.private, "Confirmed subscribers")


def _collections_controller(db_session, gid, bus):
    from marvin.routes.platform.collections_controller import CollectionsController

    ctl = object.__new__(CollectionsController)
    ctl.session, ctl.event_bus, ctl._repos = db_session, bus, None
    ctl.user = SimpleNamespace(
        id=None,
        active_group_id=gid,
        group_id=gid,
        platform_role=PlatformRole.NONE,
        get_workspace_role=lambda group_id: WorkspaceRole.EDITOR,  # editing a collection needs EDITOR
    )
    return ctl


def test_a_visibility_toggle_records_the_prior_visibility(db_session, site):
    from marvin.schemas.platform.collections import CollectionUpdate

    bus = _SpyBus()
    _collections_controller(db_session, site.gid, bus).update_collection(site.public, CollectionUpdate(is_public=False))

    [(_, data)] = bus.dispatched
    assert (data.is_public, data.before) == (False, {"is_public": True})


def test_an_edit_that_keeps_visibility_records_no_prior_visibility(db_session, site):
    from marvin.schemas.platform.collections import CollectionUpdate

    bus = _SpyBus()
    _collections_controller(db_session, site.gid, bus).update_collection(site.private, CollectionUpdate(description="Members only"))

    [(_, data)] = bus.dispatched
    assert (data.is_public, data.before) == (False, {})
