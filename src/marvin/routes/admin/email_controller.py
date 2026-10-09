"""
This module defines the FastAPI controller for administrative email functionalities
within the Marvin application.

It provides endpoints for administrators to check the email (SMTP) configuration
status and to send a test email to verify if the setup is working correctly.
"""

from typing import Annotated  # For type hinting with FastAPI Header

from fastapi import APIRouter, Header, HTTPException, status  # FastAPI components for routing and header parameters
from pydantic import UUID4, BaseModel, EmailStr

# Marvin base controller and schema imports
from marvin.routes._base import BaseAdminController, controller  # Base controller for admin routes
from marvin.schemas.admin.email import (
    EmailReady,
    EmailSuccess,
    EmailTest,
)  # Pydantic schemas for email responses/requests
from marvin.schemas.group.email_template import (
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateSummary,
    EmailTemplateUpdate,
)
from marvin.services.email import EmailService  # Service for handling email operations
from marvin.services.email.email_senders import email_ready
from marvin.services.event_bus_service.event_types import EventEmailTemplateData, EventOperation, EventTypes

# APIRouter for admin "email" section, prefixed with /email
# All routes in this controller will be under /admin/email.
router = APIRouter(prefix="/email")


class TestEmailRequest(BaseModel):
    """Request to send a test email."""

    recipient_email: EmailStr


@controller(router)
class AdminEmailController(BaseAdminController):
    """
    Controller for administrative email operations.

    Provides endpoints to check SMTP configuration status, send test emails,
    and manage system-wide email templates.
    Requires administrator privileges for all operations.
    """

    @property
    def repo(self):
        """Repository for system email templates (group_id = NULL)."""
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.repos.repository_generic import RepositoryGeneric
        from marvin.schemas.group.email_template import EmailTemplateRead

        return RepositoryGeneric(self.repos.session, "id", EmailTemplateModel, EmailTemplateRead)

    @router.get("", response_model=EmailReady, summary="Check Email Configuration Status")
    async def check_email_config(self) -> EmailReady:
        """
        Checks and returns the status of the SMTP email configuration.

        Indicates whether the SMTP settings are enabled in the application configuration,
        which is a prerequisite for sending emails. Accessible only by administrators.

        Returns:
            EmailReady: A Pydantic model indicating if the email (SMTP) service is ready.
        """
        # Returns a simple boolean status based on application settings
        return EmailReady(ready=email_ready())

    @router.post("", response_model=EmailSuccess, summary="Send a Test Email")
    async def send_test_email(
        self,
        data: EmailTest,  # Pydantic model containing the recipient email address
        accept_language: Annotated[str | None, Header()] = None,  # Optional language preference from header
    ) -> EmailSuccess:
        """
        Sends a test email to the email address specified in the request body.

        This endpoint is used to verify that the SMTP email service is correctly
        configured and operational. The email content might be localized based
        on the `accept_language` header. Accessible only by administrators.

        Args:
            data (EmailTest): Request body containing the `email` field for the recipient.
            accept_language (str | None, optional): The preferred language for the
                email content, extracted from the 'Accept-Language' header.
                Defaults to None (system default language).

        Returns:
            EmailSuccess: A Pydantic model indicating whether the email was sent
                          successfully and any error message if it failed.
        """
        # Initialize the email service, potentially with locale for localized templates
        email_service = EmailService(locale=accept_language)
        email_sent_successfully = False  # Default status
        error_message: str | None = None  # Default error message

        try:
            # Attempt to send the test email using the email service
            email_sent_successfully = email_service.send_test_email(data.email)
            if not email_sent_successfully:  # If service returns False without exception
                error_message = "Email service reported failure without raising an exception."
        except Exception as e:
            # Log the exception and capture the error message
            self.logger.error(f"Failed to send test email to {data.email}: {e}")
            error_message = str(e)

        return EmailSuccess(success=email_sent_successfully, error=error_message)

    # Email Template Management Endpoints

    @router.get("/templates", response_model=list[EmailTemplateSummary], summary="List System Email Templates")
    def list_templates(self) -> list[EmailTemplateSummary]:
        """
        List all system-wide email templates.

        Returns templates where group_id is NULL (system templates).

        Returns:
            List of system email template summaries
        """
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        # System templates only: group_id IS NULL. (The generic repo's get_all() returns every
        # template, so workspace/custom ones would otherwise show up mislabelled as "System".)
        templates = self.repos.session.query(EmailTemplateModel).filter(EmailTemplateModel.group_id.is_(None)).all()
        return [EmailTemplateSummary.model_validate(t) for t in templates]

    @router.get("/templates/{template_id}", response_model=EmailTemplateRead, summary="Get System Email Template")
    def get_template(self, template_id: UUID4) -> EmailTemplateRead:
        """
        Get a specific system email template by ID.

        Args:
            template_id: Template ID

        Returns:
            Email template details
        """
        template = self.repo.get_one(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email template not found: {template_id}",
            )

        return EmailTemplateRead.model_validate(template)

    @router.post("/templates", response_model=EmailTemplateRead, status_code=status.HTTP_201_CREATED, summary="Create System Email Template")
    def create_template(self, data: EmailTemplateCreate) -> EmailTemplateRead:
        """
        Create a new system-wide email template.

        Args:
            data: Template data

        Returns:
            Created email template
        """
        # Ensure group_id is None for system templates
        create_data = data.model_dump()
        create_data["group_id"] = None

        template = self.repo.create(create_data)

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=None,
            event_type=EventTypes.email_template_created,
            document_data=EventEmailTemplateData(
                operation=EventOperation.create,
                template_id=str(template.id),
                template_type=template.template_type,
                system_template=True,
            ),
            message=f"System email template created: {template.name} ({template.template_type})",
            user_id=self.user.id if self.user else None,
        )

        return EmailTemplateRead.model_validate(template)

    @router.patch("/templates/{template_id}", response_model=EmailTemplateRead, summary="Update System Email Template")
    def update_template(self, template_id: UUID4, data: EmailTemplateUpdate) -> EmailTemplateRead:
        """
        Update a system email template.

        Args:
            template_id: Template ID
            data: Updated template data

        Returns:
            Updated email template
        """
        template = self.repo.get_one(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email template not found: {template_id}",
            )

        update_data = data.model_dump(exclude_unset=True)
        updated_template = self.repo.update(template_id, update_data)

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=None,
            event_type=EventTypes.email_template_updated,
            document_data=EventEmailTemplateData(
                operation=EventOperation.update,
                template_id=str(template_id),
                template_type=updated_template.template_type,
                system_template=True,
            ),
            message=f"System email template updated: {updated_template.name}",
            user_id=self.user.id if self.user else None,
        )

        return EmailTemplateRead.model_validate(updated_template)

    @router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete System Email Template")
    def delete_template(self, template_id: UUID4) -> None:
        """
        Delete a system email template.

        Args:
            template_id: Template ID
        """
        template = self.repo.get_one(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email template not found: {template_id}",
            )

        template_name = template.name
        template_type = template.template_type

        self.repo.delete(template_id)

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=None,
            event_type=EventTypes.email_template_deleted,
            document_data=EventEmailTemplateData(
                operation=EventOperation.delete,
                template_id=str(template_id),
                template_type=template_type,
                system_template=True,
            ),
            message=f"System email template deleted: {template_name}",
            user_id=self.user.id if self.user else None,
        )

    @router.post("/templates/{template_id}/test", status_code=status.HTTP_200_OK, summary="Send Test Email with Template")
    def send_template_test_email(self, template_id: UUID4, data: TestEmailRequest) -> dict:
        """
        Send a test email using the specified system template.

        Args:
            template_id: Template ID
            data: Test email request with recipient address

        Returns:
            Success message
        """
        template = self.repo.get_one(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email template not found: {template_id}",
            )

        # Send test email
        email_service = EmailService()

        # Build test variables
        test_variables = {
            "workspace_name": "Test Workspace",
            "button_link": str(self.settings.BASE_URL),
            "invitation_url": str(self.settings.BASE_URL),
        }

        try:
            success = email_service._send_db_template(data.recipient_email, template, test_variables)

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to send test email. Check SMTP configuration.",
                )

            return {"message": f"Test email sent to {data.recipient_email}"}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error sending test email: {str(e)}",
            ) from e
