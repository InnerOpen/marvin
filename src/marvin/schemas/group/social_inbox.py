"""The Social API (routes/groups/social_inbox_controller.py): the comments, replies and mentions the social engagement poll kept,
what was replied (recorded on the item), what a person can do with each, a network's rules and its auto-reply mode."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class SocialInboxAuthor(_MarvinModel):
    id: str | None = None
    handle: str | None = None
    name: str | None = None


class SocialInboxReplyRead(_MarvinModel):
    """How an item was answered: by a rule (or a person) live, or in rehearsal (nothing was sent). Recorded on the item."""

    mode: str | None = None
    """private | public | both."""
    rehearsal: bool = False
    reply_id: str | None = None
    text: str | None = None
    """What was sent, or would have been in a rehearsal."""
    rule: str | None = None
    """The slug of the rule entry that fired; empty for a person's reply."""
    rule_entry_id: UUID4 | None = None
    """That rule's entry (edit it at /workspace/entries/{id}); None for a person's reply or a rule since deleted."""
    note: str | None = None
    at: datetime | None = None
    by: UUID4 | None = None
    """The person who replied from the inbox; None for a rule's reply."""
    by_name: str | None = None


class SocialInboxHeldRead(_MarvinModel):
    """Why a rule that matched the item didn't answer it. Recorded by the engine, cleared when a reply is recorded."""

    reason: str
    """cooldown (the person was answered by direct message within the rule's cool-down) | refused (the network refused)."""
    rule: str | None = None
    """The slug of the rule entry that matched."""
    rule_entry_id: UUID4 | None = None
    """That rule's entry; None for a rule since deleted."""
    until: datetime | None = None
    """When the cool-down ends: the rule answers a message the person sends after it."""
    note: str | None = None
    """The network's words, for a refusal."""
    at: datetime | None = None


class SocialInboxItemRead(_MarvinModel):
    id: UUID4
    integration: str
    """The integration's slug."""
    network: str
    kind: str
    """comment | reply | mention, and what a network pushes: message | story_reply | story_mention | reaction | live_comment."""
    post_id: str | None = None
    post_url: str | None = None
    author: SocialInboxAuthor
    text: str
    attachments: list[dict] | None = None
    """What it arrived with: {type, url, title} — a message's picture, a shared post and its caption."""
    trashed_at: datetime | None = None
    """When a person moved it to the inbox's Trash; None while it is in the inbox."""
    created_at: datetime
    """When the network says it was written."""
    first_seen_at: datetime
    url: str | None = None
    """The item on the network."""
    status: str
    """new | seen | replied | hidden | liked."""
    reply: SocialInboxReplyRead | None = None
    """The reply recorded on the item (live or rehearsal); None while it has none."""
    held: SocialInboxHeldRead | None = None
    """Why a matching rule didn't answer it; None when nothing held it back."""
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
    """A connected network (an enabled integration offering a ``social.*`` capability)."""

    slug: str
    name: str
    provider: str
    """The plugin's slug — what the logo is served under (``/api/groups/integrations/providers/{provider}/logo``)."""
    network: str
    capabilities: list[str] = Field(default_factory=list)
    reads_comments: bool = False
    """It offers ``social.comments``: it has an inbox, and the engine reads it."""
    can_reply: bool = False
    """It offers ``social.reply``: auto-reply can be switched on."""
    auto_reply: str = "off"
    """off | rehearsal | on."""
    new: int = 0
    """Items of this network still new."""


class SocialInboxSummary(_MarvinModel):
    show: bool
    """Whether Social appears at all: an enabled integration offers a ``social.*`` capability."""
    new: int
    """New items across the networks."""
    integrations: list[SocialInboxIntegration]
    can: dict[str, bool]
    """What the caller's role may do: seen, like, hide, rule, rules, publish, reply, delete, message, auto_reply."""


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
    item: SocialInboxItemRead


class SocialInboxTrash(_MarvinModel):
    trashed: bool = True
    """True: move it to the inbox's Trash; false: restore it."""


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


class SocialRuleRead(_MarvinModel):
    """One auto-reply rule, as a network's Rules tab lists it."""

    id: UUID4
    """The rule entry's id (edit it at ``path``)."""
    slug: str
    title: str
    status: str
    """draft | inbox | needs_review | approved | published. Only a published rule answers."""
    published: bool
    keywords: list[str]
    reply: str
    networks: list[str]
    """The integration slugs (or network names) it names; empty means every network."""
    all_networks: bool
    post: str
    """A post id or URL; empty means any post."""
    reply_as: str
    also_like: bool
    kinds: list[str]
    path: str


class SocialRuleList(_MarvinModel):
    rules: list[SocialRuleRead]


class SocialRuleNew(_MarvinModel):
    integration: str | None = None
    """The integration's slug to make the rule for; empty makes one for every network."""


class SocialRulePublish(_MarvinModel):
    published: bool = True


class SocialAutoReplyUpdate(_MarvinModel):
    mode: Literal["off", "rehearsal", "on"]


class SocialAutoReplyResult(_MarvinModel):
    integration: str
    auto_reply: str
