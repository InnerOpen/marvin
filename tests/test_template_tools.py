"""Entry templates through the assistants' tools: list_templates, get_entry_type's `templates`, and create_draft with a
`template` (the entry for one picture, made by services/entries/templates.py) or with a picture and no title (its name).

Uses the committed workspace of tests/test_entry_templates.py: an artwork type carrying the Ornament template."""

import json
import uuid

from marvin.db.models.platform import Entries
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from tests.test_entry_templates import _count, ws  # noqa: F401 — the workspace fixture


def _call(w, name, args) -> dict:
    return json.loads(get_tool(name).handler(ToolContext(session=w.session, group_id=w.gid, user=None), args))


def test_list_templates_says_what_each_template_does(ws):  # noqa: F811
    out = _call(ws, "list_templates", {})
    [t] = out["templates"]
    assert (t["entryType"], t["slug"], t["name"], t["title"], t["assetField"], t["assetRole"], t["status"]) == (
        "artwork", "ornament", "Ornament", "{asset.name}", "image", "featured", "inbox",
    )  # fmt: skip
    assert set(t["fields"]) == {"medium", "size", "price", "series", "sell_online"}
    assert _call(ws, "list_templates", {"entry_type": "artwork"})["count"] == 1
    assert "not found" in _call(ws, "list_templates", {"entry_type": "nope"})["error"]


def test_get_entry_type_lists_its_templates(ws):  # noqa: F811
    out = _call(ws, "get_entry_type", {"id_or_slug": "artwork"})
    assert out["templates"] == [{"slug": "ornament", "name": "Ornament", "description": None}]


def test_create_draft_with_a_template_makes_the_entry_for_the_picture(ws):  # noqa: F811
    pic = ws.picture("Blue Jay")
    out = _call(
        ws, "create_draft", {"entry_type": "artwork", "template": "ornament", "assets": [pic.slug], "fields": {"price": 90}, "tags": ["Gift"]}
    )
    assert "error" not in out, out
    assert out["template"] == "ornament" and out["title"] == "Blue Jay" and out["reviewLink"].startswith("[") and "inbox draft" in out["message"]
    ws.session.expire_all()
    entry = ws.session.get(Entries, uuid.UUID(out["entryId"]))
    assert entry.title == "Blue Jay" and entry.status == "inbox"
    assert entry.data_json["image"] == str(pic.id) and entry.data_json["medium"] == "Acrylic and Ink on Ceramic"
    assert entry.data_json["price"] == 90  # what the caller gave wins over the template's 85
    link = ws.session.query(EntryAssets).filter_by(entry_id=entry.id, asset_id=pic.id).one()
    assert (link.role, link.position) == ("featured", 0)
    assert {"gift", "ornaments"} <= {t.lower() for t in entry.tag_names}  # the caller's tag beside the template's

    # The same picture again: the entry it has is named, and no second one is made.
    made = _count(ws)
    again = _call(ws, "create_draft", {"entry_type": "artwork", "template": "ornament", "assets": [str(pic.id)]})
    assert f"that picture already has entry 'Blue Jay' ({entry.id}): use update_draft" in again["error"]
    assert _count(ws) == made


def test_create_draft_with_a_template_needs_a_picture_and_a_real_template(ws):  # noqa: F811
    out = _call(ws, "create_draft", {"entry_type": "artwork", "template": "ornament", "title": "X"})
    assert "give one in `assets`" in out["error"]
    pic = ws.picture("Cardinal")
    out = _call(ws, "create_draft", {"entry_type": "artwork", "template": "nope", "assets": [str(pic.id)]})
    assert "no template 'nope'" in out["error"] and "ornament" in out["error"]
    assert _count(ws) == 0


def test_create_draft_without_a_title_takes_the_pictures_name(ws):  # noqa: F811
    pic = ws.picture("Snowy Owl")
    out = _call(ws, "create_draft", {"entry_type": "artwork", "fields": {"image": str(pic.id), "medium": "Ink"}})
    assert "error" not in out, out
    ws.session.expire_all()
    assert ws.session.get(Entries, uuid.UUID(out["entryId"])).title == "Snowy Owl"
    out = _call(ws, "create_draft", {"entry_type": "artwork", "fields": {"medium": "Ink"}})
    assert out["error"] == "title is required (or give a picture: its name becomes the title)"
