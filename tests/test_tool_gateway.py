"""The shared tool gateway (services/ai/tool_gateway.py).

`GET /api/ai/tools` and `POST /api/ai/tools/{name}/invoke` used to gate in the controller; they now call the
gateway, which the remote MCP server will share. The parity tests hold the controller's pre-extraction logic as a
frozen oracle and compare the routes with it for every registry tool, role and a spread of sources, so nothing a
MarvinMCP caller sees changed. The one deliberate change is the AI budget: a tool that calls the provider is
refused once the workspace is over its limit (it never was through this route).
"""

import inspect
import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY, WorkspaceRole
from tests import test_content_role_gates as gates

workspace = gates.workspace  # fixture: a workspace with a signed-in user

ROLES = [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR, WorkspaceRole.ADMIN, WorkspaceRole.OWNER]
# Not a member of any workspace — the legacy `admin` flag alone doesn't make one — so there is no workspace to run in.
NO_WORKSPACE_ROLES = [None, "admin"]


def _user(ws, role):
    admin = role == "admin"
    member = None if admin else role
    return SimpleNamespace(
        id=ws.uid,
        group_id=ws.gid,
        active_group_id=ws.gid,
        admin=admin,
        is_superuser=admin,
        full_name="GATE",
        email=f"{ws.slug}@t.test",
        platform_role=gates.PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=member)] if member else [],
        get_workspace_role=lambda group_id: member if str(group_id) == str(ws.gid) else None,
    )


def _client(user) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _echo(ctx, args):
    return json.dumps({"ran": True, "args": args, "provider": ctx.provider is not None, "gid": str(ctx.group_id)})


@pytest.fixture
def echo_tools(monkeypatch):
    """Every registry handler swapped for an echo, so a call shows only what the gates decided."""
    from marvin.services.ai.tools import TOOL_REGISTRY

    for name, spec in list(TOOL_REGISTRY.items()):
        monkeypatch.setitem(TOOL_REGISTRY, name, replace(spec, handler=_echo))
    return sorted(TOOL_REGISTRY)


# ── The controller's logic before the extraction (frozen) ─────────────────────


def _legacy_role(user, gid) -> int:
    from marvin.services.ai.operations.base import ROLE_OWNER

    if user.admin:
        return ROLE_OWNER
    for m in user.workspace_memberships:
        if m.group_id == gid:
            return WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
    return 0


def _legacy_marvin(session, gid):
    from marvin.services.ai.agents import ROUTER_SLUG, resolve_agent

    spec = resolve_agent(session, gid, ROUTER_SLUG)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No agent '{ROUTER_SLUG}'.")
    return replace(spec, name="External assistants")  # outside calls name the External assistants card; the rest is the main agent's


def _legacy_list(session, gid, user) -> list[dict]:
    from marvin.services.ai.agents import POLICY_BLOCK, resolve_policy
    from marvin.services.ai.tools import list_tools
    from marvin.services.ai.tools.categories import category_of

    role = _legacy_role(user, gid)
    marvin = _legacy_marvin(session, gid)
    return [
        t.info()
        for t in list_tools()
        if "mcp" in t.sources
        and role >= t.min_role
        and resolve_policy(marvin, t.name, category_of(t.name, read_only=t.read_only), role)[0] != POLICY_BLOCK
    ]


def _legacy_source(session, gid, source, operation_sources):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.operations.base import INVOCATION_SOURCES, execution_source, source_allowed

    if source not in INVOCATION_SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown invocation source '{source}'. Valid: {', '.join(INVOCATION_SOURCES)}.")
    runs_as = execution_source(source)
    if runs_as not in operation_sources:
        raise HTTPException(status_code=403, detail=f"This operation cannot be invoked from the '{source}' source.")
    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).first()
    if not source_allowed(settings.invocation_sources if settings else None, source):
        raise HTTPException(status_code=403, detail=f"This workspace has disabled AI from the '{source}' source.")
    return runs_as


def _legacy_invoke(session, gid, user, name, args, source) -> dict:
    from marvin.services.ai.agents import unattended_refusal
    from marvin.services.ai.factory import get_workspace_ai_provider
    from marvin.services.ai.tools import ToolContext, bulk_writes, get_tool
    from marvin.services.ai.tools.categories import category_of

    try:
        spec = get_tool(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found.") from None
    if _legacy_role(user, gid) < spec.min_role:
        raise HTTPException(status_code=403, detail="Insufficient role for this tool.")
    _legacy_source(session, gid, source, spec.sources)
    category = category_of(spec.name, read_only=spec.read_only)
    refusal = unattended_refusal(_legacy_marvin(session, gid), spec.name, category, _legacy_role(user, gid))
    if refusal is not None:
        return refusal
    try:
        provider = get_workspace_ai_provider(session, gid)
    except Exception:
        provider = None
    ctx = ToolContext(session=session, group_id=gid, user=user, provider=provider)
    try:
        raw = bulk_writes.unattended(spec, ctx)(args or {})
    except Exception as e:
        session.rollback()
        return {"error": str(e)}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"result": raw}


def _expected(fn, *a) -> list:
    try:
        return [200, fn(*a)]
    except HTTPException as e:
        return [e.status_code, {"detail": e.detail}]


def _got(res) -> list:
    return [res.status_code, res.json()]


# ── Parity ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", NO_WORKSPACE_ROLES, ids=str)
def test_tools_answer_409_without_a_workspace(workspace, role):
    client = _client(_user(workspace, role))
    assert client.get("/api/ai/tools").status_code == 409
    assert client.post("/api/ai/tools/find_entries/invoke", json={"args": {}, "source": "mcp"}).status_code == 409


@pytest.mark.parametrize("role", ROLES, ids=str)
def test_tool_list_is_unchanged_for_every_role(workspace, db_session, role):
    user = _user(workspace, role)
    assert _got(_client(user).get("/api/ai/tools")) == _expected(_legacy_list, db_session, workspace.gid, user)


@pytest.mark.parametrize("role", ROLES, ids=str)
def test_invoke_is_unchanged_for_every_tool_role_and_source(workspace, db_session, echo_tools, role):
    user = _user(workspace, role)
    client = _client(user)
    calls = [(name, "mcp") for name in [*echo_tools, "no_such_tool"]]
    calls += [(name, src) for name in ("find_entries", "attach_tag", "run_workflow", "compose_entry") for src in ("bubble", "agent", "bogus")]
    for name, source in calls:
        body = {"args": {"x": 1}, "source": source}
        got = _got(client.post(f"/api/ai/tools/{name}/invoke", json=body))
        assert got == _expected(_legacy_invoke, db_session, workspace.gid, user, name, {"x": 1}, source), (name, source)


def test_invoke_is_unchanged_when_the_workspace_turns_mcp_off_or_a_handler_fails(workspace, db_session, echo_tools, monkeypatch):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.tools import TOOL_REGISTRY

    def boom(_ctx, _args):
        raise ValueError("boom")

    monkeypatch.setitem(TOOL_REGISTRY, "find_entries", replace(TOOL_REGISTRY["find_entries"], handler=boom))
    monkeypatch.setitem(TOOL_REGISTRY, "get_entry", replace(TOOL_REGISTRY["get_entry"], handler=lambda _c, _a: "plain"))
    user = _user(workspace, WorkspaceRole.EDITOR)
    client = _client(user)
    assert _got(client.post("/api/ai/tools/find_entries/invoke", json={"args": {}})) == [200, {"error": "boom"}]
    assert _got(client.post("/api/ai/tools/get_entry/invoke", json={"args": {}})) == [200, {"result": "plain"}]

    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=workspace.gid, invocation_sources={"mcp": False}))
    db_session.commit()
    for name, source in (("list_tags", "mcp"), ("list_tags", "bubble")):
        got = _got(client.post(f"/api/ai/tools/{name}/invoke", json={"args": {}, "source": source}))
        assert got == _expected(_legacy_invoke, db_session, workspace.gid, user, name, {}, source)
    assert _got(client.get("/api/ai/tools")) == _expected(_legacy_list, db_session, workspace.gid, user)


# ── AI budget (decision 13) ──────────────────────────────────────────────────


def test_tools_that_call_the_provider_are_flagged():
    """`uses_ai` is what the budget gate reads; a handler that reaches for the provider must carry it."""
    from marvin.services.ai.tools import list_tools

    def reaches_provider(fn, seen: set) -> bool:
        # The handler's own source, then every same-module helper it hands `ctx` to.
        src = inspect.getsource(fn)
        if "ctx.provider" in src:
            return True
        module = inspect.getmodule(fn)
        for helper in re.findall(r"\b(\w+)\(ctx\b", src):
            target = getattr(module, helper, None)
            if inspect.isfunction(target) and target not in seen:
                seen.add(target)
                if reaches_provider(target, seen):
                    return True
        return False

    for spec in list_tools():
        assert spec.uses_ai == reaches_provider(spec.handler, {spec.handler}), spec.name
    assert {t.name for t in list_tools() if t.uses_ai} >= {"search_content", "compose_entry", "revise_entry", "view_image", "run_agent"}


def test_an_ai_tool_is_refused_over_budget_and_the_rest_still_run(workspace, db_session, echo_tools):
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.tools import TOOL_REGISTRY

    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=workspace.gid, budget_config={"max_requests_per_day": 1}))
    db_session.add(
        AIExecutionModel(
            session=db_session,
            group_id=workspace.gid,
            operation_slug="generate-summary",
            provider_type="openai",
            model_id="m",
            status="completed",
            trigger_type="api",
        )
    )
    db_session.commit()
    client = _client(_user(workspace, WorkspaceRole.OWNER))
    try:
        for name in ("search_content", "revise_entry", "view_image"):
            res = client.post(f"/api/ai/tools/{name}/invoke", json={"args": {}})
            assert _got(res) == [429, {"detail": "Daily request limit (1) reached."}], name
        assert TOOL_REGISTRY["find_entries"].uses_ai is False
        assert client.post("/api/ai/tools/find_entries/invoke", json={"args": {}}).json()["ran"] is True
    finally:
        db_session.query(AIExecutionModel).filter_by(group_id=workspace.gid).delete()
        db_session.commit()


# ── Read-only connections (the remote MCP's `marvin:read` scope) ─────────────


def test_a_read_only_connection_sees_and_runs_read_tools_only(workspace, db_session, echo_tools):
    from marvin.services.ai.tool_gateway import READ_ONLY_REFUSAL, invoke_unattended, is_read_tool, visible_tools
    from marvin.services.ai.tools import TOOL_REGISTRY

    user = _user(workspace, WorkspaceRole.OWNER)
    everything = {t.name for t in visible_tools(db_session, workspace.gid, user)}
    reads = {t.name for t in visible_tools(db_session, workspace.gid, user, allow_writes=False)}
    assert reads and reads < everything
    assert "run_agent" in everything and "run_agent" not in reads
    assert all(TOOL_REGISTRY[n].read_only for n in reads)
    for name in sorted(everything - reads):
        assert not is_read_tool(TOOL_REGISTRY[name])
        out = invoke_unattended(db_session, workspace.gid, user, name, {}, allow_writes=False)
        if "policy" in out:  # Marvin's matrix answered first (an Ask-first category)
            continue
        assert out == {"error": READ_ONLY_REFUSAL, "tool": name}
    for name in sorted(reads):
        assert invoke_unattended(db_session, workspace.gid, user, name, {}, allow_writes=False)["ran"] is True
