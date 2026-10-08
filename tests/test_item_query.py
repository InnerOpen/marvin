"""The shared asset/resource query (services/item_query.py): what list_assets / list_resources, attach_tag's
`filter` and trash_entries' `match` select by. Each filter narrows; one naming a tag or collection that doesn't
exist, or a value it can't read, matches nothing and says why — it never widens the selection."""

import json
from datetime import UTC, datetime, timedelta

from marvin.db.models.platform import Assets, AssetTags, CollectionAssets, Collections, EntryAssets, EntryResources, Resources, Tags
from marvin.services import item_query
from marvin.services import trash as T
from tests.test_trash_assets_resources import storage, ws  # noqa: F401 — the workspace fixture (and its storage)


def _ids(w, kind, spec, **kw) -> set:
    result = item_query.run(w.session, w.gid, kind, spec, **kw)
    assert result.note is None, result.note
    return {r.id for r in result.rows}


def _tag(w, name, *asset_ids):
    tag = Tags(session=w.session, group_id=w.gid, name=name, slug=name)
    w.session.add(tag)
    w.session.flush()
    for aid in asset_ids:
        w.session.add(AssetTags(asset_id=aid, tag_id=tag.id))
    w.session.flush()


def _collection(w, name, *asset_ids):
    coll = Collections(session=w.session, group_id=w.gid, name=name, slug=name, target_type="asset", is_public=False)
    w.session.add(coll)
    w.session.flush()
    for aid in asset_ids:
        w.session.add(CollectionAssets(collection_id=coll.id, asset_id=aid))
    w.session.flush()


def test_asset_filters_narrow_by_type_mime_text_tags_and_collection(ws):  # noqa: F811
    photo, logo, doc = ws.asset("photo"), ws.asset("logo"), ws.asset("handbook")
    ws.session.get(Assets, logo).mime_type, ws.session.get(Assets, logo).asset_type = "image/svg+xml", "svg"
    ws.session.get(Assets, doc).mime_type, ws.session.get(Assets, doc).asset_type = "application/pdf", "document"
    ws.session.flush()
    _tag(ws, "brand", logo, photo)
    _collection(ws, "press", photo)

    assert _ids(ws, "asset", {"asset_type": "image"}) == {photo}
    assert _ids(ws, "asset", {"asset_types": ["svg", "document"]}) == {logo, doc}
    assert _ids(ws, "asset", {"mime_types": ["image/svg+xml"]}) == {logo}
    assert _ids(ws, "asset", {"query": "HANDBOOK.png"}) == {doc}  # filename, any case
    assert _ids(ws, "asset", {"tags": ["brand"], "asset_type": "image"}) == {photo}
    assert _ids(ws, "asset", {"collection": "press"}) == {photo}


def test_unattached_selects_items_on_no_entry_even_a_trashed_one_counts(ws):  # noqa: F811
    loose, used, on_trashed = ws.asset("loose"), ws.asset("used"), ws.asset("on-trashed")
    live, gone = ws.entry("live"), ws.entry("gone", status="trashed")
    ws.session.add_all([EntryAssets(entry_id=live, asset_id=used, position=0), EntryAssets(entry_id=gone, asset_id=on_trashed, position=0)])
    rid, linked = ws.resource("spare"), ws.resource("linked")
    ws.session.add(EntryResources(entry_id=live, resource_id=linked, position=0))
    ws.session.flush()

    unattached = _ids(ws, "asset", {"unattached": True})
    assert loose in unattached and used not in unattached and on_trashed not in unattached
    assert {used, on_trashed} <= _ids(ws, "asset", {"unattached": "false"})
    assert _ids(ws, "resource", {"unattached": True}) == {rid}


def test_created_dates_and_the_trash(ws):  # noqa: F811
    old, new = ws.asset("old"), ws.asset("new")
    ws.session.get(Assets, old).created_at = datetime.now(UTC) - timedelta(days=90)
    ws.session.flush()
    cutoff = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    assert old in _ids(ws, "asset", {"created_before": cutoff}) and new not in _ids(ws, "asset", {"created_before": cutoff})
    assert new in _ids(ws, "asset", {"created_after": cutoff}) and old not in _ids(ws, "asset", {"created_after": cutoff})

    T.trash(ws.session, ws.gid, "asset", old)
    assert old not in _ids(ws, "asset", {"query": "old"})
    assert _ids(ws, "asset", {"query": "old"}, trashed=True) == {old}  # the Trash's side, for a restore


def test_what_cannot_match_says_why_and_matches_nothing(ws):  # noqa: F811
    ws.asset("anything")
    for spec, why in (
        ({"tags": ["nope"]}, "no such tag"),
        ({"collection": "nope"}, "no such collection"),
        ({"unattached": "maybe"}, "true or false"),
        ({"created_after": "last tuesday"}, "not a date"),
    ):
        result = item_query.run(ws.session, ws.gid, "asset", spec)
        assert result.rows == [] and result.total == 0 and why in result.note
    assert item_query.unknown_keys("resource", {"asset_types": ["image"], "query": "x"}) == ["asset_types"]
    assert item_query.unknown_keys("asset", {"asset_types": ["image"], "unattached": True}) == []


def test_resources_by_type_and_text(ws):  # noqa: F811
    tool = ws.resource("drill")
    ws.session.get(Resources, tool).resource_type = "tool"
    ws.session.flush()
    assert _ids(ws, "resource", {"resource_type": "tool"}) == {tool}
    assert tool in _ids(ws, "resource", {"text": "dri"})


def test_list_tools_take_the_new_filters(ws):  # noqa: F811
    from marvin.services.ai.tools import get_tool
    from tests.test_trash import _ctx

    loose, used = ws.asset("loose"), ws.asset("used")
    ws.session.add(EntryAssets(entry_id=ws.entry("e"), asset_id=used, position=0))
    ws.session.flush()
    out = json.loads(get_tool("list_assets").handler(_ctx(ws), {"unattached": True, "query": "loose"}))
    assert [a["id"] for a in out["assets"]] == [str(loose)] and out["count"] == 1
    none = json.loads(get_tool("list_resources").handler(_ctx(ws), {"collection": "no-such"}))
    assert none["count"] == 0 and "no such collection" in none["note"]
