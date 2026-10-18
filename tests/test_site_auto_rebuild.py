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


def test_a_data_field_diff_changes_nothing_for_the_rebuild(db_session, site):
    # entry_updated now names type fields (`before.data`); only `before.status` and the entry's own status decide.
    diff = {"data": {"price": 5}}
    _fire(site.gid, _event(EventTypes.entry_updated, site.draft, before=diff))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _event(EventTypes.entry_updated, site.live, before=diff))
    assert _queued(db_session, site.gid) == 1


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
    _fire(site.gid, _event(EventTypes.entry_created, site.draft))  # a draft is nothing a site serves
    _fire(site.gid, _event(EventTypes.webhook_triggered))  # the rebuild itself must never loop
    _fire(site.gid, _event(EventTypes.entry_type_created))  # a type with no entries renders nothing
    assert _queued(db_session, site.gid) == 0


def test_an_entry_created_already_published_queues_a_rebuild(db_session, site):
    # EntryService.create sends only entry_created, even for status "published": no entry_published follows.
    _fire(site.gid, _event(EventTypes.entry_created, site.live))
    assert _queued(db_session, site.gid) == 1


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


def test_trashing_or_restoring_an_asset_or_resource_a_site_can_see_queues_a_rebuild(db_session, site):
    """Visible: attached to a published entry (or in a public collection, or the site logo). An asset only on a
    draft isn't — and an item the listener can't find counts, like a deleted one."""
    from marvin.db.models.platform import Assets, EntryAssets, EntryResources, Resources
    from marvin.db.models.users.users import Users

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=site.gid, username=f"u-{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.test", full_name="U", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip

    def asset(slug):
        a = Assets(
            session=db_session, group_id=site.gid, slug=slug, name=slug, original_filename=f"{slug}.png", filename=slug, extension="png",
            file_size=1, mime_type="image/png", asset_type="image", checksum="c", storage_provider="local",
            storage_key=f"k/{uuid.uuid4().hex}", uploaded_by=uid,
        )  # fmt: skip
        db_session.add(a)
        db_session.flush()
        return a.id

    on_live, on_draft = asset("on-live"), asset("on-draft")
    material = Resources(session=db_session, group_id=site.gid, slug="canvas", name="Canvas", resource_type="material", created_by=uid)
    db_session.add(material)
    db_session.flush()
    db_session.add_all(
        [
            EntryAssets(entry_id=site.live, asset_id=on_live, position=0),
            EntryAssets(entry_id=site.draft, asset_id=on_draft, position=0),
            EntryResources(entry_id=site.live, resource_id=material.id, position=0),
        ]
    )
    db_session.commit()
    try:

        def item_event(event_type, field, item_id):
            document = SimpleNamespace(**{field: item_id})
            return SimpleNamespace(event_type=event_type, document_data=document, entity_id=item_id, message=SimpleNamespace(body=event_type.name))

        _fire(site.gid, item_event(EventTypes.asset_trashed, "asset_id", on_draft))
        assert _queued(db_session, site.gid) == 0  # only a draft shows it
        _fire(site.gid, item_event(EventTypes.asset_trashed, "asset_id", on_live))
        _fire(site.gid, item_event(EventTypes.asset_restored, "asset_id", on_live))
        _fire(site.gid, item_event(EventTypes.resource_trashed, "resource_id", material.id))
        _fire(site.gid, item_event(EventTypes.resource_restored, "resource_id", uuid.uuid4()))  # can't tell: yes
        assert _queued(db_session, site.gid) == 4
    finally:
        db_session.rollback()
        db_session.query(EntryAssets).filter(EntryAssets.asset_id.in_([on_live, on_draft])).delete()
        db_session.query(EntryResources).filter(EntryResources.resource_id == material.id).delete()
        db_session.query(Assets).filter(Assets.group_id == site.gid).delete()
        db_session.query(Resources).filter(Resources.group_id == site.gid).delete()
        db_session.query(Users).filter(Users.id == uid).delete()
        db_session.commit()


def test_trashing_a_published_entry_queues_a_rebuild_and_a_draft_does_not(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_trashed, site.draft))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _event(EventTypes.entry_trashed, site.draft, before={"status": "published"}))
    assert _queued(db_session, site.gid) == 1


# --- T1: a rebuild only when something a site serves changes ---------------------------------------------


def _replay(db_session, site, bus, only=None) -> int:
    """Feed what a spy bus recorded to the listener, in order (only `only`, when given); how many requests it queued."""
    for event_type, data in bus.dispatched:
        if only is not None and event_type != only:
            continue
        entity_id = getattr(data, "entry_id", None) or getattr(data, "asset_id", None) or getattr(data, "resource_id", None)
        event = SimpleNamespace(event_type=event_type, document_data=data, entity_id=entity_id, message=SimpleNamespace(body=event_type.name))
        _fire(site.gid, event)
    return _queued(db_session, site.gid)


def _forget_requests(db_session, site) -> None:
    db_session.execute(delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == site.gid))
    db_session.commit()


def _entry_service(db_session, site, bus):
    from marvin.services.entries import EntryService

    return EntryService(db_session, site.gid, event_bus=bus, integration_id="test")


def _trashed_entry(db_session, site, slug, *, days_ago=10):
    from datetime import UTC, datetime, timedelta

    from marvin.db.models.platform import Entries, EntryTypes

    et = db_session.query(EntryTypes).filter_by(group_id=site.gid, slug="venue").one()
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    row = Entries(
        session=db_session, group_id=site.gid, entry_type_id=et.id, title=slug, slug=f"{slug}-{uuid.uuid4().hex[:6]}", status="trashed",
        metadata_json={"trash": {"trashed_at": when, "previous_status": "published"}},
    )  # fmt: skip
    db_session.add(row)
    db_session.commit()
    return row.id


def test_deleting_a_published_entry_queues_a_rebuild_and_a_draft_does_not(db_session, site):
    bus = _SpyBus()
    svc = _entry_service(db_session, site, bus)
    svc.delete(site.draft)
    assert [d.before for _, d in bus.dispatched] == [{"status": "draft"}]  # the row is gone, so the event says what it was
    assert _replay(db_session, site, bus) == 0
    bus.dispatched.clear()
    svc.delete(site.live)
    assert [d.before for _, d in bus.dispatched] == [{"status": "published"}]
    assert _replay(db_session, site, bus) == 1


def test_a_delete_event_that_records_no_status_still_queues_a_rebuild(db_session, site):
    # Can't tell (an older logged event, a workflow's emit_event): a spare build beats a stale site.
    _fire(site.gid, _event(EventTypes.entry_deleted, uuid.uuid4(), entry_type="venue"))
    _fire(site.gid, _event(EventTypes.entry_deleted, uuid.uuid4(), before={"status": "trashed"}, entry_type="venue"))  # can tell: no
    assert _queued(db_session, site.gid) == 1


def test_emptying_the_trash_queues_no_rebuild(db_session, site):
    from marvin.services.entries import trash

    ids = [_trashed_entry(db_session, site, "gone-a"), _trashed_entry(db_session, site, "gone-b")]
    bus = _SpyBus()
    assert trash.empty_trash(db_session, site.gid, event_bus=bus) == 2
    assert [t for t, _ in bus.dispatched] == [EventTypes.entry_deleted] * 2
    assert {d.entry_id for _, d in bus.dispatched} == set(ids)
    assert _replay(db_session, site, bus) == 0  # trashing a published entry already took it off the site


def test_the_nightly_auto_empty_queues_no_rebuild(db_session, site):
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.services.entries import trash

    _trashed_entry(db_session, site, "old-trash", days_ago=40)
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).one()
    prefs.trash_auto_empty_days = 30
    db_session.commit()
    bus = _SpyBus()
    assert trash.purge_expired(db_session, event_bus=bus).get(site.gid) == 1
    assert [t for t, _ in bus.dispatched] == [EventTypes.entry_deleted]
    assert _replay(db_session, site, bus) == 0


def test_trashing_a_published_entry_queues_a_rebuild_whichever_event_carries_it(db_session, site):
    bus = _SpyBus()
    _entry_service(db_session, site, bus).trash(site.live)
    assert EventTypes.entry_trashed in [t for t, _ in bus.dispatched]
    # The trashed event alone must do it: it can't lean on the entry_updated / entry_unpublished that come with it.
    assert _replay(db_session, site, bus, only=EventTypes.entry_trashed) == 1


def test_trashing_or_archiving_a_draft_queues_no_rebuild(db_session, site):
    bus = _SpyBus()
    svc = _entry_service(db_session, site, bus)
    svc.set_status(site.draft, "archived")
    svc.trash(site.draft)
    assert {EventTypes.entry_archived, EventTypes.entry_trashed} <= {t for t, _ in bus.dispatched}
    assert _replay(db_session, site, bus) == 0


def test_archiving_a_published_entry_queues_a_rebuild(db_session, site):
    bus = _SpyBus()
    _entry_service(db_session, site, bus).set_status(site.live, "archived")
    assert EventTypes.entry_archived in [t for t, _ in bus.dispatched]
    assert _replay(db_session, site, bus, only=EventTypes.entry_archived) == 1


def test_archiving_or_unpublishing_an_entry_that_was_not_published_does_nothing(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_archived, site.draft, before={"status": "draft"}))
    _fire(site.gid, _event(EventTypes.entry_unpublished, site.draft, before={"status": "review"}))
    assert _queued(db_session, site.gid) == 0


@fixture
def media(db_session, site):
    from marvin.db.models.platform import Assets, EntryAssets, EntryResources, Resources
    from marvin.db.models.users.users import Users

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=site.gid, username=f"u-{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.test", full_name="U", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip

    def asset(slug):
        a = Assets(
            session=db_session, group_id=site.gid, slug=slug, name=slug, original_filename=f"{slug}.png", filename=slug, extension="png",
            file_size=1, mime_type="image/png", asset_type="image", checksum="c", storage_provider="local",
            storage_key=f"k/{uuid.uuid4().hex}", uploaded_by=uid,
        )  # fmt: skip
        db_session.add(a)
        db_session.flush()
        return a.id

    def resource(slug):
        r = Resources(session=db_session, group_id=site.gid, slug=slug, name=slug, resource_type="material", created_by=uid)
        db_session.add(r)
        db_session.flush()
        return r.id

    ids = SimpleNamespace(
        asset_live=asset("a-live"), asset_draft=asset("a-draft"), asset_loose=asset("a-loose"),
        resource_live=resource("r-live"), resource_draft=resource("r-draft"), resource_loose=resource("r-loose"),
    )  # fmt: skip
    db_session.add_all(
        [
            EntryAssets(entry_id=site.live, asset_id=ids.asset_live, position=0),
            EntryAssets(entry_id=site.draft, asset_id=ids.asset_draft, position=0),
            EntryResources(entry_id=site.live, resource_id=ids.resource_live, position=0),
            EntryResources(entry_id=site.draft, resource_id=ids.resource_draft, position=0),
        ]
    )
    db_session.commit()
    yield ids
    db_session.rollback()
    db_session.query(EntryAssets).filter(EntryAssets.entry_id.in_([site.live, site.draft])).delete()
    db_session.query(EntryResources).filter(EntryResources.entry_id.in_([site.live, site.draft])).delete()
    db_session.query(Assets).filter(Assets.group_id == site.gid).delete()
    db_session.query(Resources).filter(Resources.group_id == site.gid).delete()
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.commit()


def _item_event(event_type, field, item_id, **data):
    document = SimpleNamespace(**{field: item_id}, **data)
    return SimpleNamespace(event_type=event_type, document_data=document, entity_id=item_id, message=SimpleNamespace(body=event_type.name))


def test_editing_an_asset_or_resource_queues_a_rebuild_only_when_a_site_can_see_it(db_session, site, media):
    for event_type, field, hidden in (
        (EventTypes.asset_updated, "asset_id", [media.asset_draft, media.asset_loose]),
        (EventTypes.resource_updated, "resource_id", [media.resource_draft, media.resource_loose]),
    ):
        for item_id in hidden:
            _fire(site.gid, _item_event(event_type, field, item_id))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _item_event(EventTypes.asset_updated, "asset_id", media.asset_live))
    _fire(site.gid, _item_event(EventTypes.resource_updated, "resource_id", media.resource_live))
    _fire(site.gid, _item_event(EventTypes.asset_updated, "asset_id", uuid.uuid4()))  # can't find it: yes
    assert _queued(db_session, site.gid) == 3


def test_editing_a_trashed_asset_queues_nothing_the_api_no_longer_serves_it(db_session, site, media):
    from datetime import UTC, datetime

    from marvin.db.models.platform import Assets

    db_session.query(Assets).filter_by(id=media.asset_live).update({"trashed_at": datetime.now(UTC)})
    db_session.commit()
    _fire(site.gid, _item_event(EventTypes.asset_updated, "asset_id", media.asset_live))
    assert _queued(db_session, site.gid) == 0


def test_an_asset_in_a_public_collection_is_visible(db_session, site, media):
    from marvin.db.models.platform import CollectionAssets

    db_session.add(CollectionAssets(asset_id=media.asset_loose, collection_id=site.public))
    db_session.commit()
    try:
        _fire(site.gid, _item_event(EventTypes.asset_updated, "asset_id", media.asset_loose))
        assert _queued(db_session, site.gid) == 1
    finally:
        db_session.query(CollectionAssets).filter_by(asset_id=media.asset_loose).delete()
        db_session.commit()


def _with_link_fields(db_session, site, media):
    """The venue type gets one field of each link type; the live entry holds the loose asset and resource in
    them (the asset in a list, the resource alone), the draft the same ones' siblings."""
    from marvin.db.models.platform import Entries, EntryTypes

    fields = [
        {"key": "gallery", "type": "asset-list"},
        {"key": "cover", "type": "asset"},
        {"key": "source", "type": "resource"},
        {"key": "sources", "type": "resource-list"},
        {"key": "note", "type": "text"},
    ]
    live = db_session.query(Entries).filter_by(id=site.live).one()
    db_session.query(EntryTypes).filter_by(id=live.entry_type_id).update({"schema_json": {"fields": fields}})
    return fields


def test_an_asset_or_resource_held_in_a_published_entrys_field_is_visible(db_session, site, media):
    from marvin.db.models.platform import Entries

    _with_link_fields(db_session, site, media)
    db_session.query(Entries).filter_by(id=site.live).update(
        {"data_json": {"gallery": [str(uuid.uuid4()), str(media.asset_loose).upper()], "source": str(media.resource_loose), "note": "x"}}
    )
    db_session.query(Entries).filter_by(id=site.draft).update(
        {"data_json": {"cover": str(media.asset_draft), "sources": [str(media.resource_draft)]}}
    )
    db_session.commit()
    # Trashing what only the live entry's fields hold changes the site; what only the draft's hold does not.
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", media.asset_draft))
    _fire(site.gid, _item_event(EventTypes.resource_trashed, "resource_id", media.resource_draft))
    assert _queued(db_session, site.gid) == 0
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", media.asset_loose))
    _fire(site.gid, _item_event(EventTypes.resource_trashed, "resource_id", media.resource_loose))
    assert _queued(db_session, site.gid) == 2


def test_an_id_in_a_field_that_is_not_a_link_or_on_a_private_type_does_not_count(db_session, site, media):
    from marvin.db.models.platform import Entries

    _with_link_fields(db_session, site, media)
    # In a text field (not a link), and in a published entry of a type the API never serves.
    db_session.query(Entries).filter_by(id=site.live).update({"data_json": {"note": str(media.asset_loose)}})
    db_session.query(Entries).filter_by(id=site.subscriber).update({"data_json": {"cover": str(media.asset_draft)}})
    db_session.commit()
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", media.asset_loose))
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", media.asset_draft))
    assert _queued(db_session, site.gid) == 0


def test_a_brand_or_share_image_value_naming_an_asset_makes_it_visible(db_session, site, media):
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform import Assets

    seal = db_session.query(Assets).filter_by(id=media.asset_loose).one()
    other = db_session.query(Assets).filter_by(id=media.asset_draft).one()
    db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).update(
        {"site_metadata_json": {"brand": {"seal": seal.slug, "colour": "#fff", "n": 3}, "seo": {"image": str(other.id)}}}
    )
    db_session.commit()
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", seal.id))
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", other.id))
    assert _queued(db_session, site.gid) == 2
    db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).update({"site_metadata_json": {"brand": {"colour": "#fff"}}})
    db_session.commit()
    db_session.execute(delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == site.gid))
    db_session.commit()
    _fire(site.gid, _item_event(EventTypes.asset_trashed, "asset_id", seal.id))
    assert _queued(db_session, site.gid) == 0


def test_a_deleted_asset_or_resource_queues_a_rebuild_only_if_it_was_served(db_session, site):
    for event_type, field in ((EventTypes.asset_deleted, "asset_id"), (EventTypes.resource_deleted, "resource_id")):
        _fire(site.gid, _item_event(event_type, field, uuid.uuid4(), visible_to_sites=False))
    assert _queued(db_session, site.gid) == 0
    for event_type, field in ((EventTypes.asset_deleted, "asset_id"), (EventTypes.resource_deleted, "resource_id")):
        _fire(site.gid, _item_event(event_type, field, uuid.uuid4(), visible_to_sites=True))
    assert _queued(db_session, site.gid) == 2
    _fire(site.gid, _item_event(EventTypes.asset_deleted, "asset_id", uuid.uuid4()))  # no flag recorded: can't tell
    assert _queued(db_session, site.gid) == 3


def test_deleting_a_resource_records_whether_it_was_served(db_session, site, media):
    from marvin.services import trash

    bus = _SpyBus()
    for item_id in (media.resource_live, media.resource_draft):
        trash.delete_resource(db_session, site.gid, item_id, event_bus=bus)
    assert [d.visible_to_sites for _, d in bus.dispatched] == [True, False]
    assert _replay(db_session, site, bus) == 1


def test_deleting_a_trashed_resource_for_good_queues_nothing(db_session, site, media):
    """Trashing it took it off the site (and rebuilt); the delete forever changes nothing a site can fetch."""
    from marvin.services import trash

    trash.trash(db_session, site.gid, "resource", media.resource_live, event_bus=_SpyBus())
    bus = _SpyBus()
    trash.empty_all(db_session, site.gid, event_bus=bus)
    assert [t for t, _ in bus.dispatched if t == EventTypes.resource_deleted] == [EventTypes.resource_deleted]
    assert _replay(db_session, site, bus) == 0


def test_deleting_an_asset_records_whether_it_was_served(db_session, site, media, monkeypatch):
    from marvin.services import trash
    from marvin.services.assets.asset_storage_service import AssetStorageService

    monkeypatch.setattr(AssetStorageService, "delete_asset", lambda self, asset_id: True)  # the file isn't the point
    bus = _SpyBus()
    for item_id in (media.asset_live, media.asset_loose):
        trash.delete_asset(db_session, site.gid, item_id, event_bus=bus)
    assert [d.visible_to_sites for _, d in bus.dispatched] == [True, False]
    assert _replay(db_session, site, bus) == 1


def test_deleting_a_public_collection_queues_a_rebuild_and_a_new_public_one_does_too(db_session, site):
    _fire(site.gid, _collection_event(EventTypes.collection_deleted, uuid.uuid4(), is_public=True))  # row already gone
    _fire(site.gid, _collection_event(EventTypes.collection_deleted, uuid.uuid4()))  # no flag recorded: can't tell
    assert _queued(db_session, site.gid) == 2
    _fire(site.gid, _collection_event(EventTypes.collection_created, site.public))
    assert _queued(db_session, site.gid) == 3
    _fire(site.gid, _collection_event(EventTypes.collection_created, site.private))
    assert _queued(db_session, site.gid) == 3


def test_deleting_a_collection_records_its_visibility(db_session, site):
    from marvin.db.models.platform import Collections

    empty = {}
    for slug, is_public in (("empty-private", False), ("empty-public", True)):
        row = Collections(session=db_session, group_id=site.gid, name=slug, slug=slug, is_public=is_public)
        db_session.add(row)
        db_session.commit()
        empty[is_public] = row.id
    bus = _SpyBus()
    ctl = _collections_controller(db_session, site.gid, bus)
    ctl.delete_collection(empty[False])
    assert [(t, d.is_public) for t, d in bus.dispatched] == [(EventTypes.collection_deleted, False)]
    assert _replay(db_session, site, bus) == 0
    ctl.delete_collection(empty[True])
    assert bus.dispatched[-1][1].is_public is True
    assert _replay(db_session, site, bus) == 1


def _settings_event(*fields):
    return SimpleNamespace(
        event_type=EventTypes.workspace_settings_changed,
        document_data=SimpleNamespace(changed_fields=list(fields)),
        entity_id=None,
        message=SimpleNamespace(body="settings"),
    )


def test_settings_no_site_renders_queue_no_rebuild(db_session, site):
    for fields in (("custom_events",), ("first_day_of_week",), ("workflow_max_steps", "approval_expires_hours"), ("agents.writer.model",)):
        _fire(site.gid, _settings_event(*fields))
    assert _queued(db_session, site.gid) == 0


def test_settings_a_site_serves_queue_a_rebuild(db_session, site):
    for fields in (("site_logo",), ("site_title", "custom_events"), ("name", "slug"), ("site_metadata_json",), ("something_new",), ()):
        _fire(site.gid, _settings_event(*fields))
    assert _queued(db_session, site.gid) == 6


def test_entry_type_and_workspace_changes_queue_a_rebuild(db_session, site):
    # /entry-types and /site are served whole: rendering, capabilities, URL patterns, the workspace's name and slug.
    for event_type in (EventTypes.entry_type_updated, EventTypes.entry_type_deleted, EventTypes.workspace_updated):
        _fire(site.gid, _event(event_type))
    assert _queued(db_session, site.gid) == 3


def test_the_reacted_to_events_are_each_decided_by_a_rule():
    L = SiteRebuildReactionListener
    decided = L.ENTRY_EVENTS | L.ALWAYS_EVENTS | L.COLLECTION_EVENTS | frozenset(L.TRASH_EVENTS) | frozenset(L.ITEM_EVENTS)
    assert L.REACTS_TO - decided == {EventTypes.entry_deleted, EventTypes.workspace_settings_changed}


# --- Tag changes send no event: the tags routes ask for a rebuild themselves ------------------------------


def _tags_controller(db_session, gid):
    from marvin.routes.platform.tags_controller import TagsController

    ctl = object.__new__(TagsController)
    ctl.session, ctl._repos = db_session, None
    ctl.user = SimpleNamespace(
        id=None,
        active_group_id=gid,
        group_id=gid,
        platform_role=PlatformRole.NONE,
        get_workspace_role=lambda group_id: WorkspaceRole.EDITOR,
    )
    return ctl


@fixture
def tagged(db_session, site):
    from marvin.db.models.platform import EntryTags, Tags

    live_tag = Tags(session=db_session, group_id=site.gid, name="Live tag", slug="live-tag")
    draft_tag = Tags(session=db_session, group_id=site.gid, name="Draft tag", slug="draft-tag")
    db_session.add_all([live_tag, draft_tag])
    db_session.flush()
    db_session.add_all([EntryTags(entry_id=site.live, tag_id=live_tag.id), EntryTags(entry_id=site.draft, tag_id=draft_tag.id)])
    db_session.commit()
    yield SimpleNamespace(live=live_tag.id, draft=draft_tag.id)
    db_session.rollback()
    db_session.query(EntryTags).filter(EntryTags.entry_id.in_([site.live, site.draft])).delete()
    db_session.query(Tags).filter_by(group_id=site.gid).delete()
    db_session.commit()


def test_deleting_a_tag_on_published_content_queues_a_rebuild_and_one_on_a_draft_does_not(db_session, site, tagged):
    ctl = _tags_controller(db_session, site.gid)
    ctl.delete_tag(tagged.draft)
    assert _queued(db_session, site.gid) == 0
    ctl.delete_tag(tagged.live)
    assert _queued(db_session, site.gid) == 1


def test_renaming_a_tag_queues_no_rebuild_the_api_serves_its_slug(db_session, site, tagged):
    from marvin.schemas.platform import TagUpdate

    _tags_controller(db_session, site.gid).update_tag(tagged.live, TagUpdate(name="Renamed"))
    assert _queued(db_session, site.gid) == 0


def test_tagging_or_untagging_a_published_entry_queues_a_rebuild_and_a_draft_does_not(db_session, site, tagged):
    ctl = _tags_controller(db_session, site.gid)
    ctl.attach_tag(tagged.live, site.draft)
    ctl.detach_tag(tagged.live, site.draft)
    assert _queued(db_session, site.gid) == 0
    ctl.attach_tag(tagged.draft, site.live)
    assert _queued(db_session, site.gid) == 1
    ctl.detach_tag(tagged.draft, site.live)
    assert _queued(db_session, site.gid) == 2


def test_a_tag_change_queues_nothing_when_the_workspace_turned_rebuilds_off(db_session, site, tagged):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).update({"site_auto_rebuild": False})
    db_session.commit()
    _tags_controller(db_session, site.gid).delete_tag(tagged.live)
    assert _queued(db_session, site.gid) == 0
