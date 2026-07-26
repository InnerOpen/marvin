"""The audit log must accept platform/system-scoped events (no workspace).

A global scheduled task fires e.g. `scheduled_task_completed` with workspace_id=None. `event_log`'s
workspace_id is nullable so these persist, instead of tripping a NOT NULL violation and dropping the
audit record (regression: NotNullViolation on event_log.workspace_id).
"""

import uuid
from datetime import UTC, datetime

from marvin.db.models.platform.event_log import EventLogModel


def test_event_log_accepts_a_system_event_with_null_workspace(db_session):
    eid = uuid.uuid4()
    db_session.add(
        EventLogModel(
            event_id=eid,
            event_type="scheduled_task_completed",
            occurred_at=datetime.now(UTC),
            workspace_id=None,
            integration_id="scheduled_tasks",
            operation="info",
            event_data={"message": {"title": "Scheduled Task Completed", "body": "done"}},
            message_title="Scheduled Task Completed",
            message_body="Scheduled task 'Resync Smart Collections' completed successfully",
        )
    )
    db_session.commit()

    got = db_session.query(EventLogModel).filter(EventLogModel.event_id == eid).one()
    assert got.workspace_id is None

    db_session.query(EventLogModel).filter(EventLogModel.event_id == eid).delete()
    db_session.commit()
