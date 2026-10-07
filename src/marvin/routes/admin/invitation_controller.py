"""
This module defines the FastAPI controller for managing group invitations
within the Marvin application.

It provides endpoints for creating and listing group invitation tokens,
and for sending email invitations containing these tokens.
"""

from typing import Annotated  # For type hinting with FastAPI Header

from fastapi import APIRouter, Header, HTTPException, status  # Core FastAPI components

# Marvin core, schemas, services, and base controller
from marvin.core.security import url_safe_token  # For generating secure tokens
from marvin.routes._base import BaseUserController, controller  # Base controller for user-authenticated routes
from marvin.schemas.group.invite_token import (  # Pydantic schemas for invite tokens
    EmailInitationResponse,
    EmailInvitation,
    InviteTokenCreate,
    InviteTokenRead,
    # InviteTokenUpdate, # InviteTokenUpdate was imported but not used
)
from marvin.schemas.response.pagination import PaginationQuery  # For pagination parameters
from marvin.services.email.email_service import EmailService  # Service for sending emails

# APIRouter for group invitations, prefixed accordingly.
# All routes here will be under /groups/invitations based on router prefix in main app and this.
router = APIRouter(prefix="/groups/invitations")


@controller(router)
class GroupInvitationsController(BaseUserController):
    """
    Controller for managing group invitation tokens and sending email invitations.

    Provides functionality to create and list invitation tokens for groups,
    and to email these invitations to prospective users. Access is restricted
    based on user permissions (e.g., `can_invite`).
    """

    @router.get("", response_model=list[InviteTokenRead], summary="List All Invite Tokens for User's Group")
    def get_invite_tokens(self) -> list[InviteTokenRead]:
        """
        Retrieves all active invitation tokens for the current user's group.

        Note: This endpoint currently fetches all tokens (per_page=-1) for the group
        associated with the authenticated user via `self.repos.group_invite_tokens`
        which is already group-scoped by `BaseUserController`.

        Returns:
            list[InviteTokenRead]: A list of Pydantic schemas representing the invite tokens.
        """
        # `self.repos.group_invite_tokens` is automatically scoped to the user's group
        # by `BaseUserController`'s `repos` property.
        # Fetch all items by setting per_page to -1 (or a very large number if -1 isn't supported by pagination).
        all_tokens_page = self.repos.group_invite_tokens.page_all(
            PaginationQuery(page=1, per_page=-1)  # Fetches all tokens for the group
        )
        # The print statement is for debugging and should ideally be removed in production.
        # print(all_tokens_page.items) # Original print statement
        self.logger.debug(f"Retrieved {len(all_tokens_page.items)} invite tokens for group ID {self.group_id}")
        return all_tokens_page.items

    @router.post("", response_model=InviteTokenRead, status_code=status.HTTP_201_CREATED, summary="Create an Invite Token")
    def create_invite_token(self, token_data: InviteTokenCreate) -> InviteTokenRead:  # Renamed `token` to `token_data`
        """
        Creates a new invitation token for a group.

        The user must have `can_invite` permission. If the user is not an admin,
        they can only create tokens for their own group. Admins can specify a
        `group_id` to create a token for any group. If `group_id` is not provided
        in the request, it defaults to the current user's group.

        Args:
            token_data (InviteTokenCreate): Pydantic schema containing the data for the new token,
                                         such as `uses_left` and optionally `group_id`.

        Returns:
            InviteTokenRead: The Pydantic schema of the newly created invitation token.

        Raises:
            HTTPException (403 Forbidden): If the user lacks permission to create tokens
                                         or to create tokens for the specified group.
        """
        # Check if the user has permission to invite
        if not self.user.can_invite:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to create invite tokens.",
            )

        # Determine the target group_id: use provided or default to user's current group
        target_group_id = token_data.group_id or self.group_id

        # Non-admins can only create tokens for their own group
        if not self.user.admin and (target_group_id != self.group_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can create invite tokens for groups other than their own.",
            )

        # Prepare the final token data for creation, generating a secure token string
        # Note: The input `token_data` (InviteTokenCreate) has `uses`, but the model uses `uses_left`.
        # Assuming `token_data.uses` is meant for `uses_left`.
        final_token_payload = InviteTokenCreate(
            uses_left=token_data.uses_left,  # uses_left from input schema
            group_id=target_group_id,
            token=url_safe_token(),  # Generate a new secure token string
        )

        # Create the token using the group_invite_tokens repository
        created_token = self.repos.group_invite_tokens.create(final_token_payload)
        self.logger.info(f"Invite token created by user {self.user.username} for group {target_group_id}")
        return created_token

    @router.post("/email", response_model=EmailInitationResponse, summary="Send Email Invitation")
    def email_invitation(
        self,
        invite_data: EmailInvitation,  # Renamed `invite` to `invite_data`
        accept_language: Annotated[str | None, Header()] = None,  # Optional language preference
    ) -> EmailInitationResponse:
        """
        Sends an email invitation containing a group invite token.

        The email is sent to the specified address with a registration link
        that includes the provided token. The email content may be localized.

        Args:
            invite_data (EmailInvitation): Pydantic schema containing the recipient `email`
                                           and the `token` string to include in the invitation.
            accept_language (str | None, optional): The preferred language for the email,
                                                    extracted from the 'Accept-Language' header.
                                                    Defaults to None (system default language).

        Returns:
            EmailInitationResponse: A Pydantic model indicating whether the email was
                                    sent successfully and any error message if it failed.
        """
        email_service = EmailService(locale=accept_language)  # Initialize email service with locale

        # Construct the full registration URL including the token
        registration_url = f"{self.settings.BASE_URL}/register?token={invite_data.token}"

        email_sent_successfully = False  # Default status
        error_message: str | None = None  # Default error message

        try:
            # Attempt to send the invitation email
            email_sent_successfully = email_service.send_invitation(recipient_address=invite_data.email, invitation_url=registration_url)
            if email_sent_successfully:
                self.logger.info(f"Invitation email sent to {invite_data.email}")
            else:
                # If service returns False without an exception
                error_message = "Email service reported failure to send invitation without raising an exception."
                self.logger.warning(f"Failed to send invitation email to {invite_data.email} (service returned false).")

        except Exception as e:
            # Log the exception and capture the error message
            self.logger.error(f"Error sending invitation email to {invite_data.email}: {e}")
            error_message = str(e)

        return EmailInitationResponse(success=email_sent_successfully, error=error_message)
