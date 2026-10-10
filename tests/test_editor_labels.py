"""The workflow editor's words, shared with the agents that explain it (Builder's guided steps), and the manual that
documents every part — so a feature can't ship unlabelled or undocumented, and an agent never meets a step it can't
name the way the screen does."""

import json
from pathlib import Path

import pytest

from marvin.schemas.group.automation_definition import ACTION_MODELS, TRIGGER_MODELS
from marvin.services.automation.actions.entry import OP_SENDS
from marvin.services.automation.matcher import _OPS

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src/marvin/services/automation/editor_labels.json"
FRONTEND = ROOT / "frontend/src/lib/workflowLabels.json"
MANUAL = (ROOT / "docs/manual/whats-new/workflows.md").read_text()

LABELS = json.loads(BACKEND.read_text())
PARTS = {
    "triggerTypes": set(TRIGGER_MODELS),
    "stepKinds": set(ACTION_MODELS),
    "entryOps": set(OP_SENDS),
    "conditionOps": set(_OPS),
}


def test_the_backend_and_the_editor_read_the_same_labels():
    """Two copies because the frontend image is built from frontend/ alone; change both together."""
    assert json.loads(FRONTEND.read_text()) == LABELS


@pytest.mark.parametrize("part", sorted(PARTS))
def test_every_part_the_engine_knows_has_an_editor_label(part):
    assert set(LABELS[part]) == PARTS[part], f"{part}: label the new ones in both label files, drop the removed ones"


@pytest.mark.parametrize("part", ["triggerTypes", "stepKinds", "entryOps"])
def test_every_trigger_step_and_entry_action_is_in_the_manual(part):
    """By its definition name (`set_data`) or the editor's label ("Set fields") on docs/manual/whats-new/workflows.md."""
    missing = [name for name, label in LABELS[part].items() if f"`{name}`" not in MANUAL and label not in MANUAL]
    assert missing == [], f"undocumented {part}: {missing} — describe them in docs/manual/whats-new/workflows.md"


def test_the_screen_labels_are_the_ones_the_manual_uses():
    missing = [label for label in LABELS["screen"].values() if label not in MANUAL]
    assert missing == [], f"the manual never names {missing}; use the editor's words"
