"""
This module defines the SQLAlchemy model for group-specific preferences.

It includes the `GroupPreferencesModel`, which stores various settings and
preferences that can be configured for each user group.
"""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column  # Added Session for __init__

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class GroupPreferencesModel(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing preferences for a user group.

    This model stores settings like whether a group is private and what the
    first day of the week should be for display purposes within that group.
    """

    __tablename__ = "group_preferences"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the group preferences entry.")

    # Foreign key to the Groups model, establishing a one-to-one relationship
    # as each group has one set of preferences.
    group_id: Mapped[GUID] = mapped_column(
        GUID,
        sa.ForeignKey("groups.id"),
        nullable=False,
        index=True,
        unique=True,
        doc="ID of the group these preferences belong to.",
    )
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="preferences")

    # Preference settings
    private_group: Mapped[bool | None] = mapped_column(
        sa.Boolean, default=True, doc="If True, the group is private and not publicly visible. Defaults to True."
    )
    first_day_of_week: Mapped[int | None] = mapped_column(
        sa.Integer,
        default=0,
        doc="The first day of the week (e.g., 0 for Sunday, 1 for Monday). Defaults to 0 (Sunday).",
    )

    # Site/Workspace Configuration
    # These fields define the public identity of the workspace when accessed through the publishing API
    site_title: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="The public title of the site/workspace.")
    site_tagline: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="A short tagline or slogan for the site.")
    site_description: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="A description of the site/workspace.")
    site_canonical_url: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="The canonical URL where this site is published.")
    site_logo: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="Path or URL to the site logo.")
    site_favicon: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="Path or URL to the site favicon.")
    site_locale: Mapped[str | None] = mapped_column(sa.String, nullable=True, default="en-US", doc="The locale for the site (e.g., en-US, en-GB).")
    site_timezone: Mapped[str | None] = mapped_column(
        sa.String, nullable=True, default="America/New_York", doc="The timezone for the site (e.g., America/New_York)."
    )
    site_contact_email: Mapped[str | None] = mapped_column(sa.String, nullable=True, doc="Primary contact email for the site.")
    site_auto_rebuild: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.true(),
        doc="Request a (coalesced) static-site rebuild whenever published content changes.",
    )
    scheduled_publish_requires_approval: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
        doc="Scheduled publish only publishes due entries whose status is 'approved'; others wait for approval.",
    )
    integration_alert_reminder_hours: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=24,
        server_default="24",
        doc="An open integration alert is announced again after this many hours (0 = never remind).",
    )
    trash_auto_empty_days: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Days an entry stays in the Trash before it is deleted forever (0 = never). Null inherits the platform "
        "default (services/entries/trash.py).",
    )
    site_social_json: Mapped[dict | None] = mapped_column(
        sa.JSON, nullable=True, doc="Social media links and handles (e.g., {instagram: 'url', facebook: 'url'})."
    )
    site_metadata_json: Mapped[dict | None] = mapped_column(
        sa.JSON, nullable=True, doc="Flexible metadata for framework-specific or custom site settings."
    )

    submission_protection_json: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        doc="Workspace override of the platform submission-protection defaults (null fields inherit).",
    )

    audit_overrides_json: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        doc="Event types whose audit-log coverage differs from the catalog default: {event_type: bool}. "
        "Read and written through services/events/audit_settings.py (locked types ignore it).",
    )

    notifications_json: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        doc="Where the workspace's alerts go (Settings → Automation → Notifications): {types, email, routes}. Null takes "
        "the defaults. Read and written through services/workspace_alerts.py.",
    )
    notifications_status_json: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        doc="Each notification channel's last delivery: {channel: {at, outcome, detail, event_type, test}}. Written by "
        "delivery only, so saving the settings never races it.",
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """
        Initializes a GroupPreferencesModel instance.

        Attributes are set by the `auto_init` decorator from `kwargs`.
        The `session` argument is required by `auto_init`.

        Args:
            session (Session): The SQLAlchemy session, required by `auto_init`.
            **kwargs: Attributes for the model, such as `private_group`,
                      `first_day_of_week`, and `group_id` or `group`.
        """
        # All initialization is handled by auto_init based on kwargs.
        # Example:
        # prefs = GroupPreferencesModel(session=db_session, private_group=False, first_day_of_week=1, group_id=group.id)
        pass
