"""
This module defines the FastAPI controller for managing group invitations
within the Marvin application.

It provides endpoints for creating and listing group invitation tokens,
and for sending email invitations containing these tokens.
"""

import contextlib
import uuid
from typing import Annotated  # For type hinting with FastAPI Header

from fastapi import APIRouter, Depends, Header, HTTPException, status  # Core FastAPI components
from fastapi.encoders import jsonable_encoder

# Marvin core, schemas, services, and base controller
from marvin.core.security import url_safe_token  # For generating secure tokens
from marvin.routes._base import BaseUserController, controller  # Base controller for user-authenticated routes
from marvin.schemas.group.invite_token import (  # Pydantic schemas for invite tokens
    EmailInitationResponse,
    EmailInvitation,
    InviteTokenCreate,
    InviteTokenPagination,  # For paginated responses
    InviteTokenSave,
    InviteTokenSummary,
    # InviteTokenUpdate, # InviteTokenUpdate was imported but not used
)
from marvin.schemas.mapper import cast  # Utility for casting between schema types
from marvin.schemas.response.pagination import PaginationQuery  # For pagination parameters
from marvin.services.email.email_service import EmailService
from marvin.services.event_bus_service.event_types import EventInvitationData, EventOperation, EventTypes

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

    @router.get("", response_model=InviteTokenPagination, summary="List Group Invite Tokens")
    def get_all(self, q: PaginationQuery = Depends(PaginationQuery)) -> InviteTokenPagination:
        """
        Retrieves all active invitation tokens for the current user's group.

        Note: This endpoint currently fetches all tokens (per_page=-1) for the group
        associated with the authenticated user via `self.repos.group_invite_tokens`
        which is already group-scoped by `BaseUserController`.

        Returns:
            InviteTokenPagination: Paginated list of invite token summeries.
        """
        # The tokens are live: anyone holding one joins with its role, so only members who may invite
        # may see them.
        self.checks.can_manage_members(self.group_id)
        # `self.repos.group_invite_tokens` is automatically scoped to the user's group
        # by `BaseUserController`'s `repos` property.
        # Fetch all items by setting per_page to -1 (or a very large number if -1 isn't supported by pagination).
        # `self.repo` is already group-scoped.
        paginated_response = self.repos.group_invite_tokens.page_all(
            pagination=q,
            override_schema=InviteTokenSummary,  # Serialize items using InviteTokenSummary
        )
        # Set HATEOAS pagination guide URLs
        paginated_response.set_pagination_guides(router.url_path_for("get_all"), q.model_dump())
        return paginated_response

    @router.post("", response_model=InviteTokenSummary, status_code=status.HTTP_201_CREATED, summary="Create an Invite Token")
    def create_invite_token(self, token_data: InviteTokenCreate) -> InviteTokenSummary:  # Renamed `token` to `token_data`
        """
        Creates a new invitation token for a group.

        Args:
            token_data (InviteTokenCreate): Pydantic schema containing the data for the new token,
                                         such as `uses_left`.

        Returns:
            InviteTokenRead: The Pydantic schema of the newly created invitation token.

        Raises:
            HTTPException (403 Forbidden): If the user lacks permission to create tokens
                                         or to create tokens for the specified group.
        """
        # Workspace OWNER/ADMIN may invite, and never at a role above their own.
        self.checks.can_manage_members(self.group_id, granting=token_data.workspace_role)

        # Prepare the final token data for creation, generating a secure token string
        final_token_payload = InviteTokenCreate(
            uses_left=token_data.uses_left,
            workspace_role=token_data.workspace_role,  # Role from input, defaults to EDITOR
        )

        save_data = cast(final_token_payload, InviteTokenSave, token=url_safe_token(), group_id=self.group_id)
        # Create the token using the group_invite_tokens repository
        created_token = self.repos.group_invite_tokens.create(save_data)
        self.logger.info(f"Invite token created by user {self.user.username} for group {self.group_id}")

        # Emit event
        self.event_bus.dispatch(
            integration_id="invitation_management",
            group_id=self.group_id,
            event_type=EventTypes.invitation_created,
            document_data=EventInvitationData(
                operation=EventOperation.create,
                invitation_id=created_token.id,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else "",
                inviter_name=self.user.full_name or self.user.username or "",
                uses_left=created_token.uses_left,
            ),
            message=f"Invitation token created with {created_token.uses_left} uses",
            entity_id=created_token.id,
            entity_type="invitation",
        )

        # Cast to InviteTokenSummary for proper JSON serialization
        return cast(created_token, InviteTokenSummary)

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
        self.checks.can_manage_members(self.group_id)

        if not self.settings.SMTP_ENABLED:
            # If SMTP is not enabled, raise an error
            self.logger.error("SMTP service is not enabled, cannot send email invitations.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email service is currently unavailable. Please try again later."
            )

        token = self.repos.group_invite_tokens.get_one(invite_data.token, "token")  # Fetch the token by its string value

        if not token or token.uses_left <= 0:
            # If the token does not exist or has no uses left, raise an error
            self.logger.error(f"Invalid or expired invitation token for {invite_data.email}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The provided invitation token is invalid or has expired.")

        # Construct the full registration URL including the token
        registration_url = f"{self.settings.BASE_URL}/register?token={invite_data.token}"
        workspace_name = self.group.name if self.group else ""
        inviter_name = self.user.full_name or self.user.username or ""
        # What the event says — and the email's template variables besides the link. Never the token or the link:
        # every member reads an event's payload, and webhooks, integrations and the Event Log all get it.
        invitation = EventInvitationData(
            operation=EventOperation.info,
            invitation_id=token.id,
            workspace_id=self.group_id,
            workspace_name=workspace_name,
            inviter_name=inviter_name,
            invitee_email=invite_data.email,
            uses_left=token.uses_left,
        )

        email_sent_successfully = False
        error_message: str | None = None

        try:
            # Sent from here, with the link: the template is Marvin's invitation email or the workspace's replacement.
            email_sent_successfully = EmailService(locale=accept_language, group_id=str(self.group_id)).send_invitation(
                recipient_address=invite_data.email,
                invitation_url=registration_url,
                group_id=str(self.group_id),
                workspace_name=workspace_name,
                inviter_name=inviter_name,
                variables={
                    **jsonable_encoder(invitation, exclude_none=True, by_alias=False),
                    "event_type": EventTypes.invitation_sent.name,
                    "workspace_id": str(self.group_id),
                },
            )
            if not email_sent_successfully:
                error_message = "The invitation email could not be sent."
        except Exception as e:
            self.logger.error(f"Error sending the invitation email to {invite_data.email}: {e}")
            error_message = str(e)

        if email_sent_successfully:
            self.event_bus.dispatch(
                integration_id="invitation_management",
                group_id=self.group_id,
                event_type=EventTypes.invitation_sent,
                document_data=invitation,
                message=f"Invitation sent to {invite_data.email}",
                entity_id=token.id,
                entity_type="invitation",
            )
            self.logger.info(f"Invitation email sent to {invite_data.email}")

        return EmailInitationResponse(success=email_sent_successfully, error=error_message)

    @router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an Invite Token")
    def delete_invite_token(self, token_id: str) -> None:
        """
        Deletes (revokes) an invitation token.

        This allows administrators to manually revoke invitation tokens before they
        are exhausted or expire. The token_id can be either the UUID or the token string.

        Args:
            token_id: The UUID or token string of the invitation to delete

        Raises:
            HTTPException (404 Not Found): If the token does not exist
            HTTPException (403 Forbidden): If the user lacks permission to delete tokens
        """
        self.checks.can_manage_members(self.group_id)

        # Try to find the token by ID first (what the members page sends), then by token string. The repository's
        # primary key is the token string, so the id lookup names its key.
        token = None
        with contextlib.suppress(ValueError):
            token = self.repos.group_invite_tokens.get_one(uuid.UUID(token_id), "id")
        if not token:
            # Try by token string
            token = self.repos.group_invite_tokens.get_one(token_id, "token")

        if not token:
            self.logger.warning(f"Attempt to delete non-existent token: {token_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation token not found")

        # Emit event before deletion
        self.event_bus.dispatch(
            integration_id="invitation_management",
            group_id=self.group_id,
            event_type=EventTypes.invitation_revoked,
            document_data=EventInvitationData(
                operation=EventOperation.delete,
                invitation_id=token.id,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else "",
                inviter_name=self.user.full_name or self.user.username or "",
                uses_left=token.uses_left,
            ),
            message="Invitation token revoked",
            entity_id=token.id,
            entity_type="invitation",
        )

        # Delete the token
        self.repos.group_invite_tokens.delete(token.token, match_key="token")
        self.logger.info(f"Invite token {token.id} deleted by user {self.user.username}")
