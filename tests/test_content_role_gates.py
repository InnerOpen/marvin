"""Content routes follow the workspace content roles.

Entries, entry types, collections, assets, tags, resources and forms had no role check, so a VIEWER
could create, edit and delete content (and an EDITOR could change the content schema). Now:

- any member reads;
- AUTHOR creates entries and changes their own until they are approved or published, uploads assets,
  and find-or-creates tags;
- EDITOR changes any entry (approve, publish), collections, assets, resources, tag renames/deletes,
  and reads form submissions;
- ADMIN/OWNER changes entry types and forms (structure).

Each gated route refuses the role just below its gate with a 403 before it looks anything up, and lets
the gate role past (a 404 for a made-up id proves that). Also covered: the AUTHOR ownership rules, the
workspace scoping of tag detach, admin-only scheduled task types, and the AI tool gates.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

NOPE = "00000000-0000-4000-8000-000000000000"
P = "/api/platform"

V, A, E, AD = WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR, WorkspaceRole.ADMIN

# (gate role, method, path, json body). Bodies are valid so FastAPI's validation (which runs before the
# handler) can't answer first.
GATED = [
    # entries: AUTHOR (an AUTHOR's own entries; ownership is tested below)
    (A, "POST", f"{P}/entries", {"entry_type_id": NOPE, "title": "T"}),
    (A, "PATCH", f"{P}/entries/{NOPE}", {}),
    (A, "DELETE", f"{P}/entries/{NOPE}", None),
    (A, "POST", f"{P}/entries/{NOPE}/apply-suggestion", None),
    (A, "POST", f"{P}/entries/{NOPE}/reject-suggestion", None),
    (A, "POST", f"{P}/entries/{NOPE}/suggested-assets/{NOPE}/approve", None),
    (A, "POST", f"{P}/entries/{NOPE}/suggested-assets/{NOPE}/reject", None),
    (A, "POST", f"{P}/entries/{NOPE}/collections/{NOPE}", None),
    (A, "DELETE", f"{P}/entries/{NOPE}/collections/{NOPE}", None),
    # entry types: ADMIN
    (AD, "POST", f"{P}/entry-types", {"name": "Gate type"}),
    (AD, "PATCH", f"{P}/entry-types/{NOPE}", {}),
    (AD, "DELETE", f"{P}/entry-types/{NOPE}", None),
    # collections: EDITOR
    (E, "PATCH", f"{P}/collections/order", {"collections": []}),
    (E, "POST", f"{P}/collections", {"name": "Gate collection"}),
    (E, "POST", f"{P}/collections/preview", {}),
    (E, "PATCH", f"{P}/collections/{NOPE}", {}),
    (E, "DELETE", f"{P}/collections/{NOPE}", None),
    (E, "PATCH", f"{P}/collections/{NOPE}/entries/order", {"entries": []}),
    (E, "PATCH", f"{P}/collections/{NOPE}/entries/{NOPE}", {}),
    # assets: EDITOR (upload is AUTHOR, below)
    (E, "PATCH", f"{P}/assets/{NOPE}", {}),
    (E, "POST", f"{P}/assets/{NOPE}/apply-suggestion", None),
    (E, "POST", f"{P}/assets/{NOPE}/reject-suggestion", None),
    (E, "DELETE", f"{P}/assets/{NOPE}", None),
    # resources: EDITOR
    (E, "POST", f"{P}/resources", {"slug": "gate-res", "name": "R", "resource_type": "link"}),
    (E, "PATCH", f"{P}/resources/{NOPE}", {}),
    (E, "POST", f"{P}/resources/{NOPE}/apply-suggestion", None),
    (E, "POST", f"{P}/resources/{NOPE}/reject-suggestion", None),
    (E, "DELETE", f"{P}/resources/{NOPE}", None),
    # tags: find-or-create and entry tagging AUTHOR; rename/delete and asset/resource tagging EDITOR
    (A, "POST", f"{P}/tags", {"name": "gate-tag"}),
    (A, "POST", f"{P}/tags/{NOPE}/entries/{NOPE}", None),
    (A, "DELETE", f"{P}/tags/{NOPE}/entries/{NOPE}", None),
    (E, "PATCH", f"{P}/tags/{NOPE}", {}),
    (E, "DELETE", f"{P}/tags/{NOPE}", None),
    (E, "POST", f"{P}/tags/{NOPE}/assets/{NOPE}", None),
    (E, "DELETE", f"{P}/tags/{NOPE}/assets/{NOPE}", None),
    (E, "POST", f"{P}/tags/{NOPE}/resources/{NOPE}", None),
    (E, "DELETE", f"{P}/tags/{NOPE}/resources/{NOPE}", None),
    # forms: ADMIN; submissions EDITOR
    (AD, "POST", f"{P}/forms", {"name": "Gate form"}),
    (AD, "PATCH", f"{P}/forms/{NOPE}", {}),
    (AD, "DELETE", f"{P}/forms/{NOPE}", None),
    (E, "GET", f"{P}/forms/{NOPE}/submissions", None),
]

# Reads any member may make.
OPEN = [
    f"{P}/entries",
    f"{P}/entries/counts",
    f"{P}/entry-types",
    f"{P}/collections",
    f"{P}/assets",
    f"{P}/resources",
    f"{P}/tags",
    f"{P}/forms",
]

BELOW = {A: V, E: A, AD: E}


@fixture
def workspace(db_session):
    """A workspace with two users in it (`uid` signs in; `other` owns entries the caller didn't write)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"cgate-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for user_id, name in ((uid, slug), (other, f"{slug}-other")):
        db_session.execute(
            Users.__table__.insert().values(
                id=user_id,
                group_id=gid,
                username=name,
                email=f"{name}@t.test",
                full_name="GATE",
                password="x",
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, other=other, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.resources import Resources
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    # Not purged by group, and they hold NOT NULL user references.
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()
    db_session.query(Users).filter(Users.id.in_([uid, other])).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE, user_id=None) -> TestClient:
    """Make a workspace user the caller, holding `role` in it (None = not a member)."""
    members = [SimpleNamespace(group_id=workspace.gid, workspace_role=role)] if role else []
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id or workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="GATE",
        email=f"{workspace.slug}@t.test",
        platform_role=platform_role,
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _call(client: TestClient, method: str, path: str, body):
    kwargs = {"json": body} if body is not None else {}
    return client.request(method, path, **kwargs)


def _ids(route):
    return f"{route[0].value} {route[1]} {route[2]}"


@pytest.mark.parametrize("route", GATED, ids=_ids)
def test_the_role_below_the_gate_gets_403(workspace, route):
    gate, method, path, body = route
    res = _call(_sign_in(workspace, BELOW[gate]), method, path, body)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("route", GATED, ids=_ids)
def test_non_member_gets_403(workspace, route):
    _gate, method, path, body = route
    assert _call(_sign_in(workspace, None), method, path, body).status_code == 403


@pytest.mark.parametrize("route", GATED, ids=_ids)
def test_the_gate_role_gets_past_the_gate(workspace, route):
    gate, method, path, body = route
    res = _call(_sign_in(workspace, gate), method, path, body)
    assert res.status_code != 403, res.text
    assert res.status_code < 500, res.text


@pytest.mark.parametrize("route", GATED, ids=_ids)
def test_platform_super_admin_gets_past_the_gate(workspace, route):
    _gate, method, path, body = route
    res = _call(_sign_in(workspace, None, PlatformRole.SUPER_ADMIN), method, path, body)
    assert res.status_code != 403, res.text
    assert res.status_code < 500, res.text


@pytest.mark.parametrize("path", OPEN)
def test_reads_stay_open_to_viewers(workspace, path):
    assert _sign_in(workspace, V).get(path).status_code == 200


def test_asset_upload_is_author_and_above(workspace):
    def upload(role):
        files = {"file": ("gate.txt", b"hello", "text/plain")}
        data = {"slug": f"gate-{uuid.uuid4().hex[:6]}", "name": "Gate"}
        return _sign_in(workspace, role).post(f"{P}/assets/upload", files=files, data=data)

    assert upload(V).status_code == 403
    res = upload(A)
    assert res.status_code != 403 and res.status_code < 500, res.text


# ── AUTHOR ownership ─────────────────────────────────────────────────────────


@fixture
def entries(workspace):
    """An entry type, plus a draft by the caller, a draft by someone else and a published one by the caller."""
    admin = _sign_in(workspace, AD)
    et = admin.post(f"{P}/entry-types", json={"name": "Note"}).json()["id"]
    own = admin.post(f"{P}/entries", json={"entry_type_id": et, "title": "Mine", "status": "draft"}).json()["id"]
    live = admin.post(f"{P}/entries", json={"entry_type_id": et, "title": "Mine, live", "status": "published"}).json()["id"]
    theirs = _sign_in(workspace, AD, user_id=workspace.other).post(f"{P}/entries", json={"entry_type_id": et, "title": "Theirs", "status": "draft"})
    return SimpleNamespace(et=et, own=own, live=live, theirs=theirs.json()["id"])


def test_author_edits_and_deletes_only_their_own_drafts(workspace, entries):
    author = _sign_in(workspace, A)
    assert author.patch(f"{P}/entries/{entries.own}", json={"title": "Mine, edited"}).status_code == 200
    assert author.patch(f"{P}/entries/{entries.own}", json={"status": "needs_review"}).status_code == 200
    assert author.patch(f"{P}/entries/{entries.theirs}", json={"title": "Hijacked"}).status_code == 403
    assert author.delete(f"{P}/entries/{entries.theirs}").status_code == 403
    assert author.delete(f"{P}/entries/{entries.own}").status_code == 200


@pytest.mark.parametrize("status", ["approved", "published"])
def test_author_cannot_approve_or_publish(workspace, entries, status):
    author = _sign_in(workspace, A)
    assert author.patch(f"{P}/entries/{entries.own}", json={"status": status}).status_code == 403
    created = author.post(f"{P}/entries", json={"entry_type_id": entries.et, "title": "Straight to live", "status": status})
    assert created.status_code == 403


def test_author_cannot_schedule_a_publish(workspace, entries):
    author = _sign_in(workspace, A)
    res = author.patch(f"{P}/entries/{entries.own}", json={"publish_at": "2030-01-01T00:00:00Z"})
    assert res.status_code == 403


def test_author_cannot_change_their_entry_once_it_is_live(workspace, entries):
    author = _sign_in(workspace, A)
    assert author.patch(f"{P}/entries/{entries.live}", json={"title": "Sneaky"}).status_code == 403
    assert author.delete(f"{P}/entries/{entries.live}").status_code == 403


def test_author_creates_drafts_owned_by_them(workspace, entries):
    res = _sign_in(workspace, A).post(f"{P}/entries", json={"entry_type_id": entries.et, "title": "New draft"})
    assert res.status_code == 201, res.text
    assert res.json()["createdBy"] == str(workspace.uid)


def test_editor_edits_publishes_and_deletes_anyones_entries(workspace, entries):
    """The production `n8n` user is an EDITOR: it updates entries it did not create (metadata, archive)."""
    editor = _sign_in(workspace, E)
    assert editor.patch(f"{P}/entries/{entries.theirs}", json={"metadata_json": {"desk": "replied"}}).status_code == 200
    assert editor.patch(f"{P}/entries/{entries.theirs}", json={"status": "published"}).status_code == 200
    assert editor.patch(f"{P}/entries/{entries.theirs}", json={"status": "archived"}).status_code == 200
    assert editor.delete(f"{P}/entries/{entries.theirs}").status_code == 200


def test_author_tags_their_own_entry_but_not_someone_elses(workspace, entries):
    author = _sign_in(workspace, A)
    tag = author.post(f"{P}/tags", json={"name": "gate-own"}).json()["id"]
    assert author.post(f"{P}/tags/{tag}/entries/{entries.own}").status_code == 201
    assert author.delete(f"{P}/tags/{tag}/entries/{entries.own}").status_code == 200
    assert author.post(f"{P}/tags/{tag}/entries/{entries.theirs}").status_code == 403


def test_author_cannot_revise_someone_elses_entry_with_ai(workspace, entries):
    res = _sign_in(workspace, A).post("/api/ai/revise-entry", json={"entry": entries.theirs, "instruction": "tighten it"})
    assert res.status_code == 403, res.text


def test_ai_write_back_skips_entities_the_caller_cannot_edit(workspace, entries, db_session):
    """An AUTHOR running an AI operation on someone else's entry gets the output, but nothing is
    applied or staged onto that entry (or onto any asset/resource)."""
    from marvin.db.models.platform import Entries
    from marvin.routes.ai.operations_controller import AIOperationsController

    def may_change(role, entity_type, obj):
        _sign_in(workspace, role)
        ctl = object.__new__(AIOperationsController)
        ctl.user = app.dependency_overrides[get_current_user]()  # the signed-in stand-in; group_id follows it
        return ctl._may_change(entity_type, obj)

    theirs, own = db_session.get(Entries, uuid.UUID(entries.theirs)), db_session.get(Entries, uuid.UUID(entries.own))
    assert may_change(A, "entry", own) is True
    assert may_change(A, "entry", theirs) is False
    assert may_change(A, "asset", SimpleNamespace()) is False
    assert may_change(E, "entry", theirs) is True
    assert may_change(E, "resource", SimpleNamespace()) is True


def test_tag_detach_is_scoped_to_the_callers_workspace(workspace, db_session):
    """The detach routes deleted the junction row by ids alone, so a member of one workspace could strip
    tags from another workspace's entries, assets and resources."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import AssetTags, EntryTags, Tags
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.group.group_purge import purge_group_dependents

    other = uuid.uuid4()
    group = Groups(session=db_session, name=f"cg-other-{other.hex[:8]}", slug=f"cg-other-{other.hex[:8]}")
    group.id = other
    db_session.add(group)
    db_session.flush()
    try:
        et = EntryTypes(session=db_session, group_id=other, name="T", slug=f"t-{other.hex[:6]}")
        tag = Tags(session=db_session, group_id=other, name="theirs", slug=f"theirs-{other.hex[:6]}")
        db_session.add_all([et, tag])
        db_session.flush()
        entry = Entries(session=db_session, group_id=other, entry_type_id=et.id, title="Theirs", slug=f"e-{other.hex[:6]}")
        asset = Assets(
            session=db_session,
            group_id=other,
            name="a",
            slug=f"a-{other.hex[:6]}",
            original_filename="a.txt",
            filename="a.txt",
            extension="txt",
            file_size=1,
            mime_type="text/plain",
            asset_type="document",
            checksum="x",
            storage_provider="local",
            storage_key=f"k-{other.hex}",
            uploaded_by=workspace.uid,
        )
        db_session.add_all([entry, asset])
        db_session.flush()
        db_session.add_all([EntryTags(entry_id=entry.id, tag_id=tag.id), AssetTags(asset_id=asset.id, tag_id=tag.id)])
        db_session.commit()

        editor = _sign_in(workspace, E)
        assert editor.delete(f"{P}/tags/{tag.id}/entries/{entry.id}").status_code == 404
        assert editor.delete(f"{P}/tags/{tag.id}/assets/{asset.id}").status_code == 404
        assert db_session.query(EntryTags).filter_by(entry_id=entry.id).count() == 1
        assert db_session.query(AssetTags).filter_by(asset_id=asset.id).count() == 1
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other)
        db_session.query(Assets).filter(Assets.group_id == other).delete()
        db_session.query(Groups).filter(Groups.id == other).delete()
        db_session.commit()


# ── Scheduled tasks: admin-only types ────────────────────────────────────────

TASKS = f"{P}/scheduled-tasks"


def _task(task_type):
    return {"name": f"Gate {uuid.uuid4().hex[:6]}", "schedule_type": "cron", "schedule_config": {"cron": "0 3 * * *"}, "task_type": task_type}


def _admin_only_types():
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    return [t["task_type"] for t in TaskHandlerRegistry.get_task_type_info() if t["admin_only"]]


def test_there_are_admin_only_task_types_to_reject():
    assert "cleanup_temp_files" in _admin_only_types()


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_workspace_admins_cannot_schedule_admin_only_task_types(workspace, role):
    client = _sign_in(workspace, role)
    for task_type in _admin_only_types():
        res = client.post(TASKS, json=_task(task_type))
        assert res.status_code == 403, (task_type, res.text)
    assert client.get(TASKS).json() == []


def test_workspace_admins_still_schedule_workspace_task_types(workspace):
    res = _sign_in(workspace, AD).post(TASKS, json=_task("prune_expired_invitations"))
    assert res.status_code == 201, res.text


def test_platform_super_admin_may_schedule_admin_only_task_types(workspace):
    res = _sign_in(workspace, None, PlatformRole.SUPER_ADMIN).post(TASKS, json=_task("cleanup_temp_files"))
    assert res.status_code == 201, res.text


def test_patch_cannot_turn_a_task_into_an_admin_only_type(workspace):
    client = _sign_in(workspace, AD)
    task = client.post(TASKS, json=_task("prune_expired_invitations")).json()
    res = client.patch(f"{TASKS}/{task['slug']}", json={"task_type": "cleanup_temp_files", "taskType": "cleanup_temp_files"})
    assert res.status_code == 200, res.text
    assert res.json()["taskType"] == "prune_expired_invitations"


# ── AI tools ─────────────────────────────────────────────────────────────────

SETTINGS_TOOLS = {"list_scheduled_tasks", "get_scheduled_task_history", "get_ai_settings", "list_workflows", "run_workflow"}


def test_every_write_tool_needs_editor():
    from marvin.services.ai.operations.base import ROLE_EDITOR
    from marvin.services.ai.tools import list_tools

    # run_agent is "write" only in that it delegates; the delegate's tools are bound at the caller's role.
    writes = [t for t in list_tools() if not t.read_only and t.name != "run_agent"]
    assert writes
    assert [t.name for t in writes if t.min_role < ROLE_EDITOR] == []


def test_settings_tools_need_admin():
    from marvin.services.ai.operations.base import ROLE_ADMIN
    from marvin.services.ai.tools import get_tool

    assert {name: get_tool(name).min_role for name in SETTINGS_TOOLS} == dict.fromkeys(SETTINGS_TOOLS, ROLE_ADMIN)


@pytest.mark.parametrize("tool", ["list_scheduled_tasks", "get_scheduled_task_history"])
def test_scheduled_task_tools_refuse_members_below_admin(workspace, tool):
    args = {"task": "anything"} if tool == "get_scheduled_task_history" else {}
    for role in (V, A, E):
        res = _sign_in(workspace, role).post(f"/api/ai/tools/{tool}/invoke", json={"args": args})
        assert res.status_code == 403, (role, res.text)
    assert _sign_in(workspace, AD).post(f"/api/ai/tools/{tool}/invoke", json={"args": args}).status_code == 200


def test_tool_list_hides_settings_tools_below_admin(workspace):
    names = {t["name"] for t in _sign_in(workspace, E).get("/api/ai/tools").json()}
    assert names and not (names & SETTINGS_TOOLS)
    assert "attach_tag" in names  # an EDITOR keeps the content writes
