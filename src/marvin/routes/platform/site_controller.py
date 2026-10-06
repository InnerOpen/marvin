"""
Site rebuild endpoints — ask for the workspace's static site to be rebuilt, and see where that stands.

`POST /site/rebuild` goes through the same coalescing queue as the `request_site_rebuild` workflow step
and automatic rebuilds (marvin.services.site_rebuild): it joins the pending rebuild, which goes out as
one `webhook_triggered` to the deploy target once requests have gone quiet. EDITOR and above, the role
that publishes.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from marvin.db.models.platform.event_log import EventLogModel
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_editor
from marvin.schemas.platform.site_rebuild import (
    SiteBuildStatus,
    SiteRebuildPending,
    SiteRebuildRequest,
    SiteRebuildRequested,
    SiteRebuildSent,
    SiteRebuildStatus,
    SiteRebuildTarget,
)
from marvin.services.event_bus_service.event_types import SiteRebuildChange
from marvin.services.site_rebuild import (
    REBUILD_EVENT,
    DeployTarget,
    deploy_targets,
    expected_send_at,
    pending_rebuild,
    rebuild_change,
    request_rebuild,
)

router = APIRouter(prefix="/site")

NOTHING_BUILDS = (
    "Nothing is set up to build this workspace's site: add an outgoing webhook (your host's deploy hook) "
    "on the Site Rebuild Sent event (webhook_triggered), or subscribe an integration action (e.g. Cloudflare Pages → Deploy) to it."
)

BUILD_EVENTS = tuple(f"site_{stage}_{state}" for stage in ("build", "deployment") for state in ("started", "completed", "failed"))


def _target_fields(targets: list[DeployTarget]) -> dict:
    listed = [SiteRebuildTarget(kind=t.kind, id=t.id, name=t.name, provider=t.provider, action=t.action) for t in targets]
    return {"target": listed[0] if len(listed) == 1 else None, "targets": listed}


def _document(event: EventLogModel) -> dict:
    data = event.event_data or {}
    doc = data.get("documentData") or data.get("document_data") or {}
    return doc if isinstance(doc, dict) else {}


def _pick(doc: dict, *keys: str):
    return next((doc[k] for k in keys if doc.get(k) is not None), None)


@controller(router)
class SiteController(BaseUserController):
    @router.post("/rebuild", response_model=SiteRebuildRequested, status_code=status.HTTP_202_ACCEPTED)
    def request_site_rebuild(self, data: SiteRebuildRequest | None = None) -> SiteRebuildRequested:
        """Queue a rebuild of the workspace's site.

        Joins the pending rebuild if there is one (repeat calls cost one build), which is sent to the
        deploy target once requests have been quiet for SITE_REBUILD_QUIET_SECONDS. 409 when nothing
        is set up to build the site.
        """
        require_workspace_editor(self.user, self.group_id)
        targets = deploy_targets(self.session, self.group_id)
        if not targets:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOTHING_BUILDS)

        reason = ((data.reason if data else None) or "").strip()
        if not reason:
            who = getattr(self.user, "full_name", None)
            reason = f"Rebuild requested by {who}" if who else "Rebuild requested"
        # One line per workspace in the rebuild's change list, however often it is asked for.
        request_count = request_rebuild(
            self.session, self.group_id, reason, change=rebuild_change(reason, entity_type="workspace", entity_id=self.group_id)
        )

        row = pending_rebuild(self.session, self.group_id)
        return SiteRebuildRequested(
            queued_at=row.first_requested_at,
            last_requested_at=row.last_requested_at,
            expected_send_at=expected_send_at(row.first_requested_at, row.last_requested_at),
            request_count=request_count,
            reason=reason,
            **_target_fields(targets),
        )

    @router.get("/rebuild", response_model=SiteRebuildStatus)
    def site_rebuild_status(self) -> SiteRebuildStatus:
        """Where the site rebuild stands: what builds it, the queued rebuild, the last one sent, and the
        newest build or deploy status a host reported."""
        require_workspace_editor(self.user, self.group_id)
        targets = deploy_targets(self.session, self.group_id)

        pending = None
        if row := pending_rebuild(self.session, self.group_id):
            pending = SiteRebuildPending(
                queued_at=row.first_requested_at,
                last_requested_at=row.last_requested_at,
                expected_send_at=expected_send_at(row.first_requested_at, row.last_requested_at),
                request_count=row.request_count,
                reason=row.reason,
                changes=[SiteRebuildChange.model_validate(c) for c in row.changes or []],
            )

        last_sent = None
        if sent := self._newest(REBUILD_EVENT):
            doc = _document(sent)
            count = _pick(doc, "requestCount", "request_count")
            last_sent = SiteRebuildSent(
                event_id=sent.event_id,
                sent_at=sent.occurred_at,
                message=sent.message_title,
                request_count=count if isinstance(count, int) else None,
            )

        last_build = None
        if build := self._newest(*BUILD_EVENTS):
            doc = _document(build)
            _, stage, state = build.event_type.split("_")
            detail = _pick(doc, "errorMessage", "error_message", "error")
            last_build = SiteBuildStatus(
                event_id=build.event_id,
                event_type=build.event_type,
                stage=stage,
                status=state,
                occurred_at=build.occurred_at,
                message=build.message_title,
                detail=str(detail)[:500] if detail else None,
                deployment_id=_pick(doc, "deploymentId", "deployment_id"),
                site_url=_pick(doc, "siteUrl", "site_url"),
            )

        return SiteRebuildStatus(
            configured=bool(targets),
            quiet_seconds=self.settings.SITE_REBUILD_QUIET_SECONDS,
            max_wait_seconds=self.settings.SITE_REBUILD_MAX_WAIT_SECONDS,
            pending=pending,
            last_sent=last_sent,
            last_build=last_build,
            **_target_fields(targets),
        )

    def _newest(self, *event_types: str) -> EventLogModel | None:
        return self.session.execute(
            select(EventLogModel)
            .where(EventLogModel.workspace_id == self.group_id, EventLogModel.event_type.in_(event_types))
            .order_by(EventLogModel.occurred_at.desc())
            .limit(1)
        ).scalar_one_or_none()
