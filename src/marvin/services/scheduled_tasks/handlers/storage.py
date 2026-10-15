"""Workspace storage tasks: copying a workspace's existing files into its own bucket (services/storage/workspace_admin.py)."""

from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry


class CopyToWorkspaceStorageHandler(ScheduledTaskHandler):
    """
    Copy every file of the task's workspace that isn't in the connection yet into it, checking each copy's sha256,
    then point the file's row at it. The original is never deleted, so links already published keep working.
    Resumable: a run that stops part way is finished by running it again. Started from Workspace settings → Storage.

    Configuration (task_config):
    - connection_id: str - The workspace's bucket connection (it must be verified).
    - verify: bool - Download each copy and hash it instead of trusting the bucket's checksum (default true).
    """

    name = "Copy Files to the Workspace's Bucket"
    description = "Copy this workspace's existing files into its own bucket (originals are kept)"
    config_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "The bucket connection to copy into"},
            "verify": {"type": "boolean", "description": "Download and hash each copy (default true)"},
        },
        "required": ["connection_id"],
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups import Groups
        from marvin.services.storage import workspace as ws
        from marvin.services.storage.migration import migrate

        if not task.group_id:
            raise ValueError("copy_to_workspace_storage runs in a workspace")
        connection_id = (task.task_config or {}).get("connection_id")
        if not connection_id:
            raise ValueError("task_config.connection_id is required")
        with session_context() as session:
            workspace = session.get(Groups, task.group_id)
            if workspace is None:
                raise ValueError("the workspace no longer exists")
            if not ws.policy(session).allowed:
                raise ValueError("the platform doesn't allow workspace storage")
            from marvin.services.storage.workspace_admin import get_connection

            conn = get_connection(session, task.group_id, connection_id)
            if conn.status != ws.STATUS_OK:
                raise ValueError("the bucket connection isn't verified: check it in Workspace settings → Storage first")
            slug, label = workspace.slug, conn.label
        location = ws.location_for(connection_id)
        try:
            report = migrate(location, workspace=slug, verify=bool((task.task_config or {}).get("verify", True)))
        except Exception as e:  # the copy couldn't start (the bucket unreachable, a guard): still say it ended
            _announce_finished(event_bus, task, location, label, failures=[{"asset_id": None, "error": str(e)}])
            raise
        _announce_finished(event_bus, task, location, label, report=report)
        if report.failures:
            raise RuntimeError(f"{report.summary()}; first failure: {report.failures[0]}")
        return report.summary()


def _announce_finished(event_bus, task: ScheduledTaskModel, location: str, label: str | None, *, report=None, failures=None) -> None:
    """workspace_storage_copy_finished: the counts, and each failed file."""
    from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceStorageCopyData

    failures = failures if failures is not None else [{"asset_id": str(a), "error": why} for a, why in report.failed_assets]
    data = EventWorkspaceStorageCopyData(
        operation=EventOperation.update,
        connection_id=location.split(":", 1)[1],
        location=location,
        bucket_label=label,
        moved=report.moved if report else 0,
        already_there=report.already_there if report else 0,
        changed_meanwhile=report.raced if report else 0,
        failed=len(report.failed_assets) if report else len(failures),
        failures=failures,
        copied_bytes=report.copied_bytes if report else 0,
    )
    where = label or "the workspace bucket"
    message = f"Copy into {where} finished: {data.moved} moved, {data.already_there} already there, {data.failed} failed"
    (event_bus or EventBusService(bg_tasks=None)).dispatch(
        integration_id="workspace_storage",
        group_id=task.group_id,
        event_type=EventTypes.workspace_storage_copy_finished,
        document_data=data,
        message=message,
        entity_id=task.group_id,
        entity_type="workspace",
    )


TaskHandlerRegistry.register("copy_to_workspace_storage", CopyToWorkspaceStorageHandler)
