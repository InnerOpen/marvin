"""The Social inbox API (routes/groups/social_inbox_controller.py): the comments, replies and mentions the social engagement
poll kept, what was replied, and what a person can do with each."""

from datetime import datetime

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class SocialInboxAuthor(_MarvinModel):
    id: str | None = None
    handle: str | None = None
    name: str | None = None


class SocialInboxReplyRead(_MarvinModel):
    """How an item was answered: by a rule (or a person) live, or in rehearsal (nothing was sent)."""

    log_slug: str | None = None
    log_entry_id: UUID4 | None = None
    """The ``social-reply-log`` entry (open it at /workspace/entries/{id}); None when there is no log type to write one in."""
    mode: str | None = None
    """private | public | both."""
    rehearsal: bool = False
    reply_id: str | None = None
    at: datetime | None = None
    by: UUID4 | None = None
    """The person who replied from the inbox; None for a rule's reply."""


class SocialInboxItemRead(_MarvinModel):
    id: UUID4
    integration: str
    """The integration's slug."""
    network: str
    kind: str
    """comment | reply | mention."""
    post_id: str | None = None
    post_url: str | None = None
    author: SocialInboxAuthor
    text: str
    created_at: datetime
    """When the network says it was written."""
    first_seen_at: datetime
    url: str | None = None
    """The item on the network."""
    status: str
    """new | seen | replied | hidden | liked."""
    reply: SocialInboxReplyRead | None = None
    actions: list[str] = Field(default_factory=list)
    """What this item's network offers for it: reply, like, hide, delete, message (hide and delete not for a mention)."""
    reply_modes: list[str] = Field(default_factory=list)
    """The reply modes on offer (private, public) — empty when the network has no reply."""


class SocialInboxList(_MarvinModel):
    items: list[SocialInboxItemRead]
    total: int
    limit: int
    offset: int
    new: int
    """How many items in the workspace are still new (whatever the filters)."""


class SocialInboxIntegration(_MarvinModel):
    slug: str
    name: str
    network: str


class SocialInboxEngine(_MarvinModel):
    """The scheduled task that fills the inbox."""

    state: str
    """missing (the Social engagement set isn't applied) | disabled | enabled."""
    task_id: UUID4 | None = None
    rehearsal: bool = True
    """Replies are rehearsed, not sent, unless the task's config says ``rehearsal: false``."""
    announce: bool = True


class SocialInboxSummary(_MarvinModel):
    available: bool
    """Whether the workspace has anything for an inbox: an integration that reads comments, or items already kept."""
    new: int
    integrations: list[SocialInboxIntegration]
    engine: SocialInboxEngine
    can: dict[str, bool]
    """What the caller's role may do: seen, like, hide, rule, reply, delete, message."""


class SocialInboxSeen(_MarvinModel):
    ids: list[UUID4] | None = None
    """The items to mark seen."""
    all: bool = False
    """Or every new item (of ``integration`` when it is given)."""
    integration: str | None = None


class SocialInboxSeenResult(_MarvinModel):
    changed: int


class SocialInboxReplyCreate(_MarvinModel):
    text: str = Field(min_length=1, max_length=10000)
    private: bool = True
    """A private reply (to the commenter only) unless false: a public reply in the thread."""


class SocialInboxReplyResult(_MarvinModel):
    replied: bool
    private: bool
    reply_id: str | None = None
    url: str | None = None
    logged: bool
    """Whether it is in the social-reply-log (the engine then never answers this comment). False only when the log type isn't applied."""
    item: SocialInboxItemRead


class SocialInboxHide(_MarvinModel):
    hidden: bool = True


class SocialInboxMessageCreate(_MarvinModel):
    text: str = Field(min_length=1, max_length=10000)


class SocialInboxActionResult(_MarvinModel):
    """What the network answered; ``item`` is the item afterwards (None once it is deleted)."""

    ok: bool = True
    item: SocialInboxItemRead | None = None
    message_id: str | None = None


class SocialInboxRuleCreate(_MarvinModel):
    reply: str = Field(default="", max_length=10000)
    """The reply text to pre-fill (what was typed in the reply box, say); empty leaves it for the editor."""


class SocialInboxRuleResult(_MarvinModel):
    id: UUID4
    slug: str
    keywords: list[str]
    path: str
    """The entry editor: /workspace/entries/{id}. The rule is a draft; publishing it is the approval."""
