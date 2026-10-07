"""
This module defines Pydantic schemas related to user groups within the Marvin application.

It includes schemas for creating, updating (with admin-specific variations),
reading, summarizing, and paginating group data. These schemas are used for
API request validation, response serialization, and potentially for internal
data transfer.
"""

from typing import Annotated  # For adding metadata to type hints (e.g., StringConstraints)

from pydantic import UUID4, ConfigDict, StringConstraints  # Core Pydantic components and constraints

# SQLAlchemy ORM imports for loader_options method.
# These are relevant for optimizing database queries when fetching related data.
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.interfaces import LoaderOption

# Corresponding SQLAlchemy models (used in loader_options)
from marvin.db.models.groups import Groups
from marvin.db.models.users import Users  # For specifying nested loading for users within a group
from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model
from marvin.schemas.response.pagination import PaginationBase  # Base for pagination responses

# Schemas from related domains (user, group preferences, webhooks)
from ..user import UserSummary  # Summary schema for users within a group
from .preferences import GroupPreferencesRead, GroupPreferencesUpdate  # Schemas for group preferences
from .webhook import WebhookCreate, WebhookRead  # Schemas for group webhooks


class GroupCreate(_MarvinModel):
    """
    Schema for creating a new group. Requires only a name.
    The name will be stripped of whitespace and must have a minimum length of 1.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """The name of the group. Must be at least 1 character long after stripping whitespace."""

    model_config = ConfigDict(from_attributes=True)  # Allows creating from ORM model attributes


class GroupAdminUpdate(GroupCreate):
    """
    Schema for administrators to update a group.
    Allows updating the name and group preferences. Inherits `name` from `GroupCreate`.
    """

    id: UUID4
    """The unique identifier of the group to update."""
    name: str  # Overrides name to not have Annotated constraints here, or could re-apply if needed
    """The new name for the group."""
    slug: str | None = None
    """Optional: a new URL slug (slugified). Omitted, a name change derives the slug from the new name."""
    preferences: GroupPreferencesUpdate | None = None
    """Optional: New preference settings for the group. If None, preferences are not updated."""


class GroupUpdate(GroupCreate):  # This seems like a user-facing update schema
    """
    Schema for regular users to update a group they manage (details depend on permissions).
    Allows updating the name and associated webhooks. Inherits `name` from `GroupCreate`.
    """

    id: UUID4
    """The unique identifier of the group to update."""
    name: str  # Overrides name
    """The new name for the group."""
    webhooks: list[WebhookCreate] = []  # TODO: Should this be WebhookUpdate or a list of IDs/full objects?
    """
    A list of webhook configurations to associate with the group.
    This implies replacing all existing webhooks with this new list.
    Using `WebhookCreate` here suggests creating new webhooks during group update,
    which might be complex. Often, webhook management is separate.
    """


class GroupRead(GroupUpdate):  # Extends GroupUpdate, which might be unusual if GroupUpdate is for input.
    # Often, Read schemas are more comprehensive or extend a base.
    """
    Schema for representing a group when read from the system, including detailed information.
    This typically serves as a response model for GET requests.
    Inherits `id`, `name`, and `webhooks` (as `WebhookRead`) from `GroupUpdate`.
    """

    id: UUID4
    """The unique identifier of the group."""
    slug: str | None = None
    """The URL-friendly slug of the group."""
    is_platform: bool = False
    """True on the platform (admin's) workspace — platform alerts and shared services run from it."""
    users: list[UserSummary] | None = None
    """
    DEPRECATED: Legacy users with group_id = this workspace.
    For workspace members with roles, use GET /api/admin/workspaces/{id}/members
    """
    preferences: GroupPreferencesRead | None = None
    """Optional group preference settings."""
    webhooks: list[WebhookRead] = []  # Overrides webhooks to use WebhookRead for output
    """List of webhooks configured for this group."""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def loader_options(cls) -> list[LoaderOption]:
        """
        Provides SQLAlchemy loader options for optimizing queries for `GroupRead`.

        Configures eager loading for:
        - `webhooks` relationship (joined load).
        - `preferences` relationship (joined load).
        - `users` relationship (selectin load), and within users:
            - `group` back-reference (joined load).
            - `tokens` for users (joined load).
        This helps prevent N+1 query problems.

        Returns:
            list[LoaderOption]: A list of SQLAlchemy loader options.
        """
        return [
            joinedload(Groups.webhooks),  # Eager load associated webhooks
            joinedload(Groups.preferences),  # Eager load associated preferences
            selectinload(Groups.users).joinedload(Users.group),  # Eager load users (legacy), and their group (back-ref)
            selectinload(Groups.users).joinedload(Users.tokens),  # Eager load users (legacy), and their API tokens
        ]


class GroupSummary(GroupCreate):  # Extends GroupCreate, which only has 'name'.
    """
    Schema for a summary representation of a group.
    Provides key identifying information like ID, name, slug, and preferences.
    """

    id: UUID4
    """The unique identifier of the group."""
    name: str  # Inherited from GroupCreate, but explicitly listed for clarity
    """The name of the group."""
    slug: str
    """The URL-friendly slug of the group."""
    is_platform: bool = False
    """True on the platform (admin's) workspace."""
    preferences: GroupPreferencesRead | None = None
    """Optional group preference settings."""

    # model_config from_attributes=True is inherited from GroupCreate via _MarvinModel

    @classmethod
    def loader_options(cls) -> list[LoaderOption]:
        """
        Provides SQLAlchemy loader options for optimizing queries for `GroupSummary`.

        Configures eager loading for the `preferences` relationship.

        Returns:
            list[LoaderOption]: A list of SQLAlchemy loader options.
        """
        return [
            joinedload(Groups.preferences),  # Eager load associated preferences
        ]


class GroupPagination(PaginationBase):
    """
    Schema for paginated responses containing a list of groups.
    The items in the list are expected to conform to the `GroupRead` schema.
    """

    items: list[GroupRead]
    """The list of groups for the current page, serialized as `GroupRead`."""
