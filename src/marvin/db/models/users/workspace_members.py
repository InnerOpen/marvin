"""
Workspace membership model for Marvin.

Tracks user-workspace relationships with role-based permissions.
"""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import Enum as SqlAlchemyEnum

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID
from .roles import WorkspaceRole

if TYPE_CHECKING:
    from ..groups import Groups
    from .users import Users


class WorkspaceMembers(SqlAlchemyBase, BaseMixins):
    """
    Junction table tracking user membership in workspaces with roles.

    Replaces the single group_id on Users with a many-to-many relationship
    that includes workspace-specific roles.

    This allows:
    - Users to belong to multiple workspaces
    - Each membership to have a specific role (OWNER, ADMIN, EDITOR, AUTHOR, VIEWER)
    - Fine-grained permission control per workspace
    """

    __tablename__ = "workspace_members"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the membership.")

    # Foreign keys
    user_id: Mapped[GUID] = mapped_column(
        GUID,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the user who is a member.",
    )

    group_id: Mapped[GUID] = mapped_column(
        GUID,
        sa.ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the workspace (group) the user is a member of.",
    )

    # Role within this workspace
    workspace_role: Mapped[WorkspaceRole] = mapped_column(
        SqlAlchemyEnum(WorkspaceRole),
        nullable=False,
        doc="The role this user has within this specific workspace.",
    )

    # Relationships
    user: Mapped[Optional["Users"]] = orm.relationship("Users", back_populates="workspace_memberships")
    workspace: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="members")

    # Unique constraint: a user can only have one membership per workspace
    __table_args__ = (sa.UniqueConstraint("user_id", "group_id", name="uq_workspace_member"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """
        Initialize a workspace membership.

        Args:
            session (Session): SQLAlchemy session.
            **kwargs: Membership attributes (user_id, group_id, workspace_role).
        """
        pass

    def __repr__(self) -> str:
        """String representation of the membership."""
        return f"<WorkspaceMembers user={self.user_id} workspace={self.group_id} role={self.workspace_role.value}>"
