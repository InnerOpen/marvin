"""Routes for AI operations — list, execute, and execution history."""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_execution import (
    AIAgentRequest,
    AIComposeEntryRequest,
    AIExecutionRead,
    AIOperationExecuteRequest,
    AIReindexRequest,
    AIReviseEntryRequest,
    AIToolInvokeRequest,
)

router = APIRouter(prefix="/ai", route_class=MarvinCrudRoute)


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
        """
        catalog: list[dict] = []
        for t in self._build_agent_tools(provider=None):
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
        self._check_invocation_source(body.source, operation.invocation_sources)

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
        # Vision operations need the raw image bytes loaded into context.
        if operation.requires_vision:
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
                temperature=getattr(_app, "AI_DEFAULT_TEMPERATURE", 0.7),
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
        return [AIExecutionRead.model_validate(r) for r in rows]

    @router.get("/executions/{execution_id}", response_model=AIExecutionRead, summary="Get Execution")
    def get_execution(self, execution_id: UUID4) -> AIExecutionRead:
        row = self.session.get(AIExecutionModel, execution_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
        return AIExecutionRead.model_validate(row)

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

        entities = chunks = 0
        for entity_type, entity_id, text in self._reindex_targets(body):
            try:
                chunks += index_entity(self.session, self.group_id, entity_type, entity_id, text, provider, model)
                entities += 1
            except Exception as e:
                self.logger.warning("reindex failed for %s %s: %s", entity_type, entity_id, e)
        self._emit_reindex_event(model, entities, chunks)
        return {"model": model, "entities_indexed": entities, "chunks_indexed": chunks}

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
        self._check_invocation_source(body.source, ("editor", "mcp", "agent", "api"))

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
                register=body.tone_register or self._default_register(),
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
        self._check_invocation_source(body.source, ("editor", "mcp", "agent", "api"))

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
                register=self._default_register(),
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
            "editUrl": f"/workspace/entries/{entry.id}",
            "executionId": None,
            "totalTokens": None,
            "estimatedCostUsd": None,
            "generated": entry.data_json,
            "aiSkipped": True,
        }

    # ── Agent (tool-calling loop) ──────────────────────────────────────

    @router.post("/agent", summary="Run the Marvin agent (tool-calling loop)")
    def run_agent(self, body: AIAgentRequest) -> dict:
        """Run the server-side agent: an iterative tool-calling loop over Marvin's capabilities.

        v1 tools are Marvin's own read/authoring surfaces — search, browse, list types, and compose
        a draft. The model decides which to call; the loop runs them and feeds results back until it
        answers. Requires a tool-capable provider (OpenAI/Azure/Anthropic/Ollama). Composing still
        creates an `inbox` draft for human review; the agent never publishes.
        """
        import time
        from datetime import UTC, datetime

        from marvin.core.config import get_app_settings
        from marvin.services.ai.agent import DEFAULT_MAX_STEPS, run_agent_loop
        from marvin.services.ai.base import CompletionOptions, Message
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider
        from marvin.services.ai.operations.base import ROLE_AUTHOR
        from marvin.services.ai.pricing import estimate_cost

        # AUTHOR or higher — the agent can create/modify content.
        if not self.user.admin:
            role = 0
            for m in self.user.workspace_memberships:
                if m.group_id == self.group_id:
                    role = WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
                    break
            if role < ROLE_AUTHOR:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AUTHOR role or higher required.")

        self._check_invocation_source(body.source, ("agent", "editor", "api", "mcp"))
        self._check_budget()

        try:
            provider = get_workspace_ai_provider(self.session, self.group_id)
        except AIDisabledError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"AI provider error: {e}") from e

        model = body.model_override or self._default_model()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No model configured. Set a default model on the provider.")
        self._require_tool_capable(provider, model)

        entity_id = self._resolve_entity_id(body.entity_type, body.entity_id)
        tools = self._build_agent_tools(provider)

        _app = get_app_settings()
        configured_max_steps = int(body.max_steps or getattr(_app, "AI_AGENT_MAX_STEPS", DEFAULT_MAX_STEPS) or DEFAULT_MAX_STEPS)
        max_steps = min(configured_max_steps, 12)

        assistant_name, persona_prompt = self._persona()
        system = (
            f"You are {assistant_name}, the assistant for this headless CMS workspace. Use the provided tools to "
            "search, browse, and (only when asked) author content. Prefer tools over guessing and ground "
            "your answer in what they return. To answer what EXISTS in the workspace — the tag vocabulary, "
            "resources, entry types, or collections — call the matching list tool (list_tags, list_resources, "
            "list_entry_types, list_collections). Reserve search_content for finding content by MEANING; it is "
            "semantic, so it surfaces items that merely mention a word and must not be used to enumerate a "
            "vocabulary (asking it 'what tags exist' returns content, not tags). Before proposing or attaching "
            "tags, resources, or assets, first discover what already exists — call list_tags (then search_content "
            "for related content) — and REUSE matches; only create something new when nothing fits. To author, "
            "use compose_entry for a NEW entry and revise_entry to "
            "change an EXISTING one (never recreate). Authoring creates a DRAFT for human review — never claim "
            "anything is published. When a request could reasonably map to two different tools or readings — "
            "e.g. enumerate a vocabulary vs. find content by meaning — answer the most likely one, then add ONE "
            "short line offering the alternative (what you would do differently and how to ask for it). Do this "
            "only when the reading is genuinely forked; never append a 'did you mean…' to an unambiguous request. "
            "Be concise."
        )
        # Explicit per-call register wins; otherwise the workspace default; otherwise "auto".
        system += self._register_clause(body.tone_register or self._default_register(), persona_prompt)
        # Ground the run in what the user is looking at. Prefer a pre-assembled context block
        # (title/status/fields/attachments) so the agent can answer immediately; fall back to the
        # bare id hint when we can't assemble one, so it can still fetch the entity itself.
        context_block = self._agent_context_block(body.entity_type, entity_id)
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
            *self._bounded_history(body.history),
            Message(role="user", content=user_msg),
        ]

        log_inputs, log_outputs = self._logging_policy()
        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug="agent",
            provider_type=provider.provider_type,
            model_id=model,
            status="running",
            triggered_by=self.user.id,
            trigger_type=body.source,
            entity_type=body.entity_type,
            entity_id=entity_id,
            input_json={"message": body.message} if log_inputs else None,
        )
        execution.started_at = datetime.now(UTC)
        self.session.add(execution)
        self.session.commit()

        start = time.monotonic()
        try:
            opts = CompletionOptions(
                temperature=getattr(_app, "AI_DEFAULT_TEMPERATURE", 0.7),
                max_tokens=self._max_output_tokens(),
            )
            result = run_agent_loop(provider, model, messages, tools, opts, max_steps=max_steps)
        except HTTPException:
            raise
        except Exception as e:
            self._fail_execution(execution, str(e), start)
            self._emit_ai_event(execution, "failed", str(e))
            self._maybe_emit_quota(execution, str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Agent failed: {e}") from e

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
        execution.output_json = (
            {"answer": result.answer, "steps": [{"tool": s.tool, "arguments": s.arguments} for s in result.steps]}
            if log_outputs
            else {"steps": len(result.steps)}
        )
        self.session.commit()
        self.session.refresh(execution)
        self._emit_ai_event(execution, "completed", None)
        self._emit_budget_thresholds(execution)

        return {
            "answer": result.answer,
            "steps": [{"tool": s.tool, "arguments": s.arguments, "result": s.result} for s in result.steps],
            "stoppedReason": result.stopped_reason,
            "executionId": str(execution.id),
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

        self._check_invocation_source(body.source, ("editor", "api", "agent", "mcp"))
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

        _app = get_app_settings()
        assistant_name, persona_prompt = self._persona()
        gloomy = " (if faintly gloomy)" if assistant_name == "Marvin" else ""
        system = (
            f"You are {assistant_name}, a helpful{gloomy} assistant for this headless-CMS workspace. "
            "Answer conversationally and concisely. You have no tools and no access to the workspace's "
            "content here — if the user needs answers grounded in their entries, tell them to use /ask."
        )
        if persona_prompt:
            system += f"\n\nVoice and tone: {persona_prompt}"
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
                temperature=getattr(_app, "AI_DEFAULT_TEMPERATURE", 0.7),
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

    def _build_agent_tools(self, provider) -> list:
        """Bind the agent's in-process toolset: the core tool registry + the AI operations.

        Each registry ToolSpec reachable from the "agent" source and allowed for this user's role
        becomes an AgentTool whose run() calls the spec's handler with a ToolContext (direct DB
        handlers — reads + link writes + authoring via compose_entry/revise_entry). Then every AI
        *operation* allowed for the agent (generate-summary/tags, improve-writing, …) is bound too, so
        Chat has parity with MCP's marvin_op_* surface — an operation is an LLM generation (curated
        prompt + write-back), not a direct handler. Finally, allowlisted external MCP tools.
        """
        import json
        from collections.abc import Callable

        from marvin.services.ai.agent import AgentTool
        from marvin.services.ai.tools import ToolContext, ToolSpec, list_tools

        ctx = ToolContext(
            session=self.session,
            group_id=self.group_id,
            user=self.user,
            provider=provider,
            logger=self.logger,
        )
        role = self._user_role()

        def _bind(s: ToolSpec) -> Callable[[dict], str]:
            return lambda args: s.handler(ctx, args)

        tools: list = [
            AgentTool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                run=_bind(spec),
            )
            for spec in list_tools()
            if "agent" in spec.sources and role >= spec.min_role
        ]

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
                )
            )

        # Growth plane: allowlisted tools from the workspace's enabled external MCP servers.
        tools.extend(self._external_mcp_tools())
        return tools

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

        from marvin.db.models.groups.mcp_servers import WorkspaceMcpServerModel
        from marvin.services.ai import mcp_client
        from marvin.services.ai.agent import AgentTool

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
                        text, _is_error = mcp_client.call_server_tool(s, tn, args or {}, timeout=20.0)
                        return text or json.dumps({"error": "empty result"})
                    except Exception as e:  # unreachable/timeout — non-fatal, surfaced to the model
                        return json.dumps({"error": str(e)})

                tools.append(
                    AgentTool(
                        name=f"mcp__{prefix}__{t.name}"[:64],
                        description=f"[{server.name}] {t.description}".strip(),
                        input_schema=t.input_schema or {"type": "object", "properties": {}},
                        run=_run,
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

        targets: list[tuple[str, object, str]] = []
        if body.scope == "workspace":
            for reg_desc in REGISTRY.values():
                for obj in self.session.query(reg_desc.model).filter_by(group_id=self.group_id).all():
                    targets.append((reg_desc.entity_type, obj.id, reg_desc.text(obj)))
        elif body.entity_type and body.entity_id:
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
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        return settings.approval_mode if settings and settings.approval_mode else "suggest-only"

    def _persona(self) -> tuple[str, str]:
        """(assistant_name, persona_prompt) from the workspace AI settings.

        Defaults preserve prior behavior: the assistant is named "Marvin" and no extra
        voice/tone instruction is appended when unset.
        """
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        name = (settings.assistant_name if settings and settings.assistant_name else None) or "Marvin"
        persona = (settings.persona_prompt if settings and settings.persona_prompt else "") or ""
        return name, persona

    # Tone registers. Persona and register are DIFFERENT axes and must not share one knob:
    #   persona  = how the assistant ADDRESSES you (workspace-level, user-authored)
    #   register = how THIS call's output should read (per-request, set by the caller)
    # Asking for a review and getting it in character is the failure this separates. The only
    # reliable lever is to withhold the persona entirely — asking a model to compartmentalise
    # is advisory, and small models ignore it.
    REGISTERS = ("auto", "professional", "playful")

    def _default_register(self) -> str:
        """The workspace's default tone register, or 'auto' when unset."""
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        return settings.default_register if settings and settings.default_register else "auto"

    def _register_clause(self, register: str | None, persona_prompt: str) -> str:
        """The voice/tone section of a system prompt for the requested register.

        Returns "" when there's nothing to say (no persona, or persona deliberately withheld).
        """
        reg = (register or "auto").lower()
        if reg not in self.REGISTERS:
            reg = "auto"

        if reg == "professional":
            # Withhold the persona outright — this is the mechanism, not a request to behave.
            return (
                "\n\nWrite plainly, specifically and professionally. Do not adopt a persona, "
                "voice, or character; skip pleasantries and lead with the substance. Be concrete: "
                "name the field, section, or line you mean, and say what to change and why."
            )

        if not persona_prompt:
            return ""

        if reg == "playful":
            return f"\n\nVoice and tone: {persona_prompt}"

        # auto — persona for framing, plain for the artifact.
        return (
            f"\n\nVoice and tone: {persona_prompt}"
            "\nThat voice applies ONLY to how you address the user — greetings, framing, brief "
            "asides. Work product itself — reviews, critiques, findings, summaries, suggested "
            "copy — must be written plainly, specifically, and professionally. Never let the "
            "persona soften, exaggerate, or obscure a finding, and never write generated "
            "content in that voice unless the user explicitly asks for it."
        )

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

    def _write_back(self, operation, entity_type, entity_id, output_json, execution_id) -> str | None:
        """Apply or stage an operation's output onto an entry/asset/resource, gated by approval_mode.

        Uses the operation's `writeback` field map. Returns "applied" | "staged" | None.
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

        mode = self._approval_mode()
        # Assets/resources have no published lifecycle to protect, so treat them as always-draft.
        is_draft = entity_type != "entry" or obj.status not in ("published", "archived")
        should_apply = mode == "allow-automatic-update" or (mode == "allow-draft-update" and is_draft)

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

    def _check_invocation_source(self, source: str, operation_sources) -> None:
        """Gate a call by its invocation surface.

        Effective allow-list = the operation's declared sources ∩ the workspace's
        invocation_sources policy. `source` is set by the calling infrastructure (the admin
        editor sends "editor", MarvinMCP sends "mcp", the agent endpoint sends "agent", …), so
        this is surface/feature gating — the per-user authorization wall is min_role. The
        workspace policy is an override map: a source is enabled unless explicitly set false,
        so an unset/None policy allows everything (back-compat).
        """
        from marvin.services.ai.operations.base import INVOCATION_SOURCES

        if source not in INVOCATION_SOURCES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown invocation source '{source}'. Valid: {', '.join(INVOCATION_SOURCES)}.",
            )
        if source not in operation_sources:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This operation cannot be invoked from the '{source}' source.",
            )
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        policy = settings.invocation_sources if settings else None
        if isinstance(policy, dict) and policy.get(source, True) is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This workspace has disabled AI from the '{source}' source.",
            )

    def _max_output_tokens(self) -> int | None:
        """Per-request output-token cap for this workspace.

        Honours `budget_config.max_tokens_per_request` (a workspace override that was stored but
        never read — every call used the global AI_DEFAULT_MAX_TOKENS regardless). Falls back to
        the app default when the workspace hasn't set one. A non-positive/invalid value is ignored
        rather than clamping every response to zero.
        """
        from marvin.core.config import get_app_settings

        default = getattr(get_app_settings(), "AI_DEFAULT_MAX_TOKENS", None)
        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        raw = (settings.budget_config or {}).get("max_tokens_per_request") if settings else None
        if raw is None:
            return default
        try:
            cap = int(raw)
        except (TypeError, ValueError):
            return default
        return cap if cap > 0 else default

    def _check_budget(self) -> None:
        from sqlalchemy import func

        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not settings or not settings.budget_config:
            return
        budget = settings.budget_config

        max_per_day = budget.get("max_requests_per_day")
        if max_per_day:
            today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            count = (
                self.session.query(func.count(AIExecutionModel.id))
                .filter(
                    AIExecutionModel.group_id == self.group_id,
                    AIExecutionModel.created_at >= today_start,
                )
                .scalar()
                or 0
            )
            if count >= max_per_day:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Daily request limit ({max_per_day}) reached.")

        max_cost = budget.get("max_cost_per_month_usd")
        if max_cost:
            month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            spent = (
                self.session.query(func.sum(AIExecutionModel.estimated_cost_usd))
                .filter(
                    AIExecutionModel.group_id == self.group_id,
                    AIExecutionModel.created_at >= month_start,
                    AIExecutionModel.status == "completed",
                )
                .scalar()
                or 0.0
            )
            if spent >= max_cost:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Monthly cost limit (${max_cost:.2f}) reached.")

    def _validate_model_capabilities(self, operation, model: str) -> None:
        """Reject the call up front if the operation needs a capability the model lacks (§7).

        ``ai_models`` rows are the capability source of truth. When no row exists for the
        model (platform credential mode or an ad-hoc override) we cannot assert incompatibility,
        so the call is allowed through. Extend with further capability flags (e.g. tools) as
        operations declare them.
        """
        if not getattr(operation, "requires_vision", False):
            return
        from marvin.db.models.groups.ai_providers import AIModelModel

        row = self.session.query(AIModelModel).filter_by(group_id=self.group_id, model_id=model).first()
        if row and not row.supports_vision:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Operation '{operation.slug}' requires a vision-capable model; '{model}' does not support vision.",
            )

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
                entity_id=execution.entity_id,
                entity_type=execution.entity_type,
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
        from sqlalchemy import func

        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        budget = (settings.budget_config if settings else None) or {}
        max_cost = budget.get("max_cost_per_month_usd")
        if not max_cost:
            return
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = (
            self.session.query(func.sum(AIExecutionModel.estimated_cost_usd))
            .filter(
                AIExecutionModel.group_id == self.group_id,
                AIExecutionModel.created_at >= month_start,
                AIExecutionModel.status == "completed",
            )
            .scalar()
            or 0.0
        )
        prev = spent - (execution.estimated_cost_usd or 0.0)
        from marvin.core.config import get_app_settings
        from marvin.services.event_bus_service.event_types import EventTypes

        warn_frac = getattr(get_app_settings(), "AI_BUDGET_WARNING_PERCENT", 80.0) / 100.0
        if prev < max_cost <= spent:
            self._emit_budget_event(
                EventTypes.ai_budget_exceeded,
                "monthly_cost",
                spent,
                max_cost,
                100.0,
                f"Monthly AI cost limit of ${max_cost:.2f} reached (spent ${spent:.2f})",
            )
        elif warn_frac > 0 and prev < warn_frac * max_cost <= spent:
            self._emit_budget_event(
                EventTypes.ai_budget_threshold_reached,
                "monthly_cost",
                spent,
                max_cost,
                round(spent / max_cost * 100, 1),
                f"AI spend reached {round(spent / max_cost * 100)}% of the ${max_cost:.2f} monthly limit",
            )

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
