"""
This module provides functionalities for sending emails via SMTP.

It defines data classes for email options, SMTP responses, and email messages,
an abstract base class for email senders, and a default SMTP email sender
implementation that uses Python's `smtplib`.
"""

import smtplib
import typing  # For Any type hint
from abc import ABC, abstractmethod  # For creating abstract base classes
from dataclasses import dataclass  # For creating simple data classes
from email import message as email_message  # Renamed to avoid conflict with Message dataclass
from email.utils import formatdate  # For formatting dates in email headers
from uuid import uuid4  # For generating unique message IDs

from html2text import html2text  # For converting HTML email content to plain text

from marvin.core.root_logger import get_logger
from marvin.services import BaseService  # Base service class for common functionalities

logger = get_logger()

SMTP_TIMEOUT = 10
"""Timeout in seconds for SMTP connection operations (e.g., connect, login, send)."""


@dataclass(slots=True)  # slots=True for optimized memory usage
class EmailOptions:
    """
    Dataclass for storing SMTP server configuration options.
    """

    host: str
    """Hostname or IP address of the SMTP server."""
    port: int
    """Port number for the SMTP server."""
    username: str | None = None
    """Optional username for SMTP authentication."""
    password: str | None = None
    """Optional password for SMTP authentication."""
    tls: bool = False
    """If True, use STARTTLS for secure communication. Defaults to False."""
    ssl: bool = False
    """If True, use SMTP_SSL for secure communication from the start. Defaults to False."""


@dataclass(slots=True)
class SMTPResponse:
    """
    Dataclass for representing the response from an SMTP server after sending an email.
    """

    success: bool
    """True if the email was sent successfully, False otherwise."""
    message: str
    """A human-readable message describing the outcome (e.g., "Message Sent")."""
    errors: typing.Any  # smtplib.send_message returns a dict of errors if any.
    """
    Any errors returned by the SMTP server during the send operation.
    Typically a dictionary where keys are recipient addresses that failed.
    An empty dictionary usually indicates success for all recipients.
    """


@dataclass(slots=True)
class Message(BaseService):
    """
    Dataclass representing an email message to be sent.
    Includes content, sender information, and a method to send itself.
    """

    subject: str
    """The subject line of the email."""
    html: str
    """The HTML content of the email."""
    mail_from_name: str
    """The display name of the sender."""
    mail_from_address: str
    """The email address of the sender."""

    def send(self, to_address: str, smtp_config: EmailOptions) -> SMTPResponse:  # Renamed params for clarity
        """
        Constructs and sends the email message using the provided SMTP configuration.

        The email is sent with both HTML and plain text alternatives (HTML converted to plain text).
        It handles SMTP connection (SSL or TLS based on `smtp_config`) and authentication if credentials are provided.

        Args:
            to_address (str): The recipient's email address.
            smtp_config (EmailOptions): The SMTP server configuration.

        Returns:
            SMTPResponse: An object indicating the success or failure of the send operation,
                          along with any server errors.
        """
        # Create an EmailMessage object
        msg = email_message.EmailMessage()
        msg["Subject"] = self.subject
        msg["From"] = f"{self.mail_from_name} <{self.mail_from_address}>"
        msg["To"] = to_address
        msg["Date"] = formatdate(localtime=True)  # Use local time for the Date header

        # Add plain text and HTML alternatives for the email body
        msg.set_content(html2text(self.html))  # Main content as plain text
        msg.add_alternative(self.html, subtype="html")  # HTML alternative

        # Generate a unique Message-ID
        try:
            # Attempt to create a domain part from the sender's email address
            domain_part = self.mail_from_address.split("@", 1)[1]
            message_id_value = f"<{uuid4()}@{domain_part}>"
        except IndexError:
            # Fallback if sender's email address is not standard (e.g., no '@')
            # This is unlikely for valid emails but provides a robust fallback.
            self.logger.warning(f"Could not parse domain from sender email '{self.mail_from_address}' for Message-ID. Using address as domain.")
            message_id_value = f"<{uuid4()}@{self.mail_from_address}>"
            # The SMTP server itself might also assign a Message-ID if this one is problematic.

        msg["Message-ID"] = message_id_value

        # Send the email using SMTP or SMTP_SSL
        send_errors: dict = {}  # To store errors from server.send_message()
        try:
            if smtp_config.ssl:
                # Use SMTP_SSL for connections that are SSL from the start
                with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port, timeout=SMTP_TIMEOUT) as server:
                    if smtp_config.username and smtp_config.password:
                        server.login(smtp_config.username, smtp_config.password)
                    send_errors = server.send_message(msg)
            else:
                # Use standard SMTP, with optional STARTTLS
                with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=SMTP_TIMEOUT) as server:
                    if smtp_config.tls:  # Upgrade to TLS if enabled
                        server.starttls()
                    if smtp_config.username and smtp_config.password:  # Authenticate if credentials provided
                        server.login(smtp_config.username, smtp_config.password)
                    send_errors = server.send_message(msg)

            # An empty `send_errors` dictionary means the message was accepted for all recipients.
            success = not send_errors
            response_message = "Message sent successfully." if success else "Failed to send message to some recipients."
            return SMTPResponse(success=success, message=response_message, errors=send_errors)

        except smtplib.SMTPException as e:  # Catch various SMTP errors (connection, auth, etc.)
            self.logger.error(f"SMTP error while sending email to {to_address}: {e}")
            return SMTPResponse(success=False, message=f"SMTP error: {e}", errors={to_address: (0, str(e))})  # Simulate error dict
        except Exception as e:  # Catch any other unexpected errors
            self.logger.error(f"Unexpected error sending email to {to_address}: {e}")
            return SMTPResponse(success=False, message=f"Unexpected error: {e}", errors={to_address: (0, str(e))})


class ABCEmailSender(ABC):
    """
    Abstract Base Class for email sender implementations.

    Defines the contract for sending an email, requiring subclasses to implement
    a `send` method.
    """

    @abstractmethod
    def send(self, email_to: str, subject: str, html_content: str) -> bool:  # Renamed html to html_content
        """
        Abstract method to send an email.

        Args:
            email_to (str): The recipient's email address.
            subject (str): The subject line of the email.
            html_content (str): The HTML content of the email.

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        ...  # Ellipsis indicates that this method must be implemented by subclasses.


class DefaultEmailSender(ABCEmailSender, BaseService):
    """
    Marvin's own SMTP sender: the platform SMTP server (services/platform_smtp), i.e. the environment's ``SMTP_*``
    settings with whatever an admin overrode in Admin → Email, merged field by field.

    Without a ``config`` it reads the one in force at send time, so a saved change applies to the next mail.
    """

    def __init__(self, config=None) -> None:
        self._config = config

    @property
    def config(self):
        from marvin.services import platform_smtp

        return self._config or platform_smtp.effective()

    def deliver(self, email_to: str, subject: str, html_content: str) -> SMTPResponse:
        """
        Sends an email through the platform SMTP server and returns the server's answer.

        Raises:
            ValueError: If essential SMTP settings (From address and name, host, port) are not configured.
        """
        config = self.config
        # Validate that essential sender information is configured
        if not config.from_email or not config.from_name:
            self.logger.error("SMTP From address and name must be set for sending emails.")
            raise ValueError("The SMTP From address and name must be set (Admin → Email, or SMTP_FROM_EMAIL / SMTP_FROM_NAME).")

        email_msg = Message(
            subject=subject,
            html=html_content,
            mail_from_name=config.from_name,
            mail_from_address=config.from_email,
        )

        # Validate that essential SMTP server settings are configured
        if not config.host or not config.port:
            self.logger.error("SMTP host and port must be set for sending emails.")
            raise ValueError("The SMTP host and port must be set (Admin → Email, or SMTP_HOST / SMTP_PORT).")

        smtp_options = EmailOptions(
            host=config.host,
            port=config.port,
            username=config.username or None,
            password=config.password or None,
            tls=config.tls,
            ssl=config.ssl,
        )
        return email_msg.send(to_address=email_to, smtp_config=smtp_options)

    def send(self, email_to: str, subject: str, html_content: str) -> bool:
        """
        Sends an email through the platform SMTP server.

        Returns:
            bool: True if the email was sent successfully, False otherwise.

        Raises:
            ValueError: If essential SMTP settings are not configured (see `deliver`).
        """
        smtp_response = self.deliver(email_to, subject, html_content)

        self.logger.debug(
            f"Send email result to {email_to}: {smtp_response.message}, Success: {smtp_response.success}, Errors: {smtp_response.errors}"
        )

        if not smtp_response.success:
            # Log detailed errors if sending failed
            self.logger.error(
                f"Failed to send email to {email_to}. Subject: '{subject}'. SMTP Response: {smtp_response.message}, Errors: {smtp_response.errors}"
            )

        return smtp_response.success


class WorkspaceEmailSender(ABCEmailSender, BaseService):
    """Email sender that routes through a workspace's **active** SMTP profile.

    When the workspace has an active `WorkspaceSMTPProfileModel`, mail is sent via that
    profile's server/credentials/From. When it has none, this transparently falls back to the
    platform's sender (`platform_sender`), so behaviour is unchanged until a workspace activates a
    profile.
    """

    def __init__(self, group_id) -> None:
        self.group_id = group_id

    def _active_profile(self) -> dict | None:
        """Return the active profile's fields as a plain dict, or None. Read into a dict so the
        values remain usable after the session closes (detached-instance safe)."""
        from sqlalchemy import select

        from marvin.db.db_setup import session_context
        from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel

        try:
            with session_context() as session:
                row = (
                    session.execute(
                        select(WorkspaceSMTPProfileModel).where(
                            WorkspaceSMTPProfileModel.group_id == self.group_id,
                            WorkspaceSMTPProfileModel.is_active.is_(True),
                        )
                    )
                    .scalars()
                    .first()
                )
                if row is None:
                    return None
                return {
                    "name": row.name,
                    "host": row.host,
                    "port": row.port,
                    "username": row.username,
                    "secret_ref": row.secret_ref,
                    "from_name": row.from_name,
                    "from_email": row.from_email,
                    "auth_strategy": row.auth_strategy,
                }
        except Exception as e:
            self.logger.warning(f"Could not load active SMTP profile for group {self.group_id}: {e}")
            return None

    def send(self, email_to: str, subject: str, html_content: str) -> bool:
        profile = self._active_profile()
        if not profile:
            # No active profile — behave exactly like the platform's sender.
            return platform_sender().send(email_to, subject, html_content)

        from marvin.services import platform_smtp

        platform = platform_smtp.effective()  # the platform's From, when the profile sets none of its own
        from_email = profile["from_email"] or platform.from_email
        from_name = profile["from_name"] or platform.from_name or "Marvin"
        if not from_email:
            self.logger.error(f"Active SMTP profile '{profile['name']}' has no From address and the platform SMTP has none to fall back on.")
            return False

        password = None
        if profile["secret_ref"]:
            from marvin.services.secrets.resolver import resolve_secret

            password = resolve_secret(profile["secret_ref"], self.group_id)
            if password is None:
                self.logger.error(f"Could not resolve SMTP password (secret '{profile['secret_ref']}') for profile '{profile['name']}'.")
                return False

        strategy = (profile["auth_strategy"] or "TLS").upper()
        options = EmailOptions(
            host=profile["host"],
            port=int(profile["port"]),
            username=profile["username"] or None,
            password=password,
            tls=strategy == "TLS",
            ssl=strategy == "SSL",
        )
        message = Message(
            subject=subject,
            html=html_content,
            mail_from_name=from_name,
            mail_from_address=from_email,
        )
        result = message.send(to_address=email_to, smtp_config=options)
        if result.success:
            self.logger.info(f"Email '{subject}' sent to {email_to} via SMTP profile '{profile['name']}'.")
        else:
            self.logger.error(f"SMTP profile '{profile['name']}' failed to send '{subject}' to {email_to}: {result.message}")
        return result.success


def _has_active_profile(group_id, session=None) -> bool:
    """Whether the workspace has an active SMTP profile of its own."""
    from sqlalchemy import select

    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel

    stmt = select(WorkspaceSMTPProfileModel.id).where(WorkspaceSMTPProfileModel.group_id == group_id, WorkspaceSMTPProfileModel.is_active.is_(True))
    try:
        if session is not None:
            return session.execute(stmt.limit(1)).first() is not None
        with session_context() as own:
            return own.execute(stmt.limit(1)).first() is not None
    except Exception as e:  # a failed lookup must not stop mail the platform SMTP could still send
        logger.warning(f"Could not look up the active SMTP profile of {group_id}: {e}")
        return False


def platform_sender() -> ABCEmailSender:
    """Who sends mail that isn't a workspace's own (password resets, platform alerts, the admin test, a workspace
    without an SMTP profile): the platform SMTP server — the environment's settings with Admin → Email's overrides."""
    return DefaultEmailSender()


def email_ready(group_id=None, session=None) -> bool:
    """Whether mail can go out — for ``group_id``, through its own active SMTP profile or the platform SMTP server;
    for anything else, through the platform SMTP server (services/platform_smtp)."""
    from marvin.services import platform_smtp

    return platform_smtp.ready() or bool(group_id and _has_active_profile(group_id, session))
