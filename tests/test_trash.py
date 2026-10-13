"""The Trash (services/entries/trash.py, EntryService.trash / restore_from_trash).

Delete moves an entry to the Trash: status `trashed`, where it came from kept in metadata_json.trash,
`entry_trashed` emitted (plus `entry_unpublished` when it was live). Restore puts it back where it was —
except a published entry, which comes back as a draft. Trashed entries are out of sight everywhere but the
Trash collection and a fetch by id. Emptying (ADMIN/OWNER), "Delete forever" (a trashed entry only) and the
hourly auto-empty delete through EntryService.delete, so `entry_deleted` fires per entry. The workflow
`trash` op and the AI's trash_entries tool are the same move; neither can delete anything forever.

Service tests run over a throwaway workspace with commits turned into flushes and events sent to a spy
bus; the HTTP tests commit for real (the app opens its own sessions) and purge the workspace afterwards.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.platform import Entries, EntryTypes
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.categories import CATEGORY_BY_ID, category_of
from marvin.services.entries import EntryService
from marvin.services.entries import trash as T


class _SpyBus:
    events: list = []

    def __init__(self, *a, **k):
        pass

    def dispatch(self, *, event_type, entity_id=None, **_):
        _SpyBus.events.append((event_type.name, str(entity_id)))


class _User:
    def __init__(self, uid, gid, role: WorkspaceRole | None):
        self.id, self.admin, self.platform_role = uid, False, "NONE"
        self.workspace_memberships = [SimpleNamespace(group_id=gid, workspace_role=role)] if role else []

    def get_workspace_role(self, group_id):
        return next((m.workspace_role for m in self.workspace_memberships if str(m.group_id) == str(group_id)), None)


def _make_workspace(session, prefix: str):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=session, name=f"{prefix}-{marker}", slug=f"{prefix}-{marker}")
    g.id = gid
    session.add(g)
    session.flush()
    if session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        session.add(GroupPreferencesModel(session=session, group_id=gid))
    users = {}
    for who in ("editor", "author"):
        uid = uuid.uuid4()
        session.execute(
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
    et = EntryTypes(session=session, group_id=gid, name="Note", slug=f"note-{marker}", schema_json={})
    et.id = uuid.uuid4()
    session.add(et)
    session.flush()

    def entry(slug, status="draft", owner="editor", **fields):
        e = Entries(session=session, group_id=gid, entry_type_id=et.id, title=slug.replace("-", " ").title(), slug=f"{slug}-{marker}", **fields)
        e.status = status
        e.created_by = users[owner]
        session.add(e)
        session.flush()
        return e.id

    return SimpleNamespace(gid=gid, users=users, entry_type=et, entry=entry, session=session)


@fixture
def ws(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _SpyBus)
    _SpyBus.events = []
    yield _make_workspace(db_session, "trash")
    db_session.rollback()


def _svc(ws, who="editor"):
    return EntryService(ws.session, ws.gid, actor_id=ws.users[who])


def _row(ws, eid) -> Entries:
    ws.session.expire_all()
    return ws.session.get(Entries, eid)


def _names(eid) -> list[str]:
    return [name for name, ent in _SpyBus.events if ent == str(eid)]


# ── Trash and restore ─────────────────────────────────────────────────────────


def test_trashing_records_where_it_came_from_and_emits_entry_trashed(ws):
    eid = ws.entry("a-draft", "draft", metadata_json={"keep": 1})
    _svc(ws).trash(eid)
    row = _row(ws, eid)
    assert row.status == "trashed"
    record = row.metadata_json["trash"]
    assert record["previous_status"] == "draft" and record["trashed_by"] == str(ws.users["editor"])
    assert T.trashed_at(row) is not None and row.metadata_json["keep"] == 1
    assert _names(eid) == ["entry_updated", "entry_trashed"]

    _SpyBus.events = []
    _svc(ws).trash(eid)  # already there: a no-op
    assert _SpyBus.events == []


def test_trashing_a_published_entry_unpublishes_it_and_clears_a_schedule(ws):
    eid = ws.entry("live", "published")
    sched = ws.entry("scheduled", "approved", publish_at=datetime.now(UTC) + timedelta(days=1))
    _svc(ws).trash(eid)
    _svc(ws).trash(sched)
    assert _names(eid) == ["entry_updated", "entry_unpublished", "entry_trashed"]
    assert _row(ws, eid).published_at is None
    assert _row(ws, sched).publish_at is None  # the scheduled publish can't put it (or its restore) live


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("draft", "draft"),
        ("inbox", "inbox"),
        ("needs_review", "needs_review"),
        ("approved", "approved"),
        ("archived", "archived"),
        ("published", "draft"),
    ],
)
def test_restore_returns_the_entry_where_it_was_but_never_republishes(ws, before, after):
    eid = ws.entry(f"e-{before}", before)
    _svc(ws).trash(eid)
    _SpyBus.events = []
    _svc(ws).restore_from_trash(eid)
    row = _row(ws, eid)
    assert row.status == after
    assert "trash" not in (row.metadata_json or {})
    assert _names(eid) == ["entry_updated", "entry_restored"]  # never entry_published / entry_archived


def test_restore_without_a_record_comes_back_as_a_draft(ws):
    eid = ws.entry("odd", "trashed")  # e.g. a restored backup: no metadata_json.trash
    _svc(ws).restore_from_trash(eid)
    assert _row(ws, eid).status == "draft"


def test_creating_an_entry_in_the_trash_is_refused():
    from pydantic import ValidationError

    from marvin.schemas.platform import EntryCreate

    with pytest.raises(ValidationError):
        EntryCreate(entry_type_id=uuid.uuid4(), title="x", status="trashed")


# ── Out of sight ──────────────────────────────────────────────────────────────


def test_system_trash_collection_is_seeded_and_holds_only_trashed_entries(ws):
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.services.collections.smart_collections import sync_entry
    from marvin.services.collections.system_collections import seed_system_workflow_collections

    seed_system_workflow_collections(ws.session, ws.gid)
    assert seed_system_workflow_collections(ws.session, ws.gid) == 0  # idempotent: existing workspaces get it once
    by_slug = {c.slug: c for c in ws.session.query(Collections).filter(Collections.group_id == ws.gid)}
    trash = by_slug["trash"]
    assert (trash.name, trash.icon, trash.is_system, trash.is_public) == ("Trash", "🗑️", True, False)
    assert trash.smart_rules["statuses"] == ["trashed"] and trash.sort_order > by_slug["archive"].sort_order
    # a user smart collection by type would match a trashed entry on its rules — the Trash wins
    mine = Collections(
        session=ws.session, group_id=ws.gid, slug="notes", name="Notes", is_smart=True, smart_rules={"entry_types": [ws.entry_type.slug]}
    )
    ws.session.add(mine)
    ws.session.flush()

    eid = ws.entry("goner", "draft")
    sync_entry(ws.session, ws.gid, _row(ws, eid))

    def member_of() -> set[str]:
        ws.session.flush()  # sync_entry adds/deletes junction rows without flushing
        ids = {r.collection_id for r in ws.session.query(EntryCollections).filter(EntryCollections.entry_id == eid)}
        return {slug for slug, c in by_slug.items() if c.id in ids} | ({"notes"} if mine.id in ids else set())

    assert member_of() == {"drafts", "notes"}
    _svc(ws).trash(eid)
    sync_entry(ws.session, ws.gid, _row(ws, eid))
    assert member_of() == {"trash"}
    _svc(ws).restore_from_trash(eid)
    sync_entry(ws.session, ws.gid, _row(ws, eid))
    assert member_of() == {"drafts", "notes"}


def test_entry_query_leaves_out_trashed_entries_unless_asked_by_name(ws):
    from marvin.services.entries.query import run

    keep, gone = ws.entry("keep"), ws.entry("gone")
    _svc(ws).trash(gone)
    ids = lambda spec: {r.id for r in run(ws.session, ws.gid, spec).rows}  # noqa: E731
    assert ids({}) == {keep}
    assert ids({"status": "draft"}) == {keep}
    assert ids({"status": "trashed"}) == {gone}


def test_counts_show_the_trash_apart_from_the_total(ws):
    from marvin.services.entries.entry_service import count_by_status

    ws.entry("one", "draft")
    _svc(ws).trash(ws.entry("two", "draft"))
    counts = count_by_status(ws.session, ws.gid)
    assert counts["trashed"] == 1 and counts["draft"] == 1 and counts["total"] == 1


def test_a_repeat_form_submission_does_not_find_a_trashed_entry(ws):
    from marvin.services.entries.query import find_by_identity

    eid = ws.entry("signup", "draft", data_json={"email": "a@b.test"})
    assert find_by_identity(ws.session, ws.gid, ws.entry_type.id, "email", "a@b.test").id == eid
    _svc(ws).trash(eid)
    assert find_by_identity(ws.session, ws.gid, ws.entry_type.id, "email", "a@b.test") is None


# ── Emptying, deleting forever and auto-empty ─────────────────────────────────


def test_empty_trash_deletes_only_trashed_entries_each_with_entry_deleted(ws):
    keep = ws.entry("keep")
    gone = [ws.entry(f"gone-{i}") for i in range(3)]
    for eid in gone:
        _svc(ws).trash(eid)
    _SpyBus.events = []
    assert T.empty_trash(ws.session, ws.gid, actor_id=ws.users["editor"]) == 3
    assert all(_row(ws, eid) is None for eid in gone) and _row(ws, keep) is not None
    assert sorted(_SpyBus.events) == sorted(("entry_deleted", str(eid)) for eid in gone)
    assert T.empty_trash(ws.session, ws.gid) == 0  # a second run (another replica, a double click) deletes nothing


def test_delete_forever_skips_entries_not_in_the_trash(ws):
    live = ws.entry("live", "published")
    assert T.delete_forever(ws.session, ws.gid, [live]) == 0
    assert _row(ws, live) is not None


def _trash_aged(ws, slug: str, days_ago: float):
    """A trashed entry whose trashed_at is `days_ago` days back."""
    eid = ws.entry(slug)
    _svc(ws).trash(eid)
    row = _row(ws, eid)
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    row.metadata_json = {**row.metadata_json, "trash": {**row.metadata_json["trash"], "trashed_at": when}}
    ws.session.flush()
    return eid


def _set_override(ws, days):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).one().trash_auto_empty_days = days
    ws.session.flush()


def _purged(ws) -> set:
    _SpyBus.events = []
    T.purge_expired(ws.session)
    return {uuid.UUID(eid) for name, eid in _SpyBus.events if name == "entry_deleted"}


def test_auto_empty_inherits_the_platform_default_of_30_days(ws):
    assert T.auto_empty_status(ws.session, ws.gid) == {"platform_default_days": 30, "workspace_override_days": None, "effective_days": 30}
    old, recent = _trash_aged(ws, "old", 31), _trash_aged(ws, "recent", 29)
    assert _purged(ws) == {old}
    assert _row(ws, recent) is not None


@pytest.mark.parametrize(("override", "expect"), [(7, {"d10", "d40"}), (90, set()), (0, set())])
def test_a_workspace_override_shorter_longer_or_never_wins_over_the_platform(ws, override, expect):
    aged = {"d10": _trash_aged(ws, "d10", 10), "d40": _trash_aged(ws, "d40", 40)}
    _set_override(ws, override)
    assert T.auto_empty_status(ws.session, ws.gid)["effective_days"] == override
    assert _purged(ws) == {aged[k] for k in expect}


def test_platform_never_with_a_workspace_override_of_30(ws):
    T.set_platform_auto_empty_days(ws.session, 0)
    old = _trash_aged(ws, "old", 45)
    assert _purged(ws) == set()  # inherits Never
    _set_override(ws, 30)
    assert _purged(ws) == {old}


def test_auto_empty_never_touches_restored_entries_or_ones_without_a_trashed_at(ws):
    restored = _trash_aged(ws, "restored", 60)
    _svc(ws).restore_from_trash(restored)
    undated = ws.entry("undated", "trashed")  # no record: can't be aged, so only emptying removes it
    assert _purged(ws) == set()
    assert _row(ws, restored).status == "draft" and _row(ws, undated) is not None


def test_auto_empty_task_is_registered_hourly():
    import inspect

    from marvin.app import start_scheduler

    source = inspect.getsource(start_scheduler)
    hourly = source[source.index("register_hourly(") :]
    assert "scheduler_tasks.empty_expired_trash" in hourly[: hourly.index(")")]


def test_workspace_override_only_takes_the_offered_choices():
    from pydantic import ValidationError

    from marvin.schemas.group.preferences import GroupPreferencesUpdate

    assert GroupPreferencesUpdate(trash_auto_empty_days=7).trash_auto_empty_days == 7
    assert GroupPreferencesUpdate(trash_auto_empty_days=None).model_dump(exclude_unset=True) == {"trash_auto_empty_days": None}
    with pytest.raises(ValidationError):
        GroupPreferencesUpdate(trash_auto_empty_days=5)


# ── Workflow `trash` op ───────────────────────────────────────────────────────


def _run_op(ws, op, eid):
    from marvin.services.automation.actions.entry import run_entry_action
    from marvin.services.automation.authz import ROLE_ADMIN

    ctx = {"event": {"entry_id": str(eid)}, "steps": {}, "depth": 0}
    return run_entry_action(ws.session, ws.gid, {"kind": "entry", "op": op}, ctx, authorizer_role=ROLE_ADMIN)


def test_workflow_trash_op_sends_what_op_sends_says_and_skips_trashed_entries(ws):
    from marvin.services.automation.actions.entry import OP_SENDS

    eid = ws.entry("wf")
    out = _run_op(ws, "trash", eid)
    assert out["status"] == "trashed" and sorted(_names(eid)) == sorted(OP_SENDS["trash"])
    _SpyBus.events = []
    assert _run_op(ws, "trash", eid)["skipped"] is True and _SpyBus.events == []


def test_workflow_restore_op_brings_a_trashed_published_entry_back_as_a_draft(ws):
    eid = ws.entry("was-live", "published")
    _svc(ws).trash(eid)
    _SpyBus.events = []
    assert _run_op(ws, "restore", eid)["status"] == "draft"
    assert _names(eid) == ["entry_updated", "entry_restored"]


def test_a_target_of_all_entries_with_trash_skips_what_is_already_there(ws):
    from marvin.services.automation.selector import resolve_target_entities

    a, b = ws.entry("a"), ws.entry("b")
    _svc(ws).trash(a)
    rows, total = resolve_target_entities(ws.session, ws.gid, {"entity": "entry", "query": {}}, {})
    assert [r.id for r in rows] == [b] and total == 1


def test_the_definition_schema_offers_trash_but_no_permanent_delete():
    from typing import get_args

    from marvin.schemas.group.automation_definition import EntryAction

    ops = set(get_args(EntryAction.model_fields["op"].annotation))
    assert "trash" in ops and not ops & {"delete", "empty_trash", "delete_forever"}


# ── AI: trash_entries ─────────────────────────────────────────────────────────


def _ctx(ws, role=WorkspaceRole.EDITOR, who="editor") -> ToolContext:
    return ToolContext(session=ws.session, group_id=ws.gid, user=_User(ws.users[who], ws.gid, role))


def _trash_tool(ws, refs, ctx=None) -> dict:
    return json.loads(get_tool("trash_entries").handler(ctx or _ctx(ws), {"entries": [str(r) for r in refs]}))


def test_trash_entries_sits_in_its_own_matrix_row_like_archive():
    from marvin.services.ai.operations.base import ROLE_EDITOR

    spec = get_tool("trash_entries")
    assert spec.read_only is False and spec.min_role == ROLE_EDITOR
    assert {"agent", "mcp"} <= set(spec.sources) and spec.ask_first is not None
    assert category_of("trash_entries", read_only=False) == "entries_trash" and CATEGORY_BY_ID["entries_trash"].writes
    # nothing the AI can call empties the Trash or deletes forever
    from marvin.services.ai.tools.base import TOOL_REGISTRY

    assert not {n for n in TOOL_REGISTRY if "empty" in n or "delete" in n or "purge" in n}


def test_trash_matrix_defaults_match_archive():
    from marvin.services.ai.agents import SYSTEM_AGENTS, AgentSpec, default_policy, resolve_policy
    from marvin.services.ai.operations.base import ROLE_AUTHOR, ROLE_EDITOR

    marvin = SYSTEM_AGENTS["marvin"]
    custom = AgentSpec(slug="w", name="W", allow_writes=True)
    for spec in (marvin, custom, AgentSpec(slug="r", name="R")):
        assert default_policy(spec, "entries_trash") == default_policy(spec, "entries_archive")
    assert resolve_policy(marvin, "trash_entries", "entries_trash", ROLE_AUTHOR)[0] == "block"  # authors don't get it
    assert resolve_policy(marvin, "trash_entries", "entries_trash", ROLE_EDITOR)[0] == "allow"


def test_trash_entries_trashes_drafts_through_the_human_path_and_reports_the_rest(ws):
    draft, done, mine = ws.entry("d1"), ws.entry("d2"), ws.entry("mine", owner="author")
    _svc(ws).trash(done)
    _SpyBus.events = []
    out = _trash_tool(ws, [draft, done, "no-such-entry"])
    assert [t["id"] for t in out["trashed"]] == [str(draft)] and out["trashed"][0]["was"] == "draft"
    assert out["alreadyTrashed"] == [{"id": str(done), "title": "D2"}]
    assert [s["reason"] for s in out["skipped"]] == ["not found in this workspace"]
    assert "Restore" in out["undo"] and _row(ws, draft).status == "trashed"
    assert _names(draft) == ["entry_updated", "entry_trashed"]
    # an AUTHOR may trash their own draft only (same rule as the entry page)
    author = _trash_tool(ws, [mine, draft], ctx=_ctx(ws, WorkspaceRole.AUTHOR, "author"))
    assert [t["id"] for t in author["trashed"]] == [str(mine)]


def test_trash_entries_finds_an_entry_by_its_exact_title_when_only_one_has_it(ws):
    # Seen live: the model listed entries by title and passed the title back instead of the slug.
    unique, twin_a, twin_b = ws.entry("only-one"), ws.entry("twin-a"), ws.entry("twin-b")
    for eid in (twin_a, twin_b):
        ws.session.get(Entries, eid).title = "Same Title"
    ws.session.commit()
    out = _trash_tool(ws, [_row(ws, unique).title.upper(), "Same Title"])
    assert [t["id"] for t in out["trashed"]] == [str(unique)]
    assert [s["entry"] for s in out["skipped"]] == ["Same Title"]  # ambiguous: never guesses


def _restore_tool(ws, refs, ctx=None) -> dict:
    from marvin.services.ai.tools.builtins_trash import restore_entries

    return json.loads(restore_entries(ctx or _ctx(ws), {"entries": refs}))


def test_restore_entries_takes_entries_out_of_the_trash_like_the_trash_view(ws):
    live, draft, untouched = ws.entry("was-live", "published"), ws.entry("was-draft"), ws.entry("never-trashed")
    _svc(ws).trash(live)
    _svc(ws).trash(draft)
    _SpyBus.events = []
    out = _restore_tool(ws, [live, draft, untouched, "no-such-entry"])
    assert {r["id"]: r["status"] for r in out["restored"]} == {str(live): "draft", str(draft): "draft"}  # never back on the site
    assert [n["id"] for n in out["notTrashed"]] == [str(untouched)]
    assert [s["reason"] for s in out["skipped"]] == ["not found in this workspace"]
    assert _row(ws, live).status == "draft" and _row(ws, draft).status == "draft"
    assert _names(draft) == ["entry_updated", "entry_restored"]


def test_restore_entries_shares_the_trash_matrix_row():
    from marvin.services.ai.tools.categories import CATEGORY_BY_TOOL

    assert CATEGORY_BY_TOOL["restore_entries"] == CATEGORY_BY_TOOL["trash_entries"] == "entries_trash"


def test_trash_entries_asks_first_for_a_published_entry(ws):
    live, draft = ws.entry("spring-sale", "published"), ws.entry("d")
    ask = get_tool("trash_entries").ask_first
    flagged = ask(_ctx(ws), {"entries": [str(live), str(draft)]})
    assert flagged.preview["action"] == "trash"
    assert flagged.preview["summary"] == "Move 2 entries to the Trash — 1 is published and will come off the site"
    assert ask(_ctx(ws), {"entries": [str(draft)]}) is None
    assert _row(ws, live).status == "published"


def test_the_preamble_sends_deletes_to_the_trash_and_retiring_to_archive():
    from marvin.services.ai.agents import ARCHIVE_RULE, REMOVING_RULE, TRASH_RULE, workspace_preamble

    both = workspace_preamble("ws", ["trash_entries", "archive_entries", "revise_entry"])
    assert TRASH_RULE in both and ARCHIVE_RULE in both and REMOVING_RULE not in both
    assert "only a person can empty it" in TRASH_RULE
    assert REMOVING_RULE in workspace_preamble("ws", ["archive_entries"])  # no Trash: archive stays the way out


# ── HTTP: DELETE, restore, empty, and what lists show ─────────────────────────


@fixture
def http(db_session):
    """A committed workspace for the app's own sessions; sign the editor in with any role."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users
    from marvin.services.collections.system_collections import seed_system_workflow_collections
    from marvin.services.group.group_purge import purge_group_dependents

    w = _make_workspace(db_session, "trash-http")
    seed_system_workflow_collections(db_session, w.gid)
    db_session.commit()

    def sign_in(role: WorkspaceRole) -> TestClient:
        from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

        def role_in(group_id):
            return role if str(group_id) == str(w.gid) else None

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=w.users["editor"],
            group_id=w.gid,
            active_group_id=w.gid,
            admin=False,
            is_superuser=False,
            full_name="editor",
            email="editor@t.test",
            platform_role=PlatformRole.NONE,
            workspace_memberships=[SimpleNamespace(group_id=w.gid, workspace_role=role)],
            get_workspace_role=role_in,
            has_workspace_role=lambda group_id, required: role_in(group_id) is not None
            and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
        )
        return TestClient(app)

    def entry(slug, status="draft"):
        eid = w.entry(slug, status)
        db_session.commit()
        return eid

    yield SimpleNamespace(gid=w.gid, sign_in=sign_in, entry=entry, session=db_session)
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    purge_group_dependents(db_session, w.gid)
    db_session.query(Users).filter(Users.group_id == w.gid).delete()
    db_session.query(Groups).filter(Groups.id == w.gid).delete()
    db_session.commit()


E = "/api/platform/entries"


def test_delete_moves_to_the_trash_and_permanent_needs_a_trashed_entry(http):
    client = http.sign_in(WorkspaceRole.EDITOR)
    eid = http.entry("doomed")
    assert client.delete(f"{E}/{eid}?permanent=true").status_code == 409  # not in the Trash yet
    res = client.delete(f"{E}/{eid}")
    assert res.status_code == 200 and res.json()["trashed"] is True
    assert client.get(f"{E}/{eid}").json()["status"] == "trashed"  # a fetch by id still shows it
    assert str(eid) not in {e["id"] for e in client.get(E).json()}  # the list doesn't
    assert client.patch(f"{E}/{eid}", json={"title": "x"}).status_code == 409  # read-only in the Trash
    assert client.delete(f"{E}/{eid}?permanent=true").json()["deleted"] is True
    assert client.get(f"{E}/{eid}").status_code == 404


def test_restore_endpoint_and_patch_cannot_trash(http):
    client = http.sign_in(WorkspaceRole.EDITOR)
    eid = http.entry("back", "published")
    assert client.patch(f"{E}/{eid}", json={"status": "trashed"}).status_code == 422
    client.delete(f"{E}/{eid}")
    res = client.post(f"{E}/{eid}/restore")
    assert res.status_code == 200 and res.json()["status"] == "draft"
    assert client.post(f"{E}/{eid}/restore").status_code == 409  # not in the Trash any more


def test_empty_trash_is_admin_only_and_returns_the_count(http):
    ids = [http.entry(f"e{i}") for i in range(2)]
    editor = http.sign_in(WorkspaceRole.EDITOR)
    for eid in ids:
        editor.delete(f"{E}/{eid}")
    assert editor.get(f"{E}/trash").json()["count"] == 2
    assert editor.post(f"{E}/trash/empty").status_code == 403
    admin = http.sign_in(WorkspaceRole.ADMIN)
    res = admin.post(f"{E}/trash/empty")
    assert res.status_code == 200 and res.json()["deleted"] == 2
    assert admin.get(f"{E}/trash").json() == {"count": 0, "platform_default_days": 30, "workspace_override_days": None, "effective_days": 30}


def test_collections_list_trashed_entries_only_in_the_trash(http):
    from marvin.db.models.platform.collections import Collections

    client = http.sign_in(WorkspaceRole.EDITOR)
    manual = Collections(session=http.session, group_id=http.gid, slug="picks", name="Picks")
    http.session.add(manual)
    http.session.commit()
    keep, gone = http.entry("keep"), http.entry("gone")
    for eid in (keep, gone):
        assert client.post(f"{E}/{eid}/collections/{manual.id}").status_code == 201
    client.delete(f"{E}/{gone}")

    trash_id = http.session.query(Collections.id).filter_by(group_id=http.gid, slug="trash").scalar()
    listed = lambda cid: {e["id"] for e in client.get(f"/api/platform/collections/{cid}/entries").json()}  # noqa: E731
    assert listed(manual.id) == {str(keep)}
    assert listed(trash_id) == {str(gone)}
    counts = {c["slug"]: c["entryCount"] for c in client.get("/api/platform/collections").json()}
    assert counts["picks"] == 1 and counts["trash"] == 1
    client.post(f"{E}/{gone}/restore")
    assert listed(manual.id) == {str(keep), str(gone)}  # membership kept, so a restore puts it back


def test_workspace_trash_settings_read_and_override(http):
    admin = http.sign_in(WorkspaceRole.ADMIN)
    url = f"/api/groups/{http.gid}/preferences"
    assert admin.patch(url, json={"trash_auto_empty_days": 7}).status_code == 200
    assert admin.get(f"{url}/trash").json() == {"platform_default_days": 30, "workspace_override_days": 7, "effective_days": 7}
    assert admin.patch(url, json={"trash_auto_empty_days": 5}).status_code == 422
    assert admin.patch(url, json={"trash_auto_empty_days": None}).status_code == 200  # back to inheriting
    assert admin.get(f"{url}/trash").json()["workspace_override_days"] is None
    assert http.sign_in(WorkspaceRole.EDITOR).patch(url, json={"trash_auto_empty_days": 0}).status_code == 403


def test_a_collection_whose_entries_are_all_in_the_trash_can_be_deleted(ws):
    """Deleting an entry trashes it, so counting trashed members as "in use" left such a collection undeletable
    (the CLI's create-entry / delete-entry / delete-collection run got 409). Entries outside the Trash still block."""
    from fastapi import HTTPException

    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.repos.repository_factory import AllRepositories

    kept, binned = ws.entry("kept"), ws.entry("binned")
    col = Collections(session=ws.session, group_id=ws.gid, name="Shelf", slug=f"shelf-{uuid.uuid4().hex[:6]}")
    ws.session.add(col)
    ws.session.flush()
    ws.session.add_all([EntryCollections(entry_id=kept, collection_id=col.id), EntryCollections(entry_id=binned, collection_id=col.id)])
    ws.session.flush()
    repo = AllRepositories(ws.session, group_id=ws.gid).collections

    _svc(ws).trash(binned)
    with pytest.raises(HTTPException) as refused:
        repo.delete(col.id)
    assert refused.value.status_code == 409  # `kept` is still in it

    _svc(ws).trash(kept)
    repo.delete(col.id)
    assert ws.session.get(Collections, col.id) is None
    _svc(ws).restore_from_trash(kept)  # comes back, without the collection that's gone
    assert _row(ws, kept).status == "draft"
