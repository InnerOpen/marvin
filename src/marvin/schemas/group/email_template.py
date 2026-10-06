"""Pydantic schemas for email templates."""

from datetime import datetime

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class EmailTemplateCreate(_MarvinModel):
    """Schema for creating a new email template."""

    template_type: str = Field(..., description="Type of email (invitation, password_reset, welcome, custom, test)")
    group_id: UUID4 | None = Field(None, description="Workspace ID - null for system-wide templates")
    name: str = Field(..., description="Human-readable template name")
    description: str | None = Field(None, description="Description of when this template is used")
    subject: str = Field(..., description="Email subject line - supports Jinja2 variables")
    body_markdown: str | None = Field(None, description="Markdown body rendered via default.html template")
    custom_html: str | None = Field(None, description="Full custom HTML - if set, overrides body_markdown")
    available_variables: dict | None = Field(None, description="Documentation of available variables")
    enabled: bool = Field(True, description="Whether this template is active")


class EmailTemplateUpdate(_MarvinModel):
    """Schema for updating an email template."""

    name: str | None = None
    description: str | None = None
    subject: str | None = None
    body_markdown: str | None = None
    custom_html: str | None = None
    available_variables: dict | None = None
    enabled: bool | None = None


class EmailTemplateRead(_MarvinModel):
    """Schema for reading an email template."""

    id: UUID4
    template_type: str
    group_id: UUID4 | None
    name: str
    description: str | None
    subject: str
    body_markdown: str | None
    custom_html: str | None
    available_variables: dict | None
    enabled: bool
    created_at: datetime
    update_at: datetime

    model_config = {"from_attributes": True}


class EmailTemplateSummary(_MarvinModel):
    """Summary schema for listing email templates."""

    id: UUID4
    template_type: str
    name: str
    description: str | None
    enabled: bool
    group_id: UUID4 | None = None  # None = system template, set = workspace customization

    model_config = {"from_attributes": True}


class SystemEmailVariable(_MarvinModel):
    """A {{ variable }} the replaced email's event provides (from the event catalog)."""

    slug: str
    description: str
    example: str
    type: str


class SystemEmailRead(_MarvinModel):
    """One of Marvin's own emails (welcome, password reset, invitation) that a workspace template of the same type
    can replace: `GET /api/platform/workspaces/{group_id}/email-templates/system-emails`."""

    template_type: str
    """The template type that replaces it (welcome, password_reset, invitation)."""
    label: str
    """How it reads: "welcome email"."""
    event_type: str
    """The event it is sent on (user_signup, user_password_reset_requested, invitation_sent)."""
    event_name: str
    """The catalog's name for that event."""
    recipient_type: str
    recipient_field: str | None = None
    """Who a replacing template is sent to: the connection uses these, like Marvin's own email does."""
    system_template_id: UUID4 | None = None
    """Marvin's own template (none when it doesn't exist on this install)."""
    system_sends: bool
    """Whether Marvin's own email is sent now: it is unless an enabled workspace template of this type replaces it."""
    replaced_by: list[UUID4] = []
    """The workspace templates that replace it now (the same rule the Events page shows)."""
    variables: list[SystemEmailVariable] = []
    """The variables its event provides, from the event catalog."""
