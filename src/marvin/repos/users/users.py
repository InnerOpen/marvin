"""
This module defines the specialized repository for managing User entities.

It provides the `RepositoryUsers` class, which extends `GroupRepositoryGeneric`
to include user-specific operations and logic, such as password updates and
special handling for a demo mode where default user modifications are restricted.
"""

from pydantic import UUID4  # For type hinting UUIDs
from sqlalchemy import select

from marvin.core.config import get_app_settings  # Access application settings like IS_DEMO
from marvin.schemas.user.user import PrivateUser, UserCreate, UserUpdate  # Pydantic schemas for User

from ...db.models.users import Users as UsersModel  # SQLAlchemy User model, aliased for clarity
from ..repository_generic import GroupRepositoryGeneric  # Base class for group-scoped repositories

# Global application settings instance
settings = get_app_settings()


class RepositoryUsers(GroupRepositoryGeneric[PrivateUser, UsersModel]):
    """
    Specialized repository for User entities.

    This repository handles CRUD operations for Users, inheriting group-scoping
    from `GroupRepositoryGeneric`. It includes user-specific methods like
    password updates and imposes restrictions on modifying a default user
    when the application is in demo mode.
    """

    def update_password(self, user_id: UUID4, password: str) -> PrivateUser:
        """
        Updates the password for a specified user.

        In demo mode, this operation is blocked for the default user.

        Args:
            user_id (UUID4): The ID of the user whose password is to be updated.
            password (str): The new plaintext password. Hashing is expected to be
                            handled by the `entry.update_password` method or a
                            service layer before this call.

        Returns:
            PrivateUser: The Pydantic schema of the user with the updated password.

        Raises:
            HTTPException(404): If the user is not found (from `_query_one`).
        """
        # Query user directly without group_id filtering (users exist across groups)
        # Convert UUID4 to string if needed for SQLAlchemy comparison
        from uuid import UUID

        user_uuid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id

        # Debug logging
        self.logger.debug(f"Searching for user: user_id={user_id} (type={type(user_id)}), user_uuid={user_uuid} (type={type(user_uuid)})")

        entry = self.session.query(self.model).filter_by(id=user_uuid).first()

        if not entry:
            # Log all users to debug
            all_users = self.session.query(self.model).all()
            self.logger.error(f"User {user_uuid} not found. Available users: {[str(u.id) for u in all_users]}")

            from fastapi import HTTPException
            from fastapi import status as http_status

            from marvin.schemas.response import ErrorResponse

            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse.respond(f"User with ID {user_id} not found"),
            )

        if settings.IS_DEMO:
            # In demo mode, prevent password updates for the default user.
            # Assumes the schema or model has an 'is_default_user' attribute.
            user_schema_for_check = self.schema.model_validate(entry)
            if hasattr(user_schema_for_check, "is_default_user") and user_schema_for_check.is_default_user:
                self.logger.warning(f"Attempt to update password for default user in demo mode (User ID: {user_id}). Operation blocked.")
                return user_schema_for_check  # Return user data without changes

        # Call the method on the SQLAlchemy model instance to update the password
        entry.update_password(password)
        self.session.commit()
        self.session.refresh(entry)  # Refresh to get any DB-side updates

        return self.schema.model_validate(entry)

    def create(self, user_data: UserCreate | dict) -> PrivateUser:  # type: ignore
        """
        Creates a new user.

        Currently, this method directly calls the `super().create` without additional
        user-specific logic before creation, but it allows for future extensions.

        Args:
            user_data (UserCreate | dict): Data for the new user, either as a Pydantic
                                           `UserCreate` schema or a dictionary.

        Returns:
            PrivateUser: The Pydantic schema of the created user.
        """
        # The `type: ignore` might be due to differing type hints with the base class's
        # `CreateSchema` if `UserCreate` is not perfectly aligned, or a linter preference.
        # Assuming `UserCreate` is the correct schema for creation here.
        new_user = super().create(user_data)
        # `new_user` here is already a Pydantic `PrivateUser` schema due to `super().create`'s return type.
        return new_user

    def update(self, match_value: UUID4 | str, new_data: UserUpdate | dict, match_key: str | None = None) -> PrivateUser:
        """
        Updates an existing user.

        In demo mode, this operation is blocked for the default user.

        Args:
            match_value (UUID4 | str): The ID or other unique identifier of the user to update.
            new_data (UserUpdate | dict): The new data for the user, as a Pydantic
                                          `UserUpdate` schema or a dictionary.

        Returns:
            PrivateUser: The Pydantic schema of the updated user.
        """
        # Query user directly without group_id filtering (users exist across groups)
        from uuid import UUID

        user_uuid = UUID(str(match_value)) if not isinstance(match_value, UUID) else match_value
        entry = self.session.query(self.model).filter_by(id=user_uuid).first()

        if not entry:
            from fastapi import HTTPException
            from fastapi import status as http_status

            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {match_value} not found",
            )

        if settings.IS_DEMO:
            # Check if it's the default user
            user_schema_check = self.schema.model_validate(entry)
            if hasattr(user_schema_check, "is_default_user") and user_schema_check.is_default_user:
                self.logger.warning(f"Attempt to update default user in demo mode (User ID: {match_value}). Operation blocked.")
                return user_schema_check  # Return existing data without changes

        # Convert new_data to dict if it's a Pydantic model
        if hasattr(new_data, "model_dump"):
            update_data = new_data.model_dump(exclude_unset=True)
        elif isinstance(new_data, dict):
            update_data = new_data
        else:
            update_data = dict(new_data)

        # Apply updates to the model instance
        for key, value in update_data.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        self.session.commit()
        self.session.refresh(entry)

        return self.schema.model_validate(entry)

    def delete(self, value: UUID4 | str, match_key: str | None = None) -> PrivateUser:  # Changed return to PrivateUser
        """
        Deletes a user.

        In demo mode, this operation is blocked for the default user.

        Args:
            value (UUID4 | str): The ID or other unique identifier of the user to delete.
            match_key (str | None, optional): The attribute to match `value` against.
                                             Defaults to the repository's primary key.

        Returns:
            PrivateUser: The Pydantic schema of the user that was (or would have been) deleted.
                         In demo mode for the default user, returns current data without deletion.
        """
        if settings.IS_DEMO:
            # Fetch user to check if it's the default user.
            user_to_delete_check = self.get_one(value, key=match_key)
            if user_to_delete_check and hasattr(user_to_delete_check, "is_default_user") and user_to_delete_check.is_default_user:
                self.logger.warning(f"Attempt to delete default user in demo mode (User ID/match: {value}). Operation blocked.")
                return user_to_delete_check  # Return existing data without deletion

        # If not demo mode or not default user, proceed with deletion.
        # super().delete returns Schema (which is PrivateUser here).
        deleted_user_schema = super().delete(value, match_key=match_key)
        return deleted_user_schema

    def get_by_username(self, username: str) -> PrivateUser | None:
        """
        Retrieves a user by their exact username.

        Performs a case-sensitive search for the username.

        Args:
            username (str): The username to search for.

        Returns:
            PrivateUser | None: The user's Pydantic schema if found, otherwise None.
        """
        # Note: This method bypasses `_filter_builder`, so group_id scoping from
        # `GroupRepositoryGeneric` is not automatically applied here.
        # This implies usernames are unique across the system, not just within a group.
        # If usernames should be group-scoped, this query needs adjustment.
        stmt = select(UsersModel).filter(UsersModel.username == username)
        db_user = self.session.execute(stmt).scalars().one_or_none()

        if db_user is None:
            return None
        return self.schema.model_validate(db_user)

    def get_locked_users(self) -> list[PrivateUser]:
        """
        Retrieves all users whose accounts are currently locked.

        A user is considered locked if their `locked_at` field is not None.

        Returns:
            list[PrivateUser]: A list of Pydantic schemas for all locked users.
        """
        # This query also bypasses `_filter_builder` and seems to fetch system-wide
        # locked users, not scoped by the repository's `group_id`.
        # This is generally appropriate for system admin tasks.
        stmt = select(UsersModel).filter(UsersModel.locked_at.isnot(None))  # Corrected SQLAlchemy filter for NOT NULL
        db_users = self.session.execute(stmt).scalars().all()
        return [self.schema.model_validate(user_model) for user_model in db_users]
