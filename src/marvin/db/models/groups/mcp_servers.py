"""SQLAlchemy model for per-workspace external MCP server registrations."""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class WorkspaceMcpServerModel(SqlAlchemyBase, BaseMixins):
    """An external MCP server the workspace's agent may draw tools from.

    Deny-by-default: no tool is callable until its name is in `allowed_tools`. HTTP/SSE transports
    only for now (no stdio / local subprocess). Managed by ADMIN/OWNER and gated overall by the
    workspace `external_mcp_enabled` master switch on WorkspaceAISettingsModel.
    """

    __tablename__ = "workspace_mcp_servers"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="mcp_servers")

    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    # "http" | "sse" (stdio parked — would require the server binary installed on the host)
    transport: Mapped[str] = mapped_column(sa.String, default="http", nullable=False)
    url: Mapped[str] = mapped_column(sa.String, nullable=False)
    # slug of a WorkspaceSecret holding an auth token/header value (optional)
    secret_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    # DENY-by-default allowlist of tool names the agent may call from this server (null/empty = none)
    allowed_tools: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    created_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_mcp_servers_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
