"""The AI execution log: members see their own runs, OWNERs/ADMINs every run.

GET /api/ai/executions listed every run in the workspace, inputs and outputs included, to any member,
and GET /api/ai/executions/{id} returned any of them. Now workspace OWNERs/ADMINs (and platform super
admins) see every run; other members see only runs they triggered, and another member's run is the same
404 as a missing id. Runs with no user (system, workflow, scheduled) are admin-only. The agent's
list_ai_executions / get_ai_execution tools (which MarvinMCP projects) follow the same rule. Deleting a
run still needs ADMIN.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

NOPE = "00000000-0000-4000-8000-000000000000"
BASE = "/api/ai/executions"
BELOW_ADMIN = [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR]
ADMINS = [WorkspaceRole.ADMIN, WorkspaceRole.OWNER]


@fixture
def world(db_session):
    """A workspace with three runs: the caller's, another member's, and a system run (no user)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    gid, me, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"runs-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()

    def run(triggered_by, op):
        row = AIExecutionModel(
            session=db_session,
            group_id=gid,
            operation_slug=op,
            provider_type="openai",
            model_id="gpt-test",
            status="completed",
            triggered_by=triggered_by,
            input_json={"prompt": f"{op} input"},
            output_json={"text": f"{op} output"},
        )
        db_session.add(row)
        db_session.flush()
        return str(row.id)

    mine, theirs, system = run(me, "mine"), run(other, "theirs"), run(None, "system")
    db_session.commit()
    yield SimpleNamespace(gid=gid, me=me, mine=mine, theirs=theirs, system=system)

    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(AIExecutionModel).filter(AIExecutionModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _caller(world, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE):
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(world.gid) else None

    return SimpleNamespace(
        id=world.me,
        group_id=world.gid,
        active_group_id=world.gid,
        admin=False,
        is_superuser=False,
        full_name="RUNS",
        email="runs@t.test",
        platform_role=platform_role,
        workspace_memberships=[SimpleNamespace(group_id=world.gid, workspace_role=role)] if role else [],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )


def _sign_in(world, role, platform_role=PlatformRole.NONE) -> TestClient:
    user = _caller(world, role, platform_role)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _listed(client) -> set[str]:
    res = client.get(BASE, params={"limit": 200})
    assert res.status_code == 200, res.text
    return {row["id"] for row in res.json()}


@pytest.mark.parametrize("role", BELOW_ADMIN)
def test_member_lists_only_their_own_runs(world, role):
    assert _listed(_sign_in(world, role)) == {world.mine}


@pytest.mark.parametrize("role", BELOW_ADMIN)
def test_member_reads_their_run_but_others_look_missing(world, role):
    client = _sign_in(world, role)
    assert client.get(f"{BASE}/{world.mine}").json()["outputJson"] == {"text": "mine output"}

    missing = client.get(f"{BASE}/{NOPE}")
    assert missing.status_code == 404
    for run_id in (world.theirs, world.system):
        res = client.get(f"{BASE}/{run_id}")
        assert (res.status_code, res.json()) == (404, missing.json()), res.text


@pytest.mark.parametrize("role", ADMINS)
def test_admin_sees_every_run_including_system_runs(world, role):
    client = _sign_in(world, role)
    assert _listed(client) == {world.mine, world.theirs, world.system}
    for run_id in (world.theirs, world.system):
        assert client.get(f"{BASE}/{run_id}").status_code == 200


def test_platform_super_admin_sees_every_run(world):
    client = _sign_in(world, None, PlatformRole.SUPER_ADMIN)
    assert _listed(client) == {world.mine, world.theirs, world.system}
    assert client.get(f"{BASE}/{world.theirs}").status_code == 200


@pytest.mark.parametrize("role", BELOW_ADMIN)
def test_member_cannot_delete_a_run_even_their_own(world, role):
    assert _sign_in(world, role).delete(f"{BASE}/{world.mine}").status_code == 403


def test_admin_deletes_a_run(world):
    client = _sign_in(world, WorkspaceRole.ADMIN)
    assert client.delete(f"{BASE}/{world.theirs}").status_code == 204
    assert client.get(f"{BASE}/{world.theirs}").status_code == 404


# The agent's tools (MarvinMCP projects them as marvin_list_ai_executions / marvin_get_ai_execution).


def _tool(db_session, world, name: str, role, args: dict) -> dict:
    from marvin.services.ai.tools.base import ToolContext, get_tool

    ctx = ToolContext(session=db_session, group_id=world.gid, user=_caller(world, role))
    return json.loads(get_tool(name).handler(ctx, args))


@pytest.mark.parametrize(("role", "expected"), [(WorkspaceRole.VIEWER, {"mine"}), (WorkspaceRole.ADMIN, {"mine", "theirs", "system"})])
def test_list_tool_follows_the_rule(db_session, world, role, expected):
    out = _tool(db_session, world, "list_ai_executions", role, {"limit": 100})
    assert {row["operation"] for row in out["executions"]} == expected


def test_get_tool_hides_other_members_and_system_runs_below_admin(db_session, world):
    assert _tool(db_session, world, "get_ai_execution", WorkspaceRole.VIEWER, {"id": world.mine})["output"] == {"text": "mine output"}
    missing = _tool(db_session, world, "get_ai_execution", WorkspaceRole.VIEWER, {"id": NOPE})
    for run_id in (world.theirs, world.system):
        assert _tool(db_session, world, "get_ai_execution", WorkspaceRole.VIEWER, {"id": run_id}) == missing
        assert "output" in _tool(db_session, world, "get_ai_execution", WorkspaceRole.ADMIN, {"id": run_id})
