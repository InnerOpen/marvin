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


class CheckWorkspaceStorageHandler(ScheduledTaskHandler):
    """
    Check every workspace bucket in use (and any marked failing): list, put, get and delete a tiny object, then
    fetch one from its public URL. Two failures in a row mark a bucket failing (uploads stop, with a plain message)
    and send workspace_storage_unhealthy to its workspace; a pass after that marks it working again and sends
    workspace_storage_recovered. Admin-only; runs hourly.
    """

    name = "Check Workspace Storage"
    description = "Check the buckets workspaces keep their files in; mark failing ones and tell their workspaces (admin only)"
    admin_only = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.db_setup import session_context
        from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceStorageHealthData
        from marvin.services.storage import workspace as ws
        from marvin.services.storage import workspace_admin as admin

        if task.group_id:
            return "Skipped: check_workspace_storage is admin-only and cannot run in a workspace context"
        bus = event_bus or EventBusService(bg_tasks=None)
        changes: list[str] = []
        failing = 0
        with session_context() as session:
            conns = admin.connections_to_watch(session)
            for conn in conns:
                transition = admin.health_check(session, conn)
                failing += conn.status == "failing"
                if transition is None:
                    continue
                unhealthy = transition == "unhealthy"
                where = conn.label or "the workspace bucket"
                changes.append(f"{where}: {'failing' if unhealthy else 'working again'}")
                bus.dispatch(
                    integration_id="workspace_storage",
                    group_id=conn.group_id,
                    event_type=EventTypes.workspace_storage_unhealthy if unhealthy else EventTypes.workspace_storage_recovered,
                    document_data=EventWorkspaceStorageHealthData(
                        operation=EventOperation.update,
                        connection_id=str(conn.id),
                        location=ws.location_for(conn.id),
                        bucket_label=conn.label,
                        error=conn.last_error if unhealthy else None,
                        consecutive_failures=conn.consecutive_failures or 0,
                    ),
                    message=(f"{where} is failing its checks: uploads are paused ({conn.last_error})" if unhealthy else f"{where} works again"),
                    entity_id=conn.group_id,
                    entity_type="workspace",
                )
        if not conns:
            return None  # no workspace keeps its own bucket: nothing to report
        return f"Checked {len(conns)} bucket(s): {failing} failing" + (f"; {'; '.join(changes)}" if changes else "")


TaskHandlerRegistry.register("check_workspace_storage", CheckWorkspaceStorageHandler)


class BackupToWorkspaceBucketHandler(ScheduledTaskHandler):
    """
    Make this workspace's backup bundle and save it to its own private backup bucket now ("Back up now" on
    Workspace settings → Storage). The daily Workspace Backup Bundles task does the same for every workspace that
    has a backup bucket; this is the on-demand run. Sends workspace_backup_saved or workspace_backup_failed.
    """

    name = "Back Up to the Workspace's Bucket"
    description = "Save a backup of this workspace to its own private backup bucket"

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.core.config import get_app_dirs
        from marvin.db.db_setup import session_context
        from marvin.services.storage.workspace_backups import announce, backup_now

        if not task.group_id:
            raise ValueError("backup_to_workspace_bucket runs in a workspace")
        with session_context() as session:
            try:
                saved = backup_now(session, task.group_id, get_app_dirs().BACKUP_DIR / ".own")
            except Exception as e:
                announce(event_bus, task.group_id, error=str(e), trigger="manual")
                raise
            announce(event_bus, task.group_id, saved=saved, trigger="manual")
        return f"Saved {saved.key} ({saved.size / 1024**2:.1f} MB); {saved.pruned} older backup(s) deleted"


TaskHandlerRegistry.register("backup_to_workspace_bucket", BackupToWorkspaceBucketHandler)


class PurgeDeletedWorkspaceStorageHandler(ScheduledTaskHandler):
    """
    Purge the stored files of deleted workspaces whose 30-day grace period has passed. Deleting a workspace records
    where its files are (Admin → Storage lists them with "purge now" and "keep"); this removes the ones nobody kept.
    A location that can't be reached is retried the next day. Admin-only; runs daily.
    """

    name = "Purge Deleted Workspace Storage"
    description = "Delete the stored files of workspaces deleted more than 30 days ago, unless an admin kept them (admin only)"
    admin_only = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.db_setup import session_context
        from marvin.services.storage import deleted_workspaces

        if task.group_id:
            return "Skipped: purge_deleted_workspace_storage is admin-only and cannot run in a workspace context"
        with session_context() as session:
            run = deleted_workspaces.purge_due(session)
        if not (run.purged or run.failed):
            return None  # nothing was due
        return (
            f"Purged {run.purged} location(s) ({run.objects} files); "
            f"{run.failed} could not be reached and will be retried; {run.pending} still waiting"
        )


TaskHandlerRegistry.register("purge_deleted_workspace_storage", PurgeDeletedWorkspaceStorageHandler)
