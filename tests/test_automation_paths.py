"""Workflow template paths: list indexes, and the stored metadata a workflow reads off an entry.

Square's inventory webhook puts its record in `data.object.inventory_counts[0]`, and closing a sold
artwork's payment link needs the link id an earlier workflow stored in the entry's metadata.
"""

from types import SimpleNamespace

from marvin.services.automation import engine
from marvin.services.automation.matcher import interpolate, resolve_path

PAYLOAD = {"event": {"payload": {"data": {"object": {"inventory_counts": [{"catalog_object_id": "VAR1", "quantity": "0"}]}}}}}


def test_resolve_path_numeric_hop_indexes_a_list():
    assert resolve_path("event.payload.data.object.inventory_counts.0.catalog_object_id", PAYLOAD) == "VAR1"


def test_resolve_path_index_past_the_end_is_none():
    assert resolve_path("event.payload.data.object.inventory_counts.3.quantity", PAYLOAD) is None


def test_interpolate_braced_list_path_keeps_the_value():
    assert interpolate("${event.payload.data.object.inventory_counts.0.quantity}", PAYLOAD) == "0"


def test_entry_context_carries_metadata():
    entry = SimpleNamespace(
        id="e1",
        group_id="G",
        entry_type=None,
        status="published",
        title="T",
        slug="t",
        summary=None,
        data_json={"status": "sold"},
        metadata_json={"square_payment_link_id": "PL1"},
    )
    ctx = engine._entry_context(SimpleNamespace(get=lambda m, e: entry), "G", "e1")
    assert ctx["metadata"] == {"square_payment_link_id": "PL1"}


def test_entry_context_without_metadata_is_empty_dict():
    entry = SimpleNamespace(id="e1", group_id="G", entry_type=None, status="draft", title="T", slug="t", summary=None, data_json=None)
    assert engine._entry_context(SimpleNamespace(get=lambda m, e: entry), "G", "e1")["metadata"] == {}
