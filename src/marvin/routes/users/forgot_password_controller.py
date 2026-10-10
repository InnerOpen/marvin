"""
This module defines FastAPI routes for handling password reset functionalities
within the Marvin application.

It provides public endpoints for users to request a password reset email
(which includes a unique token) and to submit a new password along with
the received token to complete the reset process.
"""

from typing import Annotated  # For type hinting with FastAPI Header

from fastapi import APIRouter, Depends, Header, Request, status  # Core FastAPI components and status codes
from sqlalchemy.orm.session import Session  # SQLAlchemy session type

# Marvin specific imports
from marvin.db.db_setup import generate_session  # Database session generator
from marvin.schemas.response.responses import SuccessResponse  # For a generic success response, if applicable
from marvin.schemas.user.password import ForgotPassword, ResetPassword  # Pydantic schemas for request bodies
from marvin.services.security.login_throttle import LoginThrottle, login_client_ip
from marvin.services.user.password_reset_service import PasswordResetService  # Service for password reset logic

# Public router for password reset functionalities.
# No prefix is added here; it's expected to be included by a parent router (e.g., /auth or /users).
# Adding a tag for OpenAPI documentation.
router = APIRouter()


@router.post("/forgot-password", summary="Request Password Reset Email", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset_email(  # Renamed function for clarity
    request: Request,
    email_data: ForgotPassword,  # Request body containing the user's email
    session: Session = Depends(generate_session),  # DB session dependency
    accept_language: Annotated[str | None, Header()] = None,  # Optional language preference for the email
) -> SuccessResponse:  # Return a generic success response or a more specific one
    """
    Initiates the password reset process for a user by sending them an email.

    The email contains a unique, time-sensitive token and a link to the password
    reset page. This endpoint is public and typically called when a user has
    forgotten their password. The email content may be localized based on the
    `accept_language` header.

    Args:
        email_data (ForgotPassword): Pydantic schema containing the `email` of the user
                                     requesting the password reset.
        session (Session): SQLAlchemy database session.
        accept_language (str | None, optional): Preferred language for the reset email,
                                                extracted from the 'Accept-Language' header.
                                                Defaults to None (system default language).

    Returns:
        SuccessResponse: A confirmation response indicating that if the email address
                         is valid and associated with an account, a reset email has been sent.
                         (Actual email sending is handled by the service, which might
                         not immediately confirm success to prevent user enumeration).
    """
    # Past the hourly cap per address or per IP the email is dropped, not refused: the answer stays the same, so the
    # form can't be used to flood someone's inbox or to learn anything (services/security/login_throttle.py).
    if LoginThrottle(session).allow_reset(email_data.email, login_client_ip(request)):
        password_reset_service = PasswordResetService(session)
        # It's good practice for send_reset_email not to reveal if an email is registered or not
        # to prevent user enumeration. So, it might always return a success-like response.
        password_reset_service.send_reset_email(email_data.email, accept_language)

    # Return a generic success message to avoid disclosing whether the email exists in the system.
    return SuccessResponse(message="If an account with that email address exists, a password reset link has been sent.")


@router.post("/reset-password", summary="Reset User Password Using Token")
def complete_password_reset(  # Renamed function for clarity
    reset_data: ResetPassword,  # Request body with token and new password
    session: Session = Depends(generate_session),  # DB session dependency
) -> SuccessResponse:  # Return a generic success response
    """
    Resets a user's password using a valid password reset token.

    The user provides the token received via email and their new desired password.
    The service layer validates the token (e.g., checks for existence, expiry, usage)
    and, if valid, updates the user's password. This endpoint is public.

    Args:
        reset_data (ResetPassword): Pydantic schema containing the `token` and the
                                    new `password`.
        session (Session): SQLAlchemy database session.

    Returns:
        SuccessResponse: A confirmation that the password has been reset.

    Raises:
        HTTPException (400 Bad Request or other): If the token is invalid, expired,
                                                  or the password update fails, the service
                                                  layer is expected to raise an appropriate
                                                  HTTPException.
    """
    password_reset_service = PasswordResetService(session)
    # The service method handles token validation and password update.
    # It should raise an HTTPException if the token is invalid or password update fails.
    password_reset_service.reset_password(reset_data.token, reset_data.password, reset_data.passwordConfirm)

    return SuccessResponse(message="Your password has been successfully reset.")
