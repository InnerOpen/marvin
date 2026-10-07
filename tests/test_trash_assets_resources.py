"""The Trash for assets and resources (services/trash.py).

Delete moves an asset or resource to the Trash: `trashed_at` set, `asset_trashed` / `resource_trashed`
emitted, the row hidden from every listing, the editor's attachments, counts and the publishing API — but a
fetch by id still shows it, and an asset's file stays in storage (sites serve it straight from the bucket).
Restore clears it. Deleting forever ("Delete forever" on a trashed item, Empty trash for ADMIN/OWNER, the
hourly auto-empty) goes through the one deletion path, so `asset_deleted` / `resource_deleted` fire and the
file leaves storage. The admin routes take the same path — their delete used to drop only the row and orphan
the file.

Storage is a local provider under tmp_path standing in for the configured one. Service tests run over a
throwaway workspace with commits turned into flushes and events sent to a spy bus; the HTTP tests commit for
real (the app opens its own sessions) and purge the workspace afterwards.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.platform import Assets, EntryAssets, EntryResources, Resources
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services import trash as T
from tests.test_publishing_expand import make_workspace, site  # noqa: F401 — publishing fixtures
from tests.test_trash import _make_workspace, _SpyBus


@fixture
def storage(tmp_path, monkeypatch):
    """Local storage under tmp_path, standing in for the configured provider everywhere."""
    from marvin.services.storage import provider_factory
    from marvin.services.storage.local_provider import LocalStorageProvider

    store = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
    monkeypatch.setattr(provider_factory, "get_storage_provider", lambda *a, **k: store)
    return store


def _add_items(session, w, store):
    """An asset (with a file in ``store``) and a resource maker for workspace ``w``."""

    def asset(slug: str):
        key = f"{w.gid.hex[:8]}/2026/10/{uuid.uuid4().hex}.png"
        store.put(key, io.BytesIO(b"\x89PNG fake"), "image/png")
        a = Assets(
            session=session,
            group_id=w.gid,
            slug=f"{slug}-{w.gid.hex[:6]}",
            name=slug.title(),
            original_filename=f"{slug}.png",
            filename=f"{slug}.png",
            extension="png",
            file_size=9,
            mime_type="image/png",
            asset_type="image",
            checksum=uuid.uuid4().hex,
            storage_provider="local",
            storage_key=key,
            uploaded_by=w.users["editor"],
        )
        session.add(a)
        session.flush()
        return a.id

    def resource(slug: str):
        r = Resources(
            session=session, group_id=w.gid, slug=f"{slug}-{w.gid.hex[:6]}", name=slug.title(), resource_type="material", created_by=w.users["editor"]
        )
        session.add(r)
        session.flush()
        return r.id

    return asset, resource


@fixture
def ws(db_session, monkeypatch, storage):
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _SpyBus)
    _SpyBus.events = []
    w = _make_workspace(db_session, "trash2")
    w.asset, w.resource = _add_items(db_session, w, storage)
    w.store = storage
    yield w
    db_session.rollback()


def _get(ws, kind, item_id):
    ws.session.expire_all()
    return ws.session.get(T.model(kind), item_id)


def _names(item_id) -> list[str]:
    return [name for name, ent in _SpyBus.events if ent == str(item_id)]


# ── Trash, restore, delete forever ────────────────────────────────────────────


def test_trashing_an_asset_keeps_its_file_and_emits_asset_trashed(ws):
    aid = ws.asset("photo")
    key = _get(ws, "asset", aid).storage_key
    T.trash(ws.session, ws.gid, "asset", aid, actor_id=ws.users["editor"])
    row = _get(ws, "asset", aid)
    assert row.trashed_at is not None and str(row.trashed_by) == str(ws.users["editor"])
    assert ws.store.exists(key)  # the site may still link it; the file goes only when the Trash is emptied
    assert _names(aid) == ["asset_trashed"]
    T.trash(ws.session, ws.gid, "asset", aid)  # already there: nothing emitted
    assert _names(aid) == ["asset_trashed"]


def test_restore_brings_it_back_and_emits_restored(ws):
    rid = ws.resource("canvas")
    T.trash(ws.session, ws.gid, "resource", rid)
    T.restore(ws.session, ws.gid, "resource", rid)
    row = _get(ws, "resource", rid)
    assert row.trashed_at is None and row.trashed_by is None
    assert _names(rid) == ["resource_trashed", "resource_restored"]


def test_delete_forever_removes_the_file_and_only_takes_trashed_items(ws):
    live, gone = ws.asset("live"), ws.asset("gone")
    keys = {i: _get(ws, "asset", i).storage_key for i in (live, gone)}
    T.trash(ws.session, ws.gid, "asset", gone)
    assert T.delete_forever(ws.session, ws.gid, "asset", [live, gone]) == 1
    assert _get(ws, "asset", gone) is None and not ws.store.exists(keys[gone])
    assert _get(ws, "asset", live) is not None and ws.store.exists(keys[live])
    assert "asset_deleted" in _names(gone) and _names(live) == []
    assert T.delete_forever(ws.session, ws.gid, "asset", [gone]) == 0  # a second run deletes nothing twice


def test_empty_all_empties_entries_assets_and_resources(ws):
    eid, aid, rid = ws.entry("old"), ws.asset("old"), ws.resource("old")
    key = _get(ws, "asset", aid).storage_key
    from marvin.services.entries import EntryService

    EntryService(ws.session, ws.gid).trash(eid)
    T.trash(ws.session, ws.gid, "asset", aid)
    T.trash(ws.session, ws.gid, "resource", rid)
    assert T.counts(ws.session, ws.gid) == {"entries": 1, "assets": 1, "resources": 1, "total": 3}
    assert T.empty_all(ws.session, ws.gid) == {"entries": 1, "assets": 1, "resources": 1, "total": 3}
    assert not ws.store.exists(key)
    assert "entry_deleted" in _names(eid) and "asset_deleted" in _names(aid) and "resource_deleted" in _names(rid)
    assert T.counts(ws.session, ws.gid)["total"] == 0


def test_auto_empty_ages_items_by_trashed_at_with_the_entries_setting(ws):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    old, new, keep = ws.asset("old"), ws.resource("new"), ws.resource("kept")
    for kind, i in (("asset", old), ("resource", new)):
        T.trash(ws.session, ws.gid, kind, i)
    _get(ws, "asset", old).trashed_at = datetime.now(UTC) - timedelta(days=31)
    ws.session.flush()
    purged = T.purge_expired(ws.session)  # platform default: 30 days
    assert purged.get(ws.gid) == 1 and _get(ws, "asset", old) is None
    assert _get(ws, "resource", new) is not None and _get(ws, "resource", keep) is not None

    ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).update({"trash_auto_empty_days": 0})  # never
    _get(ws, "resource", new).trashed_at = datetime.now(UTC) - timedelta(days=400)
    ws.session.flush()
    assert ws.gid not in T.purge_expired(ws.session)


def test_the_hourly_task_empties_assets_and_resources_too(ws, monkeypatch):
    import importlib
    from contextlib import contextmanager

    task = importlib.import_module("marvin.services.scheduler.tasks.empty_expired_trash")  # the package re-exports the function

    aid = ws.asset("stale")
    T.trash(ws.session, ws.gid, "asset", aid)
    _get(ws, "asset", aid).trashed_at = datetime.now(UTC) - timedelta(days=60)
    ws.session.flush()

    @contextmanager
    def same_session():
        yield ws.session

    monkeypatch.setattr(task, "session_context", same_session)
    task.empty_expired_trash()
    assert _get(ws, "asset", aid) is None


# ── Out of sight while trashed ────────────────────────────────────────────────


def test_an_entrys_trashed_attachments_are_hidden_and_survive_a_save(ws):
    from marvin.repos import AllRepositories
    from marvin.schemas.platform import EntryRead

    eid, aid, keep, rid = ws.entry("post"), ws.asset("hero"), ws.asset("gallery"), ws.resource("canvas")
    ws.session.add_all([EntryAssets(entry_id=eid, asset_id=aid, position=0), EntryAssets(entry_id=eid, asset_id=keep, position=1)])
    ws.session.add(EntryResources(entry_id=eid, resource_id=rid, position=0))
    ws.session.flush()
    T.trash(ws.session, ws.gid, "asset", aid)
    T.trash(ws.session, ws.gid, "resource", rid)

    repos = AllRepositories(ws.session, group_id=ws.gid)
    ws.session.expire_all()
    read = EntryRead.model_validate(repos.entries.get_one(eid))
    assert [str(a.id) for a in read.assets] == [str(keep)] and read.resources == []

    # The editor saves what it sees (no trashed links); the links to trashed items stay for a restore.
    repos.entries.update(eid, {"asset_attachments": [{"asset_id": keep}], "resource_attachments": []})
    links = {str(r.asset_id) for r in ws.session.query(EntryAssets).filter_by(entry_id=eid)}
    assert links == {str(aid), str(keep)}
    assert ws.session.query(EntryResources).filter_by(entry_id=eid, resource_id=rid).count() == 1
    T.restore(ws.session, ws.gid, "asset", aid)
    ws.session.expire_all()
    assert {str(a.id) for a in EntryRead.model_validate(repos.entries.get_one(eid)).assets} == {str(aid), str(keep)}


def test_a_trashed_item_cannot_be_attached(ws):
    from marvin.services.entries import EntryService

    eid, aid, rid = ws.entry("post"), ws.asset("x"), ws.resource("y")
    T.trash(ws.session, ws.gid, "asset", aid)
    T.trash(ws.session, ws.gid, "resource", rid)
    svc = EntryService(ws.session, ws.gid)
    assert svc.attach_asset(eid, aid) is None and svc.attach_resource(eid, rid) is None


def test_entry_query_attachment_filters_ignore_trashed_items(ws):
    from marvin.services.entries.query import run

    eid, aid = ws.entry("with-image"), ws.asset("only")
    ws.session.add(EntryAssets(entry_id=eid, asset_id=aid, position=0))
    ws.session.flush()
    assert eid in {e.id for e in run(ws.session, ws.gid, {"has_images": True}).rows}
    T.trash(ws.session, ws.gid, "asset", aid)
    assert eid not in {e.id for e in run(ws.session, ws.gid, {"has_images": True}).rows}


def test_ai_read_tools_leave_trashed_items_out(ws):
    import json

    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import ToolContext

    aid, rid = ws.asset("hidden"), ws.resource("hidden")
    seen_a, seen_r = ws.asset("seen"), ws.resource("seen")
    T.trash(ws.session, ws.gid, "asset", aid)
    T.trash(ws.session, ws.gid, "resource", rid)
    ctx = ToolContext(session=ws.session, group_id=ws.gid, user=None)
    assets = json.loads(get_tool("list_assets").handler(ctx, {}))["assets"]
    resources = json.loads(get_tool("list_resources").handler(ctx, {}))["resources"]
    assert {a["id"] for a in assets} == {str(seen_a)}
    assert {r["id"] for r in resources} == {str(seen_r)}
    # Fetched by id it is still there, saying where it is.
    got = json.loads(get_tool("get_asset").handler(ctx, {"id_or_slug": str(aid)}))
    assert got["inTrash"] is True and got["trashedAt"]


def test_the_semantic_index_drops_trashed_items():
    from marvin.services.ai.embeddings_registry import delete_descriptor_for, index_descriptor_for
    from marvin.services.event_bus_service.event_types import EventTypes

    for kind in ("asset", "resource"):
        desc = delete_descriptor_for(getattr(EventTypes, f"{kind}_trashed"))
        assert desc.entity_type == kind and index_descriptor_for(getattr(EventTypes, f"{kind}_restored")) is desc
        assert desc.content_ok(SimpleNamespace(trashed_at=datetime.now(UTC), description="d", alt_text="a")) is False


# ── Workflows ─────────────────────────────────────────────────────────────────


def test_workflow_item_ops_are_trash_and_restore_only_and_the_events_hub_knows_them():
    import pytest

    from marvin.schemas.group.automation_definition import EntryAction
    from marvin.services.automation.actions.base import AutomationActionError
    from marvin.services.automation.actions.entry import run_entry_action
    from marvin.services.automation.authz import ROLE_ADMIN
    from marvin.services.events.connections import _step_sends

    assert EntryAction(kind="entry", op="trash", entity_type="asset").entity_type == "asset"
    assert [e for e, _ in _step_sends({"kind": "entry", "op": "trash", "entity_type": "asset"})] == ["asset_trashed"]
    assert [e for e, _ in _step_sends({"kind": "entry", "op": "restore", "entity_type": "resource"})] == ["resource_restored"]
    with pytest.raises(AutomationActionError, match="only trash and restore"):
        run_entry_action(None, uuid.uuid4(), {"kind": "entry", "op": "publish", "entity_type": "asset"}, {}, authorizer_role=ROLE_ADMIN)


# ── Site rebuild ──────────────────────────────────────────────────────────────


def test_visibility_follows_published_entries_public_collections_and_the_site_logo(ws):
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform import CollectionAssets, Collections, Entries
    from marvin.services.publish_visibility import item_visible_to_sites

    draft, live = ws.entry("draft"), ws.entry("live", status="published")
    on_draft, on_live, in_public, logo, loose = (ws.asset(s) for s in ("d", "l", "c", "logo", "loose"))
    ws.session.add_all([EntryAssets(entry_id=draft, asset_id=on_draft, position=0), EntryAssets(entry_id=live, asset_id=on_live, position=0)])
    coll = Collections(session=ws.session, group_id=ws.gid, name="Gallery", slug=f"gallery-{ws.gid.hex[:6]}", target_type="asset", is_public=True)
    ws.session.add(coll)
    ws.session.flush()
    ws.session.add(CollectionAssets(collection_id=coll.id, asset_id=in_public))
    logo_row = _get(ws, "asset", logo)
    ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).update({"site_logo": logo_row.slug})
    ws.session.flush()
    assert ws.session.get(Entries, live).status == "published"
    visible = {i: item_visible_to_sites(ws.session, "asset", _get(ws, "asset", i)) for i in (on_draft, on_live, in_public, logo, loose)}
    assert visible == {on_draft: False, on_live: True, in_public: True, logo: True, loose: False}


# ── HTTP ──────────────────────────────────────────────────────────────────────


@fixture
def http(db_session, storage):
    """A committed workspace for the app's own sessions; sign the editor in with any role."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users
    from marvin.services.collections.system_collections import seed_system_workflow_collections
    from marvin.services.group.group_purge import purge_group_dependents

    w = _make_workspace(db_session, "trash2-http")
    seed_system_workflow_collections(db_session, w.gid)
    asset, resource = _add_items(db_session, w, storage)
    db_session.commit()

    def sign_in(role: WorkspaceRole, *, admin: bool = False) -> TestClient:
        from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

        def role_in(group_id):
            return role if str(group_id) == str(w.gid) else None

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=w.users["editor"],
            group_id=w.gid,
            active_group_id=w.gid,
            admin=admin,
            is_superuser=admin,
            full_name="editor",
            email="editor@t.test",
            platform_role=PlatformRole.SUPER_ADMIN if admin else PlatformRole.NONE,
            workspace_memberships=[SimpleNamespace(group_id=w.gid, workspace_role=role)],
            get_workspace_role=role_in,
            has_workspace_role=lambda group_id, required: role_in(group_id) is not None
            and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
        )
        return TestClient(app)

    def committed(make):
        def made(*a, **k):
            item_id = make(*a, **k)
            db_session.commit()
            return item_id

        return made

    def key_of(asset_id):
        db_session.expire_all()
        return db_session.get(Assets, asset_id).storage_key

    yield SimpleNamespace(
        gid=w.gid, sign_in=sign_in, asset=committed(asset), resource=committed(resource), entry=committed(w.entry), store=storage, key_of=key_of
    )
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    entry_ids = [row[0] for row in db_session.execute(EntryAssets.__table__.select().with_only_columns(EntryAssets.entry_id))]
    for junction in (EntryAssets, EntryResources):
        db_session.execute(junction.__table__.delete().where(junction.entry_id.in_(entry_ids)))
    for model in (Assets, Resources):
        db_session.execute(model.__table__.delete().where(model.group_id == w.gid))
    purge_group_dependents(db_session, w.gid)
    db_session.query(Users).filter(Users.group_id == w.gid).delete()
    db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.commit()


A, R, TRASH = "/api/platform/assets", "/api/platform/resources", "/api/platform/trash"


def test_asset_delete_moves_to_the_trash_and_permanent_needs_a_trashed_asset(http):
    client = http.sign_in(WorkspaceRole.EDITOR)
    aid = http.asset("photo")
    key = http.key_of(aid)
    assert client.delete(f"{A}/{aid}?permanent=true").status_code == 409  # not in the Trash yet
    res = client.delete(f"{A}/{aid}")
    assert res.status_code == 200 and res.json()["trashed"] is True
    assert client.get(f"{A}/{aid}").json()["trashedAt"]  # a fetch by id still shows it, trashed
    assert str(aid) not in {a["id"] for a in client.get(A).json()}  # the library doesn't
    assert [a["id"] for a in client.get(f"{TRASH}/assets").json()] == [str(aid)]
    assert client.patch(f"{A}/{aid}", json={"name": "x"}).status_code == 409  # read-only in the Trash
    assert http.store.exists(key)
    assert client.delete(f"{A}/{aid}?permanent=true").json()["deleted"] is True
    assert client.get(f"{A}/{aid}").status_code == 404
    assert not http.store.exists(key)  # deleted forever: the file is gone too


def test_resource_delete_restore_and_delete_forever(http):
    client = http.sign_in(WorkspaceRole.EDITOR)
    rid = http.resource("canvas")
    assert client.post(f"{R}/{rid}/restore").status_code == 409  # not in the Trash
    assert client.delete(f"{R}/{rid}").json()["trashed"] is True
    assert str(rid) not in {r["id"] for r in client.get(R).json()}
    restored = client.post(f"{R}/{rid}/restore")
    assert restored.status_code == 200 and restored.json()["trashedAt"] is None
    assert str(rid) in {r["id"] for r in client.get(R).json()}
    client.delete(f"{R}/{rid}")
    assert client.delete(f"{R}/{rid}?permanent=true").json()["deleted"] is True
    assert client.get(f"{R}/{rid}").status_code == 404


def test_trash_needs_an_editor_and_empty_needs_an_admin(http):
    aid, rid = http.asset("a"), http.resource("r")
    author = http.sign_in(WorkspaceRole.AUTHOR)
    assert author.delete(f"{A}/{aid}").status_code == 403
    assert author.delete(f"{R}/{rid}").status_code == 403
    editor = http.sign_in(WorkspaceRole.EDITOR)
    editor.delete(f"{A}/{aid}")
    editor.delete(f"{R}/{rid}")
    assert editor.post(f"{TRASH}/empty").status_code == 403
    summary = editor.get(TRASH).json()
    assert (summary["assets"], summary["resources"], summary["total"]) == (1, 1, 2) and "effective_days" in summary
    admin = http.sign_in(WorkspaceRole.ADMIN)
    key = http.key_of(aid)
    res = admin.post(f"{TRASH}/empty").json()
    assert (res["deleted"], res["assets"], res["resources"], res["entries"]) == (2, 1, 1, 0)
    assert not http.store.exists(key)


def test_entry_payload_and_tag_counts_leave_trashed_items_out(http):
    client = http.sign_in(WorkspaceRole.EDITOR)
    eid, aid, rid = http.entry("post"), http.asset("hero"), http.resource("canvas")
    tag = client.post("/api/platform/tags", json={"name": f"t-{uuid.uuid4().hex[:6]}"}).json()
    client.post(f"/api/platform/tags/{tag['id']}/assets/{aid}")
    client.patch(
        f"/api/platform/entries/{eid}", json={"asset_attachments": [{"asset_id": str(aid)}], "resource_attachments": [{"resource_id": str(rid)}]}
    )
    entry = client.get(f"/api/platform/entries/{eid}").json()
    assert [a["id"] for a in entry["assets"]] == [str(aid)] and [r["id"] for r in entry["resources"]] == [str(rid)]
    usage = lambda: next(t for t in client.get("/api/platform/tags").json() if t["id"] == tag["id"])["usageCount"]  # noqa: E731
    assert usage() == 1
    client.delete(f"{A}/{aid}")
    client.delete(f"{R}/{rid}")
    entry = client.get(f"/api/platform/entries/{eid}").json()
    assert entry["assets"] == [] and entry["resources"] == []
    assert usage() == 0


def test_admin_delete_trashes_and_permanent_removes_the_file(http):
    """routes/admin/platform isn't mounted in the app today; mounted on its own, its delete takes the Trash's path."""
    from fastapi import FastAPI

    from marvin.routes.admin.platform import router as admin_platform

    http.sign_in(WorkspaceRole.OWNER, admin=True)
    mini = FastAPI()
    mini.include_router(admin_platform, prefix="/api/admin")
    mini.dependency_overrides[get_current_user] = app.dependency_overrides[get_current_user]
    client, platform = TestClient(mini), TestClient(app)
    aid, rid = http.asset("admin"), http.resource("admin")
    key = http.key_of(aid)
    trashed = client.delete(f"/api/admin/platform/assets/{aid}")
    assert trashed.status_code == 200 and trashed.json()["trashedAt"] and http.store.exists(key)
    assert str(aid) not in {a["id"] for a in client.get("/api/admin/platform/assets").json()}
    assert client.post(f"/api/admin/platform/assets/{aid}/restore").json()["trashedAt"] is None
    assert client.delete(f"/api/admin/platform/assets/{aid}?permanent=true").status_code == 409  # restored: not in the Trash
    client.delete(f"/api/admin/platform/assets/{aid}")
    assert client.delete(f"/api/admin/platform/assets/{aid}?permanent=true").status_code == 200
    assert not http.store.exists(key)  # it used to drop the row and orphan the file
    assert platform.get(f"/api/platform/assets/{aid}").status_code == 404
    client.delete(f"/api/admin/platform/resources/{rid}")
    assert client.delete(f"/api/admin/platform/resources/{rid}?permanent=true").status_code == 200
    assert platform.get(f"/api/platform/resources/{rid}").status_code == 404


# ── Publishing API ────────────────────────────────────────────────────────────


def test_publishing_api_never_serves_a_trashed_asset_or_resource(db_session, make_workspace, site):  # noqa: F811
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    ws = make_workspace(1)
    gid, slug = ws.group.id, ws.group.slug
    hero = db_session.query(Assets).filter(Assets.group_id == gid, Assets.slug == "hero-0").one()
    material = db_session.query(Resources).filter(Resources.group_id == gid).one()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=gid, site_logo="hero-0", site_favicon="gallery-0"))
    hero.trashed_at = material.trashed_at = datetime.now(UTC)
    db_session.commit()
    try:
        from marvin.core.permissions import Permissions
        from tests.test_publishing_expand import SITE_TOKEN

        ws.group.name = "Pub"  # the site endpoint reads it
        client = site(ws, {**SITE_TOKEN, Permissions.READ_ASSETS: True})
        entry = client.get(f"/api/publish/{slug}/entries/{ws.slugs[0]}").json()
        assert [a["asset"]["slug"] for a in entry["assets"]] == ["gallery-0"]
        assert entry["resources"] == []
        item = client.get(f"/api/publish/{slug}/entries").json()["data"][0]
        assert item["assetSlugs"] == ["gallery-0"] and item["resourceSlugs"] == []
        assert item["featuredAsset"]["slug"] == "gallery-0"  # the trashed hero isn't featured
        assert "hero-0" not in {a["slug"] for a in client.get(f"/api/publish/{slug}/assets").json()["data"]}
        assert client.get(f"/api/publish/{slug}/assets/hero-0").status_code == 404
        assert client.get(f"/api/publish/{slug}/resources").json()["data"] == []
        assert client.get(f"/api/publish/{slug}/resources/waxed-canvas").status_code == 404
        assert client.get(f"/api/publish/{slug}/resources/waxed-canvas/entries").status_code == 404
        site_info = client.get(f"/api/publish/{slug}/site").json()["site"]
        assert site_info["logo"] is None and site_info["favicon"] == "gallery-0"
    finally:
        db_session.query(GroupPreferencesModel).filter_by(group_id=gid).delete()
        db_session.commit()


# ── AI: trash_entries / restore_entries take assets and resources ────────────


def _ai(ws, tool: str, args: dict) -> dict:
    import json

    from marvin.services.ai.tools import get_tool
    from tests.test_trash import _ctx

    return json.loads(get_tool(tool).handler(_ctx(ws), args))


def test_trash_entries_takes_assets_by_id_slug_or_filename_and_resources_by_name(ws):
    by_id, by_slug, by_file = ws.asset("one"), ws.asset("two"), ws.asset("three")
    twin_a, twin_b = ws.asset("twin-a"), ws.asset("twin-b")
    for i in (twin_a, twin_b):
        ws.session.get(Assets, i).name = "Same"
    ws.session.flush()
    rid = ws.resource("canvas")
    eid = ws.entry("draft")
    slug = _get(ws, "asset", by_slug).slug
    out = _ai(ws, "trash_entries", {"entries": [str(eid)], "assets": [str(by_id), slug, "THREE.png", "Same"], "resources": ["Canvas"]})
    assert [t["id"] for t in out["trashed"]] == [str(eid)]  # entries behave as before
    assert {a["id"] for a in out["trashedAssets"]} == {str(by_id), str(by_slug), str(by_file)}
    assert [r["id"] for r in out["trashedResources"]] == [str(rid)]
    assert [s["asset"] for s in out["skipped"]] == ["Same"]  # a name two assets share: never guessed
    assert all(_get(ws, "asset", i).trashed_at for i in (by_id, by_slug, by_file)) and _get(ws, "resource", rid).trashed_at
    assert "file is kept" in out["undo"] and _names(by_id) == ["asset_trashed"]
    again = _ai(ws, "trash_entries", {"assets": [str(by_id)]})
    assert again["trashedAssets"] == [] and [a["id"] for a in again["alreadyTrashed"]] == [str(by_id)]


def test_trash_entries_with_only_entries_answers_as_before(ws):
    eid = ws.entry("plain")
    out = _ai(ws, "trash_entries", {"entries": [str(eid)]})
    assert set(out) <= {"trashed", "skipped", "alreadyTrashed", "undo", "trashLink"}  # no asset/resource keys
    assert "assets" not in out["undo"]


def test_trashing_an_asset_a_site_shows_asks_first(ws):
    from marvin.services.ai.tools import get_tool
    from tests.test_trash import _ctx

    live = ws.entry("live", status="published")
    shown, loose = ws.asset("shown"), ws.asset("loose")
    ws.session.add(EntryAssets(entry_id=live, asset_id=shown, position=0))
    ws.session.flush()
    ask = get_tool("trash_entries").ask_first
    flagged = ask(_ctx(ws), {"assets": [str(shown), str(loose)]})
    assert flagged is not None and flagged.preview["summary"] == "Move 2 items to the Trash — 1 is on the site and will come off it"
    assert "Shown (asset, on the site)" in flagged.preview["targets"]
    assert ask(_ctx(ws), {"assets": [str(loose)]}) is None
    assert _get(ws, "asset", shown).trashed_at is None  # asking writes nothing


def test_restore_entries_takes_assets_and_resources_back_out(ws):
    aid, rid, live = ws.asset("back"), ws.resource("back"), ws.asset("never-trashed")
    T.trash(ws.session, ws.gid, "asset", aid)
    T.trash(ws.session, ws.gid, "resource", rid)
    out = _ai(ws, "restore_entries", {"assets": [str(aid), str(live)], "resources": [_get(ws, "resource", rid).slug]})
    assert [a["id"] for a in out["restoredAssets"]] == [str(aid)] and [r["id"] for r in out["restoredResources"]] == [str(rid)]
    assert [n["id"] for n in out["notTrashed"]] == [str(live)]
    assert _get(ws, "asset", aid).trashed_at is None and _get(ws, "resource", rid).trashed_at is None
    assert out["restored"] == []


def test_the_tools_need_something_named_and_cap_the_batch(ws):
    assert "name at least one" in _ai(ws, "trash_entries", {})["error"]
    assert "at most 50" in _ai(ws, "restore_entries", {"assets": [f"a{i}" for i in range(30)], "resources": [f"r{i}" for i in range(21)]})["error"]
