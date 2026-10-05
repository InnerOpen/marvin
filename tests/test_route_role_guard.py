"""Guard: no workspace route ships without a role check.

On 2026-10-04 many routes under /api/groups and /api/platform turned out to have no role check at all:
any member, a VIEWER included, could change integrations, webhooks, SMTP, variables, entries and entry
types (fixed in c5c948b5 and b1949749). This module walks every route mounted on the app so a new one
can't repeat that.

In scope:

- every write (POST/PUT/PATCH/DELETE) under the workspace prefixes (SCOPED_PREFIXES): /api/groups/,
  /api/platform/, /api/automations, /api/incoming-webhooks and /api/ai/;
- every route, reads included, on the admin-only settings controllers (SETTINGS_MODULES). Their reads
  expose workspace configuration (webhook headers, SMTP hosts, invite tokens, backups, AI provider
  keys, workflows), and docs/admin-model.md says they refuse lower roles for reads as well as writes.

Each in-scope route must enforce a workspace role, or be listed in OPEN_ROUTES with a reason.

Why static, plus a behavioural sample: calling every in-scope route as a VIEWER needs a valid body
and path for each, or FastAPI's 422 (or a 404 from a lookup that runs before the gate) answers first
and the test proves nothing; tests/test_workspace_settings_admin_gate.py shows the upkeep. So the guard
reads each endpoint's source (AST, not regex) and looks for a known gate call, in the handler or one
level down in a helper it calls. It recognises:

- the helpers in marvin.routes._base.checks (require_workspace_admin, require_workspace_role,
  require_workspace_editor, require_can_create_entry, require_can_edit_entry, editable_entry),
  resolved by identity, so aliases and function-local imports count;
- OperationChecks' workspace methods (self.checks.can_manage_settings / can_manage_members);
- user.has_workspace_role(..., WorkspaceRole.X) with X above VIEWER;
- the Depends(require_workspace_role(...)) family in marvin.core.dependencies, read from the route's
  dependency tree;
- a few controller-local helpers that predate checks.py (VETTED_LOCAL_GATES), such as the AI
  operations controller's _require_role;
- hand-written checks: an `if` comparing a role rank with a threshold above VIEWER (ROLE_AUTHOR and up,
  an agent's or operation's `.min_role`, a WORKSPACE_ROLE_HIERARCHY rank > 1) whose body raises a 403,
  or a membership loop whose `for ... else:` raises a 403;
- may_talk, the AI agent permission matrix (enabled, caller's role >= the agent's min_role, source).

A VIEWER-level check ("any member") is not a role gate. The static check proves a gate is called, not
that it runs first or works, so test_viewer_is_refused_by_each_gate_idiom calls one route per idiom as
a VIEWER (403) and as an OWNER (not 403); that pins the idioms the static check trusts, the vetted local
helpers included. Per-route behaviour stays in the controller test modules.

Routes found ungated that look like real gaps are KNOWN_GAPS: xfail(strict=True), so the build stays
green, each stays visible, and fixing one turns its XPASS into a failure that says to drop the entry.
"""

import ast
import importlib
import inspect
import textwrap
import types
import uuid
from functools import cache
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.routes._base import checks
from marvin.services.ai.agents import may_talk
from marvin.services.integrations import INTEGRATIONS_AVAILABLE

SCOPED_PREFIXES = ("/api/groups/", "/api/platform/", "/api/automations", "/api/incoming-webhooks", "/api/ai/")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
INTEGRATIONS = "/api/groups/integrations"

# Admin-only workspace configuration: every route on these controllers needs a gate, reads included.
SETTINGS_MODULES = frozenset(
    {
        "marvin.routes.groups.integrations_controller",
        "marvin.routes.groups.webhook_controller",
        "marvin.routes.groups.smtp_controller",
        "marvin.routes.groups.variables_controller",
        "marvin.routes.groups.secrets_controller",
        "marvin.routes.groups.email_event_subscriptions_controller",
        "marvin.routes.groups.invitation_controller",
        "marvin.routes.platform.scheduled_tasks_controller",
        "marvin.routes.platform.workspace_controller",
        "marvin.routes.platform.api_clients_controller",
        "marvin.routes.automations.automations_controller",
        "marvin.routes.hooks.incoming_webhooks_controller",
        "marvin.routes.ai.providers_controller",
        "marvin.routes.ai.models_controller",
        "marvin.routes.ai.mcp_servers_controller",
    }
)

# In-scope routes that are open to every member (or public) on purpose. (method, path): reason.
OPEN_ROUTES = {
    ("GET", "/api/groups/integrations/providers"): "provider catalog: plugin metadata, no workspace config; member pages render it",
    ("GET", "/api/groups/integrations/providers/{slug}/logo"): "provider logo on the public router: <img> tags can't send a token",
    ("GET", "/api/groups/webhooks/types"): "event-type list for pickers; no webhook config in it",
    ("GET", "/api/platform/scheduled-tasks/task-types"): "task-type catalog for pickers; admin_only types are refused on create",
    ("GET", "/api/groups/secrets/slugs"): "slug names only, no values: {{SLUG}} autocomplete (docs/admin-model.md keeps it open)",
    # AI: member-level by design. Running agents and operations is gated per agent/operation/tool by the
    # permission matrix (min_role, invocation sources), which the inline checks and may_talk cover.
    ("POST", "/api/ai/chat"): "plain completion, read-only (changes nothing): any member, behind the source policy and budget",
    ("PATCH", "/api/ai/threads/{thread_id}"): "rename your own Ask thread: resolve_thread scopes it to the caller (admins see all)",
    ("DELETE", "/api/ai/threads/{thread_id}"): "delete your own Ask thread: resolve_thread scopes it to the caller (admins see all)",
}

# In-scope routes with no gate today that look like real gaps. Each runs as xfail(strict=True).
KNOWN_GAPS: dict[tuple[str, str], str] = {}

# Controller-local gates that predate checks.py. (module, qualname): the rule it enforces.
# Each is called as a VIEWER and an ADMIN in test_viewer_is_refused_by_each_gate_idiom.
VETTED_LOCAL_GATES = {
    ("marvin.routes.groups.ai_settings_controller", "AISettingsController._require_admin"): "OWNER/ADMIN",
    ("marvin.routes.groups.email_template_controller", "EmailTemplateController._check_admin_access"): "OWNER/ADMIN",
    ("marvin.routes.groups.preferences_controller", "GroupPreferencesController._user_has_admin_access"): "OWNER/ADMIN",
    ("marvin.routes.ai.operations_controller", "AIOperationsController._require_role"): "the ROLE_* it is passed (VIEWER doesn't count)",
}

GATE_FUNCTIONS = frozenset(
    {
        checks.require_workspace_admin,
        checks.require_workspace_role,
        checks.require_workspace_editor,
        checks.require_can_create_entry,
        checks.require_can_edit_entry,
        checks.editable_entry,
        # The AI agent permission matrix: enabled, caller's role >= the agent's min_role, source allowed.
        may_talk,
    }
)
OPERATION_CHECKS = frozenset({"can_manage_settings", "can_manage_members"})
# Workspace role ranks above VIEWER (marvin.services.ai.operations.base), for the inline checks.
ROLE_THRESHOLDS = frozenset({"ROLE_AUTHOR", "ROLE_EDITOR", "ROLE_ADMIN", "ROLE_OWNER"})

FIX_HINT = (
    "Fix: gate it before any lookup with a helper from marvin.routes._base.checks (require_workspace_admin, "
    "require_workspace_editor, require_workspace_role, require_can_create_entry, require_can_edit_entry, "
    "editable_entry) or self.checks.can_manage_settings / can_manage_members. If every member (or the public) "
    "should reach it, add it to OPEN_ROUTES in tests/test_route_role_guard.py with a one-line reason."
)


# ---------------------------------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------------------------------


@cache
def _tree(fn) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _local_imports(tree: ast.AST) -> dict[str, object]:
    """`from x import y as z` inside the function body: name -> object."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            module = importlib.import_module(node.module)
            for alias in node.names:
                names[alias.asname or alias.name] = getattr(module, alias.name, None)
    return names


def _owner_class(fn):
    owner = fn.__globals__.get(fn.__qualname__.split(".")[0])
    return owner if isinstance(owner, type) else None


def _is_viewer(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "VIEWER") or (isinstance(node, ast.Name) and node.id == "ROLE_VIEWER")


def _names_viewer(call: ast.Call) -> bool:
    """True if the call passes WorkspaceRole.VIEWER / ROLE_VIEWER: a membership check, not a role gate."""
    return any(_is_viewer(a) for a in [*call.args, *(k.value for k in call.keywords)])


def _is_role_compare(node: ast.AST) -> bool:
    """A comparison against a role above VIEWER: `role < ROLE_EDITOR`, `self._user_role() < spec.min_role`,
    `WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0) >= 4`."""
    if not isinstance(node, ast.Compare):
        return False
    sides = [node.left, *node.comparators]
    if any(isinstance(n, ast.Name) and n.id in ROLE_THRESHOLDS for n in sides):
        return True
    if any(isinstance(n, ast.Attribute) and n.attr == "min_role" for n in sides):
        return True
    ranked = any(isinstance(n, ast.Call) and "WORKSPACE_ROLE_HIERARCHY" in ast.unparse(n.func) for n in sides)
    return ranked and any(isinstance(n, ast.Constant) and isinstance(n.value, int) and n.value > 1 for n in sides)


def _raises_403(stmts: list[ast.stmt]) -> bool:
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                args = [*node.exc.args, *(k.value for k in node.exc.keywords)]
                if any("403" in ast.unparse(a) for a in args):
                    return True
    return False


def _inline_role_checks(tree: ast.AST) -> list[str]:
    """Hand-written gates: an `if <role comparison>:` that raises a 403, or a membership loop whose
    `for ... else:` raises a 403 when no membership passed the role comparison."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(_is_role_compare(n) for n in ast.walk(node.test)) and _raises_403(node.body):
            found.append(f"inline role check: {ast.unparse(node.test)}")
        elif isinstance(node, ast.For) and _raises_403(node.orelse):
            tests = [n.test for b in node.body for n in ast.walk(b) if isinstance(n, ast.If)]
            if any(_is_role_compare(c) for t in tests for c in ast.walk(t)):
                found.append("inline role check: membership loop")
    return found


def _gates_in(fn) -> tuple[list[str], list]:
    """The gate calls in `fn`'s own body, and the marvin helpers it calls (for the one-level-deep pass)."""
    tree = _tree(fn)
    local = _local_imports(tree)
    owner = _owner_class(fn)
    gates, helpers = _inline_role_checks(tree), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            target = local.get(func.id, fn.__globals__.get(func.id))
            if target in GATE_FUNCTIONS:
                if not (target is checks.require_workspace_role and _names_viewer(node)):
                    gates.append(func.id)
            elif isinstance(target, types.FunctionType) and target.__module__.startswith("marvin."):
                helpers.append(target)
        elif isinstance(func, ast.Attribute):
            receiver = func.value
            if func.attr in OPERATION_CHECKS and isinstance(receiver, ast.Attribute) and receiver.attr == "checks":
                gates.append(f"checks.{func.attr}")
            elif func.attr == "has_workspace_role" and not _names_viewer(node):
                gates.append("has_workspace_role")
            elif isinstance(receiver, ast.Name) and receiver.id == "self" and owner is not None:
                method = inspect.getattr_static(owner, func.attr, None)
                if isinstance(method, types.FunctionType):
                    if (method.__module__, method.__qualname__) in VETTED_LOCAL_GATES:
                        if not _names_viewer(node):
                            gates.append(method.__qualname__)
                    else:
                        helpers.append(method)
    return gates, helpers


def _dependency_gates(route: APIRoute) -> list[str]:
    """Depends(require_workspace_role(ROLE)) from marvin.core.dependencies, anywhere in the route's tree."""
    found, stack = [], list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        stack.extend(dep.dependencies)
        call = dep.call
        if getattr(call, "__qualname__", "") == "require_workspace_role.<locals>.check_workspace_role":
            role = inspect.getclosurevars(call).nonlocals.get("required_role")
            if role is not None and role != WorkspaceRole.VIEWER:
                found.append(f"Depends(require_workspace_role({role.value}))")
    return found


def gates_for(route: APIRoute) -> list[str]:
    """Every role gate the route's endpoint enforces: its own calls, one level of helpers, its dependencies."""
    gates, helpers = _gates_in(route.endpoint)
    for helper in helpers:
        gates += [f"{helper.__name__} -> {g}" for g in _gates_in(helper)[0]]
    return gates + _dependency_gates(route)


# ---------------------------------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------------------------------


def _endpoints() -> list[tuple[str, str, APIRoute]]:
    out = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(SCOPED_PREFIXES):
            out += [(method, route.path, route) for method in sorted(route.methods - {"HEAD", "OPTIONS"})]
    return out


def _in_scope(method: str, route: APIRoute) -> bool:
    return method in WRITE_METHODS or route.endpoint.__module__ in SETTINGS_MODULES


def _where(route: APIRoute) -> str:
    return f"{route.endpoint.__module__}:{route.endpoint.__qualname__}"


def _guarded_params():
    params = []
    for method, path, route in _endpoints():
        if not _in_scope(method, route) or (method, path) in OPEN_ROUTES:
            continue
        gap = KNOWN_GAPS.get((method, path))
        marks = pytest.mark.xfail(strict=True, reason=f"KNOWN GAP: {gap}") if gap else ()
        params.append(pytest.param(method, path, route, id=f"{method} {path}", marks=marks))
    return params


def _key_params(entries: dict) -> list:
    return [pytest.param(key, id=f"{key[0]} {key[1]}") for key in sorted(entries)]


def _mounted(key) -> bool:
    return any((m, p) == key for m, p, _ in _endpoints())


def _sdk_only(path: str) -> bool:
    """The integrations controller only mounts when marvin_integration_sdk is installed (CI runs without it)."""
    return path.startswith(INTEGRATIONS) and not INTEGRATIONS_AVAILABLE


@pytest.mark.parametrize(("method", "path", "route"), _guarded_params())
def test_route_enforces_a_workspace_role(method, path, route):
    assert gates_for(route), f"{method} {path} ({_where(route)}) has no workspace role check, so any member (a VIEWER too) can call it.\n{FIX_HINT}"


@pytest.mark.parametrize("key", _key_params(OPEN_ROUTES))
def test_open_route_entries_are_mounted_and_ungated(key):
    if _sdk_only(key[1]):
        pytest.skip("integration routes need marvin_integration_sdk")
    method, path = key
    matches = [r for m, p, r in _endpoints() if (m, p) == key]
    assert matches, f"OPEN_ROUTES lists {method} {path}, which is not mounted any more: remove the entry."
    gated = gates_for(matches[0])
    assert not gated, f"{method} {path} is in OPEN_ROUTES but now checks a role ({gated}): remove it from OPEN_ROUTES."
    assert _in_scope(method, matches[0]), f"{method} {path} is out of scope (a read off SETTINGS_MODULES): remove it from OPEN_ROUTES."


def test_known_gap_entries_are_mounted():
    stale = [f"{m} {p}" for m, p in KNOWN_GAPS if not _sdk_only(p) and not _mounted((m, p))]
    assert not stale, f"KNOWN_GAPS lists routes that are not mounted any more: {stale}. Remove those entries."


@pytest.mark.parametrize("module", sorted(SETTINGS_MODULES))
def test_settings_modules_serve_routes(module):
    """A renamed or moved settings controller would otherwise drop its reads out of scope without a sound."""
    if module.endswith(".integrations_controller") and not INTEGRATIONS_AVAILABLE:
        pytest.skip("integration routes need marvin_integration_sdk")
    assert any(r.endpoint.__module__ == module for _, _, r in _endpoints()), f"No mounted route comes from {module}: update SETTINGS_MODULES."


def test_walk_covers_the_known_surface():
    """If the prefixes or the app layout change, the walk must not quietly match nothing."""
    expected = [
        ("POST", "/api/platform/entries"),
        ("PATCH", "/api/platform/entry-types/{item_id}"),
        ("DELETE", "/api/groups/webhooks/{item_id}"),
        ("GET", "/api/groups/smtp-profiles"),
        ("PATCH", "/api/groups/variables/{var_id}"),
        ("GET", "/api/automations"),
        ("DELETE", "/api/incoming-webhooks/{webhook_id}"),
        ("GET", "/api/ai/providers"),
        ("POST", "/api/ai/agents/{slug}/run"),
    ]
    if INTEGRATIONS_AVAILABLE:
        expected.append(("POST", "/api/groups/integrations/{integration_id}/actions/{action_key}"))
    for key in expected:
        assert key in {(m, p) for m, p, r in _endpoints() if _in_scope(m, r)}, f"{key} is missing from the guarded routes"


# ---------------------------------------------------------------------------------------------------
# Behavioural sample: one route per gate idiom the static check trusts
# ---------------------------------------------------------------------------------------------------

NOPE = "00000000-0000-4000-8000-000000000000"

# (gate as gates_for() reports it, method, path, json body). `{gid}` is the test workspace.
IDIOM_SAMPLE = [
    ("require_workspace_admin", "DELETE", f"/api/groups/variables/{NOPE}", None),
    ("require_workspace_editor", "DELETE", f"/api/platform/resources/{NOPE}", None),
    ("editable_entry", "DELETE", f"/api/platform/entries/{NOPE}", None),
    ("checks.can_manage_members", "DELETE", "/api/groups/invitations/no-such-token", None),
    ("has_workspace_role", "GET", "/api/platform/workspace/backup-key", None),
    ("Depends(require_workspace_role(ADMIN))", "DELETE", f"/api/platform/workspaces/{{gid}}/members/{NOPE}", None),
    ("AISettingsController._require_admin", "DELETE", "/api/groups/ai-settings/bubble-lines", None),
    (
        "EmailTemplateController._check_admin_access",
        "POST",
        f"/api/platform/workspaces/{{gid}}/email-templates/{NOPE}/test",
        {"recipient_email": "a@example.com"},
    ),
    ("GroupPreferencesController._user_has_admin_access", "PATCH", "/api/groups/{gid}/preferences", {}),
    ("AIOperationsController._require_role", "DELETE", "/api/ai/agents/no-such-agent", None),
    ("inline role check: membership loop", "DELETE", f"/api/ai/executions/{NOPE}", None),
    ("inline role check: role < ROLE_AUTHOR", "POST", "/api/ai/revise-entry", {"entry": "no-such-entry", "instruction": "x"}),
]


@fixture
def workspace(db_session):
    """A workspace with one user in it; tests sign that user in with whatever role they need."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"guard-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="GUARD",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole) -> TestClient:
    """Make the workspace's user the caller, holding `role` in it. Both role APIs agree: the checks.py
    helpers read get_workspace_role, the older controller-local gates walk workspace_memberships."""
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(workspace.gid) else None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="GUARD",
        email=f"{workspace.slug}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=workspace.gid, workspace_role=role)],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )
    return TestClient(app)


@pytest.mark.parametrize(("idiom", "method", "path", "body"), IDIOM_SAMPLE, ids=[s[0] for s in IDIOM_SAMPLE])
def test_viewer_is_refused_by_each_gate_idiom(workspace, idiom, method, path, body):
    url = path.format(gid=workspace.gid)
    kwargs = {"json": body} if body is not None else {}

    route = next((r for m, p, r in _endpoints() if m == method and r.path_regex.match(url)), None)
    assert route is not None, f"{method} {url} is not mounted: pick another route for {idiom}"
    assert any(g.endswith(idiom) for g in gates_for(route)), f"the static check no longer sees {idiom} on {method} {path}"

    viewer = _sign_in(workspace, WorkspaceRole.VIEWER).request(method, url, **kwargs)
    assert viewer.status_code == 403, f"{idiom}: a VIEWER got {viewer.status_code} from {method} {path}: {viewer.text}"
    admin = _sign_in(workspace, WorkspaceRole.OWNER).request(method, url, **kwargs)
    assert admin.status_code != 403, f"{idiom}: an OWNER was refused by {method} {path}: {admin.text}"
    assert admin.status_code < 500, admin.text
