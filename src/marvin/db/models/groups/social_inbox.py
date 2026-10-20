"""``social_inbox_items`` — the comments, replies and mentions the social engagement poll read, kept so a person can see
and act on them (Social inbox page; services/integrations/social_inbox.py).

One row per (integration, network item id). The 5-minute poll writes them as it reads (both the announce and the reply
read, deduplicated by the unique key); the account's own items are never stored; a daily system task
(``prune_social_inbox_items``) drops rows older than the retention window (30 days). Deleted with the workspace and with
the integration.

``status`` is new | seen | replied | hidden | liked (see ``social_inbox.next_status`` for how an action moves it).

**The reply is recorded on the row** (``reply_*``, ``replied_at``, ``replied_by``): the item is the reply log. A live reply
(``replied_at`` set, ``reply_rehearsal`` false) is what stops the engine answering the comment again; a rehearsal's is a dry
run that a real reply replaces. A reply to a comment not stored yet inserts the row first, so every reply has an item. Items
with a live reply are kept longer than the rest (``social_inbox.REPLIED_RETENTION_DAYS``), which is what makes pruning safe.
``reply_log_slug`` points at an older ``social-reply-log`` entry (written before replies moved here); nothing reads or writes it now.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import AwareDateTime
from .._model_utils.guid import GUID

__all__ = ["SocialInboxItemModel"]


class SocialInboxItemModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "social_inbox_items"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    network: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The plugin's own name for the network (``instagram``, ``mastodon``…)."""

    item_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The network's id for the item — the ``comment_id`` every social capability takes."""
    kind: Mapped[str] = mapped_column(sa.String, nullable=False, default="comment")
    """comment | reply | mention."""
    post_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    post_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    author_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    author_handle: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    posted_at: Mapped[datetime] = mapped_column(AwareDateTime, nullable=False)
    """When the network says it was written; the time first seen when the network gives none. What the list sorts on."""
    url: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, nullable=False)

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="new", server_default="new")
    """new | seen | replied | hidden | liked."""

    reply_log_slug: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """A legacy ``social-reply-log`` entry (its slug) for the reply, from before replies were recorded on the item. Neither read nor written now."""
    reply_mode: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """private | public | both."""
    reply_rehearsal: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """True when the recorded reply is a rehearsal (a dry run: nothing was sent). A real reply replaces it."""
    reply_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    replied_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    """The person who replied from the inbox; empty for a rule's reply."""
    reply_rule: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The slug of the rule entry whose reply was sent (or rehearsed); empty for a person's reply."""
    reply_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """What was sent (or would have been, in a rehearsal)."""
    reply_note: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """A note on the reply: why one half of a "both" reply failed (the other half was sent)."""

    __table_args__ = (
        sa.UniqueConstraint("integration_id", "item_id", name="uq_social_inbox_items_item"),
        sa.Index("ix_social_inbox_items_group_posted", "group_id", "posted_at"),
        sa.Index("ix_social_inbox_items_group_status", "group_id", "status"),
        sa.Index("ix_social_inbox_items_first_seen", "first_seen_at"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
