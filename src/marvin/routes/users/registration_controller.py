"""
This module defines the FastAPI controller for user registration within the
Marvin application.

It provides a public endpoint for new users to register, subject to application
settings (e.g., whether signups are globally allowed or if a valid group
invitation token is required).
"""

from fastapi import APIRouter, Depends, HTTPException, status  # Core FastAPI components

# Marvin core, schemas, services, and base controller
from marvin.core.config import get_app_settings  # Access application settings
from marvin.repos.all_repositories import get_repositories  # For creating repositories instance for service
from marvin.routes._base import BasePublicController, controller  # Base public controller
from marvin.schemas.response import ErrorResponse  # Standardized error response
from marvin.schemas.user.registration import UserRegistrationCreate  # Pydantic schema for registration data
from marvin.schemas.user.user import UserRead  # Pydantic schema for user response
from marvin.services.event_bus_service.event_bus_service import EventBusService  # Event bus for dispatching events
from marvin.services.event_bus_service.event_types import EventInvitationData, EventOperation, EventTypes, EventUserSignupData  # Event types
from marvin.services.user.registration_service import RegistrationService  # Service for registration logic

# APIRouter for user registration. This is a public endpoint.
# All routes here will be under /register.
router = APIRouter(prefix="/register")


@controller(router)  # Registers this class-based view with the defined router
class RegistrationController(BasePublicController):
    """
    Controller for handling new user registrations.

    Provides a public endpoint for users to create new accounts. Registration
    behavior is governed by application settings, such as `ALLOW_SIGNUP` and
    the requirement for group invitation tokens.
    """

    # Dependency injection for the EventBusService, available to methods in this controller
    event_bus: EventBusService = Depends(EventBusService.as_dependency)

    @router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Register New User")
    def register_new_user(self, data: UserRegistrationCreate) -> UserRead:
        """
        Registers a new user in the application.

        Registration is allowed under two conditions:
        1. If global signups are enabled (`settings.ALLOW_SIGNUP` is True).
        2. If a valid `group_token` is provided in the registration data, allowing
           registration even if global signups are disabled.

        Upon successful registration, a `user_signup` event is dispatched to the event bus.

        Args:
            data (UserRegistrationCreate): Pydantic schema containing the new user's
                                           registration details (e.g., username, email,
                                           password, optional group_token).

        Returns:
            UserRead: The Pydantic schema of the newly created user.

        Raises:
            HTTPException (403 Forbidden): If user registration is disabled and no valid
                                         group token is provided.
            HTTPException (various from service): If registration fails due to other reasons
                                                  (e.g., username/email already exists,
                                                  invalid group token), handled by the
                                                  `RegistrationService`.
        """
        settings = get_app_settings()  # Get current application settings

        # Check if registration is allowed based on settings and provided group token
        can_register_globally = settings.ALLOW_SIGNUP
        has_group_token = data.group_token is not None and data.group_token.strip() != ""

        if not can_register_globally and not has_group_token:
            # If global signups are off AND no group token is provided, forbid registration.
            self.logger.warning(f"User registration attempt denied: Signups disabled and no group token provided. Email: {data.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ErrorResponse.respond("User registration is currently disabled."),
            )

        # Initialize the registration service
        # Note: Repositories are created here with group_id=None, implying the service
        # handles any group-specific logic internally (e.g., validating token against a group).
        registration_service = RegistrationService(
            logger=self.logger,  # Pass logger from base controller
            repos=get_repositories(self.session, group_id=None),  # Provide non-scoped repos
        )

        # The invitation as it stands before this registration uses it — a last use deletes the token row.
        invitation = get_repositories(self.session, group_id=None).group_invite_tokens.get_one(data.group_token, "token") if has_group_token else None

        # Attempt to register the user via the service layer
        # The service will handle password hashing, token validation (if any), and user creation.
        newly_registered_user = registration_service.register_user(data)

        # Dispatch a user_signup event to the event bus
        # This allows other parts of the system to react to new user registrations.
        try:
            self.event_bus.dispatch(
                integration_id="user_registration_process",  # Identifier for this event source
                group_id=newly_registered_user.group_id,  # Associate event with the user's group
                event_type=EventTypes.user_signup,
                document_data=EventUserSignupData(username=newly_registered_user.username, email=newly_registered_user.email),
                message=f"New user registered: {newly_registered_user.username}",
                entity_id=newly_registered_user.id,
                entity_type="user",
            )
            self.logger.info(f"User signup event dispatched for user: {newly_registered_user.username}")
        except Exception as e:
            self.logger.error(f"Failed to dispatch user_signup event for {newly_registered_user.username}: {e}")

        # If the registration used an invitation token, fire invitation_accepted
        if has_group_token and newly_registered_user.group_id:
            try:
                group_repos = get_repositories(self.session, group_id=newly_registered_user.group_id)
                group = group_repos.groups.get_one(newly_registered_user.group_id)
                token_obj = group_repos.group_invite_tokens.get_one(data.group_token, "token")
                self.event_bus.dispatch(
                    integration_id="invitation_management",
                    group_id=newly_registered_user.group_id,
                    event_type=EventTypes.invitation_accepted,
                    document_data=EventInvitationData(
                        operation=EventOperation.update,
                        invitation_token=data.group_token,
                        workspace_id=newly_registered_user.group_id,
                        workspace_name=group.name if group else "",
                        invitee_email=newly_registered_user.email,
                        invitation_url=f"{settings.BASE_URL}/register?token={data.group_token}",
                        uses_left=token_obj.uses_left if token_obj else None,
                    ),
                    message=f"Invitation accepted by {newly_registered_user.username}",
                    entity_id=invitation.id if invitation else None,
                    entity_type="invitation" if invitation else None,
                )
                self.logger.info(f"Invitation accepted event dispatched for user: {newly_registered_user.username}")
            except Exception as e:
                self.logger.error(f"Failed to dispatch invitation_accepted event for {newly_registered_user.username}: {e}")

        return newly_registered_user
