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

from marvin.services.ai.character_library import LIBRARY_STORAGE_PREFIX
from tests import character_images as images


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

    c = SimpleNamespace(session=db_session, user=SimpleNamespace(id=workspace[1]), logger=logging.getLogger("test"))
    _bind(C, c, "_pack_or_404", "_read", "_uploads")
    c.create = lambda *names, name="": C.create_pack(c, name=name, files=_files(*names))
    c.replace = lambda ref, *names: C.replace_pack_files(c, ref, _files(*names))
    c.rename = lambda ref, name: C.rename_pack(c, ref, _update(name))
    c.assign = lambda ref, state, file: C.assign_pack_state(c, ref, _assign(state, file))
    c.delete = lambda ref: C.delete_pack(c, ref)
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
    _bind(C, c, "_settings_row", "_asset_service", "_character_store", "_effective_character", "_described")
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
    c.upload = lambda slug, *names: C.upload_agent_character(c, slug, _files(*names))
    c.use_library = lambda slug, pack: C.use_agent_library_character(c, slug, _choice(pack))
    c.assign = lambda slug, state, file: C.assign_agent_character_state(c, slug, _assign(state, file))
    c.remove = lambda slug: C.delete_agent_character(c, slug)
    c.delete_agent = lambda slug: C.delete_agent(c, slug)
    c.get = lambda slug: C.get_agent(c, slug)
    c.list = lambda: C.list_agents(c)
    return c


def _update(name):
    from marvin.schemas.platform.character_packs import CharacterPackUpdate

    return CharacterPackUpdate(name=name)


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
    assert len(stored) == 3 and all(k.startswith(f"{LIBRARY_STORAGE_PREFIX}/{pack.id}/") for k in stored)
    assert all(f.url.startswith(f"/assets/{LIBRARY_STORAGE_PREFIX}/") for f in pack.files)  # served like asset files
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


def test_the_library_admin_routes_refuse_a_workspace_admin(client):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role="NONE", is_superuser=False, admin=True)
    try:
        assert client.get("/api/admin/character-packs").status_code == 403
        assert client.delete(f"/api/admin/character-packs/{uuid.uuid4()}").status_code == 403
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
    assert any(k.startswith(f"{LIBRARY_STORAGE_PREFIX}/{pack.id}/") for k in _stored(storage.root))


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
