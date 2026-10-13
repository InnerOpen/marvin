# ruff: noqa: F811 — the `ws` / `workspace` fixtures are imported, then named as parameters
"""Ask files: files attached to a chat question live apart from the Assets library (services/assets/scope.py).

They stay out of everything that lists, counts, queries, collects, indexes, publishes or sweeps the library; they
move there from the Ask files page, by the agent's move_to_assets, or by being attached to an entry; deleting their
thread moves them to the Trash unless another thread still carries them.
"""

import json
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from marvin.services.assets import scope
from tests import test_content_role_gates as gates
from tests.test_workflow_authoring import AD, P, workspace, ws  # noqa: F401 — fixtures


def _asset(ws, name, *, ask=True, mime="image/png", asset_type="image"):
    from marvin.db.models.platform import Assets

    slug = f"ask-{name}-{uuid.uuid4().hex[:8]}" if ask else f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=ws.session, group_id=ws.gid, slug=slug, name=name, original_filename=name, filename=name, extension="png",
        file_size=3, mime_type=mime, asset_type=asset_type, checksum=uuid.uuid4().hex, storage_provider="local",
        storage_key=f"af/{slug}", uploaded_by=ws.uid, scope=scope.ASK if ask else scope.LIBRARY,
        metadata_json={"attachedVia": "bubble"} if ask else None,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    return row


def _ids(rows) -> set[str]:
    return {str(r["id"] if isinstance(r, dict) else r.id) for r in rows}


class _Recorder:
    def __init__(self):
        self.events = []

    def dispatch(self, **kw):
        self.events.append(kw)


def test_an_upload_from_a_chat_surface_is_an_ask_file():
    assert scope.upload_scope({"attachedVia": "bubble"}) == scope.ASK
    assert scope.upload_scope({"attachedVia": "ask_page"}) == scope.ASK
    assert scope.upload_scope({"attachedVia": "share"}) == scope.LIBRARY
    assert scope.upload_scope(None) == scope.LIBRARY


def test_the_library_list_leaves_ask_files_out_and_scope_ask_lists_them(ws):
    admin = gates._sign_in(ws.workspace, AD)
    chat, kept = _asset(ws, "chat.png"), _asset(ws, "logo.png", ask=False)

    library = admin.get(f"{P}/assets").json()
    asks = admin.get(f"{P}/assets", params={"scope": "ask"}).json()

    assert str(kept.id) in _ids(library) and str(chat.id) not in _ids(library)
    assert _ids(asks) == {str(chat.id)} and asks[0]["scope"] == "ask"
    assert admin.get(f"{P}/assets", params={"scope": "nope"}).status_code == 422
    assert admin.get(f"{P}/assets/{chat.id}").status_code == 200  # by id it's still there (the agent opens it)


def test_ask_files_stay_out_of_ai_queries_overview_collections_and_the_index(ws):
    from marvin.services import item_query
    from marvin.services.ai.embeddings_registry import _asset_indexable
    from marvin.services.collections.smart_collections import matches_rules

    chat, kept = _asset(ws, "chat.png"), _asset(ws, "logo.png", ask=False)
    chat.description = kept.description = "a described image"

    rows = item_query.run(ws.session, ws.gid, "asset", {"unattached": True}).rows
    assert str(kept.id) in _ids(rows) and str(chat.id) not in _ids(rows)  # "trash every unattached image" spares it
    rule = {"asset_types": ["image"]}
    assert matches_rules(kept, rule, "asset") and not matches_rules(chat, rule, "asset")
    assert _asset_indexable(kept) and not _asset_indexable(chat)


def test_the_site_api_never_serves_an_ask_file(ws):
    from marvin.app import app
    from marvin.core.dependencies import get_publishing_context

    chat, kept = _asset(ws, "chat.png"), _asset(ws, "logo.png", ask=False)
    perms = SimpleNamespace(require_permission=lambda *a, **k: None)
    slug = ws.workspace.slug
    app.dependency_overrides[get_publishing_context] = lambda: (SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=ws.gid, slug=slug), perms)
    try:
        client = TestClient(app)
        listed = client.get(f"/api/publish/{slug}/assets").json()["data"]
        slugs = {a["slug"] for a in listed}  # the site API names assets by slug, not id
        assert kept.slug in slugs and chat.slug not in slugs
        assert client.get(f"/api/publish/{slug}/assets/{chat.slug}").status_code == 404
    finally:
        app.dependency_overrides.pop(get_publishing_context, None)


def test_moving_to_the_library_announces_it_as_a_new_asset(ws):
    chat = _asset(ws, "chat.png")
    bus = _Recorder()

    moved = scope.move_to_library(ws.session, ws.gid, [chat.id], actor_id=ws.uid, event_bus=bus)

    assert [r.id for r in moved] == [chat.id] and chat.scope == scope.LIBRARY
    assert [e["event_type"].name for e in bus.events] == ["asset_uploaded"]
    assert scope.move_to_library(ws.session, ws.gid, [chat.id], event_bus=bus) == []  # already there: nothing to do


def test_the_ask_files_page_moves_one_to_the_library(ws):
    admin = gates._sign_in(ws.workspace, AD)
    chat = _asset(ws, "chat.png")

    res = admin.post(f"{P}/assets/{chat.id}/move-to-library")

    assert res.status_code == 200 and res.json()["scope"] == "library"
    assert str(chat.id) in _ids(admin.get(f"{P}/assets").json())
    assert admin.post(f"{P}/assets/{chat.id}/move-to-library").status_code == 409


def test_attaching_an_ask_file_to_an_entry_moves_it_first(ws):
    from marvin.services.entries.entry_service import EntryService

    admin = gates._sign_in(ws.workspace, AD)
    entry_id = admin.post(f"{P}/entries", json={"entry_type_id": ws.et["id"], "title": "Page", "status": "draft"}).json()["id"]
    chat = _asset(ws, "chat.png")

    assert EntryService(ws.session, ws.gid, event_bus=_Recorder()).attach_asset(entry_id, str(chat.id)) == "attached"

    ws.session.refresh(chat)
    assert chat.scope == scope.LIBRARY


def test_the_agent_moves_attached_files_with_move_to_assets(ws):
    from marvin.services.ai.tools import builtins_attachments as ba
    from marvin.services.ai.tools.categories import category_of

    chat, kept = _asset(ws, "chat.png"), _asset(ws, "logo.png", ask=False)
    ctx = SimpleNamespace(session=ws.session, group_id=ws.gid, user=SimpleNamespace(id=ws.uid))

    out = json.loads(ba.move_to_assets(ctx, {"assets": [str(chat.id), str(kept.id), str(uuid.uuid4())], "name": ""}))

    assert [m["id"] for m in out["moved"]] == [str(chat.id)]
    assert out["alreadyInLibrary"][0]["id"] == str(kept.id) and len(out["notFound"]) == 1
    assert category_of("move_to_assets", read_only=False) == "assets_import"
    renamed = _asset(ws, "IMG_2041.png")
    out = json.loads(ba.move_to_assets(ctx, {"assets": [str(renamed.id)], "name": "Heron at dusk"}))
    assert out["moved"][0]["name"] == "Heron at dusk"


def test_deleting_a_thread_trashes_the_ask_files_only_it_carried(ws):
    from marvin.db.models.groups.ai_threads import AIThreadModel
    from marvin.services.ai.threads import append_turn, create_thread

    only_here, shared, kept = _asset(ws, "only.png"), _asset(ws, "shared.png"), _asset(ws, "logo.png", ask=False)
    meta = lambda *rows: {"attachments": [{"id": str(r.id), "name": r.name, "mimeType": r.mime_type} for r in rows]}  # noqa: E731
    doomed = create_thread(ws.session, ws.gid, ws.uid, "marvin", "look", None, None)
    append_turn(ws.session, doomed, "user", "look", meta=meta(only_here, shared, kept))
    other = create_thread(ws.session, ws.gid, ws.uid, "marvin", "again", None, None)
    append_turn(ws.session, other, "user", "again", meta=meta(shared))
    ws.session.commit()
    admin = gates._sign_in(ws.workspace, AD)

    assert admin.delete(f"/api/ai/threads/{doomed.id}").status_code == 204

    for row in (only_here, shared, kept):
        ws.session.refresh(row)
    assert only_here.trashed_at is not None  # restorable from the Trash
    assert shared.trashed_at is None and kept.trashed_at is None
    assert ws.session.get(AIThreadModel, other.id) is not None
