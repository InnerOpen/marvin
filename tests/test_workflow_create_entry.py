"""The create-entry step (`{"kind": "entry", "op": "create", …}`, services/automation/actions/entry.py): a new entry of a
named type, its fields typed and validated, its id for later steps, `entry_created` one reaction deeper — and the same
event handled twice makes it once.

The case: a published article gets a follow-up draft, which the next step tags with where it came from."""

import uuid

import pytest
from pydantic import ValidationError

from marvin.schemas.group.automation_definition import AutomationDefinition
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_library import _entry, _entry_doc, _fire, _runs, ws  # noqa: F401 — the fixture

CREATE = {
    "kind": "entry",
    "id": "make",
    "op": "create",
    "entry_type": "article",
    "title": "Follow-up: ${entry.title}",
    "data": {"body": "Notes for a follow-up to ${entry.title}."},
}
TAG_IT = {"kind": "entry", "op": "set_metadata", "entity_id": "${steps.make.output.entry_id}", "metadata": {"follow_up_of": "${entry.id}"}}
DEFINITION = {"trigger": {"type": "event", "event": "entry_published"}, "actions": [CREATE, TAG_IT]}


def _install(ws, definition=DEFINITION):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    assert draft_issues(ws.session, ws.gid, definition) == []
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Follow-ups", slug=f"follow-ups-{uuid.uuid4().hex[:6]}", enabled=True, definition=definition
    )
    ws.session.add(row)
    ws.session.commit()
    return row


def _follow_ups(ws):  # noqa: F811
    from marvin.db.models.platform import Entries

    return ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.title.like("Follow-up:%")).all()


@pytest.mark.parametrize(
    "change, message",
    [
        ({"title": " "}, "needs an entry_type"),
        ({"entity_slug": "x"}, "drop entity_id"),
        ({"status": "published"}, "status"),
        ({"op": "set_data", "data": {"body": "x"}}, "go with op create only"),
    ],
)
def test_a_create_step_is_held_to_its_shape(change, message):
    with pytest.raises(ValidationError, match=message):
        AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [{**CREATE, **change}]})


def test_a_draft_names_a_type_and_fields_that_exist_here(ws):  # noqa: F811
    def issues(step):
        return [i["message"] for i in draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})]

    assert "No entry type “artcle”" in issues({**CREATE, "entry_type": "artcle"})[0]
    assert "has no field colour" in issues({**CREATE, "data": {"colour": "red"}})[0]


def test_it_makes_a_draft_the_next_step_can_use_and_says_so_one_level_deeper(ws, monkeypatch):  # noqa: F811
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append((kw["event_type"].name, kw)))
    _install(ws)
    article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-1")

    (made,) = _follow_ups(ws)
    assert (made.title, made.status, made.data_json["body"]) == ("Follow-up: Engraving brass", "draft", "Notes for a follow-up to Engraving brass.")
    assert made.metadata_json["follow_up_of"] == str(article.id)  # the second step found it by ${steps.make.output.entry_id}
    created = [kw for name, kw in sent if name == "entry_created"]
    assert len(created) == 1 and created[0]["reaction_depth"] == 1


def test_the_same_event_handled_twice_makes_one_entry(ws):  # noqa: F811
    row = _install(ws)
    article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-1")
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-1")
    assert len(_follow_ups(ws)) == 1
    second = _runs(ws, row.slug)[-1]
    assert second.actions[0].output_snapshot["created"] is False

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-2")  # a new publish
    assert len(_follow_ups(ws)) == 2


def test_fields_the_type_refuses_fail_the_step_and_nothing_is_made(ws):  # noqa: F811
    # The template resolves to nothing, so the new entry would have no body — and article's body is required.
    row = _install(ws, {**DEFINITION, "actions": [{**CREATE, "data": {"body": "${entry.data.missing}"}}]})
    article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-1")

    (run,) = _runs(ws, row.slug)
    assert run.status == "failed" and "rejected" in run.actions[0].error
    assert _follow_ups(ws) == []


def test_a_dry_run_previews_and_makes_nothing(ws):  # noqa: F811
    from marvin.services.automation.engine import dry_run_for_event

    row = _install(ws)
    article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})

    result = dry_run_for_event(ws.session, ws.gid, row, _entry_doc(article) | {"event_type": "entry_published", "entry_id": str(article.id)})

    step = next(s for s in result["plan"] if s["kind"] == "entry")
    assert step["resolved"]["title"] == "Follow-up: Engraving brass" and step["resolved"]["status"] == "draft"
    assert _follow_ups(ws) == []
