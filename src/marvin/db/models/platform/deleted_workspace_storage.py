"""Stored files a deleted workspace left behind, waiting out their grace period before they are purged.

Deleting a workspace cascades its asset rows away, which would orphan the files they pointed at (platform R2, local
disk, or the workspace's own bucket). Before the delete, one row per storage location is recorded here: the
location, the key prefix (``<storage code>/``) plus any keys outside it (older ``<slug>/assets/...`` keys), what it
held, and when the workspace was deleted. A daily system task purges the rows older than the grace period; an admin
can purge one now, or keep it (never purged). No foreign key to ``groups``: the workspace is gone.

``connection`` is a snapshot of a workspace's own bucket (plugin, plain settings, and the names of platform secrets
holding copies of its keys), because the connection row and the workspace's secrets go with the workspace.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

STATE_PENDING, STATE_KEPT, STATE_PURGED = "pending", "kept", "purged"


class DeletedWorkspaceStorageModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "deleted_workspace_storage"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    workspace_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)
    """The deleted workspace's id (no foreign key: it no longer exists)."""
    workspace_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    workspace_slug: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    location: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The asset rows' ``storage_provider``: ``local``, ``r2``, ... or ``ws:<connection id>``."""
    label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """A human name for the location (the provider, or the workspace bucket's label)."""
    prefix: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The workspace's key prefix at that location (``<storage code>/``): everything under it is the workspace's."""
    extra_keys: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    """Keys of the workspace's files outside the prefix (older key layouts), purged by name."""
    object_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    connection: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """For a workspace's own bucket: ``{plugin_slug, settings, secrets: {setting: platform secret slug}}``."""
    deleted_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    state: Mapped[str] = mapped_column(sa.String, nullable=False, default=STATE_PENDING, server_default=STATE_PENDING, index=True)
    """``pending`` (purged once the grace period has passed), ``kept`` (never purged) or ``purged``."""
    state_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    purged_objects: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Why the last purge attempt didn't finish; the next daily run tries again."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
