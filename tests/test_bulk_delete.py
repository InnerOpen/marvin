"""Bulk delete (services/entries/bulk_delete.py): the entries a saved search selects, moved to the Trash or deleted for good,
in chunks, with one summary event and the bookkeeping done in bulk.

The workspace here is committed for real (the job commits per chunk, and the HTTP tests' app opens its own sessions), so
each test makes its own and purges it afterwards. The speed test seeds 2,000 entries with one insert; run it on Postgres
(`DB_ENGINE=postgres POSTGRES_DB=marvin_test_<name>`) for the production picture: it prints the time it took.
"""

import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.platform import Entries, EntryCollections, EntryTypes
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.entries import EntryService
from marvin.services.entries import bulk_delete as B

TYPES = ("chapter", "scene", "beat", "speech-line", "sound", "cast-member", "take", "casting")
NAMES = {"speech-line": "Speech line", "cast-member": "Character"}


class _Spy:
    """An event bus that only remembers what it was asked to send."""

    def __init__(self, *a, **k):
        self.sent: list = []

    def dispatch(self, *, event_type, document_data=None, message="", **_):
        _Spy.last.append((event_type.name, document_data, message))


_Spy.last = []


@fixture
def ws(db_session, monkeypatch):
    """A committed workspace with the story types, an editor and an admin. Events go to the spy."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users
    from marvin.services.collections.system_collections import seed_system_workflow_collections
    from marvin.services.group.group_purge import purge_group_dependents

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Spy)
    _Spy.last = []
    session = db_session
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=session, name=f"bulk-{marker}", slug=f"bulk-{marker}")
    g.id = gid
    session.add(g)
    session.flush()
    if session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        session.add(GroupPreferencesModel(session=session, group_id=gid))
    users = {}
    for who in ("editor", "author", "admin"):
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
    types = {}
    for slug in (*TYPES, "story", "note"):
        et = EntryTypes(session=session, group_id=gid, name=NAMES.get(slug, slug.title()), slug=slug, schema_json={})
        et.id = uuid.uuid4()
        session.add(et)
        types[slug] = et.id
    session.flush()
    seed_system_workflow_collections(session, gid)
    session.commit()

    def seed(story: str, n: int, *, status="draft", owner="editor") -> list:
        """n entries of the story types spread over TYPES, data.story = story, slugs `<story>-<type>-<i>`. One insert."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).replace(tzinfo=None)
        rows = []
        for i in range(n):
            t = TYPES[i % len(TYPES)]
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "group_id": gid,
                    "entry_type_id": types[t],
                    "title": f"{story} {t} {i}",
                    "slug": f"{story}-{t}-{i}",
                    "data_json": {"story": story, "n": i},
                    "status": status,
                    "created_by": users[owner],
                    "created_at": now,
                    "update_at": now,
                }
            )
        session.execute(Entries.__table__.insert(), rows)
        session.commit()
        return [r["id"] for r in rows]

    def one(slug: str, type_slug="note", status="draft", **data) -> uuid.UUID:
        e = Entries(session=session, group_id=gid, entry_type_id=types[type_slug], title=slug, slug=slug, data_json=data)
        e.status = status
        e.created_by = users["editor"]
        session.add(e)
        session.commit()
        return e.id

    yield SimpleNamespace(gid=gid, session=session, users=users, types=types, seed=seed, one=one, bus=_Spy())
    app.dependency_overrides.pop(get_current_user, None)
    session.rollback()
    session.query(AIEmbeddingModel).filter(AIEmbeddingModel.group_id == gid).delete(synchronize_session=False)
    session.query(EntryAssets).filter(EntryAssets.asset_id.in_(session.query(Assets.id).filter(Assets.group_id == gid))).delete(
        synchronize_session=False
    )
    session.query(Assets).filter(Assets.group_id == gid).delete(synchronize_session=False)
    purge_group_dependents(session, gid)
    session.query(Users).filter(Users.group_id == gid).delete()
    session.query(Groups).filter(Groups.id == gid).delete()
    session.commit()


def story_spec(story: str, *, with_trash: bool = False) -> dict:
    spec = {"entry_types": list(TYPES), "fields": {"story": story}}
    if with_trash:
        spec["statuses"] = ["inbox", "draft", "needs_review", "approved", "published", "archived", "trashed"]
    return spec


def _statuses(ws, ids) -> dict:
    ws.session.expire_all()
    return {r[0]: r[1] for r in ws.session.query(Entries.id, Entries.status).filter(Entries.id.in_(ids))}


def _asset(ws, slug: str) -> Assets:
    a = Assets(
        session=ws.session,
        group_id=ws.gid,
        slug=slug,
        name=slug,
        original_filename=f"{slug}.png",
        filename=f"{slug}.png",
        extension="png",
        file_size=1,
        mime_type="image/png",
        asset_type="image",
        checksum=slug,
        storage_provider="local",
        storage_key=f"{ws.gid.hex}/{slug}.png",
        uploaded_by=ws.users["editor"],
    )
    ws.session.add(a)
    ws.session.flush()
    return a


def _bulk_events() -> list:
    return [e for e in _Spy.last if e[0] == "entries_bulk_deleted"]


# ── Preview ────────────────────────────────────────────────────────────────────────────────────────


def test_preview_counts_by_type_in_words_and_changes_nothing(ws):
    ids = ws.seed("onion", 16)
    found = B.preview(ws.session, ws.gid, story_spec("onion"))
    assert found["total"] == 16 and found["by_type"] == dict.fromkeys(TYPES, 2)
    assert found["text"] == "2 beats, 2 characters, 2 castings, 2 chapters, 2 scenes, 2 sounds, 2 speech lines and 2 takes"
    assert set(_statuses(ws, ids).values()) == {"draft"}
    assert _Spy.last == []


@pytest.mark.parametrize(
    ("spec", "says"),
    [
        ({}, "too wide"),
        ({"statuses": ["draft"]}, "too wide"),
        ({"entry_types": ["beat"], "stroy": "x"}, "unknown query key"),
        ({"entry_types": ["beat"], "fields": {"story": ""}}, "has no value"),
        ({"entry_types": ["beat"], "where": [{"field": "story", "op": "like", "value": "x"}]}, "unknown where op"),
        ("beat", "must be an object"),
    ],
)
def test_a_spec_that_could_widen_or_means_nothing_is_refused(ws, spec, says):
    with pytest.raises(B.BulkDeleteError, match=says):
        B.preview(ws.session, ws.gid, spec)


# ── Trash ──────────────────────────────────────────────────────────────────────────────────────────


def test_trash_moves_only_the_story_and_records_it_like_one_by_one(ws):
    mine = ws.seed("onion", 24)
    other = ws.seed("shoals", 8)
    story = ws.one("onion", "story")
    note = ws.one("onion-note", "note", story="onion")  # a type the spec does not name
    found = B.preview(ws.session, ws.gid, story_spec("onion"))
    done = B.execute(
        ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=found["total"], actor_id=ws.users["editor"], event_bus=ws.bus
    )
    assert done["deleted"] == found["total"] == 24 and done["by_type"] == found["by_type"]
    assert set(_statuses(ws, mine).values()) == {"trashed"}
    assert set(_statuses(ws, [*other, story, note]).values()) == {"draft"}
    row = ws.session.get(Entries, mine[0])
    record = row.metadata_json["trash"]
    assert record["previous_status"] == "draft" and record["trashed_by"] == str(ws.users["editor"]) and record["trashed_at"]
    assert record["slug"] == "onion-chapter-0" and row.slug.startswith("onion-chapter-0--trashed-")
    # the preview is what went, and a second preview finds nothing left
    assert B.preview(ws.session, ws.gid, story_spec("onion"))["total"] == 0


def test_the_summary_event_fires_once_and_no_entry_event_does(ws):
    ws.seed("onion", 40)
    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=40, description="what the import made for Onion", chunk_size=7)
    assert [e[0] for e in _Spy.last] == ["entries_bulk_deleted"]
    _name, data, message = _Spy.last[0]
    assert data.total == 40 and data.mode == "trash" and data.by_type["beat"] == 5 and data.complete
    assert message.startswith("40 entries moved to the Trash from what the import made for Onion: ")


def test_a_changed_selection_deletes_nothing(ws):
    ids = ws.seed("onion", 10)
    with pytest.raises(B.BulkDeleteMismatch) as e:
        B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=9)
    assert e.value.preview["total"] == 10
    with pytest.raises(B.BulkDeleteError, match="confirm_total is required"):
        B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=None)
    assert set(_statuses(ws, ids).values()) == {"draft"} and _bulk_events() == []


def test_chunks_are_transactions_of_their_own(ws):
    """Another session sees the first chunk trashed while the rest are not: no one transaction holds the job."""
    ids = ws.seed("onion", 1200)
    from marvin.db.db_setup import session_context

    seen = []

    def progress(done, total):
        with session_context() as other:
            seen.append((done, other.query(Entries).filter(Entries.id.in_(ids), Entries.status == "trashed").count()))

    done = B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=1200, progress=progress, pause=0)
    assert done["chunks"] == 3
    assert seen == [(500, 500), (1000, 1000), (1200, 1200)]


def test_restore_brings_entries_back_with_their_slug_and_links(ws):
    ids = ws.seed("onion", 8)
    beat = next(i for i in ids if ws.session.get(Entries, i).slug == "onion-beat-2")
    picks = Collections(session=ws.session, group_id=ws.gid, slug="picks", name="Picks")
    ws.session.add(picks)
    asset = _asset(ws, "still")
    ws.session.flush()
    ws.session.add_all(
        [EntryCollections(entry_id=beat, collection_id=picks.id, sort_order=0), EntryAssets(entry_id=beat, asset_id=asset.id, position=0)]
    )
    ws.session.commit()

    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=8)
    trash = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="trash").one()
    in_trash = {r[0] for r in ws.session.query(EntryCollections.entry_id).filter_by(collection_id=trash.id)}
    assert set(ids) <= in_trash  # the Trash view lists them (it lists by membership)

    EntryService(ws.session, ws.gid, actor_id=ws.users["editor"]).restore_from_trash(beat)
    ws.session.expire_all()
    row = ws.session.get(Entries, beat)
    assert (row.status, row.slug) == ("draft", "onion-beat-2") and "trash" not in (row.metadata_json or {})
    assert {r[0] for r in ws.session.query(EntryCollections.collection_id).filter_by(entry_id=beat)} >= {picks.id}
    assert ws.session.query(EntryAssets).filter_by(entry_id=beat, asset_id=asset.id).count() == 1


def test_the_slugs_are_free_for_an_import_made_again(ws):
    from marvin.repos.repository_factory import AllRepositories

    ids = ws.seed("onion", 8)
    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=8)
    again = AllRepositories(ws.session, group_id=ws.gid).entries.create(
        {"entry_type_id": ws.types["beat"], "title": "beat", "slug": "onion-beat-2", "data_json": {"story": "onion"}}
    )
    assert again.slug == "onion-beat-2"  # not onion-beat-2-2
    old = next(i for i in ids if ws.session.get(Entries, i).metadata_json["trash"]["slug"] == "onion-beat-2")
    EntryService(ws.session, ws.gid).restore_from_trash(old)
    ws.session.expire_all()
    restored = ws.session.get(Entries, old)
    assert restored.status == "draft" and restored.slug.startswith("onion-beat-2--trashed-")  # taken: it keeps the aside one


def test_smart_collections_and_the_search_index_are_cleaned(ws):
    from marvin.services.collections.smart_collections import sync_collection

    ids = ws.seed("onion", 8)
    keep = ws.one("keep-me", "note")
    drafts = Collections(
        session=ws.session, group_id=ws.gid, slug="all-drafts", name="All drafts", is_smart=True, smart_rules={"statuses": ["draft"]}
    )
    ws.session.add(drafts)
    ws.session.flush()
    sync_collection(ws.session, ws.gid, drafts)
    for eid in [*ids, keep]:
        ws.session.add(
            AIEmbeddingModel(
                session=ws.session,
                group_id=ws.gid,
                entity_type="entry",
                entity_id=eid,
                chunk_index=0,
                chunk_text="x",
                embedding=[0.0, 1.0],
                model_id="m",
                dimensions=2,
            )
        )
    ws.session.commit()
    assert ws.session.query(EntryCollections).filter_by(collection_id=drafts.id).count() == 9

    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=8, chunk_size=3)
    held = {r[0] for r in ws.session.query(EntryCollections.entry_id).filter_by(collection_id=drafts.id)}
    assert held == {keep}
    indexed = {r[0] for r in ws.session.query(AIEmbeddingModel.entity_id).filter(AIEmbeddingModel.group_id == ws.gid)}
    assert indexed == {keep}
    # what a full re-sync of the smart collections would decide is what the bulk path left
    assert sync_collection(ws.session, ws.gid, drafts) == 0


def test_published_entries_going_ask_for_one_site_rebuild(ws, monkeypatch):
    asked = []
    monkeypatch.setattr("marvin.services.site_rebuild.auto_rebuild_enabled", lambda s, g: True)
    monkeypatch.setattr("marvin.services.site_rebuild.request_rebuild", lambda s, g, reason, **k: asked.append(reason) or 1)
    ws.seed("onion", 4, status="published")
    done = B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=4)
    assert done["published"] == 4 and len(asked) == 1
    row = ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.status == "trashed").first()
    assert row.published_at is None and row.metadata_json["trash"]["previous_status"] == "published"


# ── Permanent ──────────────────────────────────────────────────────────────────────────────────────


def test_permanent_deletes_rows_and_their_links_but_not_assets(ws):
    ids = ws.seed("onion", 8)
    picks = Collections(session=ws.session, group_id=ws.gid, slug="picks", name="Picks")
    asset = _asset(ws, "a")
    ws.session.add(picks)
    ws.session.flush()
    ws.session.add_all(
        [EntryCollections(entry_id=ids[0], collection_id=picks.id, sort_order=0), EntryAssets(entry_id=ids[0], asset_id=asset.id, position=0)]
    )
    ws.session.commit()
    # two of them already in the Trash from an earlier clear: a permanent delete that names `trashed` takes those too
    B.execute(ws.session, ws.gid, {"entries": [str(ids[1]), str(ids[2])]}, mode="trash", confirm_total=2)
    assert B.preview(ws.session, ws.gid, story_spec("onion"), mode="permanent")["total"] == 6
    found = B.preview(ws.session, ws.gid, story_spec("onion", with_trash=True), mode="permanent")
    assert (found["total"], found["in_trash"]) == (8, 2)
    _Spy.last = []
    done = B.execute(ws.session, ws.gid, story_spec("onion", with_trash=True), mode="permanent", confirm_total=8)
    assert done["deleted"] == 8 and [e[0] for e in _Spy.last] == ["entries_bulk_deleted"]
    ws.session.expire_all()
    assert ws.session.query(Entries).filter(Entries.id.in_(ids)).count() == 0
    assert ws.session.query(EntryCollections).filter(EntryCollections.entry_id.in_(ids)).count() == 0
    assert ws.session.query(EntryAssets).filter(EntryAssets.entry_id.in_(ids)).count() == 0
    assert ws.session.get(Assets, asset.id) is not None and ws.session.get(Collections, picks.id) is not None


# ── Who may ─────────────────────────────────────────────────────────────────────────────────────────


def test_who_may_bulk_delete(ws):
    ws.seed("onion", 4, owner="author")
    spec = story_spec("onion")
    assert B.refusal(ws.session, ws.gid, spec, "permanent", role=3) is not None  # editor: not for good
    assert B.refusal(ws.session, ws.gid, spec, "permanent", role=4) is None
    assert B.refusal(ws.session, ws.gid, spec, "trash", role=3) is None
    assert B.refusal(ws.session, ws.gid, spec, "trash", role=2, user_id=ws.users["author"]) is None  # their own drafts
    assert "not" in B.refusal(ws.session, ws.gid, spec, "trash", role=2, user_id=ws.users["editor"])
    assert B.refusal(ws.session, ws.gid, spec, "trash", role=1) is not None


# ── HTTP ────────────────────────────────────────────────────────────────────────────────────────────


def _sign_in(ws, role: WorkspaceRole) -> TestClient:
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(ws.gid) else None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ws.users["editor"],
        group_id=ws.gid,
        active_group_id=ws.gid,
        admin=False,
        is_superuser=False,
        full_name="editor",
        email="editor@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=role)],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )
    return TestClient(app)


class _Inline:
    """threading.Thread that runs its target when started: the job finishes before the request answers."""

    def __init__(self, target, args=(), **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


E = "/api/platform/entries/bulk-delete"


def test_http_preview_then_delete_in_the_background(ws, monkeypatch):
    monkeypatch.setattr(B.threading, "Thread", _Inline)
    ids = ws.seed("onion", 12)
    client = _sign_in(ws, WorkspaceRole.EDITOR)
    body = {"spec": story_spec("onion"), "mode": "trash"}
    found = client.post(f"{E}/preview", json=body).json()
    assert found["total"] == 12 and found["byType"]["beat"] == 2 and found["text"]
    assert client.post(E, json=body).status_code == 400  # no confirmTotal
    stale = client.post(E, json={**body, "confirmTotal": 11})
    assert stale.status_code == 409 and stale.json()["detail"]["preview"]["total"] == 12
    res = client.post(E, json={**body, "confirmTotal": 12, "description": "the onion import"})
    assert res.status_code == 202 and res.json()["total"] == 12
    job = client.get(E).json()
    assert job["state"] == "done" and job["done"] == 12 and job["result"]["deleted"] == 12
    assert set(_statuses(ws, ids).values()) == {"trashed"}
    assert len(_bulk_events()) == 1


def test_http_permanent_is_for_admins_and_a_bad_spec_is_a_400(ws, monkeypatch):
    monkeypatch.setattr(B.threading, "Thread", _Inline)
    ws.seed("onion", 3)
    body = {"spec": story_spec("onion"), "mode": "permanent", "confirmTotal": 3}
    assert _sign_in(ws, WorkspaceRole.EDITOR).post(f"{E}/preview", json=body).status_code == 403
    assert _sign_in(ws, WorkspaceRole.EDITOR).post(E, json=body).status_code == 403
    assert _sign_in(ws, WorkspaceRole.ADMIN).post(E, json={**body, "spec": {"stroy": "onion"}}).status_code == 400
    assert _sign_in(ws, WorkspaceRole.ADMIN).post(E, json=body).status_code == 202
    assert ws.session.query(Entries).filter(Entries.group_id == ws.gid).count() == 0


# ── The workflow step ───────────────────────────────────────────────────────────────────────────────


def test_the_workflow_step_previews_then_deletes_what_it_previewed(ws):
    from marvin.services.automation.actions import AutomationActionError, run_action

    ids = ws.seed("onion", 16)
    ctx = {"entry": {"slug": "onion"}, "depth": 0}
    query = {"entry_types": list(TYPES), "fields": {"story": "${entry.slug}"}}
    look = run_action(ws.session, ws.gid, {"kind": "delete_entries", "query": query}, ctx, authorizer_role=4)
    assert look["total"] == 16 and look["mode"] == "preview" and set(_statuses(ws, ids).values()) == {"draft"}
    ctx["steps"] = {"look": {"output": look}}
    step = {"kind": "delete_entries", "query": query, "mode": "trash", "confirm_total": "${steps.look.output.total}"}
    dry = run_action(ws.session, ws.gid, step, ctx, authorizer_role=4, dry_run=True)
    assert dry["dry_run"] and dry["would"] == "trash" and set(_statuses(ws, ids).values()) == {"draft"}
    with pytest.raises(AutomationActionError):  # an AUTHOR's workflow may not
        run_action(ws.session, ws.gid, step, ctx, authorizer_role=2)
    with pytest.raises(AutomationActionError):  # an EDITOR's workflow may not delete for good
        run_action(ws.session, ws.gid, {**step, "mode": "permanent"}, ctx, authorizer_role=3)
    done = run_action(ws.session, ws.gid, step, ctx, authorizer_role=4)
    assert done["deleted"] == 16 and set(_statuses(ws, ids).values()) == {"trashed"}


def test_validation_asks_for_an_admin_approval_before_deleting_for_good():
    from marvin.schemas.group.automation_definition import DeleteEntriesAction
    from marvin.services.automation.validation import unasked_delete_issues

    look = {"kind": "delete_entries", "id": "look", "query": {"entry_types": ["beat"]}}
    gone = {"kind": "delete_entries", "query": {"entry_types": ["beat"]}, "mode": "permanent", "confirm_total": "${steps.look.output.total}"}
    manual = {"trigger": {"type": "manual"}}
    assert [i["level"] for i in unasked_delete_issues({**manual, "actions": [look, gone]})] == ["error"]
    editor_ok = {"kind": "approval", "message": "?", "approvers": "editor"}
    assert unasked_delete_issues({**manual, "actions": [look, editor_ok, gone]})
    admin_ok = {"kind": "approval", "message": "?", "approvers": "admin"}
    assert unasked_delete_issues({**manual, "actions": [look, admin_ok, gone]}) == []
    with pytest.raises(ValueError, match="confirm_total"):
        DeleteEntriesAction.model_validate({"kind": "delete_entries", "query": {"entry_types": ["beat"]}, "mode": "trash"})


# ── Speed ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["trash", "permanent"])
def test_two_thousand_entries_clear_in_a_few_seconds(ws, mode):
    ws.seed("onion", 2000)
    other = ws.seed("shoals", 50)
    found = B.preview(ws.session, ws.gid, story_spec("onion"), mode=mode)
    started = time.monotonic()
    done = B.execute(ws.session, ws.gid, story_spec("onion"), mode=mode, confirm_total=found["total"])
    took = time.monotonic() - started
    print(f"\nbulk delete ({mode}, {ws.session.get_bind().dialect.name}): {done['deleted']} entries in {took:.2f} s, {done['chunks']} chunks")  # noqa: T201
    assert done["deleted"] == 2000 and done["chunks"] == 4
    assert took < 15, f"{took:.1f} s"
    assert set(_statuses(ws, other).values()) == {"draft"}


def test_a_manual_workflow_runs_the_preview_and_the_delete(ws):
    """Through the engine, as a guided setup's run step starts it: the step's commits per chunk sit fine inside a run."""
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    ids = ws.seed("onion", 30)
    story = ws.one("onion", "story")
    query = {"entry_types": list(TYPES), "fields": {"story": "${entry.slug}"}}
    row = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name="Clear",
        slug="clear",
        enabled=True,
        definition={
            "trigger": {"type": "manual", "inputs": [{"name": "story", "label": "Story", "type": "entry", "required": True}]},
            "actions": [
                {"kind": "delete_entries", "id": "look", "query": query},
                {"kind": "delete_entries", "id": "gone", "query": query, "mode": "trash", "confirm_total": "${steps.look.output.total}"},
            ],
        },
    )
    ws.session.add(row)
    ws.session.commit()
    res = run_automation_now(
        ws.session, ws.gid, row, user_id=ws.users["admin"], inputs={"story": str(story)}, recorder=ExecutionRecorder(ws.session, ws.gid)
    )
    run = ws.session.query(AutomationExecutionModel).filter_by(automation_id=row.id).one()
    assert run.status == "success", (res, run.error)
    assert set(_statuses(ws, ids).values()) == {"trashed"} and _statuses(ws, [story])[story] == "draft"
    assert len(_bulk_events()) == 1
    ws.session.query(AutomationExecutionModel).filter_by(automation_id=row.id).delete()
    ws.session.delete(row)
    ws.session.commit()


def test_a_preview_step_counts_trashed_entries_its_query_names_so_delete_for_good_confirms(ws):
    """Clear to the Trash, import again, then delete for good: the preview of a query naming `trashed` counts the entries
    an earlier clear left in the Trash, and the permanent delete confirms that total."""
    from marvin.services.automation.actions import run_action

    ws.seed("onion", 8)
    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=8)
    again = ws.seed("onion", 8)  # slugs are free: the same ones again
    ctx = {"entry": {"slug": "onion"}, "depth": 0}
    query = {**story_spec("onion", with_trash=True), "fields": {"story": "${entry.slug}"}}
    look_all = run_action(ws.session, ws.gid, {"kind": "delete_entries", "query": query}, ctx, authorizer_role=4)
    assert (look_all["total"], look_all["in_trash"]) == (16, 8)
    ctx["steps"] = {"look_all": {"output": look_all}}
    step = {"kind": "delete_entries", "query": query, "mode": "permanent", "confirm_total": "${steps.look_all.output.total}"}
    assert run_action(ws.session, ws.gid, step, ctx, authorizer_role=4)["deleted"] == 16
    assert ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.id.in_(again)).count() == 0


def test_the_step_passes_the_definition_schema_at_the_top_but_not_inside_a_repeat():
    from marvin.services.automation.validation import structural_issues

    look = {"kind": "delete_entries", "id": "look", "query": {"entry_types": ["beat"]}}
    ok = {"trigger": {"type": "manual"}, "actions": [look, {"kind": "approval", "message": "?", "approvers": "admin"}]}
    assert structural_issues(ok) == []
    inside = {"trigger": {"type": "manual"}, "actions": [{"kind": "repeat", "for_each": "a,b", "steps": [look]}]}
    assert structural_issues(inside)


def test_emptying_the_trash_takes_bulk_trashed_entries_set_based_and_the_rest_one_by_one(ws):
    from marvin.services.entries import trash as T

    ids = ws.seed("onion", 30)
    single = ws.one("one-by-one", "note")
    EntryService(ws.session, ws.gid, actor_id=ws.users["editor"], event_bus=ws.bus).trash(single)
    B.execute(ws.session, ws.gid, story_spec("onion"), mode="trash", confirm_total=30, chunk_size=7)
    ws.session.add(
        AIEmbeddingModel(
            session=ws.session,
            group_id=ws.gid,
            entity_type="entry",
            entity_id=ids[0],
            chunk_index=0,
            chunk_text="x",
            embedding=[0.0],
            model_id="m",
            dimensions=1,
        )
    )
    ws.session.commit()
    _Spy.last = []
    assert T.empty_trash(ws.session, ws.gid, event_bus=ws.bus) == 31
    assert [e[0] for e in _Spy.last] == ["entry_deleted"]  # the one trashed one by one, and none for the 30
    ws.session.expire_all()
    assert ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.status == "trashed").count() == 0
    assert ws.session.query(AIEmbeddingModel).filter(AIEmbeddingModel.group_id == ws.gid).count() == 0
