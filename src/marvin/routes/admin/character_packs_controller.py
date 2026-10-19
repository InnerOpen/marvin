"""The platform's character library (admin): bubble-character packs any workspace or agent can pick.

A platform admin installs packs here once; workspaces only choose one (AI settings → Persona, Settings
→ Agents) or upload their own. See services/ai/character_library.py.
"""

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import UUID4

from marvin.db.models.platform.character_packs import CharacterPackModel
from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.group.ai_settings import AssistantCharacterAssign, BubbleLines
from marvin.schemas.platform.character_packs import (
    CharacterPackLinesRequest,
    CharacterPackRead,
    CharacterPackUpdate,
    CharacterPackUploadRead,
    CharacterPackUser,
)
from marvin.services.ai.character import (
    CharacterError,
    assign_state,
    delete_character_files,
    describe,
    plan_character,
    read_upload_files,
    save_character,
    store_character,
)
from marvin.services.ai.character_library import (
    clean_persona,
    get_pack,
    library_store,
    list_packs,
    pack_usage,
    pack_zip,
    unique_slug,
    unlink_pack,
    with_current_urls,
)
from marvin.services.workspace.current import NO_WORKSPACE, current_workspace_id

router = APIRouter(prefix="/character-packs")

MAX_PACK_NAME = 120
DEFAULT_PACK_NAME = "Character"


def _unprocessable(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


def _pack_json(character: dict) -> dict:
    """What a pack stores: its states and files — its name is the row's."""
    return {"states": character["states"], "files": character["files"]}


@controller(router)
class AdminCharacterPacksController(BaseAdminController):
    def _billed_workspace(self, requested: UUID4 | None) -> UUID4:
        """The workspace an AI call here is billed to: the one asked for, else the caller's current one, else 409."""
        if requested is not None:
            if self.repos.groups.get_one(requested) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That workspace doesn't exist.")
            return requested
        if (current := current_workspace_id(self.user, self.session)) is not None:
            return current
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": NO_WORKSPACE, "message": "Pick a workspace to bill the AI call to."}
        )

    def _pack_or_404(self, ref: str) -> CharacterPackModel:
        pack = get_pack(self.session, ref)
        if pack is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No character pack '{ref}'.")
        return pack

    def _read(self, pack: CharacterPackModel) -> dict:
        return {
            **describe(with_current_urls(pack.pack)),
            "id": str(pack.id),
            "slug": pack.slug,
            "name": pack.name,
            "created_at": pack.created_at,
            "used_by": [CharacterPackUser(**u) for u in pack_usage(self.session, pack.id)],
            "persona": pack.persona or None,
        }

    def _uploads(self, files: list[UploadFile]):
        """The upload's plan and, for a complete pack, its cleaned persona — both checked before anything is stored."""
        try:
            plan = plan_character(read_upload_files(files))
            return plan, clean_persona(plan.persona)
        except CharacterError as e:
            raise _unprocessable(e) from None

    @router.get("", response_model=list[CharacterPackRead], summary="Admin: List Character Packs")
    def list_character_packs(self) -> list[CharacterPackRead]:
        """Every pack in the library, with the workspaces and agents using each."""
        return [CharacterPackRead(**self._read(p)) for p in list_packs(self.session)]

    @router.post("", response_model=CharacterPackUploadRead, status_code=status.HTTP_201_CREATED, summary="Admin: Add Character Pack")
    def create_pack(self, name: str = Form(""), files: list[UploadFile] = File(...)) -> CharacterPackUploadRead:
        """A new pack from a .zip or loose GIF/WebP/PNG files, one per state by name (as a workspace upload) — or
        from a complete pack's .zip (one this library downloaded), whose character.json gives its name, states
        and persona."""
        plan, persona = self._uploads(files)
        name = name.strip() or plan.name or DEFAULT_PACK_NAME
        if len(name) > MAX_PACK_NAME:
            raise _unprocessable(ValueError(f"a pack's name is at most {MAX_PACK_NAME} characters"))
        pack_id = uuid.uuid4()
        store = library_store(pack_id)
        character = store_character(store, plan)
        pack = CharacterPackModel(
            session=self.session,
            slug=unique_slug(self.session, plan.slug or name),
            name=name,
            pack=_pack_json(character),
            persona=persona,
            created_by=self.user.id,
        )
        pack.id = pack_id  # the files are already stored under it
        self.session.add(pack)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            delete_character_files(store, character)
            raise
        self.logger.info("Character pack %s added", pack.slug)
        return CharacterPackUploadRead(
            **self._read(pack), ignored=plan.ignored, idle_guessed=plan.idle_guessed, cleared=plan.cleared, built_from=plan.built_from
        )

    @router.post("/{pack_ref}", response_model=CharacterPackUploadRead, summary="Admin: Replace a Character Pack's Files")
    def replace_pack_files(self, pack_ref: str, files: list[UploadFile] = File(...)) -> CharacterPackUploadRead:
        """New animations for an existing pack; everyone using it gets them. Its old files are deleted. A complete
        pack's .zip also brings its name and persona (its slug stays)."""
        pack = self._pack_or_404(pack_ref)
        plan, persona = self._uploads(files)
        if plan.from_manifest:
            pack.name = (plan.name or pack.name)[:MAX_PACK_NAME]
            pack.persona = persona
        store = library_store(pack.id)
        save_character(self.session, pack, "pack", _pack_json(store_character(store, plan)), store)
        return CharacterPackUploadRead(
            **self._read(pack), ignored=plan.ignored, idle_guessed=plan.idle_guessed, cleared=plan.cleared, built_from=plan.built_from
        )

    @router.patch("/{pack_ref}", response_model=CharacterPackRead, summary="Admin: Update a Character Pack")
    def update_pack(self, pack_ref: str, data: CharacterPackUpdate) -> CharacterPackRead:
        """Rename it (its slug stays, so nothing referring to it breaks) and/or save its character sheet — the
        persona a workspace or agent copies when it picks the pack (null clears it). Those already using the
        pack keep their copy until they pick it again or reset to it."""
        pack = self._pack_or_404(pack_ref)
        if data.name is not None:
            pack.name = data.name.strip() or pack.name
        if "persona" in data.model_fields_set:
            try:
                pack.persona = clean_persona(data.persona.model_dump() if data.persona else None)
            except CharacterError as e:
                raise _unprocessable(e) from None
        self.session.commit()
        return CharacterPackRead(**self._read(pack))

    @router.post("/{pack_ref}/bubble-lines/generate", response_model=BubbleLines, summary="Admin: Write a Character Pack's Bubble Lines")
    def generate_pack_lines(self, pack_ref: str, data: CharacterPackLinesRequest | None = None) -> BubbleLines:
        """Write the pack's bubble lines from its Character with one model call, billed to `workspaceId` (else your
        current workspace; with neither, 409 `no_workspace`: pick one to bill), and return them unsaved — the character
        sheet fills them in for you to edit and save. `personaPrompt` / `assistantName` stand in for the stored ones
        (the sheet's unsaved fields)."""
        from marvin.services.ai.bubble_lines import NO_CHARACTER, BubbleLinesError, ready_to_write, write_lines

        pack = self._pack_or_404(pack_ref)
        stored = pack.persona or {}
        sent = data.model_fields_set if data else set()
        persona = (data.persona_prompt if "persona_prompt" in sent else stored.get("persona_prompt")) or ""
        name = (data.assistant_name if "assistant_name" in sent else stored.get("assistant_name")) or pack.name
        if not persona.strip():
            raise _unprocessable(ValueError(NO_CHARACTER))
        workspace_id = self._billed_workspace(data.workspace_id if data else None)
        if reason := ready_to_write(self.session, workspace_id):
            code = status.HTTP_429_TOO_MANY_REQUESTS if reason.startswith("AI budget") else status.HTTP_422_UNPROCESSABLE_ENTITY
            raise HTTPException(status_code=code, detail=reason)
        try:
            lines = write_lines(self.session, workspace_id, name.strip(), persona, self.user.id, source="character_library")
        except BubbleLinesError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from None
        return BubbleLines(**lines)

    @router.get("/{pack_ref}/download", summary="Admin: Download a Character Pack", response_class=Response)
    def download_pack(self, pack_ref: str) -> Response:
        """The whole pack as one .zip — its images and a character.json with its states and persona — which
        Add (or Replace) takes back as is, here or in another Marvin."""
        pack = self._pack_or_404(pack_ref)
        try:
            data = pack_zip(pack)
        except Exception as e:  # a file's provider is gone or unreadable: say which pack, not a bare 500
            self.logger.warning("Character pack %s: download failed: %s", pack.slug, e)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"{pack.name}'s files couldn't all be read ({e}).") from None
        headers = {"Content-Disposition": f'attachment; filename="{pack.slug}.zip"'}
        return Response(content=data, media_type="application/zip", headers=headers)

    @router.put("/{pack_ref}/states", response_model=CharacterPackRead, summary="Admin: Assign a Character Pack State")
    def assign_pack_state(self, pack_ref: str, data: AssistantCharacterAssign) -> CharacterPackRead:
        """Play one of the pack's files for a state, or clear the state (it falls back) with file=null."""
        pack = self._pack_or_404(pack_ref)
        try:
            character = assign_state(pack.pack, data.state, data.file)
        except CharacterError as e:
            raise _unprocessable(e) from None
        save_character(self.session, pack, "pack", character, library_store(pack.id))
        return CharacterPackRead(**self._read(pack))

    @router.delete("/{pack_ref}", status_code=status.HTTP_204_NO_CONTENT, summary="Admin: Delete a Character Pack")
    def delete_pack(self, pack_ref: str, force: bool = Query(False)) -> None:
        """Refused while any workspace or agent uses the pack — the 409 names them — rather than quietly
        taking their character away. `force=true` is the admin's informed "delete anyway": those users
        fall back (a workspace to its icon, an agent to the workspace's character), then the pack and its
        files go."""
        pack = self._pack_or_404(pack_ref)
        users = pack_usage(self.session, pack.id)
        if users and force:
            self.logger.info("Character pack %s: unlinked from %d user(s) before deleting", pack_ref, unlink_pack(self.session, pack.id))
        elif users:
            who = ", ".join(f"{u['workspace']} (agent {u['agent']})" if u["agent"] else u["workspace"] for u in users)
            detail = f"{pack.name} is in use by {who} — they must choose another character first."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        files, store = pack.pack, library_store(pack.id)
        self.session.delete(pack)
        self.session.commit()
        delete_character_files(store, files)
        self.logger.info("Character pack %s deleted", pack_ref)
