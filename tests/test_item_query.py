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


def test_unused_also_leaves_out_what_an_entrys_asset_field_names_without_an_attachment(ws):  # noqa: F811
    """A guided setup's "pictures with no entry yet": attached to none AND named by no entry's asset field. An entry
    saved before asset fields attached what they name can hold an id it never attached; that picture is in use."""
    from marvin.db.models.platform import Entries

    loose, attached, named, in_a_list = ws.asset("loose"), ws.asset("attached"), ws.asset("named"), ws.asset("in-a-list")
    ws.entry_type.schema_json = {"fields": [{"key": "image", "type": "asset"}, {"key": "gallery", "type": "asset-list"}]}
    live = ws.entry("artwork")
    ws.session.add(EntryAssets(entry_id=live, asset_id=attached, position=0))
    old = ws.session.get(Entries, ws.entry("older-artwork", status="trashed"))  # a trashed entry still uses its pictures
    old.data_json = {"image": str(named), "gallery": [str(in_a_list)], "note": str(loose)}  # not an asset field: no use
    ws.session.flush()

    unused = _ids(ws, "asset", {"unused": True})
    assert loose in unused and not {attached, named, in_a_list} & unused
    assert {attached, named, in_a_list} <= _ids(ws, "asset", {"unused": "false"}) and loose not in _ids(ws, "asset", {"unused": False})
    assert named in _ids(ws, "asset", {"unattached": True})  # unattached alone reads only the attachments, as before


def test_ids_picks_exactly_these_by_id_or_slug_and_empty_matches_nothing(ws):  # noqa: F811
    one, two, three = ws.asset("one"), ws.asset("two"), ws.asset("three")
    slug_two = ws.session.get(Assets, two).slug
    assert _ids(ws, "asset", {"ids": f"{one},{slug_two}"}) == {one, two}
    assert _ids(ws, "asset", {"ids": [str(three)]}) == {three}
    assert item_query.run(ws.session, ws.gid, "asset", {"ids": ""}).note == "ids has no value"
    assert item_query.unknown_keys("asset", {"ids": "x", "unused": True}) == []
    assert item_query.unknown_keys("resource", {"unused": True}) == ["unused"]


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
        ({"unused": "maybe"}, "true or false"),
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
