"""Unit tests for the AI invocation-source gate.

The effective allow-list for a call is the INTERSECTION of the operation's declared sources
and the workspace's invocation_sources policy (an override map: enabled unless explicitly
false). This exercises `_check_invocation_source` directly with a mocked session.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from marvin.routes.ai.operations_controller import AIOperationsController

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"

ALL = ("editor", "forms", "actions", "mcp", "scheduled", "agent", "api")  # an op declaring every source


def _controller(policy):
    """A stand-in `self` whose settings row returns `policy` for invocation_sources."""
    fake = MagicMock()
    settings = MagicMock()
    settings.invocation_sources = policy
    fake.session.query.return_value.filter_by.return_value.first.return_value = settings
    return fake


def _check(policy, source, op_sources=ALL):
    return AIOperationsController._check_invocation_source(_controller(policy), source, op_sources)


def _blocked(policy, source, op_sources=ALL) -> bool:
    try:
        _check(policy, source, op_sources)
    except HTTPException as exc:
        assert exc.status_code == 403
        return True
    return False


def test_unknown_source_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _check(None, "telepathy")
    assert exc.value.status_code == 400


def test_operation_not_supporting_source_is_forbidden():
    # op supports only editor; caller claims mcp
    with pytest.raises(HTTPException) as exc:
        _check(None, "mcp", op_sources=("editor",))
    assert exc.value.status_code == 403


def test_workspace_policy_disabling_source_is_forbidden():
    with pytest.raises(HTTPException) as exc:
        _check({"mcp": False}, "mcp")
    assert exc.value.status_code == 403


def test_no_policy_allows_everything():
    # None policy → back-compat: all sources allowed
    _check(None, "mcp")  # should not raise


def test_policy_missing_key_defaults_to_allowed():
    # override map: a source absent from the policy is enabled
    _check({"forms": False}, "mcp")  # mcp not in policy → allowed


def test_policy_explicitly_enabled_is_allowed():
    _check({"mcp": True}, "mcp")


def test_intersection_requires_both():
    # workspace allows mcp, but the operation does not declare it → forbidden
    with pytest.raises(HTTPException) as exc:
        _check({"mcp": True}, "mcp", op_sources=("editor", "api"))
    assert exc.value.status_code == 403


def test_source_catalog_lists_every_source_something_sends():
    # Drift guard: every source a caller actually sends has a UI toggle (a new source can't ship
    # without one), and the UI never offers a toggle that switches nothing off. `agent` is sent (API
    # default, the agent loop) but follows the two Ask surface toggles instead of having its own.
    from marvin.services.ai.operations.base import AGENT_SOURCE, INVOCATION_SOURCE_CATALOG, INVOCATION_SOURCES, UNSENT_SOURCES

    catalog_keys = {s["key"] for s in INVOCATION_SOURCE_CATALOG}
    assert catalog_keys == set(INVOCATION_SOURCES) - set(UNSENT_SOURCES) - {AGENT_SOURCE}
    assert all(s.get("label") and s.get("description") for s in INVOCATION_SOURCE_CATALOG)


# ── The Ask surfaces: bubble + ask_page, and the legacy `agent` key ──


@pytest.mark.parametrize("surface", ["bubble", "ask_page"])
def test_ask_surface_is_allowed_with_no_policy(surface):
    assert not _blocked(None, surface)


@pytest.mark.parametrize("surface", ["bubble", "ask_page"])
def test_ask_surface_switched_off_is_forbidden(surface):
    assert _blocked({surface: False}, surface)


@pytest.mark.parametrize("surface", ["bubble", "ask_page"])
def test_legacy_agent_false_blocks_each_ask_surface(surface):
    assert _blocked({"agent": False}, surface)


def test_bubble_off_leaves_the_ask_page_on_and_vice_versa():
    assert not _blocked({"bubble": False}, "ask_page")
    assert not _blocked({"ask_page": False}, "bubble")


def test_agent_source_follows_the_ask_surfaces():
    # External/API agent runs: off when `agent` is, or when both surfaces are; one surface off is not enough.
    assert _blocked({"agent": False}, "agent")
    assert _blocked({"bubble": False, "ask_page": False}, "agent")
    assert not _blocked({"bubble": False}, "agent")
    assert not _blocked({"ask_page": False}, "agent")
    assert not _blocked(None, "agent")


@pytest.mark.parametrize("surface", ["bubble", "ask_page"])
def test_ask_surface_runs_as_agent(surface):
    # An operation/endpoint declaring `agent` takes the surfaces, and past the gate the call is an agent call.
    assert _check(None, surface, op_sources=("agent",)) == "agent"


def test_other_sources_run_as_themselves():
    assert _check(None, "editor") == "editor"


def test_ask_surface_rejected_where_agent_is_not_declared():
    with pytest.raises(HTTPException) as exc:
        _check(None, "bubble", op_sources=("editor", "mcp"))
    assert exc.value.status_code == 403


def test_the_bubble_identifies_as_bubble():
    text = (FRONTEND / "lib" / "api" / "aiBubble.ts").read_text()
    assert 'source: "bubble"' in text and 'source: "agent"' not in text and 'source: "editor"' not in text


def test_the_ask_page_identifies_as_ask_page():
    # Named-agent runs and resuming a paused chat both come from the Ask page.
    text = (FRONTEND / "lib" / "api" / "aiAgents.ts").read_text()
    assert text.count('source: "ask_page"') == 2 and 'source: "agent"' not in text


def test_ask_link_and_page_follow_the_ask_page_source():
    assert "sourceAllowed(" in (FRONTEND / "layouts" / "AppLayout.astro").read_text()
    page = (FRONTEND / "pages" / "workspace" / "settings" / "ai-ask.astro").read_text()
    assert '"ask_page"' in page and "Ask is switched off for this workspace." in page
