"""``social_inbox_items`` — the comments, replies and mentions the social engagement poll read, kept so a person can see
and act on them (Social inbox page; services/integrations/social_inbox.py).

One row per (integration, network item id). The 5-minute poll writes them as it reads (both the announce and the reply
read, deduplicated by the unique key); the account's own items are never stored; a daily system task
(``prune_social_inbox_items``) drops rows older than the retention window (30 days). Deleted with the workspace and with
the integration.

``status`` is new | seen | replied | hidden | liked (see ``social_inbox.next_status`` for how an action moves it). What was
replied is the ``social-reply-log`` entry named by ``reply_log_slug`` — the engine's own dedupe key — so the row only
points at it; the log stays the source of truth.
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
    """The ``social-reply-log`` entry (its slug) for the reply: rehearsal or sent, an auto-reply rule's or a person's."""
    reply_mode: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """private | public | both."""
    reply_rehearsal: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """True when ``reply_log_slug`` is a rehearsal entry (nothing was sent). A real reply replaces it."""
    reply_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    replied_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    """The person who replied from the inbox; empty for a rule's reply."""

    __table_args__ = (
        sa.UniqueConstraint("integration_id", "item_id", name="uq_social_inbox_items_item"),
        sa.Index("ix_social_inbox_items_group_posted", "group_id", "posted_at"),
        sa.Index("ix_social_inbox_items_group_status", "group_id", "status"),
        sa.Index("ix_social_inbox_items_first_seen", "first_seen_at"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
