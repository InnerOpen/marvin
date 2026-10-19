"""The Assets library's filters: versions folded under their original, where a file came from, and the shared asset
query (tags, collections, unattached, type, text) on GET /assets — the same keys workflows and the agent use."""

# ruff: noqa: F811 — `workspace` is a fixture, not a redefinition
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import item_query
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import P, workspace  # noqa: F401 — fixture


def _asset(s, gid, uid, name, *, origin="upload", source=None, mime="image/png", trashed=False, size=10, age_days=0):
    from marvin.db.models.platform import Assets

    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=s, group_id=gid, slug=slug, name=name, original_filename=f"{name}.png", filename=name, extension="png",
        file_size=size, mime_type=mime, asset_type="image" if mime.startswith("image/") else "document", checksum=uuid.uuid4().hex,
        storage_provider="local", storage_key=f"lib/{slug}", uploaded_by=uid, origin=origin,
        source_asset_id=source.id if source is not None else None, trashed_at=datetime.now(UTC) if trashed else None,
    )  # fmt: skip
    s.add(row)
    s.flush()
    row.created_at = datetime.now(UTC) - timedelta(days=age_days)
    return row


@pytest.fixture
def library(db_session, workspace):
    """harbour (an upload) with two versions; pier, in the Trash, so its one version stands on its own; a generated
    picture; a document."""
    s, gid, uid = db_session, workspace.gid, workspace.uid
    harbour = _asset(s, gid, uid, "harbour", size=900, age_days=3)
    small = _asset(s, gid, uid, "harbour small", origin="derived", source=harbour, size=100, age_days=1)
    square = _asset(s, gid, uid, "harbour square", origin="derived", source=harbour, size=300, age_days=1)
    pier = _asset(s, gid, uid, "pier", trashed=True)
    pier_crop = _asset(s, gid, uid, "pier crop", origin="derived", source=pier, size=50)
    drawn = _asset(s, gid, uid, "drawn cover", origin="generated", size=500, age_days=0)
    manual = _asset(s, gid, uid, "manual", mime="application/pdf", size=20, age_days=5)
    s.commit()
    return {"harbour": harbour, "small": small, "square": square, "pier": pier, "pier_crop": pier_crop, "drawn": drawn, "manual": manual}


def _names(spec, s, gid) -> set[str]:
    result = item_query.run(s, gid, item_query.ASSET, spec)
    assert result.note is None, result.note
    return {r.name for r in result.rows}


def test_versions_fold_under_an_original_still_in_the_library(db_session, workspace, library):
    s, gid = db_session, workspace.gid
    assert _names({"versions": False}, s, gid) == {"harbour", "pier crop", "drawn cover", "manual"}  # pier's original is trashed
    assert _names({"versions": True}, s, gid) == {"harbour small", "harbour square", "pier crop"}
    assert _names({"source": library["harbour"].slug}, s, gid) == {"harbour small", "harbour square"}
    assert _names({"source": str(library["harbour"].id)}, s, gid) == {"harbour small", "harbour square"}


def test_origin_filters_where_a_file_came_from(db_session, workspace, library):
    s, gid = db_session, workspace.gid
    assert _names({"origin": "generated"}, s, gid) == {"drawn cover"}
    assert _names({"origins": ["upload", "generated"], "versions": False}, s, gid) == {"harbour", "drawn cover", "manual"}


def test_a_lineage_filter_that_cannot_match_says_why(db_session, workspace, library):
    s, gid = db_session, workspace.gid
    assert "origin is one of" in item_query.run(s, gid, item_query.ASSET, {"origin": "scanned"}).note
    assert "no asset 'nope'" in item_query.run(s, gid, item_query.ASSET, {"source": "nope"}).note
    assert "true, false or all" in item_query.run(s, gid, item_query.ASSET, {"versions": "maybe"}).note


def test_the_list_filters_on_the_server_and_counts_versions(workspace, library):
    admin = gates._sign_in(workspace, WorkspaceRole.VIEWER)

    folded = admin.get(f"{P}/assets", params={"versions": "false", "asset_type": "image", "sort": "newest"}).json()
    assert [a["name"] for a in folded] == ["drawn cover", "pier crop", "harbour"]
    assert {a["name"]: a["versionsCount"] for a in folded}["harbour"] == 2
    assert {a["name"]: a["origin"] for a in folded} == {"drawn cover": "generated", "pier crop": "derived", "harbour": "upload"}

    versions = admin.get(f"{P}/assets", params={"source": library["harbour"].slug, "sort": "largest"}).json()
    assert [a["name"] for a in versions] == ["harbour square", "harbour small"]
    assert versions[0]["sourceAssetId"] == str(library["harbour"].id)

    assert [a["name"] for a in admin.get(f"{P}/assets", params={"q": "manual"}).json()] == ["manual"]
    assert admin.get(f"{P}/assets", params={"tag": "no-such-tag"}).status_code == 422


def test_the_default_list_is_unchanged_for_api_callers(workspace, library):
    viewer = gates._sign_in(workspace, WorkspaceRole.VIEWER)
    names = [a["name"] for a in viewer.get(f"{P}/assets").json()]
    assert names == sorted(names) and "harbour small" in names and "pier" not in names  # all but the Trash, by name


def test_a_derivative_records_its_origin_and_source(db_session, workspace, library, tmp_path, monkeypatch):
    import io

    from PIL import Image

    from marvin.repos.all_repositories import get_repositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.local_provider import LocalStorageProvider

    out = io.BytesIO()
    Image.new("RGB", (8, 8)).save(out, format="PNG")
    svc = AssetStorageService(get_repositories(db_session, group_id=workspace.gid), LocalStorageProvider(root=tmp_path, public_base_url="/a"))
    made = svc.create_derivative(source=library["harbour"], data=out.getvalue(), group_id=workspace.gid, derivation="t", slug="h-t", name="h t")
    drawn = svc.create_derivative(
        source=None, data=out.getvalue(), group_id=workspace.gid, derivation="generated:x", slug="g-t", name="g", user_id=workspace.uid
    )
    assert (made.origin, made.source_asset_id) == ("derived", library["harbour"].id)
    assert (drawn.origin, drawn.source_asset_id) == ("generated", None)


def test_a_cleanup_of_unattached_images_leaves_versions_of_a_live_original(db_session, workspace, library):
    s, gid = db_session, workspace.gid
    swept = _names({"asset_type": "image", "unattached": True}, s, gid)
    assert swept == {"harbour", "pier crop", "drawn cover"}  # harbour's versions go with harbour; pier's original is trashed
    assert _names({"unattached": True, "source": library["harbour"].slug}, s, gid) == {"harbour small", "harbour square"}  # asked for


def test_the_orphaned_assets_job_leaves_versions_of_a_live_original(db_session, workspace, library):
    from types import SimpleNamespace

    from marvin.services.scheduled_tasks.handlers.maintenance import RemoveOrphanedAssetsHandler

    task = SimpleNamespace(task_config={"age_days": 0, "auto_delete": False}, group_id=workspace.gid)
    summary = RemoveOrphanedAssetsHandler().execute(task, None)
    assert summary.startswith("4 orphaned assets")  # harbour, pier crop, drawn cover, manual — not harbour's two versions


@pytest.mark.parametrize(
    ("query", "names"),
    [
        ({"asset_type": "image"}, {"harbour", "pier crop", "drawn cover"}),  # originals only, by default
        ({"asset_type": "image", "versions": "all"}, {"harbour", "harbour small", "harbour square", "pier crop", "drawn cover"}),
        ({"versions": True}, {"harbour small", "harbour square", "pier crop"}),
        ({"origin": "derived"}, {"harbour small", "harbour square", "pier crop"}),
        ({"source": "harbour"}, {"harbour small", "harbour square"}),
    ],
)
def test_a_workflows_asset_target_runs_on_originals_unless_it_asks(db_session, workspace, library, query, names):
    from marvin.services.automation.selector import resolve_target_entities

    if "source" in query:
        query = {"source": library["harbour"].slug}
    rows, total = resolve_target_entities(db_session, workspace.gid, {"entity": "asset", "query": query}, {})
    assert {r.name for r in rows} == names and total == len(names)


def test_smart_collection_rules_read_origin_and_made_from(db_session, workspace, library):
    from marvin.services.collections.smart_collections import matches_rules

    harbour, small, drawn = library["harbour"], library["small"], library["drawn"]
    assert matches_rules(drawn, {"origins": ["generated"]}, "asset") and not matches_rules(harbour, {"origins": ["generated"]}, "asset")
    assert matches_rules(small, {"made_from": [harbour.slug]}, "asset") and matches_rules(small, {"made_from": [str(harbour.id)]}, "asset")
    assert not matches_rules(harbour, {"made_from": [harbour.slug]}, "asset")  # the original isn't its own version


def _link(s, entry_id, asset):
    from marvin.db.models.platform.entry_assets import EntryAssets

    s.add(EntryAssets(entry_id=entry_id, asset_id=asset.id, role="hero-800", position=0))
    s.commit()


def _an_entry(s, gid):
    from marvin.db.models.platform import Entries, EntryTypes

    et = EntryTypes(session=s, group_id=gid, name="Note", slug=f"note-{uuid.uuid4().hex[:6]}", schema_json={"fields": []})
    s.add(et)
    s.flush()
    entry = Entries(session=s, group_id=gid, entry_type_id=et.id, title="N", slug=f"n-{uuid.uuid4().hex[:6]}", status="draft")
    s.add(entry)
    s.commit()
    return entry


def test_versions_go_to_the_trash_and_come_back_with_their_original(db_session, workspace, library, monkeypatch):
    from marvin.services import trash
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: None)
    s, gid = db_session, workspace.gid
    harbour, small, square = library["harbour"], library["small"], library["square"]
    trash.trash(s, gid, trash.ASSET, square.id)  # trashed on its own first
    trash.restore(s, gid, trash.ASSET, square.id)
    trash.trash(s, gid, trash.ASSET, small.id)  # on its own: stays in the Trash when harbour comes back

    trash.trash(s, gid, trash.ASSET, harbour.id)
    s.expire_all()
    assert all(trash.is_trashed(a) for a in (harbour, small, square))
    assert square.metadata_json.get(trash.TRASHED_WITH) == str(harbour.id) and trash.TRASHED_WITH not in (small.metadata_json or {})

    trash.restore(s, gid, trash.ASSET, harbour.id)
    s.expire_all()
    assert not trash.is_trashed(harbour) and not trash.is_trashed(square) and trash.is_trashed(small)
    assert trash.TRASHED_WITH not in (square.metadata_json or {})


def test_a_version_an_entry_uses_stays_and_keeps_its_original_in_use(db_session, workspace, library, monkeypatch):
    from marvin.services import trash
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: None)
    s, gid = db_session, workspace.gid
    harbour, small, square = library["harbour"], library["small"], library["square"]
    _link(s, _an_entry(s, gid).id, small)

    assert _names({"asset_type": "image", "unattached": True}, s, gid) == {"pier crop", "drawn cover"}  # harbour's web size is on a page
    trash.trash(s, gid, trash.ASSET, harbour.id)
    s.expire_all()
    assert trash.is_trashed(square) and not trash.is_trashed(small)  # the used version stands on its own


def test_decision_filters_on_what_an_approval_said_about_the_picture(db_session, workspace, library):
    """A denied generated image stays in the library; `decision` tells it from the rest (and `none` from the undecided)."""
    s, gid = db_session, workspace.gid
    library["drawn"].metadata_json = {"generated_by": "openai_images.generate", "approval": {"decision": "denied", "note": "too dark"}}
    s.commit()
    assert _names({"decision": "denied"}, s, gid) == {"drawn cover"}
    assert _names({"decision": "approved"}, s, gid) == set()
    assert "drawn cover" not in _names({"decision": "none", "versions": "all"}, s, gid)
    assert "decision is one of" in item_query.run(s, gid, item_query.ASSET, {"decision": "maybe"}).note
