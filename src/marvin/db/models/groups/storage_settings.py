"""SQLAlchemy models for a workspace's own asset storage ("bring your own storage").

A workspace keeps the platform's storage until its settings row says `workspace` and names an active connection.
Each connection is one bucket; asset rows stored in it record `ws:<connection id>` as their `storage_provider`, so a
connection is kept (retired, never deleted) while rows point at it. See services/storage/workspace.py.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class WorkspaceStorageSettingsModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workspace_storage_settings"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    # "platform" | "workspace" — no row is "platform"
    credential_mode: Mapped[str] = mapped_column(sa.String, default="platform", nullable=False)
    active_connection_id: Mapped[GUID | None] = mapped_column(
        GUID, sa.ForeignKey("workspace_storage_connections.id", ondelete="SET NULL"), nullable=True
    )
    # Workspace backup bundles include files in the workspace's own bucket (off: size and egress are theirs).
    bundle_includes_own_bucket: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False, server_default=sa.false())
    updated_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass


class WorkspaceStorageConnectionModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workspace_storage_connections"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    plugin_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # The provider's non-secret workspace settings, keyed by Setting.env (bucket, endpoint, region, prefix, public URL…).
    # Bucket, endpoint and prefix never change on a connection: a different bucket is a new connection.
    settings: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    # {Setting.env: workspace secret slug}: every secret setting, and any other a workspace keeps as a secret (the
    # access key ID); never the values themselves.
    secret_refs: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    # "unverified" | "ok" | "failing" | "retired"
    status: Mapped[str] = mapped_column(sa.String, default="unverified", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # HMAC of the resolved keys when last verified: a later mismatch means the keys changed unverified.
    credential_fingerprint: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # Bumped on every edit; the built provider is cached by (id, version).
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False, server_default="1")
    created_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
