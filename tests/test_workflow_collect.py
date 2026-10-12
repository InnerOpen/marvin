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
from tests.test_workflow_media import _derivatives, _png, _stored, _workflow, media  # noqa: F401

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
