"""CRUD + builder-options routes for workspace automations (Flavor B orchestration).

ADMIN/OWNER-managed (an automation runs AI ops unattended, so registering one is a trust decision).
The `/options` endpoint advertises the builder's vocabulary — trigger events, condition operators,
action kinds, and the operations available as actions — so the UI is backend-driven.
"""

from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.automation import (
    AutomationActionOption,
    AutomationAgentOption,
    AutomationAttention,
    AutomationConditionField,
    AutomationCreate,
    AutomationExecutionDetail,
    AutomationExecutionRead,
    AutomationIncomingWebhookOption,
    AutomationOptions,
    AutomationPlaybookOption,
    AutomationPreviewMatch,
    AutomationPreviewRequest,
    AutomationPreviewResult,
    AutomationRead,
    AutomationRunRequest,
    AutomationTargetOption,
    AutomationUpdate,
    AutomationValidateRequest,
    AutomationValidateResult,
    AutomationWebhookOption,
    IntegrationRetryRead,
    RecipeConfigureRequest,
    RecipeConfigureResult,
    WorkflowApprovalDecision,
    WorkflowApprovalRead,
    WorkflowLibraryRead,
    WorkflowLibraryRefs,
    WorkflowRecipe,
)
from marvin.services.automation.workflows import WorkflowError, create_workflow, delete_workflow, update_workflow

router = APIRouter(prefix="/automations", route_class=MarvinCrudRoute)


_require_admin = require_workspace_admin


def _retry_chain(session, row, limit: int = 50) -> list:
    """The run's retry chain, oldest first: back through `retry_of_id` to the original run, then
    forward through every retry of it (bounded — a chain is a handful of runs)."""
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    root = row
    for _ in range(limit):
        parent = session.get(AutomationExecutionModel, root.retry_of_id) if root.retry_of_id else None
        if parent is None or parent.group_id != row.group_id:
            break
        root = parent
    chain, frontier = [root], [root.id]
    while frontier and len(chain) < limit:
        children = (
            session.query(AutomationExecutionModel)
            .filter(AutomationExecutionModel.group_id == row.group_id, AutomationExecutionModel.retry_of_id.in_(frontier))
            .order_by(AutomationExecutionModel.started_at)
            .all()
        )
        chain += children
        frontier = [c.id for c in children]
    return chain[:limit]  # breadth-first from the original run: chronological for a chain


def _get_or_404(session, automation_id: UUID4, group_id: UUID4) -> WorkspaceAutomationModel:
    row = session.get(WorkspaceAutomationModel, automation_id)
    if not row or row.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found.")
    return row


def _agent_step_options(session, group_id, user) -> tuple[list[AutomationAgentOption], list[AutomationPlaybookOption]]:
    """What an agent step's pickers offer: the persona agents (and whether each may save drafts for this person, by its
    own permissions) and the published Playbooks."""
    from types import SimpleNamespace

    from marvin.services.ai.agents import list_agents
    from marvin.services.ai.tools.base import user_role
    from marvin.services.ai.tools.builtins_agents import standalone_tools
    from marvin.services.playbooks import published_playbooks

    role = user_role(user, group_id)
    agents = []
    for spec in list_agents(session, group_id):
        if spec.kind != "persona":
            continue
        can_draft = any(t.name in ("create_draft", "update_draft") for t in standalone_tools(spec, SimpleNamespace(), role))
        agents.append(
            AutomationAgentOption(slug=spec.slug, name=spec.name, description=spec.description, enabled=bool(spec.enabled), can_draft=can_draft)
        )
    playbooks = [
        AutomationPlaybookOption(name=p.name, description=p.description, manual_only=bool(p.manual_only))
        for p in published_playbooks(session, group_id)
    ]
    return agents, playbooks


def _recipe_uses(session, group_id) -> dict[str, list[dict]]:
    """{recipe id: the workspace's workflows made from it, each saying whether the recipe has changed since}."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation import recipes

    rows = (
        session.query(WorkspaceAutomationModel)
        .filter(WorkspaceAutomationModel.group_id == group_id, WorkspaceAutomationModel.source_recipe.isnot(None))
        .order_by(WorkspaceAutomationModel.name)
    )
    versions: dict[str, str | None] = {}
    uses: dict[str, list[dict]] = {}
    for row in rows:
        if row.source_recipe not in versions:
            try:
                versions[row.source_recipe] = recipes.recipe_version(row.source_recipe)
            except recipes.UnknownRecipe:
                versions[row.source_recipe] = None  # a recipe since retired: nothing to compare
        current = versions[row.source_recipe]
        uses.setdefault(row.source_recipe, []).append(
            {
                "id": row.id,
                "name": row.name,
                "slug": row.slug,
                "enabled": bool(row.enabled),
                "outdated": bool(current and row.source_recipe_version and current != row.source_recipe_version),
            }
        )
    return uses


def _library_recipe(item: dict, refs, uses: dict[str, list[dict]] | None = None) -> WorkflowRecipe:
    """A catalogue entry as the Library and the editor's recipe picker show it, with what this workspace lacks."""
    from marvin.services.automation import recipes

    return WorkflowRecipe(
        **{key: item[key] for key in ("id", "title", "outcome", "category", "category_slug", "tags", "trigger", "status", "shape")},
        providers=[need["provider"] for need in (item.get("prerequisites") or {}).get("integrations") or [] if need.get("provider")],
        capabilities=[need["capability"] for need in (item.get("prerequisites") or {}).get("integrations") or [] if need.get("capability")],
        side_effects=item.get("side_effects") or [],
        setup_variables=item.get("setup_variables") or [],
        supporting_objects=item.get("supporting_objects") or [],
        dependencies=item.get("dependencies") or [],
        missing=recipes.missing_prerequisites(item, refs),
        in_use=(uses or {}).get(item["id"], []),
        source=item.get("source"),
    )


def _run_in_background(group_id, automation_id, user_id, inputs: dict | None = None) -> None:
    """A Run-button run that answered first: in its own session, after the response. A failure is logged and lands in
    the workflow's Runs and the automation_failed event like any run's."""
    from marvin.core.root_logger import get_logger
    from marvin.db.db_setup import session_context
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    logger = get_logger(__name__)
    try:
        with session_context() as session:
            row = session.get(WorkspaceAutomationModel, automation_id)
            if row is None or str(row.group_id) != str(group_id) or not row.enabled:
                return
            recorder = ExecutionRecorder(session, group_id)
            run_automation_now(session, group_id, row, user_id=user_id, logger=logger, recorder=recorder, inputs=inputs)
    except Exception as e:  # noqa: BLE001 — a background run must never take the worker down
        logger.error(f"background run of workflow {automation_id} failed: {e}", exc_info=True)


def _rank(user, group_id) -> int:
    """The caller's workspace role as the rank approval steps compare (a role-bypassing platform admin counts as OWNER)."""
    from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
    from marvin.routes._base.checks import _bypasses_workspace_roles
    from marvin.services.automation.authz import ROLE_OWNER

    return ROLE_OWNER if _bypasses_workspace_roles(user) else WORKSPACE_ROLE_HIERARCHY.get(user.get_workspace_role(group_id), 0)


def _approval_read(session, row) -> WorkflowApprovalRead:
    from marvin.db.models.platform.entries import Entries
    from marvin.services.automation.authz import ROLE_ADMIN

    automation = session.get(WorkspaceAutomationModel, row.automation_id)
    entry = session.get(Entries, row.entry_id) if row.entry_id else None
    return WorkflowApprovalRead(
        id=row.id,
        automation_id=row.automation_id,
        automation_name=getattr(automation, "name", None),
        automation_slug=getattr(automation, "slug", None),
        message=row.message,
        approvers="admin" if row.min_role >= ROLE_ADMIN else "editor",
        status=row.status,
        entry_id=row.entry_id,
        entry_title=getattr(entry, "title", None),
        created_at=row.created_at,
        expires_at=row.expires_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
        choices=row.choices or None,
        choice=row.choice,
        image_url=row.image_url,
    )


@contextmanager
def _as_http():
    """The shared write path's refusals (services/automation/workflows.py) as HTTP errors."""
    try:
        yield
    except WorkflowError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@controller(router)
class AutomationsController(BaseUserController):
    """Manage the workspace's automations (ADMIN/OWNER only)."""

    @router.get("", response_model=list[AutomationRead], summary="List Automations")
    def list_automations(self) -> list[AutomationRead]:
        _require_admin(self.user, self.group_id)
        from marvin.services.automation import attention

        rows = attention.workflow_rows(self.session, self.group_id)
        return [
            AutomationRead.model_validate(r).model_copy(update={"last_run_at": at, "last_run_status": status, "attention": reason})
            for r, at, status, reason in rows
        ]

    @router.get("/attention", response_model=AutomationAttention, summary="What in Automation needs a look")
    def attention_summary(self) -> AutomationAttention:
        """One count per kind of automation item that needs a look, and the first page with something flagged."""
        _require_admin(self.user, self.group_id)
        from marvin.services.automation import attention

        counts = attention.summary(self.session, self.group_id)
        return AutomationAttention(total=counts["total"], kinds=counts["kinds"], first_page=counts["first_page"])

    @router.get("/options", response_model=AutomationOptions, summary="Automation builder options")
    def options(self) -> AutomationOptions:
        """Advertise the builder's vocabulary so the UI doesn't hardcode triggers/ops/operators.

        Action kinds come from the executor registry. AI `operations` are listed ONLY when AI is
        enabled for the workspace and the `automation` invocation source is allowed — Flavor B works
        with AI off, so the builder just won't offer AI actions there.
        """
        _require_admin(self.user, self.group_id)
        from marvin.services.automation.actions import available_kinds
        from marvin.services.automation.authoring import automation_operations
        from marvin.services.automation.matcher import _OPS
        from marvin.services.events.event_catalog import offered_emittable, trigger_groups

        groups = trigger_groups()  # the catalog's triggerable events, under the builder's headings
        from marvin.services.events import custom_events

        own = custom_events.registered_types(self.session, self.group_id)  # the workspace's own events: one more heading
        if own:
            groups = {**groups, custom_events.TRIGGER_GROUP: own}

        # AI operations are available only when AI is enabled AND the automation source isn't disabled.
        operations = [
            AutomationActionOption(
                op=op.slug,
                name=op.name,
                description=op.description,
                entity_types=op.entity_types,
                writes_back=bool(getattr(op, "writeback", None)),
            )
            for op in automation_operations(self.session, self.group_id) or []
        ]

        # The workspace's configured webhooks, offered to the `webhook` action.
        from marvin.db.models.groups.webhooks import GroupWebhooksModel

        webhooks = [
            AutomationWebhookOption(
                id=w.id,
                name=w.name or str(w.url),
                url=str(w.url),
                method=getattr(w.method, "value", w.method) or "POST",
            )
            for w in self.session.query(GroupWebhooksModel).filter_by(group_id=self.group_id).all()
        ]

        # Other automations, for chained / on-error triggers to target.
        targets = [
            AutomationTargetOption(id=a.id, slug=a.slug, name=a.name)
            for a in self.session.query(WorkspaceAutomationModel).filter_by(group_id=self.group_id).order_by(WorkspaceAutomationModel.name).all()
        ]

        # The workspace's incoming (ingress) webhooks, offered to the `incoming_webhook` trigger.
        from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

        incoming_webhooks = [
            AutomationIncomingWebhookOption(id=w.id, slug=w.slug, name=w.name, enabled=bool(w.enabled), has_token=bool(w.token))
            for w in self.session.query(WorkspaceIncomingWebhookModel)
            .filter_by(group_id=self.group_id)
            .order_by(WorkspaceIncomingWebhookModel.name)
            .all()
        ]

        agents, playbooks = _agent_step_options(self.session, self.group_id, self.user)

        from marvin.schemas.group.automation_definition import TRIGGER_MODELS, definition_json_schema
        from marvin.services.automation.validation import condition_field_catalog

        condition_fields = {ttype: [AutomationConditionField(**f) for f in fields] for ttype, fields in condition_field_catalog().items()}

        return AutomationOptions(
            trigger_types=list(TRIGGER_MODELS),
            triggers=[name for names in groups.values() for name in names],
            trigger_groups=groups,
            emittable=[*offered_emittable(), *own],
            condition_ops=list(_OPS),
            condition_fields=condition_fields,
            action_kinds=available_kinds(),
            operations=operations,
            webhooks=webhooks,
            automations=targets,
            incoming_webhooks=incoming_webhooks,
            agents=agents,
            playbooks=playbooks,
            # The definition's JSON Schema — the one structural declaration the builder + SDK mirror.
            definition_schema=definition_json_schema(),
        )

    # ── Workflow Library ───────────────────────────────────────────────────────
    @router.get("/library", response_model=WorkflowLibraryRead, summary="Workflow Library")
    def library(self) -> WorkflowLibraryRead:
        """Every Library recipe, with what this workspace is missing to use it (`missing` empty → ready here), the
        capabilities the ideas wait on, and the workspace's names the setup pickers offer."""
        _require_admin(self.user, self.group_id)
        from marvin.schemas.platform.entries import ENTRY_STATUSES, TRASHED
        from marvin.services.automation import recipes
        from marvin.services.automation.authoring import workspace_refs

        refs = workspace_refs(self.session, self.group_id)
        uses = _recipe_uses(self.session, self.group_id)
        return WorkflowLibraryRead(
            recipes=[_library_recipe(item, refs, uses) for item in recipes.entries()],
            capabilities=recipes.catalogue()["capabilities"],
            refs=WorkflowLibraryRefs(
                entry_types=refs.entry_types,
                integrations=[{**i, "capabilities": i.get("capabilities") or []} for i in refs.integrations],
                collections=refs.collections,
                outgoing_webhooks=refs.outgoing_webhooks,
                incoming_webhooks=refs.incoming_webhooks,
                statuses=sorted(ENTRY_STATUSES - {TRASHED}),  # a workflow moves entries to the Trash with its own step
                agents=[{"slug": a["slug"], "name": a["name"]} for a in refs.agents if a["enabled"]],
            ),
        )

    @router.post("/library/{recipe_id}/configure", response_model=RecipeConfigureResult, summary="Fill in a Library recipe")
    def configure_recipe(self, recipe_id: str, data: RecipeConfigureRequest) -> RecipeConfigureResult:
        """The recipe filled in with `vars` for this workspace, for the workflow editor to load — nothing is saved (the
        editor's Save creates it, switched off). 404 unknown recipe; 409 not usable here (`detail` says why); 422 a
        setup value missing or of the wrong type."""
        _require_admin(self.user, self.group_id)
        from marvin.services.automation import recipes
        from marvin.services.automation.authoring import draft_issues
        from marvin.services.automation.library import RecipeConfigError

        try:
            document = recipes.configure_for(self.session, self.group_id, recipe_id, data.vars)
        except recipes.UnknownRecipe as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No recipe “{recipe_id}”.") from e
        except recipes.RecipeUnavailable as e:
            detail = f"“{recipe_id}” can't be used in this workspace: {'; '.join(e.reasons)}."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from e
        except RecipeConfigError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        definition = document["definition"]
        return RecipeConfigureResult(
            name=document["name"],
            definition=definition,
            issues=draft_issues(self.session, self.group_id, definition),
        )

    # ── Approval steps: runs waiting for a person (services/automation/approvals.py) ──
    @router.get("/approvals", response_model=list[WorkflowApprovalRead], summary="Workflow runs waiting for approval")
    def list_approvals(self) -> list[WorkflowApprovalRead]:
        """The runs in this workspace waiting at an Approval step that you may decide (your role is at least the step's
        `approvers`), oldest first. EDITOR and above."""
        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_workspace_role
        from marvin.services.automation import approvals

        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        role = _rank(self.user, self.group_id)
        return [_approval_read(self.session, row) for row in approvals.pending(self.session, self.group_id, role)]

    @router.post("/approvals/{approval_id}/decide", response_model=WorkflowApprovalRead, summary="Approve or deny a waiting run")
    def decide_approval(self, approval_id: UUID4, data: WorkflowApprovalDecision) -> WorkflowApprovalRead:
        """Approve or deny; the run goes on from the next step with `${steps.<id>.output.decision}` (approved, denied — or
        stale when the entry changed after it was asked). One with `choices` is approved with one of them (`choice`:
        the label or its index; 422 without). 403 below the step's role; 404 unknown; 409 already decided or expired."""
        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_workspace_role
        from marvin.services.automation import approvals

        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        role = _rank(self.user, self.group_id)
        try:
            row = approvals.decide(
                self.session, self.group_id, approval_id, data.decision, user_id=self.user.id, role=role, note=data.note, choice=data.choice
            )
        except approvals.ApprovalError as e:
            raise HTTPException(status_code=e.status, detail=str(e)) from e
        return _approval_read(self.session, row)

    @router.post("/validate", response_model=AutomationValidateResult, summary="Validate an automation definition")
    def validate(self, data: AutomationValidateRequest) -> AutomationValidateResult:
        """Check a definition before saving. Returns two levels of issue: structural **errors** (a
        shape the definition model rejects — unknown action kind, missing required field, wrong type;
        these block a save) and advisory **warnings** (coherent but won't match anything, e.g. entry.*
        under a webhook trigger). The builder surfaces both; only errors gate the save."""
        _require_admin(self.user, self.group_id)
        from marvin.services.automation.validation import structural_issues, validate_definition

        # Errors first (most severe), then advisory warnings.
        structural = structural_issues(data.definition)
        from marvin.services.automation.engine import workflow_max_steps

        issues = structural + validate_definition(data.definition, workflow_max_steps(self.session, self.group_id))
        if not structural:
            issues += self._missing_chain_warnings(data.definition)
            issues += self._custom_event_warnings(data.definition)
            issues += self._agent_step_warnings(data.definition)
        return AutomationValidateResult(issues=issues)

    def _agent_step_warnings(self, definition: dict) -> list[dict]:
        """An agent step naming an agent or Playbook this workspace lacks (or has switched off), or an agent whose permissions
        leave it nothing to do the job with. Warnings: the workflow saves, and the step fails when it runs."""
        from marvin.services.ai.tools.base import user_role
        from marvin.services.automation.authoring import agent_step_warnings, reference_issues

        if not any(isinstance(s, dict) and s.get("kind") == "agent" for key in ("actions", "on_failure") for s in definition.get(key) or []):
            return []
        named = [
            {**issue, "level": "warning"}
            for issue in reference_issues(self.session, self.group_id, definition)
            if issue["path"].endswith((".agent", ".playbooks"))
        ]
        return named + agent_step_warnings(self.session, self.group_id, definition, user_role(self.user, self.group_id))

    def _custom_event_warnings(self, definition: dict) -> list[dict]:
        """A trigger or Emit event step naming a `custom.*` event this workspace hasn't registered (or sending a field it
        doesn't have) — a pasted copy whose event hasn't been registered here yet. A warning: it saves, but won't run until
        the event is registered (Settings → Automation → Custom events)."""
        import json

        from marvin.services.automation.authoring import reference_issues
        from marvin.services.events.custom_events import PREFIX

        named = {w for w in json.dumps(definition).split('"') if w.startswith(PREFIX)}
        return [
            {**issue, "level": "warning"}
            for issue in reference_issues(self.session, self.group_id, definition)
            if any(f"“{name}”" in issue["message"] or f"{name} has no field" in issue["message"] for name in named)
        ]

    def _missing_chain_warnings(self, definition: dict) -> list[dict]:
        """An "after workflow X" trigger naming a workflow this workspace doesn't have — a pasted copy whose other half
        hasn't been copied yet. A warning: saving is fine, but it won't run until X exists here."""
        from marvin.services.automation.authoring import reference_issues

        return [
            {**issue, "level": "warning", "message": f"{issue['message']} Copy that workflow into this workspace too, or pick another."}
            for issue in reference_issues(self.session, self.group_id, definition)
            if issue.get("path") == "trigger.automation"
        ]

    @router.post("/preview", response_model=AutomationPreviewResult, summary="Dry-run a target selector")
    def preview(self, data: AutomationPreviewRequest) -> AutomationPreviewResult:
        """Resolve a definition's `target` query (with an optional test payload) and show which
        entities it would act on — WITHOUT running any action. `matches` is the capped set that also
        passes the conditions; `total` is the full query count so the caller sees when it's capped."""
        _require_admin(self.user, self.group_id)
        from marvin.services.automation.engine import _target_context, target_row_context
        from marvin.services.automation.matcher import matches as _conds_match
        from marvin.services.automation.selector import entity_ref, resolve_target_entities, target_entity

        defn = data.definition or {}
        target = defn.get("target")
        if not target:
            return AutomationPreviewResult(has_target=False)

        context: dict[str, Any] = {"event": {"event_type": "preview", "payload": data.payload or {}}, "previous": {}, "depth": 0}
        try:
            entities, total = resolve_target_entities(self.session, self.group_id, target, context)
        except Exception as e:
            return AutomationPreviewResult(has_target=True, entity=target.get("entity", "entry"), error=str(e))

        conditions = defn.get("conditions")
        kind = target_entity(target)
        matched: list[AutomationPreviewMatch] = []
        for ent in entities:
            ctx = _target_context(context, kind, target_row_context(self.session, self.group_id, kind, ent))
            if _conds_match(conditions, ctx):
                matched.append(AutomationPreviewMatch(**entity_ref(ent, kind)))

        return AutomationPreviewResult(
            has_target=True,
            entity=kind,
            total=total,
            capped=total > len(entities),
            matches=matched,
        )

    # ── Execution history ─────────────────────────────────────────────────────
    @router.get("/{automation_id}/executions", response_model=list[AutomationExecutionRead], summary="List recent runs")
    def list_executions(self, automation_id: UUID4, limit: int = 25) -> list[AutomationExecutionRead]:
        """Recent runs of this automation, newest first — status, targets, step counts, timing."""
        _require_admin(self.user, self.group_id)
        _get_or_404(self.session, automation_id, self.group_id)
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        rows = (
            self.session.query(AutomationExecutionModel)
            .filter_by(group_id=self.group_id, automation_id=automation_id)
            .order_by(AutomationExecutionModel.started_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [AutomationExecutionRead.model_validate(r) for r in rows]

    @router.post("/{automation_id}/executions/{execution_id}/cancel", response_model=AutomationExecutionRead, summary="Cancel a waiting run")
    def cancel_execution(self, automation_id: UUID4, execution_id: UUID4) -> AutomationExecutionRead:
        """Stop a run parked at a Wait step: it won't go on when its time comes (the steps after the wait never run;
        what ran before it stays). The run's status becomes `cancelled`. 409 when the run isn't waiting at a Wait step
        (a run waiting for an approval is decided on Automation → Approvals)."""
        _require_admin(self.user, self.group_id)
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel
        from marvin.db.models.groups.workflow_waits import WAIT_WAITING, WorkflowWaitModel
        from marvin.services.automation import waits

        row = self.session.get(AutomationExecutionModel, execution_id)
        if not row or row.group_id != self.group_id or row.automation_id != automation_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
        wait = self.session.query(WorkflowWaitModel).filter_by(execution_id=execution_id, status=WAIT_WAITING).first()
        if wait is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This run isn't waiting at a Wait step.")
        who = getattr(self.user, "full_name", None) or getattr(self.user, "username", None) or "an admin"
        waits.cancel(self.session, wait, f"cancelled by {who}")
        self.session.refresh(row)
        return AutomationExecutionRead.model_validate(row)

    @router.get("/{automation_id}/executions/{execution_id}", response_model=AutomationExecutionDetail, summary="Run detail")
    def get_execution(self, automation_id: UUID4, execution_id: UUID4) -> AutomationExecutionDetail:
        """One run plus its per-(target, step) records and the definition snapshot it ran against."""
        _require_admin(self.user, self.group_id)
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        row = self.session.get(AutomationExecutionModel, execution_id)
        if not row or row.group_id != self.group_id or row.automation_id != automation_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
        detail = AutomationExecutionDetail.model_validate(row)
        chain = _retry_chain(self.session, row)
        if len(chain) > 1:
            detail.retry_chain = [AutomationExecutionRead.model_validate(r) for r in chain]
        from marvin.db.models.groups.integration_errors import IntegrationRetryModel

        retries = (
            self.session.query(IntegrationRetryModel)
            .filter(IntegrationRetryModel.group_id == self.group_id, IntegrationRetryModel.origin_execution_id.in_([r.id for r in chain]))
            .order_by(IntegrationRetryModel.created_at)
            .all()
        )
        detail.retries = [IntegrationRetryRead.model_validate(r) for r in retries]
        return detail

    @router.get("/{automation_id}/samples", summary="Events a dry run can test against")
    def list_samples(self, automation_id: UUID4, limit: int = 10) -> dict:
        """Recent events this workflow's trigger would have fired on (newest first, each marked with
        whether its conditions pass) — then, for an entry trigger, recent entries no logged event
        covers. The dry run's sample picker. Empty for a workflow no event triggers."""
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        from marvin.services.automation.samples import list_samples, trigger_event

        samples = list_samples(self.session, self.group_id, row, user_id=self.user.id, limit=limit)
        return {"event_type": trigger_event(row), "samples": [s.describe() for s in samples]}

    @router.post("/{automation_id}/run", summary="Run an automation now (manual trigger)")
    def run_automation(
        self,
        automation_id: UUID4,
        bg_tasks: BackgroundTasks,
        dry_run: bool = False,
        entry_id: UUID4 | None = None,
        event_id: UUID4 | None = None,
        background: bool = False,
        body: AutomationRunRequest | None = None,
    ) -> dict:
        """Run the automation's steps immediately — the Manual trigger / Run button. Skips the
        trigger + condition gates (the caller asked for it explicitly).

        ``background=true`` starts the run after answering (``{"status": "started"}``) instead of waiting for it — for a
        run over many entries (re-listing a shop) that would outlast the request. Its progress is the usual
        automation_started / automation_ran events (the activity toasts) and the workflow's Runs.

        ``dry_run=true`` resolves the target + each action's inputs but executes nothing (no AI call,
        no mutation, no webhook POST) and records nothing — it returns ``plan``, the resolved per-step
        preview. A disabled draft can be dry-run (that's when you most want to preview it).

        An event-triggered workflow is dry-run against a sample event — ``event_id`` (an event_log
        row), ``entry_id`` (that entry's latest event of the trigger's type, or one built for it), or
        by default the latest matching event (see ``GET /samples``). The result adds ``sample``,
        ``trigger_matched``, per-condition ``conditions`` with the values compared, and
        ``would_fire``.

        The body's ``inputs`` are the run's inputs (the manual trigger's ``inputs``: ${input.<name>}); a missing
        required one, an unknown name or a value that doesn't fit is a 400 saying which."""
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        if (entry_id or event_id) and not dry_run:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A sample (entry_id / event_id) only applies to a dry run.")
        if entry_id and event_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pass entry_id or event_id, not both.")
        if not row.enabled and not dry_run:
            # A disabled automation is off — don't fire it via the Run button either (the scheduled
            # path already skips disabled). Enable it to run. (A dry run is fine — it does nothing.)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This workflow is disabled — enable it to run.",
            )
        from marvin.services.automation.engine import run_automation_now
        from marvin.services.automation.inputs import RunInputError, resolve
        from marvin.services.automation.recorder import ExecutionRecorder
        from marvin.services.automation.samples import trigger_event

        inputs = (body.inputs if body else None) or None
        if dry_run and (entry_id or event_id or trigger_event(row)):
            return {"status": "dry_run", **self._dry_run_with_sample(row, entry_id=entry_id, event_id=event_id)}
        try:
            resolve(self.session, self.group_id, row, inputs, dry_run=dry_run)  # refused now, not after answering
        except RunInputError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        if background and not dry_run:
            bg_tasks.add_task(_run_in_background, self.group_id, row.id, self.user.id, inputs)
            return {"status": "started", "ok": True}
        try:
            res = run_automation_now(
                self.session,
                self.group_id,
                row,
                user_id=self.user.id,
                dry_run=dry_run,
                recorder=None if dry_run else ExecutionRecorder(self.session, self.group_id),
                inputs=inputs,
            )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
        return {"status": "dry_run" if dry_run else "ran", **res}

    def _dry_run_with_sample(self, row, *, entry_id, event_id) -> dict:
        """An event-triggered dry run: against the picked (or default) sample event; with no sample
        to be had, the plain dry run — `sample: None` says nothing was found to test with."""
        from marvin.services.automation.engine import dry_run_for_event, run_automation_now
        from marvin.services.automation.samples import SampleNotApplicable, SampleNotFound, resolve_sample

        try:
            sample = resolve_sample(self.session, self.group_id, row, entry_id=entry_id, event_id=event_id, user_id=self.user.id)
        except SampleNotFound as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        except SampleNotApplicable as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        try:
            if sample is None:
                return {**run_automation_now(self.session, self.group_id, row, user_id=self.user.id, dry_run=True), "sample": None}
            return {**dry_run_for_event(self.session, self.group_id, row, sample.event_ctx), "sample": sample.describe()}
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    @router.post("", response_model=AutomationRead, status_code=status.HTTP_201_CREATED, summary="Create Automation")
    def create_automation(self, data: AutomationCreate) -> AutomationRead:
        _require_admin(self.user, self.group_id)
        with _as_http():
            row = create_workflow(self.session, self.group_id, self.user.id, data)
        return AutomationRead.model_validate(row)

    @router.get("/{automation_id}", response_model=AutomationRead, summary="Get Automation")
    def get_automation(self, automation_id: UUID4) -> AutomationRead:
        _require_admin(self.user, self.group_id)
        return AutomationRead.model_validate(_get_or_404(self.session, automation_id, self.group_id))

    @router.patch("/{automation_id}", response_model=AutomationRead, summary="Update Automation")
    def update_automation(self, automation_id: UUID4, data: AutomationUpdate) -> AutomationRead:
        from marvin.services.automation import toggle

        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        was_enabled = row.enabled
        with _as_http():
            row = update_workflow(self.session, self.group_id, row, data)
        if row.enabled != was_enabled:
            toggle.record_switch(self.session, self.group_id, toggle.WORKFLOW, row.id, actor_id=self.user.id, event_bus=self.event_bus)
        return AutomationRead.model_validate(row)

    @router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Automation")
    def delete_automation(self, automation_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        delete_workflow(self.session, self.group_id, row)
