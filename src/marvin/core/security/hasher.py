"""
This module provides password hashing functionality for the Marvin application.

It defines a `Hasher` protocol and provides two implementations:
- `BcryptHasher`: Uses bcrypt for strong password hashing.
- `FakeHasher`: A no-op hasher for testing purposes.

The `get_hasher` function returns the appropriate hasher based on the
application settings (FakeHasher for testing, BcryptHasher otherwise).
"""

import hashlib
from functools import lru_cache
from typing import Protocol

import bcrypt

from marvin.core.config import get_app_settings


class Hasher(Protocol):
    """
    Protocol defining the interface for password hashers.
    """

    def hash(self, password: str) -> str:
        """Hashes a password."""
        ...

    def verify(self, password: str, hashed: str) -> bool:
        """Verifies a password against a hashed version."""
        ...


class FakeHasher:
    """
    A fake hasher that does not perform any hashing.

    This is used for testing purposes.
    """

    def hash(self, password: str) -> str:
        """Returns the passwordそのまま."""
        return password

    def verify(self, password: str, hashed: str) -> bool:
        """Compares the password with the hashed value directly."""
        return password == hashed


class BcryptHasher:
    """
    A hasher that uses the bcrypt algorithm for password hashing.
    """

    def __init__(self, rounds: int = 12):
        """
        Initialize the BcryptHasher with a configurable cost factor.

        Args:
            rounds (int): Bcrypt cost factor (4-31). Higher = more secure but slower. Default: 12
        """
        self.rounds = max(4, min(31, rounds))  # Clamp to valid bcrypt range

    def hash(self, password: str) -> str:
        """
        Hashes a password using bcrypt.

        Args:
            password (str): The password to hash.

        Returns:
            str: The hashed password.
        """
        password_bytes = password.encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=self.rounds))
        return hashed.decode("utf-8")

    def verify(self, password: str, hashed: str) -> bool:
        """
        Verifies a password against a bcrypt-hashed version.

        Args:
            password (str): The password to verify.
            hashed (str): The hashed password.

        Returns:
            bool: True if the password matches, False otherwise.
        """
        password_bytes = password.encode("utf-8")
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)


@lru_cache(maxsize=1)
def get_hasher() -> Hasher:
    """
    Returns the appropriate password hasher based on application settings.

    If the application is in TESTING mode, a FakeHasher is returned.
    Otherwise, a BcryptHasher is returned with the configured cost factor.

    Returns:
        Hasher: The password hasher instance.
    """
    settings = get_app_settings()

    if settings.TESTING:
        return FakeHasher()

    return BcryptHasher(rounds=settings.SECURITY_BCRYPT_ROUNDS)


def token_lookup(token: str) -> str:
    """A fast, indexable fingerprint of an API token (SHA-256): finds the one stored token to bcrypt-check, instead
    of bcrypt-checking every one — a wrong token then costs one query, not a CPU-second per stored token. Safe
    because tokens are SECURITY_TOKEN_RANDOM_BYTES of randomness, not something guessable; the bcrypt hash stays
    the check."""
    return hashlib.sha256(token.encode()).hexdigest()


def find_token(query, model, token: str):
    """The row of `query` (enabled tokens of `model`, which has token_hash and token_lookup) that `token` belongs
    to, or None. Found by its lookup and confirmed with bcrypt; a token stored before token_lookup existed is
    found the old way — bcrypt against each such row — and gets its lookup on the way, so that scan shrinks to
    nothing as old tokens are used."""
    lookup = token_lookup(token)
    row = query.filter(model.token_lookup == lookup).first()
    if row is not None:
        return row if get_hasher().verify(token, row.token_hash) else None
    for row in query.filter(model.token_lookup.is_(None)).all():
        if get_hasher().verify(token, row.token_hash):
            row.token_lookup = lookup
            return row
    return None
