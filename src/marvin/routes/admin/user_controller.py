"""
This module defines the FastAPI controller for administrative management of users
within the Marvin application.

It provides RESTful endpoints for administrators to perform CRUD operations on users,
unlock user accounts, and generate password reset tokens on behalf of users.
"""

from functools import cached_property  # For lazy-loading properties

from fastapi import APIRouter, Depends, HTTPException, status  # Core FastAPI components & status codes
from pydantic import UUID4  # For UUID type validation

# Marvin core, schemas, services, and base controller/mixin
from marvin.core import security  # For password hashing
from marvin.db.models.users.roles import PlatformRole
from marvin.routes._base import BaseAdminController, controller  # Base admin controller
from marvin.routes._base.mixins import HttpRepo  # Mixin for standardized CRUD HTTP responses
from marvin.schemas.response.pagination import PaginationQuery  # Pagination query parameters
from marvin.schemas.response.responses import ErrorResponse  # Standardized error response
from marvin.schemas.user import (
    UserAdminUpdate,
    UserCreate,
    UserPagination,
    UserRead,
    UserUpdate,
)
from marvin.schemas.user.auth import UnlockResults  # Schema for unlock operation result
from marvin.schemas.user.password import ForgotPassword, PasswordResetToken  # Schemas for password reset
from marvin.services.user.password_reset_service import PasswordResetService  # Service for password reset logic
from marvin.services.user.user_service import UserService  # Service for user-related business logic

# APIRouter for admin user management, prefixed with /users
# All routes here will be under /admin/users.
router = APIRouter(prefix="/users")


@controller(router)
class AdminUserManagementRoutes(BaseAdminController):
    """
    Controller for administrative CRUD operations on users.

    Provides endpoints for creating, retrieving, updating, and deleting users,
    as well as unlocking accounts and generating password reset tokens.
    All operations require administrator privileges.
    """

    @cached_property
    def repo(self):  # Type hint could be RepositoryUsers if imported
        """
        Provides a cached instance of the users repository (`self.repos.users`).
        The repository is used for direct data access for user entities.
        """
        return self.repos.users

    # =======================================================================
    # CRUD Operations and User Management
    # =======================================================================

    @property
    def mixins(self) -> HttpRepo[UserCreate, UserRead, UserUpdate]:  # Assuming UserUpdate for HttpRepo Update schema
        """
        Provides an instance of `HttpRepo` configured for User CRUD operations.

        This property initializes `HttpRepo` with the user repository, logger,
        and registered exception messages, streamlining common CRUD HTTP responses
        and error handling. `UserUpdate` is assumed as the schema for update operations.
        """
        # HttpRepo[CreateSchema, ReadSchema, UpdateSchema]
        return HttpRepo[UserCreate, UserRead, UserUpdate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=UserPagination, summary="Get All Users (Paginated)")
    def get_all(self, q: PaginationQuery = Depends(PaginationQuery)) -> UserPagination:
        """
        Retrieves a paginated list of all users.

        Accessible only by administrators. Supports standard pagination query parameters.

        Args:
            q (PaginationQuery): FastAPI dependency for pagination parameters.

        Returns:
            UserPagination: Paginated list of users.
        """
        paginated_response = self.repo.page_all(
            pagination=q,
            override_schema=UserRead,  # Ensure response items are UserRead schemas
        )
        # Set HATEOAS pagination guide URLs
        paginated_response.set_pagination_guides(router.url_path_for("get_all"), q.model_dump())
        return paginated_response

    @router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Create a New User")
    def create_one(self, data: UserCreate) -> UserRead:
        """
        Creates a new user.

        The user's password will be hashed before being stored.
        Accessible only by administrators.

        Args:
            data (UserCreate): Pydantic schema containing the data for the new user,
                               including a plaintext password.

        Returns:
            UserRead: The Pydantic schema of the newly created user.
        """
        # Hash the password before passing data to the repository/mixin
        data.password = security.hash_password(data.password)
        return self.mixins.create_one(data)

    @router.post("/unlock", response_model=UnlockResults, summary="Unlock User Accounts")
    def unlock_users(self, force: bool = False) -> UnlockResults:
        """
        Unlocks user accounts that were locked due to excessive failed login attempts.

        Accessible only by administrators.

        Args:
            force (bool, optional): If True, unlocks all users regardless of their
                                    current lockout status or time. Defaults to False.
                                    (Behavior depends on `UserService.reset_locked_users`)

        Returns:
            UnlockResults: A Pydantic model indicating the number of users unlocked.
        """
        user_service = UserService(self.repos)
        unlocked_count = user_service.reset_locked_users(force=force)
        return UnlockResults(unlocked=unlocked_count)

    @router.get("/{item_id}", response_model=UserRead, summary="Get a Specific User by ID")
    def get_one(self, item_id: UUID4) -> UserRead:
        """
        Retrieves a specific user by their unique ID.

        Accessible only by administrators.

        Args:
            item_id (UUID4): The unique identifier of the user to retrieve.

        Returns:
            UserRead: The Pydantic schema of the requested user.
        """
        return self.mixins.get_one(item_id)

    @router.put("/{item_id}", response_model=UserRead, summary="Update a User")
    def update_one(self, item_id: UUID4, data: UserAdminUpdate) -> UserRead:
        """
        Updates an existing user's details. Only the fields sent are changed.

        Super admins cannot demote themselves using this endpoint, so the platform can't be left
        without one by accident. Accessible only by administrators.

        Args:
            item_id (UUID4): The ID of the user to update.
            data (UserAdminUpdate): The fields to change.

        Returns:
            UserRead: The Pydantic schema of the updated user.

        Raises:
            HTTPException (403 Forbidden): If a super admin attempts to demote themselves.
        """
        is_self_demotion = (
            self.user.id == item_id
            and self.user.platform_role == PlatformRole.SUPER_ADMIN
            and data.platform_role is not None
            and data.platform_role != PlatformRole.SUPER_ADMIN
        )
        if is_self_demotion:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ErrorResponse.respond("Administrators cannot demote themselves."),
            )
        return self.mixins.update_one(item_id=item_id, data=data)

    @router.delete("/{item_id}", summary="Delete a User")
    def delete_one(self, item_id: UUID4) -> dict:
        """
        Deletes a user by their unique ID.

        Accessible only by administrators. Note: Self-deletion checks might be needed
        or handled by service/repository layer depending on policy.

        Args:
            item_id (UUID4): The ID of the user to delete.

        Returns:
            dict: Status message on successful deletion.
        """
        # TODO: Consider adding a check to prevent an admin from deleting themselves,
        # or ensure this is handled at a lower level if it's a requirement.
        # if self.user.id == item_id:
        #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators cannot delete themselves.")

        self.mixins.delete_one(item_id)
        return {"status": "ok", "message": "User deleted successfully"}

    @router.post(
        "/password-reset-token",
        response_model=PasswordResetToken,
        status_code=status.HTTP_201_CREATED,
        summary="Generate Password Reset Token for a User",
    )
    def generate_token(self, email_data: ForgotPassword) -> PasswordResetToken:  # Renamed `email` to `email_data` for clarity
        """
        Generates a password reset token for a user specified by email.

        This is an authenticated endpoint for administrators to initiate password
        resets on behalf of users. The generated token can then be communicated
        to the user.

        Args:
            email_data (ForgotPassword): Pydantic schema containing the `email` of the user
                                         for whom to generate the reset token.

        Returns:
            PasswordResetToken: A Pydantic model containing the generated token.

        Raises:
            HTTPException (500 Internal Server Error): If token generation fails.
                                                       (Consider 404 if user email not found).
        """
        password_reset_service = PasswordResetService(self.session)  # Use self.session from BaseController
        # Attempt to generate the reset token
        token_model_instance = password_reset_service.generate_reset_token(email_data.email)

        if not token_model_instance:
            # This could be because the user email doesn't exist, or another issue.
            # A 404 might be more appropriate if user not found.
            # For now, sticking to 500 as per original logic for "error while generating".
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # Or 404 if user not found
                detail=ErrorResponse.respond(message=f"Error generating password reset token for {email_data.email}."),
            )
        return PasswordResetToken(token=token_model_instance.token)
