"""Keys a stored file had before ``storage_migrate --rekey`` moved it to an opaque key.

One row per old (provider, key): which asset row, or which character-library pack file, now holds the
file. The ``/assets`` mount uses it to redirect an old local URL to the file's current one, and
``storage_migrate --prune-old`` to find the old copies it may delete (``pruned_at`` records that it
did). Rows are kept after a prune: the redirect still needs them.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class StorageKeyAliasModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "storage_key_aliases"
    __table_args__ = (sa.UniqueConstraint("provider", "storage_key", name="uq_storage_key_aliases_provider_key"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    provider: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The provider the old copy is on."""
    storage_key: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    """The old key."""
    current_key: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The key the file was moved to."""
    asset_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True, index=True)
    """The asset row now holding the file (no foreign key: the alias outlives a deleted asset until pruned)."""
    pack_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True)
    """Or the character-library pack whose file it is."""
    pruned_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """When ``--prune-old`` deleted the old copy."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
