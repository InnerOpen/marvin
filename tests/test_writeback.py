"""Unit tests for the AI write-back decision (apply vs stage) by approval_mode × status."""

from unittest.mock import MagicMock

from marvin.routes.ai.operations_controller import AIOperationsController


def _operation(writeback):
    op = MagicMock()
    op.writeback = writeback
    op.slug = "generate-summary"
    return op


def _call(status, mode, writeback=None, output=None, entity_type="entry"):
    if writeback is None:
        writeback = {"summary": "summary"}
    if output is None:
        output = {"summary": "new summary"}
    ctrl = MagicMock()
    ctrl.group_id = "g1"
    entry = MagicMock()
    entry.status = status
    entry.group_id = "g1"
    entry.id = "e1"
    entry.title = "T"
    ctrl.session.get.return_value = entry
    ctrl._approval_mode.return_value = mode
    return AIOperationsController._write_back(ctrl, _operation(writeback), entity_type, "e1", output, "exec1")


def test_unsupported_entity_returns_none():
    # entries/assets/resources write back; anything else (e.g. form_submission) does not.
    assert _call("inbox", "allow-automatic-update", entity_type="form_submission") is None


def test_asset_and_resource_write_back():
    # Assets/resources have no published lifecycle to protect → always eligible to apply;
    # suggest-only still stages.
    assert _call("published", "allow-automatic-update", entity_type="asset") == "applied"
    assert _call("published", "allow-draft-update", entity_type="resource") == "applied"
    assert _call("published", "suggest-only", entity_type="resource") == "staged"


def test_empty_writeback_returns_none():
    assert _call("inbox", "allow-automatic-update", writeback={}) is None


def test_suggest_only_stages():
    assert _call("inbox", "suggest-only") == "staged"


def test_draft_update_applies_on_draft():
    assert _call("inbox", "allow-draft-update") == "applied"
    assert _call("draft", "allow-draft-update") == "applied"


def test_draft_update_stages_on_published():
    assert _call("published", "allow-draft-update") == "staged"
    assert _call("archived", "allow-draft-update") == "staged"


def test_automatic_applies_even_on_published():
    assert _call("published", "allow-automatic-update") == "applied"
