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

            if get_connection(session, task.group_id, connection_id).status != ws.STATUS_OK:
                raise ValueError("the bucket connection isn't verified: check it in Workspace settings → Storage first")
            slug = workspace.slug
        report = migrate(ws.location_for(connection_id), workspace=slug, verify=bool((task.task_config or {}).get("verify", True)))
        if report.failures:
            raise RuntimeError(f"{report.summary()}; first failure: {report.failures[0]}")
        return report.summary()


TaskHandlerRegistry.register("copy_to_workspace_storage", CopyToWorkspaceStorageHandler)
