"""A package: a named, versioned bundle of blueprints a workspace installed, uploaded or built from its own content.

The manifest (``schemas/platform/packages.py``) is stored whole, so the package can be downloaded again as it was installed. The rows it
created carry its slug in ``source_package`` (``PackagedMixin``), which is what the Workflows page groups and collapses by. See
``services/blueprints/packages.py``.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.guid import GUID


class WorkspacePackageModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workspace_packages"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)

    slug: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str] = mapped_column(sa.String, nullable=False, default="", server_default="")
    version: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="1", server_default="1")
    manifest: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    created_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_workspace_packages_group_slug"),)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
