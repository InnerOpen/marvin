"""Shared AI authoring service — the one "brain" behind composing and revising entries.

Both entry points call this:
  - the ``POST /ai/compose-entry`` (and, later, ``/ai/revise-entry``) endpoints, and
  - the agent's ``compose_entry`` / ``revise_entry`` tools.

So "create such-and-such entry" from chat and the Compose button do the *same* thing, grounded the
same way. The service owns the authoring flow — grounding, the structured LLM call, the entry
write, the execution record, cost, and lifecycle events — decoupled from FastAPI (plain deps:
session, group_id, user, provider, model). The calling surface still owns request concerns
(role/source/budget gating, response shaping).

Stage 1 moves the compose flow here behavior-preservingly; grounding + revise layer on next.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from marvin.core.root_logger import get_logger
from marvin.services.ui_links import entry_edit_url, entry_review_link


def default_authoring_model(session, group_id, provider=None) -> str | None:
    """The workspace's default model id (settings → default provider/model → platform app default).

    Shared by the agent's authoring tools so they use the same model the compose endpoint would.
    """
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    if settings and settings.model:
        return settings.model
    from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel

    prov = session.query(AIProviderModel).filter_by(group_id=group_id, is_default=True, enabled=True).first()
    if prov:
        model = session.query(AIModelModel).filter_by(provider_id=prov.id, is_default=True, enabled=True).first()
        if model:
            return model.model_id
    if settings and settings.credential_mode == "platform":
        from marvin.core.config import get_app_settings

        app = get_app_settings()
        provider_type = settings.provider or getattr(app, "AI_DEFAULT_PROVIDER", "openai")
        return getattr(app, f"{provider_type.upper()}_MODEL", None)
    return None


class AuthoringService:
    """Composes and revises entries. Construct with the request's session/user/provider/model."""

    def __init__(self, session, group_id, user, provider, model, event_bus=None, logger=None):
        from marvin.repos.all_repositories import get_repositories

        self.session = session
        self.group_id = group_id
        self.user = user
        self.provider = provider
        self.model = model
        self.repos = get_repositories(session, group_id=group_id)
        self._event_bus = event_bus
        self.logger = logger or get_logger(__name__)
        # The execution record for the most recent call — the caller reads it to emit the
        # ai_operation lifecycle + budget-threshold events it owns (success and failure paths).
        self.last_execution = None

    # ── Public API ─────────────────────────────────────────────────────────

    def compose(
        self,
        *,
        entry_type,
        brief: str,
        asset_ids: list | None = None,
        asset_attachments: list | None = None,
        source: str = "api",
        assistant_name: str = "Marvin",
        persona_prompt: str = "",
        register: str = "auto",
        log_inputs: bool = False,
        log_outputs: bool = True,
        max_tokens: int | None = None,
        ground: bool = True,
    ) -> dict:
        """Compose a DRAFT entry of ``entry_type`` from a brief (+ optional images).

        The entry type's field schema IS the LLM output schema, so the model returns exactly the
        fields a valid entry needs. Lands as status='inbox' for review. Requires a provider — the
        no-AI skeleton fallback stays with the caller.
        """
        from marvin.db.models.groups.ai_executions import AIExecutionModel
        from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
        from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
        from marvin.services.ai.base import CompletionOptions, ImagePart, Message
        from marvin.services.ai.compose import entry_type_to_output_schema
        from marvin.services.ai.context import ContextBuilder, resolve_prompt_messages

        asset_ids = asset_ids or []
        schema_def = EntryTypeSchemaDefinition.model_validate(entry_type.schema_json or {})
        recipe = EntryTypeRecipe.model_validate(entry_type.recipe_json or {})
        output_schema = entry_type_to_output_schema(schema_def, entry_type.name)
        # Let the model return tags + resources so it can REUSE the existing vocabulary/catalog
        # (both grounded below). Resources are linked reuse-only after create (like revise).
        if isinstance(output_schema, dict) and isinstance(output_schema.get("properties"), dict):
            output_schema["properties"]["tags"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relevant tags. Reuse the existing tag names listed in the prompt where they fit; only add a new tag when none match.",
            }
            output_schema["properties"]["resources"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Existing resources (materials, suppliers, techniques, …) this entry uses — by name or slug, "
                "from the list in the prompt. Reuse only; do not invent.",
            }
            output_schema["properties"]["assets"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Existing images/assets from this workspace that belong on this entry — by name or slug, "
                "from the list in the prompt. Reuse only; do not invent. The first is treated as the hero.",
            }

        # Context + vision images.
        builder = ContextBuilder(self.session, self.group_id).with_site_settings().with_variables()
        for aid in asset_ids:
            builder.with_asset(aid)
        if asset_ids:
            builder.with_asset_images()
        ctx = builder.build()

        grounding = self._grounding_block(brief) if ground else ""
        instruction = (
            f"Compose a new '{entry_type.name}' for {ctx.workspace_name or 'this workspace'} from the brief below. "
            f"Fill every field you reasonably can"
            + (", using the attached image(s) as the subject — the first is the hero/primary image." if asset_ids else ".")
            + self._recipe_instructions_block(recipe)
            + f"\n\nBrief:\n{brief}"
            + grounding
            + self._recipe_resource_hint(recipe)
            + self._recipe_asset_hint(recipe)
        )
        parts: list = [instruction]
        for a in ctx.assets or []:
            img = a.get("image_data")
            if img:
                parts.append(ImagePart(data=img, mime_type=a.get("mime_type") or "image/png"))

        voice = recipe.enrichment.get("voice") if isinstance(recipe.enrichment, dict) else None
        system_content = f"You are a content author. Produce a complete, publish-ready '{entry_type.name}'. Return ONLY the requested fields."
        if voice:
            system_content += f" Voice/tone: {voice}"
        messages = [
            Message(role="system", content=system_content),
            Message(role="user", content=parts if len(parts) > 1 else instruction),
        ]
        messages = resolve_prompt_messages(messages, self.group_id, ctx.variables)

        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug="compose-entry",
            provider_type=self.provider.provider_type,
            model_id=self.model,
            status="pending",
            triggered_by=getattr(self.user, "id", None),
            trigger_type=source,
            entity_type="entry_type",
            entity_id=entry_type.id,
            input_json={"entry_type": entry_type.slug, "brief": brief} if log_inputs else None,
        )
        self.session.add(execution)
        self.session.commit()
        self.last_execution = execution

        start = time.monotonic()
        try:
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            self.session.commit()

            opts = CompletionOptions(temperature=self._temperature(), max_tokens=max_tokens)
            parsed, completion = self.provider.execute_operation(messages, self.model, output_schema, opts)

            fields = dict(parsed or {})
            title = fields.pop("title", None) or f"Untitled {entry_type.name}"
            summary = fields.pop("summary", None)
            proposed_tags = fields.pop("tags", None)
            proposed_resources = fields.pop("resources", None)
            proposed_assets = fields.pop("assets", None)
            allowed = schema_def.get_field_keys()
            # Drop empty-string / null values the model emits for fields it couldn't fill — an empty
            # string fails typed validation (e.g. a date field: "" is not ISO-8601), and "not provided"
            # should be omitted, not a broken value. This lets types with optional date/number fields
            # compose cleanly.
            data_json = {k: v for k, v in fields.items() if k in allowed and v not in ("", None)}

            # Auto-attach existing assets the model surfaced from the grounded catalog (reuse-only),
            # combined with any caller-supplied asset_ids — the caller's keep priority for the hero
            # role (they lead the list). Recipe roles are assigned first→hero, then declared order.
            extra_assets = self._resolve_asset_refs(proposed_assets, exclude_ids=asset_ids)
            # Respect the recipe's overall image ceiling for AUTO-suggested assets (caller-supplied
            # ones are an explicit choice and aren't trimmed). No cap → attach what the model chose.
            recipe_max = getattr(recipe.assets, "max", None) if getattr(recipe, "assets", None) else None
            if recipe_max is not None:
                extra_assets = extra_assets[: max(0, recipe_max - len(asset_ids))]
            auto_asset_slugs = [slug for _, slug in extra_assets]
            final_attachments: list[dict] | None
            if extra_assets:
                combined_ids = list(asset_ids) + [aid for aid, _ in extra_assets]
                final_attachments = self.recipe_asset_attachments(combined_ids, entry_type)
            else:
                final_attachments = asset_attachments or None
            recipe_warnings = self._validate_recipe_assets(recipe, final_attachments)

            entry = self.repos.entries.create(
                {
                    "title": title,
                    "summary": summary,
                    "entry_type_id": entry_type.id,
                    "status": "inbox",  # draft — review before publishing
                    "data_json": data_json,
                    "asset_attachments": final_attachments,
                    "created_by": getattr(self.user, "id", None),
                }
            )
            self.session.commit()
            # Link the model's tags onto the draft — find-or-create by slug, reusing the vocabulary.
            if isinstance(proposed_tags, list | tuple) and proposed_tags:
                self.repos.entries.apply_fields(entry.id, {"tags": list(proposed_tags)})
            # Link the resources it references — reuse-only (existing catalog), like revise. So a recipe
            # that extracts suppliers/materials lands them linked, without inventing duplicate resources.
            attached_resources = self._attach_existing_resources(entry.id, proposed_resources)
            self.session.commit()

            # Upgrade the draft's warnings from asset-only to the full completeness contract
            # (required fields + assets + resources + tags), so the author/AI sees every gap that
            # would block publishing. Best-effort — fall back to the asset warnings on any error.
            try:
                from marvin.db.models.platform.entries import Entries as _Entries
                from marvin.services.entries.completeness import evaluate_entry as _evaluate_entry

                _orm = self.session.get(_Entries, entry.id)
                if _orm is not None:
                    recipe_warnings = _evaluate_entry(_orm, entry_type).blocking_messages()
            except Exception as _e:  # noqa: BLE001
                self.logger.debug("compose completeness eval skipped: %s", _e)

            self._emit_entry_created(entry, entry_type)

            # Recipe enrichment: derive alt text for the draft's images (opt-in, best-effort).
            enriched_alt = self._run_alt_text_enrichment(recipe, final_attachments)
            # Recipe enrichment: run local media derivations (grade/crop) declared in the recipe's
            # asset `derive` tokens — deterministic, no model, best-effort.
            self._run_media_enrichment(entry.id)

            self._complete_execution(
                execution,
                completion,
                start,
                entity_id=entry.id,
                output={
                    "entry_id": str(entry.id),
                    "title": title,
                    "status": entry.status,
                    **(
                        {
                            "fields": data_json,
                            "tags": list(proposed_tags or []),
                            "resources": attached_resources,
                            "assets": auto_asset_slugs,
                            "altText": enriched_alt,
                        }
                        if log_outputs
                        else {}
                    ),
                },
            )
        except Exception as e:
            self._fail_execution(execution, str(e), start)
            raise

        return {
            "entryId": str(entry.id),
            "status": entry.status,
            "title": title,
            "tags": list(proposed_tags or []),
            "resources": attached_resources,
            "assets": auto_asset_slugs,
            "altText": enriched_alt,
            "warnings": recipe_warnings,
            "editUrl": entry_edit_url(entry.id),
            "reviewLink": entry_review_link(entry.id),
            "executionId": str(execution.id),
            "totalTokens": execution.total_tokens,
            "estimatedCostUsd": execution.estimated_cost_usd,
            "generated": data_json,
        }

    def revise(
        self,
        *,
        entry,
        instruction: str,
        source: str = "api",
        register: str = "auto",
        log_inputs: bool = False,
        log_outputs: bool = True,
        max_tokens: int | None = None,
        ground: bool = True,
    ) -> dict:
        """Revise an EXISTING entry in place per an instruction — never recreate it.

        The model sees the entry's current fields/tags/resources + the catalog, and returns the
        full field set (unchanged ones as-is) plus tags and resource references to associate. We
        merge fields, link tags (find-or-create), and attach resources that already exist (reuse).
        Good for "determine tags/resources for this entry" or "tighten the summary".
        """
        import json

        from marvin.db.models.groups.ai_executions import AIExecutionModel
        from marvin.db.models.platform.entry_types import EntryTypes
        from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
        from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
        from marvin.services.ai.base import CompletionOptions, Message
        from marvin.services.ai.compose import entry_type_to_output_schema

        entry_type = self.session.get(EntryTypes, entry.entry_type_id)
        schema_def = EntryTypeSchemaDefinition.model_validate((entry_type.schema_json if entry_type else {}) or {})
        recipe = EntryTypeRecipe.model_validate((entry_type.recipe_json if entry_type else {}) or {})
        output_schema = entry_type_to_output_schema(schema_def, entry_type.name if entry_type else "Entry")
        if isinstance(output_schema, dict) and isinstance(output_schema.get("properties"), dict):
            # Content fields become optional (return unchanged ones untouched, so a tags-only ask
            # needn't re-emit the body) — but tags/resources are REQUIRED so the model always
            # determines them.
            output_schema["required"] = ["tags", "resources"]
            output_schema["properties"]["tags"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags to associate. Reuse existing tag names where they fit; only add new when none match.",
            }
            output_schema["properties"]["resources"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names/slugs of EXISTING resources to attach (from the list in the prompt). Do not invent new ones.",
            }

        current = (
            f"Current title: {entry.title}\n"
            f"Current summary: {entry.summary or '—'}\n"
            f"Current fields: {json.dumps(entry.data_json or {}, ensure_ascii=False)}\n"
            f"Current tags: {', '.join(entry.tag_names) or 'none'}\n"
            f"Currently attached resources: {', '.join(r.slug for r in entry.resources) or 'none'}"
        )
        seed = " ".join(filter(None, [entry.title, entry.summary, json.dumps(entry.data_json or {})]))
        grounding = self._grounding_block(seed) if ground else ""
        instruction_msg = (
            f"Revise this existing '{entry_type.name if entry_type else 'entry'}'. Do NOT recreate it — change only "
            f"what the instruction asks; return the FULL field set (unchanged fields exactly as-is), plus tags and "
            f"resources to associate.{self._recipe_instructions_block(recipe)}\n\n{current}\n\nInstruction: {instruction}{grounding}"
        )
        messages = [
            Message(
                role="system",
                content=(
                    "You are a content editor revising an existing entry. Reuse the existing tags and resources listed; "
                    "never invent duplicates. Return ONLY the requested fields."
                ),
            ),
            Message(role="user", content=instruction_msg),
        ]

        execution = AIExecutionModel(
            session=self.session,
            group_id=self.group_id,
            operation_slug="revise-entry",
            provider_type=self.provider.provider_type,
            model_id=self.model,
            status="pending",
            triggered_by=getattr(self.user, "id", None),
            trigger_type=source,
            entity_type="entry",
            entity_id=entry.id,
            input_json={"entry": str(entry.id), "instruction": instruction} if log_inputs else None,
        )
        self.session.add(execution)
        self.session.commit()
        self.last_execution = execution

        start = time.monotonic()
        try:
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            self.session.commit()

            opts = CompletionOptions(temperature=self._temperature(), max_tokens=max_tokens)
            parsed, completion = self.provider.execute_operation(messages, self.model, output_schema, opts)

            fields = dict(parsed or {})
            new_title = fields.pop("title", None)
            new_summary = fields.pop("summary", None)
            proposed_tags = fields.pop("tags", None)
            proposed_resources = fields.pop("resources", None)
            allowed = schema_def.get_field_keys()
            new_fields = {k: v for k, v in fields.items() if k in allowed}
            tag_list = list(proposed_tags) if isinstance(proposed_tags, list | tuple) else []
            resource_refs = [str(r).strip() for r in proposed_resources if str(r).strip()] if isinstance(proposed_resources, list | tuple) else []

            # Honor the workspace approval policy, exactly like the operations controller's write-back:
            # suggest-only always stages; allow-draft-update applies to drafts and stages published;
            # allow-automatic-update always applies. Revise must not bypass the review wall.
            mode = self._approval_mode()
            is_draft = entry.status not in ("published", "archived")
            should_apply = mode == "allow-automatic-update" or (mode == "allow-draft-update" and is_draft)

            if should_apply:
                # Associations first (they can't fail content validation) so a malformed field
                # re-emission can never lose the tags/resources the user actually asked for.
                if tag_list:
                    self.repos.entries.apply_fields(entry.id, {"tags": tag_list})
                attached_resources = self._attach_existing_resources(entry.id, resource_refs)
                self.session.commit()

                update: dict = {}
                if new_title:
                    update["title"] = new_title
                if new_summary is not None:
                    update["summary"] = new_summary
                if new_fields:
                    update["data_json"] = {**(entry.data_json or {}), **new_fields}  # merge, don't clobber
                if update:
                    try:
                        self.repos.entries.update(entry.id, update)
                    except Exception as e:  # a bad field value shouldn't sink the whole revise
                        self.session.rollback()
                        self.logger.warning(f"AuthoringService.revise: field update skipped (validation): {e}")

                self._emit_entry_updated(entry)
                outcome = "applied"
            else:
                # Stage the whole revision for review — nothing touches the entry yet. The entries
                # "apply suggestion" endpoint commits it later (title/summary/fields/tags/resources
                # via apply_fields' special targets).
                proposed: dict = {}
                if new_title:
                    proposed["title"] = new_title
                if new_summary is not None:
                    proposed["summary"] = new_summary
                for k, v in new_fields.items():
                    proposed[f"data_json.{k}"] = v
                if tag_list:
                    proposed["tags"] = tag_list
                if resource_refs:
                    proposed["resources"] = resource_refs
                self.repos.entries.stage_suggestion(
                    entry.id,
                    {**proposed, "_meta": {"operation": "revise-entry", "executionId": str(execution.id)}},
                )
                self.session.commit()
                attached_resources = []  # staged, not attached yet
                outcome = "staged"

            changed = {"fields": list(new_fields), "tags": tag_list, "resources": attached_resources or resource_refs}
            self._complete_execution(
                execution,
                completion,
                start,
                entity_id=entry.id,
                output={
                    "entry_id": str(entry.id),
                    "outcome": outcome,
                    **({"changed": changed} if log_outputs else {}),
                },
            )
        except Exception as e:
            self._fail_execution(execution, str(e), start)
            raise

        fresh = self.session.get(type(entry), entry.id)
        return {
            "entryId": str(entry.id),
            "outcome": outcome,  # "applied" (live) | "staged" (pending review per approval_mode)
            "title": fresh.title,
            "tags": list(fresh.tag_names),
            "resources": [r.slug for r in fresh.resources],
            # When staged the entry is untouched, so echo what the model proposed for the review UI.
            "proposed": {"tags": tag_list, "resources": resource_refs} if outcome == "staged" else None,
            "editUrl": entry_edit_url(entry.id),
            "reviewLink": entry_review_link(entry.id, "Review the entry"),
            "executionId": str(execution.id),
            "totalTokens": execution.total_tokens,
            "estimatedCostUsd": execution.estimated_cost_usd,
        }

    def _validate_recipe_assets(self, recipe, attachments) -> list[str]:
        """Warn when a composed draft doesn't satisfy the entry type's asset contract — the recipe
        expects a hero image but none was attached, or fewer images than the declared minimum.

        Advisory only: compose still lands the draft. The warnings ride the result so the author
        knows what to add before publishing. Empty when the recipe declares no asset requirements.
        """
        assets = getattr(recipe, "assets", None)
        if not assets:
            return []
        attachments = attachments or []
        warnings: list[str] = []
        n = len(attachments)
        if assets.min and n < assets.min:
            warnings.append(f"This type expects at least {assets.min} image(s); {n} attached.")
        roles_present = {a.get("role") for a in attachments if isinstance(a, dict) and a.get("role")}
        for r in assets.roles or []:
            if (r.required or (r.min and r.min > 0)) and r.role not in roles_present:
                warnings.append(f"This type expects a '{r.role}' image; none attached.")
        return warnings

    def _alt_text_requested(self, recipe) -> bool:
        """Whether the entry type's recipe asks compose to derive alt text for its images —
        either a top-level ``enrichment.alt_text`` flag or any asset role deriving "alt_text"."""
        enrichment = getattr(recipe, "enrichment", None)
        if isinstance(enrichment, dict) and enrichment.get("alt_text"):
            return True
        assets = getattr(recipe, "assets", None)
        roles = (getattr(assets, "roles", None) or []) if assets else []
        return any("alt_text" in (getattr(r, "derive", None) or []) for r in roles)

    def _run_media_enrichment(self, entry_id) -> list[str]:
        """Recipe enrichment step: run the entry type's local media derivations (grade/crop) on the
        draft's images, driven by the recipe's asset ``derive`` tokens. Deterministic (Pillow, no
        model), best-effort — a failure never breaks compose. Returns produced-derivative summaries."""
        try:
            from marvin.services.ai.media.enrichment import MediaEnrichmentService

            return MediaEnrichmentService(
                self.session,
                self.repos,
                self.group_id,
                user_id=getattr(self.user, "id", None),
                provider=self.provider,
                model=self.model,
            ).run_for_entry(entry_id)
        except Exception as e:  # noqa: BLE001
            self.logger.debug("media enrichment skipped: %s", e)
            return []

    def _run_alt_text_enrichment(self, recipe, attachments) -> list[str]:
        """Recipe enrichment step: generate accessible alt text for freshly-attached image assets
        that lack it, reusing the ``generate-alt-text`` operation. Opt-in via the recipe.

        Best-effort and self-contained: needs a vision-capable provider, skips assets that already
        have alt text or aren't images, and a failed vision call never breaks compose. Returns the
        slugs it enriched.
        """
        if not self._alt_text_requested(recipe) or not attachments:
            return []
        if not (self.provider and getattr(self.provider, "supports_vision", False) and self.model):
            return []
        import uuid as _uuid

        from marvin.db.models.platform import Assets
        from marvin.services.ai.base import CompletionOptions
        from marvin.services.ai.context import ContextBuilder, resolve_prompt_messages
        from marvin.services.ai.operations.base import get_operation

        op = get_operation("generate-alt-text")
        enriched: list[str] = []
        for att in attachments:
            aid = att.get("asset_id") if isinstance(att, dict) else None
            if not aid:
                continue
            try:
                asset = self.session.get(Assets, _uuid.UUID(str(aid)))
            except (ValueError, TypeError):
                asset = None
            if not asset or asset.group_id != self.group_id:
                continue
            if asset.alt_text or (asset.asset_type or "") != "image":
                continue
            try:
                ctx = (
                    ContextBuilder(self.session, self.group_id).with_site_settings().with_variables().with_asset(asset.id).with_asset_images().build()
                )
                if not (ctx.assets and ctx.assets[0].get("image_data")):
                    continue  # unreadable / not actually an image
                messages = resolve_prompt_messages(op.build_prompt({}, ctx), self.group_id, ctx.variables)
                opts = CompletionOptions(temperature=self._temperature(), max_tokens=300)
                parsed, _ = self.provider.execute_operation(messages, self.model, op.output_schema, opts)
                alt = (parsed or {}).get("alt_text")
                if alt:
                    asset.alt_text = alt
                    self.session.commit()
                    enriched.append(asset.slug)
            except Exception as e:  # enrichment is best-effort — never sink the compose
                self.session.rollback()
                self.logger.warning(f"AuthoringService: alt-text enrichment skipped for asset {aid}: {e}")
        return enriched

    def _recipe_instructions_block(self, recipe) -> str:
        """The recipe author's verbatim ``instructions`` — freeform "how to build this type" prose the
        model follows. This is the cascade's freeform layer: the recipe carries the directions, compose
        just injects them (no per-type code). Empty when the recipe declares no instructions."""
        text = getattr(recipe, "instructions", None)
        if not text or not str(text).strip():
            return ""
        return f"\n\nAuthoring instructions for this type (follow these):\n{str(text).strip()}"

    def _recipe_resource_hint(self, recipe) -> str:
        """A prompt fragment for the entry type's recipe.resources.extract rules — tells the model which
        kinds of resource to pull from which field, so composed drafts execute the recipe's extraction
        (reusing existing resources). Empty when the recipe declares no extraction."""
        extract = getattr(recipe.resources, "extract", None) if getattr(recipe, "resources", None) else None
        if not extract:
            return ""
        types = ", ".join(sorted({e.type for e in extract if getattr(e, "type", None)}))
        sources = ", ".join(sorted({getattr(e, "source", None) or "body" for e in extract})) or "the content"
        if not types:
            return ""
        return (
            f"\n\nThis entry type extracts resources: identify the {types} referenced in {sources} and list them "
            f"by name in `resources`. Reuse the existing resource names above where they match; do not invent new ones."
        )

    def _recipe_asset_hint(self, recipe) -> str:
        """A prompt fragment about attaching EXISTING images, driven by the recipe's asset contract.

        Keys off the recipe, not just role declaration: it URGES attachment only for roles the type
        actually needs (``required`` or ``min > 0``), treats every other declared role as optional —
        attach one only if the brief explicitly calls for an image — and states the overall ``max``.
        So an optional-image type (e.g. a nav page whose hero is merely allowed) no longer gets a hero
        stapled on unbidden. Empty when the recipe declares no asset roles.
        """
        assets = getattr(recipe, "assets", None)
        roles = list(getattr(assets, "roles", None) or []) if assets else []
        if not roles:
            return ""

        def _needed(r) -> bool:
            return bool(getattr(r, "required", False) or (getattr(r, "min", 0) or 0) > 0)

        def _label(r) -> str:
            return f"{r.role} (up to {r.max})" if getattr(r, "max", None) else r.role

        required = [r for r in roles if _needed(r)]
        optional = [r for r in roles if not _needed(r)]
        parts: list[str] = []
        if required:
            parts.append(
                "This entry type needs images for: "
                + ", ".join(_label(r) for r in required)
                + ". Attach a fitting EXISTING image for each in `assets` (reuse only, by name or slug from the "
                "list above); the first becomes the hero."
            )
        if optional:
            lead = "Optional image slot(s): " if required else "Images are optional here — "
            parts.append(
                lead
                + ", ".join(_label(r) for r in optional)
                + ". Only attach one if the brief explicitly calls for an image and an existing one clearly fits; "
                "otherwise leave `assets` empty."
            )
        total_max = getattr(assets, "max", None)
        if total_max:
            parts.append(f"Attach at most {total_max} image(s) in total, and never invent images.")
        return "\n\n" + " ".join(parts)

    def _attach_existing_resources(self, entry_id, refs) -> list[str]:
        """Attach only resources that already exist (reuse); ignore unknown refs. Returns attached slugs.

        Resolves each ref by id, slug, OR name — the grounding lists resources by *name*, so the model
        returns names; matching by name is essential (slug-only resolution silently linked nothing)."""
        if not isinstance(refs, list | tuple) or not refs:
            return []
        import uuid as _uuid

        from marvin.db.models.platform import EntryResources, Resources

        attached: list[str] = []
        for ref in refs:
            ref = str(ref).strip()
            if not ref:
                continue
            resource = None
            try:
                resource = self.session.get(Resources, _uuid.UUID(ref))
            except (ValueError, TypeError):
                resource = (
                    self.session.query(Resources)
                    .filter(Resources.group_id == self.group_id)
                    .filter((Resources.slug == ref) | (Resources.name == ref))
                    .first()
                )
            if not resource or str(resource.group_id) != str(self.group_id):
                continue
            exists = self.session.query(EntryResources).filter_by(entry_id=entry_id, resource_id=resource.id).first()
            if exists is None:
                self.session.add(EntryResources(entry_id=entry_id, resource_id=resource.id, position=0))
                attached.append(resource.slug)
        return attached

    def _resolve_asset_refs(self, refs, exclude_ids=None) -> list:
        """Resolve existing-asset refs (id, slug, OR name) to (id, slug), reuse-only, deduped and
        excluding ids the caller already supplied. The grounded catalog lists assets by name, so the
        model returns names — matching by name is essential. Unknown refs are ignored."""
        if not isinstance(refs, list | tuple) or not refs:
            return []
        import uuid as _uuid

        from marvin.db.models.platform import Assets

        exclude = {str(x) for x in (exclude_ids or [])}
        out: list = []
        seen: set = set()
        for raw in refs:
            ref = str(raw).strip()
            if not ref:
                continue
            asset = None
            try:
                asset = self.session.get(Assets, _uuid.UUID(ref))
            except (ValueError, TypeError):
                asset = (
                    self.session.query(Assets).filter(Assets.group_id == self.group_id).filter((Assets.slug == ref) | (Assets.name == ref)).first()
                )
            if not asset or str(asset.group_id) != str(self.group_id):
                continue
            if str(asset.id) in exclude or asset.id in seen:
                continue
            seen.add(asset.id)
            out.append((asset.id, asset.slug))
        return out

    def _emit_entry_updated(self, entry) -> None:
        """Dispatch entry_updated after a revise so reactions fire (re-embed, smart collections). Best-effort."""
        from marvin.services.event_bus_service.event_types import EventEntryData, EventOperation, EventTypes

        try:
            grp = self.repos.groups.get_one(self.group_id)
            self._event_bus_or_default().dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=EventTypes.entry_updated,
                document_data=EventEntryData(
                    operation=EventOperation.update,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    entry_type=None,
                    workspace_id=self.group_id,
                    workspace_name=getattr(grp, "name", None) if grp else None,
                    author_id=getattr(self.user, "id", None),
                ),
                message=f"Entry '{entry.title}' revised by AI",
                user_id=getattr(self.user, "id", None),
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:
            self.logger.error(f"AuthoringService: failed to dispatch entry_updated: {e}")

    def recipe_asset_attachments(self, asset_ids: list, entry_type) -> list[dict]:
        """Map provided assets to the type recipe's roles (first → hero, then declared order)."""
        from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

        recipe = EntryTypeRecipe.model_validate(entry_type.recipe_json or {})
        roles = [r.role for r in recipe.assets.roles] if (recipe.assets and recipe.assets.roles) else []
        out: list[dict] = []
        for i, aid in enumerate(asset_ids):
            role = roles[i] if i < len(roles) else (roles[-1] if roles else None)
            out.append({"asset_id": str(aid), "role": role, "position": i})
        return out

    # ── Catalog grounding (reuse, don't duplicate) ───────────────────────────

    def _grounding_block(self, seed_text: str) -> str:
        """A prompt block listing what already exists — the workspace tag vocabulary plus (via RAG)
        resources/assets relevant to the seed — so the model reuses instead of inventing duplicates."""
        from marvin.db.models.platform import Tags

        parts: list[str] = []
        tags = self.session.query(Tags).filter_by(group_id=self.group_id).order_by(Tags.name).limit(80).all()
        if tags:
            parts.append(
                "Existing tags — REUSE these exact names where they fit; do not invent near-duplicates:\n  " + ", ".join(t.name for t in tags)
            )
        catalog = self._rag_catalog(seed_text)
        if catalog:
            parts.append(catalog)
        if not parts:
            return ""
        return "\n\n## Already in this workspace — reuse, don't duplicate\n" + "\n".join(parts)

    def _rag_catalog(self, seed_text: str) -> str:
        """RAG-relevant existing resources/assets for the seed text, as a short reuse hint.

        Resources and assets get SEPARATE retrieval budgets rather than sharing one top-k. Pooled,
        a text-heavy brief's near-exact resource matches take every slot and assets never surface —
        so compose could never suggest an existing image to attach. Split, each kind always gets a
        fair share. The seed is embedded once and reused for both queries.
        """
        if not (seed_text and self.provider and getattr(self.provider, "supports_embeddings", False)):
            return ""
        from marvin.services.ai.embeddings import default_embedding_model, search_embeddings
        from marvin.services.ai.entity_resolve import resolve_retrieved_sources

        emb = default_embedding_model(self.provider.provider_type)
        if not emb:
            return ""
        try:
            qvec = self.provider.embed([seed_text], emb)[0]
        except Exception as e:  # grounding must never break authoring
            self.logger.warning(f"AuthoringService: RAG grounding embed failed: {e}")
            return ""

        def _titles(entity_type: str, limit: int) -> list[str]:
            try:
                rows = search_embeddings(self.session, self.group_id, qvec, limit, [entity_type])
                srcs = resolve_retrieved_sources(self.session, rows or [])
            except Exception as e:
                self.logger.warning(f"AuthoringService: RAG grounding ({entity_type}) failed: {e}")
                return []
            return list(dict.fromkeys(s["title"] for s in srcs if s.get("entity_type") == entity_type))

        res = _titles("resource", 6)
        ass = _titles("asset", 6)
        out: list[str] = []
        if res:
            out.append("Relevant existing resources (reference/attach these rather than recreating): " + ", ".join(res))
        if ass:
            out.append("Relevant existing assets: " + ", ".join(ass))
        return "\n".join(out)

    # ── Execution-record + event machinery (self-contained) ──────────────────

    def _temperature(self) -> float:
        from marvin.core.config import get_app_settings

        return getattr(get_app_settings(), "AI_DEFAULT_TEMPERATURE", 0.7)

    def _approval_mode(self) -> str:
        """Workspace approval policy: suggest-only | allow-draft-update | allow-automatic-update.

        The same gate the operations controller applies to AI write-back. Defaults to the safest
        (suggest-only) when unset, so AI edits are staged for review rather than auto-applied.
        """
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        settings = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        return settings.approval_mode if settings and settings.approval_mode else "suggest-only"

    def _complete_execution(self, execution, completion, start, *, entity_id, output: dict) -> None:
        from marvin.services.ai.pricing import estimate_cost

        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.entity_type = "entry"
        execution.entity_id = entity_id
        execution.output_json = output
        execution.prompt_tokens = completion.prompt_tokens
        execution.completion_tokens = completion.completion_tokens
        execution.total_tokens = completion.total_tokens
        execution.estimated_cost_usd = estimate_cost(
            self.provider.provider_type,
            self.model,
            completion.prompt_tokens,
            completion.completion_tokens,
        )
        self.session.commit()

    def _fail_execution(self, execution, message: str, start) -> None:
        try:
            execution.status = "failed"
            execution.error_message = message[:2000]
            execution.completed_at = datetime.now(UTC)
            execution.duration_ms = int((time.monotonic() - start) * 1000)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            self.logger.warning(f"AuthoringService: could not record failure: {e}")

    def _event_bus_or_default(self):
        if self._event_bus is not None:
            return self._event_bus
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        return EventBusService(bg_tasks=None)

    def _emit_entry_created(self, entry, entry_type) -> None:
        """Dispatch entry_created so reactions fire (smart-collection routing, RAG index, …). Best-effort."""
        from marvin.services.event_bus_service.event_types import EventEntryData, EventOperation, EventTypes

        try:
            grp = self.repos.groups.get_one(self.group_id)
            self._event_bus_or_default().dispatch(
                integration_id="entry_management",
                group_id=self.group_id,
                event_type=EventTypes.entry_created,
                document_data=EventEntryData(
                    operation=EventOperation.create,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    entry_type=entry_type.slug,
                    workspace_id=self.group_id,
                    workspace_name=getattr(grp, "name", None) if grp else None,
                    author_id=getattr(self.user, "id", None),
                ),
                message=f"Entry '{entry.title}' composed by AI",
                user_id=getattr(self.user, "id", None),
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:
            self.logger.error(f"AuthoringService: failed to dispatch entry_created: {e}")
