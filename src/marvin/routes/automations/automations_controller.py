"""CRUD + builder-options routes for workspace automations (Flavor B orchestration).

ADMIN/OWNER-managed (an automation runs AI ops unattended, so registering one is a trust decision).
The `/options` endpoint advertises the builder's vocabulary — trigger events, condition operators,
action kinds, and the operations available as actions — so the UI is backend-driven.
"""

from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.automation import (
    AutomationActionOption,
    AutomationConditionField,
    AutomationCreate,
    AutomationExecutionDetail,
    AutomationExecutionRead,
    AutomationIncomingWebhookOption,
    AutomationOptions,
    AutomationPreviewMatch,
    AutomationPreviewRequest,
    AutomationPreviewResult,
    AutomationRead,
    AutomationTargetOption,
    AutomationUpdate,
    AutomationValidateRequest,
    AutomationValidateResult,
    AutomationWebhookOption,
    IntegrationRetryRead,
    RecipeConfigureRequest,
    RecipeConfigureResult,
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


def _library_recipe(item: dict, refs) -> WorkflowRecipe:
    """A catalogue entry as the Library and the editor's recipe picker show it, with what this workspace lacks."""
    from marvin.services.automation import recipes

    return WorkflowRecipe(
        **{key: item[key] for key in ("id", "title", "outcome", "category", "category_slug", "tags", "trigger", "status", "shape")},
        providers=[need["provider"] for need in (item.get("prerequisites") or {}).get("integrations") or []],
        side_effects=item.get("side_effects") or [],
        setup_variables=item.get("setup_variables") or [],
        supporting_objects=item.get("supporting_objects") or [],
        dependencies=item.get("dependencies") or [],
        missing=recipes.missing_prerequisites(item, refs),
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
        rows = self.session.query(WorkspaceAutomationModel).filter_by(group_id=self.group_id).order_by(WorkspaceAutomationModel.name).all()
        return [AutomationRead.model_validate(r) for r in rows]

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

        from marvin.schemas.group.automation_definition import TRIGGER_MODELS, definition_json_schema
        from marvin.services.automation.validation import condition_field_catalog

        condition_fields = {ttype: [AutomationConditionField(**f) for f in fields] for ttype, fields in condition_field_catalog().items()}

        return AutomationOptions(
            trigger_types=list(TRIGGER_MODELS),
            triggers=[name for names in groups.values() for name in names],
            trigger_groups=groups,
            emittable=offered_emittable(),
            condition_ops=list(_OPS),
            condition_fields=condition_fields,
            action_kinds=available_kinds(),
            operations=operations,
            webhooks=webhooks,
            automations=targets,
            incoming_webhooks=incoming_webhooks,
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
        return WorkflowLibraryRead(
            recipes=[_library_recipe(item, refs) for item in recipes.entries()],
            capabilities=recipes.catalogue()["capabilities"],
            refs=WorkflowLibraryRefs(
                entry_types=refs.entry_types,
                integrations=refs.integrations,
                collections=refs.collections,
                outgoing_webhooks=refs.outgoing_webhooks,
                incoming_webhooks=refs.incoming_webhooks,
                statuses=sorted(ENTRY_STATUSES - {TRASHED}),  # a workflow moves entries to the Trash with its own step
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
        issues = structural + validate_definition(data.definition)
        if not structural:
            issues += self._missing_chain_warnings(data.definition)
        return AutomationValidateResult(issues=issues)

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
    def run_automation(self, automation_id: UUID4, dry_run: bool = False, entry_id: UUID4 | None = None, event_id: UUID4 | None = None) -> dict:
        """Run the automation's steps immediately — the Manual trigger / Run button. Skips the
        trigger + condition gates (the caller asked for it explicitly).

        ``dry_run=true`` resolves the target + each action's inputs but executes nothing (no AI call,
        no mutation, no webhook POST) and records nothing — it returns ``plan``, the resolved per-step
        preview. A disabled draft can be dry-run (that's when you most want to preview it).

        An event-triggered workflow is dry-run against a sample event — ``event_id`` (an event_log
        row), ``entry_id`` (that entry's latest event of the trigger's type, or one built for it), or
        by default the latest matching event (see ``GET /samples``). The result adds ``sample``,
        ``trigger_matched``, per-condition ``conditions`` with the values compared, and
        ``would_fire``."""
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
        from marvin.services.automation.recorder import ExecutionRecorder
        from marvin.services.automation.samples import trigger_event

        if dry_run and (entry_id or event_id or trigger_event(row)):
            return {"status": "dry_run", **self._dry_run_with_sample(row, entry_id=entry_id, event_id=event_id)}
        try:
            res = run_automation_now(
                self.session,
                self.group_id,
                row,
                user_id=self.user.id,
                dry_run=dry_run,
                recorder=None if dry_run else ExecutionRecorder(self.session, self.group_id),
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
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        with _as_http():
            row = update_workflow(self.session, self.group_id, row, data)
        return AutomationRead.model_validate(row)

    @router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Automation")
    def delete_automation(self, automation_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, automation_id, self.group_id)
        delete_workflow(self.session, self.group_id, row)
