"""
Metric observations: the numbers a workflow's Metric step recorded, per variant and window.

Reading is EDITOR and above, as the Approvals page is; removing an observation is ADMIN/OWNER. The API only lists —
a workflow's `metric` step writes (services/metrics.py) — and what it lists are observations, never conclusions.
Retention: observations are a deliberate record, kept until removed here (a workspace holds at most 50,000).
"""

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import UUID4

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin, require_workspace_role
from marvin.schemas.group.metrics import MetricObservationList, MetricObservationRead, MetricSummary
from marvin.services import metrics

router = APIRouter(prefix="/groups/metrics")


@controller(router)
class MetricsController(BaseUserController):
    @router.get("", response_model=list[MetricSummary], summary="The metrics this workspace has observations for")
    def list_metrics(self):
        """Each metric name with how many observations it has and the first and last window. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        return [MetricSummary(**m) for m in metrics.metric_names(self.session, self.group_id)]

    @router.get("/observations", response_model=MetricObservationList, summary="List metric observations")
    def list_observations(
        self,
        metric: str | None = Query(None, description="One metric (its slug)."),
        variant: str | None = Query(None, description="One variant label; an empty value means the observations with none."),
        subject: str | None = Query(None, description="One subject label; an empty value means the observations with none."),
        window_from: str | None = Query(
            None, description="Windows starting on or after this one: a day (2026-10-18), week (2026-W42) or month (2026-10)."
        ),
        window_to: str | None = Query(None, description="Windows starting on or before this one (same forms)."),
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        """Observations, newest window first (then metric, variant, subject). Each is a number a workflow recorded for a
        metric, variant and window — observations, not conclusions: nothing here compares variants or says what caused
        a number. 422 for a window that isn't a day, week or month. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        try:
            rows, total = metrics.query(
                self.session,
                self.group_id,
                metric=metric,
                variant=variant,
                subject=subject,
                window_from=window_from,
                window_to=window_to,
                limit=limit,
                offset=offset,
            )
        except metrics.MetricError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        names = {
            a.id: (a.name, a.slug)
            for a in self.session.query(WorkspaceAutomationModel).filter(
                WorkspaceAutomationModel.id.in_({r.automation_id for r in rows if r.automation_id})
            )
        }
        items = [
            MetricObservationRead(
                id=r.id,
                metric=r.metric,
                variant=r.variant,
                subject=r.subject,
                window=r.window_label,
                granularity=r.granularity,
                window_start=r.window_start,
                value=r.value,
                workflow_name=names.get(r.automation_id, (None, None))[0],
                workflow_slug=names.get(r.automation_id, (None, None))[1],
                updated_at=r.update_at,
            )
            for r in rows
        ]
        return MetricObservationList(items=items, total=total, limit=limit, offset=offset)

    @router.delete("/observations/{observation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an observation")
    def delete_observation(self, observation_id: UUID4):
        """Remove one observation (a wrong number, a test run). A workflow that records that window again writes it
        afresh. 404 if there is none. ADMIN and above."""
        require_workspace_admin(self.user, self.group_id)
        if not metrics.remove(self.session, self.group_id, observation_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such observation.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
