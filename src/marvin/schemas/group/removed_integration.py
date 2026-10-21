"""``DELETE /groups/removed-integration-items/{kind}`` (routes/groups/removed_integration_controller.py)."""

from typing import Literal

from marvin.schemas._marvin import _MarvinModel

RemovedKind = Literal["workflows", "incoming-webhooks", "scheduled-tasks", "outgoing-webhooks"]


class RemovedIntegrationDeleted(_MarvinModel):
    kind: RemovedKind
    deleted: int
    """How many items were deleted."""
    names: list[str]
    """Their names, as they were."""
    skipped: int = 0
    """Items with a blueprint and no integration that were left alone because the provider's connection is still here."""
