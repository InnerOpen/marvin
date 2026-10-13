"""Executions spawned inside an agent run point back at it (services/ai/executions.py)."""

import uuid

from marvin.services.ai.executions import PARENT_KEY, link_child_execution, parent_meta
from marvin.services.ai.tools import ToolContext


def test_parent_meta_is_none_without_a_parent():
    assert parent_meta(None) is None
    assert parent_meta("") is None
    assert parent_meta("abc") == {PARENT_KEY: "abc"}


def test_tool_context_has_no_execution_until_the_controller_sets_one():
    assert ToolContext(session=None, group_id="g").execution_id is None


def test_link_child_execution_stamps_the_parent_and_keeps_existing_metadata(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"ex-{gid.hex[:8]}", slug=f"ex-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    row = AIExecutionModel(
        session=db_session, group_id=gid, operation_slug="generate-summary", provider_type="fake", model_id="m", status="completed"
    )
    row.metadata_json = {"writeback": "applied"}
    db_session.add(row)
    db_session.flush()
    link_child_execution(db_session, row.id, "parent-1")
    db_session.refresh(row)
    assert row.metadata_json == {"writeback": "applied", PARENT_KEY: "parent-1"}
    link_child_execution(db_session, row.id, None)  # no parent → untouched
    assert row.metadata_json[PARENT_KEY] == "parent-1"
    link_child_execution(db_session, uuid.uuid4(), "parent-2")  # unknown row → no error
    db_session.rollback()
