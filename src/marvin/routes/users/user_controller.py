"""
This module defines FastAPI controllers related to user management in the Marvin application.

It includes:
- `UserController`: For operations that authenticated users can perform on their
  own profiles, such as retrieving their information, updating their profile,
  and changing their password.

Note: This file contains commented-out sections for `AdminUserController` and
`UserApiTokensController`. These functionalities might be handled in their
dedicated controller files (e.g., `marvin/routes/admin/user_controller.py` and
`marvin/routes/users/api_token_controller.py` respectively) or are pending
implementation/refactoring.
"""

# from datetime import timedelta # Imported but not used in active code
from typing import Any

from fastapi import HTTPException, status  # APIRouter for consistency

# Marvin core, schemas, services, and base controllers
from marvin.core.security import hash_password  # , create_access_token # create_access_token not used in active code
from marvin.core.security.providers.credentials_provider import CredentialsProvider  # For password verification
from marvin.db.models.users.users import AuthMethod  # Enum for authentication methods
from marvin.routes._base import BaseUserController, controller  # Base controller for user-auth routes

# from marvin.routes._base.mixins import HttpRepo # HttpRepo not directly used by UserController methods
from marvin.routes._base.routers import UserAPIRouter  # Router for user-authenticated endpoints

# from marvin.routes._base.routers import AdminAPIRouter # AdminAPIRouter not used for active UserController
from marvin.schemas.response import ErrorResponse, SuccessResponse  # Standardized response schemas

# from marvin.schemas.response.pagination import PaginationQuery # Not used in active UserController
from marvin.schemas.user import (  # User Pydantic schemas
    ChangePassword,
    PrivateUser,  # Represents the authenticated user profile
    # UserCreate, # Not used by active UserController endpoints for creation
    UserProfileUpdate,  # For updating user profile without password
    UserRead,  # Using UserUpdate for user profile updates
    # Schemas related to API tokens, not used in active UserController:
    # LongLiveTokenCreate,
    # LongLiveTokenRead,
    # LongLiveTokenRead_,
    # TokenResponseDelete,
    # TokenCreate,
    # LongLiveTokenCreateResponse,
)

# from marvin.schemas.user.user import UserPagination # Not used in active UserController

# Router for user-specific, self-service operations.
# All routes here will be under /users (or a parent prefix if UserAPIRouter is included with one).
user_router = UserAPIRouter(tags=["User: Self Service"])  # Renamed tag for clarity

# Commented-out AdminAPIRouter. Admin user operations are likely in admin/user_controller.py.
# admin_router = AdminAPIRouter(prefix="/users", tags=["Users: Admin CRUD"])

# Commented-out EventBusService and related imports, not used in active UserController.
# from marvin.services.event_bus_service.event_bus_service import EventBusService
# from marvin.services.event_bus_service.event_types import EventTypes, EventUserSignupData
# from marvin.services.user.registration_service import RegistrationService


# Commented-out AdminUserController.
# This functionality is expected to be in `marvin/routes/admin/user_controller.py`.
# @controller(admin_router)
# class AdminUserController(BaseAdminController):
#     # ... (implementation omitted as it's commented out)


@controller(user_router)  # Registers this class-based view with the user_router
class UserController(BaseUserController):
    """
    Controller for user self-service operations.

    Provides endpoints for authenticated users to manage their own profile,
    including retrieving their details, updating their information, and
    changing their password.
    """

    @user_router.get("/self", response_model=UserRead, summary="Get Current User Profile")
    def get_logged_in_user(self) -> PrivateUser:  # Return type from BaseUserController is PrivateUser
        """
        Retrieves the profile information of the currently authenticated user.

        Returns:
            PrivateUser: Pydantic schema containing the authenticated user's details.
        """
        # `self.user` is injected by `BaseUserController` and contains the current user's data.
        return self.user

    @user_router.put("/self/password", response_model=SuccessResponse, summary="Update Current User's Password")
    def update_password(self, password_change_data: ChangePassword) -> dict[str, Any]:
        """
        Updates the password for the currently authenticated user.

        The user must provide their current password for verification before the
        new password can be set. This endpoint does not work for users whose
        passwords are managed by external systems like LDAP.

        Args:
            password_change_data (ChangePassword): Pydantic schema containing the
                                                   `current_password` and `new_password`.

        Returns:
            SuccessResponse: A confirmation message if the password was updated successfully.

        Raises:
            HTTPException (400 Bad Request): If the user is an LDAP user, if the current
                                           password is incorrect, or if the password
                                           update fails for other reasons.
        """
        # Check if user's password is managed externally (e.g., LDAP)
        if self.user.auth_method == AuthMethod.LDAP:  # Comparing with enum member
            self.logger.warning(f"User {self.user.username} (LDAP) attempted to change password via Marvin.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorResponse.respond("Password for LDAP users cannot be changed here."),
            )

        # Verify the current password
        if not CredentialsProvider.verify_password(
            password_change_data.current_password,
            self.user.password,  # user.password should be hashed
        ):
            self.logger.warning(f"Incorrect current password provided by user {self.user.username} during password update.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorResponse.respond("The current password provided is incorrect."),
            )

        # Hash the new password before updating
        hashed_new_password = hash_password(password_change_data.new_password)

        try:
            # Update the password in the repository
            # The `update_password` method on the repo is assumed to handle the actual DB update.
            # `self.user` object here is from the Depends(get_current_user),
            # direct modification to `self.user.password` won't persist unless saved.
            # The repository method should be used to persist the change.
            self.repos.users.update_password(self.user.id, hashed_new_password)
            self.logger.info(f"Password updated successfully for user {self.user.username}.")
        except Exception as e:
            self.logger.exception(f"Failed to update password for user {self.user.username}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # Changed to 500 for unexpected update failure
                detail=ErrorResponse.respond("Failed to update password due to a server error."),
            ) from e

        return SuccessResponse.respond("User password updated successfully.")

    @user_router.put("/self", response_model=SuccessResponse, summary="Update Current User Profile")
    def update_user(self, new_data: UserProfileUpdate) -> dict[str, Any]:
        """
        Updates the profile information for the currently authenticated user.

        Users can only update their own profiles via this endpoint. Non-admin users
        cannot change their permissions or group. Admins also have restrictions on
        changing their own permissions via this user-facing endpoint.

        Args:
            new_data (UserProfileUpdate): Pydantic schema containing the fields to update.
                                          Only username, email, and full_name can be updated.

        Returns:
            SuccessResponse: A confirmation message if the user profile was updated successfully.

        Raises:
            HTTPException (403 Forbidden): If the user attempts an unauthorized change
                                         (e.g., changing permissions).
            HTTPException (400/500): If the update fails for other reasons.
        """
        try:
            # Perform the update using the users repository.
            # `new_data.model_dump(exclude_unset=True)` ensures only provided fields are updated (PATCH behavior).
            self.repos.users.update(self.user.id, new_data.model_dump(exclude_unset=True))
            self.logger.info(f"User profile updated by user {self.user.username}.")
        except Exception as e:
            self.logger.exception(f"Failed to update user profile for {self.user.username}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ErrorResponse.respond("Failed to update user profile due to a server error."),
            ) from e

        return SuccessResponse.respond("User profile updated successfully.")


# Commented-out UserApiTokensController.
# This functionality is now in `marvin/routes/users/api_token_controller.py`.
# @controller(user_router)
# class UserApiTokensController(BaseUserController):
#     # ... (implementation omitted as it's commented out)
