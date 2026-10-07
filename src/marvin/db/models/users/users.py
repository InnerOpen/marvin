"""
This module defines SQLAlchemy models related to users and authentication.

It includes:
- `AuthMethod`: An enumeration for different authentication methods (Marvin, LDAP, OIDC).
- `LongLiveToken`: A model for storing long-lived API tokens for users.
- `Users`: The main user model, containing user profile information, credentials,
  permissions, and relationships to other parts of the application like groups
  and tokens.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pydantic import ConfigDict
from sqlalchemy import Boolean, ForeignKey, Integer, String, orm, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import Enum as SqlAlchemyEnum  # Explicit import for sqlalchemy Enum type

from marvin.db.models._model_utils.auto_init import auto_init
from marvin.db.models._model_utils.datetime import NaiveDateTime
from marvin.db.models._model_utils.guid import GUID

from .. import BaseMixins, SqlAlchemyBase
from .roles import PlatformRole

if TYPE_CHECKING:
    from ..groups import Groups
    from .password_reset import PasswordResetModel
    from .roles import WorkspaceRole
    from .workspace_members import WorkspaceMembers


class AuthMethod(enum.Enum):
    """
    Enumeration for the authentication methods a user can be associated with.
    """

    MARVIN = "MARVIN"  # Standard username/password authentication managed by Marvin.
    LDAP = "LDAP"  # Authentication via an LDAP server.
    OIDC = "OIDC"  # Authentication via an OpenID Connect provider.


class LongLiveToken(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model for long-lived API tokens (Personal Access Tokens).

    Security model matches APIClients - tokens are hashed with bcrypt,
    support rotation, soft deletion, and usage tracking.

    The `id` (PK), `created_at`, `update_at` are inherited from `BaseMixins`.
    """

    __tablename__ = "long_live_tokens"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the token.")
    name: Mapped[str] = mapped_column(String, nullable=False, doc="User-defined name for the token (e.g., 'CI/CD Token').")
    description: Mapped[str | None] = mapped_column(String, nullable=True, doc="Optional description of token purpose.")

    # Token security (hashed storage - matches APIClients pattern)
    token_hash: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        unique=True,
        doc="Bcrypt hash of the token. Plaintext token never stored.",
    )

    # Lifecycle management
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Whether the token is currently active. Disabled tokens cannot authenticate.",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        NaiveDateTime,
        nullable=True,
        doc="Timestamp of last successful authentication with this token.",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        NaiveDateTime,
        nullable=True,
        doc="Timestamp when token was revoked (soft delete).",
    )

    # Audit trail
    user_id: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="ID of the user this token belongs to.",
    )
    created_by: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
        doc="ID of the user who created this token (audit trail).",
    )

    # Relationship to the User who owns this token
    user: Mapped[Optional["Users"]] = orm.relationship("Users", back_populates="tokens", foreign_keys=[user_id])

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass


class Users(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing a user in the system.

    This model stores all information related to a user, including their profile,
    credentials, authentication method, permissions, and associations with groups
    and tokens.
    """

    __tablename__ = "users"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the user.")
    full_name: Mapped[str | None] = mapped_column(String, index=True, doc="User's full name.")
    username: Mapped[str | None] = mapped_column(String, index=True, unique=True, doc="Unique username for login.")
    email: Mapped[str | None] = mapped_column(String, unique=True, index=True, doc="Unique email address for the user.")
    password: Mapped[str | None] = mapped_column(String, doc="Hashed password for users with 'MARVIN' auth method.")
    auth_method: Mapped[AuthMethod] = mapped_column(
        SqlAlchemyEnum(AuthMethod), default=AuthMethod.MARVIN, doc="Authentication method used by this user."
    )  # Used SqlAlchemyEnum
    admin: Mapped[bool | None] = mapped_column(
        Boolean,
        default=False,
        doc="Indicates if the user has administrative privileges system-wide. Defaults to False.",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="DEPRECATED: Use platform_role instead. Platform-level administrator with access to all workspaces. Kept for backward compatibility.",
    )
    platform_role: Mapped[PlatformRole] = mapped_column(
        SqlAlchemyEnum(PlatformRole),
        nullable=False,
        default=PlatformRole.NONE,
        doc="Platform-level role. Determines platform-wide permissions. SUPER_ADMIN has unrestricted access.",
    )
    advanced: Mapped[bool | None] = mapped_column(
        Boolean, default=False, doc="DEPRECATED: Legacy field. Indicates if the user has access to advanced features. Defaults to False."
    )

    # Foreign key to the Groups model
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id"), nullable=False, index=True, doc="ID of the group this user belongs to.")
    # Relationship to the Group the user belongs to
    group: Mapped["Groups"] = orm.relationship("Groups", back_populates="users", foreign_keys=[group_id])

    # Active workspace tracking (multi-workspace support)
    active_group_id: Mapped[GUID | None] = mapped_column(
        GUID,
        ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The workspace the user is currently working in. Falls back to group_id if NULL.",
    )
    active_workspace: Mapped["Groups | None"] = orm.relationship(
        "Groups",
        foreign_keys=[active_group_id],
        doc="Active workspace relationship",
    )

    # Security and state fields
    cache_key: Mapped[str | None] = mapped_column(
        String,
        default="1234",
        doc="A cache key that can be used for invalidating user-specific caches. Defaults to '1234'.",
    )  # Consider making this dynamic
    # NOTE: Field name 'login_attemps' is intentionally misspelled (missing 't') for
    # backward compatibility with existing database schema. Do not rename without migration.
    # See: https://github.com/yourorg/marvin/issues/XXX for tracking proper migration
    login_attemps: Mapped[int | None] = mapped_column(
        Integer, default=0, doc="Number of failed login attempts. Resets on successful login. Defaults to 0."
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        NaiveDateTime,
        default=None,
        nullable=True,
        doc="Timestamp (UTC) when the user account was locked due to excessive failed logins. Null if not locked.",
    )  # Added nullable=True

    # Group-level Permissions (could be refactored into a separate roles/permissions system for more granularity)
    can_manage: Mapped[bool | None] = mapped_column(
        Boolean, default=False, doc="Indicates if the user can manage their current group. Defaults to False."
    )
    can_invite: Mapped[bool | None] = mapped_column(
        Boolean, default=False, doc="Indicates if the user can invite others to their current group. Defaults to False."
    )
    # `can_organize` is used in `_set_permissions` but not a mapped column. This implies it might be a transient or calculated permission.

    # Common arguments for one-to-many relationships from User to token-like models
    _token_relationship_args = {
        "back_populates": "user",  # Assumes 'user' field on LongLiveToken and PasswordResetToken
        "cascade": "all, delete, delete-orphan",  # Operations on User cascade to these tokens
        "single_parent": True,  # User is the single parent
    }

    # Relationship to LongLiveToken (one-to-many: one user can have many API tokens)
    # Use foreign_keys to specify which FK to use (user_id, not created_by)
    tokens: Mapped[list["LongLiveToken"]] = orm.relationship("LongLiveToken", foreign_keys="LongLiveToken.user_id", **_token_relationship_args)
    # Relationship to PasswordResetModel (one-to-many: one user can have multiple password reset tokens over time)
    password_reset_tokens: Mapped[list["PasswordResetModel"]] = orm.relationship("PasswordResetModel", **_token_relationship_args)

    # Relationship to WorkspaceMembers (one-to-many: one user can be a member of many workspaces)
    workspace_memberships: Mapped[list["WorkspaceMembers"]] = orm.relationship(
        "WorkspaceMembers",
        back_populates="user",
        cascade="all, delete, delete-orphan",
    )

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        # Fields to exclude from Pydantic model serialization by default for security or verbosity.
        exclude={
            "password",  # Never serialize password hashes.
            "admin",  # Admin status might be exposed via other means if needed.
            "is_superuser",  # Superuser status should be controlled via specific schemas.
            "can_manage",  # Permissions might be part of a dedicated permissions endpoint.
            "can_invite",
            "group",  # Group details might be fetched separately or via a nested schema.
            "tokens",  # Tokens should generally not be listed directly with user details.
            "password_reset_tokens",  # These are internal and should not be serialized.
            "locked_at",  # Internal security detail.
            "login_attemps",  # Internal security detail.
            "cache_key",  # Internal detail.
        },
    )

    @hybrid_property
    def group_slug(self) -> str | None:
        """
        Returns the slug of the group this user belongs to.
        Returns None if the group or group slug is not set.

        DEPRECATED: This uses the legacy single group_id.
        For multi-workspace support, iterate workspace_memberships instead.
        """
        return self.group.slug if self.group else None

    def is_platform_admin(self) -> bool:
        """Check if user is a platform administrator (SUPER_ADMIN)."""
        return self.platform_role == PlatformRole.SUPER_ADMIN

    def get_effective_workspace_id(self) -> GUID:
        """
        Returns active workspace if set, otherwise falls back to primary group_id.

        Returns:
            GUID: The workspace ID to use for scoping operations.
        """
        return self.active_group_id or self.group_id

    def get_workspace_role(self, group_id: str) -> "WorkspaceRole | None":
        """
        Get the user's role in a specific workspace.

        Args:
            group_id: The workspace/group ID to check.

        Returns:
            WorkspaceRole if user is a member, None otherwise.
        """

        for membership in self.workspace_memberships:
            if str(membership.group_id) == str(group_id):
                return membership.workspace_role
        return None

    def has_workspace_role(self, group_id: str, required_role: "WorkspaceRole") -> bool:
        """
        Check if user has a specific role (or higher) in a workspace.

        Args:
            group_id: The workspace/group ID to check.
            required_role: The minimum required role.

        Returns:
            True if user has the required role or higher privilege.
        """
        from .roles import workspace_role_has_higher_or_equal_privilege

        user_role = self.get_workspace_role(group_id)
        if user_role is None:
            return False
        return workspace_role_has_higher_or_equal_privilege(user_role, required_role)

    @auto_init()
    def __init__(self, session: Session, full_name: str, password: str, group: str | None = None, **kwargs) -> None:
        """
        Initializes a new User instance.

        The `auto_init` decorator handles setting attributes from `kwargs`.
        This method sets up the user's group and initial password, and default username if not provided.

        Args:
            session (Session): The SQLAlchemy session.
            full_name (str): The user's full name.
            password (str): The user's plaintext password (will be hashed by the service layer before saving).
            group (str | None, optional): The name of the group to assign the user to.
                                         Defaults to the platform workspace.
            **kwargs: Additional attributes for the user, processed by `auto_init`
                      (e.g., `username`, `email`, `admin`).

        Raises:
            ValueError: If the specified group does not exist.
        """
        # `auto_init` will process kwargs first. Values explicitly set here will override
        # those from kwargs if they share the same name, or complement them.

        from marvin.db.models.groups import Groups  # Local import to avoid circularity

        # Query for the group. auto_init does not handle this specific lookup logic.
        if group is None:
            # No group named: the platform (admin's) workspace — by its marker, whatever it's called.
            from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace

            try:
                self.group = platform_workspace(session)
            except PlatformWorkspaceMissing as e:
                raise ValueError("No group given and no platform workspace exists; cannot create user.") from e
        else:
            self.group = session.execute(select(Groups).filter(Groups.name == group)).scalars().one_or_none()
            if self.group is None:
                raise ValueError(f"Group '{group}' does not exist; cannot create user.")

        # Password should be set after auto_init if it's also in kwargs,
        # or ensure it's not processed by auto_init if handled exclusively here.
        # Assuming password hashing happens at a higher service layer.
        self.password = password  # Store as provided; hashing should occur before DB commit.

        # Set username from full_name if username is not provided in kwargs
        # This relies on `auto_init` having already processed `username` from `kwargs` if present.
        if self.username is None and full_name:  # Check full_name as it's a required arg
            self.username = full_name

        # Set permissions based on kwargs (e.g., admin status)
        self._set_permissions(**kwargs)

    @auto_init()  # auto_init might re-apply some fields from kwargs if not careful.
    def update(
        self,
        session: Session,
        full_name: str | None = None,
        email: str | None = None,
        group: str | None = None,
        username: str | None = None,
        **kwargs,
    ) -> None:
        """
        Updates attributes of an existing User instance.

        The `auto_init` decorator assists in setting attributes from `kwargs`.
        This method specifically handles updates to core fields like name, email, group, and username.

        Args:
            session (Session): The SQLAlchemy session.
            full_name (str | None, optional): New full name.
            email (str | None, optional): New email address.
            group (str | None, optional): Name of the new group to assign the user to.
            username (str | None, optional): New username.
            **kwargs: Additional attributes to update, processed by `auto_init`.
        """
        # Attributes directly passed are set. kwargs might override them if auto_init runs after these lines.
        # However, auto_init wraps this, so these explicit assignments happen within the wrapped function.
        # It's generally safer for auto_init to handle fields passed in kwargs.
        # Fields explicitly in signature are for clarity or specific logic.

        if username is not None:
            self.username = username
        if full_name is not None:
            self.full_name = full_name
        if email is not None:
            self.email = email

        if group:
            from marvin.db.models.groups import Groups  # Local import

            queried_group = session.execute(select(Groups).filter(Groups.name == group)).scalars().one_or_none()
            if queried_group is None:
                raise ValueError(f"Group '{group}' does not exist; cannot update user's group.")
            self.group = queried_group

        # Fallback for username if it ends up None and full_name is available
        if self.username is None and self.full_name:
            self.username = self.full_name

        self._set_permissions(**kwargs)

    def update_password(self, password: str) -> None:
        """
        Updates the user's password.

        Args:
            password (str): The new plaintext password. Hashing should be handled
                            by the service layer before calling this or committing.
        """
        self.password = password

    def _set_permissions(
        self,
        admin: bool | None = None,
        is_superuser: bool = False,
        can_manage: bool = False,
        can_invite: bool = False,
        can_organize: bool = False,
        **kwargs,
    ) -> None:
        """
        Sets user permissions based on the admin flag and other permission flags.

        If `admin` is True, all other specific permissions (`can_manage`, `can_invite`,
        `advanced`, `can_organize`) are also set to True. Otherwise, they are set
        based on the provided arguments.

        Note: `can_organize` is a parameter here but not a mapped database column.
        Its effect might be transient or used to derive other settings if applicable.

        Args:
            admin (bool | None, optional): System-wide admin status. If None, existing status is maintained unless other flags imply changes.
            is_superuser (bool, optional): Platform-level super admin status. Super admins can access all workspaces. Defaults to False.
            can_manage (bool, optional): Permission to manage the group. Defaults to False.
            can_invite (bool, optional): Permission to invite users to the group. Defaults to False.
            can_organize (bool, optional): Placeholder for organizational permissions. Not a DB field. Defaults to False.
        """
        if admin is not None:
            self.admin = admin

        # Set is_superuser - this must be explicitly passed, not derived from admin
        self.is_superuser = is_superuser

        if self.admin:  # If user is admin, grant all other managed permissions
            self.can_manage = True
            self.can_invite = True
            self.advanced = True
            self.can_organize = True  # Not a DB field, so assignment has no direct DB effect.
        else:  # If not admin, set permissions as provided (or their defaults)
            self.can_manage = can_manage
            self.can_invite = can_invite
            self.can_organize = can_organize  # No DB field
            # `advanced` status for non-admins might be set explicitly or based on other criteria.
            # If `admin` was just set to False, ensure `advanced` is also False unless specified.
            if admin is False:  # Explicitly making non-admin
                self.advanced = kwargs.get("advanced", False)  # Check kwargs if advanced is passed

        # Ensure can_organize doesn't cause issues if it was intended for a DB field.
        # For now, it's just a local variable in its effect if not a class attribute.
        # If it _was_ meant to be a class attribute not mapped, it would be `self.can_organize = True/can_organize`
        # but this is not typical for non-mapped attributes within a DB model method like this.
        # Assuming `can_organize`'s primary role here is for the logic if admin.
