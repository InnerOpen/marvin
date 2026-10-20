"""The Audience API (routes/groups/audience_controller.py): what Audience › Submissions shows — the forms whose submissions go to
the Audience, the submissions themselves with the protection's verdict and where each came from, and what a person can do."""

from datetime import datetime
from typing import Any, Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class AudienceForm(_MarvinModel):
    """A submittable entry type whose submissions go to the Audience."""

    slug: str
    name: str
    icon: str | None = None
    new: int = 0
    """Submissions of this form still waiting: new (inbox) plus suspicious (needs review)."""


class AudienceSubmissionsSummary(_MarvinModel):
    show: bool
    """Whether Audience › Submissions appears: at least one message form sends its submissions to the Audience."""
    new: int = 0
    forms: list[AudienceForm] = Field(default_factory=list)


class AudienceIntegration(_MarvinModel):
    """A connected integration that acts on the signup forms (subscribes a signup, syncs confirm and unsubscribe)."""

    slug: str
    name: str
    provider: str


class AudienceSignupsSummary(_MarvinModel):
    show: bool
    """Whether a signup form exists (a submittable type with `submission.kind: signup`): Audience › Subscribers is drawn."""
    forms: list[AudienceForm] = Field(default_factory=list)
    """Each signup form; `new` is its pending plus problem signups."""
    pending: int = 0
    """Asked to join, not confirmed yet (entry status inbox, or any status that isn't settled)."""
    confirmed: int = 0
    """Confirmed (published)."""
    unsubscribed: int = 0
    """Unsubscribed (archived)."""
    problem: int = 0
    """Needs a look (needs review): the mailing list refused it, or the spam protection held it."""
    waiting: int = 0
    """Pending plus problems: the sidebar's badge."""
    integrations: list[AudienceIntegration] = Field(default_factory=list)
    """The enabled integrations that act on the signup forms (filled by the Subscribers list, empty in `/summary`)."""


class AudienceCan(_MarvinModel):
    act: bool = True
    """Mark handled, not spam / reopen, delete (EDITOR and above, as for reading)."""
    full_ip: bool = False
    """The submitter's whole IP address is shown (ADMIN and above); below that it is masked."""


class AudienceSummary(_MarvinModel):
    submissions: AudienceSubmissionsSummary
    signups: AudienceSignupsSummary
    can: AudienceCan


class AudienceField(_MarvinModel):
    key: str
    label: str
    type: str | None = None
    value: Any = None


class AudienceVerdict(_MarvinModel):
    """What the submission protection made of it (the entry's `metadata.submission`; there is no score)."""

    flagged: bool = False
    """The protection held it for review when it arrived."""
    reasons: list[str] = Field(default_factory=list)


class AudienceSource(_MarvinModel):
    """Where it came from, as recorded when the workspace's Submission Protection captures client info."""

    ip: str | None = None
    ip_masked: bool = False
    """The IP is partly hidden (the caller is below ADMIN)."""
    user_agent: str | None = None
    referrer: str | None = None
    received_at: datetime | None = None
    last_received_at: datetime | None = None
    """When the same person (the form's match field) last wrote again."""
    count: int = 1
    """How many times this person has submitted (1 unless the form's match field folds repeats into one entry)."""


class AudienceSubmission(_MarvinModel):
    id: UUID4
    """The entry's id: it is an entry of the form's type."""
    form: AudienceForm
    title: str
    state: str
    """new | suspicious | handled — what the page shows."""
    status: str
    """The entry's own status (inbox | needs_review | archived …)."""
    fields: list[AudienceField] = Field(default_factory=list)
    verdict: AudienceVerdict
    source: AudienceSource
    created_at: datetime
    path: str
    """The entry editor, /workspace/entries/{id}."""


class AudienceSubmissionList(_MarvinModel):
    items: list[AudienceSubmission]
    total: int
    limit: int
    offset: int
    new: int
    """New plus suspicious submissions of the form (or of every form), whatever the other filters."""


class AudienceSubmissionResult(_MarvinModel):
    submission: AudienceSubmission | None = None
    """The submission afterwards; None once it is deleted (moved to the Trash)."""


SubscriberStatus = Literal["pending", "confirmed", "unsubscribed", "problem"]


class AudienceSubscriber(_MarvinModel):
    """One signup, as the Subscribers list shows it. The status mirrors the mailing list (the entry's own status is `entry_status`)."""

    id: UUID4
    """The entry's id: it is an entry of the signup form's type."""
    form: AudienceForm
    email: str | None = None
    name: str | None = None
    title: str
    status: SubscriberStatus
    entry_status: str
    review_reasons: list[str] = Field(default_factory=list)
    """Why it needs a look (status problem only), oldest first."""
    reason: str | None = None
    """The latest of them."""
    signed_up_at: datetime
    path: str
    """The entry editor, /workspace/entries/{id}."""


class AudienceHistoryItem(_MarvinModel):
    label: str
    """Signed up, Confirmed, Unsubscribed, Reopened, Back to pending, Needs a look."""
    at: datetime


class AudienceSubscriberDetail(AudienceSubscriber):
    fields: list[AudienceField] = Field(default_factory=list)
    source: AudienceSource
    history: list[AudienceHistoryItem] = Field(default_factory=list)
    """Status changes from the event log, newest first."""


class AudienceSubscriberCounts(_MarvinModel):
    pending: int = 0
    confirmed: int = 0
    unsubscribed: int = 0
    problem: int = 0


class AudienceSubscriberList(_MarvinModel):
    items: list[AudienceSubscriber]
    total: int
    limit: int
    offset: int
    counts: AudienceSubscriberCounts
    """Per status, for the form (or every form), whatever the other filters."""
    forms: list[AudienceForm] = Field(default_factory=list)
    integrations: list[AudienceIntegration] = Field(default_factory=list)
    """The enabled integrations that act on the signup forms: the page says they handle subscribing and unsubscribing, or hints to connect one."""
    can: AudienceCan


class AudienceSubscriberResult(_MarvinModel):
    subscriber: AudienceSubscriberDetail | None = None
    """The subscriber; None once it is deleted (moved to the Trash)."""
