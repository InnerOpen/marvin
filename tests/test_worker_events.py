"""A worker going quiet or coming back as events: Marvin's per-minute check marks `data.offline_since`, and that change is worker_offline /
worker_online (a worker's heartbeat is a `worker` entry whose `last_seen` the dispatcher rewrites about once a minute)."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa
from pytest import fixture

from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.users import Users
from marvin.schemas.platform import EntryUpdate
from marvin.services import worker_health
from marvin.services.entries import EntryService
from marvin.services.events.event_catalog import CATALOG_BY_TYPE

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _Bus:
    def __init__(self):
        self.sent = []

    def dispatch(self, *, event_type, document_data=None, message=None, **_):
        self.sent.append((event_type.name, message))


def _service(slug, data):
    state = {
        "id": uuid.uuid4(),
        "title": "Dispatcher on desktop",
        "status": "draft",
        "group_id": uuid.uuid4(),
        "created_by": None,
        "entry_type_id": "T",
        "data_json": data,
    }
    snap = lambda: SimpleNamespace(**{**state, "data_json": dict(state["data_json"])})  # noqa: E731
    entries = SimpleNamespace(
        get_one=lambda _id: snap(),
        update=lambda _id, d: state.update(data_json=dict(d.data_json)) or snap(),
    )
    repos = SimpleNamespace(
        entries=entries,
        entry_types=SimpleNamespace(get_one=lambda _id: SimpleNamespace(slug=slug)),
        groups=SimpleNamespace(get_one=lambda _id: SimpleNamespace(name="W")),
        users=SimpleNamespace(get_one=lambda _id: None),
    )
    bus = _Bus()
    svc = EntryService.__new__(EntryService)
    svc.repos, svc.group_id, svc.actor_id, svc.integration_id, svc._event_bus, svc.session = repos, "G", None, None, bus, SimpleNamespace()
    svc._sync_linked_fields = lambda e, **_: e
    return svc, bus, state


def _names(bus):
    return [n for n, _ in bus.sent]


def test_setting_offline_since_on_a_worker_sends_worker_offline():
    svc, bus, state = _service("worker", {"last_seen": "x"})
    svc.update(state["id"], EntryUpdate(data_json={"last_seen": "x", "offline_since": NOW.isoformat()}))
    assert _names(bus) == ["entry_updated", "worker_offline"]
    assert "went offline" in bus.sent[-1][1]


def test_clearing_offline_since_sends_worker_online():
    svc, bus, state = _service("worker", {"last_seen": "x", "offline_since": NOW.isoformat()})
    svc.update(state["id"], EntryUpdate(data_json={"last_seen": "x", "offline_since": ""}))
    assert _names(bus) == ["entry_updated", "worker_online"]


def test_a_heartbeat_alone_and_other_entry_types_send_no_worker_event():
    svc, bus, state = _service("worker", {"last_seen": "a"})
    svc.update(state["id"], EntryUpdate(data_json={"last_seen": "b"}))
    other, other_bus, other_state = _service("beat", {})
    other.update(other_state["id"], EntryUpdate(data_json={"offline_since": "x"}))
    assert _names(bus) == ["entry_updated"] and _names(other_bus) == ["entry_updated"]


def test_the_worker_events_are_catalogued_under_workers():
    for name in ("worker_offline", "worker_online"):
        entry = CATALOG_BY_TYPE[name]
        assert entry.category == "Workers" and entry.triggerable and entry.sent_by


@fixture
def workers(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"wk-{marker}", slug=f"wk-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uuid.uuid4(), group_id=gid, full_name="T", username=f"u-{marker}", email=f"u-{marker}@x.test",
            auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=True,
        )
    )  # fmt: skip
    et = EntryTypes(session=db_session, group_id=gid, name="Worker", slug="worker")
    db_session.add(et)
    db_session.flush()

    def make(name, data):
        row = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=name, slug=f"{name}-{marker}", status="draft", data_json=data)
        db_session.add(row)
        db_session.flush()
        return row

    return make


def _ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def test_check_marks_a_quiet_worker_once_and_clears_it_when_it_is_back(workers, db_session):
    bus = _Bus()
    quiet = workers("quiet", {"last_seen": _ago(10)})
    live = workers("live", {"last_seen": _ago(1)})
    no_beat = workers("nobeat", {})

    first = worker_health.check(db_session, NOW, event_bus=bus)
    assert first.offline == ["quiet"] and first.online == []
    assert db_session.get(Entries, quiet.id).data_json["offline_since"] == NOW.isoformat()
    assert not db_session.get(Entries, live.id).data_json.get("offline_since") and not db_session.get(Entries, no_beat.id).data_json.get(
        "offline_since"
    )
    assert [n for n in _names(bus) if n.startswith("worker_")] == ["worker_offline"]

    again = worker_health.check(db_session, NOW + timedelta(minutes=1), event_bus=bus)  # still quiet: no second event
    assert again.offline == [] and [n for n in _names(bus) if n.startswith("worker_")] == ["worker_offline"]

    db_session.get(Entries, quiet.id).data_json = {
        "last_seen": _ago(0),
        "offline_since": NOW.isoformat(),
    }  # the heartbeat is back (it merges, so the mark stays)
    db_session.flush()
    back = worker_health.check(db_session, NOW + timedelta(minutes=2), event_bus=bus)
    assert back.online == ["quiet"]
    assert [n for n in _names(bus) if n.startswith("worker_")] == ["worker_offline", "worker_online"]
