"""One run of a workflow on an entry at a time (engine `_entry_turn`, db/models/groups/workflow_entry_locks.py).

The case: Grace's re-list ran while the retries of an earlier, failed re-list were still going. Two runs of
"Square: list for sale" on "Gathering Static 1" both read it unlisted and both created a Square item. Now the second
waits for its turn, reads the entry again, finds it listed, and doesn't run."""

import uuid
from datetime import UTC, datetime, timedelta

from marvin.services.automation import engine
from tests.test_workflow_library import _entry, _entry_doc, _fire, _reload, ws  # noqa: F401 — the fixture

LIST_FOR_SALE = {
    "trigger": {"type": "event", "event": "entry_updated"},
    "conditions": [{"field": "entry.metadata.listed", "op": "neq", "value": "yes"}],
    "actions": [{"kind": "entry", "op": "set_metadata", "metadata": {"listed": "yes", "listed_by": "${event.correlation_id}"}}],
}


def _workflow(ws):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="List", slug=f"list-{uuid.uuid4().hex[:6]}", enabled=True, definition=LIST_FOR_SALE
    )
    ws.session.add(row)
    ws.session.commit()
    return row


def _hold(ws, workflow, entry, *, holder="other", seconds=60):  # noqa: F811
    from marvin.db.models.groups.workflow_entry_locks import WorkflowEntryLockModel

    ws.session.add(
        WorkflowEntryLockModel(
            session=ws.session,
            automation_id=workflow.id,
            entry_id=entry.id,
            holder=holder,
            lease_until=datetime.now(UTC) + timedelta(seconds=seconds),
        )
    )
    ws.session.commit()


def _release_when_waited(ws, monkeypatch, then):  # noqa: F811
    """The other run finishes the first time this one waits: `then()` is what it did, and its turn ends."""
    from marvin.db.models.groups.workflow_entry_locks import WorkflowEntryLockModel

    def finish_other_run(_seconds):
        then()
        ws.session.query(WorkflowEntryLockModel).filter_by(holder="other").delete()
        ws.session.commit()

    # The engine's own `sleep` (not time.sleep: that is global, and any other thread or concurrent test calling it would
    # run `then()` and delete the lock out from under this one).
    monkeypatch.setattr(engine, "sleep", finish_other_run)


def test_a_run_waits_for_its_turn_and_skips_an_entry_the_other_run_already_handled(ws, monkeypatch):  # noqa: F811
    workflow = _workflow(ws)
    piece = _entry(ws, "article", "Gathering Static 1", data={"body": "x"})
    _hold(ws, workflow, piece)

    def other_run_lists_it():
        row = _reload(ws, piece)
        row.metadata_json = {"listed": "yes", "listed_by": "other"}
        ws.session.commit()

    _release_when_waited(ws, monkeypatch, other_run_lists_it)
    _fire(ws, "entry_updated", _entry_doc(piece), entity=piece.id, entity_type="entry", correlation_id="relist-2")

    assert _reload(ws, piece).metadata_json["listed_by"] == "other"  # listed once, by the run that had the turn
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel

    assert ws.session.query(AutomationActionExecutionModel).filter_by(group_id=ws.gid).count() == 0  # nothing ran


def test_when_the_other_run_changed_nothing_this_one_goes_on(ws, monkeypatch):  # noqa: F811
    workflow = _workflow(ws)
    piece = _entry(ws, "article", "Held in Motion", data={"body": "x"})
    _hold(ws, workflow, piece)
    _release_when_waited(ws, monkeypatch, lambda: None)

    _fire(ws, "entry_updated", _entry_doc(piece), entity=piece.id, entity_type="entry", correlation_id="relist-3")

    assert _reload(ws, piece).metadata_json["listed_by"] == "relist-3"


def test_a_lease_that_ran_out_is_taken_over_and_a_turn_is_given_back(ws):  # noqa: F811
    from marvin.db.models.groups.workflow_entry_locks import WorkflowEntryLockModel

    workflow = _workflow(ws)
    piece = _entry(ws, "article", "Web of Bloom", data={"body": "x"})
    _hold(ws, workflow, piece, holder="crashed", seconds=-5)

    assert engine._take_turn(ws.session, workflow.id, piece.id, "mine")  # the crashed worker's lease ran out
    assert not engine._take_turn(ws.session, workflow.id, piece.id, "theirs")  # held now
    with engine._entry_turn(ws.session, SimpleWorkflow(workflow.id), uuid.uuid4()) as waited:  # another entry: free
        assert waited is False
    assert ws.session.query(WorkflowEntryLockModel).filter_by(automation_id=workflow.id).count() == 1  # only "mine" is left


class SimpleWorkflow:
    def __init__(self, id):
        self.id = id
        self.slug = "w"
