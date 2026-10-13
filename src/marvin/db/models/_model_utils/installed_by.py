"""Installed by: which integration's blueprint created a row.

Shared by everything a blueprint can create — workflows, scheduled tasks, incoming webhooks,
integration event subscriptions and collections. Set in one place, ``services/blueprints/apply.py``;
never writable through the API. Both NULL means a person made it.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .guid import GUID


class InstalledByMixin:
    source_integration_id: Mapped[GUID | None] = mapped_column(
        GUID,
        sa.ForeignKey("integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The integration whose blueprint created this row (NULL: made by a person, or the integration is gone).",
    )
    source_blueprint: Mapped[str | None] = mapped_column(
        sa.String,
        nullable=True,
        doc="The key (slug) of the blueprint that created this row.",
    )
