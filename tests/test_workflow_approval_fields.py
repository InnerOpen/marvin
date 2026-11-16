"""An approval's boxes (`fields`, services/automation/approvals.py): the text a paid step will send is shown, may be
changed before approving, and the step after it sends what was approved — byte for byte what it would have sent when
nobody changed it. A Redo with changes hands the changed text to the next try on the same entry; `approved_when` goes
on without asking (a page already asked); what a run makes records who approved it and that the prompt was changed.

The case: a sound is made from its description by a paid integration action, after a person approves."""

import pytest

from marvin.services.automation import approvals
from marvin.services.automation.authoring import draft_issues
from marvin.services.automation.authz import ROLE_EDITOR
from tests.test_workflow_approvals import _install, _published, _runs, _waiting, signoff  # noqa: F401 — the fixture
from tests.test_workflow_library import _entry_doc, _fire, _reload, ws  # noqa: F401 — the fixture

# Spaces and line breaks at either end are part of the text: the box holds exactly what the step after it sends.
PROMPT = "  A knife chopping “${entry.title}”, close up.\n"
SENT = "  A knife chopping “Onions”, close up.\n"
APPROVED = {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}
SEND = {
    "kind": "integration",
    "integration": "signoff",
    "action": "send_contract",
    "args": {"to": "${steps.ok.output.fields.prompt}"},
    "when": APPROVED,
}
ASK = {"kind": "approval", "id": "ok", "message": "Make “${entry.title}”?", "fields": [{"name": "prompt", "label": "Prompt", "value": PROMPT}]}


def _flow(*steps, trigger="entry_published") -> dict:
    return {"trigger": {"type": "event", "event": trigger}, "actions": list(steps)}


def _ask(ws, title="Onions", correlation="c-1"):  # noqa: F811
    article = _published(ws, title)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=correlation)
    return article, _waiting(ws)


def _decide(ws, row, decision="approve", **kw):  # noqa: F811
    return approvals.decide(ws.session, ws.gid, row.id, decision, user_id=ws.uid, role=ROLE_EDITOR, **kw)


# ── asked, approved as it is, or changed ─────────────────────────────────────


def test_the_box_is_asked_with_the_exact_text_and_unchanged_is_sent_byte_for_byte(ws, signoff):  # noqa: F811
    workflow = _install(ws, _flow(ASK, SEND))
    _, row = _ask(ws)

    (field,) = row.fields
    assert (field["name"], field["label"], field["type"], field["value"]) == ("prompt", "Prompt", "textarea", SENT)
    _decide(ws, row, fields={"prompt": SENT.replace("\n", "\r\n")})  # a browser's form sends \r\n: the same text

    assert signoff.calls == [("send_contract", {"to": SENT})]
    resumed = _runs(ws, workflow)[-1]
    assert resumed.actions[0].output_snapshot["fields"] == {"prompt": SENT} and resumed.actions[0].output_snapshot["edited"] == []
    ws.session.refresh(row)
    assert approvals.edited_names(row) == []


def test_a_changed_box_is_what_the_next_step_sends_and_the_event_names_it_without_the_text(ws, signoff, monkeypatch):  # noqa: F811
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    workflow = _install(ws, _flow(ASK, SEND))
    _, row = _ask(ws)

    _decide(ws, row, fields={"prompt": "A cleaver on a board, slow."})

    assert signoff.calls == [("send_contract", {"to": "A cleaver on a board, slow."})]
    output = _runs(ws, workflow)[-1].actions[0].output_snapshot
    assert output["fields"] == {"prompt": "A cleaver on a board, slow."} and output["edited"] == ["prompt"]
    ws.session.refresh(row)
    assert row.fields[0]["value"] == SENT and row.field_values == {"prompt": "A cleaver on a board, slow."}  # both kept
    (decided,) = [kw["document_data"] for kw in sent if kw["event_type"].name == "workflow_approval_decided"]
    assert decided.edited_fields == ["prompt"] and "cleaver" not in decided.model_dump_json()


def test_a_deny_ignores_the_changes_and_the_run_reads_the_box_as_asked(ws, signoff):  # noqa: F811
    noted = {"kind": "entry", "op": "set_metadata", "metadata": {"was": "${steps.ok.output.fields.prompt}"}}
    _install(ws, _flow(ASK, SEND, noted))
    article, row = _ask(ws)

    _decide(ws, row, "deny", fields={"prompt": "Something else"})

    assert signoff.calls == [] and _reload(ws, article).metadata_json["was"] == SENT
    ws.session.refresh(row)
    assert row.field_values is None and approvals.edited_names(row) == []


@pytest.mark.parametrize(
    ("given", "says"),
    [
        ({"tone": "x"}, "has no field “tone”"),
        ({"prompt": 3}, "must be text"),
        ({"prompt": "   "}, "can't be empty"),
        ({"prompt": "x" * 41}, "at most 40"),
        ({"prompt": "{{ OPENAI_KEY }}"}, "can't take {{ OPENAI_KEY }}"),
        ({"prompt": "Read ${vars.TOKEN} aloud"}, "can't take ${"),
    ],
)
def test_a_box_that_cant_be_taken_is_refused_and_the_approval_still_waits(ws, signoff, given, says):  # noqa: F811
    ask = {**ASK, "fields": [{"name": "prompt", "value": PROMPT, "max_length": 40}]}
    _install(ws, _flow(ask, SEND))
    _, row = _ask(ws)

    with pytest.raises(approvals.ApprovalError) as refused:
        _decide(ws, row, fields=given)

    assert refused.value.status == 422 and says in str(refused.value)
    ws.session.refresh(row)
    assert row.status == "pending" and signoff.calls == []


def test_the_one_leading_line_break_a_text_box_drops_is_not_a_change(ws, signoff):  # noqa: F811
    ask = {**ASK, "fields": [{"name": "prompt", "value": "\nLine one\nLine two"}]}
    _install(ws, _flow(ask, SEND))
    _, row = _ask(ws)

    _decide(ws, row, fields={"prompt": "Line one\r\nLine two"})

    assert signoff.calls == [("send_contract", {"to": "\nLine one\nLine two"})]


def test_a_box_too_long_to_show_fails_the_step(ws, signoff):  # noqa: F811
    ask = {**ASK, "fields": [{"name": "prompt", "value": "${entry.data.body}"}]}
    workflow = _install(ws, _flow(ask, SEND))
    article = _published(ws, "Long")
    article.data_json = {"body": "x" * 20_001}
    ws.session.commit()

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

    (run,) = _runs(ws, workflow)
    assert run.status == "failed" and "at most 20,000" in run.actions[0].error
    assert approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == []


# ── Redo with changes ────────────────────────────────────────────────────────

REDO = {**ASK, "choices": ["Keep", "Redo"], "redo": "Redo"}


def test_a_redo_with_changes_starts_the_next_try_from_them_once(ws, signoff):  # noqa: F811
    _install(ws, _flow(REDO))
    article, row = _ask(ws)

    _decide(ws, row, choice="Redo", fields={"prompt": "Slower, wetter."})
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="c-2")
    again = _waiting(ws)

    assert (again.fields[0]["value"], again.fields[0].get("carried")) == ("Slower, wetter.", True)
    _decide(ws, again, choice="Redo")  # unchanged this time: nothing to carry
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="c-3")
    assert _waiting(ws).fields[0]["value"] == SENT  # used once: the step's own text again


def test_keep_with_a_change_carries_nothing(ws, signoff):  # noqa: F811
    _install(ws, _flow(REDO))
    article, row = _ask(ws)

    _decide(ws, row, choice="Keep", fields={"prompt": "Slower, wetter."})
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="c-2")

    assert _waiting(ws).fields[0]["value"] == SENT


def test_a_carried_text_belongs_to_its_entry(ws, signoff):  # noqa: F811
    _install(ws, _flow(REDO))
    _, row = _ask(ws, "Onions")
    _decide(ws, row, choice="Redo", fields={"prompt": "Slower, wetter."})

    _ask(ws, "Leeks", correlation="c-2")

    assert _waiting(ws).fields[0]["value"] == "  A knife chopping “Leeks”, close up.\n"


# ── a page already asked: approved_when ──────────────────────────────────────


def test_approved_when_goes_on_without_asking_with_the_boxes_as_they_are(ws, signoff):  # noqa: F811
    noted = {"kind": "entry", "op": "set_metadata", "metadata": {"was": "${steps.ok.output.fields.prompt}", "how": "${steps.ok.output.decision}"}}
    asked_on_the_page = {**ASK, "approved_when": {"field": "entry.metadata.spend_approved", "op": "eq", "value": "yes"}}
    workflow = _install(ws, _flow(asked_on_the_page, noted))
    article = _published(ws, "Onions")
    article.metadata_json = {"spend_approved": "yes"}
    ws.session.commit()

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

    assert approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == []
    assert _reload(ws, article).metadata_json["was"] == SENT and _reload(ws, article).metadata_json["how"] == "approved"
    (run,) = _runs(ws, workflow)
    assert run.status == "success" and run.actions[0].output_snapshot["auto"] is True


def test_approved_when_is_no_persons_approval(ws, signoff):  # noqa: F811
    asked_on_the_page = {**ASK, "approved_when": {"field": "entry.title", "op": "eq", "value": "Onions"}}
    workflow = _install(ws, _flow(asked_on_the_page, {**SEND, "when": None}))

    _fire(ws, "entry_published", _entry_doc(_published(ws, "Onions")), entity=None, entity_type="entry")

    (run,) = _runs(ws, workflow)
    assert signoff.calls == [] and "requires approval" in (run.actions[-1].error or "")


# ── a dry run, and the step's own checks ─────────────────────────────────────


def test_a_dry_run_shows_the_boxes_and_the_step_after_reads_them(ws, signoff):  # noqa: F811
    from marvin.services.automation.engine import dry_run_for_event

    workflow = _install(ws, _flow(ASK, {**SEND, "when": None}))
    article = _published(ws, "Onions")

    result = dry_run_for_event(ws.session, ws.gid, workflow, _entry_doc(article) | {"event_type": "entry_published", "entry_id": str(article.id)})

    ask, call = result["plan"]
    assert ask["resolved"]["fields"] == {"prompt": SENT} and call["resolved"]["args"] == {"to": SENT}
    assert approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == [] and signoff.calls == []


@pytest.mark.parametrize(
    ("step", "says"),
    [
        ({**ASK, "choices": ["Keep", "Redo"], "redo": "Again"}, "redo must be one of the choices"),
        ({**ASK, "fields": None, "choices": ["Keep", "Redo"], "redo": "Redo"}, "give the step `fields`"),
        ({**ASK, "fields": [{"name": "prompt"}, {"name": "prompt"}]}, "its own name"),
        ({**ASK, "fields": [{"name": "Prompt Text"}]}, "pattern"),
        ({**ASK, "fields": [{"name": f"f{i}"} for i in range(5)]}, "at most 4"),
        ({**ASK, "fields": [{"name": "prompt", "max_length": 20_001}]}, "20000"),
    ],
)
def test_a_step_with_boxes_that_dont_fit_is_refused_on_save(ws, step, says):  # noqa: F811
    issues = draft_issues(ws.session, ws.gid, _flow(step))
    assert any(says in i["message"] for i in issues), issues
