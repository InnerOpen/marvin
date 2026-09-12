"""Platform-wide, admin-editable settings — one JSON document per key.

`AppSettings` (env/.env) covers deploy-time configuration that never changes at runtime. This table is
for the small set of policies a platform admin adjusts from the UI and that workspaces may inherit
(submission protection is the first). Keyed rather than columnar so the next such setting is a new
key, not a migration.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID


class PlatformSettingsModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "platform_settings"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    key: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True, index=True)
    """Setting name, e.g. ``submission_protection``."""
    value_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """The setting document, validated by the owning schema before it is stored."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
