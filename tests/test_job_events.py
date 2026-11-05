"""A worker job's life as events: a `job` entry's status changing is also job_queued / job_claimed / job_started / job_done / job_failed."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from marvin.schemas.platform import EntryUpdate
from marvin.services.entries import EntryService
from marvin.services.events.event_catalog import CATALOG_BY_TYPE, CATEGORIES

JOB_EVENTS = ("job_queued", "job_claimed", "job_started", "job_done", "job_failed")


class _Bus:
    def __init__(self):
        self.sent = []

    def dispatch(self, *, event_type, document_data=None, message=None, entity_id=None, **_):
        self.sent.append((event_type.name, message, document_data))


class _Entries:
    """One entry whose data can change; get_one returns a snapshot, so what it was differs from what it is."""

    def __init__(self, status):
        self.state = {"id": uuid4(), "title": "Audio cut: The Last Onion", "status": "draft", "group_id": uuid4(), "created_by": None, "entry_type_id": "T", "data_json": {"kind": "audio-cut", "status": status}}

    def _snap(self):
        return SimpleNamespace(**{**self.state, "data_json": dict(self.state["data_json"])})

    def get_one(self, _id):
        return self._snap()

    def update(self, _id, data):
        if getattr(data, "data_json", None) is not None:
            self.state["data_json"] = dict(data.data_json)
        return self._snap()

    def create(self, _data):
        return self._snap()


def _service(type_slug, status="queued"):
    bus, entries = _Bus(), _Entries(status)
    repos = SimpleNamespace(
        entries=entries,
        entry_types=SimpleNamespace(get_one=lambda _id: SimpleNamespace(slug=type_slug)),
        groups=SimpleNamespace(get_one=lambda _id: SimpleNamespace(name="W")),
        users=SimpleNamespace(get_one=lambda _id: None),
    )
    svc = EntryService.__new__(EntryService)
    svc.repos, svc.group_id, svc.actor_id, svc.integration_id, svc._event_bus, svc.session = repos, "G", None, None, bus, SimpleNamespace()
    svc._sync_linked_fields = lambda e, **_: e  # no linked fields in this unit test
    return svc, bus, entries


def _names(bus):
    return [name for name, *_ in bus.sent]


def test_a_job_made_queued_sends_job_queued_after_entry_created():
    svc, bus, _ = _service("job", "queued")
    svc.create({"title": "x"})
    assert _names(bus) == ["entry_created", "job_queued"]


@pytest.mark.parametrize(("status", "event"), [("claimed", "job_claimed"), ("running", "job_started"), ("done", "job_done"), ("failed", "job_failed")])
def test_a_job_changing_status_sends_that_jobs_event_after_entry_updated(status, event):
    svc, bus, entries = _service("job", "queued")
    svc.update(entries.state["id"], EntryUpdate(data_json={"kind": "audio-cut", "status": status}))
    assert _names(bus) == ["entry_updated", event]
    name, message, data = bus.sent[-1]
    assert "Audio cut" in message and data.entry_type == "job" and "data.status" in data.changed_fields and data.after["data"]["status"] == status


def test_a_job_edited_without_its_status_changing_sends_no_job_event():
    svc, bus, entries = _service("job", "running")
    svc.update(entries.state["id"], EntryUpdate(data_json={"kind": "audio-cut", "status": "running", "log": "pulled 3 files"}))
    assert _names(bus) == ["entry_updated"]


def test_an_entry_of_another_type_with_a_status_field_sends_no_job_event():
    svc, bus, entries = _service("beat", "queued")  # a beat is also `queued` while a still is made
    svc.update(entries.state["id"], EntryUpdate(data_json={"status": "made"}))
    svc.create({"title": "x"})
    assert not [n for n in _names(bus) if n.startswith("job_")]


def test_the_job_events_are_catalogued_as_workers_events_a_workflow_can_start_on():
    assert "Workers" in CATEGORIES
    for name in JOB_EVENTS:
        entry = CATALOG_BY_TYPE[name]
        assert entry.category == "Workers" and entry.triggerable and entry.sent_by
