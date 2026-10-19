"""
This module defines Pydantic schemas for operations related to user password
management within the Marvin application, such as initiating a password reset,
validating reset tokens, and setting a new password.
"""

from pydantic import UUID4, ConfigDict, field_validator, model_validator  # For UUID type and Pydantic model configuration

# SQLAlchemy ORM imports for loader_options method
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.interfaces import LoaderOption

# Corresponding SQLAlchemy models (used in loader_options)
from marvin.db.models.users import PasswordResetModel as PasswordResetSQLModel  # Aliased for clarity
from marvin.db.models.users import Users as UsersSQLModel  # Aliased for clarity
from marvin.schemas._marvin import _MarvinModel  # Base Pydantic model

from .user import PrivateUser  # User schema for embedding user details


class ForgotPassword(_MarvinModel):
    """
    Schema for the "forgot password" request.
    Requires the user's email address to initiate the password reset process.
    """

    email: str
    """The email address of the user requesting a password reset."""


class PasswordResetToken(ForgotPassword):  # Extends ForgotPassword, so it also includes 'email'
    """
    Schema representing a password reset token along with the associated email.
    This might be used when returning token information or in contexts where
    both email and token are relevant.
    """

    token: str
    """The generated password reset token string."""
    # Inherits `email` from ForgotPassword.


class ValidateResetToken(_MarvinModel):
    """
    Schema for validating a password reset token.
    Used when a user attempts to access the password reset form using a token.
    """

    token: str
    """The password reset token string to validate."""


class ResetPassword(ValidateResetToken):  # Extends ValidateResetToken, so it also includes 'token'
    """
    Schema for the actual password reset operation: the reset token (it names the user) and the new password with
    confirmation.
    """

    email: str | None = None
    """Not checked (the token names the user); accepted so older clients that send it keep working."""
    password: str
    """The new password to set for the user."""
    passwordConfirm: str  # Field name uses camelCase, consistent with alias_generator in _MarvinModel
    """Confirmation of the new password. Must match `password`."""

    @field_validator("password")
    @classmethod
    def password_long_enough(cls, value: str) -> str:
        from .password_rules import check_password_length

        return check_password_length(value)

    @model_validator(mode="after")
    def check_passwords_match(self) -> "ResetPassword":
        """Validate that password and passwordConfirm fields match."""
        if self.password != self.passwordConfirm:
            raise ValueError("Passwords do not match")
        return self


class SavePasswordResetToken(_MarvinModel):
    """
    Schema for data required to save a password reset token in the database.
    Links a user ID with a generated token.
    """

    user_id: UUID4
    """The unique identifier of the user to whom this token belongs."""
    token: str
    """The password reset token string to be saved."""


class PrivatePasswordResetToken(SavePasswordResetToken):
    """
    Schema for representing a password reset token along with associated user details
    when read from the system, potentially for administrative or internal use.
    "Private" suggests it might contain more information than publicly exposed tokens.
    """

    user: PrivateUser  # Embeds the full PrivateUser schema for the associated user.
    """The user object associated with this password reset token."""

    model_config = ConfigDict(from_attributes=True)  # Allows creating from ORM model attributes

    @classmethod
    def loader_options(cls) -> list[LoaderOption]:
        """
        Provides SQLAlchemy loader options for optimizing queries for `PrivatePasswordResetToken`.

        Configures eager loading for:
        - The `user` relationship of the `PasswordResetSQLModel`.
        - Within the loaded `user`, also eagerly loads their `group` and `tokens` relationships.
        This helps prevent N+1 query problems when fetching reset tokens with user details.

        Returns:
            list[LoaderOption]: A list of SQLAlchemy loader options.
        """
        return [
            # Eagerly load the 'user' related to the PasswordResetSQLModel
            selectinload(PasswordResetSQLModel.user).joinedload(UsersSQLModel.group),  # Then, from that user, joinedload their group
            selectinload(PasswordResetSQLModel.user).joinedload(UsersSQLModel.tokens),  # Also, from that user, joinedload their API tokens
        ]
