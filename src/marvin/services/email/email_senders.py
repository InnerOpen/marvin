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

from marvin.services import BaseService  # Base service class for common functionalities

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
    Default email sender implementation for Marvin using SMTP.

    This class uses SMTP settings from the application's configuration file
    to send emails via Python's standard `smtplib` library. It supports
    both TLS and SSL encryption for SMTP connections. It inherits common
    service functionalities (like settings and logger access) from `BaseService`.
    """

    def send(self, email_to: str, subject: str, html_content: str) -> bool:
        """
        Sends an email using the application's configured SMTP settings.

        Args:
            email_to (str): The recipient's email address.
            subject (str): The subject of the email.
            html_content (str): The HTML content of the email.

        Returns:
            bool: True if the email was sent successfully, False otherwise.

        Raises:
            ValueError: If essential SMTP settings (from_email, from_name, host, port)
                        are not configured in the application settings.
        """
        # Validate that essential sender information is configured
        if not self.settings.SMTP_FROM_EMAIL or not self.settings.SMTP_FROM_NAME:
            self.logger.error("SMTP_FROM_EMAIL and SMTP_FROM_NAME must be set for sending emails.")
            raise ValueError("SMTP_FROM_EMAIL and SMTP_FROM_NAME must be set in the config file.")

        # Create the email message object
        email_msg = Message(
            subject=subject,
            html=html_content,
            mail_from_name=self.settings.SMTP_FROM_NAME,
            mail_from_address=self.settings.SMTP_FROM_EMAIL,
        )

        # Validate that essential SMTP server settings are configured
        if not self.settings.SMTP_HOST or not self.settings.SMTP_PORT:
            self.logger.error("SMTP_HOST and SMTP_PORT must be set for sending emails.")
            raise ValueError("SMTP_HOST and SMTP_PORT must be set in the config file.")

        # Prepare SMTP options from application settings
        smtp_options = EmailOptions(
            host=self.settings.SMTP_HOST,
            port=int(self.settings.SMTP_PORT),  # Ensure port is integer
            # Determine TLS/SSL usage based on configured strategy (case-insensitive)
            tls=(self.settings.SMTP_AUTH_STRATEGY.upper() == "TLS" if self.settings.SMTP_AUTH_STRATEGY else False),
            ssl=(self.settings.SMTP_AUTH_STRATEGY.upper() == "SSL" if self.settings.SMTP_AUTH_STRATEGY else False),
        )

        # Add SMTP authentication credentials if configured
        if self.settings.SMTP_USER:
            smtp_options.username = self.settings.SMTP_USER
        if self.settings.SMTP_PASSWORD:  # Password should be accessed securely
            smtp_options.password = self.settings.SMTP_PASSWORD

        # Send the message using the Message object's send method
        smtp_response = email_msg.send(to_address=email_to, smtp_config=smtp_options)

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
    profile's server/credentials/From. When it has none, this transparently falls back to
    `DefaultEmailSender` (the global SMTP settings), so behaviour is unchanged until a
    workspace activates a profile.
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
            # No active profile — behave exactly like the global sender.
            return DefaultEmailSender().send(email_to, subject, html_content)

        from_email = profile["from_email"] or self.settings.SMTP_FROM_EMAIL
        from_name = profile["from_name"] or self.settings.SMTP_FROM_NAME or "Marvin"
        if not from_email:
            self.logger.error(f"Active SMTP profile '{profile['name']}' has no From address and no global SMTP_FROM_EMAIL fallback.")
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
