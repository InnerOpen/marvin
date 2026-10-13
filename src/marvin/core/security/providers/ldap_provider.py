"""
This module provides an LDAP authentication provider for Marvin.

It extends the `CredentialsProvider` to allow users to authenticate against an
LDAP server. If a user is found in LDAP but not in the Marvin database, a new
Marvin user account can be created. It also supports syncing admin status based
on LDAP group membership.
"""

from datetime import timedelta

import ldap
from ldap.ldapobject import LDAPObject
from sqlalchemy.orm.session import Session

from marvin.core import root_logger
from marvin.core.security.providers.credentials_provider import CredentialsProvider
from marvin.db.models.users.users import AuthMethod
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.user.auth import CredentialsRequest
from marvin.schemas.user.user import PrivateUser


class LDAPProvider(CredentialsProvider):
    """Authentication provider that authenticats a user against an LDAP server using username/password combination"""

    _logger = root_logger.get_logger("ldap_provider")

    def __init__(self, session: Session, data: CredentialsRequest) -> None:
        """
        Initializes the LDAPProvider.

        Args:
            session (Session): SQLAlchemy session.
            data (CredentialsRequest): The credentials request data containing
                                       username and password.
        """
        super().__init__(session, data)
        self.conn = None

    def authenticate(self) -> tuple[str, timedelta] | None:
        """
        Attempts to authenticate a user against an LDAP provider or falls back to
        local database authentication.

        The authentication flow is as follows:
        1. Try to find the user in the local Marvin database.
        2. If the user is not found OR their authentication method is LDAP:
           - Attempt to authenticate against the LDAP server using `get_user()`.
           - If successful, generate an access token.
        3. If the user is found and their authentication method is NOT LDAP,
           or if LDAP authentication fails:
           - Fall back to the standard `CredentialsProvider.authenticate()` method.

        Returns:
            tuple[str, timedelta] | None: A tuple containing the access token and
                                         its expiration delta if authentication is
                                         successful, otherwise None.
        """
        # When LDAP is enabled, we need to still also support authentication with Mealie backend
        # First we look to see if we have a user. If we don't we'll attempt to create one with LDAP
        # If we do find a user, we will check if their auth method is LDAP and attempt to authenticate
        # Otherwise, we will proceed with Mealie authentication
        user = self.try_get_user(self.data.username)
        if not user or user.auth_method == AuthMethod.LDAP:
            user = self.get_user()
            if user:
                return self.get_access_token(user, self.data.remember_me)

        return super().authenticate()

    def search_user(self, conn: LDAPObject) -> list[tuple[str, dict[str, list[bytes]]]] | None:
        """
        Searches for a user by LDAP_ID_ATTRIBUTE, LDAP_MAIL_ATTRIBUTE, and the provided LDAP_USER_FILTER.
        If none or multiple users are found, return False
        """
        if not self.data:
            return None

        user_filter = ""
        if self.settings.LDAP_USER_FILTER:
            # fill in the template provided by the user to maintain backwards compatibility
            user_filter = self.settings.LDAP_USER_FILTER.format(
                id_attribute=self.settings.LDAP_ID_ATTRIBUTE,
                mail_attribute=self.settings.LDAP_MAIL_ATTRIBUTE,
                input=self.data.username,
            )
        # Don't assume the provided search filter has (|({id_attribute}={input})({mail_attribute}={input}))
        search_filter = "(&(|({id_attribute}={input})({mail_attribute}={input})){filter})".format(
            id_attribute=self.settings.LDAP_ID_ATTRIBUTE,
            mail_attribute=self.settings.LDAP_MAIL_ATTRIBUTE,
            input=self.data.username,
            filter=user_filter,
        )

        user_entry: list[tuple[str, dict[str, list[bytes]]]] | None = None
        try:
            self.logger.debug(f"[LDAP] Starting search with filter: {search_filter}")
            user_entry = conn.search_s(
                self.settings.LDAP_BASE_DN,
                ldap.SCOPE_SUBTREE,
                search_filter,
                [
                    self.settings.LDAP_ID_ATTRIBUTE,
                    self.settings.LDAP_NAME_ATTRIBUTE,
                    self.settings.LDAP_MAIL_ATTRIBUTE,
                ],
            )
        except ldap.FILTER_ERROR:
            self.logger.error("[LDAP] Bad user search filter")

        if not user_entry:
            conn.unbind_s()
            self.logger.error("[LDAP] No user was found with the provided user filter")
            return None

        # we only want the entries that have a dn
        user_entry = [(dn, attr) for dn, attr in user_entry if dn]

        if len(user_entry) > 1:
            self.logger.warning("[LDAP] Multiple users found with the provided user filter")
            self.logger.debug(f"[LDAP] The following entries were returned: {user_entry}")
            conn.unbind_s()
            return None

        return user_entry

    def get_user(self) -> PrivateUser | None:
        """Given a username and password, tries to authenticate by BINDing to an
        LDAP server

        If the BIND succeeds, it will either create a new user of that username on
        the server or return an existing one.
        Returns False on failure.
        """

        db = get_repositories(self.session, group_id=None)
        if not self.data:
            return None
        data = self.data

        if self.settings.LDAP_TLS_INSECURE:
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)

        conn = ldap.initialize(self.settings.LDAP_SERVER_URL)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        conn.set_option(ldap.OPT_REFERRALS, 0)

        if self.settings.LDAP_TLS_CACERTFILE:
            conn.set_option(ldap.OPT_X_TLS_CACERTFILE, self.settings.LDAP_TLS_CACERTFILE)
            conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)

        if self.settings.LDAP_ENABLE_STARTTLS:
            conn.start_tls_s()

        try:
            conn.simple_bind_s(self.settings.LDAP_QUERY_BIND, self.settings.LDAP_QUERY_PASSWORD)
        except (ldap.INVALID_CREDENTIALS, ldap.NO_SUCH_OBJECT):
            self.logger.error("[LDAP] Unable to bind to with provided user/password")
            conn.unbind_s()
            return None

        user_entry = self.search_user(conn)
        if not user_entry:
            return None
        user_dn, user_attr = user_entry[0]

        # Check the credentials of the user
        try:
            self.logger.debug(f"[LDAP] Attempting to bind with '{user_dn}' using the provided password")
            conn.simple_bind_s(user_dn, data.password)
        except (ldap.INVALID_CREDENTIALS, ldap.NO_SUCH_OBJECT):
            self.logger.error("[LDAP] Bind failed")
            conn.unbind_s()
            return None

        user = self.try_get_user(data.username)

        if user is None:
            self.logger.debug("[LDAP] User is not in Mealie. Creating a new account")

            attribute_keys = {
                self.settings.LDAP_ID_ATTRIBUTE: "username",
                self.settings.LDAP_NAME_ATTRIBUTE: "name",
                self.settings.LDAP_MAIL_ATTRIBUTE: "mail",
            }
            attributes = {}
            for attribute_key, attribute_name in attribute_keys.items():
                if attribute_key not in user_attr or len(user_attr[attribute_key]) == 0:
                    self.logger.error(f"[LDAP] Unable to create user due to missing '{attribute_name}' ('{attribute_key}') attribute")
                    self.logger.debug(f"[LDAP] User has the following attributes: {user_attr}")
                    conn.unbind_s()
                    return None
                attributes[attribute_key] = user_attr[attribute_key][0].decode("utf-8")

            user = db.users.create(
                {
                    "username": attributes[self.settings.LDAP_ID_ATTRIBUTE],
                    "password": "LDAP",
                    "full_name": attributes[self.settings.LDAP_NAME_ATTRIBUTE],
                    "email": attributes[self.settings.LDAP_MAIL_ATTRIBUTE],
                    "admin": False,
                    "auth_method": AuthMethod.LDAP,
                },
            )

        if self.settings.LDAP_ADMIN_FILTER:
            should_be_admin = len(conn.search_s(user_dn, ldap.SCOPE_BASE, self.settings.LDAP_ADMIN_FILTER, [])) > 0
            if user.admin != should_be_admin:
                self.logger.debug(f"[LDAP] {'Setting' if should_be_admin else 'Removing'} user as admin")
                user.admin = should_be_admin
                db.users.update(user.id, user)

        conn.unbind_s()
        return user
