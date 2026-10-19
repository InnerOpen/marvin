"""The platform's character library (services/ai/character_library.py, /api/admin/character-packs) and
per-agent bubble characters (/api/ai/agents/{slug}/character).

A platform admin installs packs once; workspaces and agents point at one by id ({"library": id}) or keep
their own upload. A pack's files live under a platform storage prefix, never in a workspace's assets,
and a pack anyone still uses can't be deleted.
"""

import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from marvin.services.storage.keys import LIBRARY_CODE, is_opaque
from tests import character_images as images
from tests._users import member_of


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("P", (2, 2)).save(buf, "GIF")
    return buf.getvalue()


def _files(*names: str) -> list[UploadFile]:
    return [UploadFile(io.BytesIO(_gif()), filename=n) for n in names]


def _bind(cls, target, *names):
    """The controller's real methods, bound to a stand-in that carries just what they read."""
    for name in names:
        setattr(target, name, getattr(cls, name).__get__(target))


def _stored(root) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} if root.exists() else set()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Local storage under tmp_path, standing in for the configured provider everywhere."""
    from marvin.services.storage import provider_factory
    from marvin.services.storage.local_provider import LocalStorageProvider

    store = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
    monkeypatch.setattr(provider_factory, "get_storage_provider", lambda *a, **k: store)
    return store


@pytest.fixture
def workspace(db_session):
    """A throwaway workspace with an admin user; it and anything made for it are cleaned up after."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.platform import Assets, CharacterPackModel
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"Lib {marker}", slug=f"lib-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    # A core insert: the ORM Users.__init__ has side effects (notifier seeding) a unit test doesn't want.
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Test User",
            username=f"u-{marker}",
            email=f"u-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    db_session.commit()
    yield gid, uid
    db_session.rollback()
    db_session.query(WorkspaceAgentModel).filter_by(group_id=gid).delete()
    db_session.query(Assets).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(CharacterPackModel).filter_by(created_by=uid).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def admin(db_session, workspace, storage):
    """The library admin controller's methods, as a platform admin."""
    import logging

    from marvin.routes.admin.character_packs_controller import AdminCharacterPacksController as C

    # the admin's current workspace pays for writing a pack's lines
    user = SimpleNamespace(id=workspace[1], active_group_id=workspace[0], group_id=workspace[0], **member_of(workspace[0]))
    c = SimpleNamespace(session=db_session, user=user, logger=logging.getLogger("test"))
    _bind(C, c, "_pack_or_404", "_read", "_uploads", "_billed_workspace")
    c.create = lambda *names, name="": C.create_pack(c, name=name, files=_files(*names))
    c.replace = lambda ref, *names: C.replace_pack_files(c, ref, _files(*names))
    c.rename = lambda ref, name: C.update_pack(c, ref, _update(name))
    c.save_persona = lambda ref, persona: C.update_pack(c, ref, _persona_update(persona))
    c.create_from = lambda filename, data, name="": C.create_pack(c, name=name, files=[UploadFile(io.BytesIO(data), filename=filename)])
    c.replace_from = lambda ref, filename, data: C.replace_pack_files(c, ref, [UploadFile(io.BytesIO(data), filename=filename)])
    c.download = lambda ref: C.download_pack(c, ref)
    c.generate = lambda ref, **kw: C.generate_pack_lines(c, ref, _pack_lines(**kw) if kw else None)
    c.assign = lambda ref, state, file: C.assign_pack_state(c, ref, _assign(state, file))
    c.delete = lambda ref, force=False: C.delete_pack(c, ref, force=force)
    c.list = lambda: C.list_character_packs(c)
    return c


@pytest.fixture
def settings(db_session, workspace, storage):
    """The workspace AI settings controller's character methods."""
    import logging

    from marvin.repos.all_repositories import get_repositories
    from marvin.routes.groups.ai_settings_controller import AISettingsController as C

    gid, uid = workspace
    repos = get_repositories(db_session, group_id=gid)
    c = SimpleNamespace(session=db_session, group_id=gid, user=SimpleNamespace(id=uid), repos=repos, logger=logging.getLogger("test"))
    c._require_admin = lambda: None
    c._allow_workspace_credentials = lambda: True
    _bind(C, c, "_settings_row", "_asset_service", "_character_store", "_effective_character", "_described", "get_ai_settings")
    c.reset = lambda: C.reset_persona(c)
    c.get = lambda: C.get_ai_settings(c)
    c.upload = lambda *names: C.upload_character(c, _files(*names))
    c.use_library = lambda pack: C.use_library_character(c, _choice(pack))
    c.assign = lambda state, file: C.assign_character_state(c, _assign(state, file))
    c.patch = lambda **kw: C.update_ai_settings(c, _settings_update(**kw))
    c.library = lambda: C.character_library(c)
    return c


@pytest.fixture
def agents(db_session, workspace, storage):
    """The agents controller's character methods, and a custom agent `scout` to give a character."""
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.repos.all_repositories import get_repositories
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    gid, uid = workspace
    db_session.add(WorkspaceAgentModel(session=db_session, group_id=gid, slug="scout", name="Scout"))
    db_session.commit()
    c = SimpleNamespace(session=db_session, group_id=gid, user=SimpleNamespace(id=uid, admin=True), repos=get_repositories(db_session, group_id=gid))
    c._require_role = lambda *a: None
    _bind(C, c, "_agent_row_or_404", "_agent_or_404", "_character_store", "_agent_character", "_character_admin_row", "_save_agent_character")
    c._agent_read = C._agent_read
    c._record_agent_change = lambda *a: None  # the Event Log line an agent edit adds: see test_agent_edit_events
    c.upload = lambda slug, *names: C.upload_agent_character(c, slug, _files(*names))
    c.use_library = lambda slug, pack: C.use_agent_library_character(c, slug, _choice(pack))
    c.assign = lambda slug, state, file: C.assign_agent_character_state(c, slug, _assign(state, file))
    c.remove = lambda slug: C.delete_agent_character(c, slug)
    c.delete_agent = lambda slug: C.delete_agent(c, slug)
    c.get = lambda slug: C.get_agent(c, slug)
    c.list = lambda: C.list_agents(c)
    c.reset = lambda slug: C.reset_agent_persona(c, slug)
    _bind(C, c, "_require_known_tone", "_tones")
    c._is_builtin, c._agent_edit_message = C._is_builtin, C._agent_edit_message
    c.update = lambda slug, **kw: C.update_agent(c, slug, _agent_update(**kw))
    c.generate = lambda slug, **kw: C.generate_agent_lines(c, slug, _agent_lines(**kw) if kw else None)
    return c


def _update(name):
    from marvin.schemas.platform.character_packs import CharacterPackUpdate

    return CharacterPackUpdate(name=name)


def _pack_lines(**kw):
    from marvin.schemas.platform.character_packs import CharacterPackLinesRequest

    return CharacterPackLinesRequest(**kw)


def _agent_update(**kw):
    from marvin.schemas.group.agent import AgentUpdate

    return AgentUpdate(**kw)


def _agent_lines(**kw):
    from marvin.schemas.group.agent import AgentLinesRequest

    return AgentLinesRequest(**kw)


def _persona_update(persona):
    from marvin.schemas.platform.character_packs import CharacterPackUpdate

    return CharacterPackUpdate(persona=persona)


def _assign(state, file):
    from marvin.schemas.group.ai_settings import AssistantCharacterAssign

    return AssistantCharacterAssign(state=state, file=file)


def _choice(pack):
    from marvin.schemas.group.ai_settings import AssistantCharacterLibraryChoice

    return AssistantCharacterLibraryChoice(pack=pack)


def _settings_update(**kw):
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    return WorkspaceAISettingsUpdate(**kw)


def _asset_ids(db_session, gid) -> set[str]:
    from marvin.db.models.platform import Assets

    db_session.expire_all()
    return {str(a.id) for a in db_session.query(Assets).filter_by(group_id=gid)}


# --- the library (admin) --------------------------------------------------------------------------


def test_a_pack_upload_stores_its_files_under_the_platform_prefix_not_as_assets(admin, storage, db_session, workspace):
    pack = admin.create("idle.gif", "waving.gif", "extra.gif", name="Robot")
    assert set(pack.states) == {"idle", "greeting"} and [f.name for f in pack.files] == ["idle.gif", "waving.gif", "extra.gif"]
    stored = _stored(storage.root)
    # Opaque keys under the platform's prefix: neither the pack nor the file names appear in them.
    assert len(stored) == 3 and all(is_opaque(k, LIBRARY_CODE) and str(pack.id) not in k and "idle" not in k for k in stored)
    assert all(f.url.startswith(f"/assets/{LIBRARY_CODE}/") for f in pack.files)  # served like asset files
    assert _asset_ids(db_session, workspace[0]) == set()


def test_pack_slugs_are_unique_and_survive_a_rename(admin):
    first, second = admin.create("idle.gif", name="Robot"), admin.create("idle.gif", name="Robot")
    assert (first.slug, second.slug) == ("robot", "robot-2")
    renamed = admin.rename(first.id, "Tin Man")
    assert (renamed.name, renamed.slug) == ("Tin Man", "robot")


def test_a_pack_state_is_assigned_by_file_name(admin):
    pack = admin.create("idle.gif", "extra.gif", name="Robot")
    extra = next(f for f in pack.files if f.name == "extra.gif")
    assert admin.assign(pack.slug, "success", "extra.gif").states["success"] == extra.url
    assert "success" not in admin.assign(pack.slug, "success", None).states


def test_replacing_a_packs_files_deletes_the_old_ones(admin, storage):
    pack = admin.create("idle.gif", "extra.gif", name="Robot")
    before = _stored(storage.root)
    replaced = admin.replace(pack.id, "idle.gif")
    after = _stored(storage.root)
    assert replaced.id == pack.id and [f.name for f in replaced.files] == ["idle.gif"]
    assert len(after) == 1 and not after & before


def test_deleting_an_unused_pack_removes_it_and_its_files(admin, storage):
    pack = admin.create("idle.gif", name="Robot")
    admin.delete(pack.id)
    assert all(p.id != pack.id for p in admin.list())
    assert _stored(storage.root) == set()


def test_deleting_a_pack_in_use_is_refused_naming_who_uses_it(admin, settings, agents, storage):
    pack = admin.create("idle.gif", name="Robot")
    settings.use_library(pack.slug)
    agents.use_library("scout", pack.id)
    with pytest.raises(HTTPException) as exc:
        admin.delete(pack.id)
    assert exc.value.status_code == 409
    assert "Lib " in exc.value.detail and "agent scout" in exc.value.detail
    assert len(_stored(storage.root)) == 1  # nothing was taken away
    listed = next(p for p in admin.list() if p.id == pack.id)
    assert sorted(u.agent or "" for u in listed.used_by) == ["", "scout"]


def test_force_deleting_a_pack_in_use_unlinks_its_users_first(admin, settings, agents, storage):
    # The admin's informed "delete anyway": users fall back (workspace → icon, agent → workspace's character).
    pack = admin.create("idle.gif", name="Robot")
    settings.use_library(pack.slug)
    agents.use_library("scout", pack.id)

    admin.delete(pack.id, force=True)

    assert all(p.id != pack.id for p in admin.list())
    assert settings._settings_row().assistant_character is None
    assert next(a for a in agents.list() if a.slug == "scout").character is None
    assert _stored(storage.root) == set()


def test_the_library_admin_routes_refuse_a_workspace_admin(client):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role="NONE", is_superuser=False, admin=True)
    try:
        assert client.get("/api/admin/character-packs").status_code == 403
        assert client.delete(f"/api/admin/character-packs/{uuid.uuid4()}").status_code == 403
        assert client.get(f"/api/admin/character-packs/{uuid.uuid4()}/download").status_code == 403
        assert client.post(f"/api/admin/character-packs/{uuid.uuid4()}/bubble-lines/generate").status_code == 403
        assert client.patch(f"/api/admin/character-packs/{uuid.uuid4()}", json={"persona": None}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# --- a workspace choosing a pack ------------------------------------------------------------------


def test_a_workspace_picking_a_pack_plays_its_states_and_drops_its_own_upload(admin, settings, db_session, workspace):
    settings.upload("idle.gif", "waving.gif")
    pack = admin.create("idle.gif", "jumping.gif", name="Robot")
    chosen = settings.use_library(pack.slug)
    assert (chosen.library, chosen.name, set(chosen.states)) == (pack.id, "Robot", {"idle", "success"})
    assert _asset_ids(db_session, workspace[0]) == set()  # the own upload's assets are gone
    assert settings._settings_row().assistant_character == {"library": pack.id}  # stored by id, not copied
    # The bubble reads the settings: the pack's states, as the admin re-picks them.
    admin.assign(pack.id, "greeting", "jumping.gif")
    assert set(settings.get().assistant_character["states"]) == {"idle", "success", "greeting"}


def test_the_settings_patch_takes_a_library_pack_by_slug(admin, settings):
    pack = admin.create("idle.gif", name="Robot")
    assert settings.patch(assistant_character={"library": pack.slug}).assistant_character["library"] == pack.id


def test_an_unknown_library_pack_is_a_422(settings):
    for call in (lambda: settings.use_library("nope"), lambda: settings.patch(assistant_character={"library": "nope"})):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 422


def test_a_library_characters_states_are_not_the_workspaces_to_change(admin, settings):
    settings.use_library(admin.create("idle.gif", name="Robot").id)
    with pytest.raises(HTTPException) as exc:
        settings.assign("success", "idle.gif")
    assert exc.value.status_code == 422


def test_uploading_after_a_library_pack_replaces_it_and_leaves_the_pack_alone(admin, settings, storage):
    pack = admin.create("idle.gif", name="Robot")
    settings.use_library(pack.id)
    own = settings.upload("idle.gif")
    assert own.library is None and len(own.files) == 1
    assert any(is_opaque(k, LIBRARY_CODE) for k in _stored(storage.root))


def test_any_member_reads_the_library_to_choose_from(admin, settings):
    pack = admin.create("idle.gif", "waving.gif", name="Robot")
    listed = next(p for p in settings.library() if p.id == pack.id)
    assert (listed.slug, set(listed.states)) == ("robot", {"idle", "greeting"}) and "thinking" in listed.missing


# --- agents ---------------------------------------------------------------------------------------


def test_an_agent_gets_its_own_uploaded_character(agents, db_session, workspace):
    up = agents.upload("scout", "idle.gif", "running.gif")
    assert set(up.states) == {"idle", "working"}
    assert {f.asset_id for f in up.files} == _asset_ids(db_session, workspace[0])  # stored as workspace assets
    assert agents.get("scout").character.states == up.states
    assert agents.assign("scout", "success", "running.gif").states["success"] == up.states["working"]


def test_an_agent_with_a_library_pack_lists_with_that_packs_states(admin, agents):
    pack = admin.create("idle.gif", "waving.gif", name="Robot")
    agents.use_library("scout", pack.slug)
    scout = next(a for a in agents.list() if a.slug == "scout")
    assert (scout.character.library, set(scout.character.states)) == (pack.id, {"idle", "greeting"})


def test_removing_or_deleting_an_agent_deletes_its_own_character_files(agents, db_session, workspace):
    agents.upload("scout", "idle.gif")
    agents.remove("scout")
    assert agents.get("scout").character is None and _asset_ids(db_session, workspace[0]) == set()
    agents.upload("scout", "idle.gif")
    agents.delete_agent("scout")
    assert _asset_ids(db_session, workspace[0]) == set()


def test_system_agents_carry_no_character_and_cannot_be_given_one(agents):
    # Built-ins are code, not rows: `marvin` plays the workspace's character, ask/chat fall back to it.
    assert all(a.character is None for a in agents.list() if a.is_system)
    for slug in ("marvin", "ask", "chat"):
        with pytest.raises(HTTPException) as exc:
            agents.upload(slug, "idle.gif")
        assert exc.value.status_code == 400


def test_the_settings_the_bubble_reads_carry_each_agents_character(admin, settings, agents):
    pack = admin.create("idle.gif", "waving.gif", name="Robot")
    assert settings.get().agent_characters == {}
    agents.use_library("scout", pack.id)
    assert set(settings.get().agent_characters["scout"]) == {"idle", "greeting"}


# --- solid backgrounds ----------------------------------------------------------------------------


def test_a_pack_upload_lists_the_files_whose_background_was_cleared(admin):
    from marvin.routes.admin.character_packs_controller import AdminCharacterPacksController as C

    files = [UploadFile(io.BytesIO(images.matted_gif()), filename="running.gif"), UploadFile(io.BytesIO(_gif()), filename="idle.gif")]
    assert C.create_pack(admin, name="Boxed", files=files).cleared == ["running.gif"]


def test_an_agent_upload_lists_the_files_whose_background_was_cleared(agents):
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    res = C.upload_agent_character(agents, "scout", [UploadFile(io.BytesIO(images.matted_gif()), filename="idle.gif")])
    assert res.cleared == ["idle.gif"]


@pytest.fixture
def boxed_files(admin, settings, agents, storage, db_session):
    """A library pack, a workspace's own character and an agent's, each with one file stored before uploads
    cleared backgrounds: its stored bytes swapped for a matted GIF behind the controller's back."""
    from marvin.db.models.platform import Assets

    pack = admin.create("idle.gif", "running.gif", name="Old pack")
    own = settings.upload("idle.gif")
    agent = agents.upload("scout", "idle.gif")
    keys = [f.url.removeprefix("/assets/") for f in pack.files if f.name == "running.gif"]
    keys += [db_session.get(Assets, uuid.UUID(c.files[0].asset_id)).storage_key for c in (own, agent)]
    for key in keys:
        storage.put(storage_key=key, file_data=io.BytesIO(images.matted_gif()), content_type="image/gif")
    return keys


def _stored_bytes(storage, key) -> bytes:
    return storage.get(key).read()


def test_the_matte_repair_dry_run_reports_but_writes_nothing(boxed_files, storage, db_session):
    from marvin.scripts.repair_character_mattes import repair_stored_mattes

    repairs = repair_stored_mattes(db_session, storage)
    assert {r.key for r in repairs if not r.error} >= set(boxed_files)
    assert all(_stored_bytes(storage, key) == images.matted_gif() for key in boxed_files)


def test_the_matte_repair_overwrites_each_file_in_place(boxed_files, storage, db_session):
    from marvin.db.models.platform import Assets
    from marvin.scripts.repair_character_mattes import repair_stored_mattes

    repair_stored_mattes(db_session, storage, apply=True)
    assert all(f.getpixel((0, 0))[3] == 0 for key in boxed_files for f in images.frames_rgba(_stored_bytes(storage, key)))
    asset = db_session.query(Assets).filter_by(storage_key=boxed_files[-1]).one()
    assert asset.file_size == len(_stored_bytes(storage, boxed_files[-1]))
    assert not {r.key for r in repair_stored_mattes(db_session, storage)} & set(boxed_files)  # nothing left to do


# --- where each drawing sits in its frame -------------------------------------------------------------


def test_an_upload_records_where_each_drawing_sits_and_the_bubble_gets_it(settings):
    character = settings.upload("idle.gif", "peek-top.gif")
    assert all(f.get("inset") for f in settings._settings_row().assistant_character["files"])
    insets = settings.get().character_insets
    assert set(insets) == {character.states["idle"], character.states["peek_top"]}
    assert set(next(iter(insets.values()))) == {"top", "right", "bottom", "left"}


def test_a_library_pack_brings_its_insets_without_its_files(admin, settings):
    pack = admin.create("idle.gif", "peek-left.gif", name="Edges")
    settings.use_library(pack.slug)
    got = settings.get()
    assert got.assistant_character["files"] == []
    assert set(got.character_insets) == set(got.assistant_character["states"].values())


def test_the_inset_backfill_measures_files_stored_before_uploads_did(admin, settings, storage, db_session):
    from marvin.db.models.platform import CharacterPackModel
    from marvin.scripts.measure_character_insets import measure_stored_insets

    pack = admin.create("idle.gif", name="Old pack")
    settings.upload("idle.gif")
    row, pack_row = settings._settings_row(), db_session.get(CharacterPackModel, uuid.UUID(str(pack.id)))
    unmeasured = lambda c: {**c, "files": [{k: v for k, v in f.items() if k != "inset"} for f in c["files"]]}  # noqa: E731
    row.assistant_character, pack_row.pack = unmeasured(row.assistant_character), unmeasured(pack_row.pack)
    db_session.commit()

    dry = measure_stored_insets(db_session, storage)
    assert {m.owner.split(" ")[0] for m in dry if m.inset} >= {"library", "workspace"}
    assert not any(f.get("inset") for f in row.assistant_character["files"])  # a dry run records nothing

    measure_stored_insets(db_session, storage, apply=True)
    db_session.refresh(row)
    db_session.refresh(pack_row)
    assert all(f.get("inset") for f in [*row.assistant_character["files"], *pack_row.pack["files"]])
    assert not [m for m in measure_stored_insets(db_session, storage) if m.owner in ("library pack " + pack_row.slug,)]


# --- one character sheet, built into the pack ------------------------------------------------------


def _sheet_upload(name: str, sheet: Image.Image) -> list[UploadFile]:
    return [UploadFile(io.BytesIO(images.png_bytes(sheet)), filename=name)]


def test_a_pose_sheet_uploaded_to_the_library_becomes_a_whole_pack(admin):
    from marvin.routes.admin.character_packs_controller import AdminCharacterPacksController as C
    from marvin.services.ai.character import CHARACTER_STATES

    pack = C.create_pack(admin, name="Mossy", files=_sheet_upload("Mossy’s 16-pose grid.png", images.pose_sheet()))
    assert pack.built_from == "16-pose sheet (height 108)" and pack.name == "Mossy"
    assert set(pack.states) == set(CHARACTER_STATES) and pack.missing == [] and not pack.idle_guessed
    assert all(f.get("inset") for f in admin._pack_or_404(pack.id).pack["files"])  # measured, so a peek's ledge lines up with the screen edge
    assert pack.model_dump(by_alias=True)["builtFrom"] == pack.built_from


def test_a_pet_sheet_uploaded_by_a_workspace_or_an_agent_becomes_its_character(settings, agents):
    from marvin.routes.ai.operations_controller import AIOperationsController as C

    own = C.upload_agent_character(agents, "scout", _sheet_upload("hoots-spritesheet.webp", images.pet_sheet()))
    assert own.built_from.startswith("ChatGPT pet sheet") and {"peek_left", "peek_top", "idle_variant"} <= set(own.states)
    character = settings.upload("idle.gif")  # an ordinary upload says nothing was built
    assert character.built_from is None


# --- a pack's persona: its character sheet, copied on pick ----------------------------------------

ELVIRA = {
    "assistantName": "Elvira",
    "personaPrompt": "You are Elvira, Mistress of the Dark: campy, warm, wicked puns.",
    "bubbleLines": {"greetings": ["  Well, hello there.  ", ""], "taglines": ["unpleasant dreams"], "emotes": ["*flips hair*"]},
    "defaultRegister": "playful",
    "icon": "🦇",
    "mood": {"drains": "treatment", "meter": "hidden", "low": {"greetings": ["Mm-hmm."]}},
}


@pytest.fixture
def started(monkeypatch):
    """Background line generations asked for, instead of running them."""
    from marvin.services.ai import bubble_lines

    calls = []
    monkeypatch.setattr(bubble_lines, "start", lambda group_id, user_id=None, **kw: calls.append(group_id) or True)
    return calls


def _elvira(admin, sheet=ELVIRA):
    pack = admin.create("idle.gif", "waving.gif", name="Elvira")
    return admin.save_persona(pack.slug, sheet)


def test_a_packs_character_sheet_is_saved_cleaned(admin):
    persona = _elvira(admin).persona
    assert (persona.assistant_name, persona.default_register, persona.icon) == ("Elvira", "playful", "🦇")
    assert persona.bubble_lines.greetings == ["Well, hello there."] and persona.bubble_lines.thinking == []
    assert persona.mood.drains == "treatment" and persona.mood.low.greetings == ["Mm-hmm."] and persona.mood.high is None


def test_clearing_a_packs_character_sheet_leaves_it_animations_only(admin):
    pack = _elvira(admin)
    assert admin.save_persona(pack.slug, None).persona is None


def test_a_character_sheet_takes_only_a_built_in_tone(admin):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="auto, professional, playful"):
        _persona_update({**ELVIRA, "defaultRegister": "pirate"})


def test_a_character_sheet_icon_is_an_emoji_not_a_url(admin):
    pack = admin.create("idle.gif", name="Elvira")
    with pytest.raises(HTTPException) as e:
        admin.save_persona(pack.slug, {"icon": "http://a.b/c.png"})
    assert e.value.status_code == 422


def test_picking_a_pack_makes_the_workspace_that_character(admin, settings, started):
    settings.patch(assistant_name="Marvin", persona_prompt="A gloomy robot.")
    started.clear()
    settings.use_library(_elvira(admin).slug)
    got = settings.get()
    assert (got.assistant_name, got.persona_prompt, got.default_register, got.assistant_icon) == ("Elvira", ELVIRA["personaPrompt"], "playful", "🦇")
    assert got.bubble_lines.greetings == ["Well, hello there."] and got.bubble_lines_source == "character"
    assert got.mood.drains == "treatment"
    assert started == []  # the pack brought its own lines


def test_picking_a_pack_with_a_character_but_no_lines_has_them_written(admin, settings, started):
    settings.use_library(_elvira(admin, {"personaPrompt": "You are Elvira."}).slug)
    assert settings.get().bubble_lines is None and started == [settings.group_id]


def test_picking_a_pack_without_a_character_sheet_takes_its_name_and_keeps_the_rest(admin, settings, started):
    settings.patch(assistant_name="Ada", persona_prompt="Warm and direct.")
    settings.use_library(admin.create("idle.gif", name="Robot").slug)
    got = settings.get()
    assert (got.assistant_name, got.persona_prompt) == ("Robot", "Warm and direct.")


def test_an_agent_picking_a_pack_without_a_sheet_is_named_after_it(admin, agents):
    agents.update("scout", persona_prompt="Terse.")
    agents.use_library("scout", admin.create("idle.gif", name="Night Shift").slug)
    agent = agents.get("scout")
    assert (agent.name, agent.persona_prompt) == ("Night Shift", "Terse.")


def test_reset_to_a_pack_without_a_sheet_is_a_409_and_renames_nothing(admin, settings, db_session):
    settings.use_library(admin.create("idle.gif", name="Robot").slug)
    settings.patch(assistant_name="Ada")
    with pytest.raises(HTTPException) as e:
        settings.reset()
    db_session.rollback()
    assert e.value.status_code == 409 and settings.get().assistant_name == "Ada"


def test_the_settings_patch_picking_a_pack_copies_it_but_explicit_fields_win(admin, settings, started):
    pack = _elvira(admin)
    got = settings.patch(assistant_character={"library": pack.slug}, assistant_name="Vira")
    assert (got.assistant_name, got.persona_prompt) == ("Vira", ELVIRA["personaPrompt"])


def test_any_member_sees_each_packs_persona_to_choose_from(admin, settings):
    _elvira(admin)
    listed = {p.name: p for p in settings.library()}
    assert listed["Elvira"].persona.assistant_name == "Elvira"


def test_reset_copies_the_packs_persona_in_again(admin, settings, started):
    settings.use_library(_elvira(admin).slug)
    settings.patch(assistant_name="Vira", persona_prompt="Someone else entirely.")
    got = settings.reset()
    assert (got.assistant_name, got.persona_prompt, got.bubble_lines_source) == ("Elvira", ELVIRA["personaPrompt"], "character")


def test_reset_without_a_library_character_is_a_409(settings):
    settings.upload("idle.gif")
    with pytest.raises(HTTPException) as e:
        settings.reset()
    assert e.value.status_code == 409


def test_a_character_edit_rewrites_a_packs_lines_but_never_edited_ones(admin, settings, started, db_session):
    from marvin.services.ai.bubble_lines import SOURCE_EDITED, store

    settings.use_library(_elvira(admin).slug)
    settings.patch(persona_prompt="Elvira, but on a diet of puns.")
    assert started == [settings.group_id]
    store(settings._settings_row(), {"greetings": ["mine"]}, SOURCE_EDITED)
    db_session.commit()
    settings.patch(persona_prompt="Elvira, unpunned.")
    assert started == [settings.group_id] and settings.get().bubble_lines.greetings == ["mine"]


def test_the_workspace_saves_its_own_mood_settings(settings):
    assert settings.patch(mood={"memory": "weeks", "absence": "cools"}).mood.model_dump(exclude_none=True) == {"memory": "weeks", "absence": "cools"}
    assert settings.patch(mood={}).mood is None


def test_an_agent_picking_a_pack_becomes_that_character(admin, agents):
    agents.use_library("scout", _elvira(admin).slug)
    agent = agents.get("scout")
    assert (agent.name, agent.persona_prompt, agent.default_register, agent.icon) == ("Elvira", ELVIRA["personaPrompt"], "playful", "🦇")
    assert agent.bubble_lines.taglines == ["unpleasant dreams"] and agent.bubble_lines_source == "character"
    assert agent.mood.meter == "hidden"


def test_an_agent_reset_copies_its_packs_persona_in_again(admin, agents, db_session, workspace):
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    agents.use_library("scout", _elvira(admin).slug)
    row = db_session.query(WorkspaceAgentModel).filter_by(group_id=workspace[0], slug="scout").one()
    row.name, row.persona_prompt = "Scout", "Terse."
    db_session.commit()
    assert (agents.reset("scout").name, agents.get("scout").persona_prompt) == ("Elvira", ELVIRA["personaPrompt"])


def test_an_agent_reset_without_a_library_character_is_a_409(agents):
    with pytest.raises(HTTPException) as e:
        agents.reset("scout")
    assert e.value.status_code == 409


def test_the_bubble_gets_each_agents_name_and_lines(admin, settings, agents):
    agents.use_library("scout", _elvira(admin).slug)
    voice = settings.get().agent_voices["scout"]
    assert voice.name == "Elvira" and voice.bubble_lines.greetings == ["Well, hello there."]


def test_the_bubble_reads_each_agents_voice_in_camel_case_like_the_rest(admin, settings, agents):
    """Regression (2026-10-16, seen live): the voices went out as raw dicts (`bubble_lines`), so the bubble swapped
    the name but found no lines and fell back to neutral ones."""
    agents.use_library("scout", _elvira(admin).slug)
    dumped = settings.get().model_dump(by_alias=True, mode="json")
    assert dumped["agentVoices"]["scout"]["bubbleLines"]["taglines"] == ["unpleasant dreams"]


def test_an_agent_without_a_voice_of_its_own_speaks_as_the_workspace(settings, agents):
    assert "scout" not in settings.get().agent_voices


# --- the portable pack file -------------------------------------------------------------------------


def _zip(entries: dict[str, bytes]) -> bytes:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return out.getvalue()


def _manifest(**overrides) -> bytes:
    import json

    manifest = {"format": "marvin-character/1", "name": "Ada", "states": {"idle": "a.gif", "success": "b.gif"}, **overrides}
    return json.dumps(manifest).encode()


def _by_file(pack) -> dict[str, str]:
    """{state: file name}: a pack's states, independent of where its files are stored."""
    names = {f.url: f.name for f in pack.files}
    return {state: names[url] for state, url in pack.states.items()}


def test_a_downloaded_pack_uploads_back_as_the_same_pack(admin, storage, db_session):
    import zipfile

    pack = _elvira(admin)
    admin.assign(pack.slug, "success", "waving.gif")  # an assignment no file name would guess
    pack = admin.assign(pack.slug, "idle_variant", "idle.gif")
    insets = {f.name: f.inset for f in admin._pack_or_404(pack.slug).pack["files"] for f in [SimpleNamespace(**f)]}
    data = admin.download(pack.slug).body
    assert set(zipfile.ZipFile(io.BytesIO(data)).namelist()) == {"idle.gif", "waving.gif", "character.json"}
    admin.delete(pack.slug)

    back = admin.create_from("anything.zip", data)
    assert (back.name, back.slug) == ("Elvira", pack.slug)
    assert _by_file(back) == _by_file(pack) and back.persona == pack.persona
    assert {f["name"]: f.get("inset") for f in admin._pack_or_404(back.slug).pack["files"]} == insets


def test_a_complete_packs_states_are_taken_as_written_not_guessed(admin):
    pack = admin.create_from("ada.zip", _zip({"a.gif": _gif(), "b.gif": _gif(), "waving.gif": _gif(), "character.json": _manifest()}))
    assert _by_file(pack) == {"idle": "a.gif", "success": "b.gif"} and not pack.idle_guessed


def test_replacing_with_a_complete_pack_brings_its_name_and_persona(admin):
    pack = admin.create("idle.gif", name="Robot")
    manifest = _manifest(persona={"personaPrompt": "You are Ada.", "icon": "🧁"})
    replaced = admin.replace_from(pack.slug, "ada.zip", _zip({"a.gif": _gif(), "b.gif": _gif(), "character.json": manifest}))
    assert (replaced.name, replaced.slug, replaced.persona.persona_prompt, replaced.persona.icon) == ("Ada", "robot", "You are Ada.", "🧁")


def test_a_zip_without_a_manifest_is_read_as_before(admin):
    pack = admin.create_from("Hoots.zip", _zip({"waving.gif": _gif(), "jump.gif": _gif()}))
    assert pack.name == "Hoots" and pack.persona is None and pack.idle_guessed
    assert _by_file(pack) == {"idle": "waving.gif", "greeting": "waving.gif", "success": "jump.gif"}


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (b"x" * (256 * 1024 + 1), "over 256 KB"),
        (b"{not json", "isn't valid JSON"),
        (_manifest(format="marvin-character/2"), "this version of Marvin reads"),
        (_manifest(states={"idle": "a.gif", "dancing": "b.gif"}), "unknown state"),
        (_manifest(states={"idle": "missing.gif"}), "isn't in the pack"),
        (_manifest(insets={"a.gif": {"top": 2}}), "four shares"),
        (_manifest(persona={"defaultRegister": "pirate"}), "tone is one of"),
        (_manifest(persona={"bubbleLines": {"greetings": ["x" * 201]}}), "longer than 200"),
    ],
)
def test_a_bad_manifest_is_refused_before_anything_is_stored(admin, storage, manifest, problem):
    with pytest.raises(HTTPException) as e:
        admin.create_from("ada.zip", _zip({"a.gif": _gif(), "b.gif": _gif(), "character.json": manifest}))
    assert e.value.status_code == 422 and problem in e.value.detail
    assert _stored(storage.root) == set()


def test_a_manifests_unknown_keys_are_ignored(admin):
    assert admin.create_from("ada.zip", _zip({"a.gif": _gif(), "b.gif": _gif(), "character.json": _manifest(sparkles=True)})).name == "Ada"


# --- writing a character's lines, and an agent's own persona fields -------------------------------


@pytest.fixture
def provider(monkeypatch):
    from tests.test_bubble_lines import FakeProvider

    fake = FakeProvider()
    monkeypatch.setattr("marvin.services.ai.factory.get_workspace_ai_provider", lambda session, gid: fake)
    monkeypatch.setattr("marvin.services.ai.authoring.default_authoring_model", lambda session, gid, provider=None: "m")
    return fake


def test_a_packs_lines_are_written_from_the_sheets_unsaved_character_and_not_saved(admin, provider, db_session, workspace):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    pack = admin.create("idle.gif", name="Elvira")
    lines = admin.generate(pack.slug, persona_prompt="You are Elvira.")
    assert lines.greetings and "You are Elvira." in provider.calls[0][1].content and admin.list()[0].persona is None
    runs = db_session.query(AIExecutionModel).filter_by(group_id=workspace[0])
    assert [r.status for r in runs] == ["completed"]  # billed to the admin's workspace
    runs.delete()
    db_session.commit()


def test_a_pack_without_a_character_has_no_lines_to_write(admin, provider):
    with pytest.raises(HTTPException) as e:
        admin.generate(admin.create("idle.gif", name="Elvira").slug)
    assert e.value.status_code == 422 and provider.calls == []


def test_an_agents_lines_are_written_from_its_character(agents, provider, db_session, workspace):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    agents.update("scout", persona_prompt="You are Ada.")
    assert agents.generate("scout").taglines and "You are Ada." in provider.calls[0][1].content
    db_session.query(AIExecutionModel).filter_by(group_id=workspace[0]).delete()
    db_session.commit()


def test_an_agents_own_lines_and_mood_are_saved_as_edited(agents):
    agent = agents.update("scout", bubble_lines={"greetings": [" Howdy ", ""]}, mood={"absence": "recharges"}, persona_prompt="  ")
    assert agent.bubble_lines.greetings == ["Howdy"] and agent.bubble_lines_source == "edited"
    assert agent.mood.absence == "recharges" and agent.persona_prompt is None
    assert agents.update("scout", bubble_lines=None).bubble_lines_source is None


def _mcp_system_prompt(db_session, workspace, monkeypatch, **args) -> str:
    """The system prompt an external client's run_agent call sends for `scout`."""
    import json

    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.users.roles import WorkspaceRole
    from marvin.services.ai import agent as loop_mod
    from marvin.services.ai.tools import ToolContext
    from marvin.services.ai.tools import builtins_agents as ba

    sent: list[str] = []

    def loop(provider, model, messages, tools, opts=None, max_steps=6, **_):
        sent.append(messages[0].content)
        return SimpleNamespace(answer="ok", steps=[], prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def complete(messages, model, opts):
        sent.append(messages[0].content)
        return SimpleNamespace(content="ok", prompt_tokens=0, completion_tokens=0, total_tokens=0)

    monkeypatch.setattr(loop_mod, "run_agent_loop", loop)
    monkeypatch.setattr(ba, "_default_model", lambda ctx: "m")
    gid, uid = workspace
    user = SimpleNamespace(id=uid, admin=False, workspace_memberships=[SimpleNamespace(group_id=gid, workspace_role=WorkspaceRole.ADMIN)])
    ctx = ToolContext(session=db_session, group_id=gid, user=user, provider=SimpleNamespace(provider_type="fake", complete=complete), logger=None)
    out = json.loads(ba._run_standalone(ctx, {"agent": "scout", "message": "hi", **args}))
    assert out.get("answer") == "ok", out
    db_session.query(AIExecutionModel).filter_by(group_id=gid).delete()
    db_session.commit()
    return sent[-1]


ELVIRA_CHARACTER = "Character: You are Elvira, Mistress of the Dark."


def test_an_mcp_run_of_an_agent_is_plain_by_default(agents, db_session, workspace, monkeypatch):
    agents.update("scout", persona_prompt="You are Elvira, Mistress of the Dark.")
    system = _mcp_system_prompt(db_session, workspace, monkeypatch)
    assert "Elvira" not in system and "Write plainly" in system  # professional: the character is dropped


def test_an_mcp_caller_can_ask_for_the_agents_character(agents, db_session, workspace, monkeypatch):
    agents.update("scout", persona_prompt="You are Elvira, Mistress of the Dark.")
    assert ELVIRA_CHARACTER in _mcp_system_prompt(db_session, workspace, monkeypatch, tone="playful")


def test_an_agents_own_default_tone_decides_its_mcp_runs(agents, db_session, workspace, monkeypatch):
    agents.update("scout", persona_prompt="You are Elvira, Mistress of the Dark.", default_register="auto")
    assert ELVIRA_CHARACTER in _mcp_system_prompt(db_session, workspace, monkeypatch)
