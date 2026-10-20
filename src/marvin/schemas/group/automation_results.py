"""The Automation results API (routes/groups/automation_results_controller.py): what Settings › Automation › Results shows — the work
Marvin handed to another system, whether it came back, and what a person can do about a failure."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel

ResultStatus = Literal["in_flight", "succeeded", "failed"]
ResultFilter = Literal["in_flight", "no_reply", "failed", "succeeded"]


class AutomationResultEntry(_MarvinModel):
    """The entry the work was about."""

    id: UUID4
    title: str
    slug: str | None = None


class AutomationResultConnection(_MarvinModel):
    """The connection the work went through (a Settings › Integrations connection)."""

    slug: str
    name: str
    provider: str


class AutomationResultWorkflow(_MarvinModel):
    """The Marvin workflow whose step handed it off."""

    id: UUID4
    name: str
    slug: str | None = None


class AutomationResult(_MarvinModel):
    id: UUID4
    status: ResultStatus
    """in_flight | succeeded | failed, in Marvin's words (the provider maps its own)."""
    no_reply: bool = False
    """In flight for more than 24 hours: no reply has come. Still `in_flight`; a late reply settles it as usual."""
    entry: AutomationResultEntry | None = None
    connection: AutomationResultConnection | None = None
    """Empty for a result no known connection reported, and once the connection is deleted (the result goes with it)."""
    workflow: AutomationResultWorkflow | None = None
    """Empty for a result that arrived unannounced, or from a workflow since deleted."""
    target: str | None = None
    """What was asked of the other side, as the provider names it (an n8n workflow's path)."""
    remote_id: str | None = None
    remote_url: str | None = None
    """A link to the run on the other side (web addresses only)."""
    message: str | None = None
    sent_at: datetime
    finished_at: datetime | None = None
    attempt: int = 1
    dismissed: bool = False
    """A failure a person dealt with: it no longer counts as needing attention."""
    can_retry: bool = False
    """A failure that names the workflow step and entry that made it. Whether that step can be run again safely is checked when asked."""


class AutomationResultsCan(_MarvinModel):
    act: bool = False
    """Retry and dismiss (ADMIN and above). Reading is EDITOR and above."""


class AutomationResultsSummary(_MarvinModel):
    show: bool
    """Whether any result has been kept: Settings › Automation › Results (and its tab in the Automation hub) is drawn only then."""
    in_flight: int = 0
    """Still in flight, not counting those with no reply."""
    no_reply: int = 0
    failed: int = 0
    """Failed and not dismissed."""
    succeeded: int = 0
    attention: int = 0
    """Failed plus no reply: what needs a person."""
    can: AutomationResultsCan


class AutomationResultsList(_MarvinModel):
    items: list[AutomationResult]
    total: int
    limit: int
    offset: int
    counts: AutomationResultsSummary
    """The per-state counts for the whole workspace, whatever the filters (the tabs' numbers)."""
    connections: list[AutomationResultConnection] = Field(default_factory=list)


class AutomationResultOne(_MarvinModel):
    result: AutomationResult
