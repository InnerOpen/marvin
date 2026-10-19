"""``entry_snapshots`` — a version of an entry, kept so it can be put back (services/snapshots.py).

``snapshot_json`` holds what the entry was: title, summary, description, data, metadata, status, its collections and
its attached assets (references — the asset rows, not the files). A workflow's Snapshot step captures one before a risky
change and restores it after; the entries API does the same for a person. The entry's event history says *what happened*;
this says what it *looked like*. Each entry keeps its latest ``MAX_PER_ENTRY`` snapshots (the oldest go first) and they go
with the entry.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

__all__ = ["EntrySnapshotModel"]


class EntrySnapshotModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "entry_snapshots"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(sa.String(100), nullable=False, default="")
    """Free text the capturer gave it ("before the refresh"); "" when none."""
    source: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="api")
    """workflow | api."""
    snapshot_json: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    created_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    automation_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="SET NULL"), nullable=True)
    """The workflow whose step captured it (None for a person's, or once it is deleted)."""

    __table_args__ = (sa.Index("ix_entry_snapshots_entry_created", "entry_id", "created_at"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
