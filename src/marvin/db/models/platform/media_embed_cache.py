"""Resolved media embeds, shared by every workspace.

One row per link as written (``url_hash`` = sha256 of the trimmed link). Filled by the editor's resolve
endpoint and by ``MediaEmbedReactionListener`` when an entry is saved; read by the publishing API, which
never calls a provider itself. Holds only public facts about public media (title, author, thumbnail,
the Marvin-built player src), so it is platform-wide rather than per workspace — the same YouTube link
in two workspaces is one row and one oEmbed call.

``status``: ``ok`` (a player), ``link`` (no safe player — show a link card), ``unavailable`` (the
provider said 401/403/404). ``expires_at`` is 30 days out for ``ok`` and 1 day otherwise; an expired row
is still served, and refreshed the next time an entry using it is saved or previewed.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class MediaEmbedCacheModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "media_embed_cache"
    __table_args__ = (sa.UniqueConstraint("url_hash", name="uq_media_embed_cache_url_hash"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    url_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """The link as written."""

    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    canonical_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embed_src: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """The Marvin-built iframe src (never provider HTML); null when there is no safe player."""

    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    author_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """Player height in px for audio/podcast players; null for aspect-ratio (video) players."""

    aspect_ratio: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
