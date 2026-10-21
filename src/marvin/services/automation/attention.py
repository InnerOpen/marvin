"""What in Automation needs a person's look, and the one summary the dashboard and Settings read.

Each kind of automation item (workflows, incoming webhooks, scheduled tasks, outgoing webhooks) has its own rules for "needs a look". A kind
plugs into the summary by registering a counter and the page that lists it — see ``register`` at the bottom. The summary adds them up and names
the first page with something flagged, so the dashboard line can link straight to it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from marvin.db.models.groups.automation_executions import AutomationExecutionModel as Run
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integrations import IntegrationModel

# Why a workflow is flagged (the API's `attention` field; the page words them).
LAST_RUN_FAILED = "last_run_failed"
OFF_WHILE_INTEGRATION_ON = "off_while_integration_on"


def workflow_reason(*, enabled: bool, last_status: str | None, handled: bool, integration_id: Any, integration_enabled: bool | None) -> str | None:
    """Why a workflow needs a look, or None.

    Its last run failed or partly failed, unless an integration's error policy handled it. Or an integration installed it and it is off while
    that integration is on (a workflow that integration's removal left behind has no integration id, so it never matches; nor does one a person made).
    """
    if last_status in ("failed", "partial") and not handled:
        return LAST_RUN_FAILED
    if not enabled and integration_id is not None and integration_enabled:
        return OFF_WHILE_INTEGRATION_ON
    return None


def workflow_rows(session, group_id) -> list[tuple[WorkspaceAutomationModel, Any, str | None, str | None]]:
    """``(workflow, last run started, last run status, attention reason)`` for every workflow of the workspace, by name — in one query."""
    started = sa.func.coalesce(Run.started_at, Run.created_at)
    newest = (
        sa.select(
            Run.automation_id,
            Run.status,
            Run.handled,
            started.label("at"),
            sa.func.row_number().over(partition_by=Run.automation_id, order_by=(started.desc(), Run.created_at.desc())).label("rank"),
        )
        .where(Run.group_id == group_id, Run.automation_id.is_not(None))
        .subquery()
    )
    rows = (
        session.query(WorkspaceAutomationModel, newest.c.at, newest.c.status, newest.c.handled, IntegrationModel.enabled)
        .outerjoin(newest, sa.and_(newest.c.automation_id == WorkspaceAutomationModel.id, newest.c.rank == 1))
        .outerjoin(
            IntegrationModel,
            sa.and_(IntegrationModel.id == WorkspaceAutomationModel.source_integration_id, IntegrationModel.group_id == group_id),
        )
        .filter(WorkspaceAutomationModel.group_id == group_id)
        .order_by(WorkspaceAutomationModel.name)
        .all()
    )
    return [
        (
            wf,
            at,
            status,
            workflow_reason(
                enabled=wf.enabled,
                last_status=status,
                handled=bool(handled),
                integration_id=wf.source_integration_id,
                integration_enabled=integration_enabled,
            ),
        )
        for wf, at, status, handled, integration_enabled in rows
    ]


def workflows_needing_a_look(session, group_id) -> int:
    return sum(1 for *_, reason in workflow_rows(session, group_id) if reason)


def incoming_webhooks_needing_a_look(session, group_id) -> int:
    """Enabled incoming webhooks that have never received a call. (Marvin does not record rejected deliveries — a bad token or signature
    only reaches the log — so "recent deliveries all rejected" cannot be told apart here; the page's filter uses the same single rule.)"""
    hook = WorkspaceIncomingWebhookModel
    return session.query(sa.func.count(hook.id)).filter(hook.group_id == group_id, hook.enabled.is_(True), hook.received_count == 0).scalar() or 0


@dataclass(frozen=True)
class Kind:
    key: str  # "workflows" …
    page: str  # where its items are listed, filtered to the flagged ones
    count: Callable[[Any, Any], int]  # (session, group_id) -> how many need a look


_KINDS: list[Kind] = []


def register(key: str, page: str, count: Callable[[Any, Any], int]) -> None:
    """Add a kind to the summary. ``page`` is the list page's URL with its Needs-attention filter on (``?status=attention``)."""
    _KINDS[:] = [k for k in _KINDS if k.key != key] + [Kind(key, page, count)]


def summary(session, group_id) -> dict:
    """``{"total": N, "kinds": {key: count}, "first_page": url | None}`` — kinds in registration order; the first page is that of the first kind
    with something flagged. A kind whose count fails counts as 0: one broken check never sinks the others."""
    kinds: dict[str, int] = {}
    first_page: str | None = None
    for kind in _KINDS:
        try:
            n = int(kind.count(session, group_id) or 0)
        except Exception:
            session.rollback()
            n = 0
        kinds[kind.key] = n
        if n and first_page is None:
            first_page = kind.page
    return {"total": sum(kinds.values()), "kinds": kinds, "first_page": first_page}


# ── the kinds ───────────────────────────────────────────────────────────────────────────────────────────────────
register("workflows", "/automation/workflows?status=attention", workflows_needing_a_look)
register("incoming_webhooks", "/automation/incoming-webhooks?status=attention", incoming_webhooks_needing_a_look)
# Later pages add theirs here: register("scheduled_tasks", …), register("outgoing_webhooks", …)
