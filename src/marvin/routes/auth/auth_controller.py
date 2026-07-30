"""
This module defines FastAPI routes for user authentication within the Marvin application.

It handles various authentication mechanisms including:
- Standard username/password login via a form, returning an access token.
- OpenID Connect (OIDC) based authentication flow (login initiation and callback).
- Token refresh for authenticated users.
- User logout by clearing the access token cookie.

Two routers are defined:
- `public_router`: For endpoints that do not require prior authentication (e.g., login, OIDC).
- `user_router`: For endpoints that require an authenticated user (e.g., refresh, logout).
"""

from datetime import timedelta

from authlib.integrations.starlette_client import OAuth  # For OIDC integration
from fastapi import APIRouter, Depends, Request, Response, status  # Core FastAPI components
from fastapi.exceptions import HTTPException  # Standard HTTP exceptions
from fastapi.responses import RedirectResponse  # For OIDC redirects
from pydantic import BaseModel  # For response model definition
from sqlalchemy.orm.session import Session  # SQLAlchemy session type
from starlette.datastructures import URLPath  # For constructing absolute URLs

# Marvin core components and utilities
from marvin.core import root_logger, security
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user  # Dependency for authenticated user
from marvin.core.exceptions import MissingClaimException, UserLockedOut  # Custom exceptions
from marvin.core.security.providers.openid_provider import OpenIDProvider  # OIDC auth provider
from marvin.core.security.security import get_auth_provider  # General auth provider factory
from marvin.db.db_setup import generate_session  # DB session generator
from marvin.routes._base.base_controllers import BasePublicController, BaseUserController
from marvin.routes._base.controller import controller
from marvin.routes._base.routers import UserAPIRouter  # Base router for authenticated user endpoints
from marvin.schemas.user import PrivateUser  # Pydantic schema for user data
from marvin.schemas.user.auth import CredentialsRequestForm  # Schema for form-based login
from marvin.services.event_bus_service.event_types import (
    EventTokenRefreshData,  # Data for token refresh event
    EventTypes,  # Enum for event types
)

# Routers for public and user-authenticated authentication endpoints
public_router = APIRouter(tags=["Authentication"])  # Tag for OpenAPI docs
user_router = UserAPIRouter(tags=["Authentication"])  # Inherits auth dependency, same tag

logger = root_logger.get_logger("auth")  # Logger for authentication events

# Duration for "remember me" functionality, though not explicitly used in cookie setting below for it.
# Standard token duration is handled by `security.create_access_token`.
remember_me_duration = timedelta(days=14)

settings = get_app_settings()
oauth: OAuth | None = None  # Initialize oauth client, will be set if OIDC is ready

# Configure OIDC client if OIDC settings are ready
if settings.OIDC_READY:  # OIDC_READY checks if all necessary OIDC settings are present
    oauth = OAuth()
    # Determine OIDC scopes
    oidc_scope = "openid email profile"  # Default scopes
    if settings.OIDC_SCOPES_OVERRIDE:
        oidc_scope = settings.OIDC_SCOPES_OVERRIDE
    elif settings.OIDC_REQUIRES_GROUP_CLAIM and settings.OIDC_GROUPS_CLAIM:
        oidc_scope += f" {settings.OIDC_GROUPS_CLAIM}"  # Add groups claim to scope if needed

    oidc_client_args = {"scope": oidc_scope.strip()}
    if settings.OIDC_TLS_CACERTFILE:  # Optional CA certificate for TLS verification
        oidc_client_args["verify"] = settings.OIDC_TLS_CACERTFILE

    # Register the OIDC client with Authlib
    oauth.register(
        name="oidc",  # Client name
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        server_metadata_url=settings.OIDC_CONFIGURATION_URL,  # Discovery document URL
        client_kwargs=oidc_client_args,
        code_challenge_method="S256",  # PKCE code challenge method
    )
else:
    logger.info("OIDC client not configured because OIDC_READY is false.")


class MarvinAuthToken(BaseModel):
    """
    Pydantic response model for authentication tokens.
    """

    access_token: str
    token_type: str = "bearer"  # Defaults to "bearer" token type

    @classmethod
    def respond(cls, token: str, token_type: str = "bearer") -> dict[str, str]:
        """
        Helper method to create a dictionary representation of the token response.

        Args:
            token (str): The access token string.
            token_type (str, optional): The type of token. Defaults to "bearer".

        Returns:
            dict[str, str]: A dictionary suitable for an HTTP response body.
        """
        return cls(access_token=token, token_type=token_type).model_dump()


@controller(public_router)
class PublicAuthenticiationController(BasePublicController):
    @public_router.post("/token", summary="Get Access Token")
    def get_token(
        self,
        request: Request,  # FastAPI Request object to access headers, client info
        response: Response,  # FastAPI Response object to set cookies
        data: CredentialsRequestForm = Depends(),  # Form data for username/password
        session: Session = Depends(generate_session),  # DB session dependency
    ) -> dict[str, str]:
        """
        Authenticates a user with username and password (form data) and returns an access token.

        It sets the access token as an HTTPOnly cookie and also returns it in the response body.
        Handles potential `UserLockedOut` exceptions and general authentication failures.
        Client IP address is logged for security purposes.

        Args:
            request (Request): The incoming HTTP request.
            response (Response): The outgoing HTTP response, used for setting cookies.
            data (CredentialsRequestForm): Form data containing `username` and `password`.
            session (Session): SQLAlchemy database session.

        Returns:
            dict[str, str]: A dictionary containing the `access_token` and `token_type`.

        Raises:
            HTTPException (423 Locked): If the user account is locked.
            HTTPException (401 Unauthorized): If authentication fails (incorrect credentials).
        """
        # Attempt to get the client's real IP address, considering proxies
        client_ip = "unknown"
        if "x-forwarded-for" in request.headers:
            # The first IP in X-Forwarded-For is generally the original client
            client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host

        self.logger.info(f"Token requested from IP: {client_ip} for user: {data.username}")

        try:
            # Determine and use the appropriate authentication provider
            auth_provider = get_auth_provider(session, data)
            auth_result = auth_provider.authenticate()  # Returns (token, duration) or None
        except UserLockedOut as e:
            self.logger.warning(f"Login attempt for locked out user '{data.username}' from IP: {client_ip}")
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="User account is locked.") from e

        if not auth_result:
            logger.warning(f"Failed login attempt for user '{data.username}' from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password.",  # User-friendly generic message
                headers={"WWW-Authenticate": "Bearer"},  # Standard header for token auth
            )

        access_token, token_duration = auth_result
        expires_seconds = token_duration.total_seconds() if token_duration else None

        # Set the access token as an HTTPOnly cookie for web clients
        response.set_cookie(
            key="marvin.access_token",
            value=access_token,
            httponly=True,  # Helps prevent XSS attacks
            max_age=int(expires_seconds) if expires_seconds is not None else None,
            secure=self.settings.PRODUCTION,  # Send cookie only over HTTPS in production
            samesite="lax",  # Recommended SameSite policy
        )
        # Also return the token in the response body for API clients
        return MarvinAuthToken.respond(access_token)

    @public_router.get("/oauth", summary="Initiate OIDC Login")
    async def oauth_login(self, request: Request) -> RedirectResponse:
        """
        Initiates the OIDC authentication flow by redirecting the user to the OIDC provider.

        This endpoint is called when a user chooses to log in via OIDC.
        It requires OIDC to be configured and enabled in the application settings.

        Args:
            request (Request): The incoming HTTP request.

        Returns:
            RedirectResponse: A redirect to the OIDC provider's authorization endpoint.

        Raises:
            HTTPException (500 Internal Server Error): If OIDC is not configured/initialized.
        """
        if not oauth:  # Check if OIDC client was initialized
            self.logger.error("OIDC login attempt failed: OAuth client not initialized (OIDC not configured or not ready).")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC authentication is not configured on the server.",
            )

        oidc_client = oauth.create_client("oidc")  # Get the registered OIDC client

        # Determine the redirect URL for the OIDC provider to send the user back to after authentication
        if not self.settings.PRODUCTION:
            redirect_uri = f"{self.settings.BASE_URL}/api/auth/oauth/callback"
        else:
            # For production, construct the redirect URI based on the current request's base URL
            redirect_uri = str(URLPath("/api/auth/oauth/callback").make_absolute_url(request.base_url))
            # Ensure scheme matches request if behind TLS-terminating proxy
            if request.url.scheme == "https" and not redirect_uri.startswith("https://"):
                redirect_uri = redirect_uri.replace("http://", "https://", 1)

        # Generate the authorization redirect to the OIDC provider
        return await oidc_client.authorize_redirect(request, redirect_uri)

    @public_router.get("/oauth/callback", summary="OIDC Authentication Callback")
    async def oauth_callback(self, request: Request, response: Response, session: Session = Depends(generate_session)):
        """
        Handles the callback from the OIDC provider after user authentication.

        It exchanges the authorization code for an access token, retrieves user information,
        authenticates the user within Marvin (potentially creating a new user account),
        and sets an access token cookie.

        Args:
            request (Request): The incoming HTTP request from the OIDC provider.
            response (Response): The outgoing HTTP response, used for setting cookies.
            session (Session): SQLAlchemy database session.

        Returns:
            dict[str, str]: A dictionary containing the Marvin `access_token` and `token_type`.

        Raises:
            HTTPException (500 Internal Server Error): If OIDC is not configured.
            HTTPException (401 Unauthorized): If OIDC authentication fails or required claims are missing.
        """
        if not oauth:  # Check if OIDC client was initialized
            self.logger.error("OIDC callback failed: OAuth client not initialized.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC authentication is not configured on the server.",
            ) from None

        oidc_client = oauth.create_client("oidc")

        try:
            # Exchange authorization code for OIDC tokens
            oidc_token_data = await oidc_client.authorize_access_token(request)
        except Exception as e:
            self.logger.error(f"OIDC authorize_access_token failed: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC token exchange failed.") from e

        user_info_from_id_token = oidc_token_data.get("userinfo")
        marvin_auth_result = None

        try:
            if user_info_from_id_token:
                # Attempt authentication using userinfo from ID token first
                oidc_auth_provider = OpenIDProvider(session, user_info_from_id_token)
                marvin_auth_result = oidc_auth_provider.authenticate()

            if not marvin_auth_result:  # If not in ID token or auth failed, try userinfo endpoint
                self.logger.debug("[OIDC] Claims not present/sufficient in ID token, or initial auth failed. Fetching from userinfo endpoint.")
                # Fetch userinfo from OIDC provider's userinfo endpoint
                userinfo_from_endpoint = await oidc_client.userinfo(token=oidc_token_data)
                oidc_auth_provider_endpoint = OpenIDProvider(session, userinfo_from_endpoint)
                marvin_auth_result = oidc_auth_provider_endpoint.authenticate()

        except MissingClaimException as e:
            self.logger.error("OIDC authentication failed due to missing claims: %s", e)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"OIDC authentication failed: {e}") from e
        except Exception as e:  # Catch other unexpected errors during OIDC auth provider logic
            self.logger.error("OIDC authentication processing error: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error processing OIDC user information.") from e

        if not marvin_auth_result:
            self.logger.error("OIDC authentication failed after attempting all userinfo sources.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unable to authenticate user with OIDC provider.")

        access_token, token_duration = marvin_auth_result
        expires_seconds = token_duration.total_seconds() if token_duration else None

        frontend_url = self.settings.FRONTEND_URL

        # Set cookie for same-origin production deployments
        redirect = RedirectResponse(
            url=f"{frontend_url}/api/auth/oidc/callback?token={access_token}",
            status_code=302,
        )
        redirect.set_cookie(
            key="marvin.access_token",
            value=access_token,
            httponly=True,
            max_age=int(expires_seconds) if expires_seconds is not None else None,
            secure=self.settings.PRODUCTION,
            samesite="lax",
        )
        return redirect


@controller(user_router)
class UserAuthenticationController(BaseUserController):
    @user_router.get("/refresh", response_model=MarvinAuthToken, summary="Refresh Access Token")
    async def refresh_token(self, current_user: PrivateUser = Depends(get_current_user)) -> dict[str, str]:
        """
        Refreshes an access token for an currently authenticated user.

        Requires a valid existing access token (either via cookie or Authorization header).
        Generates a new access token with a new expiration time.
        Also dispatches an event to the event bus upon successful token refresh.

        Args:
            current_user (PrivateUser): The currently authenticated user, injected by FastAPI.

        Returns:
            dict[str, str]: A dictionary containing the new `access_token` and `token_type`.
        """
        # Create a new access token for the current user
        new_access_token = security.create_access_token(data={"sub": str(current_user.id)})

        # Dispatch an event indicating a token refresh
        self.event_bus.dispatch(
            integration_id="internal_token_refresh",  # Identifier for the source of the event
            event_type=EventTypes.token_refreshed,  # Specific event type
            group_id=current_user.group_id,  # Associate with user's group
            document_data=EventTokenRefreshData(username=current_user.username),
            message=f"Access token refreshed for user {current_user.username}",
        )
        self.logger.info(f"Access token refreshed for user: {current_user.username}")
        return MarvinAuthToken.respond(new_access_token)

    @user_router.post("/logout", summary="Log Out User")
    async def logout(self, response: Response) -> dict[str, str]:
        """
        Logs out the current user by deleting their access token cookie.

        Args:
            response (Response): The FastAPI Response object, used to delete the cookie.

        Returns:
            dict[str, str]: A confirmation message indicating successful logout.
        """
        # Delete the access token cookie (use the configured name — auth reads settings.AUTH_COOKIE_NAME)
        response.delete_cookie(self.settings.AUTH_COOKIE_NAME, httponly=True, secure=self.settings.PRODUCTION, samesite="lax")
        self.logger.info("User logged out successfully.")
        return {"message": "Successfully logged out."}
