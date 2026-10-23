"""Workspace Variables in a workflow's steps: `{{SHOP_URL}}` (as the Variables page writes it) or `${vars.SHOP_URL}` in any
step's text is the Variable's value. Variables only: no Secret is ever filled in this way, a Variable sharing a Secret's
name is left to the Secret (a header's or an integration argument's own `{{SLUG}}`), and a name the workspace has no
Variable for stays as written — the editor's check says so before it's saved."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
from types import SimpleNamespace

import pytest

from marvin.services.automation import approvals
from marvin.services.automation.authoring import variable_warnings
from marvin.services.automation.authz import ROLE_EDITOR
from marvin.services.automation.engine import _variables_context
from marvin.services.automation.matcher import interpolate
from tests.test_workflow_approvals import _install, _published
from tests.test_workflow_library import _entry_doc, _fire, ws  # noqa: F401 — the fixture

VARS = {"vars": {"SHOP_URL": "https://mashburn.co", "TEAM": "Mash & Burn"}, "entry": {"title": "Brass lantern"}}


def test_a_variable_fills_in_either_way_it_is_written():
    assert interpolate("Shop: {{SHOP_URL}}", VARS) == "Shop: https://mashburn.co"
    assert interpolate("Shop: {{ SHOP_URL }}", VARS) == "Shop: https://mashburn.co"
    assert interpolate("${vars.TEAM} likes ${entry.title}", VARS) == "Mash & Burn likes Brass lantern"
    assert interpolate("{{TEAM}}: ${entry.title}", VARS) == "Mash & Burn: Brass lantern"
    assert interpolate({"links": ["{{SHOP_URL}}/shop"]}, VARS) == {"links": ["https://mashburn.co/shop"]}
    assert interpolate("${vars.TEAM|url}", VARS) == "Mash%20%26%20Burn"


def test_what_isnt_a_variable_stays_as_written():
    assert interpolate("Hi {{NOPE}} and {{name}}", VARS) == "Hi {{NOPE}} and {{name}}"  # unknown; a lower-case placeholder
    assert interpolate("Hi {{TEAM}}", {"entry": {}}) == "Hi {{TEAM}}"  # no Variables in the run: as before


def test_a_filled_in_value_is_never_read_again_as_a_template():
    context = {"vars": {"TRICK": "${entry.title} {{OTHER}}", "OTHER": "x"}, "entry": {"title": "Brass lantern"}}
    assert interpolate("{{TRICK}}", context) == "${entry.title} {{OTHER}}"


def _variable(ws, slug, value):
    from marvin.db.models.groups.variables import WorkspaceVariable

    ws.session.add(WorkspaceVariable(session=ws.session, group_id=ws.gid, name=slug.title(), slug=slug, value=value))
    ws.session.commit()


@pytest.fixture
def secrets(monkeypatch):
    """The workspace's Secret names, as the secret backend lists them."""
    names: list[str] = []
    backend = SimpleNamespace(list_slugs=lambda group_id=None: list(names), get=lambda slug, group_id=None: None)
    monkeypatch.setattr("marvin.services.secrets.factory.get_secret_backend", lambda: backend)
    return names


def test_a_run_reads_the_workspaces_variables_but_never_a_secret(ws, secrets):
    _variable(ws, "SHOP_URL", "https://mashburn.co")
    _variable(ws, "API_KEY", "a variable shadowed by the secret")
    secrets.append("API_KEY")

    assert _variables_context(ws.session, ws.gid) == {"SHOP_URL": "https://mashburn.co"}
    assert interpolate("Bearer {{API_KEY}}", {"vars": _variables_context(ws.session, ws.gid)}) == "Bearer {{API_KEY}}"  # left to the header


def test_the_ask_of_a_wait_for_approval_step_fills_in_a_variable(ws, secrets):
    _variable(ws, "SOME_VARIABLE", "the spring sale")
    definition = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [{"kind": "approval", "id": "ok", "message": "Feature “${entry.title}” in {{SOME_VARIABLE}}?"}],
    }
    workflow = _install(ws, definition)
    article = _published(ws)

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

    (waiting,) = approvals.pending(ws.session, ws.gid, ROLE_EDITOR)
    assert waiting.message == "Feature “Engraving brass” in the spring sale?"
    assert workflow.id == waiting.automation_id


def test_the_editor_warns_of_a_variable_the_workspace_doesnt_have(ws, secrets):
    _variable(ws, "SHOP_URL", "https://mashburn.co")
    secrets.append("API_KEY")
    definition = {
        "trigger": {"type": "manual"},
        "actions": [
            {"kind": "approval", "message": "{{SHOP_URL}} {{SHOP_ULR}} ${vars.TEAM|default:'us'}"},
            {"kind": "request", "url": "https://api.test", "headers": {"Authorization": "Bearer {{API_KEY}}"}},
        ],
    }

    warnings = variable_warnings(ws.session, ws.gid, definition)

    assert [(w["level"], w["path"]) for w in warnings] == [("warning", "actions[0]"), ("warning", "actions[0]")]
    assert "“SHOP_ULR”" in warnings[0]["message"] and "“TEAM”" in warnings[1]["message"]
