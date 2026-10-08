"""The day-before reminder for the Trash's auto-empty (services/trash.py remind_auto_empty, the hourly
remind_trash_auto_empty task, its push in services/push_notifications.py and its kind on Settings → Automation →
Notifications).

Counted across entries, assets and resources due within 24 hours (those already due too), only where the
workspace's effective auto-empty isn't "never"; one ``trash_auto_empty_soon`` per workspace per day, claimed
atomically on ``group_preferences.trash_reminded_on`` so another tick or replica sends nothing. Its push goes
to owners and admins who take "Trash reminders"; on the notifications page it is a kind that's off by default
and never goes to the Push channel (that push is each person's own choice).
"""

import importlib
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from pytest import fixture

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import alerting, push_notifications, web_push
from marvin.services import trash as T
from marvin.services import workspace_alerts as notes
from marvin.services.entries import trash as entry_trash
from tests.test_trash import _make_workspace, _row, _SpyBus, _svc
from tests.test_trash_assets_resources import _add_items, storage  # noqa: F401 — the storage fixture

DAY = timedelta(days=1)


class _Bus:
    def __init__(self):
        self.events = []

    def dispatch(self, **kw):
        self.events.append(kw)


@fixture
def ws(db_session, monkeypatch, storage):  # noqa: F811
    """A workspace (30-day platform default) with an owner, an admin and an editor as members, a Trash
    collection, and every push captured."""
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _SpyBus)
    w = _make_workspace(db_session, "remind")
    w.asset, w.resource = _add_items(db_session, w, storage)
    marker = w.gid.hex[:8]
    for role in ("owner", "admin"):
        uid = uuid.uuid4()
        db_session.execute(
            Users.__table__.insert().values(
                id=uid, group_id=w.gid, username=f"{role}-{marker}", email=f"{role}-{marker}@t.test", full_name=role,
                password="x", is_superuser=False, platform_role="NONE", auth_method="MARVIN",
            )
        )  # fmt: skip
        w.users[role] = uid
    for role in ("owner", "admin", "editor"):
        db_session.execute(
            sa.insert(WorkspaceMembers.__table__).values(
                id=uuid.uuid4(), user_id=w.users[role], group_id=w.gid, workspace_role=WorkspaceRole[role.upper()]
            )
        )
    trash = Collections(session=db_session, group_id=w.gid, name="Trash", slug="trash")
    db_session.add(trash)
    db_session.flush()
    w.trash_id = trash.id
    w.pushes = []
    monkeypatch.setattr(web_push, "_post", lambda sub, data, message, vapid: w.pushes.append((sub.endpoint, json.loads(data))) or 201)
    yield w
    db_session.rollback()


@fixture
def vapid(monkeypatch):
    from marvin.core.config import get_app_settings
    from marvin.scripts.vapid import generate

    public, private = generate()
    settings = get_app_settings()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@example.test")


def _entry_aged(ws, slug, days_ago):
    eid = ws.entry(slug)
    _svc(ws).trash(eid)
    row = _row(ws, eid)
    row.metadata_json = {
        **row.metadata_json,
        "trash": {**row.metadata_json["trash"], "trashed_at": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()},
    }
    ws.session.flush()
    return eid


def _item_aged(ws, kind, slug, days_ago):
    item = ws.asset(slug) if kind == "asset" else ws.resource(slug)
    T.trash(ws.session, ws.gid, kind, item, event_bus=_Bus())
    ws.session.get(T.model(kind), item).trashed_at = datetime.now(UTC) - timedelta(days=days_ago)
    ws.session.flush()
    return item


def _due(ws):
    """Due within a day: an entry (12 hours left), an asset (2 hours left), an overdue resource; plus some not due."""
    _entry_aged(ws, "due", 29.5)
    _entry_aged(ws, "later", 28)
    _item_aged(ws, "asset", "due-img", 29.9)
    _item_aged(ws, "asset", "later-img", 10)
    _item_aged(ws, "resource", "overdue", 31)
    restored = _entry_aged(ws, "restored", 29.9)
    _svc(ws).restore_from_trash(restored)


def _set_override(ws, days):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).one().trash_auto_empty_days = days
    ws.session.flush()


def _reminded_on(ws):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    return ws.session.query(GroupPreferencesModel.trash_reminded_on).filter_by(group_id=ws.gid).scalar()


def _mine(bus, ws):
    return [e for e in bus.events if e["group_id"] == ws.gid]


# ── what is due, and when it is said ──────────────────────────────────────────


def test_counts_entries_assets_and_resources_due_within_a_day(ws):
    _due(ws)
    assert T.expiring_soon(ws.session, ws.gid, 30) == {"entries": 1, "assets": 1, "resources": 1, "total": 3}
    assert T.expiring_soon(ws.session, ws.gid, 0)["total"] == 0  # never
    assert T.expiring_soon(ws.session, ws.gid, 7)["total"] == 5  # a week: the 10-day asset and the 28-day entry too


def test_one_reminder_per_workspace_per_day(ws):
    _due(ws)
    bus = _Bus()
    now = datetime.now(UTC)
    assert T.remind_auto_empty(ws.session, event_bus=bus, now=now)[ws.gid] == 3
    [event] = _mine(bus, ws)
    data = event["document_data"]
    assert event["event_type"].name == "trash_auto_empty_soon" and event["entity_id"] == ws.trash_id
    assert (data.total, data.entries, data.assets, data.resources, data.days) == (3, 1, 1, 1, 30)
    assert data.trash_collection_id == ws.trash_id and _reminded_on(ws) == now.date()

    for later in (now, now + timedelta(hours=5)):  # the next ticks, another replica: already reminded today
        assert ws.gid not in T.remind_auto_empty(ws.session, event_bus=bus, now=later)
    assert len(_mine(bus, ws)) == 1
    assert T.remind_auto_empty(ws.session, event_bus=bus, now=now + DAY).get(ws.gid)  # tomorrow: again, while something is due
    assert len(_mine(bus, ws)) == 2


def test_never_and_nothing_due_send_nothing(ws):
    _due(ws)
    _set_override(ws, 0)
    bus = _Bus()
    assert ws.gid not in T.remind_auto_empty(ws.session, event_bus=bus) and not _mine(bus, ws)
    _set_override(ws, 90)  # nothing within a day of 90
    assert ws.gid not in T.remind_auto_empty(ws.session, event_bus=bus) and not _mine(bus, ws)
    assert _reminded_on(ws) is None  # nothing claimed: a reminder can still go later today


def test_platform_never_is_respected_too(ws):
    _due(ws)
    entry_trash.set_platform_auto_empty_days(ws.session, 0)
    bus = _Bus()
    assert ws.gid not in T.remind_auto_empty(ws.session, event_bus=bus)


def test_the_claim_is_atomic(ws):
    today = datetime.now(UTC).date()
    assert T._claim_reminder(ws.session, ws.gid, today) is True
    assert T._claim_reminder(ws.session, ws.gid, today) is False
    assert T._claim_reminder(ws.session, ws.gid, today + DAY) is True


def test_the_hourly_task_reminds_and_is_registered_hourly(ws, monkeypatch):
    import inspect

    from marvin.app import start_scheduler

    source = inspect.getsource(start_scheduler)
    hourly = source[source.index("register_hourly(") :]
    assert "scheduler_tasks.remind_trash_auto_empty" in hourly[: hourly.index(")")]  # hourly ticks run on the leader only

    task = importlib.import_module("marvin.services.scheduler.tasks.remind_trash_auto_empty")
    bus = _Bus()

    @contextmanager
    def same_session():
        yield ws.session

    monkeypatch.setattr(task, "session_context", same_session)
    monkeypatch.setattr(task, "EventBusService", lambda bg_tasks=None: bus)
    _due(ws)
    task.remind_trash_auto_empty()
    task.remind_trash_auto_empty()
    assert len(_mine(bus, ws)) == 1


# ── the push ──────────────────────────────────────────────────────────────────


def _event(ws, bus):
    [kw] = _mine(bus, ws)
    return SimpleNamespace(
        event_type=kw["event_type"],
        workspace_id=ws.gid,
        user_id=None,
        entity_id=kw["entity_id"],
        entity_type=kw["entity_type"],
        document_data=kw["document_data"],
        message=SimpleNamespace(body=kw["message"]),
    )


def _subscribe(ws, *names):
    from marvin.db.models.users.users import Users

    for name in names:
        user = ws.session.get(Users, ws.users[name])
        web_push.subscribe(ws.session, user, endpoint=f"https://push.example.test/{name}/1", p256dh="p", auth="a", user_agent=None, label=None)


def test_the_push_reaches_owners_and_admins_who_take_trash_reminders(ws, vapid):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    _due(ws)
    _subscribe(ws, "owner", "admin", "editor")
    bus = _Bus()
    T.remind_auto_empty(ws.session, event_bus=bus)
    event = _event(ws, bus)
    push_notifications.deliver(ws.session, ws.gid, event)
    assert {endpoint.split("/")[-2] for endpoint, _ in ws.pushes} == {"owner", "admin"}  # not the editor
    payload = ws.pushes[0][1]
    workspace = ws.session.get(Groups, ws.gid).name
    assert payload["title"] == f"{workspace}: 3 items will be deleted forever tomorrow"
    assert payload["url"] == f"/workspace/collections/{ws.trash_id}" and payload["tag"] == f"trash-reminder:{ws.gid}"

    ws.pushes.clear()
    web_push.set_preferences(ws.session, ws.session.get(Users, ws.users["admin"]), {web_push.TRASH_REMINDERS: False})
    push_notifications.deliver(ws.session, ws.gid, event)
    assert {endpoint.split("/")[-2] for endpoint, _ in ws.pushes} == {"owner"}


def test_trash_reminders_is_a_push_kind_people_choose_on_by_default(ws):
    from marvin.db.models.users.users import Users

    owner = ws.session.get(Users, ws.users["owner"])
    assert web_push.preferences(owner)[web_push.TRASH_REMINDERS] is True


# ── the notifications page ────────────────────────────────────────────────────


def test_the_notifications_kind_is_off_by_default_and_never_on_the_push_channel(ws, vapid, monkeypatch):
    settings = notes.load(ws.session, ws.gid)
    assert settings.types[notes.TRASH_SOON] is False
    assert alerting.PUSH_CHANNEL in settings.channels_for(notes.WORKFLOW_FAILED)  # the other kinds still take push
    assert alerting.PUSH_CHANNEL not in settings.channels_for(notes.TRASH_SOON)
    assert alerting.EMAIL_CHANNEL in settings.channels_for(notes.TRASH_SOON)

    _due(ws)
    bus = _Bus()
    T.remind_auto_empty(ws.session, event_bus=bus)
    event = _event(ws, bus)
    assert notes.deliver(ws.session, ws.gid, event) == {}  # off by default: nothing sent

    sent = []
    monkeypatch.setattr(alerting, "send", lambda scope, session, settings, message, channels, **kw: sent.append((message, channels)) or {})
    stored = notes.load(ws.session, ws.gid)
    stored.types[notes.TRASH_SOON] = True
    notes.WorkspaceScope(ws.gid).store_settings(ws.session, stored.as_stored())
    notes.deliver(ws.session, ws.gid, event)
    [(message, channels)] = sent
    assert channels == [alerting.EMAIL_CHANNEL]
    assert message.title == "3 items will be deleted forever tomorrow" and message.path == f"/workspace/collections/{ws.trash_id}"


@pytest.mark.parametrize("key", [notes.TRASH_SOON])
def test_the_page_says_the_kind_takes_no_push(key):
    kind = notes.KINDS_BY_KEY[key]
    assert kind.default is False and kind.push is False and kind.event_type == "trash_auto_empty_soon"
