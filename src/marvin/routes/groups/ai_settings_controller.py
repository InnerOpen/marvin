"""API routes for per-workspace AI workflow policy settings."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_settings import (
    AIUsageLimits,
    AIUsageOperation,
    AssistantCharacter,
    AssistantCharacterAssign,
    AssistantCharacterLibraryChoice,
    AssistantCharacterState,
    AssistantCharacterUpload,
    BubbleLines,
    BubbleLinesState,
    CharacterPackSummary,
    TonePreview,
    TonePreviewRequest,
    ToneRead,
    TonesState,
    TonesUpdate,
    WorkspaceAISettingsRead,
    WorkspaceAISettingsUpdate,
    WorkspaceAIUsage,
)

router = APIRouter(prefix="/groups/ai-settings", route_class=MarvinCrudRoute)


def _bubble_lines_generating(group_id) -> bool:
    from marvin.services.ai.bubble_lines import is_generating

    return is_generating(group_id)


@controller(router)
class AISettingsController(BaseUserController):
    """Manage per-workspace AI workflow policy — group_id comes from the user session."""

    def _require_admin(self) -> None:
        if self.user.admin:
            return
        for m in self.user.workspace_memberships:
            if m.group_id == self.group_id and WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0) >= 4:
                return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN or OWNER role required.")

    def _allow_workspace_credentials(self) -> bool:
        from marvin.core.config import get_app_settings

        return bool(getattr(get_app_settings(), "AI_ALLOW_WORKSPACE_CREDENTIALS", True))

    @router.get("/sources", summary="List invocation sources (for the policy editor)")
    def list_invocation_sources(self) -> list[dict]:
        """The catalog of AI invocation surfaces — key + human label/description — so the settings UI
        can render a toggle per source. A source is allowed unless the workspace policy sets it false."""
        from marvin.services.ai.agents import ROUTER_SLUG, agent_names
        from marvin.services.ai.operations.base import INVOCATION_SOURCE_CATALOG

        assistant = agent_names(self.session, self.group_id)[ROUTER_SLUG]
        return [{k: v.format(assistant=assistant) for k, v in s.items()} for s in INVOCATION_SOURCE_CATALOG]

    @router.get("/usage", response_model=WorkspaceAIUsage, summary="AI usage against the workspace's limits")
    def get_usage(self) -> WorkspaceAIUsage:
        """This month's estimated spend and today's runs against the budget limits, and what cost the most."""
        from marvin.services.ai import budget
        from marvin.services.ai.agents import agent_names, operation_label

        u = budget.usage(self.session, self.group_id)
        names = agent_names(self.session, self.group_id)
        return WorkspaceAIUsage(
            limits=AIUsageLimits(
                max_cost_per_month_usd=u.limits.month_usd,
                max_requests_per_day=u.limits.per_day,
                max_tokens_per_request=u.limits.tokens_per_request,
            ),
            warning_percent=u.warning_percent,
            level=u.level,
            month_cost_usd=u.month_cost_usd,
            month_tokens=u.month_tokens,
            month_runs=u.month_runs,
            month_percent=u.month_percent,
            today_runs=u.today_runs,
            day_percent=u.day_percent,
            resets_on=u.resets_on,
            by_operation=[AIUsageOperation(label=operation_label(o["operation"], names), **o) for o in u.by_operation],
        )

    @router.get("", response_model=WorkspaceAISettingsRead, summary="Get AI Workflow Settings")
    def get_ai_settings(self) -> WorkspaceAISettingsRead:
        """Return current settings; returns defaults when no row exists yet."""
        allow_ws = self._allow_workspace_credentials()
        from marvin.services.ai.character import insets_by_url
        from marvin.services.ai.character_library import agent_characters as resolve_agent_characters

        agents = resolve_agent_characters(self.session, self.group_id)
        agent_characters = {slug: character["states"] for slug, character in agents.items()}
        insets = {url: inset for character in agents.values() for url, inset in insets_by_url(character).items()}
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row:
            return WorkspaceAISettingsRead(
                group_id=self.group_id, allow_workspace_credentials=allow_ws, agent_characters=agent_characters, character_insets=insets
            )
        result = WorkspaceAISettingsRead.model_validate(row)
        result.allow_workspace_credentials = allow_ws
        result.assistant_character = self._effective_character(row)
        result.agent_characters = agent_characters
        result.character_insets = {**insets, **insets_by_url(result.assistant_character)}
        result.bubble_lines_generating = _bubble_lines_generating(self.group_id)
        return result

    @router.patch("", response_model=WorkspaceAISettingsRead, summary="Update AI Workflow Settings")
    def update_ai_settings(self, data: WorkspaceAISettingsUpdate) -> WorkspaceAISettingsRead:
        """Upsert AI workflow settings. Creates the row on first write."""
        self._require_admin()

        # Platform policy: workspaces may be barred from using their own AI credentials.
        if data.credential_mode == "workspace" and not self._allow_workspace_credentials():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace-provided AI credentials are disabled by the platform administrator.",
            )

        warnings = []
        if data.credential_mode == "workspace" and data.secret_ref:
            from marvin.db.models.groups.secrets import WorkspaceSecret

            exists = self.session.query(WorkspaceSecret).filter_by(group_id=self.group_id, slug=data.secret_ref).first()
            if not exists:
                warnings.append(f"Secret slug '{data.secret_ref}' not found in this workspace.")

        if data.assistant_icon:
            from marvin.services.ai.persona import icon_problem

            problem = icon_problem(data.assistant_icon)
            if problem:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

        character_set = "assistant_character" in data.model_fields_set
        library_choice = None
        if character_set:
            from marvin.services.ai.character import LIBRARY_KEY, CharacterError, character_problem

            if isinstance(data.assistant_character, dict) and LIBRARY_KEY in data.assistant_character:
                from marvin.services.ai.character_library import library_reference

                try:
                    library_choice = library_reference(self.session, data.assistant_character[LIBRARY_KEY])
                except CharacterError as e:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
            else:
                problem = character_problem(data.assistant_character)
                if problem:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

        if "approval_mode" in data.model_fields_set:
            from marvin.services.ai.approval import APPROVAL_MODES

            if data.approval_mode not in APPROVAL_MODES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"approval_mode must be one of: {', '.join(APPROVAL_MODES)}.",
                )

        if "default_register" in data.model_fields_set:
            data.default_register = self._usable_default_tone(data.default_register)

        row = self._settings_row()
        if data.provider and data.provider != row.provider:
            # A newly chosen provider must be installed (built in, or an AI provider plugin); a stored one
            # that has since gone stays saveable, so the rest of the form still works.
            from marvin.routes.ai.provider_types_controller import require_installed_provider

            require_installed_provider(data.provider)
        persona_set = bool({"assistant_name", "persona_prompt"} & data.model_fields_set)
        before_name, before_persona = row.assistant_name, row.persona_prompt

        updates = data.model_dump(exclude_unset=True)
        updates.pop("assistant_character", None)  # merged below: the file list isn't the caller's to set
        for field, value in updates.items():
            if hasattr(row, field):
                setattr(row, field, value)

        previous_character = row.assistant_character
        if character_set and (library_choice or data.assistant_character is None):
            row.assistant_character = library_choice
        elif character_set:
            from marvin.services.ai.character import library_ref

            states = {k: v.strip() for k, v in data.assistant_character["states"].items()}
            # Own animations replace a library pack outright; there's nothing of its to keep.
            own = previous_character if not library_ref(previous_character) else None
            row.assistant_character = {**(own or {}), "states": states}

        if data.credential_mode is not None and data.credential_mode != "workspace":
            row.secret_ref = None

        self.session.commit()
        self.session.refresh(row)

        if character_set:
            from marvin.services.ai.character import character_file_ids, delete_character_files

            store = self._character_store()
            delete_character_files(store, previous_character, keep=character_file_ids(store, row.assistant_character))

        if persona_set:
            from marvin.services.ai.bubble_lines import on_persona_saved

            on_persona_saved(self.session, row, before_name, before_persona, self.user.id)

        result = WorkspaceAISettingsRead.model_validate(row)
        result.assistant_character = self._effective_character(row)
        result.bubble_lines_generating = _bubble_lines_generating(self.group_id)
        if warnings:
            self.logger.warning("AI settings saved with warnings: %s", "; ".join(warnings))
        return result

    # --- tones (services/ai/tones.py) ---------------------------------------------------------------

    def _usable_default_tone(self, slug: str | None, tones=None) -> str:
        """`slug` normalised, or 422 unless it names a tone the workspace has and doesn't hide."""
        from marvin.services.ai.tones import load_workspace_tones

        tones = tones or load_workspace_tones(self.session, self.group_id)
        key = (slug or "auto").strip().lower()
        if tones.get(key) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"No tone '{key}' in this workspace.")
        if key in tones.hidden:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The default tone can't be a hidden one.")
        return key

    def _agents_by_tone(self) -> dict[str, list[str]]:
        from marvin.db.models.groups.agents import WorkspaceAgentModel

        rows = (
            self.session.query(WorkspaceAgentModel.slug, WorkspaceAgentModel.default_register)
            .filter(WorkspaceAgentModel.group_id == self.group_id, WorkspaceAgentModel.default_register.isnot(None))
            .all()
        )
        out: dict[str, list[str]] = {}
        for slug, tone in rows:
            out.setdefault(tone, []).append(slug)
        return out

    def _tones_state(self) -> TonesState:
        from marvin.services.ai import tones as t

        state = t.load_workspace_tones(self.session, self.group_id)
        used = self._agents_by_tone()
        return TonesState(
            tones=[
                ToneRead(
                    slug=x.slug,
                    name=x.name,
                    instructions=x.instructions,
                    persona=x.persona,
                    description=x.description,
                    builtin=x.builtin,
                    hidden=x.slug in state.hidden,
                    used_by=sorted(used.get(x.slug, [])),
                )
                for x in state.all()
            ],
            default_tone=state.default.slug,
            max_custom_tones=t.MAX_CUSTOM_TONES,
            max_name_chars=t.MAX_NAME_CHARS,
            max_instructions_chars=t.MAX_INSTRUCTIONS_CHARS,
        )

    @router.get("/tones", response_model=TonesState, summary="The workspace's tones")
    def get_tones(self) -> TonesState:
        """Built-in and custom tones, for the editor and every tone picker. Any member may read them."""
        return self._tones_state()

    @router.put("/tones", response_model=TonesState, summary="Save the workspace's tones")
    def put_tones(self, data: TonesUpdate) -> TonesState:
        """Replace the custom tones and hidden list (and optionally the default). ADMIN/OWNER only.

        A tone that agents default to can't be removed (409 naming them); an invalid list is a 422.
        """
        from marvin.routes._base.checks import require_workspace_admin
        from marvin.services.ai import tones as t

        require_workspace_admin(self.user, self.group_id)
        before = t.load_workspace_tones(self.session, self.group_id)
        try:
            custom = t.validate_tones([i.model_dump() for i in data.tones], existing=before.custom)
            hidden = t.validate_hidden(data.hidden, t.BUILTIN_TONES + tuple(custom))
        except t.ToneError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None

        kept = {x.slug for x in custom}
        removed = [x for x in before.custom if x.slug not in kept]
        used = self._agents_by_tone()
        blocked = {x.slug: sorted(used[x.slug]) for x in removed if x.slug in used}
        if blocked:
            names = ", ".join(f"'{x.name}'" for x in removed if x.slug in blocked)
            agents = sorted({a for v in blocked.values() for a in v})
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"Agents still default to {names}: {', '.join(agents)}. Pick another default tone for them first.",
                    "tones": blocked,
                },
            )

        after = t.WorkspaceTones(custom=tuple(custom), hidden=frozenset(hidden), default_slug=before.default_slug)
        default = data.default_tone if data.default_tone is not None else before.default_slug
        if data.default_tone is None and (after.get(default) is None or default in after.hidden):
            # The old default went away (or was hidden) and the caller didn't pick another: say so.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{default}' is the workspace's default tone; pick another default to remove or hide it.",
            )
        default = self._usable_default_tone(default, after)

        row = self._settings_row()
        row.tones = [x.to_json() for x in custom] or None
        row.hidden_tones = hidden or None
        row.default_register = default
        self.session.commit()
        return self._tones_state()

    @router.post("/tones/preview", response_model=TonePreview, summary="Preview a tone's prompt section")
    def preview_tone(self, data: TonePreviewRequest) -> TonePreview:
        """The section a tone adds to every agent step, with this workspace's character, in its parts, and its
        rough token cost: a saved tone (`slug`), a draft one (the editor's fields) or, with neither, the
        workspace default. `personaPrompt` / `assistantName` preview unsaved Character fields."""
        from marvin.services.ai import tones as t
        from marvin.services.ai.persona import resolve_persona

        self._require_admin()
        workspace = t.load_workspace_tones(self.session, self.group_id)
        if data.slug:
            tone = workspace.get(data.slug)
            if tone is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No tone '{data.slug}'.")
        elif data.is_draft:
            draft = {"name": data.name or "Untitled", "instructions": data.instructions, "persona": data.persona}
            try:
                tone = t.validate_tones([draft])[0]
            except t.ToneError as e:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        else:
            tone = workspace.default
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        sent = data.model_fields_set
        name = data.assistant_name if "assistant_name" in sent else (row.assistant_name if row else None)
        prompt = data.persona_prompt if "persona_prompt" in sent else (row.persona_prompt if row else None)
        _, persona = resolve_persona(name, prompt)
        return TonePreview(**t.preview(tone, persona))

    # --- the bubble's animated character (services/ai/character.py) ------------------------------

    def _settings_row(self) -> WorkspaceAISettingsModel:
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row:
            row = WorkspaceAISettingsModel(session=self.session, group_id=self.group_id)
            self.session.add(row)
        return row

    def _asset_service(self):
        from marvin.services.assets.asset_storage_service import AssetStorageService
        from marvin.services.storage.provider_factory import get_storage_provider

        return AssetStorageService(self.repos, get_storage_provider())

    def _character_store(self):
        from marvin.services.ai.character import WorkspaceAssetStore

        return WorkspaceAssetStore(self._asset_service(), self.group_id, self.user.id)

    def _effective_character(self, row: WorkspaceAISettingsModel) -> dict | None:
        """The character as the bubble plays it: a library pack resolved to its states."""
        from marvin.services.ai.character_library import resolve

        return resolve(self.session, row.assistant_character)

    def _described(self, row: WorkspaceAISettingsModel) -> dict | None:
        from marvin.services.ai.character import describe

        return describe(self._effective_character(row))

    @router.get("/character/catalog", response_model=list[AssistantCharacterState], summary="Bubble character states")
    def character_catalog(self) -> list[AssistantCharacterState]:
        """The canonical bubble states and the file names each one picks up from an upload."""
        from marvin.services.ai.character import catalog

        return [AssistantCharacterState(**s) for s in catalog()]

    @router.get("/character/library", response_model=list[CharacterPackSummary], summary="The platform's character library")
    def character_library(self) -> list[CharacterPackSummary]:
        """The packs a platform admin installed, any of which the workspace or its agents can use."""
        from marvin.services.ai.character import missing_states
        from marvin.services.ai.character_library import list_packs

        return [
            CharacterPackSummary(id=str(p.id), slug=p.slug, name=p.name, states=(p.pack or {}).get("states") or {}, missing=missing_states(p.pack))
            for p in list_packs(self.session)
        ]

    @router.put("/character/library", response_model=AssistantCharacter, summary="Use a library character")
    def use_library_character(self, data: AssistantCharacterLibraryChoice) -> AssistantCharacter:
        """The bubble plays a library pack; the workspace's own uploaded character, if any, is deleted."""
        from marvin.services.ai.character import CharacterError, save_character
        from marvin.services.ai.character_library import library_reference

        self._require_admin()
        try:
            choice = library_reference(self.session, data.pack)
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        row = self._settings_row()
        save_character(self.session, row, "assistant_character", choice, self._character_store())
        return AssistantCharacter(**self._described(row))

    @router.post("/character", response_model=AssistantCharacterUpload, summary="Upload the bubble character")
    def upload_character(self, files: list[UploadFile] = File(...)) -> AssistantCharacterUpload:
        """Replace the bubble's character with a .zip or loose GIF/WebP/PNG files, one per state by name.

        Every accepted image is stored as a workspace asset; the previous character's assets are deleted.
        """
        from marvin.services.ai.character import CharacterError, describe, plan_character, read_upload_files, save_character, store_character

        self._require_admin()
        try:
            plan = plan_character(read_upload_files(files))
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None

        store = self._character_store()
        character = store_character(store, plan)
        save_character(self.session, self._settings_row(), "assistant_character", character, store)
        return AssistantCharacterUpload(**describe(character), ignored=plan.ignored, idle_guessed=plan.idle_guessed, cleared=plan.cleared)

    @router.put("/character/states", response_model=AssistantCharacter, summary="Assign a bubble character state")
    def assign_character_state(self, data: AssistantCharacterAssign) -> AssistantCharacter:
        """Play one of the character's files for a state, or clear the state (it falls back) with file=null."""
        from marvin.services.ai.character import CharacterError, assign_state, save_character

        self._require_admin()
        row = self._settings_row()
        try:
            character = assign_state(row.assistant_character, data.state, data.file)
        except CharacterError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        save_character(self.session, row, "assistant_character", character, self._character_store())
        return AssistantCharacter(**self._described(row))

    @router.delete("/character", status_code=status.HTTP_204_NO_CONTENT, summary="Remove the bubble character")
    def delete_character(self) -> None:
        """Back to the icon; the character's stored assets are deleted (a library pack's stay in the library)."""
        from marvin.services.ai.character import save_character

        self._require_admin()
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row or not row.assistant_character:
            return
        save_character(self.session, row, "assistant_character", None, self._character_store())

    # --- the bubble's canned lines (services/ai/bubble_lines.py) ----------------------------------

    def _bubble_lines_state(self) -> BubbleLinesState:
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        state = BubbleLinesState.model_validate(row) if row else BubbleLinesState()
        state.bubble_lines_generating = _bubble_lines_generating(self.group_id)
        return state

    @router.get("/bubble-lines", response_model=BubbleLinesState, summary="The bubble's lines")
    def get_bubble_lines(self) -> BubbleLinesState:
        """The workspace's bubble lines, where they came from, and whether a generation is running."""
        return self._bubble_lines_state()

    @router.put("/bubble-lines", response_model=BubbleLinesState, summary="Edit the bubble's lines")
    def edit_bubble_lines(self, data: BubbleLines) -> BubbleLinesState:
        """Save hand-edited lines; a persona change won't overwrite them. All lists empty → the built-in lines."""
        from marvin.services.ai.bubble_lines import SOURCE_EDITED, BubbleLinesError, clean_edited, store

        self._require_admin()
        try:
            lines = clean_edited(data.model_dump())
        except BubbleLinesError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        store(self._settings_row(), lines, SOURCE_EDITED)
        self.session.commit()
        return self._bubble_lines_state()

    @router.delete("/bubble-lines", response_model=BubbleLinesState, summary="Back to the built-in bubble lines")
    def clear_bubble_lines(self) -> BubbleLinesState:
        """Drop the workspace's lines; the bubble uses its built-in ones again."""
        from marvin.services.ai.bubble_lines import store

        self._require_admin()
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if row:
            store(row, None, None)
            self.session.commit()
        return self._bubble_lines_state()

    @router.post(
        "/bubble-lines/generate", response_model=BubbleLinesState, status_code=status.HTTP_202_ACCEPTED, summary="Regenerate the bubble's lines"
    )
    def regenerate_bubble_lines(self) -> BubbleLinesState:
        """Write the lines from the persona again, in the background — replacing hand-edited ones too."""
        from marvin.services.ai.bubble_lines import preflight, start

        self._require_admin()
        if reason := preflight(self.session, self.group_id):
            code = status.HTTP_429_TOO_MANY_REQUESTS if reason.startswith("AI budget") else status.HTTP_422_UNPROCESSABLE_ENTITY
            raise HTTPException(status_code=code, detail=reason)
        start(self.group_id, self.user.id, force=True)
        return self._bubble_lines_state()
