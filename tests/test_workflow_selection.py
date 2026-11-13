"""What a manual workflow would act on before it runs (`POST /api/automations/selection`, services/automation/selection.py):
the entries its first step, a `collect`, gathers with the inputs a page would run it with. A guided setup's run step lists
them above its button, so the list is the workflow's own and the two cannot drift apart."""

import uuid

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_workflow_library_api import _sign_in, ws  # noqa: F401 — the fixture

SELECTION = "/api/automations/selection"
STORY_INPUT = {"type": "manual", "inputs": [{"name": "story", "label": "Story", "type": "entry", "required": True}]}
# The issues of one campaign that have a body and are not marked done, oldest first, two at a time.
GATHER = {
    "kind": "collect",
    "id": "items",
    "entity": "entry",
    "limit": 2,
    "query": {
        "entry_type": "newsletter-issue",
        "data": {"preview": "${entry.slug}"},
        "where": [{"field": "body", "op": "exists"}, {"field": "utm", "op": "neq", "value": "done"}],
        "sort": {"by": "created_at", "direction": "asc"},
    },
}


def _workflow(ws, actions: list, *, trigger=None, slug="make-them", enabled=True, **extra):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {"trigger": trigger or STORY_INPUT, "actions": actions, **extra}
    row = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Make them", slug=slug, enabled=enabled, definition=definition)
    ws.session.add(row)
    ws.session.commit()
    return row


def _entry(ws, type_slug: str, title: str, data: dict):  # noqa: F811
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.entries import Entries

    entry_type = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug=type_slug).one()
    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=entry_type.id, title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status="draft", data_json=data,
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.commit()
    return entry


@pytest.fixture
def story(ws):  # noqa: F811
    """A campaign with five issues: three waiting (a body, not done), one with no body, one done. Another campaign's issue."""
    campaign = _entry(ws, "campaign", "Spring", {})
    s = campaign.slug
    waiting = [_entry(ws, "newsletter-issue", f"Issue {n}", {"preview": s, "body": "words"}) for n in (1, 2, 3)]
    _entry(ws, "newsletter-issue", "No body", {"preview": s})
    _entry(ws, "newsletter-issue", "Done one", {"preview": s, "body": "words", "utm": "done"})
    _entry(ws, "newsletter-issue", "Elsewhere", {"preview": "another-campaign", "body": "words"})
    return campaign, waiting


def _select(body: dict, status: int = 200) -> dict:
    res = TestClient(app).post(SELECTION, json=body)
    assert res.status_code == status, res.text
    return res.json()


def test_an_editor_sees_the_next_ones_the_workflow_would_gather(ws, story):  # noqa: F811
    campaign, waiting = story
    _workflow(ws, [GATHER])
    _sign_in(ws.gid, WorkspaceRole.EDITOR)

    found = _select({"slug": "make-them", "inputs": {"story": campaign.slug}})

    assert found["found"] is True and found["step"] == "items"
    assert (found["count"], found["total"], found["limit"]) == (2, 3, 2)
    assert found["ids"] == [str(e.id) for e in waiting[:2]]  # oldest first, as the step sorts them


def test_the_list_is_what_the_run_itself_gathers(ws, story):  # noqa: F811
    """The proof the page and the workflow cannot drift: the run's own collect returns the same entries, in the same order."""
    from marvin.services.automation.engine import run_automation_now

    campaign, _ = story
    workflow = _workflow(ws, [{**GATHER, "limit": 5}])

    ran = run_automation_now(ws.session, ws.gid, workflow, inputs={"story": campaign.slug})
    found = _select({"slug": "make-them", "inputs": {"story": campaign.slug}})

    assert [row["id"] for row in ran["result"]["rows"]] == found["ids"]
    assert ran["result"]["total"] == found["total"] == 3


def test_reasons_count_what_is_left_out_over_the_same_entries(ws, story):  # noqa: F811
    campaign, _ = story
    _workflow(ws, [GATHER])

    found = _select(
        {
            "slug": "make-them",
            "inputs": {"story": campaign.slug},
            "left_out": [
                [{"field": "body", "op": "missing"}],
                [{"field": "utm", "op": "eq", "value": "done"}],
                [{"field": "utm", "op": "eq", "value": "x"}],
            ],
        }
    )

    assert found["leftOut"] == [1, 1, 0]  # the other campaign's issue is never counted


def test_nothing_waiting_is_an_empty_list(ws):  # noqa: F811
    campaign = _entry(ws, "campaign", "Quiet", {})
    _workflow(ws, [GATHER])

    found = _select({"slug": "make-them", "inputs": {"story": campaign.slug}})

    assert (found["found"], found["count"], found["total"], found["ids"]) == (True, 0, 0, [])


def test_a_workflow_that_is_off_still_says_what_it_would_gather(ws, story):  # noqa: F811
    campaign, _ = story
    _workflow(ws, [GATHER], enabled=False)
    assert _select({"slug": "make-them", "inputs": {"story": campaign.slug}})["total"] == 3


@pytest.mark.parametrize(
    ("actions", "extra"),
    [
        ([{"kind": "approval", "message": "Go?"}, GATHER], {}),  # not its first step
        ([{**GATHER, "when": {"field": "input.story", "op": "exists"}}], {}),  # it may not run at all
        ([{**GATHER, "only_invalid": True}], {}),  # a list the query alone does not give
        ([{**GATHER, "entity": "asset", "query": {}}], {}),  # not entries
        ([{**GATHER, "query": {**GATHER["query"], "text": "${steps.before.output.text}"}}], {}),  # reads an earlier step
        ([GATHER], {"target": {"entity": "entry", "query": {"entry_type": "campaign"}}}),  # runs once per target
        ([{"kind": "entry", "op": "set_metadata", "metadata": {"seen": "yes"}}], {}),  # gathers nothing
    ],
)
def test_a_workflow_that_does_not_start_by_gathering_entries_has_no_list(ws, story, actions, extra):  # noqa: F811
    campaign, _ = story
    _workflow(ws, actions, **extra)
    found = _select({"slug": "make-them", "inputs": {"story": campaign.slug}, "left_out": [[{"field": "body", "op": "missing"}]]})
    assert (found["found"], found["step"], found["ids"], found["total"], found["leftOut"]) == (False, None, [], 0, [])


def test_an_unknown_workflow_has_no_list(ws):  # noqa: F811
    assert _select({"slug": "nowhere", "inputs": {}})["found"] is False


def test_inputs_the_workflow_does_not_take_are_refused(ws, story):  # noqa: F811
    _workflow(ws, [GATHER])
    assert "Story" in _select({"slug": "make-them", "inputs": {}}, 400)["detail"]
    assert "colour" in _select({"slug": "make-them", "inputs": {"story": story[0].slug, "colour": "red"}}, 400)["detail"]


def test_a_reason_is_a_short_list_of_conditions(ws, story):  # noqa: F811
    _workflow(ws, [GATHER])
    body = {"slug": "make-them", "inputs": {"story": story[0].slug}}
    assert TestClient(app).post(SELECTION, json={**body, "left_out": [[{"field": "body", "op": "sparkle"}]]}).status_code == 422
    assert TestClient(app).post(SELECTION, json={**body, "left_out": [[]]}).status_code == 422
    assert TestClient(app).post(SELECTION, json={**body, "left_out": [[{"field": "body", "op": "missing"}]] * 5}).status_code == 422


def test_anyone_who_may_read_entries_may_ask(ws, story):  # noqa: F811
    """It says no more than an entry query would, so an author or a viewer, who may not run it, still sees the list."""
    _workflow(ws, [GATHER])
    body = {"slug": "make-them", "inputs": {"story": story[0].slug}}
    for role in (WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER):
        _sign_in(ws.gid, role)
        assert _select(body)["total"] == 3


def test_another_workspace_does_not_see_this_ones_workflow(ws, story):  # noqa: F811
    _workflow(ws, [GATHER])
    _sign_in(uuid.uuid4(), WorkspaceRole.ADMIN)
    assert _select({"slug": "make-them", "inputs": {"story": story[0].slug}})["found"] is False


def test_the_reasons_may_be_named_as_the_sdk_names_them(ws, story):  # noqa: F811
    _workflow(ws, [GATHER])
    found = _select({"slug": "make-them", "inputs": {"story": story[0].slug}, "leftOut": [[{"field": "body", "op": "missing"}]]})
    assert found["leftOut"] == [1]
