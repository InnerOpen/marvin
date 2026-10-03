"""The platform's character library (admin): bubble-character packs any workspace or agent can pick.

A platform admin installs packs here once; workspaces only choose one (AI settings → Persona, Settings
→ Agents) or upload their own. See services/ai/character_library.py.
"""

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from marvin.db.models.platform.character_packs import CharacterPackModel
from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.group.ai_settings import AssistantCharacterAssign
from marvin.schemas.platform.character_packs import CharacterPackRead, CharacterPackUpdate, CharacterPackUploadRead, CharacterPackUser
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
from marvin.services.ai.character_library import get_pack, library_store, list_packs, pack_usage, unique_slug

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
    def _pack_or_404(self, ref: str) -> CharacterPackModel:
        pack = get_pack(self.session, ref)
        if pack is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No character pack '{ref}'.")
        return pack

    def _read(self, pack: CharacterPackModel) -> dict:
        return {
            **describe(pack.pack),
            "id": str(pack.id),
            "slug": pack.slug,
            "name": pack.name,
            "created_at": pack.created_at,
            "used_by": [CharacterPackUser(**u) for u in pack_usage(self.session, pack.id)],
        }

    def _uploads(self, files: list[UploadFile]):
        try:
            uploads = read_upload_files(files)
            return plan_character(uploads)
        except CharacterError as e:
            raise _unprocessable(e) from None

    @router.get("", response_model=list[CharacterPackRead], summary="Admin: List Character Packs")
    def list_character_packs(self) -> list[CharacterPackRead]:
        """Every pack in the library, with the workspaces and agents using each."""
        return [CharacterPackRead(**self._read(p)) for p in list_packs(self.session)]

    @router.post("", response_model=CharacterPackUploadRead, status_code=status.HTTP_201_CREATED, summary="Admin: Add Character Pack")
    def create_pack(self, name: str = Form(""), files: list[UploadFile] = File(...)) -> CharacterPackUploadRead:
        """A new pack from a .zip or loose GIF/WebP/PNG files, one per state by name (as a workspace upload)."""
        plan = self._uploads(files)
        name = name.strip() or plan.name or DEFAULT_PACK_NAME
        if len(name) > MAX_PACK_NAME:
            raise _unprocessable(ValueError(f"a pack's name is at most {MAX_PACK_NAME} characters"))
        pack_id = uuid.uuid4()
        store = library_store(pack_id)
        character = store_character(store, plan)
        pack = CharacterPackModel(
            session=self.session, slug=unique_slug(self.session, name), name=name, pack=_pack_json(character), created_by=self.user.id
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
        return CharacterPackUploadRead(**self._read(pack), ignored=plan.ignored, idle_guessed=plan.idle_guessed)

    @router.post("/{pack_ref}", response_model=CharacterPackUploadRead, summary="Admin: Replace a Character Pack's Files")
    def replace_pack_files(self, pack_ref: str, files: list[UploadFile] = File(...)) -> CharacterPackUploadRead:
        """New animations for an existing pack; everyone using it gets them. Its old files are deleted."""
        pack = self._pack_or_404(pack_ref)
        plan = self._uploads(files)
        store = library_store(pack.id)
        save_character(self.session, pack, "pack", _pack_json(store_character(store, plan)), store)
        return CharacterPackUploadRead(**self._read(pack), ignored=plan.ignored, idle_guessed=plan.idle_guessed)

    @router.patch("/{pack_ref}", response_model=CharacterPackRead, summary="Admin: Rename a Character Pack")
    def rename_pack(self, pack_ref: str, data: CharacterPackUpdate) -> CharacterPackRead:
        """Its slug stays, so nothing referring to it breaks."""
        pack = self._pack_or_404(pack_ref)
        pack.name = data.name.strip() or pack.name
        self.session.commit()
        return CharacterPackRead(**self._read(pack))

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
    def delete_pack(self, pack_ref: str) -> None:
        """Refused while any workspace or agent uses the pack — the 409 names them — rather than quietly
        taking their character away; once they've chosen another, the pack and its files go."""
        pack = self._pack_or_404(pack_ref)
        users = pack_usage(self.session, pack.id)
        if users:
            who = ", ".join(f"{u['workspace']} (agent {u['agent']})" if u["agent"] else u["workspace"] for u in users)
            detail = f"{pack.name} is in use by {who} — they must choose another character first."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        files, store = pack.pack, library_store(pack.id)
        self.session.delete(pack)
        self.session.commit()
        delete_character_files(store, files)
        self.logger.info("Character pack %s deleted", pack_ref)
