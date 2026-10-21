"""The validator reads inside `all` / `any` / `not` condition groups (the engine's matcher evaluates them) — a group
has no `field` of its own, so it must not be warned about; its leaves are checked like any other condition."""

from marvin.services.automation.validation import validate_definition

ENTRY = {"trigger": {"type": "event", "event": "entry_created"}}


def _msgs(conditions, trigger=None):
    definition = {**(trigger or ENTRY), "conditions": conditions, "actions": [{"kind": "emit_event", "event": "x"}]}
    return [i["message"] for i in validate_definition(definition)]


def test_valid_groups_do_not_warn():
    exists = {"field": "entry.metadata.image_suggestion", "op": "exists"}
    conditions = [
        {"not": exists},
        {"any": [{"field": "entry.type", "op": "eq", "value": "a"}, {"all": [exists, {"not": exists}]}]},
        {"all": [exists]},
    ]
    assert _msgs(conditions) == []


def test_a_field_less_leaf_inside_a_group_still_warns():
    for group in ({"not": {}}, {"any": [{"field": "entry.title", "op": "exists"}, {}]}, {"all": [{"op": "eq", "value": 1}]}):
        assert any("has no field" in m for m in _msgs([group])), group


def test_leaves_inside_groups_are_checked_like_top_level_ones():
    assert any("no entry" in m for m in _msgs([{"not": {"field": "entry.title", "op": "exists"}}], {"trigger": {"type": "manual"}}))
    assert any("Unknown condition operator" in m for m in _msgs([{"any": [{"field": "entry.title", "op": "bogus"}]}]))
    assert any("step outputs" in m for m in _msgs([{"all": [{"field": "steps.a.output.x", "op": "exists"}]}]))


def test_a_plain_empty_condition_still_warns():
    assert any("has no field" in m for m in _msgs([{}]))
