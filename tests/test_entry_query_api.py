"""POST /api/entries/query: the Entries page's structured search (tasks/structured-search-plan.md). The same engine as
the assistants' find_entries, so the page and the AI find the same entries."""

# ruff: noqa: F811 — the `ws` fixture is imported, then named as a parameter
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from tests.test_remote_mcp_oauth import ws  # noqa: F401 — the fixture


@pytest.fixture
def shop(db_session, ws):
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.db.models.platform.entry_tags import EntryTags
    from marvin.db.models.platform.tags import Tags

    editor = ws(role=WorkspaceRole.EDITOR)
    gid = editor.gid
    et = EntryTypes(session=db_session, group_id=gid, name="Bench Note", slug="bench-note",
                    schema_json={"fields": [{"key": "readTime", "label": "Read time", "type": "text"}]})  # fmt: skip
    db_session.add(et)
    db_session.flush()
    tag = Tags(session=db_session, group_id=gid, name="denim", slug="denim")
    db_session.add(tag)
    db_session.flush()
    made = {}
    for title, status, minutes, tagged in (("Wear", "published", "2 min", True), ("Seams", "published", "5 min", False),
                                           ("Draft", "draft", "2 min", True), ("Gone", "trashed", "2 min", True)):  # fmt: skip
        e = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=title, slug=f"{title.lower()}-{gid.hex[:6]}", status=status,
                    data_json={"readTime": minutes})  # fmt: skip
        db_session.add(e)
        db_session.flush()
        if tagged:
            db_session.add(EntryTags(entry_id=e.id, tag_id=tag.id))
        made[title] = e
    db_session.commit()
    yield editor, made
    db_session.rollback()
    db_session.query(EntryTags).filter(EntryTags.tag_id == tag.id).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.commit()


def _query(editor, spec, **page):
    client = TestClient(app)
    return client.post("/api/platform/entries/query", json={"spec": spec, **page}, headers={"Authorization": f"Bearer {editor.jwt}"})


def test_conditions_narrow_one_at_a_time(shop):
    editor, made = shop
    titles = lambda spec: sorted(e["title"] for e in _query(editor, spec).json()["entries"])  # noqa: E731
    assert titles({"entry_types": ["bench-note"]}) == ["Draft", "Seams", "Wear"]  # the Trash is left out
    assert titles({"entry_types": ["bench-note"], "status": ["published"]}) == ["Seams", "Wear"]
    assert titles({"entry_types": ["bench-note"], "status": ["published"], "tags": ["denim"]}) == ["Wear"]
    where = [{"field": "readTime", "op": "contains", "value": "2"}]
    assert titles({"entry_types": ["bench-note"], "where": where}) == ["Draft", "Wear"]
    assert titles({"status": ["trashed"]}) == ["Gone"]  # only when asked


def test_the_page_and_the_assistant_find_the_same_entries(db_session, shop):
    editor, _made = shop
    spec = {"entry_types": ["bench-note"], "status": ["published"], "tags": ["denim"]}
    via_api = {e["id"] for e in _query(editor, spec).json()["entries"]}
    via_ai = json.loads(get_tool("find_entries").handler(ToolContext(session=db_session, group_id=editor.gid), {**spec, "limit": 200}))
    assert via_api == {e["id"] for e in via_ai["entries"]} and via_api


def test_paging_counts_everything_and_a_condition_that_cannot_match_says_why(shop):
    editor, _made = shop
    page = _query(editor, {"entry_types": ["bench-note"], "sort": {"by": "title"}}, limit=2, offset=0).json()
    assert page["total"] == 3 and [e["title"] for e in page["entries"]] == ["Draft", "Seams"]
    nothing = _query(editor, {"tags": ["no-such-tag"]}).json()
    assert nothing["entries"] == [] and nothing["total"] == 0 and "no-such-tag" in nothing["note"]
    odd = _query(editor, {"where": [{"field": "readTime", "op": "sounds_like", "value": "x"}]}).json()
    assert odd["entries"] == [] and odd["unknownOps"] == ["sounds_like"] and "Valid:" in odd["note"]


def test_a_non_member_gets_nothing(shop, ws):
    _editor, _made = shop
    outsider = ws("Other")
    assert all(e["title"] not in ("Wear", "Seams") for e in _query(outsider, {}).json()["entries"])
    assert uuid  # (imported for the fixtures' ids)
