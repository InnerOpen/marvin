"""
This module defines Pydantic schemas related to group preferences within the
Marvin application.

These schemas are used for creating, updating, and representing preference
settings associated with a user group, such as privacy settings or display options
like the first day of the week.
"""

from pydantic import UUID4, ConfigDict  # For UUID type and Pydantic model configuration
from sqlalchemy.orm.interfaces import LoaderOption  # Type for loader options

# Corresponding SQLAlchemy models (used in loader_options)
# from marvin.db.models.groups import Groups # Groups model itself is used in a potentially confusing way in loader_options
from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model
from marvin.schemas.platform.submission_protection import SubmissionProtectionOverride


class GroupPreferencesCreate(_MarvinModel):
    """
    Schema for creating group preferences.
    Requires the `group_id` to associate the preferences with a group.
    Specific preference fields (like `private_group`, `first_day_of_week`)
    are expected to be part of the request body if they are to be set,
    otherwise they might rely on database defaults or be set in an update.
    This schema primarily establishes the link to a group.
    """

    group_id: UUID4
    """The unique identifier of the group these preferences belong to."""

    # Optional preference fields that can be set during creation
    private_group: bool = True
    """Indicates if the group is private. Defaults to True."""
    first_day_of_week: int = 0
    """
    Sets the first day of the week for the group (e.g., 0 for Sunday, 1 for Monday).
    Defaults to 0 (Sunday).
    """

    # Site/Workspace Configuration
    site_title: str | None = None
    """The public title of the site/workspace."""
    site_tagline: str | None = None
    """A short tagline or slogan for the site."""
    site_description: str | None = None
    """A description of the site/workspace."""
    site_canonical_url: str | None = None
    """The canonical URL where this site is published."""
    site_logo: str | None = None
    """Path or URL to the site logo."""
    site_favicon: str | None = None
    """Path or URL to the site favicon."""
    site_locale: str | None = "en-US"
    """The locale for the site (e.g., en-US, en-GB)."""
    site_timezone: str | None = "America/New_York"
    """The timezone for the site (e.g., America/New_York)."""
    site_contact_email: str | None = None
    """Primary contact email for the site."""
    site_social_json: dict | None = None
    """DEPRECATED: Social media links. Use site_metadata_json with 'social' key instead."""
    site_metadata_json: dict | None = None
    """Flexible metadata for framework-specific settings. Include social links under 'social' key, SEO under 'seo', etc."""
    submission_protection_json: dict | None = None
    """Workspace override of the platform submission-protection defaults; null fields inherit."""

    model_config = ConfigDict(from_attributes=True)  # Allows creating from ORM model attributes


class GroupPreferencesUpdate(_MarvinModel):  # Typically, update schemas allow partial updates.
    """
    Schema for updating existing group preferences and workspace settings.
    All fields are optional for partial updates.
    The id and group_id are set by the controller based on the URL path.
    """

    id: UUID4 | None = None
    """The unique identifier of the group preferences record to update (set by controller)."""

    group_id: UUID4 | None = None  # Group ID is usually not updatable for existing preferences.
    """The group ID. Typically not changed during an update."""

    # Workspace-level settings (stored in Groups model, not preferences)
    name: str | None = None
    """Optional: The name of the workspace. Slug is auto-generated from name."""

    private_group: bool | None = None
    """Optional: New value for the private group setting."""

    first_day_of_week: int | None = None
    """Optional: New value for the first day of the week setting."""

    # Site/Workspace Configuration (all optional for partial updates)
    site_title: str | None = None
    """Optional: The public title of the site/workspace."""
    site_tagline: str | None = None
    """Optional: A short tagline or slogan for the site."""
    site_description: str | None = None
    """Optional: A description of the site/workspace."""
    site_canonical_url: str | None = None
    """Optional: The canonical URL where this site is published."""
    site_logo: str | None = None
    """Optional: Path or URL to the site logo."""
    site_favicon: str | None = None
    """Optional: Path or URL to the site favicon."""
    site_locale: str | None = None
    """Optional: The locale for the site (e.g., en-US, en-GB)."""
    site_timezone: str | None = None
    """Optional: The timezone for the site (e.g., America/New_York)."""
    site_contact_email: str | None = None
    """Optional: Primary contact email for the site."""
    site_social_json: dict | None = None
    """Optional: DEPRECATED - Social media links. Use site_metadata_json with 'social' key instead."""
    site_metadata_json: dict | None = None
    """Optional: Flexible metadata for framework-specific settings. Include social links under 'social' key, SEO under 'seo', etc."""
    submission_protection_json: SubmissionProtectionOverride | None = None
    """Optional: workspace override of the platform submission-protection defaults; null fields inherit."""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def loader_options(cls) -> list[LoaderOption]:
        """
        Provides SQLAlchemy loader options for optimizing queries related to `GroupPreferencesUpdate`.

        NOTE: The current loader option `joinedload(GroupPreferencesSQLModel).load_only(Groups.group_id)`
        seems problematic or incorrectly structured.
        - `joinedload(GroupPreferencesSQLModel)` implies eagerly loading the `GroupPreferencesSQLModel` itself,
          which doesn't make sense in the context of loading attributes *of* it or related to it.
        - `load_only(Groups.group_id)` would apply to a query for `Groups`, not `GroupPreferencesSQLModel`,
          unless there's a relationship path from `GroupPreferencesSQLModel` to `Groups` that is
          being targeted in a very specific way not immediately obvious.

        If the intent was to load only specific fields of `GroupPreferencesSQLModel` when it's
        part of another query (e.g., when loading a `Group` that has `preferences`),
        then this option would be defined in the schema for `Group` (e.g., `GroupRead`).
        If the intent is to load only the `group_id` *from* the `GroupPreferencesSQLModel` itself,
        it should be `load_only(GroupPreferencesSQLModel.group_id)`.

        Assuming this is a placeholder or needs review. For now, returning an empty list
        or a corrected version if the intent is clear. Given it's on `GroupPreferencesUpdate`,
        loader options are less common for update schemas unless they are also used for reading before update.

        Returns:
            list[LoaderOption]: A list of SQLAlchemy loader options. Currently returning empty.
        """
        # Original: return [joinedload(GroupPreferencesSQLModel).load_only(Groups.group_id)]
        # This is likely incorrect as written. Returning empty or a more standard option.
        # If it's about loading the related Group's ID when preferences are fetched:
        # return [joinedload(GroupPreferencesSQLModel.group).load_only(Groups.id)] # Assuming 'group' is relationship name
        # Or if only specific fields of GroupPreferencesModel itself:
        # return [load_only(GroupPreferencesSQLModel.private_group, GroupPreferencesSQLModel.first_day_of_week)]
        return []  # Returning empty as the original is confusing.


class GroupPreferencesRead(GroupPreferencesCreate):  # Extends Create, but usually Read is more comprehensive.
    """
    Schema for representing group preferences when read from the system.
    Includes all preference fields.
    """

    # Inherits group_id, private_group, first_day_of_week from GroupPreferencesCreate's new definition.
    # If GroupPreferencesCreate was minimal (only group_id), then these would be explicitly defined here.
    # id: UUID4 # Usually a Read schema includes the ID of the preference record itself.
    # private_group: bool = True
    # first_day_of_week: int = 0

    model_config = ConfigDict(from_attributes=True)
    # If this schema needs its own loader_options for when it's nested in other Read schemas,
    # they would be defined here. For example, if it had a relationship to another model.
