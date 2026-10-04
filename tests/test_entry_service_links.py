"""DB-backed tests for EntryService tag + asset attachments, and registration of the write tools.

Completes the deterministic entry-link surface: tags (find-or-create + link), assets (link an
existing asset). Both idempotent, both emit their events. Mirrors the collection/resource tests.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Assets, AssetTags, Entries, EntryAssets, EntryTags, EntryTypes, Tags
from marvin.services.entries import EntryService


class _SpyBus:
    def __init__(self):
        self.events = []

    def dispatch(self, *, event_type, **_):
        self.events.append(event_type.name)


@fixture
def workspace(db_session):
    """A throwaway workspace with an entry + one asset (created via core inserts for the FK-heavy rows)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"lnk-{marker}", slug=f"lnk-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )

    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}")
    db_session.add(entry)

    aid = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid,
            group_id=gid,
            slug="hero-img",
            name="Hero Image",
            original_filename="hero.jpg",
            filename="hero",
            extension="jpg",
            file_size=1234,
            mime_type="image/jpeg",
            asset_type="image",
            checksum="abc",
            storage_provider="local",
            storage_key=f"k/{marker}.jpg",
            uploaded_by=uid,
        )
    )
    db_session.commit()

    yield gid, entry.id, aid

    db_session.query(EntryTags).delete()
    db_session.query(AssetTags).delete()
    db_session.query(EntryAssets).delete()
    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.execute(Assets.__table__.delete().where(Assets.group_id == gid))
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, gid):
    bus = _SpyBus()
    return EntryService(db_session, gid, event_bus=bus, integration_id="automation"), bus


# ── Tags ──────────────────────────────────────────────────────────────────────
def test_attach_tag_find_or_creates_and_emits(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, bus = _svc(db_session, gid)

    assert svc.attach_tag(entry_id, "Waxed Canvas") == "attached"  # find-or-creates the tag
    assert svc.attach_tag(entry_id, "waxed-canvas") == "exists"  # same slug → idempotent
    assert db_session.query(EntryTags).filter(EntryTags.entry_id == entry_id).count() == 1
    assert db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "waxed-canvas").count() == 1
    assert bus.events == ["entry_tag_attached"]


def test_detach_tag_is_idempotent_and_keeps_the_tag(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, bus = _svc(db_session, gid)
    svc.attach_tag(entry_id, "waxed")

    assert svc.detach_tag(entry_id, "waxed") == "detached"
    assert svc.detach_tag(entry_id, "waxed") == "absent"  # unknown-to-this-entry → absent
    assert db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "waxed").count() == 1  # tag survives
    assert bus.events == ["entry_tag_attached", "entry_tag_detached"]


def test_attach_tag_unknown_entry_returns_none(db_session, workspace):
    gid, _, _ = workspace
    svc, _ = _svc(db_session, gid)
    assert svc.attach_tag(uuid.uuid4(), "waxed") is None


def test_link_tag_spans_entry_and_asset_one_vocabulary(db_session, workspace):
    # THE point: the same tag vocabulary links to entries AND assets (and resources) via link_tag.
    from marvin.db.models.platform.asset_tags import AssetTags
    from marvin.services.tagging import link_tag

    gid, entry_id, aid = workspace
    bus = _SpyBus()  # spy so no real event_log rows are persisted (they'd block group teardown)
    assert link_tag(db_session, gid, "entry", entry_id, "Shared", attach=True, event_bus=bus) == "attached"
    assert link_tag(db_session, gid, "asset", aid, "shared", attach=True, event_bus=bus) == "attached"  # same slug, other junction
    assert link_tag(db_session, gid, "asset", aid, "shared", attach=True, event_bus=bus) == "exists"  # idempotent

    assert db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "shared").count() == 1  # ONE tag
    assert db_session.query(EntryTags).filter(EntryTags.entry_id == entry_id).count() == 1
    assert db_session.query(AssetTags).filter(AssetTags.asset_id == aid).count() == 1
    assert bus.events == ["entry_tag_attached", "asset_updated"]  # entry gets its tag event; asset reuses asset_updated

    assert link_tag(db_session, gid, "asset", aid, "shared", attach=False, event_bus=bus) == "detached"
    assert link_tag(db_session, gid, "asset", aid, "shared", attach=False, event_bus=bus) == "absent"


def test_link_tag_rejects_unknown_entity_type():
    from marvin.services.tagging import link_tag

    assert link_tag(None, uuid.uuid4(), "widget", uuid.uuid4(), "x", attach=True) is None


def test_attach_tag_tool_validates_entity_type():
    import json

    from marvin.services.ai.tools import ToolContext, get_tool

    ctx = ToolContext(session=None, group_id=uuid.uuid4(), user=None)
    out = json.loads(get_tool("attach_tag").handler(ctx, {"entity_type": "widget", "entity": "x", "tag": "y"}))
    assert "entity_type" in out["error"]


# ── Assets ────────────────────────────────────────────────────────────────────
def test_attach_asset_by_slug_emits_and_persists(db_session, workspace):
    gid, entry_id, aid = workspace
    svc, bus = _svc(db_session, gid)

    assert svc.attach_asset(entry_id, "hero-img", role="hero") == "attached"
    assert svc.attach_asset(entry_id, str(aid)) == "exists"  # by id, idempotent
    assert db_session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id).count() == 1
    assert bus.events == ["asset_attached_to_entry"]


def test_detach_asset_is_idempotent(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, bus = _svc(db_session, gid)
    svc.attach_asset(entry_id, "hero-img")

    assert svc.detach_asset(entry_id, "hero-img") == "detached"
    assert svc.detach_asset(entry_id, "hero-img") == "absent"
    assert bus.events == ["asset_attached_to_entry", "asset_detached_from_entry"]


def test_attach_asset_positions_increment(db_session, workspace):
    # Regression: (max_pos or -1)+1 collapsed to 0 for every attach because 0 is falsy, so a second
    # gallery image never advanced past position 0 (arbitrary render order).
    from marvin.db.models.users.users import Users

    gid, entry_id, aid = workspace
    uid = db_session.query(Users.id).filter(Users.group_id == gid).scalar()
    aid2 = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid2,
            group_id=gid,
            slug="second-img",
            name="Second",
            original_filename="b.jpg",
            filename="b",
            extension="jpg",
            file_size=1,
            mime_type="image/jpeg",
            asset_type="image",
            checksum="b",
            storage_provider="local",
            storage_key=f"k/{gid.hex[:5]}b.jpg",
            uploaded_by=uid,
        )
    )
    db_session.commit()
    svc, _ = _svc(db_session, gid)

    assert svc.attach_asset(entry_id, aid, role="hero") == "attached"
    assert svc.attach_asset(entry_id, aid2, role="gallery") == "attached"
    positions = sorted(r.position for r in db_session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id))
    assert positions == [0, 1]  # not [0, 0]


def test_attach_asset_unknown_returns_none(db_session, workspace):
    gid, entry_id, _ = workspace
    svc, _ = _svc(db_session, gid)
    assert svc.attach_asset(entry_id, "no-such-asset") is None


# ── Registry write tools ──────────────────────────────────────────────────────
def test_all_link_tools_registered_as_writes():
    from marvin.services.ai.operations.base import ROLE_EDITOR
    from marvin.services.ai.tools import get_tool

    for name in (
        "attach_resource",
        "detach_resource",
        "attach_tag",
        "detach_tag",
        "add_to_collection",
        "remove_from_collection",
        "attach_asset",
        "detach_asset",
    ):
        spec = get_tool(name)
        assert spec.read_only is False and spec.min_role == ROLE_EDITOR
        assert "mcp" in spec.sources and "agent" in spec.sources


def test_list_tags_is_a_read_tool():
    from marvin.services.ai.operations.base import ROLE_VIEWER
    from marvin.services.ai.tools import get_tool

    spec = get_tool("list_tags")
    assert spec.read_only is True and spec.min_role == ROLE_VIEWER


# ── import_asset (ingestion) input guards ─────────────────────────────────────
class _User:
    id = uuid.uuid4()


def _import(args, user=_User()):
    import json

    from marvin.services.ai.tools import ToolContext, get_tool

    ctx = ToolContext(session=None, group_id=uuid.uuid4(), user=user)
    return json.loads(get_tool("import_asset").handler(ctx, args))


def test_import_asset_is_a_write_tool():
    from marvin.services.ai.operations.base import ROLE_EDITOR
    from marvin.services.ai.tools import get_tool

    spec = get_tool("import_asset")
    assert spec.read_only is False and spec.min_role == ROLE_EDITOR and "mcp" in spec.sources


def test_import_asset_requires_a_user():
    assert "authenticated user" in _import({"url": "https://x/y.jpg"}, user=None)["error"]


def test_import_asset_requires_url_or_data():
    assert "url" in _import({})["error"]  # "provide either 'url' or 'data'"


def test_import_asset_rejects_non_http_url():
    assert "http" in _import({"url": "file:///etc/passwd"})["error"]  # SSRF-adjacent guard


def test_import_asset_rejects_bad_base64():
    assert "base64" in _import({"data": "!!!not base64!!!"})["error"]


def test_recipe_roles_for_entry_reads_declared_roles(db_session, workspace):
    # Bulk import attaches by position → these roles (first→hero). Reads the entry type's recipe.
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.services.ai.tools import ToolContext
    from marvin.services.ai.tools.builtins_actions import _recipe_roles_for_entry

    gid, entry_id, _ = workspace
    entry = db_session.get(Entries, entry_id)
    et = db_session.get(EntryTypes, entry.entry_type_id)
    et.recipe_json = {"assets": {"roles": [{"role": "hero"}, {"role": "gallery"}]}}
    db_session.commit()

    ctx = ToolContext(session=db_session, group_id=gid, user=None)
    assert _recipe_roles_for_entry(ctx, entry_id) == ["hero", "gallery"]
    assert _recipe_roles_for_entry(ctx, uuid.uuid4()) == []  # unknown entry → no roles


def test_import_asset_ssrf_fence_blocks_internal_hosts():
    # The SSRF guard rejects non-public targets before any fetch happens (IP literals need no DNS).
    from marvin.services.ai.tools.builtins_actions import _public_url_error

    assert "http" in _public_url_error("file:///etc/passwd")
    assert "non-public" in _public_url_error("http://127.0.0.1/x")  # loopback
    assert "non-public" in _public_url_error("http://10.0.0.5/x")  # private
    assert "non-public" in _public_url_error("http://169.254.169.254/x")  # cloud metadata (link-local)
    assert "non-public" in _public_url_error("http://[::1]/x")  # IPv6 loopback
