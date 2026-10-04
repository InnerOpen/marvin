"""A workflow never reacts to an event its own run caused.

An entry step's write emits entry_updated synchronously, inside the run that made it. The workflow that
wrote it must sit that event out — and any event a reaction to its run caused — while other workflows
react as usual, and a later, independent event still triggers it. (Before, a Square close workflow that
sets metadata re-entered itself until the reaction-depth guard stopped it.)
"""

import uuid

from pytest import fixture

from marvin.services.automation.engine import run_automations_for_event

UPDATED = {"trigger": {"type": "event", "event": "entry_updated"}, "conditions": []}


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"self-{gid.hex[:8]}", slug=f"self-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for slug, step in (("writer", "write"), ("watcher", "watch")):
        definition = {**UPDATED, "actions": [{"kind": "webhook", "id": step, "url": "https://example.test"}]}
        db_session.add(WorkspaceAutomationModel(session=db_session, group_id=gid, name=slug, slug=slug, enabled=True, definition=definition))
    db_session.commit()
    yield gid

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_a_workflow_sits_out_events_its_own_run_caused(db_session, workspace, monkeypatch):
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", lambda self, *a, **k: None)
    entry_id = str(uuid.uuid4())
    calls: list[tuple[str, int]] = []

    def runner(session, group_id, action, context, **kw):
        depth = int(context.get("depth", 0))
        calls.append((action["id"], depth))
        if action["id"] == "write" and depth < 2:
            # The entry write's entry_updated, dispatched synchronously inside the run (as EntryService does).
            run_automations_for_event(
                session, group_id, {"event_type": "entry_updated", "entry_id": entry_id, "reaction_depth": depth + 1}, run_action=runner
            )
        return {}

    run_automations_for_event(db_session, workspace, {"event_type": "entry_updated", "entry_id": entry_id}, run_action=runner)

    # The writer ran once, for the outside event; the watcher saw both the outside event and the write.
    assert sorted(calls) == [("watch", 0), ("watch", 1), ("write", 0)]

    calls.clear()
    run_automations_for_event(db_session, workspace, {"event_type": "entry_updated", "entry_id": entry_id}, run_action=runner)
    assert ("write", 0) in calls  # a later, independent event triggers it again
