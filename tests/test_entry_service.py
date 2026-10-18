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
        self.state = {"id": uuid4(), "title": "T", "status": status, "group_id": uuid4(), "created_by": None, "entry_type_id": None, "data_json": {}}
        self.deleted = False

    def _snap(self):
        return SimpleNamespace(**self.state)

    def get_one(self, _id):
        return self._snap()

    def update(self, _id, data):
        st = getattr(data, "status", None)
        if st:
            self.state["status"] = st
        if getattr(data, "data_json", None) is not None:
            self.state["data_json"] = dict(data.data_json)
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


# ── Type fields in the diff: `changed_fields contains data.price`, `${event.before.data.price}` ───────────────────


def _set_data(svc, data):
    svc.repos.entries.state["data_json"] = data


def test_a_changed_data_field_is_named_with_its_values():
    svc, bus = _svc("draft")
    _set_data(svc, {"price": 5, "sku": "A1"})
    svc.update("id", EntryUpdate(data_json={"price": 7, "sku": "A1"}))
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == ["data.price"]  # sku is the same: not named
    assert doc.before == {"data": {"price": 5}} and doc.after == {"data": {"price": 7}}


def test_status_and_data_changes_share_one_diff_on_every_event():
    svc, bus = _svc("draft")
    _set_data(svc, {"price": 5})
    svc.update("id", EntryUpdate(status="published", data_json={"price": 6}))
    for name in ("entry_updated", "entry_published"):
        assert bus.docs[name].changed_fields == ["status", "data.price"]
        assert bus.docs[name].after == {"status": "published", "data": {"price": 6}}


def test_a_new_and_a_cleared_field_read_as_none_on_the_other_side():
    svc, bus = _svc("draft")
    _set_data(svc, {"gone": "x"})
    svc.update("id", EntryUpdate(data_json={"new": "y"}))
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == ["data.gone", "data.new"]
    assert doc.before == {"data": {"gone": "x", "new": None}} and doc.after == {"data": {"gone": None, "new": "y"}}


def test_unchanged_data_adds_nothing():
    svc, bus = _svc("draft")
    _set_data(svc, {"price": 5})
    svc.update("id", EntryUpdate(data_json={"price": 5}))
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == [] and doc.before == {} and doc.after == {}


def test_long_text_lists_and_secret_like_fields_are_named_but_elided():
    from marvin.services.entries.entry_service import DATA_VALUE_MAX_CHARS, ELIDED

    svc, bus = _svc("draft")
    old = {"body": "x" * (DATA_VALUE_MAX_CHARS + 1), "tags": ["a"], "api_key": "k-1", "note": "short"}
    _set_data(svc, old)
    svc.update("id", EntryUpdate(data_json={"body": "y" * 500, "tags": ["a", "b"], "api_key": "k-2", "note": "still short"}))
    doc = bus.docs["entry_updated"]
    assert doc.changed_fields == ["data.api_key", "data.body", "data.note", "data.tags"]  # every change is named
    assert doc.before["data"] == {"api_key": ELIDED, "body": ELIDED, "note": "short", "tags": ELIDED}
    assert doc.after["data"] == {"api_key": ELIDED, "body": ELIDED, "note": "still short", "tags": ELIDED}
    assert "k-2" not in str(doc.after) and "y" * 20 not in str(doc.after)


def test_a_flood_of_changed_fields_is_capped():
    from marvin.services.entries.entry_service import DATA_NAMES_MAX, DATA_VALUES_MAX

    svc, bus = _svc("draft")
    _set_data(svc, {})
    svc.update("id", EntryUpdate(data_json={f"f{i:03d}": i for i in range(DATA_NAMES_MAX + 20)}))
    doc = bus.docs["entry_updated"]
    assert len(doc.changed_fields) == DATA_NAMES_MAX and len(doc.after["data"]) == DATA_VALUES_MAX


def test_the_webhook_payload_carries_the_data_diff():
    # An outgoing webhook sends the event's document data as JSON: the diff rides in `before`/`after` as plain dicts.
    from fastapi.encoders import jsonable_encoder

    svc, bus = _svc("draft")
    _set_data(svc, {"price": 5})
    svc.update("id", EntryUpdate(data_json={"price": 7}))
    sent = jsonable_encoder(bus.docs["entry_updated"], by_alias=True)
    assert sent["changedFields"] == ["data.price"] and sent["after"] == {"data": {"price": 7}}
