"""The caption check (services/integrations/caption_check.py): core's checks, each network's limits from its plugin
(`post_limits`), the API, the assistant's tool, and the preview an approval shows of the post that follows it."""

from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

# ruff: noqa: E402, F811 — fixtures are imported from other tests
from marvin.services.integrations import caption_check
from marvin.services.integrations.caption_check import check, count
from tests.test_social_engagement import _types, nets, ws  # noqa: F401 — the inbox workspace
from tests.test_social_inbox import api  # noqa: F401

INSTAGRAM = {"max": 2200, "unit": "characters", "visible": 125, "hashtags_max": 30, "links": "not_clickable"}
BLUESKY = {"max": 300, "unit": "graphemes", "visible": None, "hashtags_max": None, "links": "card"}
MASTODON = {"max": 500, "unit": "characters", "visible": None, "hashtags_max": None, "links": "clickable"}


def codes(result) -> list[str]:
    return [i.code for i in result.issues]


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_clean_caption_has_no_issues_anywhere():
    text = "Our new mash tun lid holds heat 20% longer. Here's how we tested it over six brew days."
    for limits in (INSTAGRAM, BLUESKY, MASTODON):
        assert codes(check(text, limits)) == []


def test_over_the_limit_is_an_error_that_counts_how_many_too_many():
    result = check("x" * 501, MASTODON)
    assert result.over and codes(result) == ["too_long"] and "1 too many" in result.issues[0].message
    assert result.issues[0].severity == "error"


def test_bluesky_counts_graphemes_not_characters():
    thumbs = "👍🏽" * 300  # two code points each, one grapheme each
    assert count(thumbs, "graphemes") == 300 and len(thumbs) == 600
    assert not check(thumbs, BLUESKY).over and check(thumbs + "👍🏽", BLUESKY).over


def test_the_visible_window_cuts_on_a_word_and_flags_a_first_sentence_that_runs_past_it():
    long_first = "This is the story of how a small shop in our town spent three winters building a lid that keeps a mash at temperature for hours"
    result = check(long_first + ". More below.", INSTAGRAM)
    assert result.cut and len(result.visible_text) <= 125 and not result.visible_text.endswith(" ")
    assert "hook_cut" in codes(result)
    assert "hook_cut" not in codes(check("Short hook. " + "x " * 100, INSTAGRAM))
    assert check("All of it shows", BLUESKY).visible_text is None


def test_an_opening_greeting_or_tag_is_flagged():
    assert "opens_with_greeting" in codes(check("Hey guys! New lid is out", MASTODON))
    assert "opens_with_greeting" not in codes(check("Heyday of brewing", MASTODON))
    assert "opens_with_tag" in codes(check("#brewing new lid", MASTODON))


def test_a_link_is_flagged_only_where_links_dont_work():
    text = "Grab one at https://mashandburn.co today"
    assert "link_not_clickable" in codes(check(text, INSTAGRAM))
    assert "link_not_clickable" in codes(check("Out now", INSTAGRAM, link="https://x.example"))
    assert "link_not_clickable" not in codes(check(text, MASTODON))


def test_too_many_hashtags_and_stock_phrases():
    assert "too_many_hashtags" in codes(check("Lid " + " ".join(f"#t{i}" for i in range(31)), INSTAGRAM))
    assert "too_many_hashtags" not in codes(check("Lid " + " ".join(f"#t{i}" for i in range(31)), MASTODON))
    assert "stock_phrase" in codes(check("A game-changer for every brewer", MASTODON))


def test_an_empty_caption_is_an_error():
    assert codes(check("   ", MASTODON)) == ["empty"]


# ── each network that posts ──────────────────────────────────────────────────────────────────────────────────────


def _nets(monkeypatch, *specs):
    """Fake connected networks: (slug, provider, capabilities, post_limits)."""
    from marvin.services.integrations import social_setup

    def fake(slug, prov, caps, lim):
        row = SimpleNamespace(slug=slug, provider=prov, name=prov.title())
        return SimpleNamespace(row=row, capabilities=frozenset(caps), provider=type("P", (), {"post_limits": lim}))

    fakes = [fake(*spec) for spec in specs]
    monkeypatch.setattr(social_setup, "social_networks", lambda session, group_id: fakes)


def test_every_network_that_posts_is_checked_one_without_limits_is_unknown_and_readers_are_skipped(monkeypatch):
    _nets(
        monkeypatch,
        ("ig", "instagram", {"social.post", "social.comments"}, INSTAGRAM),
        ("bsky", "bluesky", {"social.post"}, BLUESKY),
        ("new", "newnet", {"social.post"}, {}),
        ("read", "readonly", {"social.comments"}, MASTODON),
    )
    results = caption_check.check_for_networks(None, None, "Grab one at https://x.example")
    assert [r["integration"] for r in results] == ["ig", "bsky", "new"]
    assert "link_not_clickable" in [i["code"] for i in results[0]["issues"]] and results[2]["unknown"] is True
    assert [r["integration"] for r in caption_check.check_for_networks(None, None, "x", integrations=["BSKY"])] == ["bsky"]


def test_the_api(ws, api, monkeypatch):
    from tests.test_social_inbox import API, EDITOR, VIEWER

    _nets(monkeypatch, ("ig", "instagram", {"social.post"}, INSTAGRAM))
    body = api(EDITOR).post(f"{API}/caption-check", json={"text": "Hey guys, a new lid " + "x " * 70}).json()
    (ig,) = body["results"]
    assert ig["integration"] == "ig" and ig["visibleText"] and ig["cut"] is True
    assert "opens_with_greeting" in [i["code"] for i in ig["issues"]]
    assert api(VIEWER).post(f"{API}/caption-check", json={"text": "x"}).status_code == 403


def test_the_assistant_tool(ws, monkeypatch):
    import json

    from marvin.db.models.users.roles import WorkspaceRole
    from marvin.services.ai.tools.base import ToolContext, get_tool

    _nets(monkeypatch, ("bsky", "bluesky", {"social.post"}, BLUESKY))
    editor = SimpleNamespace(id=ws.uid, get_workspace_role=lambda g: WorkspaceRole.EDITOR, platform_role=None, is_superuser=False, admin=False)
    out = json.loads(get_tool("check_caption").handler(ToolContext(session=ws.session, group_id=ws.gid, user=editor), {"text": "x" * 301}))
    assert out["count"] == 1 and out["results"][0]["over"] is True
