"""
This module provides an OpenID Connect (OIDC) authentication provider for Marvin.

It allows users to authenticate using an OIDC Identity Provider (IdP).
It handles claim validation, user creation (if enabled), and synchronization
of admin status based on group claims.
"""

from datetime import timedelta

from authlib.oidc.core import UserInfo
from sqlalchemy.orm.session import Session

from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.core.exceptions import MissingClaimException
from marvin.core.security.providers.auth_providers import AuthProvider
from marvin.db.models.users.users import AuthMethod
from marvin.repos.all_repositories import get_repositories


class OpenIDProvider(AuthProvider[UserInfo]):
    """Authentication provider that authenticates a user using a token from OIDC ID token"""

    _logger = root_logger.get_logger("openid_provider")

    def __init__(self, session: Session, data: UserInfo) -> None:
        """
        Initializes the OpenIDProvider.

        Args:
            session (Session): SQLAlchemy session.
            data (UserInfo): The OIDC UserInfo object containing claims from the ID token.
        """
        super().__init__(session, data)

    def authenticate(self) -> tuple[str, timedelta] | None:
        """
        Attempts to authenticate a user using OIDC claims.

        It performs the following steps:
        1. Validates that all required claims are present and not empty.
        2. If group claim validation is enabled, checks if the user belongs to
           the required groups.
        3. Tries to find an existing user based on the OIDC user claim.
        4. If the user doesn't exist and OIDC signup is enabled, creates a new user.
        5. If the user exists, optionally updates their admin status based on group claims.
        6. Generates an access token if authentication is successful.

        Raises:
            MissingClaimException: If required OIDC claims are missing or empty.

        Returns:
            tuple[str, timedelta] | None: A tuple containing the access token and
                                         its expiration delta if authentication is
                                         successful, otherwise None.
        """

        settings = get_app_settings()
        claims = self.data
        if not claims:
            self._logger.error("[OIDC] No claims in the id_token")
            raise MissingClaimException()

        # Log all claims for debugging
        self._logger.debug("[OIDC] Received claims:")
        for key, value in claims.items():
            self._logger.debug("[OIDC]   %s: %s", key, value)

        if not self.required_claims.issubset(claims.keys()):
            self._logger.error(
                "[OIDC] Required claims not present. Expected: %s Actual: %s",
                self.required_claims,
                claims.keys(),
            )
            raise MissingClaimException()

        # Check for empty required claims
        for claim in self.required_claims:
            if not claims.get(claim):
                self._logger.error("[OIDC] Required claim '%s' is empty", claim)
                raise MissingClaimException()

        repos = get_repositories(self.session, group_id=None)

        is_admin = False
        if settings.OIDC_REQUIRES_GROUP_CLAIM:
            group_claim = claims.get(settings.OIDC_GROUPS_CLAIM, []) or []
            is_admin = settings.OIDC_ADMIN_GROUP in group_claim if settings.OIDC_ADMIN_GROUP else False
            is_valid_user = settings.OIDC_USER_GROUP in group_claim if settings.OIDC_USER_GROUP else True

            if not (is_valid_user or is_admin):
                self._logger.warning(
                    "[OIDC] Successfully authenticated, but user does not have one of the required group(s). \
                    Found: %s - Required (one of): %s",
                    group_claim,
                    [settings.OIDC_USER_GROUP, settings.OIDC_ADMIN_GROUP],
                )
                return None

        user = self.try_get_user(claims.get(settings.OIDC_USER_CLAIM))
        if not user:
            if not settings.OIDC_SIGNUP_ENABLED:
                self._logger.debug("[OIDC] No user found. Not creating a new user - new user creation is disabled.")
                return None

            self._logger.debug("[OIDC] No user found. Creating new OIDC user.")

            try:
                # some IdPs don't provide a username (looking at you Google), so if we don't have the claim,
                # we'll create the user with whatever the USER_CLAIM is (default email)
                username = claims.get("preferred_username", claims.get("username", claims.get(settings.OIDC_USER_CLAIM)))
                user = repos.users.create(
                    {
                        "username": username,
                        "password": "OIDC",
                        "full_name": claims.get(settings.OIDC_NAME_CLAIM),
                        "email": claims.get("email"),
                        "admin": is_admin,
                        "auth_method": AuthMethod.OIDC,
                    }
                )
                self.session.commit()

            except Exception as e:
                self._logger.error("[OIDC] Exception while creating user: %s", e)
                return None

            return self.get_access_token(user, settings.OIDC_REMEMBER_ME)  # type: ignore

        if user:
            if settings.OIDC_ADMIN_GROUP and user.admin != is_admin:
                self._logger.debug("[OIDC] %s user as admin", "Setting" if is_admin else "Removing")
                user.admin = is_admin
                repos.users.update(user.id, user)
            return self.get_access_token(user, settings.OIDC_REMEMBER_ME)

        self._logger.warning("[OIDC] Found user but their AuthMethod does not match OIDC")
        return None

    @property
    def required_claims(self):
        """
        Returns a set of required OIDC claims based on application settings.

        The base required claims are the OIDC name claim, email claim, and user claim.
        If OIDC group claim requirement is enabled, the OIDC groups claim is also added.

        Returns:
            set: A set of required OIDC claim names.
        """
        claims = {self.settings.OIDC_NAME_CLAIM, "email", self.settings.OIDC_USER_CLAIM}
        if self.settings.OIDC_REQUIRES_GROUP_CLAIM:
            claims.add(self.settings.OIDC_GROUPS_CLAIM)
        return claims
