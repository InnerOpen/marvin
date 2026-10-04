"""Routes for AI operations — list, execute, and execution history."""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import UUID4

from marvin.db.models.groups.agents import WorkspaceAgentModel
from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.agent import (
    AgentCreate,
    AgentDefinitionPreviewRequest,
    AgentPromptPreview,
    AgentPromptPreviewRequest,
    AgentRead,
    AgentToolCategory,
    AgentUpdate,
)
from marvin.schemas.group.ai_execution import (
    AIAgentRequest,
    AIComposeEntryRequest,
    AIExecutionRead,
    AIOperationExecuteRequest,
    AIReindexRequest,
    AIReviseEntryRequest,
    AIToolInvokeRequest,
)
from marvin.schemas.group.ai_settings import (
    AssistantCharacter,
    AssistantCharacterAssign,
    AssistantCharacterLibraryChoice,
    AssistantCharacterUpload,
)
from marvin.schemas.group.ai_thread import AIThreadDetail, AIThreadMessageRead, AIThreadRead, AIThreadResumeRequest, AIThreadUpdate
from marvin.services.ai.agents import ROUTER_SLUG
from marvin.services.ai.executions import link_child_execution
from marvin.services.ai.parked_runs import ABANDONED_ERROR, ABANDONED_MESSAGE, EXECUTION_STATUS_AWAITING  # noqa: F401 — re-exported
from marvin.services.ui_links import entry_edit_url, entry_review_link

router = APIRouter(prefix="/ai", route_class=MarvinCrudRoute)

# `thread_id` value that asks a run to open a fresh thread (see AIAgentRequest.thread_id).
NEW_THREAD = "new"
# A delegated (hand-off) run's tool budget: the router asked for `max_steps` or this default, capped —
# a hand-off nests the child's model calls inside the parent's request.
DELEGATED_MAX_STEPS = 6
DELEGATED_MAX_STEPS_CAP = 8
# A new message on a thread that is parked for approval: "deny" denies the pending calls, clears the
# park and runs the message (the agent asks again if it still needs the action); "reject" refuses the
# message with 409 until the pending calls are decided.
PARKED_THREAD_ON_NEW_MESSAGE = "deny"


@controller(router)
class AIOperationsController(BaseUserController):
    # ── Operations catalogue ───────────────────────────────────────────

    @router.get("/operations", summary="List AI Operations")
    def list_operations(self) -> list[dict]:
        """Return all registered system operations and their schemas."""
        from marvin.services.ai.operations import list_operations

        return [op.info() for op in list_operations()]

    @router.get("/operations/{slug}", summary="Get AI Operation")
    def get_operation(self, slug: str) -> dict:
        from marvin.services.ai.operations import get_operation

        try:
            return get_operation(slug).info()
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Operation '{slug}' not found.") from None

    # ── Tools catalogue + generic execution (projected to MarvinMCP) ───

    @router.get("/tools", summary="List AI Tools")
    def list_tools(self) -> list[dict]:
        """Return the core tool registry specs projectable to MCP, filtered by the user's role.

        Mirror of `list_operations`: MarvinMCP reads this to auto-project each tool. A tool is
        listed only when it declares the `mcp` source and the caller meets its min_role.
        """
        from marvin.services.ai.tools import list_tools as _list_tools

        role = self._user_role()
        return [t.info() for t in _list_tools() if "mcp" in t.sources and role >= t.min_role]

    @router.get("/agent/tools", summary="List the agent's bound tools")
    def list_agent_tools(self) -> list[dict]:
        """The tool surface the `/agent` loop actually binds for THIS caller — so the UI can show
        "what can Marvin reach right now" honestly.

        Unlike `/tools` (the MCP projection), this is the live agent catalogue: built-in registry
        tools + `compose_entry` + allowlisted external MCP tools (only when the `external_mcp_enabled`
        master switch is on), all role-filtered. External tools are named `mcp__<server>__<tool>`;
        we surface `source` and the originating server so the UI can group them. No tool is called —
        this only reads names/descriptions off the bound tools (external servers are queried live for
        their tool list, so an unreachable server is simply omitted).

        Bound exactly as the bubble's Marvin binds them — through Marvin's permission matrix at the
        caller's role, on a run that can park — so blocked tools are absent and `asksFirst` marks the
        ones that pause for the user's approval.
        """
        spec = self._agent_or_404(ROUTER_SLUG)
        catalog: list[dict] = []
        for t in self._build_agent_tools(provider=None, agent=spec, role=self._user_role(), park_allowed=True):
            external = t.name.startswith("mcp__")
            server = None
            if external:
                # description is "[Server Name] <desc>"; recover the label for grouping.
                desc = t.description or ""
                if desc.startswith("[") and "]" in desc:
                    server = desc[1 : desc.index("]")]
            catalog.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "source": "external" if external else "builtin",
                    "server": server,
                    "category": t.category or None,
                    "asksFirst": bool(t.requires_approval),
                }
            )
        return catalog

    @router.post("/tools/{name}/invoke", summary="Invoke an AI Tool")
    def invoke_tool(self, name: str, body: AIToolInvokeRequest) -> dict:
        """Generic execution endpoint every projected registry tool routes through.

        Role-gates, checks the invocation source (tool's declared sources ∩ workspace policy),
        builds a ToolContext, then calls the tool's handler with the raw `args` and returns the
        JSON result. A provider is attached best-effort so tools that need one (semantic search)
        can use it; tools that don't simply ignore it.
        """
        import json

        from marvin.services.ai.factory import get_workspace_ai_provider
        from marvin.services.ai.tools import ToolContext, get_tool

        try:
            spec = get_tool(name)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{name}' not found.") from None

        if self._user_role() < spec.min_role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this tool.")

        # Invocation-source gate: tool's declared sources ∩ workspace policy.
        self._check_invocation_source(body.source, spec.sources)

        provider = None
        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except Exception:
            provider = None  # read tools work without a provider; search reports it's unavailable

        ctx = ToolContext(
            session=self.session,
            group_id=self.group_id,
            user=self.user,
            provider=provider,
            logger=self.logger,
        )
        # A handler raising is not fatal (mirrors the agent loop, which surfaces tool errors to
        # the model): roll back any poisoned transaction and return a structured error.
        try:
            raw = spec.handler(ctx, body.args or {})
        except Exception as e:
            self.session.rollback()
            self.logger.warning("AI tool '%s' handler failed: %s", name, e)
            return {"error": str(e)}
        # Handlers return a JSON string; hand back a JSON object to the caller.
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {"result": raw}

    # ── Execute ────────────────────────────────────────────────────────

    @router.post("/operations/{slug}/execute", response_model=AIExecutionRead, summary="Execute AI Operation")
    def execute_operation(self, slug: str, body: AIOperationExecuteRequest) -> AIExecutionRead:
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider
        from marvin.services.ai.operations import get_operation

        # Load and validate operation
        try:
            operation = get_operation(slug)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Operation '{slug}' not found.") from None

        # Permission check
        if not self.user.admin:
            role = 0
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id:
                    role = WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
                    break
            if role < operation.min_role:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this operation.")

        # Invocation-source gate: operation's declared sources ∩ workspace policy.
        body.source = self._check_invocation_source(body.source, operation.invocation_sources)

        # Budget check from workspace settings
        self._check_budget()

        # Resolve provider
        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except AIDisabledError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"AI provider error: {e}") from e

        # Determine model
        model = body.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")

        # Validate the selected model can satisfy the operation's capability requirements (§7)
        self._validate_model_capabilities(operation, model)

        # Accept either a UUID or a slug for entity_id — MCP/CLI callers work in slugs.
        entity_id = self._resolve_entity_id(body.entity_type, body.entity_id)

        # Build context via ContextBuilder
        from marvin.services.ai.context import ContextBuilder, resolve_prompt_messages

        builder = ContextBuilder(self.session, self.group_id).with_site_settings().with_variables()
        if body.entity_type == "entry" and entity_id:
            builder.with_entry(entity_id).with_assets(entity_id).with_resources(entity_id)
        elif body.entity_type == "asset" and entity_id:
            builder.with_asset(entity_id)
        elif body.entity_type == "resource" and entity_id:
            builder.with_resource(entity_id)
        elif body.entity_type == "form_submission" and entity_id:
            builder.with_form_submission(entity_id)
        # Vision operations need the raw image bytes loaded into context; an op that merely benefits
        # from seeing an image asset (generate-tags) gets them when the model can see.
        if operation.requires_vision or (
            body.entity_type == "asset" and getattr(operation, "sees_asset_image", False) and self._model_sees_images(model)
        ):
            builder.with_asset_images()
        # RAG operations retrieve semantically-similar workspace chunks for the question.
        if getattr(operation, "requires_retrieval", False):
            from marvin.core.config import get_app_settings
            from marvin.services.ai.embeddings import default_embedding_model
            from marvin.services.ai.embeddings_registry import indexable_types

            emb_model = default_embedding_model(provider.provider_type)
            query = body.input.get("question") or body.input.get("query") or ""
            if emb_model:
                top_k = getattr(get_app_settings(), "AI_RAG_TOP_K", 5)
                builder.with_semantic_search(query, provider, emb_model, limit=top_k, entity_types=indexable_types())
        ctx = builder.build()

        # Workspace logging policy: whether to persist inputs/outputs on the execution.
        log_inputs, log_outputs = self._logging_policy()

        # Create execution record (pending)
        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug=slug,
            provider_type=provider.provider_type,
            model_id=model,
            status="pending",
            triggered_by=self.user.id,
            trigger_type=body.source,
            entity_type=body.entity_type,
            entity_id=entity_id,
            input_json=body.input if log_inputs else None,
        )
        self.session.add(execution)
        self.session.commit()

        # Run the operation
        start = time.monotonic()
        try:
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            self.session.commit()

            # Build prompt then resolve {{SLUG}} references
            messages = operation.build_prompt(body.input, ctx)
            messages = resolve_prompt_messages(messages, self.group_id, ctx.variables)

            # execute_operation returns (parsed_dict, CompletionResult with token counts)
            from marvin.core.config import get_app_settings
            from marvin.services.ai.base import CompletionOptions

            _app = get_app_settings()
            opts = CompletionOptions(
                temperature=_app.AI_DEFAULT_TEMPERATURE,
                max_tokens=self._max_output_tokens(),
            )
            parsed, completion = provider.execute_operation(messages, model, operation.output_schema, opts)

            # For retrieval ops, attach the actual sources (index → entity + title) so the UI can
            # render clickable citations. IDs come from context, not the model, so they're authoritative.
            if getattr(operation, "requires_retrieval", False) and ctx.retrieved:
                parsed = {**(parsed or {}), "retrieved_sources": self._resolve_retrieved_sources(ctx.retrieved)}

            from marvin.services.ai.pricing import estimate_cost

            elapsed_ms = int((time.monotonic() - start) * 1000)
            execution.status = "completed"
            execution.completed_at = datetime.now(UTC)
            execution.duration_ms = elapsed_ms
            execution.output_json = parsed if log_outputs else None
            execution.prompt_tokens = completion.prompt_tokens
            execution.completion_tokens = completion.completion_tokens
            execution.total_tokens = completion.total_tokens
            execution.estimated_cost_usd = estimate_cost(
                provider.provider_type,
                model,
                completion.prompt_tokens,
                completion.completion_tokens,
            )
            self.session.commit()

            # Write-back: apply or stage the output onto the entity per approval_mode.
            # Record the outcome — without it a client cannot tell whether the entity was
            # changed ("applied") or a suggestion is waiting ("staged"), and so cannot report
            # honestly to the user. Also makes the distinction auditable after the fact.
            outcome = self._write_back(operation, body.entity_type, entity_id, parsed, execution.id)
            if outcome:
                execution.metadata_json = {**(execution.metadata_json or {}), "writeback": outcome}
                self.session.commit()

        except Exception as e:
            execution.status = "failed"
            execution.completed_at = datetime.now(UTC)
            execution.duration_ms = int((time.monotonic() - start) * 1000)
            execution.error_message = str(e)
            self.session.commit()
            self._emit_ai_event(execution, "failed", str(e))
            self._maybe_emit_quota(execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI call failed: {e}") from e

        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)
        return AIExecutionRead.model_validate(execution)

    # ── Execution history ──────────────────────────────────────────────

    @router.get("/executions", response_model=list[AIExecutionRead], summary="List Executions")
    def list_executions(
        self,
        operation_slug: str | None = None,
        status: str | None = None,
        entity_id: UUID4 | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AIExecutionRead]:
        q = self.session.query(AIExecutionModel).filter_by(group_id=self.group_id)
        if operation_slug:
            q = q.filter(AIExecutionModel.operation_slug == operation_slug)
        if status:
            q = q.filter(AIExecutionModel.status == status)
        if entity_id:
            q = q.filter(AIExecutionModel.entity_id == entity_id)
        rows = q.order_by(AIExecutionModel.created_at.desc()).offset(offset).limit(limit).all()
        return self._labelled(rows)

    @router.get("/executions/{execution_id}", response_model=AIExecutionRead, summary="Get Execution")
    def get_execution(self, execution_id: UUID4) -> AIExecutionRead:
        row = self.session.get(AIExecutionModel, execution_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
        return self._labelled([row])[0]

    def _labelled(self, rows: list) -> list[AIExecutionRead]:
        from marvin.services.ai.agents import agent_names, operation_label

        names = agent_names(self.session, self.group_id)
        return [AIExecutionRead.model_validate(r).model_copy(update={"operation_label": operation_label(r.operation_slug, names)}) for r in rows]

    @router.delete("/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Execution")
    def delete_execution(self, execution_id: UUID4) -> None:
        if not self.user.admin:
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id and WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0) >= 4:
                    break
            else:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN or OWNER role required.")
        row = self.session.get(AIExecutionModel, execution_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
        self.session.delete(row)
        self.session.commit()

    # ── Embeddings (RAG) ───────────────────────────────────────────────

    @router.post("/embeddings/reindex", summary="Reindex embeddings for semantic search / RAG")
    def reindex_embeddings(self, body: AIReindexRequest) -> dict:
        from marvin.services.ai.embeddings import default_embedding_model, index_entity
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider
        from marvin.services.ai.operations.base import ROLE_EDITOR

        # Workspace maintenance — require EDITOR or higher.
        if not self.user.admin:
            role = 0
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id:
                    role = WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
                    break
            if role < ROLE_EDITOR:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="EDITOR role or higher required.")

        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except AIDisabledError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        if not getattr(provider, "supports_embeddings", False):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Provider '{provider.provider_type}' does not support embeddings.",
            )
        model = default_embedding_model(provider.provider_type)
        if not model:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No default embedding model for this provider.",
            )

        if body.scope == "workspace":
            # A whole workspace takes minutes — longer than a request may last behind the tunnel — so
            # it runs in the background and reports through ai_embeddings_reindexed (toast + event log).
            from marvin.services.ai import reindex_jobs

            if not reindex_jobs.start(self.group_id, self.user.id if self.user else None, force=bool(body.force)):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A reindex is already running for this workspace.")
            return {"status": "started", "model": model}

        entities = chunks = 0
        for entity_type, entity_id, text in self._reindex_targets(body):
            try:
                chunks += index_entity(self.session, self.group_id, entity_type, entity_id, text, provider, model)
                entities += 1
            except Exception as e:
                self.logger.warning("reindex failed for %s %s: %s", entity_type, entity_id, e)
        self._emit_reindex_event(model, entities, chunks)
        return {"model": model, "entities_indexed": entities, "chunks_indexed": chunks}

    @router.get("/embeddings/status", summary="Search index status for this workspace")
    def embeddings_status(self) -> dict:
        """What the search index holds (chunks, items, models), the run in progress if any, and the last run."""
        from sqlalchemy import func

        from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
        from marvin.db.models.platform.event_log import EventLogModel
        from marvin.services.ai import reindex_jobs
        from marvin.services.ai.embeddings_registry import REGISTRY

        base = self.session.query(AIEmbeddingModel).filter(AIEmbeddingModel.group_id == self.group_id)
        chunks = base.count()
        items = base.with_entities(AIEmbeddingModel.entity_type, AIEmbeddingModel.entity_id).distinct().count()
        models = [m for (m,) in base.with_entities(AIEmbeddingModel.model_id).distinct().all()]
        indexable = sum(self.session.query(func.count(d.model.id)).filter(d.model.group_id == self.group_id).scalar() or 0 for d in REGISTRY.values())
        last = (
            self.session.query(EventLogModel)
            .filter(EventLogModel.workspace_id == self.group_id, EventLogModel.event_type == "ai_embeddings_reindexed")
            .order_by(EventLogModel.occurred_at.desc())
            .first()
        )
        return {
            "chunks": chunks,
            "items_indexed": items,
            "indexable": indexable,
            "models": models,
            "running": reindex_jobs.status(self.group_id),
            "last_run": {"at": last.occurred_at.isoformat(), "summary": last.message_body} if last else None,
        }

    # ── Compose (schema-driven draft generation) ───────────────────────

    @router.post("/compose-entry", summary="Compose a draft entry from a brief")
    def compose_entry(self, body: AIComposeEntryRequest) -> dict:
        """Generate a DRAFT entry of `entry_type` from a brief (+ optional images).

        The entry type's field schema IS the LLM output schema, so the model returns exactly
        the fields a valid entry needs. The result lands as status='inbox' for review — the
        caller (Marvin / MCP / UI) decides whether to publish, which fires the usual pipeline.
        """
        import uuid

        from marvin.db.models.platform.entry_types import EntryTypes
        from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
        from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
        from marvin.services.ai.factory import get_workspace_ai_provider
        from marvin.services.ai.operations.base import ROLE_AUTHOR

        # AUTHOR or higher — composing creates content.
        if not self.user.admin:
            role = 0
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id:
                    role = WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
                    break
            if role < ROLE_AUTHOR:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AUTHOR role or higher required.")

        # Compose is an authoring verb: reachable from the editor, MCP, the agent, and the API
        # (not forms/scheduled). Gated against the workspace invocation_sources policy.
        body.source = self._check_invocation_source(body.source, ("editor", "mcp", "agent", "api"))

        # Resolve entry type by slug (workspace or system), then by id.
        entry_type = (
            self.session.query(EntryTypes)
            .filter(EntryTypes.slug == body.entry_type)
            .filter((EntryTypes.group_id == self.group_id) | (EntryTypes.group_id.is_(None)))
            .first()
        )
        if not entry_type:
            try:
                et = self.session.get(EntryTypes, uuid.UUID(str(body.entry_type)))
                if et and et.group_id in (None, self.group_id):
                    entry_type = et
            except (ValueError, TypeError):
                entry_type = None
        if not entry_type:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entry type '{body.entry_type}' not found.")

        schema_def = EntryTypeSchemaDefinition.model_validate(entry_type.schema_json or {})
        recipe = EntryTypeRecipe.model_validate(entry_type.recipe_json or {})

        # Assign asset roles from the recipe (hero → first) so rendering (getFeaturedAsset) lights up.
        asset_attachments = self._recipe_asset_attachments(body.asset_ids or [], recipe)

        # Degrade gracefully: if AI is off / unconfigured / erroring, still create a blank
        # skeleton draft of this type so the flow works "at a very dumb level".
        provider = None
        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except Exception:
            provider = None
        model = (body.model_override or self._default_model()) if provider else None
        if not provider or not model:
            return self._compose_skeleton(body, entry_type, schema_def, asset_attachments)

        self._check_budget()

        # Author through the shared service (same brain the agent's compose_entry tool uses).
        from marvin.services.ai.authoring import AuthoringService

        assistant_name, persona_prompt = self._persona()
        log_inputs, log_outputs = self._logging_policy()
        service = AuthoringService(
            self.session,
            self.group_id,
            self.user,
            provider,
            model,
            event_bus=self.event_bus,
            logger=self.logger,
        )
        try:
            result = service.compose(
                entry_type=entry_type,
                brief=body.brief,
                asset_ids=body.asset_ids or [],
                asset_attachments=asset_attachments,
                source=body.source,
                assistant_name=assistant_name,
                persona_prompt=persona_prompt,
                register=body.tone_register,
                log_inputs=log_inputs,
                log_outputs=log_outputs,
                max_tokens=self._max_output_tokens(),
            )
        except HTTPException as he:
            if service.last_execution is not None:
                self._emit_ai_event(service.last_execution, "failed", str(he.detail))
            raise
        except Exception as e:
            if service.last_execution is not None:
                self._emit_ai_event(service.last_execution, "failed", str(e))
                self._maybe_emit_quota(service.last_execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Compose failed: {e}") from e

        # The controller owns the ai_operation event surface + budget notifications.
        execution = service.last_execution
        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)
        return result

    @router.post("/revise-entry", summary="Revise an existing entry from an instruction")
    def revise_entry(self, body: AIReviseEntryRequest) -> dict:
        """Revise an EXISTING entry in place per an instruction — the counterpart to compose.

        Same shared AuthoringService, but it enriches an entry that already exists (e.g.
        "determine the tags and attach relevant resources", "tighten the summary") instead of
        authoring a new draft. Grounded on the workspace catalog so it reuses existing tags and
        resources rather than duplicating. Unlike compose there is no skeleton fallback — reworking
        an entry has no meaning without a model, so an unconfigured provider is a hard error.
        """
        import uuid

        from marvin.db.models.platform.entries import Entries
        from marvin.services.ai.factory import get_workspace_ai_provider
        from marvin.services.ai.operations.base import ROLE_AUTHOR

        # AUTHOR or higher — revising mutates content.
        if not self.user.admin:
            role = 0
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id:
                    role = WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
                    break
            if role < ROLE_AUTHOR:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AUTHOR role or higher required.")

        # Same authoring surfaces as compose (editor / MCP / agent / API), gated by policy.
        body.source = self._check_invocation_source(body.source, ("editor", "mcp", "agent", "api"))

        # Resolve the entry (workspace-scoped) by slug then id.
        entry = self.session.query(Entries).filter(Entries.slug == body.entry, Entries.group_id == self.group_id).first()
        if not entry:
            try:
                e = self.session.get(Entries, uuid.UUID(str(body.entry)))
                if e and e.group_id == self.group_id:
                    entry = e
            except (ValueError, TypeError):
                entry = None
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entry '{body.entry}' not found.")
        # Revising is editing: an AUTHOR may revise only their own entries, and not approved/published ones.
        from marvin.routes._base.checks import require_can_edit_entry

        require_can_edit_entry(self.user, self.group_id, entry)

        provider = None
        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except Exception:
            provider = None
        model = (body.model_override or self._default_model()) if provider else None
        if not provider or not model:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No AI provider is configured for this workspace.")

        self._check_budget()

        from marvin.services.ai.authoring import AuthoringService

        log_inputs, log_outputs = self._logging_policy()
        service = AuthoringService(
            self.session,
            self.group_id,
            self.user,
            provider,
            model,
            event_bus=self.event_bus,
            logger=self.logger,
        )
        try:
            result = service.revise(
                entry=entry,
                instruction=body.instruction,
                source=body.source,
                register=body.tone_register,
                log_inputs=log_inputs,
                log_outputs=log_outputs,
                max_tokens=self._max_output_tokens(),
            )
        except HTTPException as he:
            if service.last_execution is not None:
                self._emit_ai_event(service.last_execution, "failed", str(he.detail))
            raise
        except Exception as e:
            if service.last_execution is not None:
                self._emit_ai_event(service.last_execution, "failed", str(e))
                self._maybe_emit_quota(service.last_execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Revise failed: {e}") from e

        execution = service.last_execution
        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)
        return result

    # ── Compose helpers ────────────────────────────────────────────────

    def _recipe_asset_attachments(self, asset_ids: list, recipe) -> list[dict]:
        """Map provided assets to the recipe's roles (first → hero, then declared order)."""
        roles = [r.role for r in recipe.assets.roles] if (recipe.assets and recipe.assets.roles) else []
        out: list[dict] = []
        for i, aid in enumerate(asset_ids):
            role = roles[i] if i < len(roles) else (roles[-1] if roles else None)
            out.append({"asset_id": str(aid), "role": role, "position": i})
        return out

    def _skeleton_data(self, schema_def, brief: str) -> dict:
        """Minimal valid data_json for a no-AI draft: required fields filled with type-appropriate
        placeholders, and the brief stashed into the first free-text field so it isn't lost."""
        from datetime import UTC, datetime

        def placeholder(f):
            t = f.type
            if t == "number":
                return 0
            if t == "boolean":
                return False
            if t == "select":
                opts = getattr(f, "options", []) or []
                return opts[0] if opts else ""
            if t == "date":
                return datetime.now(UTC).date().isoformat()
            if t == "datetime":
                return datetime.now(UTC).isoformat()
            if t == "json":
                return {}
            return ""  # text / textarea / markdown

        data: dict = {f.key: placeholder(f) for f in schema_def.get_required_fields()}
        for f in schema_def.fields:
            if f.type in ("markdown", "textarea", "text"):
                data[f.key] = brief
                break
        return data

    def _compose_skeleton(self, body, entry_type, schema_def, asset_attachments) -> dict:
        """No-AI fallback: create a blank draft of the type so /compose still works when AI is off."""
        brief = (body.brief or "").strip()
        first_line = brief.splitlines()[0].strip() if brief else ""
        title = first_line[:120] or f"New {entry_type.name}"
        entry = self.repos.entries.create(
            {
                "title": title,
                "entry_type_id": entry_type.id,
                "status": "inbox",
                "data_json": self._skeleton_data(schema_def, brief),
                "asset_attachments": asset_attachments or None,
                "created_by": self.user.id,
            }
        )
        self.session.commit()
        self._emit_entry_created(entry, entry_type)
        return {
            "entryId": str(entry.id),
            "status": entry.status,
            "title": title,
            "editUrl": entry_edit_url(entry.id),
            "reviewLink": entry_review_link(entry.id),
            "executionId": None,
            "totalTokens": None,
            "estimatedCostUsd": None,
            "generated": entry.data_json,
            "aiSkipped": True,
        }

    # ── Agent (tool-calling loop) ──────────────────────────────────────

    @router.post("/agent", summary="Run the Marvin agent (tool-calling loop)")
    def run_agent(self, body: AIAgentRequest) -> dict:
        """Run the default agent (`marvin`): an iterative tool-calling loop over Marvin's capabilities.

        Tools are Marvin's own read/authoring surfaces — search, browse, list types, compose a draft —
        plus AI operations and allow-listed external MCP tools. The model decides which to call; the
        loop runs them and feeds results back until it answers. Requires a tool-capable provider.
        Composing still creates an `inbox` draft for human review; the agent never publishes.
        Named agents (system or workspace-defined) run through `POST /agents/{slug}/run`.
        """
        from marvin.services.ai.operations.base import ROLE_AUTHOR

        # AUTHOR or higher — the default agent can create/modify content.
        self._require_role(ROLE_AUTHOR, "AUTHOR role or higher required.")
        body.source = self._check_invocation_source(body.source, ("agent", "editor", "api", "mcp"))
        self._check_budget()

        provider = self._agent_provider()
        model = body.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")
        self._require_tool_capable(provider, model)

        entity_id = self._resolve_entity_id(body.entity_type, body.entity_id)
        # This is the Ask page's Marvin under another URL (the bubble's default agent), so it binds
        # through Marvin's permission matrix exactly as `/agents/marvin/run` does: "ask first" tools
        # park the run when there is a thread to park on, and are not bound without one.
        spec = self._agent_or_404(ROUTER_SLUG)
        tools, ctx = self._bind_agent_tools(provider, agent=spec, role=self._user_role(), park_allowed=bool(body.thread_id))
        max_steps = self._agent_max_steps(body)

        assistant_name, persona_prompt = self._persona()
        system = self._default_agent_system_prompt(assistant_name)
        # Explicit per-call register wins; otherwise the workspace default; otherwise "auto".
        system += self._register_clause(body.tone_register or self._default_register(), persona_prompt)
        ctx.tone_register = body.tone_register  # drafts the run writes use its tone (None → workspace default)
        return self._run_agent_core(
            provider=provider,
            model=model,
            system=system,
            body=body,
            entity_id=entity_id,
            tools=tools,
            max_steps=max_steps,
            operation_slug=f"agent:{ROUTER_SLUG}",
            agent_slug=ROUTER_SLUG,
            ctx=ctx,
        )

    # ── Agents (definable: system + workspace rows) ─────────────────────

    @router.get("/agents", response_model=list[AgentRead], summary="List agents (built-in + workspace-defined)")
    def list_agents(self) -> list[AgentRead]:
        from marvin.services.ai.agents import list_agents as _list

        packs: dict = {}  # agents sharing a library pack look it up once
        return [self._agent_read(spec, self._agent_character(spec, packs)) for spec in _list(self.session, self.group_id)]

    @router.get("/agents/catalog", summary="Tool catalog for the permission matrix (categories, tools, operations)")
    def agents_catalog(self) -> dict:
        from marvin.services.ai.tools.categories import CATEGORIES

        return {"categories": [c.__dict__ for c in CATEGORIES], "tools": self._catalog_with_mcp()}

    @router.get("/agents/runs/{run_id}/progress", summary="Live steps of an in-flight agent run (poll while the run POST is pending)")
    def agent_run_progress(self, run_id: str) -> dict:
        """`{status, events}` for a run started with `client_run_id`; 404 when unknown, expired, or not yours.

        Process-local (see services/ai/run_progress.py) — with several backend replicas a poll may miss;
        clients treat 404 as "no live steps", never as a failed run.
        """
        from marvin.services.ai import run_progress

        rid = run_progress.normalize_run_id(run_id)
        run = run_progress.get(rid, (self.group_id, self.user.id)) if rid else None
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such run (unknown, expired, or not yours).")
        return run.to_dict()

    @router.get("/agents/{slug}/permissions", summary="Effective permission matrix of an agent for the caller")
    def agent_permissions(self, slug: str) -> dict:
        from marvin.services.ai.agents import permission_matrix

        spec = self._agent_or_404(slug)
        role = self._user_role()
        return {"agent": spec.slug, "role": role, "allowWrites": spec.allow_writes, "rows": permission_matrix(spec, role, self._catalog_with_mcp())}

    @router.get("/agents/{slug}", response_model=AgentRead, summary="Get an agent")
    def get_agent(self, slug: str) -> AgentRead:
        spec = self._agent_or_404(slug)
        return self._agent_read(spec, self._agent_character(spec))

    @router.post("/agents", response_model=AgentRead, status_code=status.HTTP_201_CREATED, summary="Define an agent")
    def create_agent(self, data: AgentCreate) -> AgentRead:
        from marvin.services.ai.agents import spec_from_row
        from marvin.services.ai.operations.base import ROLE_ADMIN

        self._require_role(ROLE_ADMIN, "ADMIN role or higher required to define agents.")
        exists = self.session.query(WorkspaceAgentModel).filter_by(group_id=self.group_id, slug=data.slug).first()
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"An agent with slug '{data.slug}' already exists.")
        self._require_known_tone(data.default_register)
        row = WorkspaceAgentModel(session=self.session, group_id=self.group_id, created_by=self.user.id, **data.model_dump())
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        spec = spec_from_row(row)
        return self._agent_read(spec, self._agent_character(spec))

    @router.patch("/agents/{slug}", response_model=AgentRead, summary="Update an agent")
    def update_agent(self, slug: str, data: AgentUpdate) -> AgentRead:
        from marvin.services.ai.agents import spec_from_row
        from marvin.services.ai.operations.base import ROLE_ADMIN

        self._require_role(ROLE_ADMIN, "ADMIN role or higher required to edit agents.")
        row = self._agent_row_or_404(slug)
        self._require_known_tone(data.default_register)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(row, k, v)
        self.session.commit()
        self.session.refresh(row)
        spec = spec_from_row(row)
        return self._agent_read(spec, self._agent_character(spec))

    @router.delete("/agents/{slug}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an agent")
    def delete_agent(self, slug: str) -> None:
        from marvin.services.ai.operations.base import ROLE_ADMIN

        self._require_role(ROLE_ADMIN, "ADMIN role or higher required to delete agents.")
        row = self._agent_row_or_404(slug)
        character = row.character
        self.session.delete(row)
        self.session.commit()
        if character:
            from marvin.services.ai.character import delete_character_files

            delete_character_files(self._character_store(), character)

    # ── An agent's bubble character (services/ai/character.py; the workspace's is in AI settings) ──
    # Custom agents only: system agents are code, not rows, and `marvin` plays the workspace's character.

    def _character_store(self):
        from marvin.services.ai.character import WorkspaceAssetStore
        from marvin.services.assets.asset_storage_service import AssetStorageService
        from marvin.services.storage.provider_factory import get_storage_provider

        return WorkspaceAssetStore(AssetStorageService(self.repos, get_storage_provider()), self.group_id, self.user.id)

    def _agent_character(self, spec, packs: dict | None = None) -> dict | None:
        from marvin.services.ai.character import describe
        from marvin.services.ai.character_library import resolve

        return describe(resolve(self.session, spec.character, packs))

    def _character_admin_row(self, slug: str) -> WorkspaceAgentModel:
        from marvin.services.ai.operations.base import ROLE_ADMIN

        self._require_role(ROLE_ADMIN, "ADMIN role or higher required to edit agents.")
        return self._agent_row_or_404(slug)

    def _save_agent_character(self, row: WorkspaceAgentModel, character: dict | None) -> None:
        from marvin.services.ai.character import save_character

        save_character(self.session, row, "character", character, self._character_store())

    @router.post("/agents/{slug}/character", response_model=AssistantCharacterUpload, summary="Upload an agent's bubble character")
    def upload_agent_character(self, slug: str, files: list[UploadFile] = File(...)) -> AssistantCharacterUpload:
        """The agent's own character, from a .zip or GIF/WebP/PNG files (as the workspace's); replaces its previous one."""
        from marvin.services.ai.character import CharacterError, describe, plan_character, read_upload_files, store_character

        row = self._character_admin_row(slug)
        try:
            plan = plan_character(read_upload_files(files))
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        character = store_character(self._character_store(), plan)
        self._save_agent_character(row, character)
        return AssistantCharacterUpload(**describe(character), ignored=plan.ignored, idle_guessed=plan.idle_guessed, cleared=plan.cleared)

    @router.put("/agents/{slug}/character/states", response_model=AssistantCharacter, summary="Assign an agent's bubble character state")
    def assign_agent_character_state(self, slug: str, data: AssistantCharacterAssign) -> AssistantCharacter:
        from marvin.services.ai.agents import spec_from_row
        from marvin.services.ai.character import CharacterError, assign_state

        row = self._character_admin_row(slug)
        try:
            character = assign_state(row.character, data.state, data.file)
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        self._save_agent_character(row, character)
        return AssistantCharacter(**self._agent_character(spec_from_row(row)))

    @router.put("/agents/{slug}/character/library", response_model=AssistantCharacter, summary="Give an agent a library character")
    def use_agent_library_character(self, slug: str, data: AssistantCharacterLibraryChoice) -> AssistantCharacter:
        """The agent plays a library pack; its own uploaded character, if any, is deleted."""
        from marvin.services.ai.agents import spec_from_row
        from marvin.services.ai.character import CharacterError
        from marvin.services.ai.character_library import library_reference

        row = self._character_admin_row(slug)
        try:
            choice = library_reference(self.session, data.pack)
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        self._save_agent_character(row, choice)
        return AssistantCharacter(**self._agent_character(spec_from_row(row)))

    @router.delete("/agents/{slug}/character", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an agent's bubble character")
    def delete_agent_character(self, slug: str) -> None:
        """The bubble shows the workspace's character for this agent again; its own files are deleted."""
        row = self._character_admin_row(slug)
        if row.character:
            self._save_agent_character(row, None)

    @router.post("/agents/preview-prompt", response_model=AgentPromptPreview, summary="Preview the system prompt of an agent not saved yet")
    def preview_new_agent_prompt(self, data: AgentDefinitionPreviewRequest) -> AgentPromptPreview:
        """As `/agents/{slug}/preview-prompt`, for the New form: `data` is the whole create payload, read as the
        saved agent would be. Nothing is stored; never calls a model."""
        from marvin.services.ai.agents import unsaved_spec

        self._require_preview_role()
        return self._prompt_preview(unsaved_spec(data.model_dump(exclude={"slug"}), (data.slug or "").strip().lower()))

    @router.post("/agents/{slug}/preview-prompt", response_model=AgentPromptPreview, summary="Preview the system prompt an agent runs with")
    def preview_agent_prompt(self, slug: str, data: AgentPromptPreviewRequest) -> AgentPromptPreview:
        """What a run of this agent sends the model as its system prompt, assembled by the run's own code, in
        labelled parts: the workspace preamble, the agent's instructions, the character and tone (with the rule
        for which wins), and who it may hand off to. `data` is the Edit form's unsaved values; anything left
        out is the stored agent's. Tools are bound as you would run it from the Ask page and only counted per
        category. Never calls a model.
        """
        self._require_preview_role()
        return self._prompt_preview(self._agent_with_overrides(self._agent_or_404(slug), data))

    def _require_preview_role(self) -> None:
        from marvin.services.ai.operations.base import ROLE_ADMIN

        self._require_role(ROLE_ADMIN, "ADMIN role or higher required to preview an agent's prompt.")

    def _prompt_preview(self, spec) -> AgentPromptPreview:
        """The preview of `spec`'s system prompt, built by the helpers a real run uses."""
        from marvin.services.ai import tones as t

        assistant_name, persona_prompt = self._persona()
        tones = self._tones()
        register = self._effective_register(None, spec)
        instructions = self._named_agent_instructions(spec, assistant_name)
        system = instructions + self._register_clause(register, persona_prompt)
        preamble = roster = ""
        tools: list = []
        if spec.kind != "model":
            # No provider: binding only builds the tool list; nothing runs, so nothing reaches a model.
            tools, _ = self._bind_agent_tools(None, agent=spec, role=self._user_role(), park_allowed=True)
            preamble, roster = self._system_frame({tool.name for tool in tools}, spec.slug)
            system = self._framed(system, preamble, roster)
        return AgentPromptPreview(
            system=system,
            tokens=t.estimate_tokens(system),
            kind=spec.kind,
            workspace=preamble,
            instructions=instructions,
            default_instructions=not spec.system_prompt,
            tone=t.preview(tones.resolve(register), persona_prompt),
            tone_source="agent" if spec.default_register and tones.get(spec.default_register) else "workspace",
            roster=roster,
            tool_count=len(tools),
            ask_first_count=sum(1 for tool in tools if getattr(tool, "requires_approval", False)),
            tool_categories=self._tool_categories(tools),
        )

    @staticmethod
    def _agent_with_overrides(spec, data: AgentPromptPreviewRequest):
        """`spec` with the form's unsaved values; a field sent as null keeps its stored value where null
        means nothing for it (name, kind, the toggles), and clears it where it does (instructions, tone)."""
        from dataclasses import replace

        changes = data.model_dump(exclude_unset=True)
        for key in ("name", "kind", "min_role", "enabled", "allow_writes", "sources"):
            if changes.get(key, ...) is None:
                del changes[key]
        for key in ("tool_allowlist", "sources", "suggestions"):
            if changes.get(key) is not None:
                changes[key] = tuple(changes[key])
        return replace(spec, **changes)

    @staticmethod
    def _tool_categories(tools: list) -> list[AgentToolCategory]:
        """Bound tools counted per permission-matrix category, in the matrix's order."""
        from collections import Counter

        from marvin.services.ai.tools.categories import CATEGORIES

        counts = Counter(tool.category or "other_write" for tool in tools)
        labels = {c.id: c.label for c in CATEGORIES}
        order = [c.id for c in CATEGORIES] + sorted(set(counts) - set(labels))
        return [AgentToolCategory(id=cid, label=labels.get(cid, cid), count=counts[cid]) for cid in order if counts[cid]]

    @router.post("/agents/{slug}/run", summary="Run a named agent (built-in or workspace-defined)")
    def run_named_agent(self, slug: str, body: AIAgentRequest) -> dict:
        """Same loop as `/agent`, shaped by the agent: its prompt, model, tool allowlist and write policy.

        Who may talk to it is the agent's `min_role`; what it may *do* is still bound by the caller's
        own role (a VIEWER running `marvin` gets its read-only tools). `model` agents are a plain
        completion — no tools, no retrieval.
        """
        from marvin.services.ai.agents import may_talk
        from marvin.services.ai.operations.base import execution_source

        spec = self._agent_or_404(slug)
        role = self._user_role()
        ok, reason = may_talk(spec, role, execution_source(body.source))
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        body.source = self._check_invocation_source(body.source, ("agent", "editor", "api", "mcp"))
        self._check_budget()

        provider = self._agent_provider()
        model = body.model_override or spec.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")

        assistant_name, persona_prompt = self._persona()
        register = self._effective_register(body.tone_register, spec)
        system = self._named_agent_instructions(spec, assistant_name) + self._register_clause(register, persona_prompt)
        if spec.kind == "model":
            return self._run_model_agent(spec, provider, model, system, body)

        self._require_tool_capable(provider, model)
        entity_id = self._resolve_entity_id(body.entity_type, body.entity_id)
        # The agent's matrix decides per tool; a write still needs the caller to be AUTHOR+. "Ask first"
        # tools are bound only when there is a thread to park the run on (NEW_THREAD counts).
        tools, ctx = self._bind_agent_tools(provider, agent=spec, role=role, park_allowed=bool(body.thread_id))
        ctx.tone_register = register
        max_steps = self._agent_max_steps(body)
        return self._run_agent_core(
            provider=provider,
            model=model,
            system=system,
            body=body,
            entity_id=entity_id,
            tools=tools,
            max_steps=max_steps,
            operation_slug=f"agent:{spec.slug}",
            agent_slug=spec.slug,
            ctx=ctx,
        )

    # ── Threads (server-side Ask conversations) ─────────────────────────
    # Any future literal `/threads/<word>` route must be declared before `/threads/{thread_id}`.

    @router.get("/threads", response_model=list[AIThreadRead], summary="List my Ask threads (admins: every thread)")
    def list_threads(self, agent: str | None = None, limit: int = 50, children: bool = False) -> list[AIThreadRead]:
        """Top-level threads, every agent's unless `agent` is given.

        `children=true` adds the specialist threads opened by hand-offs (each with `parentThreadId` and
        `parentTitle`) under the listed ones; `limit` counts the listed threads, not their children.
        With `agent`, that agent's hand-off threads count as listed too.
        """
        from marvin.services.ai.threads import list_threads

        rows = list_threads(
            self.session, self.group_id, self.user.id, see_all=self._sees_all_threads(), agent_slug=agent, limit=limit, include_children=children
        )
        return [AIThreadRead.model_validate(r) for r in rows]

    @router.get("/threads/{thread_id}", response_model=AIThreadDetail, summary="Get a thread with its messages")
    def get_thread(self, thread_id: str) -> AIThreadDetail:
        thread = self._thread_or_404(thread_id)
        return self._thread_detail(thread)

    @router.patch("/threads/{thread_id}", response_model=AIThreadRead, summary="Rename a thread")
    def update_thread(self, thread_id: str, data: AIThreadUpdate) -> AIThreadRead:
        thread = self._thread_or_404(thread_id)
        if "title" in data.model_fields_set:
            thread.title = (data.title or "").strip() or None
        self.session.commit()
        self.session.refresh(thread)
        return AIThreadRead.model_validate(thread)

    @router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a thread")
    def delete_thread(self, thread_id: str) -> None:
        thread = self._thread_or_404(thread_id)
        self.session.delete(thread)
        self.session.commit()

    @router.post("/threads/{thread_id}/resume", summary="Decide the calls a paused run is waiting on and continue it")
    def resume_thread(self, thread_id: str, data: AIThreadResumeRequest) -> dict:
        """Continue a run parked by an "ask first" tool: approved calls run, denied ones tell the model
        the user declined, and the loop goes on — on the same execution row, in the same thread. Only
        the thread's owner may decide (admins see the thread but cannot approve on its behalf). A
        missing decision is a deny. The run may park again; the response has the same shape as a run.

        A specialist's ask carried up through a hand-off (slice C2) is decided here too: its id is a path
        (`c1/c7`). The specialist resumes first on its own thread and execution; its answer becomes the
        hand-off's result and the router finishes once. Resuming on the specialist's own thread forwards
        to the root conversation (ids translated), so one place decides; the answer is the root's.
        Permissions are taken at decision time, never widened: the owner of every thread involved, the
        caller may still talk to each agent, and each run's tools rebound at the caller's current role.
        """
        from marvin.core.config import get_app_settings
        from marvin.services.ai.agent import DECISION_APPROVE, DECISION_DENY, flatten_pending
        from marvin.services.ai.agents import may_talk
        from marvin.services.ai.parked_runs import REASON_EXPIRED, end_tree, execution_of, is_expired, root_of, tree_threads
        from marvin.services.ai.threads import pending_state
        from marvin.services.event_bus_service.event_types import EventTypes

        thread = self._thread_or_404(thread_id)
        self._require_thread_owner(thread)
        if pending_state(thread) is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This thread has nothing waiting for approval.")
        root, prefix = root_of(self.session, thread)
        requested = {f"{prefix}{k}": v for k, v in data.decisions.items()}
        for t in tree_threads(self.session, root):
            self._require_thread_owner(t)
        pending = pending_state(root)
        spec = self._agent_or_404(root.agent_slug)
        role = self._user_role()
        # Resuming a paused conversation is agent chat from the surface that resumes it (the Ask page or
        # the bubble), gated like the original run.
        ok, reason = may_talk(spec, role, "agent")
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        self._check_invocation_source(data.source, ("agent",))
        self._check_budget()
        if is_expired(root, int(get_app_settings().AI_PARKED_RUN_TTL_HOURS or 0)):
            execution = execution_of(self.session, pending)
            calls = end_tree(self.session, root, REASON_EXPIRED)
            self._emit_approval_event(
                EventTypes.approval_rejected, root, execution, calls, {str(c["id"]): DECISION_DENY for c in calls}, reason=REASON_EXPIRED
            )
            self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="This request expired before it was approved; send a new message instead."
            )
        if execution_of(self.session, pending) is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The paused run's execution record is gone; send a new message instead.")
        run = dict(pending.get("run") or {})
        # Refuse before anything is announced or cleared: the user can decide again once this is fixed.
        model = run.get("model") or spec.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")
        self._require_tool_capable(self._agent_provider(), model)

        flat = flatten_pending(pending.get("calls"))
        if prefix and any(not str(c["id"]).startswith(prefix) for c in flat):
            # Decided on a specialist's thread, but the conversation above waits on more than this
            # specialist: deciding here would deny actions the user never saw. Decide them all there.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This decision belongs to the conversation that handed off ({root.id}), which waits on other actions too; decide there.",
            )
        decisions = {str(c["id"]): (DECISION_APPROVE if requested.get(str(c["id"])) == DECISION_APPROVE else DECISION_DENY) for c in flat}
        execution = execution_of(self.session, pending)
        for kind, event_type in ((DECISION_APPROVE, EventTypes.approval_granted), (DECISION_DENY, EventTypes.approval_rejected)):
            subset = [c for c in flat if decisions[str(c["id"])] == kind]
            if subset:
                self._emit_approval_event(event_type, root, execution, subset, decisions, surface=data.source)

        body = self._resume_body(root, run, client_run_id=data.client_run_id)
        run_id, on_event = self._start_progress(body, root, execution)
        try:
            return self._resume_leg(root, pending, decisions, depth=0, on_event=on_event, run_id=run_id, surface=data.source, chain=())
        except HTTPException as e:
            self._finish_progress(run_id, "failed", self._http_error_text(e))
            raise

    def _require_thread_owner(self, thread) -> None:
        if str(thread.created_by) != str(self.user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the thread's owner can decide its pending actions.")

    @staticmethod
    def _resume_body(thread, run: dict, client_run_id: str | None = None) -> AIAgentRequest:
        """The request a parked run is resumed as: its last user turn and its own stored parameters."""
        last_user = next((m.content for m in sorted(thread.messages, key=lambda m: m.seq, reverse=True) if m.role == "user"), "")
        return AIAgentRequest(
            message=last_user,
            source="agent",
            thread_id=str(thread.id),
            max_steps=run.get("max_steps"),
            register=run.get("register"),
            entity_type=run.get("entity_type"),
            entity_id=run.get("entity_id"),
            client_run_id=client_run_id,
        )

    def _resume_leg(self, thread, pending: dict, decisions: dict[str, str], *, depth: int, on_event, run_id, surface: str, chain: tuple) -> dict:  # noqa: C901
        """Resume one parked run of a tree, children first.

        `decisions` are path-keyed relative to this run. Each hand-off call resumes its specialist
        (`_resume_child`): an answer becomes the call's output; a specialist that parks again keeps the
        call pending with a fresh snapshot. Then this run's loop continues once — or, while a specialist
        is still waiting, settles its own decisions and parks again without asking the model.
        """
        import time

        from marvin.services.ai.agent import (
            DECISION_APPROVE,
            DECISION_DENY,
            PENDING_CALL,
            STOPPED_AWAITING_APPROVAL,
            ResumeState,
            deserialize_pending,
            deserialize_steps,
            run_agent_loop,
            split_decisions,
        )
        from marvin.services.ai.base import deserialize_messages
        from marvin.services.ai.parked_runs import REASON_NOT_PERMITTED, execution_of, own_calls, record_approvals
        from marvin.services.ai.threads import clear_pending

        spec = self._agent_or_404(thread.agent_slug)
        role = self._user_role()
        execution = execution_of(self.session, pending)
        if execution is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The paused run's execution record is gone; send a new message instead.")
        run = dict(pending.get("run") or {})
        provider = self._agent_provider()
        model = run.get("model") or spec.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")
        self._require_tool_capable(provider, model)

        # Rebound first, at the caller's current role: a hand-off this run may no longer make (its matrix now
        # blocks run_agent, or AI_HANDOFF_MAX_DEPTH was lowered) does not resume the specialist.
        tools, ctx = self._bind_agent_tools(provider, agent=spec, role=role, depth=depth, park_allowed=True)
        may_hand_off = "run_agent" in {t.name for t in tools}
        calls = deserialize_pending(pending.get("calls"))
        outputs: dict[str, str] = {}
        for call in calls:
            if call.kind == PENDING_CALL:
                continue
            if may_hand_off:
                outcome = self._resume_child(
                    call, split_decisions(decisions, call.id), depth=depth + 1, on_event=on_event, surface=surface, chain=(*chain, spec.slug)
                )
            else:
                outcome = self._end_child(call, REASON_NOT_PERMITTED, surface, "hand-offs are no longer permitted here")
            if outcome is not None:
                outputs[call.id] = self._json(outcome)
        own = {c.id: (DECISION_APPROVE if decisions.get(c.id) == DECISION_APPROVE else DECISION_DENY) for c in calls if c.kind == PENDING_CALL}
        record_approvals(execution, own_calls(pending), own, decided_by=self.user.id, surface=surface)

        body = self._resume_body(thread, run, client_run_id=None)
        ctx.execution_id = str(execution.id)
        ctx.tone_register = self._effective_register(run.get("register"), spec)
        if depth < self._handoff_max_depth() and may_hand_off:
            ctx.delegate = self._delegate_runner(
                parent_thread=thread, parent_body=body, parent_execution=execution, on_event=on_event, depth=depth, chain=(*chain, spec.slug)
            )
        parent = pending.get("parent")
        # The park is cleared before the loop: a provider failure leaves an open thread and a failed
        # execution, never a stale park.
        clear_pending(thread)
        execution.status = "running"
        self.session.commit()

        max_steps = int(run.get("max_steps") or self._agent_max_steps(body))
        _, log_outputs = self._logging_policy()
        start = time.monotonic()
        try:
            result = run_agent_loop(
                provider,
                model,
                [],
                tools,
                self._completion_opts(),
                max_steps=max_steps,
                on_event=on_event,
                resume=ResumeState(convo=deserialize_messages(pending.get("convo")), pending=calls, decisions=own, outputs=outputs),
            )
        except HTTPException:
            raise
        except Exception as e:
            # The caller finishes the live steps (`resume_thread` on the HTTPException below).
            self._fail_execution(execution, str(e), start)
            self._emit_ai_event(execution, "failed", str(e))
            self._maybe_emit_quota(execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Agent failed: {e}") from e

        common = {
            "provider": provider,
            "model": model,
            "body": body,
            "thread": thread,
            "execution": execution,
            "result": result,
            "steps": [*deserialize_steps(pending.get("steps")), *result.steps],
            "referrals": [*(pending.get("referrals") or []), *ctx.referrals],
            "agent_slug": spec.slug,
            "start": start,
            "run_id": run_id,
            "log_outputs": log_outputs,
            "record_user": False,
        }
        if result.stopped_reason == STOPPED_AWAITING_APPROVAL:
            return self._park_agent_run(max_steps=max_steps, entity_id=run.get("entity_id"), emit=depth == 0, parent=parent, **common)
        return self._finish_agent_run(**common)

    def _resume_child(self, call, decisions: dict[str, str], *, depth: int, on_event, surface: str, chain: tuple) -> dict | None:
        """Resume the specialist a deferred hand-off call waits on. Returns the call's output (the
        specialist's answer, or an error the router answers around), or None when the specialist parked
        again — `call.child` then holds its fresh snapshot."""
        from marvin.db.models.groups.ai_threads import AIThreadModel
        from marvin.services.ai.agents import may_talk, resolve_agent
        from marvin.services.ai.parked_runs import REASON_FAILED, REASON_NOT_PERMITTED
        from marvin.services.ai.threads import pending_state

        child = call.child or {}
        slug = str(child.get("agent") or "")
        name = child.get("name") or slug
        thread = self.session.get(AIThreadModel, self._uuid_or_none(child.get("thread_id")))
        record = pending_state(thread) if thread is not None else None
        if record is None:
            return {"error": f"{name}'s paused request is gone; answer without it", "agent": slug}
        spec = resolve_agent(self.session, self.group_id, slug)
        ok, reason = may_talk(spec, self._user_role(), "agent") if spec is not None else (False, "the agent no longer exists")
        if not ok:
            return self._end_child(call, REASON_NOT_PERMITTED, surface, reason)
        try:
            res = self._resume_leg(
                thread, record, decisions, depth=depth, on_event=self._via_listener(on_event, spec.slug), run_id=None, surface=surface, chain=chain
            )
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else self._json(e.detail)
            if pending_state(thread) is not None:
                # It failed before its own resume began (no model, agent disabled, …): end the park properly
                # rather than leave its execution waiting forever.
                return self._end_child(call, REASON_FAILED, surface, detail)
            return {"error": detail, "agent": spec.slug}
        if res.get("stoppedReason") == "awaiting_approval":
            call.child = self._handoff_record(spec, res)
            return None
        return self._handoff_output(spec, res)

    def _end_child(self, call, reason: str, surface: str, why: str) -> dict:
        """End the parked tree under a hand-off call without running it; the router hears why."""
        from marvin.db.models.groups.ai_threads import AIThreadModel
        from marvin.services.ai.parked_runs import REASON_NOT_PERMITTED, end_tree
        from marvin.services.ai.threads import pending_state

        child = call.child or {}
        slug = str(child.get("agent") or "")
        name = child.get("name") or slug
        thread = self.session.get(AIThreadModel, self._uuid_or_none(child.get("thread_id")))
        if thread is not None and pending_state(thread) is not None:
            end_tree(self.session, thread, reason, decided_by=self.user.id, surface=surface)
            self.session.commit()
        if reason == REASON_NOT_PERMITTED:
            return {"error": f"{name} is no longer permitted for this user ({why}); nothing it asked for was done", "agent": slug}
        return {"error": f"{name} could not continue ({why}); nothing it asked for was done", "agent": slug}

    @staticmethod
    def _json(value) -> str:
        import json

        return json.dumps(value)

    @staticmethod
    def _uuid_or_none(value):
        from marvin.services.ai.threads import _uuid

        return _uuid(value)

    # ── Thread helpers ─────────────────────────────────────────────────

    def _sees_all_threads(self) -> bool:
        from marvin.services.ai.operations.base import ROLE_ADMIN

        return self._user_role() >= ROLE_ADMIN

    def _thread_or_404(self, thread_id: str, agent_slug: str | None = None):
        from marvin.services.ai.threads import ThreadAgentMismatch, ThreadNotFound, resolve_thread

        try:
            return resolve_thread(self.session, self.group_id, thread_id, self.user.id, see_all=self._sees_all_threads(), agent_slug=agent_slug)
        except ThreadNotFound:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No thread '{thread_id}'.") from None
        except ThreadAgentMismatch as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None

    def _thread_detail(self, thread) -> AIThreadDetail:
        from marvin.services.ai.agent import flatten_pending
        from marvin.services.ai.parked_runs import root_of
        from marvin.services.ai.threads import pending_state

        detail = AIThreadDetail.model_validate(thread)
        detail.messages = [AIThreadMessageRead.model_validate(m) for m in sorted(thread.messages, key=lambda m: m.seq)]
        record = pending_state(thread)
        detail.pending = flatten_pending((record or {}).get("calls"))
        if record is not None:
            root, _ = root_of(self.session, thread)
            detail.root_thread_id = root.id if root is not thread else None
        return detail

    def _thread_for_run(self, body: AIAgentRequest, agent_slug: str):
        """The existing thread this run continues, or None (stateless, or a thread to open after the run)."""
        if not body.thread_id or body.thread_id == NEW_THREAD:
            return None
        return self._thread_or_404(body.thread_id, agent_slug=agent_slug)

    def _run_history(self, body: AIAgentRequest, thread) -> list:
        """History for the model: the thread's stored turns when there is one, else the client's replay."""
        from marvin.services.ai.threads import history_rows

        return self._bounded_history(history_rows(thread) if thread is not None else body.history)

    def _record_thread_turns(
        self,
        thread,
        body: AIAgentRequest,
        agent_slug: str,
        execution,
        answer: str,
        steps,
        sources: list[dict],
        tokens: int,
        *,
        handoffs: list[dict] | None = None,
        referrals: list[dict] | None = None,
        parent_thread_id=None,
        record_user: bool = True,
    ):
        """After a successful run: open the thread if this is its first turn, then store question + answer.

        Hand-offs and referrals land in the assistant turn's meta only when there are any, so a plain
        turn's meta keeps its two-key shape. A resumed run passes `record_user=False`: its user turn
        was stored when the run parked.
        """
        from marvin.services.ai.threads import append_turn, create_thread, touch

        if thread is None:
            if body.thread_id != NEW_THREAD:
                return None
            thread = create_thread(
                self.session,
                self.group_id,
                self.user.id,
                agent_slug,
                body.message,
                body.entity_type,
                execution.entity_id,
                parent_thread_id=parent_thread_id,
            )
        _, log_outputs = self._logging_policy()
        meta: dict = {"sources": sources, "totalTokens": tokens}
        if handoffs:
            meta["handoffs"] = handoffs
        if referrals:
            meta["referrals"] = referrals
        if record_user:
            append_turn(self.session, thread, "user", body.message)
        append_turn(
            self.session,
            thread,
            "assistant",
            answer or "",
            steps=steps,
            meta=meta,
            execution_id=execution.id,
            log_outputs=log_outputs,
        )
        touch(thread, tokens)
        execution.metadata_json = {**(execution.metadata_json or {}), "thread_id": str(thread.id)}
        self.session.commit()
        return thread

    # ── Agent helpers ──────────────────────────────────────────────────

    def _start_progress(self, body: AIAgentRequest, thread=None, execution=None):
        """(run_id, on_event) for a run the client wants to watch, or (None, None).

        The run's thread and execution are recorded with it, so a client that lost the response
        (navigated away mid-run) can still find the answer.
        """
        from marvin.services.ai import run_progress

        run_id = run_progress.normalize_run_id(body.client_run_id)
        if run_id is None:
            return None, None
        run_progress.start(
            run_id,
            (self.group_id, self.user.id),
            thread_id=thread.id if thread is not None else None,
            execution_id=execution.id if execution is not None else None,
        )
        return run_id, lambda event: run_progress.push(run_id, event)

    @staticmethod
    def _finish_progress(run_id: str | None, status_: str, error: str | None = None) -> None:
        from marvin.services.ai import run_progress

        if run_id is not None:
            run_progress.finish(run_id, status_, error)

    @staticmethod
    def _http_error_text(e: HTTPException) -> str:
        import json

        return e.detail if isinstance(e.detail, str) else json.dumps(e.detail)

    def _require_role(self, min_role: int, detail: str) -> None:
        if self._user_role() < min_role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    def _agent_provider(self):
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider

        try:
            return get_workspace_ai_provider(self.session, self.group_id)
        except AIDisabledError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"AI provider error: {e}") from e

    def _agent_max_steps(self, body: AIAgentRequest) -> int:
        from marvin.core.config import get_app_settings
        from marvin.services.ai.agent import DEFAULT_MAX_STEPS

        _app = get_app_settings()
        configured = int(body.max_steps or getattr(_app, "AI_AGENT_MAX_STEPS", DEFAULT_MAX_STEPS) or DEFAULT_MAX_STEPS)
        return min(configured, 12)

    def _agent_or_404(self, slug: str):
        from marvin.services.ai.agents import resolve_agent

        spec = resolve_agent(self.session, self.group_id, slug)
        if spec is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No agent '{slug}'.")
        return spec

    def _agent_row_or_404(self, slug: str) -> WorkspaceAgentModel:
        from marvin.schemas.group.agent import SYSTEM_AGENT_SLUGS

        slug = (slug or "").strip().lower()
        if slug in SYSTEM_AGENT_SLUGS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{slug}' is a built-in agent and cannot be edited.")
        row = self.session.query(WorkspaceAgentModel).filter_by(group_id=self.group_id, slug=slug).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No agent '{slug}'.")
        return row

    @staticmethod
    def _agent_read(spec, character: dict | None = None) -> AgentRead:
        return AgentRead(
            id=spec.id,
            slug=spec.slug,
            name=spec.name,
            description=spec.description,
            kind=spec.kind,
            system_prompt=spec.system_prompt,
            model_override=spec.model_override,
            tool_allowlist=list(spec.tool_allowlist) if spec.tool_allowlist is not None else None,
            default_register=spec.default_register,
            min_role=spec.min_role,
            sources=list(spec.sources),
            enabled=spec.enabled,
            allow_writes=spec.allow_writes,
            tool_policy=dict(spec.tool_policy) if spec.tool_policy else None,
            icon=spec.icon,
            suggestions=list(spec.suggestions) if spec.suggestions else None,
            handoff_hint=spec.handoff_hint,
            is_system=spec.is_system,
            character=character,
        )

    @staticmethod
    def _restrict_tools(tools: list, agent, role: int, *, park_allowed: bool = False) -> list:
        """Apply an agent's allowlist, permission matrix and write policy to the bound toolset.

        Every bound tool carries a category (registry tools by name, AI operations `ai_ops`,
        external MCP `mcp`); `resolve_policy` decides per tool and never lets a write through to a
        caller below AUTHOR, whatever the matrix says. An "ask first" tool is kept — flagged
        `requires_approval` — only when the run can park (`park_allowed`); otherwise it is dropped,
        as if blocked.
        """
        from marvin.services.ai.agents import POLICY_ALLOW, POLICY_ASK, resolve_policy

        kept = []
        for t in tools:
            decision = resolve_policy(agent, t.name, t.category or "other_write", role)[0]
            if decision == POLICY_ALLOW:
                kept.append(t)
            elif decision == POLICY_ASK and park_allowed:
                t.requires_approval = True
                kept.append(t)
        return kept

    @staticmethod
    def _default_agent_system_prompt(assistant_name: str) -> str:
        return (
            f"You are {assistant_name}, the assistant for this headless CMS workspace. Use the provided tools to "
            "search, browse, and (only when asked) author content. Prefer tools over guessing and ground "
            "your answer in what they return. To answer what EXISTS in the workspace — the tag vocabulary, "
            "resources, entry types, collections, workflows — call the matching list tool (list_tags, "
            "list_resources, list_entry_types, list_collections, list_workflows), or workspace_overview for the "
            "whole inventory (its `structure` block names every workflow, scheduled task, webhook, integration, MCP server and agent). "
            "Reserve search_content for finding content by MEANING; it is "
            "semantic, so it surfaces items that merely mention a word and must not be used to enumerate a "
            "vocabulary (asking it 'what tags exist' returns content, not tags). Before proposing or attaching "
            "tags, resources, or assets, first discover what already exists — call list_tags (then search_content "
            "for related content) — and REUSE the matches that fit each item; only create something new when nothing fits. To author, "
            "use compose_entry for a NEW entry and revise_entry to "
            "change an EXISTING one (never recreate). Authoring creates a DRAFT for human review — never claim "
            "anything is published. When a request could reasonably map to two different tools or readings — "
            "e.g. enumerate a vocabulary vs. find content by meaning — answer the most likely one, then add ONE "
            "short line offering the alternative (what you would do differently and how to ask for it). Do this "
            "only when the reading is genuinely forked; never append a 'did you mean…' to an unambiguous request. "
            "Be concise."
        )

    def _named_agent_instructions(self, spec, assistant_name: str) -> str:
        """A named agent's own part of its system prompt: its instructions, else its kind's default. The
        character/tone section follows it; a persona run then frames both (`_system_frame`)."""
        from marvin.services.ai.agents import model_agent_system_prompt

        name = assistant_name if spec.is_system else spec.name
        if spec.kind == "model":
            return spec.system_prompt or model_agent_system_prompt(name, router_name=assistant_name)
        return spec.system_prompt or self._default_agent_system_prompt(name)

    def _system_frame(self, tool_names: set[str], agent_slug: str) -> tuple[str, str]:
        """(preamble, roster) around a persona run's own prompt. Environment facts come first — what "the
        RAG" means here and which of the bound tools answers which kind of question; the agents it may hand
        off or refer to come last ("" when it can do neither)."""
        from marvin.services.ai.agents import list_agents, roster_block, workspace_preamble

        preamble = workspace_preamble(self._workspace_name(), tool_names)
        roster = ""
        if "run_agent" in tool_names or "suggest_agent" in tool_names:
            specs = list_agents(self.session, self.group_id)
            roster = roster_block(specs, agent_slug, self._user_role(), "agent", can_handoff="run_agent" in tool_names)
        return preamble, roster

    @staticmethod
    def _framed(system: str, preamble: str, roster: str) -> str:
        framed = preamble + "\n\n" + system
        return framed + "\n\n" + roster if roster else framed

    def _catalog_with_mcp(self) -> list[dict]:
        """The registry catalog plus the MCP tools discovered right now, so the matrix can show and
        override real `mcp__server__tool` names rather than a blind category row."""
        from marvin.services.ai.agents import catalog_tools
        from marvin.services.ai.operations.base import ROLE_VIEWER

        catalog = catalog_tools()
        for t in self._external_mcp_tools():
            catalog.append(
                {
                    "name": t.name,
                    "category": t.category,
                    "description": t.description,
                    "kind": "mcp",
                    "readOnly": t.category == "mcp_read",
                    "minRole": ROLE_VIEWER,
                }
            )
        return catalog

    def _workspace_name(self) -> str | None:
        from marvin.db.models.groups.groups import Groups

        group = self.session.query(Groups).filter(Groups.id == self.group_id).first()
        return getattr(group, "name", None)

    def _run_agent_core(
        self,
        *,
        provider,
        model,
        system: str,
        body: AIAgentRequest,
        entity_id,
        tools: list,
        max_steps: int,
        operation_slug: str,
        agent_slug: str,
        ctx=None,
        on_event=None,
        parent_thread_id=None,
        execution_meta: dict | None = None,
        handoff_chain: tuple = (),
    ) -> dict:
        """The shared tail of every persona run: context block, history, execution row, loop, bookkeeping.

        `ctx` is the ToolContext the tools were bound with (hand-offs hang the delegate on it and read
        its referrals). A delegated child run passes `on_event` (the parent's listener, tagged `via`),
        `parent_thread_id` (so its thread hangs off the router's), `execution_meta` and the agents
        above it (`handoff_chain`). A child that stops on an ask parks quietly on its own thread,
        pointing up; the parent's hand-off call then defers (slice C2).
        """
        import time
        from datetime import UTC, datetime

        from marvin.services.ai.agent import STOPPED_AWAITING_APPROVAL, run_agent_loop
        from marvin.services.ai.base import Message
        from marvin.services.ai.threads import create_thread, pending_state

        names = {t.name for t in tools}
        depth = getattr(ctx, "depth", 0) if ctx is not None else 0
        thread = self._thread_for_run(body, agent_slug)
        if thread is not None and depth == 0 and pending_state(thread):
            if PARKED_THREAD_ON_NEW_MESSAGE == "reject":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="This thread is waiting for your approval; decide the pending actions first."
                )
            self._abandon_pending(thread)
        # Ground the run in what the user is looking at. Prefer a pre-assembled context block
        # (title/status/fields/attachments) so the agent can answer immediately; fall back to the
        # bare id hint when we can't assemble one, so it can still fetch the entity itself.
        context_block = self._agent_context_block(body.entity_type, entity_id)
        # Environment facts come first, the agent's own persona after: what "the RAG" means here and which
        # of the bound tools answers which kind of question.
        system = self._framed(system, *self._system_frame(names, agent_slug))
        user_msg = body.message
        if context_block:
            system += (
                "\n\n## What the user is currently looking at\n"
                f"{context_block}\n"
                "This is a summary, not the whole record — use the tools when you need more "
                "detail, related content, or anything not shown above. When the user says "
                '"this"/"it" without naming something, they mean this.'
            )
        elif body.entity_type and entity_id:
            user_msg += f"\n\n(Context: the user is currently looking at {body.entity_type} {entity_id}.)"
        messages = [
            Message(role="system", content=system),
            *self._run_history(body, thread),
            Message(role="user", content=user_msg),
        ]

        # A new thread is opened before the loop: a router's hand-offs hang their child threads off it,
        # and its id is known while the run is in flight, so a client that navigates away mid-run (the
        # bubble) can find the answer there afterwards. A failed run drops it again.
        opened_here = False
        if thread is None and body.thread_id == NEW_THREAD:
            thread = create_thread(
                self.session, self.group_id, self.user.id, agent_slug, body.message, body.entity_type, entity_id, parent_thread_id=parent_thread_id
            )
            opened_here = True

        log_inputs, log_outputs = self._logging_policy()
        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug=operation_slug,
            provider_type=provider.provider_type,
            model_id=model,
            status="running",
            triggered_by=self.user.id,
            trigger_type=body.source,
            entity_type=body.entity_type,
            entity_id=entity_id,
            input_json={"message": body.message} if log_inputs else None,
            metadata_json=self._run_meta(execution_meta, thread),
        )
        execution.started_at = datetime.now(UTC)
        self.session.add(execution)
        self.session.commit()
        if ctx is not None:
            ctx.execution_id = str(execution.id)  # tools spawning executions link them back here

        start = time.monotonic()
        run_id, local_on_event = self._start_progress(body, thread, execution)
        on_event = local_on_event or on_event
        if ctx is not None and depth < self._handoff_max_depth() and "run_agent" in names:
            ctx.delegate = self._delegate_runner(
                parent_thread=thread,
                parent_body=body,
                parent_execution=execution,
                on_event=on_event,
                depth=depth,
                chain=(*handoff_chain, agent_slug),
            )
        try:
            result = run_agent_loop(provider, model, messages, tools, self._completion_opts(), max_steps=max_steps, on_event=on_event)
        except HTTPException as e:
            self._finish_progress(run_id, "failed", self._http_error_text(e))
            self._discard_empty_thread(thread if opened_here else None)
            raise
        except Exception as e:
            self._finish_progress(run_id, "failed", f"Agent failed: {e}")
            self._fail_execution(execution, str(e), start)
            self._discard_empty_thread(thread if opened_here else None)
            self._emit_ai_event(execution, "failed", str(e))
            self._maybe_emit_quota(execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Agent failed: {e}") from e

        common = {
            "provider": provider,
            "model": model,
            "body": body,
            "thread": thread,
            "execution": execution,
            "result": result,
            "steps": list(result.steps),
            "referrals": list(ctx.referrals) if ctx is not None else [],
            "agent_slug": agent_slug,
            "start": start,
            "run_id": run_id,
            "log_outputs": log_outputs,
        }
        if result.stopped_reason == STOPPED_AWAITING_APPROVAL:
            parent = None
            if depth > 0 and parent_thread_id:
                parent = {"thread_id": parent_thread_id, "execution_id": (execution_meta or {}).get("parent_execution_id")}
            # A specialist's ask is announced once, by the conversation it is carried up to.
            return self._park_agent_run(max_steps=max_steps, entity_id=entity_id, emit=depth == 0, parent=parent, **common)
        return self._finish_agent_run(parent_thread_id=parent_thread_id, **common)

    @staticmethod
    def _run_meta(execution_meta: dict | None, thread) -> dict | None:
        """A run's execution metadata, naming its thread from the start rather than only when it ends,
        so a run a restart kills is closed on its thread by the next process (services/ai/interrupted_runs.py)."""
        if thread is None:
            return execution_meta
        return {**(execution_meta or {}), "thread_id": str(thread.id)}

    def _completion_opts(self):
        from marvin.core.config import get_app_settings
        from marvin.services.ai.base import CompletionOptions

        _app = get_app_settings()
        return CompletionOptions(temperature=_app.AI_DEFAULT_TEMPERATURE, max_tokens=self._max_output_tokens())

    def _account_execution(self, execution, result, provider, model, start: float) -> None:
        """Add a loop leg's tokens and wall time to the execution row (a resumed run keeps its row)."""
        import time

        from marvin.services.ai.pricing import estimate_cost

        execution.prompt_tokens = int(execution.prompt_tokens or 0) + int(result.prompt_tokens or 0)
        execution.completion_tokens = int(execution.completion_tokens or 0) + int(result.completion_tokens or 0)
        execution.total_tokens = int(execution.total_tokens or 0) + int(result.total_tokens or 0)
        execution.duration_ms = int(execution.duration_ms or 0) + int((time.monotonic() - start) * 1000)
        execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, execution.prompt_tokens, execution.completion_tokens)

    def _finish_agent_run(
        self,
        *,
        provider,
        model,
        body: AIAgentRequest,
        thread,
        execution,
        result,
        steps: list,
        referrals: list[dict],
        agent_slug: str,
        start: float,
        run_id,
        log_outputs: bool,
        parent_thread_id=None,
        record_user: bool = True,
    ) -> dict:
        """The tail of a run that answered: close the execution, store the turn(s), emit, respond.

        `steps` is the whole trace — on a resumed run the steps from before the park plus the new
        ones — and drives the output, sources, hand-offs and the stored turn. Tokens and duration
        accumulate on the execution row.
        """
        from datetime import UTC, datetime

        from marvin.services.ai.threads import extract_handoffs, extract_sources

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        self._account_execution(execution, result, provider, model, start)
        execution.output_json = (
            {"answer": result.answer, "steps": [{"tool": s.tool, "arguments": s.arguments} for s in steps]} if log_outputs else {"steps": len(steps)}
        )
        sources = extract_sources(steps)
        handoffs, child_referrals = extract_handoffs(steps)
        referrals = [*referrals, *child_referrals]
        thread = self._record_thread_turns(
            thread,
            body,
            agent_slug,
            execution,
            result.answer,
            steps,
            sources,
            execution.total_tokens,
            handoffs=handoffs,
            referrals=referrals,
            parent_thread_id=parent_thread_id,
            record_user=record_user,
        )
        self.session.commit()
        # Only once the turn is committed: a poller that sees "completed" must find the answer in the thread.
        self._finish_progress(run_id, "completed")
        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)

        return {
            "answer": result.answer,
            "steps": [{"tool": s.tool, "arguments": s.arguments, "result": s.result} for s in steps],
            "sources": sources,
            "handoffs": handoffs,
            "referrals": referrals,
            "stoppedReason": result.stopped_reason,
            "executionId": str(execution.id),
            "threadId": str(thread.id) if thread is not None else None,
            "totalTokens": execution.total_tokens,
            "estimatedCostUsd": execution.estimated_cost_usd,
        }

    def _park_agent_run(
        self,
        *,
        provider,
        model,
        body: AIAgentRequest,
        thread,
        execution,
        result,
        steps: list,
        referrals: list[dict],
        agent_slug: str,
        start: float,
        run_id,
        log_outputs: bool,
        max_steps: int,
        entity_id,
        record_user: bool = True,
        emit: bool = True,
        parent: dict | None = None,
    ) -> dict:
        """The tail of a run that stopped on an "ask first" tool: store the user's turn, freeze the
        loop on the thread, leave the execution `awaiting_approval` (no completed_at), tell the
        event bus, and answer with the pending calls instead of an answer.

        `pending` in the answer is flattened: a hand-off that deferred shows as its specialist's own
        asks (`c1/c7`, tagged `via`). A specialist's park passes `emit=False` and its `parent`.
        """
        from marvin.services.ai.agent import flatten_pending
        from marvin.services.ai.threads import append_turn, create_thread, park_thread
        from marvin.services.event_bus_service.event_types import EventTypes

        if thread is None:
            thread = create_thread(self.session, self.group_id, self.user.id, agent_slug, body.message, body.entity_type, entity_id)
        if record_user:
            append_turn(self.session, thread, "user", body.message)
        execution.status = EXECUTION_STATUS_AWAITING
        self._account_execution(execution, result, provider, model, start)
        execution.metadata_json = {**(execution.metadata_json or {}), "thread_id": str(thread.id)}
        park_thread(
            self.session,
            thread,
            calls=result.pending_calls,
            convo=result.convo,
            execution_id=execution.id,
            run={
                "agent_slug": agent_slug,
                "max_steps": max_steps,
                "register": body.tone_register,
                "entity_type": body.entity_type,
                "entity_id": str(entity_id) if entity_id else None,
                "model": model,
            },
            steps=steps,
            referrals=referrals,
            parent=parent,
        )
        self.session.commit()
        self._finish_progress(run_id, EXECUTION_STATUS_AWAITING)
        pending = flatten_pending((thread.pending_json or {}).get("calls"))
        if emit:
            self._emit_approval_event(EventTypes.approval_requested, thread, execution, pending)
        return {
            "answer": "",
            "steps": [{"tool": s.tool, "arguments": s.arguments, "result": s.result} for s in steps],
            "sources": [],
            "handoffs": [],
            "referrals": referrals,
            "stoppedReason": result.stopped_reason,
            "pending": pending,
            "executionId": str(execution.id),
            "threadId": str(thread.id),
            "totalTokens": execution.total_tokens,
            "estimatedCostUsd": None,
        }

    def _abandon_pending(self, thread) -> None:
        """A new message arrived on a parked thread: end the whole parked tree it belongs to — up to the
        conversation the decision is taken on, and down through every specialist parked under it. Each
        pending call is denied, each parked execution failed, each thread gets a short assistant turn
        (turns stay alternating) and its park cleared. approval_rejected fires once, on the root, with
        reason "abandoned". The new message then runs as usual; the agent asks again if it still needs
        the action.
        """
        from marvin.services.ai.agent import DECISION_DENY
        from marvin.services.ai.parked_runs import REASON_ABANDONED, end_tree, execution_of, root_of
        from marvin.services.ai.threads import pending_state
        from marvin.services.event_bus_service.event_types import EventTypes

        root, _ = root_of(self.session, thread)
        execution = execution_of(self.session, pending_state(root))
        calls = end_tree(self.session, root, REASON_ABANDONED, decided_by=self.user.id)
        decisions = {str(c.get("id")): DECISION_DENY for c in calls}
        self._emit_approval_event(EventTypes.approval_rejected, root, execution, calls, decisions, reason=REASON_ABANDONED)
        self.session.commit()

    def _emit_approval_event(
        self,
        event_type,
        thread,
        execution,
        calls: list[dict],
        decisions: dict | None = None,
        *,
        surface: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Dispatch approval_requested / approval_granted / approval_rejected for a parked agent run —
        always on the root conversation, `calls` flattened (a specialist's carry `via`)."""
        from marvin.services.ai.parked_runs import approval_event_data, approval_message

        decided = getattr(event_type, "name", "") != "approval_requested"
        try:
            self.event_bus.dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=event_type,
                document_data=approval_event_data(
                    thread,
                    execution,
                    calls,
                    decisions,
                    workspace_name=self.group.name if self.group else None,
                    decided_by=self.user.id if (decided and reason != "expired" and self.user) else None,
                    surface=surface,
                    reason=reason,
                ),
                message=approval_message(event_type, self._agent_display_name(thread.agent_slug), calls, reason),
                user_id=self.user.id if self.user else None,
                entity_id=thread.id,
                entity_type="ai_thread",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch agent approval event: {e}", exc_info=True)

    def _agent_display_name(self, slug: str) -> str:
        """An agent's name for a message line; the system router goes by the workspace's assistant name."""
        try:
            from marvin.services.ai.agents import resolve_agent

            spec = resolve_agent(self.session, self.group_id, slug)
            if spec is None:
                return slug
            return self._persona()[0] if spec.is_system and spec.slug == ROUTER_SLUG else spec.name
        except Exception:  # noqa: BLE001 — a label, never worth failing an event over
            return slug

    def _discard_empty_thread(self, thread) -> None:
        """Drop a thread a router run opened before its loop failed, so no empty thread is left behind."""
        if thread is None or thread.messages:
            return
        self.session.delete(thread)
        self.session.commit()

    def _delegate_runner(self, *, parent_thread, parent_body: AIAgentRequest, parent_execution, on_event, depth: int = 0, chain: tuple = ()):
        """The child runner a router run hangs on its ToolContext: `run(slug, message, max_steps) -> dict`.

        Runs the specialist for real through `_run_agent_core` (its own matrix at `depth + 1`) on a child
        thread per (parent thread, specialist, user) — reused on later hand-offs, and what "Continue
        with X" opens. Never raises an error: the model sees an error dict and answers around it. The
        one exception is `ToolDeferred`: the specialist parked on its own "ask first" call (only when
        the parent has a thread to carry the ask up to), and the loop pends the hand-off (slice C2).
        """
        import json

        from marvin.services.ai.agent import STOPPED_AWAITING_APPROVAL, ToolDeferred
        from marvin.services.ai.agents import may_talk, resolve_agent
        from marvin.services.ai.threads import child_thread_for, pending_state

        role = self._user_role()
        parent_id = str(parent_thread.id) if parent_thread is not None else None
        child_depth = depth + 1

        def run(slug: str, message: str, max_steps: int | None = None) -> dict:
            spec = resolve_agent(self.session, self.group_id, slug)
            if spec is None:
                return {"error": f"unknown agent '{slug}' — call list_agents", "agent": slug}
            if spec.slug in chain:
                return {"error": f"'{spec.slug}' is already part of this hand-off — answer with what you have", "agent": spec.slug}
            ok, reason = may_talk(spec, role, "agent")
            if not ok:
                return {"error": reason, "agent": spec.slug}
            if not message:
                return {"error": "message is required", "agent": spec.slug}
            child = child_thread_for(self.session, parent_thread, spec.slug, self.user.id) if parent_thread is not None else None
            if child is not None and pending_state(child):
                # The same specialist twice in one turn while its first request waits on the user: running
                # it again would abandon that request.
                return {
                    "error": f"{spec.name} is already waiting for the user's approval on an earlier request — do not ask it again now",
                    "agent": spec.slug,
                }
            try:
                self._check_budget()
                provider = self._agent_provider()
                model = spec.model_override or self._default_model()
                if not model:
                    return {"error": "no model configured", "agent": spec.slug}
                child_body = AIAgentRequest(
                    message=message,
                    source="agent",
                    thread_id=str(child.id) if child is not None else (NEW_THREAD if parent_thread is not None else None),
                    max_steps=min(int(max_steps or DELEGATED_MAX_STEPS), DELEGATED_MAX_STEPS_CAP),
                    register=parent_body.tone_register,
                    entity_type=parent_body.entity_type,
                    entity_id=parent_body.entity_id,
                )
                meta = {"parent_execution_id": str(parent_execution.id)}
                if parent_id:
                    meta["parent_thread_id"] = parent_id
                child_on_event = self._via_listener(on_event, spec.slug)
                assistant_name, persona_prompt = self._persona()
                register = self._effective_register(parent_body.tone_register, spec)
                system = self._named_agent_instructions(spec, assistant_name) + self._register_clause(register, persona_prompt)
                if spec.kind == "model":
                    res = self._run_model_agent(spec, provider, model, system, child_body, parent_thread_id=parent_id, execution_meta=meta)
                else:
                    self._require_tool_capable(provider, model)
                    entity_id = self._resolve_entity_id(child_body.entity_type, child_body.entity_id)
                    # The specialist may park only when there is a conversation to carry its ask up to.
                    tools, child_ctx = self._bind_agent_tools(
                        provider, agent=spec, role=role, depth=child_depth, park_allowed=parent_thread is not None
                    )
                    child_ctx.tone_register = register
                    res = self._run_agent_core(
                        provider=provider,
                        model=model,
                        system=system,
                        body=child_body,
                        entity_id=entity_id,
                        tools=tools,
                        max_steps=child_body.max_steps,
                        operation_slug=f"agent:{spec.slug}",
                        agent_slug=spec.slug,
                        ctx=child_ctx,
                        on_event=child_on_event,
                        parent_thread_id=parent_id,
                        execution_meta=meta,
                        handoff_chain=chain,
                    )
            except HTTPException as e:
                return {"error": e.detail if isinstance(e.detail, str) else json.dumps(e.detail), "agent": spec.slug}
            if res.get("stoppedReason") == STOPPED_AWAITING_APPROVAL:
                raise ToolDeferred(self._handoff_record(spec, res))
            return self._handoff_output(spec, res)

        return run

    def _handoff_record(self, spec, res: dict) -> dict:
        """The `child` of a deferred hand-off call: the specialist, its parked thread and execution, and a
        snapshot of its own (possibly nested) pending calls — what the root's card flattens."""
        from marvin.db.models.groups.ai_threads import AIThreadModel
        from marvin.services.ai.threads import pending_state

        thread = self.session.get(AIThreadModel, self._uuid_or_none(res.get("threadId")))
        record = pending_state(thread) if thread is not None else None
        return {
            "agent": spec.slug,
            "name": spec.name,
            "thread_id": res.get("threadId"),
            "execution_id": res.get("executionId"),
            "calls": list((record or {}).get("calls") or []),
        }

    @staticmethod
    def _handoff_output(spec, res: dict) -> dict:
        """What `run_agent` returns to the router once the specialist answered."""
        return {
            "agent": spec.slug,
            "answer": res.get("answer"),
            "steps": [{"tool": s.get("tool"), "arguments": s.get("arguments")} for s in res.get("steps") or []],
            "referrals": res.get("referrals") or [],
            "threadId": res.get("threadId"),
            "executionId": res.get("executionId"),
            "totalTokens": res.get("totalTokens"),
        }

    @staticmethod
    def _via_listener(on_event, slug: str):
        """The parent's listener for a specialist's events, tagged `via` (innermost agent) and `viaChain`
        (outermost first). The specialist's own `awaiting_approval` is dropped: the parent announces the
        flattened asks itself."""
        if on_event is None:
            return None

        def listen(ev: dict) -> None:
            if ev.get("type") == "awaiting_approval":
                return
            on_event({**ev, "via": ev.get("via") or slug, "viaChain": [slug, *(ev.get("viaChain") or [])]})

        return listen

    def _run_model_agent(
        self, spec, provider, model: str, system: str, body: AIAgentRequest, parent_thread_id=None, execution_meta: dict | None = None
    ) -> dict:
        """A `model` agent: plain completion with the agent's prompt and the caller's history; no tools."""
        import time
        from datetime import UTC, datetime

        from marvin.core.config import get_app_settings
        from marvin.services.ai.base import CompletionOptions, Message
        from marvin.services.ai.pricing import estimate_cost
        from marvin.services.ai.threads import create_thread

        _app = get_app_settings()
        thread = self._thread_for_run(body, spec.slug)
        messages = [
            Message(role="system", content=system),
            *self._run_history(body, thread),
            Message(role="user", content=body.message),
        ]
        # Opened before the completion for the same reason as in _run_agent_core: the id is known mid-run.
        opened_here = False
        if thread is None and body.thread_id == NEW_THREAD:
            thread = create_thread(
                self.session, self.group_id, self.user.id, spec.slug, body.message, body.entity_type, parent_thread_id=parent_thread_id
            )
            opened_here = True
        log_inputs, log_outputs = self._logging_policy()
        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug=f"agent:{spec.slug}",
            provider_type=provider.provider_type,
            model_id=model,
            status="running",
            triggered_by=self.user.id,
            trigger_type=body.source,
            input_json={"message": body.message} if log_inputs else None,
            metadata_json=self._run_meta(execution_meta, thread),
        )
        execution.started_at = datetime.now(UTC)
        self.session.add(execution)
        self.session.commit()
        start = time.monotonic()
        run_id, _ = self._start_progress(body, thread, execution)
        try:
            opts = CompletionOptions(temperature=_app.AI_DEFAULT_TEMPERATURE, max_tokens=self._max_output_tokens())
            result = provider.complete(messages, model, opts)
        except Exception as e:
            self._finish_progress(run_id, "failed", f"Agent failed: {e}")
            self._fail_execution(execution, str(e), start)
            self._discard_empty_thread(thread if opened_here else None)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Agent failed: {e}") from e
        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.prompt_tokens = result.prompt_tokens
        execution.completion_tokens = result.completion_tokens
        execution.total_tokens = result.total_tokens
        execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, result.prompt_tokens, result.completion_tokens)
        execution.output_json = {"answer": result.content} if log_outputs else None
        thread = self._record_thread_turns(
            thread, body, spec.slug, execution, result.content, [], [], result.total_tokens, parent_thread_id=parent_thread_id
        )
        self.session.commit()
        self._finish_progress(run_id, "completed")
        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)
        return {
            "answer": result.content,
            "steps": [],
            "sources": [],
            "stoppedReason": "final",
            "executionId": str(execution.id),
            "threadId": str(thread.id) if thread is not None else None,
            "totalTokens": result.total_tokens,
            "estimatedCostUsd": execution.estimated_cost_usd,
        }

    @router.post("/chat", summary="Plain chat completion (no tools, no RAG)")
    def chat(self, body: AIAgentRequest) -> dict:
        """A straight conversational completion — NO tools, NO retrieval — so any model works,
        including text-only Ollama models (gemma, phi) that can't run the agent. Not grounded in
        workspace content (use `/ask` for that); this is just talking to the model.
        """
        import time
        from datetime import UTC, datetime

        from marvin.core.config import get_app_settings
        from marvin.services.ai.base import CompletionOptions, Message
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider
        from marvin.services.ai.operations.base import ROLE_VIEWER
        from marvin.services.ai.pricing import estimate_cost

        # VIEWER or higher — chat is read-only (it changes nothing).
        if self._user_role() < ROLE_VIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="VIEWER role or higher required.")

        body.source = self._check_invocation_source(body.source, ("editor", "api", "agent", "mcp"))
        self._check_budget()

        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except AIDisabledError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"AI provider error: {e}") from e

        model = body.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured.")

        from marvin.services.ai.agents import model_agent_system_prompt

        _app = get_app_settings()
        assistant_name, persona_prompt = self._persona()
        system = model_agent_system_prompt(assistant_name, gloomy=assistant_name == "Marvin", router_name=assistant_name)
        # Same tone resolution as the default agent: the caller's tone, else the workspace default.
        system += self._register_clause(body.tone_register or self._default_register(), persona_prompt)
        messages = [Message(role="system", content=system), Message(role="user", content=body.message)]

        log_inputs, log_outputs = self._logging_policy()
        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug="chat",
            provider_type=provider.provider_type,
            model_id=model,
            status="running",
            triggered_by=self.user.id,
            trigger_type=body.source,
            input_json={"message": body.message} if log_inputs else None,
        )
        execution.started_at = datetime.now(UTC)
        self.session.add(execution)
        self.session.commit()

        start = time.monotonic()
        try:
            opts = CompletionOptions(
                temperature=_app.AI_DEFAULT_TEMPERATURE,
                max_tokens=self._max_output_tokens(),
            )
            result = provider.complete(messages, model, opts)
        except Exception as e:
            self._fail_execution(execution, str(e), start)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Chat failed: {e}") from e

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.prompt_tokens = result.prompt_tokens
        execution.completion_tokens = result.completion_tokens
        execution.total_tokens = result.total_tokens
        execution.estimated_cost_usd = estimate_cost(
            provider.provider_type,
            model,
            result.prompt_tokens,
            result.completion_tokens,
        )
        execution.output_json = {"reply": result.content} if log_outputs else None
        self.session.commit()

        return {
            "reply": result.content,
            "model": model,
            "totalTokens": result.total_tokens,
            "estimatedCostUsd": execution.estimated_cost_usd,
            "executionId": str(execution.id),
        }

    @staticmethod
    def _handoff_max_depth() -> int:
        """AI_HANDOFF_MAX_DEPTH: how many hand-offs may nest (1 = Marvin → specialist, no further)."""
        from marvin.core.config import get_app_settings

        return max(0, int(getattr(get_app_settings(), "AI_HANDOFF_MAX_DEPTH", 1) or 0))

    def _require_tool_capable(self, provider, model: str) -> None:
        """Gate the agent to a tool-capable provider/model. Consumes AIModelModel.supports_tools
        when the model is registered (else trusts the provider-level capability)."""
        if not getattr(provider, "supports_tool_calls", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"The '{provider.provider_type}' provider does not support tool calling. The agent "
                    "needs a tool-capable provider (OpenAI, Azure, Anthropic, or Ollama)."
                ),
            )
        from marvin.db.models.groups.ai_providers import AIModelModel

        row = self.session.query(AIModelModel).filter(AIModelModel.group_id == self.group_id, AIModelModel.model_id == model).first()
        if row is not None and not row.supports_tools:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model}' is configured as not supporting tools. Choose a tool-capable model.",
            )

    def _build_agent_tools(self, provider, agent=None, role: int | None = None, *, park_allowed: bool = False) -> list:
        """The bound toolset alone (see `_bind_agent_tools`)."""
        return self._bind_agent_tools(provider, agent=agent, role=role, park_allowed=park_allowed)[0]

    def _bind_agent_tools(self, provider, agent=None, role: int | None = None, *, depth: int = 0, park_allowed: bool = False) -> tuple:
        """Bind the agent's in-process toolset: the core tool registry + the AI operations.

        Returns `(tools, ctx)` — the ToolContext is shared by every bound registry tool, so the run can
        hang its hand-off delegate on it and read the referrals back. `depth` > 0 is a delegated child
        run: it binds `run_agent` only while `depth` is below AI_HANDOFF_MAX_DEPTH (default 1: a
        specialist never hands off further and gets `suggest_agent` only). `park_allowed` is whether
        the run has a thread to pause on — a specialist's thread counts (its ask is carried up to the
        conversation that handed off, slice C2).

        Each registry ToolSpec reachable from the "agent" source and allowed for this user's role
        becomes an AgentTool whose run() calls the spec's handler with a ToolContext (direct DB
        handlers — reads + link writes + authoring via compose_entry/revise_entry). Then every AI
        *operation* allowed for the agent (generate-summary/tags, improve-writing, …) is bound too, so
        Chat has parity with MCP's marvin_op_* surface — an operation is an LLM generation (curated
        prompt + write-back), not a direct handler. Finally, allowlisted external MCP tools.
        """
        import json

        from marvin.services.ai.agent import AgentTool
        from marvin.services.ai.tools import ToolContext, bulk_writes, list_tools
        from marvin.services.ai.tools.categories import category_of

        ctx = ToolContext(
            session=self.session,
            group_id=self.group_id,
            user=self.user,
            provider=provider,
            logger=self.logger,
            depth=depth,
            source="agent",
        )
        role = self._user_role()
        can_park = park_allowed
        can_handoff = depth < self._handoff_max_depth()

        tools: list = []
        for spec in list_tools():
            if "agent" not in spec.sources or role < spec.min_role or (not can_handoff and spec.name == "run_agent"):
                continue
            # A big bulk write asks first even where the policy allows it outright — or, with no
            # thread to park on, is refused (tools/bulk_writes.py).
            run, approval_check = bulk_writes.bind(spec, ctx, can_park=can_park)
            tools.append(
                AgentTool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    run=run,
                    category=category_of(spec.name, read_only=spec.read_only),
                    approval_check=approval_check,
                )
            )

        # compose_entry / revise_entry now come from the registry (builtins_authoring, shared
        # AuthoringService) and are bound by the loop above — no hand-wiring here.

        # Bind AI operations (generate-summary/tags, improve-writing, describe-image, …) as agent
        # tools too, so Chat has parity with MCP's marvin_op_* surface. Each runs through the shared
        # execute path (curated prompt + output schema + write-back), gated by its own agent source +
        # min_role. Unlike a registry tool (a direct DB handler), an operation is an LLM generation.
        from marvin.schemas.group.ai_execution import AIOperationExecuteRequest
        from marvin.services.ai.operations import list_operations

        def _make_op_run(op_slug: str):
            def run(args: dict) -> str:
                try:
                    res = self.execute_operation(
                        op_slug,
                        AIOperationExecuteRequest(
                            entity_type=(args.get("entity_type") or "entry"),
                            entity_id=args.get("entity_id"),
                            input=args.get("input") or {},
                            source="agent",
                        ),
                    )
                except HTTPException as e:
                    return json.dumps({"error": e.detail})
                except Exception as e:  # noqa: BLE001 — surface to the model, never raise into the loop
                    return json.dumps({"error": str(e)})
                link_child_execution(self.session, res.id, ctx.execution_id)
                return json.dumps({"status": res.status, "output": res.output_json, "error": res.error_message})

            return run

        for op in list_operations():
            if "agent" not in op.invocation_sources or role < op.min_role:
                continue
            tools.append(
                AgentTool(
                    name=op.slug.replace("-", "_"),
                    description=f"AI operation — {op.description} (LLM generation with curated prompt + write-back; slug '{op.slug}').",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "entity_id": {
                                "type": "string",
                                "description": "id or slug of the entry/asset/resource to run on "
                                "(omit for ops that don't target one, e.g. answer-workspace-question)",
                            },
                            "entity_type": {"type": "string", "description": "entry | asset | resource (default entry)"},
                            "input": op.input_schema or {"type": "object", "properties": {}},
                        },
                    },
                    run=_make_op_run(op.slug),
                    category="ai_ops",
                )
            )

        # Growth plane: allowlisted tools from the workspace's enabled external MCP servers.
        tools.extend(self._external_mcp_tools())
        if agent is None:
            return tools, ctx
        return self._restrict_tools(tools, agent, role if role is not None else self._user_role(), park_allowed=can_park), ctx

    def _external_mcp_tools(self) -> list:
        """Load allowlisted tools from the workspace's ENABLED external MCP servers as AgentTools.

        Gated by the `external_mcp_enabled` master switch. Deny-by-default: only tools named in a
        server's `allowed_tools` are exposed, prefixed `mcp__<serverslug>__<tool>` to avoid
        collisions. A server that's unreachable or errors is skipped (logged), never fatal to the
        agent; a tool call that fails is surfaced to the model as a JSON error, not raised.
        """
        import json
        import re

        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not settings or not getattr(settings, "external_mcp_enabled", False):
            return []

        from marvin.core.config import get_app_settings
        from marvin.db.models.groups.mcp_servers import WorkspaceMcpServerModel
        from marvin.services.ai import mcp_client
        from marvin.services.ai.agent import AgentTool
        from marvin.services.ai.tools.categories import category_of

        app = get_app_settings()
        servers = self.session.query(WorkspaceMcpServerModel).filter_by(group_id=self.group_id, enabled=True).all()
        tools: list = []
        for server in servers:
            allow = set(server.allowed_tools or [])
            if not allow:
                continue  # deny-by-default: nothing allowlisted → expose nothing
            try:
                available = mcp_client.list_server_tools(server, timeout=10.0)
            except Exception as e:
                self.logger.warning("external MCP '%s' tools/list failed: %s", server.slug, e)
                continue
            prefix = re.sub(r"[^a-zA-Z0-9]+", "_", server.slug)
            for t in available:
                if t.name not in allow:
                    continue

                def _run(args, s=server, tn=t.name):
                    try:
                        text, _is_error = mcp_client.call_server_tool(s, tn, args or {}, timeout=app.MCP_TOOL_TIMEOUT_SECONDS)
                    except Exception as e:  # unreachable/timeout — non-fatal, surfaced to the model
                        self.logger.warning("external MCP '%s' tool %s failed: %s", s.slug, tn, e)
                        return json.dumps({"error": str(e)})
                    return mcp_client.clip_result(text, app.MCP_TOOL_RESULT_MAX_CHARS) if text else json.dumps({"error": "empty result"})

                tools.append(
                    AgentTool(
                        name=f"mcp__{prefix}__{t.name}"[:64],
                        description=f"[{server.name}] {t.description}".strip(),
                        input_schema=t.input_schema or {"type": "object", "properties": {}},
                        run=_run,
                        # the server's own hints place the tool: read-only → a read row, destructive → its own row
                        category=category_of(f"mcp__{prefix}__{t.name}", read_only=t.read_only, destructive=t.destructive),
                    )
                )
        return tools

    # ── Helpers ────────────────────────────────────────────────────────

    def _fail_execution(self, execution, error: str, start: float) -> None:
        """Mark an execution failed. Rolls back first so a poisoned transaction (e.g. an
        IntegrityError during create) can't block writing the failure record."""
        import time
        from datetime import UTC, datetime

        self.session.rollback()
        row = self.session.get(AIExecutionModel, execution.id) or execution
        row.status = "failed"
        row.completed_at = datetime.now(UTC)
        row.duration_ms = int((time.monotonic() - start) * 1000)
        row.error_message = (error or "")[:2000]
        self.session.commit()

    def _resolve_retrieved_sources(self, retrieved: list[dict]) -> list[dict]:
        """Map retrieved chunks (in citation order) to their entity + resolved title.

        Thin wrapper over the shared helper (also used by the search_content tool handler)."""
        from marvin.services.ai.entity_resolve import resolve_retrieved_sources

        return resolve_retrieved_sources(self.session, retrieved)

    def _reindex_targets(self, body: AIReindexRequest) -> list[tuple[str, object, str]]:
        # Derives targets from the indexable-type registry, so a newly registered type is covered
        # by workspace reindex and single-entity reindex with no change here.
        from marvin.services.ai.embeddings_registry import REGISTRY

        # Single-entity reindex only; a workspace reindex runs in the background (services/ai/reindex_jobs).
        targets: list[tuple[str, object, str]] = []
        if body.entity_type and body.entity_id:
            desc = REGISTRY.get(body.entity_type)
            if desc:
                obj = self.session.get(desc.model, body.entity_id)
                if obj and obj.group_id == self.group_id:
                    targets.append((desc.entity_type, obj.id, desc.text(obj)))
        return targets

    def _logging_policy(self) -> tuple[bool, bool]:
        """(log_inputs, log_outputs) from the workspace logging_config.

        Defaults preserve prior behavior: outputs are logged, inputs are not. A workspace can
        opt into input logging or out of output logging via ai_settings.logging_config.
        """
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        cfg = (settings.logging_config if settings else None) or {}
        return bool(cfg.get("log_inputs", False)), bool(cfg.get("log_outputs", True))

    def _approval_mode(self) -> str:
        """Workspace approval_mode: suggest-only | allow-draft-update | allow-automatic-update."""
        from marvin.services.ai.approval import workspace_approval_mode

        return workspace_approval_mode(self.session, self.group_id)

    def _persona(self) -> tuple[str, str]:
        """(assistant_name, persona_prompt) from the workspace AI settings.

        Unset, the assistant is Marvin with Marvin's built-in voice — the "default voice" the AI settings
        page promises (see marvin.services.ai.persona). A workspace persona replaces it.
        """
        from marvin.services.ai.persona import resolve_persona

        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        return resolve_persona(settings.assistant_name if settings else None, settings.persona_prompt if settings else None)

    # Tones. Persona and tone are DIFFERENT axes and must not share one knob:
    #   persona = the CHARACTER: who the assistant is and how it speaks (workspace-level, user-authored)
    #   tone    = how THIS call delivers its output (per-request, set by the caller); it wins on
    #             formality, length and mood where the two disagree
    # Asking for a review and getting it in character is the failure this separates. The only
    # reliable lever is to withhold the persona entirely — asking a model to compartmentalise
    # is advisory, and small models ignore it. The tones themselves (built-in + the workspace's
    # own) live in marvin.services.ai.tones; the wire name stays `register`.

    def _tones(self):
        from marvin.services.ai.tones import workspace_tones

        return workspace_tones(self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first())

    def _effective_register(self, requested: str | None, spec) -> str:
        """The tone a named agent runs with: an explicit caller choice, else the agent's own, else the workspace's.

        "auto" from the caller is not a choice — the Ask page always sends one — so it must not override an
        agent configured as professional (a specialist would otherwise inherit the workspace persona). A slug
        that names no tone (deleted since) is skipped with a warning.
        """
        explicit = requested if requested and requested.lower() != "auto" else None
        return self._tones().resolve(explicit, spec.default_register).slug

    def _require_known_tone(self, slug: str | None) -> None:
        """422 unless `slug` (an agent's default tone) names a tone this workspace has; None = workspace default."""
        if slug and self._tones().get(slug) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"No tone '{slug}' in this workspace.")

    def _default_register(self) -> str:
        """The workspace's default tone, or 'auto' when unset (or it names a tone that's gone)."""
        return self._tones().default.slug

    def _register_clause(self, register: str | None, persona_prompt: str) -> str:
        """The character/tone section of a system prompt for the requested tone (unknown → workspace default → auto).

        Returns "" when there's nothing to say (a built-in that only places the character, with no persona set).
        """
        from marvin.services.ai.tones import tone_clause

        return tone_clause(self._tones().resolve(register), persona_prompt)

    # Caps for replayed conversation history. The client sends what it has; the server decides
    # what's affordable. Keeps the newest turns — recency is what "do #2" depends on.
    _HISTORY_MAX_TURNS = 10
    _HISTORY_MAX_CHARS = 6000
    _HISTORY_TURN_CHARS = 2000

    def _bounded_history(self, turns) -> "list":
        """Newest-first trim of prior turns, returned oldest-first as provider Messages.

        Bounded three ways: per-turn length, total characters, and turn count. Anything not a
        user/assistant turn is dropped — history is a replay of the conversation, not a channel
        for injecting system instructions.
        """
        if not turns:
            return []

        # Imported locally, as elsewhere in this module — marvin.services.ai.base is not a
        # module-level import here, so a class-body annotation referencing it would NameError.
        from marvin.services.ai.base import Message

        out: list = []
        budget = self._HISTORY_MAX_CHARS
        for turn in reversed(turns[-self._HISTORY_MAX_TURNS :]):  # newest first while spending budget
            role = (getattr(turn, "role", "") or "").lower()
            if role not in ("user", "assistant"):
                continue
            content = (getattr(turn, "content", "") or "").strip()
            if not content:
                continue
            if len(content) > self._HISTORY_TURN_CHARS:
                content = content[: self._HISTORY_TURN_CHARS - 1].rstrip() + "…"
            if len(content) > budget:
                break  # older turns beyond the budget are dropped wholesale, not half-quoted
            budget -= len(content)
            out.append(Message(role=role, content=content))
        out.reverse()  # back to chronological order for the model
        return out

    # Caps for the agent's pre-assembled context block. Grounding should orient the model, not
    # dominate the context window (or the token budget) — the tools are there for the long tail.
    _CTX_TEXT_CHARS = 400
    _CTX_FIELD_CHARS = 1200
    _CTX_LIST_CAP = 8

    @staticmethod
    def _ctx_truncate(text: str, limit: int) -> str:
        text = " ".join(str(text).split())  # collapse whitespace so the block stays compact
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    def _agent_context_block(self, entity_type: str | None, entity_id) -> str | None:  # noqa: C901 — sequential entity-type dispatch; complexity is inherent, not accidental
        """Pre-assemble what the user is looking at, for the agent's system prompt.

        Without this the agent learns only the entity's UUID and must spend a tool call to
        discover anything about it — which weaker models often skip, answering from nothing.
        Bounded on purpose; the agent still has get_entry/get_asset/... for full detail.

        Returns None when there's nothing to assemble (unknown/absent entity), in which case
        the caller falls back to the plain one-line hint.
        """
        if not entity_type or not entity_id:
            return None

        from marvin.services.ai.context import ContextBuilder

        builder = ContextBuilder(self.session, self.group_id)
        if entity_type == "entry":
            builder.with_entry(entity_id).with_assets(entity_id).with_resources(entity_id)
        elif entity_type == "asset":
            builder.with_asset(entity_id)
        elif entity_type == "resource":
            builder.with_resource(entity_id)
        else:
            # collection / entry_type have no ContextBuilder loader yet; the agent's own
            # get_collection / get_entry_type tools cover them.
            return None

        try:
            ctx = builder.build()
        except Exception as e:  # never let grounding break the run — degrade to the hint
            self.logger.warning("agent context assembly failed: %s", e)
            return None

        lines: list[str] = []

        if entity_type == "entry":
            if not ctx.entry:
                return None  # not found, or not this workspace's entry
            entry = ctx.entry
            lines.append(f'The user is looking at the entry "{entry.get("title") or "Untitled"}" (id: {entity_id}).')
            for label, key in (("Type", "entry_type"), ("Status", "status")):
                if val := (entry.get(key) or "").strip():
                    lines.append(f"- {label}: {val}")
            for label, key in (("Summary", "summary"), ("Description", "description")):
                if val := (entry.get(key) or "").strip():
                    lines.append(f"- {label}: {self._ctx_truncate(val, self._CTX_TEXT_CHARS)}")
            content = (entry.get("content") or "").strip()
            if content and content not in ("{}", "None"):
                lines.append(f"- Fields: {self._ctx_truncate(content, self._CTX_FIELD_CHARS)}")

        elif entity_type == "asset":
            if not ctx.assets:
                return None
            a = ctx.assets[0]
            lines.append(f'The user is looking at the asset "{a.get("name") or "Untitled"}" (id: {entity_id}).')
            if a.get("mime_type"):
                lines.append(f"- Type: {a['mime_type']}")
            if a.get("width") and a.get("height"):
                lines.append(f"- Dimensions: {a['width']}×{a['height']}")

        elif entity_type == "resource":
            if not ctx.resources:
                return None
            r = ctx.resources[0]
            lines.append(f'The user is looking at the resource "{r.get("name") or "Untitled"}" (id: {entity_id}).')
            if r.get("type"):
                lines.append(f"- Type: {r['type']}")
            if desc := (r.get("description") or "").strip():
                lines.append(f"- Description: {self._ctx_truncate(desc, self._CTX_TEXT_CHARS)}")
            if r.get("url"):
                lines.append(f"- URL: {r['url']}")

        # Attachments only make sense as "what's on this entry"; for a primary asset/resource
        # the lists above already are the entity itself.
        if entity_type == "entry":
            if ctx.assets:
                shown = ctx.assets[: self._CTX_LIST_CAP]
                names = ", ".join(f"{a.get('name')} ({a.get('mime_type') or 'unknown'})" for a in shown)
                more = f" (+{len(ctx.assets) - len(shown)} more)" if len(ctx.assets) > len(shown) else ""
                lines.append(f"- Attached assets ({len(ctx.assets)}): {names}{more}")
            else:
                lines.append("- Attached assets: none")
            if ctx.resources:
                shown = ctx.resources[: self._CTX_LIST_CAP]
                names = ", ".join(f"{r.get('name')} ({r.get('type') or 'untyped'})" for r in shown)
                more = f" (+{len(ctx.resources) - len(shown)} more)" if len(ctx.resources) > len(shown) else ""
                lines.append(f"- Linked resources ({len(ctx.resources)}): {names}{more}")
            else:
                lines.append("- Linked resources: none")

        return "\n".join(lines)

    def _may_change(self, entity_type: str, obj) -> bool:
        """Whether the caller may edit this entry/asset/resource under the content roles (EDITOR+ any;
        an AUTHOR only their own unpublished entries)."""
        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_can_edit_entry, require_workspace_role

        try:
            if entity_type == "entry":
                require_can_edit_entry(self.user, self.group_id, obj)
            else:
                require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        except HTTPException:
            return False
        return True

    def _write_back(self, operation, entity_type, entity_id, output_json, execution_id) -> str | None:
        """Apply or stage an operation's output onto an entry/asset/resource, gated by approval_mode.

        Uses the operation's `writeback` field map. Returns "applied" | "staged" | "not_permitted"
        (the caller may not edit the entity) | None.
        Best-effort — never breaks the operation response.
        """
        if entity_type not in ("entry", "asset", "resource") or not entity_id or not isinstance(output_json, dict):
            return None
        writeback = getattr(operation, "writeback", None) or {}
        proposed = {target: output_json[out] for out, target in writeback.items() if out in output_json}
        if not proposed:
            return None

        from marvin.db.models.platform import Assets, Entries, Resources
        from marvin.repos.platform._suggestions import SuggestionWritebackMixin

        repo_map: dict[str, tuple[SuggestionWritebackMixin, type]] = {
            "entry": (self.repos.entries, Entries),
            "asset": (self.repos.assets, Assets),
            "resource": (self.repos.resources, Resources),
        }
        repo, model = repo_map[entity_type]
        obj = self.session.get(model, entity_id)
        if not obj or obj.group_id != self.group_id:
            return None
        if not self._may_change(entity_type, obj):
            # The output is still returned; it just isn't applied or staged onto something the caller
            # can't edit (an AUTHOR's operation on someone else's entry, or on any asset/resource).
            return "not_permitted"

        from marvin.services.ai.approval import may_apply

        should_apply = may_apply(self._approval_mode(), entity_type, getattr(obj, "status", None))

        try:
            if should_apply:
                repo.apply_fields(entity_id, proposed)
                if entity_type == "entry":
                    self._emit_entry_updated(obj)
                return "applied"
            repo.stage_suggestion(
                entity_id,
                {**proposed, "_meta": {"operation": operation.slug, "executionId": str(execution_id)}},
            )
            return "staged"
        except Exception as e:
            self.session.rollback()
            self.logger.warning(f"write-back failed for {entity_type} {entity_id}: {e}")
            return None

    def _emit_entry_updated(self, entry) -> None:
        """Dispatch entry_updated after an AI write-back so reactions fire (re-embed, smart collections)."""
        from marvin.services.event_bus_service.event_types import EventEntryData, EventOperation, EventTypes

        try:
            self.event_bus.dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=EventTypes.entry_updated,
                document_data=EventEntryData(
                    operation=EventOperation.update,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    entry_type=None,
                    workspace_id=self.group_id,
                    workspace_name=self.group.name if self.group else None,
                    author_id=self.user.id if self.user else None,
                ),
                message=f"Entry '{entry.title}' updated by AI write-back",
                user_id=self.user.id if self.user else None,
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch entry_updated (write-back): {e}")

    def _resolve_entity_id(self, entity_type: str | None, entity_id):
        """Accept a UUID or a slug for entity_id so MCP/CLI callers can work in slugs.

        Thin wrapper over the shared helper (also used by the get_entry tool handler)."""
        from marvin.services.ai.entity_resolve import resolve_entity_id

        return resolve_entity_id(self.session, self.group_id, entity_type, entity_id)

    def _user_role(self) -> int:
        """The calling user's numeric workspace role for this group (platform admins → OWNER)."""
        from marvin.services.ai.operations.base import ROLE_OWNER

        if self.user.admin:
            return ROLE_OWNER
        for m in self.user.workspace_memberships:
            if m.group_id == self.group_id:
                return WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
        return 0

    def _check_invocation_source(self, source: str, operation_sources) -> str:
        """Gate a call by its invocation surface; returns the source it runs under.

        Effective allow-list = the operation's declared sources ∩ the workspace's
        invocation_sources policy. `source` is set by the calling infrastructure (the admin
        editor sends "editor", the bubble "bubble", the Ask page "ask_page", MarvinMCP "mcp", …), so
        this is surface/feature gating — the per-user authorization wall is min_role. The
        workspace policy is an override map: a source is enabled unless explicitly set false,
        so an unset/None policy allows everything (back-compat). The Ask surfaces are agent chat:
        an operation declaring `agent` takes them, and past the gate they run as `agent`.
        """
        from marvin.services.ai.operations.base import INVOCATION_SOURCES, execution_source, source_allowed

        if source not in INVOCATION_SOURCES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown invocation source '{source}'. Valid: {', '.join(INVOCATION_SOURCES)}.",
            )
        runs_as = execution_source(source)
        if runs_as not in operation_sources:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This operation cannot be invoked from the '{source}' source.",
            )
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not source_allowed(settings.invocation_sources if settings else None, source):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This workspace has disabled AI from the '{source}' source.",
            )
        return runs_as

    def _max_output_tokens(self) -> int | None:
        """Per-request output-token cap: the workspace's `max_tokens_per_request`, else the app default."""
        from marvin.services.ai.budget import max_output_tokens

        return max_output_tokens(self.session, self.group_id)

    def _check_budget(self) -> None:
        from marvin.services.ai.budget import blocked_reason

        reason = blocked_reason(self.session, self.group_id)
        if reason:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    def _validate_model_capabilities(self, operation, model: str) -> None:
        """Reject the call up front if the operation needs a capability the model lacks (§7).

        ``ai_models`` rows are the capability source of truth. When no row exists for the
        model (platform credential mode or an ad-hoc override) we cannot assert incompatibility,
        so the call is allowed through. Extend with further capability flags (e.g. tools) as
        operations declare them.
        """
        if not getattr(operation, "requires_vision", False):
            return
        if not self._model_sees_images(model):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Operation '{operation.slug}' requires a vision-capable model; '{model}' does not support vision.",
            )

    def _model_sees_images(self, model: str) -> bool:
        """False only when the model's `ai_models` row says it has no vision; no row → assume it can."""
        from marvin.db.models.groups.ai_providers import AIModelModel

        row = self.session.query(AIModelModel).filter_by(group_id=self.group_id, model_id=model).first()
        return not (row and not row.supports_vision)

    def _default_model(self) -> str | None:
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if settings and settings.model:
            return settings.model
        # Workspace mode: default model from the default provider's models.
        from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel

        provider = self.session.query(AIProviderModel).filter_by(group_id=self.group_id, is_default=True, enabled=True).first()
        if provider:
            model = self.session.query(AIModelModel).filter_by(provider_id=provider.id, is_default=True, enabled=True).first()
            if model:
                return model.model_id
        # Platform mode: fall back to the admin-configured AppSettings model (e.g. OPENAI_MODEL),
        # so platform credentials work with env vars alone — no per-workspace model needed.
        if settings and settings.credential_mode == "platform":
            from marvin.core.config import get_app_settings

            app = get_app_settings()
            provider_type = settings.provider or getattr(app, "AI_DEFAULT_PROVIDER", "openai")
            return getattr(app, f"{provider_type.upper()}_MODEL", None)
        return None

    # ── Event emission ─────────────────────────────────────────────────

    def _emit_entry_created(self, entry, entry_type) -> None:
        """Dispatch entry_created for a composed entry.

        Compose creates entries via the repo directly (not the entries controller), so without
        this the entry would skip the lifecycle event and miss reactions like smart-collection
        routing (e.g. a composed draft landing in a "Drafts" smart collection). Best-effort.
        """
        from marvin.services.event_bus_service.event_types import EventEntryData, EventOperation, EventTypes

        try:
            self.event_bus.dispatch(
                integration_id="entry_management",
                group_id=self.group_id,
                event_type=EventTypes.entry_created,
                document_data=EventEntryData(
                    operation=EventOperation.create,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    entry_type=getattr(entry_type, "slug", None),
                    workspace_id=self.group_id,
                    workspace_name=self.group.name if self.group else None,
                    author_id=self.user.id if self.user else None,
                ),
                message=f"Entry '{entry.title}' composed",
                user_id=self.user.id if self.user else None,
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch entry_created for composed entry: {e}", exc_info=True)

    def _emit_ai_event(self, execution, status: str, error_message: str | None) -> None:
        """Dispatch ai_operation_executed / ai_operation_failed to the event bus."""
        from marvin.services.event_bus_service.event_types import EventAIOperationData, EventTypes

        try:
            self.event_bus.dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=EventTypes.ai_operation_executed if status == "completed" else EventTypes.ai_operation_failed,
                document_data=EventAIOperationData(
                    operation_slug=execution.operation_slug,
                    provider_type=execution.provider_type,
                    model_id=execution.model_id,
                    status=status,
                    execution_id=execution.id,
                    entity_type=execution.entity_type,
                    entity_id=execution.entity_id,
                    total_tokens=execution.total_tokens,
                    estimated_cost_usd=execution.estimated_cost_usd,
                    error_message=error_message,
                    workspace_id=self.group_id,
                    workspace_name=self.group.name if self.group else None,
                ),
                message=f"AI operation '{execution.operation_slug}' {status}",
                user_id=self.user.id if self.user else None,
                # About what it acted on; an operation with no target (a chat answer) is about its run.
                entity_id=execution.entity_id or execution.id,
                entity_type=execution.entity_type if execution.entity_id else "ai_execution",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch ai operation event: {e}", exc_info=True)

    def _emit_reindex_event(self, model: str, entities: int, chunks: int) -> None:
        """Dispatch ai_embeddings_reindexed to the event bus."""
        from marvin.services.event_bus_service.event_types import EventAIEmbeddingsData, EventTypes

        try:
            self.event_bus.dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=EventTypes.ai_embeddings_reindexed,
                document_data=EventAIEmbeddingsData(
                    model_id=model,
                    entities_indexed=entities,
                    chunks_indexed=chunks,
                    workspace_id=self.group_id,
                    workspace_name=self.group.name if self.group else None,
                ),
                message=f"Reindexed {entities} entities ({chunks} chunks)",
                user_id=self.user.id if self.user else None,
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch ai_embeddings_reindexed event: {e}", exc_info=True)

    def _emit_budget_thresholds(self, execution) -> None:
        """Emit budget threshold/exceeded events on the call that crosses the line (once)."""
        from marvin.services.ai.budget import crossing_after
        from marvin.services.event_bus_service.event_types import EventTypes

        crossing = crossing_after(self.session, self.group_id, execution.estimated_cost_usd)
        if crossing:
            event = EventTypes.ai_budget_exceeded if crossing.exceeded else EventTypes.ai_budget_threshold_reached
            self._emit_budget_event(event, "monthly_cost", crossing.spent, crossing.limit, crossing.percent, crossing.detail)

    def _maybe_emit_quota(self, execution, error: str) -> None:
        """Emit ai_provider_quota_exceeded when a provider rejects the call for lack of quota/credits."""
        low = error.lower()
        if "insufficient_quota" in low or "quota" in low or "insufficient" in low or "429" in low:
            from marvin.services.event_bus_service.event_types import EventTypes

            self._emit_budget_event(
                EventTypes.ai_provider_quota_exceeded,
                "provider_quota",
                None,
                None,
                None,
                error[:300],
                provider_type=execution.provider_type,
                operation_slug=execution.operation_slug,
            )

    def _emit_budget_event(
        self, event_type, reason: str, current, limit, percent, detail: str, provider_type: str | None = None, operation_slug: str | None = None
    ) -> None:
        from marvin.services.event_bus_service.event_types import EventAIBudgetData

        try:
            self.event_bus.dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=event_type,
                document_data=EventAIBudgetData(
                    reason=reason,
                    current_value=current,
                    limit_value=limit,
                    percent=percent,
                    provider_type=provider_type,
                    operation_slug=operation_slug,
                    detail=detail,
                    workspace_id=self.group_id,
                    workspace_name=self.group.name if self.group else None,
                ),
                message=detail or f"AI {reason} event",
                user_id=self.user.id if self.user else None,
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch AI budget event: {e}", exc_info=True)
