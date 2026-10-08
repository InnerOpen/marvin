"""trash_entries / restore_entries `match`: "all of them" and "everything that matches", for an agent.

Seen live: asked to "move all assets to the trash", the agent called trash_entries with assets: ["*"] and then
told the owner a wildcard isn't an asset. The named lists hold at most 50 refs and the list tools paginate, so
there was no way to act on "all X". `match` selects one kind — every one (`all: true`) or those a query in the
kind's own list vocabulary matches — server-side, at most MAX_MATCH per call with the rest reported. A call
with a match always asks first (count, a sample of names, "the Trash, not forever"), and where the run can't
pause to ask it is refused with the count. A wildcard in a named list is refused with a pointer to `match`.
"""

import json

from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport

from marvin.db.models.platform import Assets, Entries, EntryAssets
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import trash as T
from marvin.services.ai.agent import AgentTool, ResumeState, run_agent_loop
from marvin.services.ai.base import Message, ToolCall
from marvin.services.ai.tools import builtins_trash, bulk_writes, get_tool
from marvin.services.ai.tools.bulk_writes import PREVIEW_MAX_TARGETS
from tests.test_trash import _ctx
from tests.test_trash_assets_resources import storage, ws  # noqa: F401 — the workspace fixture (and its storage)

ALL_ASSETS = {"match": {"kind": "assets", "all": True}}


def _run(w, tool: str, args: dict, ctx=None) -> dict:
    return json.loads(get_tool(tool).handler(ctx or _ctx(w), args))


def _ask(w, tool: str, args: dict, ctx=None):
    return get_tool(tool).ask_first(ctx or _ctx(w), args)


def _assets(w, n: int, prefix: str = "img") -> list:
    return [w.asset(f"{prefix}-{i:02d}") for i in range(n)]


def _trashed(w, kind: str, ids) -> list:
    w.session.expire_all()
    return [i for i in ids if w.session.get(T.model(kind), i).trashed_at is not None]


# ── Trash: all of a kind ──────────────────────────────────────────────────────


def test_all_assets_asks_first_with_the_count_a_sample_and_that_it_is_the_trash(ws):  # noqa: F811
    ids = _assets(ws, 60)
    flagged = _ask(ws, "trash_entries", ALL_ASSETS)
    p = flagged.preview
    assert p["summary"] == (
        "Move 60 assets to the Trash (every asset in this workspace). They can be restored from the Trash; nothing is deleted forever"
    )
    assert p["action"] == "trash" and p["targetType"] == "asset" and p["targetCount"] == 60
    assert len(p["targets"]) == PREVIEW_MAX_TARGETS and p["targets"][0] == "Img-00"
    refusal = json.loads(flagged.refusal)
    assert "always needs the user's approval" in refusal["error"] and refusal["matched"]["total"] == 60
    assert _trashed(ws, "asset", ids) == []  # asking writes nothing


def test_an_approved_match_trashes_every_one_beyond_the_named_cap(ws):  # noqa: F811
    ids = _assets(ws, 60)
    out = _run(ws, "trash_entries", ALL_ASSETS)
    assert len(out["trashedAssets"]) == 60 and out["trashed"] == [] and out["skipped"] == []
    assert out["matched"] == {"kind": "assets", "selection": "all", "total": 60, "selected": 60, "remaining": 0}
    assert len(_trashed(ws, "asset", ids)) == 60 and "file is kept" in out["undo"]
    # nothing left to match: no card, an empty answer
    assert _ask(ws, "trash_entries", ALL_ASSETS) is None
    assert _run(ws, "trash_entries", ALL_ASSETS)["matched"]["total"] == 0


def test_the_cap_leaves_the_rest_for_another_call_and_says_how_many(ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(builtins_trash, "MAX_MATCH", 5)
    ids = _assets(ws, 8)
    assert _ask(ws, "trash_entries", ALL_ASSETS).preview["summary"].endswith(". 3 more match and are left for another call")
    first = _run(ws, "trash_entries", ALL_ASSETS)
    assert len(first["trashedAssets"]) == 5 and first["matched"]["remaining"] == 3
    assert "call trash_entries again with the same match" in first["matched"]["next"]
    second = _run(ws, "trash_entries", ALL_ASSETS)
    assert len(second["trashedAssets"]) == 3 and second["matched"]["remaining"] == 0 and "next" not in second["matched"]
    assert len(_trashed(ws, "asset", ids)) == 8


def test_a_query_selects_only_what_it_says_unattached_images(ws):  # noqa: F811
    loose, used, svg = ws.asset("loose"), ws.asset("used"), ws.asset("vector")
    ws.session.get(Assets, svg).asset_type = "svg"
    ws.session.add(EntryAssets(entry_id=ws.entry("draft"), asset_id=used, position=0))
    ws.session.flush()
    args = {"match": {"kind": "assets", "query": {"asset_type": "image", "unattached": True}}}
    p = _ask(ws, "trash_entries", args).preview
    assert p["targetCount"] == 1 and p["targets"] == ["Loose"]
    assert 'assets matching asset_type: "image", unattached: true' in p["summary"]
    out = _run(ws, "trash_entries", args)
    assert [a["id"] for a in out["trashedAssets"]] == [str(loose)]
    assert _trashed(ws, "asset", [loose, used, svg]) == [loose]


def test_entries_match_uses_the_entry_query_and_flags_what_comes_off_the_site(ws):  # noqa: F811
    live, draft, other = ws.entry("spring-sale", "published"), ws.entry("spring-draft"), ws.entry("autumn")
    args = {"match": {"kind": "entries", "query": {"text": "spring"}}}
    p = _ask(ws, "trash_entries", args).preview
    assert p["targetType"] == "entry" and p["targetCount"] == 2
    assert " — 1 is on the site and will come off it." in p["summary"] and "Spring Sale (on the site)" in p["targets"]
    out = _run(ws, "trash_entries", args)
    assert {t["id"] for t in out["trashed"]} == {str(live), str(draft)}
    ws.session.expire_all()
    assert ws.session.get(Entries, other).status == "draft"
    assert "trashedAssets" not in out  # entries only: the entry answer


def test_named_and_matched_combine_and_count_once(ws):  # noqa: F811
    a, b = ws.asset("one"), ws.asset("two")
    rid = ws.resource("kit")
    args = {"assets": [str(a)], "resources": ["Kit"], **ALL_ASSETS}
    p = _ask(ws, "trash_entries", args).preview
    assert p["targetCount"] == 3 and p["targetType"] == "item" and "Kit (resource)" in p["targets"]
    out = _run(ws, "trash_entries", args)
    assert sorted(x["id"] for x in out["trashedAssets"]) == sorted([str(a), str(b)])
    assert [r["id"] for r in out["trashedResources"]] == [str(rid)]


def test_permissions_are_checked_per_item_and_skips_reported(ws):  # noqa: F811
    mine, theirs = ws.entry("mine", owner="author"), ws.entry("theirs")
    out = _run(ws, "trash_entries", {"match": {"kind": "entries", "all": True}}, ctx=_ctx(ws, WorkspaceRole.AUTHOR, "author"))
    assert [t["id"] for t in out["trashed"]] == [str(mine)]
    assert [s["id"] for s in out["skipped"]] == [str(theirs)] and out["skipped"][0]["reason"]


# ── Where nobody can be asked ─────────────────────────────────────────────────


def test_a_run_that_cannot_park_refuses_a_match_with_the_count(ws):  # noqa: F811
    ids = _assets(ws, 3)
    run = bulk_writes.unattended(get_tool("trash_entries"), _ctx(ws))
    out = json.loads(run(ALL_ASSETS))
    assert out["error"].startswith("Not done: Move 3 assets to the Trash") and out["wouldMove"] == 3
    assert _trashed(ws, "asset", ids) == []
    # named, off-site items still go straight through, as before
    assert len(json.loads(run({"assets": [str(ids[0])]}))["trashedAssets"]) == 1


# ── Wildcards and bad matches ────────────────────────────────────────────────


def test_a_wildcard_in_a_named_list_is_refused_with_a_pointer_to_match(ws):  # noqa: F811
    ids = _assets(ws, 2)
    for ref in ("*", "all", "Everything", "all assets"):
        out = _run(ws, "trash_entries", {"assets": [ref]})
        assert 'match: {"kind": "assets", "all": true}' in out["error"] and ref in out["error"]
        assert _ask(ws, "trash_entries", {"assets": [ref]}) is None  # no card for a call that can't run
    assert "entries` takes names, never wildcards" in _run(ws, "trash_entries", {"entries": ["*"]})["error"]
    assert "restore_entries with match" in _run(ws, "restore_entries", {"resources": ["*"]})["error"]
    assert _trashed(ws, "asset", ids) == []


def test_an_item_really_called_all_is_still_found_by_name(ws):  # noqa: F811
    aid = ws.asset("all")
    out = _run(ws, "trash_entries", {"assets": ["All"]})
    assert [a["id"] for a in out["trashedAssets"]] == [str(aid)]


def test_a_match_that_could_select_more_than_it_says_is_refused(ws):  # noqa: F811
    _assets(ws, 2)
    for match, why in (
        ({"kind": "assets"}, "needs all: true"),
        ({"kind": "assets", "query": {}}, "needs all: true"),
        ({"kind": "assets", "all": True, "query": {"asset_type": "image"}}, "not both"),
        ({"kind": "assets", "query": {"resource_types": ["tool"]}}, "does not understand resource_types"),
        ({"kind": "entries", "query": {"colour": "red"}}, "does not understand colour"),
        ({"kind": "pages", "all": True}, "match.kind is one of"),
    ):
        assert why in _run(ws, "trash_entries", {"match": match})["error"]
    assert "status 'trashed'" in _run(ws, "restore_entries", {"match": {"kind": "entries", "query": {"statuses": ["published"]}}})["error"]


def test_a_query_naming_a_missing_tag_matches_nothing_and_says_so(ws):  # noqa: F811
    ids = _assets(ws, 2)
    out = _run(ws, "trash_entries", {"match": {"kind": "assets", "query": {"tags": ["nope"]}}})
    assert out["matched"]["total"] == 0 and "no such tag" in out["matched"]["note"]
    assert _trashed(ws, "asset", ids) == []


# ── Restore from the Trash ────────────────────────────────────────────────────


def test_restore_with_a_match_asks_first_and_brings_every_one_back(ws):  # noqa: F811
    ids = _assets(ws, 3)
    kept = ws.asset("never-trashed")
    for i in ids:
        T.trash(ws.session, ws.gid, "asset", i)
    assert _ask(ws, "restore_entries", {"assets": [str(ids[0])]}) is None  # named: runs as it always has
    p = _ask(ws, "restore_entries", ALL_ASSETS).preview
    assert p["action"] == "restore" and p["targetCount"] == 3
    assert p["summary"].startswith("Restore 3 assets from the Trash (every asset in the Trash)")
    out = _run(ws, "restore_entries", ALL_ASSETS)
    assert len(out["restoredAssets"]) == 3 and out["matched"]["total"] == 3
    assert _trashed(ws, "asset", [*ids, kept]) == []


def test_restore_entries_by_match_takes_only_trashed_ones(ws):  # noqa: F811
    from marvin.services.entries import EntryService

    gone, here = ws.entry("old-note"), ws.entry("old-other")
    EntryService(ws.session, ws.gid, actor_id=ws.users["editor"]).trash(gone)
    out = _run(ws, "restore_entries", {"match": {"kind": "entries", "query": {"text": "old"}}})
    assert [r["id"] for r in out["restored"]] == [str(gone)] and out["matched"]["total"] == 1
    ws.session.expire_all()
    assert ws.session.get(Entries, here).status == "draft"


# ── End to end: "move all assets to the trash" ───────────────────────────────


def _agent_tool(w) -> AgentTool:
    spec = get_tool("trash_entries")
    run, check = bulk_writes.bind(spec, _ctx(w), can_park=True)
    return AgentTool(
        name=spec.name, description=spec.description, input_schema=spec.input_schema, run=run, category="entries_trash", approval_check=check
    )


def test_move_all_assets_to_the_trash_parks_on_a_card_and_the_approved_run_trashes_them(ws):  # noqa: F811
    """The live request, scripted with the SDK's fake provider: the preamble and the tool steer "all" to
    `match`, the call parks on an approval card (nothing written), and approving it trashes all 60."""
    from marvin.services.ai.agents import TRASH_RULE, workspace_preamble

    ids = _assets(ws, 60)
    transport = ScriptedTransport()
    provider = FakeAIProvider(transport)
    tools = [_agent_tool(ws)]
    preamble = workspace_preamble("ws", [t.name for t in tools])
    assert TRASH_RULE in preamble and "`match`" in TRASH_RULE

    transport.reply_tool_calls([ToolCall(id="c1", name="trash_entries", arguments=ALL_ASSETS)])
    res = run_agent_loop(provider, "fake-model", [Message("system", preamble), Message("user", "move all assets to the trash")], tools)
    assert res.stopped_reason == "awaiting_approval"
    card = res.pending_calls[0].preview
    assert card["targetCount"] == 60 and "nothing is deleted forever" in card["summary"]
    offered = transport.requests[0]["tools"][0]
    assert offered["name"] == "trash_entries" and "match" in json.dumps(offered)
    assert _trashed(ws, "asset", ids) == []

    transport.reply_text("Moved all 60 assets to the Trash.")
    done = run_agent_loop(
        provider, "fake-model", [], tools, resume=ResumeState(convo=res.convo, pending=res.pending_calls, decisions={"c1": "approve"})
    )
    assert done.stopped_reason == "complete" and done.answer == "Moved all 60 assets to the Trash."
    assert len(_trashed(ws, "asset", ids)) == 60
    result = next(m for m in transport.requests[-1]["messages"] if m.get("role") == "tool")
    assert json.loads(result["content"])["matched"]["total"] == 60
