"""The collect step (many → one): a query gathered into one output — rows, count, total and a ready text list — under
any trigger, with relative dates; and a render step drawing a whole list of pictures (the grid template)."""

# ruff: noqa: F811 — `ws` / `media` are fixtures, not redefinitions
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from marvin.services.ai.media import render
from marvin.services.automation.authoring import draft_issues
from marvin.services.entries.query import _when
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures
from tests.test_workflow_media import _derivatives, _link, _png, _stored, _workflow, media  # noqa: F401

needs_browser = pytest.mark.skipif(render.browser_path() is None, reason="no headless Chromium (chromium-headless-shell) here")


def _entry(ws, title, *, days_ago=0, status="published", body=""):
    from marvin.db.models.platform.entries import Entries

    slug = f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"
    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title, slug=slug,
        status=status, data_json={"body": body}, metadata_json={}, summary=f"About {title}",
    )  # fmt: skip
    ws.session.add(entry)
    ws.session.flush()
    entry.published_at = datetime.now(UTC) - timedelta(days=days_ago)
    ws.session.commit()
    return entry


def _run(ws, definition):
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    wf = _workflow(ws, definition)
    result = run_automation_now(ws.session, ws.gid, wf, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    run = (
        ws.session.query(AutomationExecutionModel)
        .filter_by(group_id=ws.gid, automation_slug="media-wf")
        .order_by(AutomationExecutionModel.started_at.desc())
        .first()
    )
    return result, run


def test_relative_dates_read_as_now_minus_a_span():
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    assert _when("-7d", now) == now - timedelta(days=7) and _when("+3d", now) == now + timedelta(days=3)
    assert _when("-12h", now) == now - timedelta(hours=12) and _when("-2w", now) == now - timedelta(weeks=2)
    assert _when("today", now) == datetime(2026, 10, 12, tzinfo=UTC) and _when("soon", now) is None


def test_collect_gathers_the_weeks_entries_into_one_output(media):
    _entry(media, "Fresh one", days_ago=2, body="Brass, step by step.")
    _entry(media, "Fresh two", days_ago=5)
    _entry(media, "Old news", days_ago=40)
    _entry(media, "Unfinished", days_ago=1, status="draft")
    step = {
        "kind": "collect",
        "id": "week",
        "entity": "entry",
        "query": {"status": "published", "published_after": "-7d"},
        "fields": ["data.body"],
        "limit": 10,
    }

    result, run = _run(media, {"trigger": {"type": "manual"}, "actions": [step]})

    out = run.actions[0].output_snapshot
    assert result["ok"] and (out["count"], out["total"]) == (2, 2)
    titles = sorted(r["title"] for r in out["rows"])
    assert titles == ["Fresh one", "Fresh two"] and {"id", "slug", "summary", "published_at"} <= set(out["rows"][0])
    body = next(r for r in out["rows"] if r["title"] == "Fresh one")["data"]["body"]
    assert body == "Brass, step by step." and "- Fresh one — About Fresh one" in out["text"] and "data.body: Brass" in out["text"]


def test_a_date_collect_cant_read_fails_instead_of_widening(media):
    _entry(media, "Any", days_ago=1)
    result, run = _run(media, {"trigger": {"type": "manual"}, "actions": [{"kind": "collect", "query": {"published_after": "last week"}}]})
    assert not result["ok"] and "is not a date" in run.actions[0].error


def test_collect_on_assets_leaves_versions_out_unless_asked(media):
    from marvin.db.models.platform.assets import Assets

    original = _stored(media, "harbour", _png())
    copy = _stored(media, "harbour copy", _png())
    media.session.query(Assets).filter_by(id=copy.id).update({"origin": "derived", "source_asset_id": original.id})
    media.session.commit()

    _, run = _run(
        media,
        {
            "trigger": {"type": "manual"},
            "actions": [{"kind": "collect", "entity": "asset", "query": {}}, {"kind": "collect", "entity": "asset", "query": {"versions": "all"}}],
        },
    )

    assert [r["name"] for r in run.actions[0].output_snapshot["rows"]] == ["harbour"]
    assert run.actions[1].output_snapshot["count"] == 2


@needs_browser
def test_a_render_draws_a_whole_list_from_a_collect(media):
    for i, color in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
        _stored(media, f"tile {i}", _png((300, 300), color=color))
    steps = [
        {"kind": "collect", "id": "tiles", "entity": "asset", "query": {"asset_type": "image"}},
        {
            "kind": "media",
            "id": "sheet",
            "op": "render",
            "template": "grid",
            "fields": {"title": "Three tiles"},
            "images": {"tiles": "${steps.tiles.output.rows}"},
            "width": 600,
            "height": 600,
        },
    ]

    result, run = _run(media, {"trigger": {"type": "manual"}, "actions": steps})

    assert result["ok"], [a.error for a in run.actions]
    out = run.actions[1].output_snapshot
    assert len(out["sources"]["tiles"]) == 3
    from marvin.db.models.platform.assets import Assets

    sheet = media.session.get(Assets, uuid.UUID(out["asset"]["id"]))
    assert (sheet.width, sheet.height) == (600, 600) and sheet.metadata_json["render_template"] == "grid"
    img = Image.open(io.BytesIO(media.store.get(sheet.storage_key).read())).convert("RGB")
    assert img.size == (600, 600)


def test_the_validator_reads_a_collect_query(ws):
    step = {"kind": "collect", "entity": "resource", "query": {"where": [{"field": "x", "op": "eq", "value": 1}]}}
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})
    assert any(str(i.get("path", "")).startswith("actions[0].query") for i in issues), issues


# ── Linked items: what an entry names, uses, holds — and a collection's own order ──
def _query(ws, spec):
    from marvin.services.entries.query import run

    return run(ws.session, ws.gid, spec)


def test_entries_follows_a_field_to_the_entry_it_names(media):
    lantern, coat = _entry(media, "Brass lantern"), _entry(media, "Chore coat")
    note = _entry(media, "Wiring day")
    note.data_json = {"project": lantern.slug}
    media.session.commit()

    assert [e.id for e in _query(media, {"entries": note.data_json["project"]}).rows] == [lantern.id]
    by_both = _query(media, {"entries": [lantern.slug, str(coat.id)]}).rows
    assert {e.id for e in by_both} == {lantern.id, coat.id}  # ids or slugs
    assert [e.id for e in _query(media, {"data": {"project": lantern.slug}}).rows] == [note.id]  # and back: what names it
    empty = _query(media, {"entries": ""})
    assert (empty.rows, empty.note) == ([], "entries has no value")  # a template that resolved to nothing never widens


def test_asset_and_resource_find_the_entries_that_use_them(media):
    from marvin.db.models.platform.entry_resources import EntryResources
    from tests.test_workflow_item_targets import _resource

    lantern, coat, _other = _entry(media, "Brass lantern"), _entry(media, "Chore coat"), _entry(media, "Loom")
    photo = _stored(media, "lantern-photo", _png())
    _link(media, lantern, photo, "hero")
    supplier = _resource(media, "Brass supply")
    media.session.add(EntryResources(entry_id=coat.id, resource_id=supplier.id))
    media.session.commit()

    assert [e.id for e in _query(media, {"asset": photo.slug}).rows] == [lantern.id]
    assert [e.id for e in _query(media, {"resource": str(supplier.id)}).rows] == [coat.id]
    missing = _query(media, {"resource": "no-such-supplier"})
    assert missing.rows == [] and "no resource 'no-such-supplier'" in missing.note


def test_position_is_a_collections_own_order(media):
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections

    series = Collections(session=media.session, group_id=media.gid, name="Series", slug="series")
    media.session.add(series)
    media.session.flush()
    parts = {title: _entry(media, title) for title in ("Part two", "Part one", "Part three", "Extra")}
    for title, order in (("Part one", 0), ("Part two", 1), ("Part three", 2), ("Extra", 2)):
        parts[title].published_at = datetime.now(UTC) - timedelta(days=1 if title == "Extra" else 5)
        media.session.add(EntryCollections(entry_id=parts[title].id, collection_id=series.id, sort_order=order))
    _entry(media, "Not in it")
    media.session.commit()

    in_order = _query(media, {"collection": "series", "sort": {"by": "position"}}).rows
    assert [e.title for e in in_order] == ["Part one", "Part two", "Extra", "Part three"]  # a tie: newest published first
    no_collection = _query(media, {"sort": {"by": "position"}})
    assert no_collection.rows == [] and no_collection.note == "sort by position needs exactly one collection"


def test_entry_lists_an_entrys_pictures_in_its_order_and_role(media):
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.services import item_query

    lantern = _entry(media, "Brass lantern")
    shots = [_stored(media, name, _png()) for name in ("a-detail", "b-hero", "c-side")]
    for asset, position, role in ((shots[0], 2, "gallery"), (shots[1], 0, "hero"), (shots[2], 1, "gallery")):
        media.session.add(EntryAssets(entry_id=lantern.id, asset_id=asset.id, position=position, role=role))
    _stored(media, "elsewhere", _png())
    media.session.commit()

    def ids(spec):
        result = item_query.run(media.session, media.gid, "asset", spec)
        assert result.note is None, result.note
        return [r.id for r in result.rows]

    assert ids({"entry": lantern.slug}) == [shots[1].id, shots[2].id, shots[0].id]  # the entry's order, not by name
    assert ids({"entry": str(lantern.id), "role": "gallery"}) == [shots[2].id, shots[0].id]
    assert ids({"role": "hero"}) == [shots[1].id]
    gone = item_query.run(media.session, media.gid, "asset", {"entry": "no-such-entry"})
    assert gone.rows == [] and gone.note == "no entry 'no-such-entry' in this workspace"
