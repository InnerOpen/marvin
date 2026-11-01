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
