"""Integrations teach Marvin about themselves (SDK 0.9.0): a plugin's recipes join the Workflow Library — tagged with
the plugin, offered once it is connected, filled in like Marvin's own — and its guide reaches the workflow authoring
guide (for a connected integration) and the manual search.

The stand-in: a "chatter" integration in its own package, with one good recipe, two broken ones and a guide."""

import importlib
import textwrap
import uuid

import pytest
from fastapi.testclient import TestClient
from marvin_integration_sdk import INTEGRATION_REGISTRY

from marvin.app import app
from marvin.services.automation import recipes
from marvin.services.automation.authoring import authoring_guide, workspace_refs
from tests.test_workflow_library_api import LIBRARY, _configure, ws  # noqa: F401 — the fixture

PROVIDER = """
from marvin_integration_sdk import IntegrationProvider, ProviderAction, WorkflowRecipe

ANNOUNCE = WorkflowRecipe(
    id="announce-entry-type",
    title="Announce published entries",
    outcome="Each published entry of one type is posted to the chat.",
    definition={
        "trigger": {"type": "event", "event": "entry_published"},
        "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "{{entry_type}}"}],
        "actions": [{"kind": "integration", "integration": "{{connection}}", "action": "send", "args": {"text": "New: ${entry.title}"}}],
    },
    variables={
        "entry_type": {"type": "entry_type_slug", "description": "Which entries.", "example": "post"},
        "connection": {"type": "integration_slug", "description": "The Chatter connection.", "example": "chatter"},
    },
)


class Chatter(IntegrationProvider):
    slug = "chatter"
    name = "Chatter"
    guide = "guide.md"
    actions = (ProviderAction(key="send", label="Send"),)
    recipes = (
        ANNOUNCE,
        WorkflowRecipe(id="undeclared", title="t", outcome="o", definition=ANNOUNCE.definition),
        WorkflowRecipe(
            id="not-a-workflow", title="t", outcome="o",
            definition={"trigger": {"type": "event", "event": "entry_published"}, "actions": [{"kind": "teleport"}]},
        ),
    )
"""
GUIDE = "# Chatter\n\n## Connect it\n\nPaste the room token from Chatter's settings: one room per connection.\n"
RECIPE = "chatter.announce-entry-type"


@pytest.fixture
def chatter(tmp_path, monkeypatch):
    """The Chatter plugin, installed: its package (provider + guide.md) importable and its provider registered."""
    name = f"chatter_plugin_{uuid.uuid4().hex[:8]}"
    (tmp_path / name).mkdir()
    (tmp_path / name / "__init__.py").write_text(textwrap.dedent(PROVIDER))
    (tmp_path / name / "guide.md").write_text(GUIDE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(INTEGRATION_REGISTRY, "chatter", importlib.import_module(name).Chatter())


def _connect(ws, slug="team-chat"):  # noqa: F811
    from marvin.db.models.groups.integrations import IntegrationModel

    ws.session.add(IntegrationModel(session=ws.session, group_id=ws.gid, provider="chatter", name="Team chat", slug=slug, enabled=True, config={}))
    ws.session.commit()


# ── recipes ──────────────────────────────────────────────────────────────────


def test_valid_recipes_join_the_library_tagged_with_their_plugin_and_broken_ones_are_skipped(chatter, caplog):
    caplog.set_level("WARNING", logger="marvin.services.automation.recipes")
    ids = {e["id"] for e in recipes.entries()}

    assert RECIPE in ids and not {"chatter.undeclared", "chatter.not-a-workflow"} & ids
    warned = caplog.text
    assert "chatter.undeclared" in warned and "{{entry_type}} is not declared" in warned
    assert "chatter.not-a-workflow" in warned
    item = recipes.entry(RECIPE)
    assert item["source"] == {"provider": "chatter", "name": "Chatter", "package": None, "version": None}
    assert (item["status"], item["category"], item["prerequisites"]) == (
        "supported-after-configuration",
        "Chatter",
        {"integrations": [{"provider": "chatter", "name": "Chatter"}]},
    )
    assert len(recipes.recipe_version(RECIPE)) == 16


def test_the_library_offers_it_once_connected_and_fills_it_in(ws, chatter):  # noqa: F811
    client = TestClient(app)

    def shown():
        return next(r for r in client.get(LIBRARY).json()["recipes"] if r["id"] == RECIPE)

    assert shown()["missing"] == ["needs a connection to Chatter"] and shown()["source"]["name"] == "Chatter"
    _connect(ws)
    assert shown()["missing"] == []

    filled = client.post(_configure(RECIPE), json={"vars": {"entry_type": "campaign", "connection": "team-chat"}})
    assert filled.status_code == 200, filled.text
    body = filled.json()
    assert body["name"] == "Announce published entries" and body["issues"] == []
    assert body["definition"]["actions"][0]["integration"] == "team-chat"
    assert body["definition"]["actions"][0]["args"]["text"] == "New: ${entry.title}"  # run-time templates untouched


# ── the guide ────────────────────────────────────────────────────────────────


def test_a_connected_integrations_guide_reaches_the_authoring_guide(ws, chatter):  # noqa: F811
    assert "integration_guides" not in authoring_guide(ws.session, ws.gid, "workspace")["workspace"]
    _connect(ws)

    assert [i["has_guide"] for i in workspace_refs(ws.session, ws.gid).integrations] == [True]
    assert "chatter" in authoring_guide(ws.session, ws.gid, "workspace")["workspace"]["integration_guides"]
    assert authoring_guide(ws.session, ws.gid, "workspace")["workspace"]["integration_guides"] == {"chatter": GUIDE}


def test_the_manual_search_finds_an_installed_guide(chatter):
    from marvin.services.docs import get_docs

    top = get_docs().search("chatter room token")[0]
    assert (top["page"], top["url"], top["source"]) == ("plugins/chatter.md", None, "the Chatter plugin")
    assert get_docs().read_page("plugins/chatter.md")["markdown"] == GUIDE
