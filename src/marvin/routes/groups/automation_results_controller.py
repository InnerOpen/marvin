"""
The Automation results API (``/groups/automation-results``): what Settings › Automation › Results shows — the work Marvin handed to
another system (an integration action that declares ``hands_off``), newest first, whether the other side reported back, and what a
person can do about a failure (services/automation_results.py).

Roles: reading (summary, list, one) is EDITOR and above; retry and dismiss are ADMIN and above, because a retry calls the other system
with the workspace's credentials. Each route checks its role before it looks anything up.

**Retry** runs the one step of the Marvin workflow that handed the work off, again, for the same entry; it answers 409 with the reason
when that can't be done honestly (the workflow is gone or off, the entry no longer matches, the step reads from the run that began it).
**Dismiss** marks a failure dealt with, so it stops counting as needing attention; only a failed result can be dismissed.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID4

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_role
from marvin.schemas.group.automation_results import (
    AutomationResult,
    AutomationResultConnection,
    AutomationResultOne,
    AutomationResultsCan,
    AutomationResultsList,
    AutomationResultsSummary,
)
from marvin.services import automation_results as results

router = APIRouter(prefix="/groups/automation-results")


@controller(router)
class AutomationResultsController(BaseUserController):
    def _may_act(self) -> bool:
        try:
            require_workspace_role(self.user, self.group_id, WorkspaceRole.ADMIN)
        except HTTPException:
            return False
        return True

    def _gate(self) -> bool:
        """EDITOR and above (before any lookup); returns whether the caller may retry and dismiss (ADMIN and above)."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        return self._may_act()

    def _summary(self, can_act: bool) -> AutomationResultsSummary:
        return AutomationResultsSummary(**results.summary(self.session, self.group_id), can=AutomationResultsCan(act=can_act))

    def _one(self, result_id: UUID4):
        found = results.get(self.session, self.group_id, result_id)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such result.")
        return found

    def _result(self, row) -> AutomationResultOne:
        self.session.refresh(row)
        return AutomationResultOne(result=AutomationResult(**results.read(self.session, row)))

    @router.get("/summary", response_model=AutomationResultsSummary, summary="What Automation results needs to show: the counts")
    def summary(self):
        """Whether any result has been kept (`show`: the Results page and its tab in the Automation hub are drawn only then) and the
        counts: in flight (not counting those with no reply), no reply (in flight for more than 24 hours), failed (not dismissed),
        succeeded, and `attention` = failed + no reply. EDITOR and above (a lower role gets 403)."""
        return self._summary(self._gate())

    @router.get("", response_model=AutomationResultsList, summary="List automation results, newest first")
    def list_results(
        self,
        result_state: list[Literal["in_flight", "no_reply", "failed", "succeeded"]] | None = Query(
            None, alias="status", description="One or more of in_flight (not counting no reply), no_reply, failed, succeeded."
        ),
        connection: str | None = Query(None, description="One connection, by its slug."),
        entry_id: UUID4 | None = Query(None, description="One entry's results (the entry editor's line)."),
        q: str | None = Query(None, max_length=200, description="Text to find in the target, message, run id, entry title or connection."),
        include_dismissed: bool = Query(True, description="False leaves out failures a person dismissed."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """The hand-offs, newest first, each with its entry, connection, workflow, target, status, message and times. `no_reply` marks an
        in-flight one with no reply after 24 hours. `counts` is the whole workspace's, whatever the filters. EDITOR and above."""
        can_act = self._gate()
        rows, total = results.query(
            self.session,
            self.group_id,
            states=result_state,
            connection=connection,
            entry_id=entry_id,
            text=q,
            include_dismissed=include_dismissed,
            limit=limit,
            offset=offset,
        )
        return AutomationResultsList(
            items=[AutomationResult(**r) for r in results.reads(self.session, rows)],
            total=total,
            limit=limit,
            offset=offset,
            counts=self._summary(can_act),
            connections=[AutomationResultConnection(slug=s, name=n, provider=p) for s, n, p in results.connections(self.session, self.group_id)],
        )

    @router.get("/{result_id}", response_model=AutomationResultOne, summary="Get one automation result")
    def get_result(self, result_id: UUID4):
        """One result, as the list returns it. 404 for one that isn't this workspace's. EDITOR and above."""
        self._gate()
        return self._result(self._one(result_id))

    @router.post("/{result_id}/retry", response_model=AutomationResultOne, summary="Retry a failed hand-off")
    def retry(self, result_id: UUID4):
        """Run the hand-off step of the workflow that made this result again, alone, for the same entry. 409 with the reason when it
        can't be done honestly. A repeat that goes out is in flight again; one that fails again is the same result with its attempt
        counted up. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.ADMIN)
        row = self._one(result_id)
        try:
            results.retry(self.session, self.group_id, row, self.user.id if self.user else None, logger=self.logger)
        except results.ResultError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        self.session.commit()
        return self._result(row)

    @router.post("/{result_id}/dismiss", response_model=AutomationResultOne, summary="Dismiss a failure that has been dealt with")
    def dismiss(self, result_id: UUID4):
        """Mark a failed result dealt with: it stops counting as needing attention (and goes with the settled ones when pruned). 409 for
        a result that didn't fail. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.ADMIN)
        row = self._one(result_id)
        try:
            results.dismiss(self.session, row, self.user.id if self.user else None)
        except results.ResultError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        self.session.commit()
        return self._result(row)
