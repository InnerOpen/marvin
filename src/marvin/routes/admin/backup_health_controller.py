"""Backup health (super admin): each backup target as its runs report it — schedule, retention, last run,
last success, next run, overdue — and the recent runs. Read-only.

The backup targets are CronJobs the backend can't see; each run records itself in `backup_runs` (see
services/backup_health). A target appears here after its first recorded run, failed ones included.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.backup_health import BackupHealthRead, BackupRunRead, BackupTargetRead
from marvin.services import backup_health

router = APIRouter(prefix="/backup-health")


def target_read(t: backup_health.TargetHealth) -> BackupTargetRead:
    return BackupTargetRead(
        name=t.name,
        type=t.type,
        state=t.state,
        schedule=t.schedule,
        time_zone=t.time_zone,
        schedule_error=t.schedule_error,
        interval_seconds=int(t.interval.total_seconds()) if t.interval else None,
        keep_hourly=t.retention[0],
        keep_daily=t.retention[1],
        keep_weekly=t.retention[2],
        location=t.location,
        settings=t.settings,
        last_run=BackupRunRead.model_validate(t.last_run) if t.last_run else None,
        last_success=BackupRunRead.model_validate(t.last_success) if t.last_success else None,
        first_seen=t.first_seen,
        next_run_at=t.next_run_at,
        due_by=t.due_by,
        overdue=t.overdue,
        overdue_since=t.overdue_since,
    )


@controller(router)
class AdminBackupHealthController(BaseAdminController):
    @router.get("", response_model=BackupHealthRead, summary="Admin: Backup Health")
    def get_backup_health(
        self,
        target: str | None = Query(None, description="Only this target's runs"),
        limit: int = Query(50, ge=1, le=500, description="How many recent runs"),
    ) -> BackupHealthRead:
        """Every backup target that has recorded a run, with its state (ok, partial, failed, overdue), and the
        newest runs, newest first. Times are UTC."""
        now = datetime.now(UTC)
        return BackupHealthRead(
            now=now,
            targets=[target_read(t) for t in backup_health.all_targets(self.session, now)],
            runs=[BackupRunRead.model_validate(r) for r in backup_health.recent_runs(self.session, limit, target)],
        )
