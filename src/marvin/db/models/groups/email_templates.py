"""Database model for email templates."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from marvin.db.models import BaseMixins, SqlAlchemyBase
from marvin.db.models._model_utils.auto_init import auto_init
from marvin.db.models._model_utils.guid import GUID


class EmailTemplateModel(SqlAlchemyBase, BaseMixins):
    """Email templates stored in the database.

    Supports both system-wide templates (group_id=None) and workspace-specific
    templates (group_id set). Templates support Jinja2 variable substitution.

    Rendering modes (mutually exclusive, custom_html takes priority):
    - body_markdown: Markdown body rendered to HTML and placed in the email layout (with the workspace's brand)
    - custom_html: Full HTML template that overrides the default layout entirely

    Template types:
    - invitation: Workspace invitation emails
    - password_reset: Password reset emails
    - welcome: Welcome emails for new users
    - custom: Custom / general-purpose notification emails
    - test: Test emails for SMTP verification
    """

    __tablename__ = "email_templates"

    # Override id from SqlAlchemyBase to use GUID instead of Integer
    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the email template")

    # Template identifier and scope
    template_type: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        index=True,
        doc="Type of email template (invitation, password_reset, welcome, custom, test)",
    )
    group_id: Mapped[GUID | None] = mapped_column(
        GUID,
        sa.ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Group/workspace ID - null for system-wide templates",
    )

    # Template metadata
    name: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        doc="Human-readable name for the template",
    )
    description: Mapped[str | None] = mapped_column(
        sa.String,
        nullable=True,
        doc="Description of when this template is used",
    )

    # Email content - supports two modes (custom_html takes priority):
    # 1. body_markdown: Markdown body rendered to HTML and placed in the email layout
    # 2. custom_html: Full HTML template that overrides the default layout entirely
    subject: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        doc="Email subject line - supports Jinja2 variables like {{ user_name }}",
    )
    body_markdown: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        doc="Markdown body, placed in the email layout with the workspace's brand. Supports Jinja2 variables.",
    )
    custom_html: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        doc="Full custom HTML template - if set, overrides body_markdown. Supports Jinja2 variables.",
    )

    # Template variables documentation
    available_variables: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        doc="JSON object documenting available variables for this template type",
    )

    # Status
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        doc="Whether this template is active",
    )

    __table_args__ = ()

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
