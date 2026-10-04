"""Scheduled publishing publishes due entries once, and only the ones it should.

Regression: publishing never cleared publish_at, so an entry that went live (on schedule or by
hand) and was then unpublished went live again on the next run, and an archived entry with an old
schedule was brought back.

Regression: the scheduled publish/expiry wrote the status directly and dispatched an event with no
entry in it, so nothing keyed on the entry reacted: a smart collection didn't pick up a scheduled
publish until it was re-saved. They now change status as a manual edit does (EntryService).

Regression: expiry archived an entry but kept its expire_at, so re-publishing it put it back in
front of the expiry task, which archived it again within minutes. Expiry now clears the date, and
publishing an entry whose expiration date has passed is refused with the reason.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.services.event_bus_service.event_types import EventTypes
from marvin.services.scheduled_tasks.handlers.publishing import PublishScheduledEntriesHandler, UnpublishExpiredEntriesHandler

PAST = datetime.now(UTC) - timedelta(hours=1)
FUTURE = datetime.now(UTC) + timedelta(days=1)


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Collections, Entries, EntryCollections, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"sched-{gid.hex[:8]}", slug=f"sched-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json={})
    db_session.add(et)
    db_session.commit()
    yield SimpleNamespace(id=gid, entry_type_id=et.id)
    collection_ids = [c.id for c in db_session.query(Collections).filter_by(group_id=gid)]
    if collection_ids:
        db_session.query(EntryCollections).filter(EntryCollections.collection_id.in_(collection_ids)).delete()
    db_session.query(Collections).filter_by(group_id=gid).delete()
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@fixture
def make_entry(db_session, workspace):
    from marvin.db.models.platform import Entries

    def make(status="draft", **fields):
        entry = Entries(
            session=db_session,
            group_id=workspace.id,
            entry_type_id=workspace.entry_type_id,
            title=f"E-{uuid.uuid4().hex[:6]}",
            slug=f"e-{uuid.uuid4().hex[:8]}",
            status=status,
        )
        for key, value in fields.items():
            setattr(entry, key, value)
        db_session.add(entry)
        db_session.commit()
        return entry.id

    return make


def run_task(workspace_id, handler=PublishScheduledEntriesHandler, **config):
    events: list[dict] = []
    task = SimpleNamespace(group_id=workspace_id, task_config=config)
    summary = handler().execute(task, SimpleNamespace(dispatch=lambda **kw: events.append(kw)))
    return summary, events


def of_type(events, event_type):
    return [e for e in events if e["event_type"] == event_type]


def reload(db_session, entry_id):
    from marvin.db.models.platform import Entries

    db_session.expire_all()
    return db_session.get(Entries, entry_id)


def test_publish_due_entry_publishes_and_clears_schedule(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at, entry.published_at is not None) == ("published", None, True)
    assert len(of_type(events, EventTypes.entry_published)) == 1 and summary.startswith("1 entry published")


def test_publish_entry_unpublished_after_schedule_stays_unpublished(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)
    run_task(workspace.id)
    entry = reload(db_session, entry_id)
    entry.status = "draft"
    entry.published_at = None
    db_session.commit()

    run_task(workspace.id)

    assert reload(db_session, entry_id).status == "draft"


def test_publish_archived_entry_with_old_schedule_is_not_resurrected(db_session, workspace, make_entry):
    entry_id = make_entry(status="archived", publish_at=PAST)

    summary, _ = run_task(workspace.id)

    assert reload(db_session, entry_id).status == "archived"
    assert summary is None


def test_publish_future_schedule_is_left_alone(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=FUTURE)

    run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at is not None) == ("draft", True)


def test_publish_keeps_a_backdated_published_at(db_session, workspace, make_entry):
    backdated = datetime(2024, 1, 15, 9, 0, tzinfo=UTC)
    entry_id = make_entry(publish_at=PAST, published_at=backdated)

    run_task(workspace.id)

    assert reload(db_session, entry_id).published_at == backdated


def test_publish_dry_run_changes_nothing(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id, dry_run=True)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at is not None, events) == ("draft", True, [])
    assert summary.endswith("(dry run)")


def repos_for(db_session, workspace):
    from marvin.repos.all_repositories import get_repositories

    return get_repositories(db_session, group_id=workspace.id)


def test_manual_publish_clears_schedule(db_session, workspace, make_entry):
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(publish_at=FUTURE)

    repos_for(db_session, workspace).entries.update(entry_id, EntryUpdate(status="published"))

    assert reload(db_session, entry_id).publish_at is None


def test_create_as_published_drops_schedule(db_session, workspace):
    from marvin.schemas.platform import EntryCreate

    created = repos_for(db_session, workspace).entries.create(
        EntryCreate(entry_type_id=workspace.entry_type_id, title="Live now", status="published", publish_at=FUTURE)
    )

    assert reload(db_session, created.id).publish_at is None


def test_manual_publish_then_unpublish_is_not_republished_by_task(db_session, workspace, make_entry):
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(publish_at=PAST)
    repos = repos_for(db_session, workspace)
    repos.entries.update(entry_id, EntryUpdate(status="published"))
    repos.entries.update(entry_id, EntryUpdate(status="draft"))

    run_task(workspace.id)

    assert reload(db_session, entry_id).status == "draft"


def test_system_and_workspace_publish_tasks_publish_once(db_session, workspace, make_entry):
    """The built-in platform-wide task and a workspace's own task can both run in one tick."""
    entry_id = make_entry(publish_at=PAST)

    _, system_events = run_task(None)
    workspace_summary, workspace_events = run_task(workspace.id)

    published = of_type(system_events + workspace_events, EventTypes.entry_published)
    published_here = [e for e in published if e["group_id"] == workspace.id]
    assert (reload(db_session, entry_id).status, len(published_here), workspace_summary) == ("published", 1, None)


def test_unpublish_with_nothing_expired_records_nothing(workspace):
    task = SimpleNamespace(group_id=workspace.id, task_config={})

    assert UnpublishExpiredEntriesHandler().execute(task, SimpleNamespace(dispatch=lambda **_: None)) is None


# ── Same events as a manual status change ──────────────────────────────────────


def test_publish_emits_updated_then_published_about_the_entry(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST)

    _, events = run_task(workspace.id)

    assert [e["event_type"] for e in events] == [EventTypes.entry_updated, EventTypes.entry_published]
    published = events[1]
    data = published["document_data"]
    assert (published["entity_id"], published["group_id"], data.entry_id, data.entry_type, data.after) == (
        entry_id,
        workspace.id,
        entry_id,
        "newsletter",
        {"status": "published"},
    )


def test_expiry_emits_updated_unpublished_archived_about_the_entry(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=PAST)

    _, events = run_task(workspace.id, handler=UnpublishExpiredEntriesHandler)

    expected = [EventTypes.entry_updated, EventTypes.entry_unpublished, EventTypes.entry_archived]
    assert [(e["event_type"], e["entity_id"], e["document_data"].entry_id) for e in events] == [(t, entry_id, entry_id) for t in expected]


def smart_collection_bus():
    """The real event bus, fanning out only to the smart-collection listener."""
    from marvin.services.event_bus_service.event_bus_listener import SmartCollectionReactionListener
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    class SmartCollectionBus(EventBusService):
        def _get_listeners(self, group_id):
            return [SmartCollectionReactionListener(group_id)]

    return SmartCollectionBus(bg_tasks=None)


def run_with_bus(workspace_id, handler):
    task = SimpleNamespace(group_id=workspace_id, task_config={})
    return handler().execute(task, smart_collection_bus())


@fixture
def published_collection(db_session, workspace):
    from marvin.db.models.platform import Collections

    collection = Collections(
        session=db_session,
        group_id=workspace.id,
        name="Published newsletters",
        slug=f"published-{uuid.uuid4().hex[:6]}",
        is_smart=True,
        smart_rules={"entry_types": ["newsletter"], "statuses": ["published"]},
    )
    db_session.add(collection)
    db_session.commit()
    return collection.id


def members(db_session, collection_id):
    from marvin.db.models.platform import EntryCollections

    db_session.expire_all()
    return {row.entry_id for row in db_session.query(EntryCollections).filter_by(collection_id=collection_id)}


def test_scheduled_publish_joins_matching_smart_collection(db_session, workspace, make_entry, published_collection):
    entry_id = make_entry(publish_at=PAST)

    run_with_bus(workspace.id, PublishScheduledEntriesHandler)

    assert entry_id in members(db_session, published_collection)


def test_expiry_leaves_published_only_smart_collection(db_session, workspace, make_entry, published_collection):
    from marvin.services.collections.smart_collections import sync_entry

    entry_id = make_entry(status="published", expire_at=PAST)
    sync_entry(db_session, workspace.id, reload(db_session, entry_id))
    db_session.commit()
    assert entry_id in members(db_session, published_collection)

    summary = run_with_bus(workspace.id, UnpublishExpiredEntriesHandler)

    assert (reload(db_session, entry_id).status, entry_id in members(db_session, published_collection)) == ("archived", False)
    assert summary.startswith("1 entry archived")


@fixture
def strict_type_id(db_session, workspace):
    from marvin.db.models.platform import EntryTypes

    et = EntryTypes(
        session=db_session,
        group_id=workspace.id,
        name="Issue",
        slug="issue",
        schema_json={"fields": [{"key": "subject", "label": "Subject", "type": "text", "required": True}]},
    )
    db_session.add(et)
    db_session.commit()
    return et.id


def test_incomplete_entry_is_skipped_and_others_publish(db_session, workspace, make_entry, strict_type_id):
    incomplete_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    complete_id = make_entry(publish_at=PAST)

    summary, events = run_task(workspace.id)

    incomplete, complete = reload(db_session, incomplete_id), reload(db_session, complete_id)
    assert (incomplete.status, incomplete.publish_at is not None, complete.status) == ("draft", True, "published")
    assert [e["entity_id"] for e in of_type(events, EventTypes.entry_published)] == [complete_id]
    assert summary == f"1 entry published: '{complete.title}'; 1 skipped (can't publish: '{incomplete.title}' — Required field 'Subject' is empty.)"


# ── Expiration date ────────────────────────────────────────────────────────────


def service_for(db_session, workspace):
    from marvin.services.entries import EntryService

    return EntryService(db_session, workspace.id, event_bus=SimpleNamespace(dispatch=lambda **_: None))


def expired_message(when: datetime) -> str:
    return f"The expiration date ({when:%b} {when.day}, {when:%Y %H:%M} UTC) has passed — clear it or set a later date."


def test_expiry_archives_and_clears_expire_at(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=PAST)

    run_task(workspace.id, handler=UnpublishExpiredEntriesHandler)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.expire_at) == ("archived", None)


def test_expiry_dry_run_keeps_expire_at(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=PAST)

    run_task(workspace.id, handler=UnpublishExpiredEntriesHandler, dry_run=True)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.expire_at is not None) == ("published", True)


def test_republish_after_expiry_stays_published_past_next_run(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=PAST)
    run_task(workspace.id, handler=UnpublishExpiredEntriesHandler)
    service_for(db_session, workspace).set_status(entry_id, "published")

    summary, _ = run_task(workspace.id, handler=UnpublishExpiredEntriesHandler)

    assert (reload(db_session, entry_id).status, summary) == ("published", None)


def test_manual_archive_keeps_a_pending_expiry(db_session, workspace, make_entry):
    entry_id = make_entry(status="published", expire_at=FUTURE)

    service_for(db_session, workspace).set_status(entry_id, "archived")

    assert reload(db_session, entry_id).expire_at == FUTURE


def test_publish_with_past_expiry_is_refused_with_reason(db_session, workspace, make_entry):
    entry_id = make_entry(expire_at=PAST)

    with pytest.raises(HTTPException) as exc:
        service_for(db_session, workspace).set_status(entry_id, "published")

    assert (exc.value.status_code, exc.value.detail["issues"]) == (422, [expired_message(PAST)])
    assert reload(db_session, entry_id).status == "draft"


def test_publish_with_future_expiry_publishes(db_session, workspace, make_entry):
    entry_id = make_entry(expire_at=FUTURE)

    service_for(db_session, workspace).set_status(entry_id, "published")

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.expire_at is not None) == ("published", True)


def test_publish_that_clears_a_past_expiry_in_the_same_save_publishes(db_session, workspace, make_entry):
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(expire_at=PAST)

    service_for(db_session, workspace).update(entry_id, EntryUpdate(status="published", expire_at=None))

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.expire_at) == ("published", None)


def test_publish_that_sets_a_past_expiry_in_the_same_save_is_refused(db_session, workspace, make_entry):
    entry_id = make_entry()

    with pytest.raises(HTTPException) as exc:
        service_for(db_session, workspace).update(entry_id, {"status": "published", "expire_at": PAST.isoformat()})

    assert exc.value.detail["issues"] == [expired_message(PAST)]


def test_publish_reports_past_expiry_alongside_missing_fields(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(expire_at=PAST, entry_type_id=strict_type_id)

    with pytest.raises(HTTPException) as exc:
        service_for(db_session, workspace).set_status(entry_id, "published")

    assert exc.value.detail["issues"] == ["Required field 'Subject' is empty.", expired_message(PAST)]


def test_saving_a_published_entry_with_a_past_expiry_is_allowed(db_session, workspace, make_entry):
    """Not a publish: setting a live entry's expiry to now/earlier is how you take it down on the next run."""
    from marvin.schemas.platform import EntryUpdate

    entry_id = make_entry(status="published")

    service_for(db_session, workspace).update(entry_id, EntryUpdate(expire_at=PAST))

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.expire_at is not None) == ("published", True)


def test_scheduled_publish_skips_entry_whose_expiry_passed(db_session, workspace, make_entry):
    entry_id = make_entry(publish_at=PAST, expire_at=PAST)

    summary, events = run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.publish_at is not None) == ("draft", True)
    assert [e["event_type"] for e in events] == [EventTypes.entry_scheduled_publish_blocked]
    assert summary == f"1 entry skipped (can't publish: '{entry.title}' — {expired_message(PAST)})"


def test_automation_publish_with_past_expiry_fails_the_step_with_reason(db_session, workspace, make_entry):
    from marvin.services.automation.actions.base import AutomationActionError
    from marvin.services.automation.actions.entry import run_entry_action
    from marvin.services.automation.authz import ROLE_OWNER

    entry_id = make_entry(expire_at=PAST)

    with pytest.raises(AutomationActionError) as exc:
        run_entry_action(
            db_session,
            workspace.id,
            {"kind": "entry", "op": "publish", "entity_id": str(entry_id)},
            {"event": {}, "steps": {}, "depth": 0},
            authorizer_role=ROLE_OWNER,
        )

    assert str(exc.value) == f"entry publish refused: {expired_message(PAST)}"
    assert reload(db_session, entry_id).status == "draft"


# ── expiry_issue ───────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "expire_at",
    [
        datetime(2026, 10, 3, 11, 59, tzinfo=UTC),
        datetime(2026, 10, 3, 11, 59),  # noqa: DTZ001 — naive is UTC, as entries store it
        datetime(2026, 10, 3, 6, 59, tzinfo=timezone(timedelta(hours=-5))),
        "2026-10-03T11:59:00Z",
        NOW,  # the expiry task archives at expire_at <= now
    ],
)
def test_expiry_issue_blocks_a_passed_date(expire_at):
    from marvin.services.entries.completeness import expiry_issue

    issue = expiry_issue(expire_at, now=NOW)

    assert issue is not None and issue.blocking and issue.key == "expire_at"


@pytest.mark.parametrize("expire_at", [None, "", "not a date", datetime(2026, 10, 3, 12, 1, tzinfo=UTC)])
def test_expiry_issue_allows_unset_unparseable_and_future(expire_at):
    from marvin.services.entries.completeness import expiry_issue

    assert expiry_issue(expire_at, now=NOW) is None


def test_expiry_issue_message_shows_the_date_in_utc():
    from marvin.services.entries.completeness import expiry_issue

    issue = expiry_issue(datetime(2026, 10, 1, 9, 5, tzinfo=timezone(timedelta(hours=-5))), now=NOW)

    assert issue.message == "The expiration date (Oct 1, 2026 14:05 UTC) has passed — clear it or set a later date."


# ── A held-back scheduled publish: recorded on the entry, notified once ─────────
#
# Regression: a scheduled publish the gate refused was skipped every 5 minutes with the reason only
# in the scheduler's execution log, so nobody knew the entry hadn't gone out.

REQUIRED_SUBJECT = "Required field 'Subject' is empty."


def blocked_events(events):
    return of_type(events, EventTypes.entry_scheduled_publish_blocked)


def edit(db_session, workspace, entry_id, **changes):
    from marvin.schemas.platform import EntryUpdate

    service_for(db_session, workspace).update(entry_id, EntryUpdate(**changes))


def test_blocked_entry_records_the_reason_on_the_entry(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)

    run_task(workspace.id)

    block = reload(db_session, entry_id).scheduled_publish_blocked
    assert {k: block[k] for k in ("waiting_for", "reason", "issues", "notified")} == {
        "waiting_for": "requirements",
        "reason": REQUIRED_SUBJECT,
        "issues": [REQUIRED_SUBJECT],
        "notified": True,
    }


def test_blocked_entry_notifies_once_across_runs(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)

    notified = [blocked_events(run_task(workspace.id)[1]) for _ in range(3)]

    assert [len(n) for n in notified] == [1, 0, 0]
    event = notified[0][0]
    assert (event["entity_id"], event["entity_type"], event["document_data"].issues) == (entry_id, "entry", [REQUIRED_SUBJECT])


def test_blocked_entry_event_says_why(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)

    event = blocked_events(run_task(workspace.id)[1])[0]

    title = reload(db_session, entry_id).title
    assert (event["document_data"].waiting_for, event["message"]) == (
        "requirements",
        f"Scheduled publish of '{title}' is waiting — can't publish: {REQUIRED_SUBJECT}",
    )


def test_blocked_entry_renotifies_when_the_reason_changes(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)
    entry = reload(db_session, entry_id)
    entry.expire_at = PAST  # not through an edit: only the reason changes
    db_session.commit()

    events = blocked_events(run_task(workspace.id)[1])

    assert [e["document_data"].issues for e in events] == [[REQUIRED_SUBJECT, expired_message(PAST)]]
    assert reload(db_session, entry_id).scheduled_publish_blocked["issues"] == [REQUIRED_SUBJECT, expired_message(PAST)]


def test_an_edit_that_keeps_the_schedule_keeps_the_notice_and_renotifies(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)
    # The editor posts publish_at on every save, as a UTC ISO string; the same instant isn't a reschedule.
    edit(db_session, workspace, entry_id, summary="Tweaked", publish_at=PAST.isoformat().replace("+00:00", "Z"))

    kept = reload(db_session, entry_id).scheduled_publish_blocked
    events = blocked_events(run_task(workspace.id)[1])

    assert (kept["issues"], kept["notified"], len(events)) == ([REQUIRED_SUBJECT], False, 1)


def test_scheduled_publish_after_the_fix_clears_the_block(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)
    edit(db_session, workspace, entry_id, data_json={"subject": "October news"})

    summary, events = run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (entry.status, entry.scheduled_publish_blocked, blocked_events(events)) == ("published", None, [])


@pytest.mark.parametrize("changes", [{"publish_at": FUTURE}, {"publish_at": None}, {"status": "archived"}])
def test_rescheduling_or_archiving_clears_the_block(db_session, workspace, make_entry, strict_type_id, changes):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)

    edit(db_session, workspace, entry_id, **changes)

    assert reload(db_session, entry_id).scheduled_publish_blocked is None


def test_dry_run_records_and_notifies_nothing(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)

    _, events = run_task(workspace.id, dry_run=True)

    assert (reload(db_session, entry_id).scheduled_publish_blocked, events) == (None, [])


# ── "Scheduled publish only for approved entries" (workspace setting) ───────────


def set_approval_only(db_session, workspace_id, on: bool) -> None:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=workspace_id).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=db_session, group_id=workspace_id)
        db_session.add(prefs)
    prefs.scheduled_publish_requires_approval = on
    db_session.commit()


@fixture
def approval_only(db_session, workspace):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    set_approval_only(db_session, workspace.id, True)
    yield
    db_session.query(GroupPreferencesModel).filter_by(group_id=workspace.id).delete()
    db_session.commit()


def approval_message(status_label: str) -> str:
    return f"This workspace publishes only approved entries on schedule, and this one is '{status_label}'. Approve it to let it go out."


def test_approval_setting_off_publishes_an_inbox_entry(db_session, workspace, make_entry):
    entry_id = make_entry(status="inbox", publish_at=PAST)

    run_task(workspace.id)

    assert reload(db_session, entry_id).status == "published"


def test_approval_setting_holds_an_unapproved_entry_with_the_reason(db_session, workspace, make_entry, approval_only):
    waiting_id = make_entry(status="inbox", publish_at=PAST)
    approved_id = make_entry(status="approved", publish_at=PAST)

    summary, events = run_task(workspace.id)

    waiting, approved = reload(db_session, waiting_id), reload(db_session, approved_id)
    block = waiting.scheduled_publish_blocked
    assert (waiting.status, waiting.publish_at is not None, approved.status) == ("inbox", True, "published")
    assert (block["waiting_for"], block["reason"], block["issues"]) == ("approval", "Waiting for approval", [approval_message("Inbox")])
    assert [(e["entity_id"], e["message"]) for e in blocked_events(events)] == [
        (waiting_id, f"Scheduled publish of '{waiting.title}' is waiting for approval")
    ]
    assert summary == f"1 entry published: '{approved.title}'; 1 waiting for approval: '{waiting.title}'"


def test_approval_wait_notifies_once_then_publishes_when_approved(db_session, workspace, make_entry, approval_only):
    entry_id = make_entry(status="needs_review", publish_at=PAST)
    first, second = (blocked_events(run_task(workspace.id)[1]) for _ in range(2))
    edit(db_session, workspace, entry_id, status="approved")

    run_task(workspace.id)

    entry = reload(db_session, entry_id)
    assert (len(first), len(second), first[0]["document_data"].issues) == (1, 0, [approval_message("Needs review")])
    assert (entry.status, entry.scheduled_publish_blocked) == ("published", None)


def test_platform_wide_run_reads_each_workspace_setting(db_session, workspace, make_entry, approval_only):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    other_id = uuid.uuid4()
    other = Groups(session=db_session, name=f"sched-{other_id.hex[:8]}", slug=f"sched-{other_id.hex[:8]}")
    other.id = other_id
    db_session.add(other)
    db_session.flush()
    other_type = EntryTypes(session=db_session, group_id=other_id, name="Newsletter", slug="newsletter", schema_json={})
    db_session.add(other_type)
    db_session.flush()
    other_entry = Entries(
        session=db_session, group_id=other_id, entry_type_id=other_type.id, title="Elsewhere", slug=f"else-{other_id.hex[:6]}", status="inbox"
    )
    other_entry.publish_at = PAST
    db_session.add(other_entry)
    db_session.commit()
    other_entry_id = other_entry.id
    waiting_id = make_entry(status="inbox", publish_at=PAST)
    try:
        run_task(None)

        assert (reload(db_session, waiting_id).status, reload(db_session, other_entry_id).status) == ("inbox", "published")
    finally:
        db_session.query(Entries).filter_by(group_id=other_id).delete()
        db_session.query(EntryTypes).filter_by(group_id=other_id).delete()
        db_session.query(Groups).filter_by(id=other_id).delete()
        db_session.commit()


def test_approval_setting_is_a_workspace_preference(db_session, workspace):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.schemas.group.preferences import GroupPreferencesRead

    set_approval_only(db_session, workspace.id, True)
    try:
        prefs = AllRepositories(db_session, group_id=workspace.id).group_preferences.multi_query({"group_id": workspace.id})[0]
        assert GroupPreferencesRead.model_validate(prefs).model_dump(by_alias=True)["scheduledPublishRequiresApproval"] is True
    finally:
        set_approval_only(db_session, workspace.id, False)
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        db_session.query(GroupPreferencesModel).filter_by(group_id=workspace.id).delete()
        db_session.commit()


def test_entry_read_carries_the_block(db_session, workspace, make_entry, strict_type_id):
    from marvin.schemas.platform import EntryRead

    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)

    read = EntryRead.model_validate(reload(db_session, entry_id)).model_dump(by_alias=True)["scheduledPublishBlocked"]

    assert {k: read[k] for k in ("waitingFor", "reason", "issues")} == {
        "waitingFor": "requirements",
        "reason": REQUIRED_SUBJECT,
        "issues": [REQUIRED_SUBJECT],
    }
    assert "notified" not in read


def test_an_automation_write_back_re_arms_the_notification(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)

    service_for(db_session, workspace).apply_fields(entry_id, {"summary": "Written by a workflow"})

    assert reload(db_session, entry_id).scheduled_publish_blocked["notified"] is False


def test_an_automation_write_back_that_reschedules_clears_the_block(db_session, workspace, make_entry, strict_type_id):
    entry_id = make_entry(publish_at=PAST, entry_type_id=strict_type_id)
    run_task(workspace.id)

    service_for(db_session, workspace).apply_fields(entry_id, {"publish_at": FUTURE})

    assert reload(db_session, entry_id).scheduled_publish_blocked is None
