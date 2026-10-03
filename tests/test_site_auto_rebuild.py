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
from marvin.services.event_bus_service.event_bus_listener import SiteRebuildReactionListener
from marvin.services.event_bus_service.event_types import EventTypes


@fixture
def site(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"sr-{gid.hex[:8]}", slug=f"sr-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    et = EntryTypes(session=db_session, group_id=gid, name="Venue", slug="venue", schema_json={})
    db_session.add(et)
    db_session.flush()
    live = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Live", slug=f"live-{gid.hex[:6]}", status="published")
    draft = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Draft", slug=f"draft-{gid.hex[:6]}", status="draft")
    db_session.add_all([live, draft])
    db_session.commit()
    yield SimpleNamespace(gid=gid, live=live.id, draft=draft.id)
    db_session.execute(delete(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == gid))
    # The request that opens a batch logs `site_rebuild_queued` against the workspace.
    db_session.query(EventLogModel).filter_by(workspace_id=gid).delete()
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(GroupPreferencesModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _event(event_type, entry_id=None, before=None):
    data = SimpleNamespace(entry_id=entry_id, before=before or {})
    return SimpleNamespace(event_type=event_type, document_data=data, entity_id=entry_id, message=SimpleNamespace(body=f"{event_type.name}"))


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


def test_unrelated_events_are_ignored(db_session, site):
    _fire(site.gid, _event(EventTypes.entry_created, site.live))  # published only when it says so
    _fire(site.gid, _event(EventTypes.webhook_triggered))  # the rebuild itself must never loop
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
