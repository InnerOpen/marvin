"""One approval rule for every path that writes AI output (services/ai/approval.py).

Regressions covered: a workflow's operation step with write-back applied AI output to published
entries even in suggest-only; allow-draft-update treated entries in review/approved as drafts;
compose's alt text bypassed the mode; the settings API accepted any approval_mode string.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.ai.approval import may_apply, normalize_mode


@pytest.mark.parametrize(
    ("mode", "status", "applies"),
    [
        ("suggest-only", "draft", False),
        ("suggest-only", "published", False),
        ("allow-draft-update", "inbox", True),
        ("allow-draft-update", "draft", True),
        ("allow-draft-update", "needs_review", False),
        ("allow-draft-update", "approved", False),
        ("allow-draft-update", "published", False),
        ("allow-automatic-update", "published", True),
    ],
)
def test_entries_follow_the_mode_and_their_status(mode, status, applies):
    assert may_apply(mode, "entry", status) is applies


def test_assets_have_no_lifecycle_so_count_as_drafts():
    assert may_apply("allow-draft-update", "asset", None) is True
    assert may_apply("suggest-only", "asset", None) is False


@pytest.mark.parametrize("mode", [None, "", "yolo"])
def test_unset_or_unknown_mode_is_suggest_only(mode):
    assert normalize_mode(mode) == "suggest-only" and may_apply(mode, "entry", "draft") is False


# --- the workflow operation step ------------------------------------------------------------------


def _workflow_write_back(monkeypatch, mode, status):
    from marvin.services.automation import runner

    calls = {"applied": [], "staged": []}
    entry = SimpleNamespace(status=status)
    session = SimpleNamespace(get=lambda _m, _id: entry)
    monkeypatch.setattr("marvin.services.ai.approval.workspace_approval_mode", lambda s, g: mode)
    monkeypatch.setattr(runner, "_apply_writeback", lambda *a, **k: calls["applied"].append(a[3]))

    class _Entries:
        def stage_suggestion(self, entity_id, fields):
            calls["staged"].append(fields)

    monkeypatch.setattr("marvin.repos.repository_factory.AllRepositories", lambda *a, **k: SimpleNamespace(entries=_Entries()))
    outcome = runner._write_back(session, "G", "E1", {"summary": "AI text"}, None, 0, "generate-summary", "X1")
    return outcome, calls


def test_workflow_write_back_is_staged_on_a_published_entry_in_suggest_only(monkeypatch):
    outcome, calls = _workflow_write_back(monkeypatch, "suggest-only", "published")

    assert outcome == "staged" and calls["applied"] == []
    assert calls["staged"][0]["summary"] == "AI text" and calls["staged"][0]["_meta"]["source"] == "automation"


def test_workflow_write_back_applies_when_the_mode_allows(monkeypatch):
    outcome, calls = _workflow_write_back(monkeypatch, "allow-automatic-update", "published")

    assert outcome == "applied" and calls["applied"] == [{"summary": "AI text"}]


# --- the settings API -----------------------------------------------------------------------------


def test_saving_an_unknown_approval_mode_is_refused(monkeypatch):
    from marvin.routes.groups.ai_settings_controller import AISettingsController
    from marvin.schemas.group.ai_settings import WorkspaceAISettingsUpdate

    ctrl = SimpleNamespace(_require_admin=lambda: None, _allow_workspace_credentials=lambda: True)
    with pytest.raises(HTTPException) as exc:
        AISettingsController.update_ai_settings(ctrl, WorkspaceAISettingsUpdate(approval_mode="yolo"))
    assert exc.value.status_code == 422
