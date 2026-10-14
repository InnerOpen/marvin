import abc
from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar

import jwt
from sqlalchemy.orm.session import Session

from marvin.core.config import get_app_settings
from marvin.core.security.security import JWT_ALGORITHM, _session_hours
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.user.user import PrivateUser

ALGORITHM = JWT_ALGORITHM  # Import from central location
ISS = "marvin"
remember_me_duration = timedelta(days=14)

T = TypeVar("T")


class AuthProvider(Generic[T], metaclass=abc.ABCMeta):
    """
    Abstract base class for authentication providers.

    This class defines the interface for different authentication strategies,
    such as credentials-based or LDAP-based authentication.

    Type Parameters:
        T: The type of the input data used for authentication (e.g., CredentialsRequest).
    """

    def __init__(self, session: Session, data: T) -> None:
        """
        Initializes the authentication provider.

        Args:
            session (Session): SQLAlchemy session.
            data (T): The authentication data.
        """
        self.session = session
        self.data = data
        self.user: PrivateUser | None = None
        self.__has_tried_user = False

    @classmethod
    def __subclasshook__(cls, __subclass: type) -> bool:
        return hasattr(__subclass, "authenticate") and callable(__subclass.authenticate)

    def _record_sign_in(self, user: PrivateUser) -> None:
        """Stamp the user's last sign-in (Admin → Overview lists recent ones). Best-effort: never blocks a sign-in."""
        from datetime import UTC, datetime

        from marvin.db.models.users.users import Users

        try:
            self.session.query(Users).filter(Users.id == user.id).update({Users.last_login_at: datetime.now(UTC)}, synchronize_session=False)
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()

    def get_access_token(self, user: PrivateUser, remember_me=False) -> tuple[str, timedelta]:
        """
        Generates an access token for the given user.

        Args:
            user (PrivateUser): The user for whom to create the token.
            remember_me (bool, optional): If True, the token will have a longer
                                         expiration time. Defaults to False.

        Returns:
            tuple[str, timedelta]: A tuple containing the access token and its expiration delta.
        """
        self._record_sign_in(user)
        duration = timedelta(hours=_session_hours())
        if remember_me and remember_me_duration > duration:
            duration = remember_me_duration

        return AuthProvider.create_access_token({"sub": str(user.id)}, duration)

    @staticmethod
    def create_access_token(data: dict, expires_delta: timedelta | None = None) -> tuple[str, timedelta]:
        """
        Creates a JWT access token.

        Args:
            data (dict): The data to include in the token payload.
            expires_delta (timedelta | None, optional): The token expiration time.
                Defaults to the value specified in application settings.

        Returns:
            tuple[str, timedelta]: A tuple containing the encoded JWT access token
                                 and its expiration delta.
        """
        settings = get_app_settings()

        to_encode = data.copy()
        expires_delta = expires_delta or timedelta(hours=_session_hours())

        expire = datetime.now(UTC) + expires_delta

        to_encode["exp"] = expire
        to_encode["iss"] = ISS
        return (
            jwt.encode(to_encode, settings.SECRET, algorithm=ALGORITHM),
            expires_delta,
        )

    def try_get_user(self, username: str) -> PrivateUser | None:
        """
        Tries to retrieve a user from the database by username or email.

        It first searches by username, and if not found, searches by email.
        The result is cached to avoid redundant database queries.

        Args:
            username (str): The username or email to search for.

        Returns:
            PrivateUser | None: The found user, or None if not found.
        """
        if self.__has_tried_user:
            return self.user

        db = get_repositories(self.session, group_id=None)

        user = user = db.users.get_one(username, "username", any_case=True)
        if not user:
            user = db.users.get_one(username, "email", any_case=True)

        self.user = user
        return user

    @abc.abstractmethod
    def authenticate(self) -> tuple[str, timedelta] | None:
        """
        Attempts to authenticate a user based on the provided data.

        This method must be implemented by subclasses.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.

        Returns:
            tuple[str, timedelta] | None: A tuple containing the access token and
                                         its expiration delta if authentication is
                                         successful, otherwise None.
        """
        raise NotImplementedError
