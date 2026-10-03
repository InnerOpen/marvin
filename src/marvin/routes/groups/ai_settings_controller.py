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
    CharacterPackSummary,
    WorkspaceAISettingsRead,
    WorkspaceAISettingsUpdate,
    WorkspaceAIUsage,
)

router = APIRouter(prefix="/groups/ai-settings", route_class=MarvinCrudRoute)


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
        from marvin.services.ai.character_library import agent_character_states

        agent_characters = agent_character_states(self.session, self.group_id)
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row:
            return WorkspaceAISettingsRead(group_id=self.group_id, allow_workspace_credentials=allow_ws, agent_characters=agent_characters)
        result = WorkspaceAISettingsRead.model_validate(row)
        result.allow_workspace_credentials = allow_ws
        result.assistant_character = self._effective_character(row)
        result.agent_characters = agent_characters
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

        row = self._settings_row()

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

        result = WorkspaceAISettingsRead.model_validate(row)
        result.assistant_character = self._effective_character(row)
        if warnings:
            self.logger.warning("AI settings saved with warnings: %s", "; ".join(warnings))
        return result

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
        return AssistantCharacterUpload(**describe(character), ignored=plan.ignored, idle_guessed=plan.idle_guessed)

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
