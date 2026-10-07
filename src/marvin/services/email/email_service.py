"""
This module provides services for constructing and sending emails within the
Marvin application.

It defines an `EmailTemplate` Pydantic model to structure email content and an
`EmailService` class responsible for rendering these templates into HTML and
dispatching emails using a configurable email sender (defaulting to SMTP).
The service supports sending various types of emails, such as password resets,
invitations, and test emails.
"""

from pathlib import Path  # For path manipulation (template directory)

from jinja2 import Template  # For rendering HTML templates
from pydantic import BaseModel  # For creating data models like EmailTemplate

from marvin.core.root_logger import get_logger  # Application logger
from marvin.services import BaseService  # Base service class

# Email sender implementations
from .email_senders import ABCEmailSender, DefaultEmailSender

# Current working directory of this file, used to locate the 'templates' subdirectory.
CWD = Path(__file__).parent

# Logger instance for this module
logger = get_logger()


class EmailTemplate(BaseModel):
    """
    Pydantic model representing the content structure for an email template.

    This model holds various parts of an email, such as subject, header,
    messages, and call-to-action button details. The content for these fields
    is often provided as localization keys (e.g., "emails.password.subject")
    which would be resolved by a translation service if integrated.
    """

    subject: str
    header_text: str
    message_top: str
    message_bottom: str = ""
    button_link: str = ""
    button_text: str = ""
    workspace_name: str = ""

    def render_html(self, template_file: Path) -> str:  # Renamed `template` to `template_file`
        """
        Renders the email content into an HTML string using a Jinja2 template.

        The method reads the template content from the provided `template_file` path
        and renders it by passing the current `EmailTemplate` instance's data
        (converted to a dictionary) to the template.

        Args:
            template_file (Path): The path to the Jinja2 HTML template file.

        Returns:
            str: The rendered HTML content as a string.
        """
        # Read the template file content
        tmpl_str = template_file.read_text(encoding="utf-8")  # Added encoding
        jinja_template = Template(tmpl_str)  # Create a Jinja2 Template object

        # Render the template with the data from this EmailTemplate instance
        # The template should expect a 'data' variable containing the model's fields.
        return jinja_template.render(data=self.model_dump())


class EmailService(BaseService):
    """
    Service class for sending emails.

    This service handles the construction of email content using `EmailTemplate`
    and dispatches emails through a configured email sender (which defaults to
    `DefaultEmailSender` if not provided). It provides methods for sending
    specific types of application emails like password resets and invitations.
    """

    def __init__(self, sender: ABCEmailSender | None = None, locale: str | None = None, group_id: str | None = None) -> None:
        """
        Initializes the EmailService.

        Args:
            sender (ABCEmailSender | None, optional): An email sender instance.
                If None, `DefaultEmailSender` is used. Defaults to None.
            locale (str | None, optional): The locale string (e.g., "en_US") for
                email localization. Currently, the translator part is commented out,
                so this parameter's effect is pending full i18n implementation.
                Defaults to None.
        """
        self.templates_dir: Path = CWD / "templates"  # Path to the email templates directory
        self.default_template: Path = self.templates_dir / "default.html"  # Path to the default email template

        if Path(self.templates_dir / self.settings.EMAIL_TEMPLATE).is_file():
            self.default_template = self.templates_dir / self.settings.EMAIL_TEMPLATE  # Path to the default email template per settings

        if Path(self.directories.TEMPLATE_DIR / self.settings.EMAIL_TEMPLATE).is_file():
            self.templates_dir = self.directories.TEMPLATE_DIR
            self.default_template = self.templates_dir / self.settings.EMAIL_TEMPLATE

        # Workspace-level override — highest priority
        if group_id:
            workspace_template = self.directories.TEMPLATE_DIR / str(group_id) / self.settings.EMAIL_TEMPLATE
            if workspace_template.is_file():
                self.default_template = workspace_template

        self.logger.debug(f"Loading {self.templates_dir} in {self.default_template}")

        # Sender resolution:
        #  - explicit sender wins
        #  - otherwise, when scoped to a workspace, route through its active SMTP profile
        #    (WorkspaceEmailSender falls back to global settings when none is active)
        #  - unscoped falls back to the global DefaultEmailSender
        if sender is not None:
            self.sender: ABCEmailSender = sender
        elif group_id:
            from marvin.services.email.email_senders import WorkspaceEmailSender

            self.sender = WorkspaceEmailSender(group_id)
        else:
            self.sender = DefaultEmailSender()

        # Placeholder for localization/translation functionality.
        # If uncommented, `local_provider` would need to be defined and return a Translator instance.
        # self.translator: Translator = local_provider(locale)
        # For now, string keys in EmailTemplate will be used as-is if no translation occurs.
        self.logger.info(f"EmailService initialized. Sender: {type(self.sender).__name__}. Locale: {locale or 'default'}.")

    def _can_send(self) -> bool:
        """Whether email can be dispatched: global SMTP is configured, OR this service is
        scoped to a workspace that has an active SMTP profile of its own."""
        if self.settings.SMTP_ENABLED:
            return True
        from marvin.services.email.email_senders import WorkspaceEmailSender

        if isinstance(self.sender, WorkspaceEmailSender):
            return self.sender._active_profile() is not None
        return False

    def send_email(self, email_to: str, email_data: EmailTemplate) -> bool:  # Renamed `data` to `email_data`
        """
        Sends an email using the configured sender and default HTML template.

        This is a generic method used by more specific email sending methods.
        It checks if SMTP is enabled in settings before attempting to send.

        Args:
            email_to (str): The recipient's email address.
            email_data (EmailTemplate): An `EmailTemplate` instance containing the
                                        content for the email.

        Returns:
            bool: True if the email was sent successfully (or if SMTP is disabled),
                  False otherwise. Note: Returning True when SMTP is disabled might
                  be misleading; consider alternative return or logging.
        """
        if not self._can_send():
            self.logger.info(f"SMTP is disabled. Email not sent to {email_to} (Subject: {email_data.subject}).")
            # Returning False might be more indicative that no email was actually sent.
            # However, if the intent is "operation considered successful if SMTP off", True is okay.
            # Let's change to False for clarity that no email dispatch occurred.
            return False

        # Render the HTML content using the default template and email_data
        html_content = email_data.render_html(self.default_template)

        # Send the email via the configured sender
        success = self.sender.send(email_to, email_data.subject, html_content)
        if success:
            self.logger.info(f"Email '{email_data.subject}' sent successfully to {email_to}.")
        else:
            self.logger.error(f"Failed to send email '{email_data.subject}' to {email_to}.")
        return success

    def send_forgot_password(
        self,
        recipient_address: str,
        reset_password_url: str,
        username: str = "",
        group_id: str | None = None,
    ) -> bool:
        """Sends a password reset email, using a DB template if available."""
        db_template = self._get_db_template("password_reset", group_id)
        if db_template:
            return self._send_db_template(
                recipient_address,
                db_template,
                {
                    "reset_url": reset_password_url,
                    "button_link": reset_password_url,
                    "username": username,
                    "expiry_hours": "24",
                },
            )
        forgot_password_template = EmailTemplate(
            subject="Reset your password",
            header_text="Password Reset Request",
            message_top=f"We received a request to reset the password for {username or 'your account'}.",
            message_bottom="If you didn't request this, you can safely ignore this email.",
            button_link=reset_password_url,
            button_text="Reset Password",
        )
        return self.send_email(recipient_address, forgot_password_template)

    def send_invitation(
        self,
        recipient_address: str,
        invitation_url: str,
        group_id: str | None = None,
        workspace_name: str = "",
        inviter_name: str = "",
        variables: dict | None = None,
    ) -> bool:
        """
        Sends a group invitation email to a prospective user.

        The email contains a unique URL for accepting the invitation and registering. The link is a live credential,
        so it's sent from here — never through the event bus, whose events every member can read. The template is
        Marvin's own invitation email, or the workspace's template that replaces it (services/email/
        system_email_events.py `system_email_route`, the rule the email settings and event pages show), always to
        `recipient_address`; with neither, the built-in one.

        Args:
            recipient_address (str): The email address of the person being invited.
            invitation_url (str): The URL the recipient will click to accept the invitation.
            group_id (str | None): Workspace ID for workspace-specific templates.
            variables (dict | None): More template variables (the invitation_sent event's payload fields).

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP, system_email_route
        from marvin.services.events.event_variables import enrich_variables

        with session_context() as session:
            route = system_email_route(session, group_id, SYSTEM_TEMPLATE_EVENT_MAP["invitation"]["event_type"]) or []
            db_templates = [t for t in (session.get(EmailTemplateModel, r.template_id) for r in route) if t is not None]

        if db_templates:
            template_variables = enrich_variables(
                {
                    **(variables or {}),
                    "email_address": recipient_address,
                    "invitation_url": invitation_url,
                    "button_link": invitation_url,
                    "workspace_name": workspace_name,
                    "inviter_name": inviter_name,
                },
                group_id,
            )
            results = [self._send_db_template(recipient_address, t, template_variables) for t in db_templates]
            return all(results)

        # Fallback to hardcoded template
        invitation_template = EmailTemplate(
            subject="Invitation to Join",
            header_text="You're Invited!",
            message_top="You have been invited to join",
            message_bottom="Please click the button above to accept the invitation.",
            button_link=invitation_url,
            button_text="Accept Invitation",
        )
        return self.send_email(recipient_address, invitation_template)

    def send_test_email(self, recipient_address: str) -> bool:  # Renamed param
        """
        Sends a test email to verify SMTP configuration.

        The email uses generic test content and links to the application's base URL.
        Content is defined by localization keys.

        Args:
            recipient_address (str): The email address to send the test email to.

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        # Construct the EmailTemplate with content specific for a test email
        test_email_template = EmailTemplate(
            subject="Test Email",  # Localization key for subject
            header_text="Test Email",
            message_top="This is a test email",
            message_bottom="Please click the button above to test the email.",
            button_link=str(self.settings.BASE_URL),  # Link to the application's base URL
            button_text="Open",
        )
        return self.send_email(recipient_address, test_email_template)

    def _get_db_template(self, template_type: str, group_id: str | None = None):
        """Get email template from database.

        Looks for workspace-specific template first, then system-wide template.

        Args:
            template_type: Type of template (invitation, password_reset, etc.)
            group_id: Workspace ID for workspace-specific templates

        Returns:
            EmailTemplateModel or None if not found
        """
        try:
            from marvin.db.db_setup import session_context
            from marvin.db.models.groups.email_templates import EmailTemplateModel

            with session_context() as session:
                # Try workspace-specific template first
                if group_id:
                    template = session.query(EmailTemplateModel).filter_by(template_type=template_type, group_id=group_id, enabled=True).first()
                    if template:
                        return template

                # Fall back to system-wide template
                template = session.query(EmailTemplateModel).filter_by(template_type=template_type, group_id=None, enabled=True).first()
                return template
        except Exception as e:
            self.logger.warning(f"Failed to load database template '{template_type}': {e}")
            return None

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        """Convert markdown to HTML. Handles headings, bold, italic, links, bare URLs, paragraphs."""
        import re

        # Escape HTML special characters
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Headings (must run before paragraph splitting, line-by-line)
        text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
        text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
        text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)

        # Bold and italic
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

        # Markdown links [text](url)
        text = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)

        # Bare URLs not already in an href
        text = re.sub(r'(?<!["\'=>])(https?://[^\s<>"\']+)', r'<a href="\1">\1</a>', text)

        # Split on double newline → paragraphs; wrap non-block lines in <p>
        paragraphs = re.split(r"\n{2,}", text.strip())
        html_parts = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if para.startswith("<h") or para.startswith("<ul") or para.startswith("<ol"):
                html_parts.append(para)
            else:
                html_parts.append(f"<p>{para.replace(chr(10), '<br>')}</p>")

        return "\n".join(html_parts)

    def _send_db_template(self, recipient_address: str, db_template, variables: dict) -> bool:
        """Send email using database template.

        Supports two modes (custom_html takes priority):
        1. custom_html: Full HTML rendered with Jinja2 and injected into default.html
        2. body_markdown: Markdown converted to HTML and injected into default.html

        {{SLUG}} workspace secrets/variables are resolved before Jinja2 rendering.

        Args:
            recipient_address: Email recipient
            db_template: EmailTemplateModel from database
            variables: Dictionary of variables to render in the template

        Returns:
            bool: True if email sent successfully
        """
        try:
            subject, html_content = self.render_db_template(db_template, variables)
        except ValueError:
            raise  # Missing-required-variable errors propagate to the caller.
        except Exception as e:
            self.logger.error(f"Error rendering database template: {e}")
            return False

        # Send via configured sender
        if not self._can_send():
            self.logger.info(f"SMTP is disabled. Email not sent to {recipient_address} (Subject: {subject}).")
            return False

        success = self.sender.send(recipient_address, subject, html_content)
        if success:
            self.logger.info(f"Email '{subject}' sent successfully to {recipient_address} (DB template: {db_template.name}).")
        else:
            self.logger.error(f"Failed to send email '{subject}' to {recipient_address}.")
        return success

    def render_db_template(self, db_template, variables: dict) -> tuple[str, str]:
        """Render a DB email template to ``(subject, html_content)``.

        Supports two modes (custom_html takes priority):
        1. custom_html: Full HTML rendered with Jinja2 and sent as-is (no chrome wrapper).
        2. body_markdown: Markdown → HTML, injected into the default.html chrome.

        {{SLUG}} workspace secrets/variables are resolved before Jinja2 rendering.
        Raises ValueError if the template is missing required variables.
        """
        from marvin.services.email.system_templates import validate_template_content

        # Validate required variables first so ValueError propagates to the caller.
        has_custom_html = bool(db_template.custom_html and db_template.custom_html.strip())
        if not has_custom_html:
            content_fields = {
                "subject": db_template.subject or "",
                "body_markdown": db_template.body_markdown or "",
            }
            missing = validate_template_content(db_template.template_type or "", content_fields)
            if missing:
                raise ValueError(f"Template is missing required variables: {', '.join('{{' + v + '}}' for v in missing)}")

        from jinja2 import Template

        from marvin.services.secrets.resolver import resolve

        group_id = getattr(db_template, "group_id", None)

        def _r(text: str | None) -> str:
            return resolve(text or "", group_id, allow_secrets=False, context=variables)

        # Render subject with Jinja2
        try:
            subject = Template(_r(db_template.subject)).render(**variables)
        except Exception:
            subject = db_template.subject or "(no subject)"

        # Shared button_link derivation
        button_link = (
            variables.get("invitation_url")
            or variables.get("reset_url")
            or variables.get("login_url")
            or variables.get("action_url")
            or variables.get("button_link", "")
        )

        def _render_safe(text: str) -> str:
            """Render Jinja2 template, falling back to raw text on syntax/render errors."""
            try:
                return Template(_r(text)).render(**variables)
            except Exception as exc:
                self.logger.warning(f"Template render error (sending raw): {exc}")
                return text

        # Determine rendering mode
        raw_custom = db_template.custom_html or ""
        if raw_custom.strip():
            # Mode 1: custom_html — render Jinja2 variables and send as-is (no chrome wrapper)
            return subject, _render_safe(raw_custom)

        # Mode 2: body_markdown — render Jinja2 variables, convert to HTML, inject into default.html chrome
        raw_markdown = db_template.body_markdown or ""
        rendered_markdown = _render_safe(raw_markdown)
        body_html = self._markdown_to_html(rendered_markdown)
        template_data = EmailTemplate(
            subject=subject,
            header_text=variables.get("message_title", ""),
            message_top=body_html,
            message_bottom="",
            button_link=button_link,
            button_text="",
            workspace_name=variables.get("workspace_name", ""),
        )
        return subject, template_data.render_html(self.default_template)
