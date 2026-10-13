"""Unit tests for EntryService — the entry domain service that owns mutation + event emission.

The headline is the bug the extraction fixes: an automation write-back that flips an entry to
published must now emit `entry_published` (not just a bare `entry_updated`), so chained automations
keying on publish fire. Tests use a fake repo + a spy event bus, so no DB is needed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from marvin.schemas.platform import EntryUpdate
from marvin.services.entries import EntryService


class _SpyBus:
    def __init__(self):
        self.events = []  # (event_name, reaction_depth, integration_id)
        self.docs = {}  # event_name -> document_data
        self.correlations = []  # the ambient correlation id in effect at each dispatch

    def dispatch(self, *, event_type, reaction_depth=0, integration_id=None, document_data=None, **_):
        from marvin.services.event_bus_service.correlation import current_correlation_id

        self.events.append((event_type.name, reaction_depth, integration_id))
        self.docs[event_type.name] = document_data
        self.correlations.append(current_correlation_id.get())


class _FakeEntries:
    """A single entry whose status can change; get_one returns a snapshot so old != new."""

    def __init__(self, status="draft"):
        self.state = {"id": uuid4(), "title": "T", "status": status, "group_id": uuid4(), "created_by": None, "entry_type_id": None}
        self.deleted = False

    def _snap(self):
        return SimpleNamespace(**self.state)

    def get_one(self, _id):
        return self._snap()

    def update(self, _id, data):
        st = getattr(data, "status", None)
        if st:
            self.state["status"] = st
        return self._snap()

    def apply_fields(self, _id, fields):
        if "status" in fields:
            self.state["status"] = fields["status"]

    def create(self, _data):
        return self._snap()

    def apply_suggestion(self, _id):
        return self._snap()

    def delete(self, _id):
        self.deleted = True


class _FakeRepos:
    def __init__(self, status="draft"):
        self.entries = _FakeEntries(status)
        self.entry_types = SimpleNamespace(get_one=lambda _id: None)
        self.groups = SimpleNamespace(get_one=lambda _id: SimpleNamespace(name="WS"))
        self.users = SimpleNamespace(get_one=lambda _id: SimpleNamespace(full_name="Jane"))


def _svc(status="draft", integration_id="entry_management"):
    bus = _SpyBus()
    svc = EntryService(MagicMock(), "G", event_bus=bus, actor_id=None, integration_id=integration_id)
    svc.repos = _FakeRepos(status)
    return svc, bus


def _names(bus):
    return [e[0] for e in bus.events]


def test_update_to_published_emits_updated_then_published():
    svc, bus = _svc("draft")
    svc.update("id", EntryUpdate(status="published"))
    assert _names(bus) == ["entry_updated", "entry_published"]  # order matters (embedding reaction)


def test_writeback_status_change_emits_the_transition_event():
    # THE FIX: the old write-back only emitted entry_updated, so publish-chains never fired.
    svc, bus = _svc("draft", integration_id="automation")
    svc.apply_fields("id", {"status": "published"}, reaction_depth=1)
    assert _names(bus) == ["entry_updated", "entry_published"]
    # loop-guard depth threaded, and tagged as automation-sourced
    assert all(e[1] == 1 and e[2] == "automation" for e in bus.events)


def test_writeback_without_status_change_emits_only_updated():
    svc, bus = _svc("published", integration_id="automation")
    svc.apply_fields("id", {"summary": "a tidy summary"}, reaction_depth=1)
    assert _names(bus) == ["entry_updated"]


def test_update_batch_shares_one_correlation_id():
    # entry_updated + entry_published from one publish belong to one chain → one correlation id.
    svc, bus = _svc("draft")
    svc.update("id", EntryUpdate(status="published"))
    assert _names(bus) == ["entry_updated", "entry_published"]
    assert len(set(bus.correlations)) == 1 and bus.correlations[0] is not None


def test_update_inherits_the_ambient_chain_when_inside_a_run():
    # Within an automation run (ambient scope set), the emit batch inherits the run's id, not a new one.
    from marvin.services.event_bus_service.correlation import correlation_scope

    svc, bus = _svc("draft", integration_id="automation")
    with correlation_scope("run-chain"):
        svc.apply_fields("id", {"status": "published"}, reaction_depth=1)
    assert bus.correlations == ["run-chain", "run-chain"]


def test_unpublish_emits_unpublished():
    svc, bus = _svc("published")
    svc.update("id", EntryUpdate(status="draft"))
    assert _names(bus) == ["entry_updated", "entry_unpublished"]


def test_archive_and_restore():
    svc, bus = _svc("draft")
    svc.update("id", EntryUpdate(status="archived"))
    assert _names(bus) == ["entry_updated", "entry_archived"]

    svc2, bus2 = _svc("archived")
    svc2.update("id", EntryUpdate(status="draft"))
    assert _names(bus2) == ["entry_updated", "entry_restored"]


def test_create_emits_created():
    svc, bus = _svc("draft")
    svc.create({"title": "x", "created_by": None})
    assert _names(bus) == ["entry_created"]


def test_delete_emits_then_deletes():
    svc, bus = _svc("draft")
    assert svc.delete("id") is True
    assert _names(bus) == ["entry_deleted"]
    assert svc.repos.entries.deleted is True


def test_update_carries_scalar_diff():
    # The headline: a status change is expressible as event.after.status.
    svc, bus = _svc("draft")
    svc.update("id", EntryUpdate(status="needs_review"))
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == ["status"]
    assert doc.before == {"status": "draft"} and doc.after == {"status": "needs_review"}
    # a non-lifecycle status change still emits (only entry_updated — needs_review isn't publish/archive)
    assert _names(bus) == ["entry_updated"]


def test_no_change_has_empty_diff():
    svc, bus = _svc("draft")
    svc.update("id", EntryUpdate())  # nothing changes
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == [] and doc.before == {} and doc.after == {}


def test_writeback_publish_diff_on_both_events():
    svc, bus = _svc("draft", integration_id="automation")
    svc.apply_fields("id", {"status": "published"}, reaction_depth=1)
    assert bus.docs["entry_published"].after == {"status": "published"}
    assert bus.docs["entry_updated"].changed_fields == ["status"]


def test_missing_entry_is_a_noop():
    svc, bus = _svc("draft")
    svc.repos.entries.get_one = lambda _id: None
    assert svc.update("id", EntryUpdate(status="published")) is None
    assert svc.delete("id") is False
    assert bus.events == []
