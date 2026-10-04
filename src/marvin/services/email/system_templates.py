"""
System email template definitions and seeder.

System templates (group_id=NULL) are the defaults for all system emails.
Workspace owners can "Customize" them to create workspace-specific overrides.

Each definition includes:
  - required_vars: {{lower_case}} slugs that MUST be present for the email to work
  - optional_vars: nice to have but not critical
  - default content with the variables shown in context
"""

from dataclasses import dataclass, field

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)


@dataclass
class SystemTemplateDefinition:
    template_type: str
    name: str
    description: str
    subject: str
    body_markdown: str
    required_vars: list[str]
    optional_vars: list[str] = field(default_factory=list)


SYSTEM_TEMPLATES: list[SystemTemplateDefinition] = [
    SystemTemplateDefinition(
        template_type="invitation",
        name="Workspace Invitation",
        description="Sent when a user is invited to join a workspace.",
        subject="You've been invited to join {{workspace_name}}",
        body_markdown=(
            "{{inviter_name}} has invited you to join **{{workspace_name}}**.\n\n"
            "Click the link below to accept the invitation and get started:\n\n"
            "{{invitation_url}}\n\n"
            "If you weren't expecting this invitation, you can safely ignore this email. "
            "The link will expire in 7 days."
        ),
        required_vars=["invitation_url", "workspace_name"],
        optional_vars=["inviter_name"],
    ),
    SystemTemplateDefinition(
        template_type="password_reset",
        name="Password Reset",
        description="Sent when a user requests a password reset.",
        subject="Reset your Marvin password",
        body_markdown=(
            "We received a request to reset the password for your account ({{username}}).\n\n"
            "Click the link below to choose a new password. This link expires in {{expiry_hours}} hours:\n\n"
            "{{reset_url}}\n\n"
            "If you didn't request a password reset, you can safely ignore this email. "
            "Your password will not be changed."
        ),
        required_vars=["reset_url"],
        optional_vars=["username", "expiry_hours"],
    ),
    SystemTemplateDefinition(
        template_type="welcome",
        name="Welcome",
        description="Sent when a new user joins a workspace.",
        subject="Welcome to {{workspace_name}}!",
        body_markdown=(
            "Welcome, **{{first_name}}**!\n\n"
            "Your account has been created and you're now a member of **{{workspace_name}}**.\n\n"
            "Click the link below to log in:\n\n"
            "{{login_url}}\n\n"
            "Need help? Reach out to your workspace administrator."
        ),
        required_vars=["login_url"],
        optional_vars=["first_name", "username", "workspace_name"],
    ),
    SystemTemplateDefinition(
        template_type="integration_alert",
        name="Integration Alert",
        description="Sent to workspace admins when a connection needs attention, and again when it works again. "
        "Chosen under Settings → Integrations → Integration alerts.",
        subject="{{title}}",
        body_markdown=(
            "{{summary}}\n\n"
            "Connection: **{{integration_name}}** ({{provider_name}}) · error code `{{code}}`\n\n"
            "{{settings_url}}\n\n"
            "You get one email when the alert opens, a reminder while it stays open, and one when it is resolved — "
            "never one per affected item."
        ),
        required_vars=["title", "summary"],
        optional_vars=["integration_name", "provider_name", "code", "settings_url", "count", "error", "resolution"],
    ),
    SystemTemplateDefinition(
        template_type="custom",
        name="Custom Notification",
        description="General-purpose custom notification email. Edit to suit any event.",
        subject="Notification from {{workspace_name}}",
        body_markdown="Write your message here. Use **{{ variable }}** for dynamic values.",
        required_vars=[],
        optional_vars=["workspace_name"],
    ),
]

# Quick lookup by type
TEMPLATE_BY_TYPE: dict[str, SystemTemplateDefinition] = {t.template_type: t for t in SYSTEM_TEMPLATES}


def get_required_vars(template_type: str) -> list[str]:
    """Return required variable slugs for a template type."""
    defn = TEMPLATE_BY_TYPE.get(template_type)
    return defn.required_vars if defn else []


def validate_template_content(template_type: str, content_fields: dict[str, str]) -> list[str]:
    """
    Check that all required {{variable}} slugs appear somewhere in the template content.

    Returns a list of missing required variable slugs (empty = all present).
    """
    required = get_required_vars(template_type)
    if not required:
        return []

    all_content = " ".join(v for v in content_fields.values() if v)
    missing = [slug for slug in required if "{{" + slug + "}}" not in all_content]
    return missing


def seed_system_templates(session) -> int:
    """
    Create system templates (group_id=NULL) if they don't already exist.
    Idempotent — skips existing template types. Returns count of created templates.
    """
    from sqlalchemy import select

    from marvin.db.models.groups.email_templates import EmailTemplateModel

    created = 0
    for defn in SYSTEM_TEMPLATES:
        existing = session.execute(
            select(EmailTemplateModel).where(
                EmailTemplateModel.template_type == defn.template_type,
                EmailTemplateModel.group_id.is_(None),
            )
        ).scalar_one_or_none()

        if existing:
            # Update content in case seeded templates have changed
            existing.body_markdown = defn.body_markdown
            existing.subject = defn.subject
            existing.available_variables = {
                "required": defn.required_vars,
                "optional": defn.optional_vars,
            }
            continue

        template = EmailTemplateModel(session=session)
        template.template_type = defn.template_type
        template.name = defn.name
        template.description = defn.description
        template.subject = defn.subject
        template.body_markdown = defn.body_markdown
        template.group_id = None
        template.enabled = True
        template.available_variables = {
            "required": defn.required_vars,
            "optional": defn.optional_vars,
        }
        session.add(template)
        created += 1
        logger.info(f"Seeded system email template: {defn.template_type}")

    session.commit()
    if created:
        logger.info(f"Email template seeder: created {created} system template(s)")
    else:
        logger.info("Email template seeder: system templates updated")

    return created
