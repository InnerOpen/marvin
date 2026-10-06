"""archive_entries — the agent's reversible delete (services/ai/tools/builtins_archive.py).

The incident: asked to delete test inbox entries, an agent with no remove tool staged no-op
revise_entry suggestions on seven real entries. These pin the replacement: drafts archive straight
away through the same EntryService path as the entry page (same events), a published entry asks first
(approval card; nothing archived until approved), the AUTHOR ownership rules hold, the batch is capped,
and an agent turn asked to delete entries ends with them archived, not with staged revisions.

DB-backed over a throwaway workspace; commits are flushes rolled back at teardown. Events go to a spy
bus. The model is a scripted fake provider — no real model calls.
"""

import json
import uuid
from types import SimpleNamespace

from pytest import fixture

from marvin.db.models.platform import Entries, EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.agent import AgentTool, ResumeState, run_agent_loop
from marvin.services.ai.base import AIProvider, CompletionResult, Message, ToolCall
from marvin.services.ai.operations.base import ROLE_EDITOR
from marvin.services.ai.tools import bulk_writes, get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.builtins_archive import MAX_ARCHIVE_BATCH
from marvin.services.ai.tools.categories import category_of


class _SpyBus:
    events: list = []

    def __init__(self, *a, **k):
        pass

    def dispatch(self, *, event_type, entity_id=None, **_):
        _SpyBus.events.append((event_type.name, str(entity_id)))


class _User:
    """What the tool reads off a caller: id, role in the workspace, the role-bypass flags."""

    def __init__(self, uid, gid, role: WorkspaceRole | None):
        self.id, self.admin, self.platform_role = uid, False, "NONE"
        self.workspace_memberships = [SimpleNamespace(group_id=gid, workspace_role=role)] if role else []

    def get_workspace_role(self, group_id):
        return next((m.workspace_role for m in self.workspace_memberships if str(m.group_id) == str(group_id)), None)


@fixture
def ws(db_session, monkeypatch):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _SpyBus)
    _SpyBus.events = []

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"arc-{marker}", slug=f"arc-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    users = {}
    for who in ("editor", "author"):
        uid = uuid.uuid4()
        db_session.execute(
            Users.__table__.insert().values(
                id=uid,
                group_id=gid,
                username=f"{who}-{marker}",
                email=f"{who}-{marker}@t.test",
                full_name=who,
                password="x",
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
        users[who] = uid

    et = EntryTypes(session=db_session, group_id=gid, name="Signup", slug=f"signup-{marker}", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    def entry(slug, status, owner="editor"):
        e = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=slug.replace("-", " ").title(), slug=slug)
        e.status = status
        e.created_by = users[owner]
        db_session.add(e)
        db_session.flush()
        return e

    ids = {
        "test1": entry("test-signup-1", "inbox").id,
        "test2": entry("test-signup-2", "draft").id,
        "review": entry("needs-a-look", "needs_review").id,
        "live": entry("spring-sale", "published").id,
        "gone": entry("old-post", "archived").id,
        "mine": entry("author-draft", "draft", owner="author").id,
        "mine_live": entry("author-live", "published", owner="author").id,
    }
    yield SimpleNamespace(gid=gid, users=users, ids=ids, session=db_session)
    db_session.rollback()


def _ctx(ws, role=WorkspaceRole.EDITOR, who="editor") -> ToolContext:
    return ToolContext(session=ws.session, group_id=ws.gid, user=_User(ws.users[who], ws.gid, role))


def _status(ws, key) -> str:
    return ws.session.get(Entries, ws.ids[key]).status


def _archive(ws, keys, ctx=None, **extra) -> dict:
    args = {"entries": [str(ws.ids[k]) if k in ws.ids else k for k in keys], **extra}
    return json.loads(get_tool("archive_entries").handler(ctx or _ctx(ws), args))


# ── Registration: where it sits ──────────────────────────────────────────────


def test_archive_entries_is_a_registry_write_in_its_own_matrix_row():
    spec = get_tool("archive_entries")
    assert spec.read_only is False and spec.min_role == ROLE_EDITOR  # every AI write tool's floor
    assert {"agent", "mcp"} <= set(spec.sources)  # bound in-process AND projected to MarvinMCP
    assert spec.ask_first is not None and spec.bulk_write is None
    assert category_of("archive_entries", read_only=False) == "entries_archive"
    assert spec.input_schema["properties"]["entries"]["maxItems"] == MAX_ARCHIVE_BATCH


def test_descriptions_steer_deletes_to_archive_and_away_from_revise():
    archive = get_tool("archive_entries").description
    assert "delete" in archive and "reversible" in archive
    revise = get_tool("revise_entry").description
    assert "Not for deleting, removing or clearing out entries" in revise and "archive_entries" in revise


# ── Drafts archive straight away, through the human path ─────────────────────


def test_drafts_inbox_and_review_entries_archive_directly_with_the_human_paths_events(ws):
    out = _archive(ws, ["test1", "test2", "review"], reason="test signups")
    assert [a["was"] for a in out["archived"]] == ["inbox", "draft", "needs_review"]
    assert all(_status(ws, k) == "archived" for k in ("test1", "test2", "review"))
    assert out["skipped"] == [] and out["alreadyArchived"] == [] and out["reason"] == "test signups"
    assert "status back" in out["undo"] and out["archivedUrl"].endswith("/workspace/entries?status=archived")
    assert out["archived"][0]["editUrl"].endswith(f"/workspace/entries/{ws.ids['test1']}")
    # exactly what PATCH /entries/{id} {status: archived} emits (EntryService.set_status): updated, then archived
    assert _SpyBus.events == [(name, str(ws.ids[k])) for k in ("test1", "test2", "review") for name in ("entry_updated", "entry_archived")]


def test_already_archived_is_a_reported_no_op(ws):
    out = _archive(ws, ["gone", "test1"])
    assert out["alreadyArchived"] == [{"id": str(ws.ids["gone"]), "title": "Old Post"}]
    assert [a["id"] for a in out["archived"]] == [str(ws.ids["test1"])]
    assert all(eid != str(ws.ids["gone"]) for _, eid in _SpyBus.events)


def test_slugs_resolve_and_unknown_entries_are_skipped(ws):
    out = _archive(ws, ["test-signup-1", "no-such-entry", str(uuid.uuid4())])
    assert [a["id"] for a in out["archived"]] == [str(ws.ids["test1"])]
    assert [s["reason"] for s in out["skipped"]] == ["not found in this workspace"] * 2


def test_the_same_entry_twice_is_archived_once(ws):
    out = _archive(ws, ["test1", "test-signup-1"])
    assert len(out["archived"]) == 1 and len(_SpyBus.events) == 2


# ── Roles and ownership: exactly the entry page's rules ──────────────────────
# The tool is EDITOR-gated, but its handler checks each entry as the entry page does, so even a caller
# below the gate (or a role change mid-run) can never archive more than the entry page would allow.


def test_author_archives_own_drafts_and_skips_the_rest(ws):
    out = _archive(ws, ["mine", "test1", "mine_live"], ctx=_ctx(ws, WorkspaceRole.AUTHOR, who="author"))
    assert [a["id"] for a in out["archived"]] == [str(ws.ids["mine"])]
    reasons = {s["id"]: s["reason"] for s in out["skipped"]}
    assert reasons[str(ws.ids["test1"])] == "An AUTHOR can only change their own entries."
    assert "Only an EDITOR or above" in reasons[str(ws.ids["mine_live"])]  # own, but published
    assert _status(ws, "test1") == "inbox" and _status(ws, "mine_live") == "published"


def test_author_never_gets_an_approval_card_for_a_published_entry_they_cannot_archive(ws):
    ctx = _ctx(ws, WorkspaceRole.AUTHOR, who="author")
    assert get_tool("archive_entries").ask_first(ctx, {"entries": [str(ws.ids["mine_live"])]}) is None


def test_viewer_and_non_member_archive_nothing(ws):
    for role in (WorkspaceRole.VIEWER, None):
        out = _archive(ws, ["test1", "mine"], ctx=_ctx(ws, role))
        assert out["archived"] == [] and len(out["skipped"]) == 2
    assert _status(ws, "test1") == "inbox" and _SpyBus.events == []


# ── Batch cap and bad input ──────────────────────────────────────────────────


def test_batch_cap_refuses_the_whole_call(ws):
    refs = ["test1"] + [f"missing-{i}" for i in range(MAX_ARCHIVE_BATCH)]
    out = _archive(ws, refs)
    assert "at most 50" in out["error"]
    assert _status(ws, "test1") == "inbox" and _SpyBus.events == []


def test_no_entries_is_an_error(ws):
    assert "error" in _archive(ws, [])


# ── Published: ask first ─────────────────────────────────────────────────────


def test_published_entry_needs_approval_and_drafts_do_not(ws):
    ask = get_tool("archive_entries").ask_first
    flagged = ask(_ctx(ws), {"entries": [str(ws.ids["live"]), str(ws.ids["test1"])]})
    assert flagged.preview["summary"] == "Archive 2 entries — 1 is published and will come off the site"
    assert flagged.preview["targets"] == ["Spring Sale (published)", "Test Signup 1"]
    assert ask(_ctx(ws), {"entries": [str(ws.ids["test1"]), str(ws.ids["gone"])]}) is None
    assert _status(ws, "live") == "published"  # looking never writes


class _Provider(AIProvider):
    provider_type = "fake"
    display_name = "Fake"
    supports_tool_calls = True

    def __init__(self, results):
        self._results = list(results)
        self.seen_tools: list = []
        self.seen_messages: list = []

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.seen_tools.append(tools)
        self.seen_messages.append(list(messages))
        return self._results.pop(0)

    def complete(self, messages, model, options=None):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, messages, model, output_schema, options=None):  # pragma: no cover
        raise NotImplementedError

    def list_models(self):  # pragma: no cover
        return []

    def test_connection(self):  # pragma: no cover
        return True, ""


def _result(content="", tool_calls=None):
    return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2, model="m", tool_calls=tool_calls or [])


def _agent_tool(ws, *, can_park=True) -> AgentTool:
    spec = get_tool("archive_entries")
    run, check = bulk_writes.bind(spec, _ctx(ws), can_park=can_park)
    return AgentTool(
        name=spec.name, description=spec.description, input_schema=spec.input_schema, run=run, category="entries_archive", approval_check=check
    )


def _call(ws, *keys):
    return ToolCall(id="c1", name="archive_entries", arguments={"entries": [str(ws.ids[k]) for k in keys]})


def _park(ws):
    provider = _Provider([_result(tool_calls=[_call(ws, "live", "test1")])])
    res = run_agent_loop(provider, "m", [Message(role="user", content="archive these")], [_agent_tool(ws)])
    return res


def test_published_call_parks_and_archives_nothing_until_approved(ws):
    res = _park(ws)
    assert res.stopped_reason == "awaiting_approval"
    assert res.pending_calls[0].tool == "archive_entries" and "published" in res.pending_calls[0].preview["summary"]
    assert _status(ws, "live") == "published" and _status(ws, "test1") == "inbox" and _SpyBus.events == []


def test_approved_call_archives_everything_it_named(ws):
    res = _park(ws)
    provider = _Provider([_result(content="Archived both.")])
    done = run_agent_loop(
        provider, "m", [], [_agent_tool(ws)], resume=ResumeState(convo=res.convo, pending=res.pending_calls, decisions={"c1": "approve"})
    )
    assert done.stopped_reason == "complete"
    assert _status(ws, "live") == "archived" and _status(ws, "test1") == "archived"
    live = str(ws.ids["live"])
    assert [n for n, eid in _SpyBus.events if eid == live] == ["entry_updated", "entry_unpublished", "entry_archived"]


def test_refused_call_archives_nothing(ws):
    res = _park(ws)
    provider = _Provider([_result(content="Left them alone.")])
    done = run_agent_loop(
        provider, "m", [], [_agent_tool(ws)], resume=ResumeState(convo=res.convo, pending=res.pending_calls, decisions={"c1": "deny"})
    )
    assert done.stopped_reason == "complete"
    assert any(m.role == "tool" and "declined" in (m.content or "") for m in provider.seen_messages[0])
    assert _status(ws, "live") == "published" and _status(ws, "test1") == "inbox" and _SpyBus.events == []


def test_drafts_only_call_runs_without_parking(ws):
    provider = _Provider([_result(tool_calls=[_call(ws, "test1", "test2")]), _result(content="done")])
    res = run_agent_loop(provider, "m", [], [_agent_tool(ws)])
    assert res.stopped_reason == "complete" and _status(ws, "test1") == "archived" and _status(ws, "test2") == "archived"


def test_without_a_thread_a_published_call_is_refused_and_writes_nothing(ws):
    run = _agent_tool(ws, can_park=False).run
    out = json.loads(run({"entries": [str(ws.ids["live"]), str(ws.ids["test1"])]}))
    assert "cannot pause to ask" in out["error"] and out["published"][0]["id"] == str(ws.ids["live"])
    assert _status(ws, "live") == "published" and _status(ws, "test1") == "inbox"


def test_mcp_invoke_refuses_a_published_call_but_archives_drafts(ws):
    run = bulk_writes.unattended(get_tool("archive_entries"), _ctx(ws))
    assert "error" in json.loads(run({"entries": [str(ws.ids["live"])]})) and _status(ws, "live") == "published"
    assert json.loads(run({"entries": [str(ws.ids["test1"])]}))["archived"][0]["id"] == str(ws.ids["test1"])


# ── The incident: "delete these test entries" ────────────────────────────────


def test_asked_to_delete_test_entries_the_agent_archives_them_and_stages_no_revisions(ws):
    """A scripted model can't prove what a real one would choose, so this pins both halves: what steers
    the choice (the descriptions and the preamble rule the run is given) and what the choice does
    (entries archived, no suggestion staged on any entry)."""
    from marvin.services.ai.agents import REMOVING_RULE, workspace_preamble

    tools = [_agent_tool(ws), AgentTool(name="revise_entry", description=get_tool("revise_entry").description, input_schema={}, run=lambda a: "{}")]
    preamble = workspace_preamble("ws", [t.name for t in tools])
    assert REMOVING_RULE in preamble

    provider = _Provider([_result(tool_calls=[_call(ws, "test1", "test2")]), _result(content="Archived 2 test entries.")])
    res = run_agent_loop(provider, "m", [Message(role="system", content=preamble), Message(role="user", content="delete these test entries")], tools)
    assert [s.tool for s in res.steps] == ["archive_entries"]
    offered = {t.name: t.description for t in provider.seen_tools[0]}
    assert "delete" in offered["archive_entries"] and "use archive_entries" in offered["revise_entry"]
    assert _status(ws, "test1") == "archived" and _status(ws, "test2") == "archived"
    staged = ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.suggestion_json.isnot(None)).count()
    assert staged == 0


def test_preamble_without_archive_says_entries_cannot_be_deleted():
    from marvin.services.ai.agents import NO_REMOVE_RULE, REMOVING_RULE, workspace_preamble

    blocked = workspace_preamble("ws", ["revise_entry", "find_entries"])
    assert NO_REMOVE_RULE in blocked and REMOVING_RULE not in blocked
    assert NO_REMOVE_RULE not in workspace_preamble("ws", ["search_content"])
