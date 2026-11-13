"""
This module provides password hashing functionality for the Marvin application.

It defines a `Hasher` protocol and provides two implementations:
- `BcryptHasher`: Uses bcrypt for strong password hashing.
- `FakeHasher`: A no-op hasher for testing purposes.

The `get_hasher` function returns the appropriate hasher based on the
application settings (FakeHasher for testing, BcryptHasher otherwise).
"""

import hashlib
import threading
import time
from collections import OrderedDict
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


class VerifiedTokens:
    """Remembers which (token, stored hash) pairs bcrypt has already confirmed, so an API token costs one bcrypt
    check per few minutes instead of one per request (~0.17 s of CPU each at 12 rounds).

    Only the bcrypt RESULT is remembered; the row query still runs on every request, so a revoked, disabled or
    deleted token is refused on its very next use. The key is (table, SHA-256 of the token, the row's stored
    token_hash): rotating a token changes its stored hash, so the old pair can never match again. Knowing a key
    is no use to an attacker: a request carries the raw token and the lookup half is computed from it here, so
    hitting an entry takes the token itself (or a SHA-256 preimage), and an entry exists only after bcrypt
    accepted that exact token against that exact hash. Failures are never remembered. Bounded (least recently
    used goes first) and every entry lapses after `ttl` seconds.

    `size` and `ttl` are SECURITY_TOKEN_VERIFY_CACHE_SIZE (minimum 1) and SECURITY_TOKEN_VERIFY_CACHE_TTL (0 or
    less: remember nothing), read when used so a change takes effect; a value given here overrides the setting."""

    def __init__(self, size: int | None = None, ttl: float | None = None):
        self._size, self._ttl = size, ttl
        self._seen: OrderedDict[tuple[str, str, str], float] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        size = self._size if self._size is not None else get_app_settings().SECURITY_TOKEN_VERIFY_CACHE_SIZE
        return max(1, size)

    @property
    def ttl(self) -> float:
        ttl = self._ttl if self._ttl is not None else get_app_settings().SECURITY_TOKEN_VERIFY_CACHE_TTL
        return max(0.0, ttl)

    def __len__(self) -> int:
        return len(self._seen)

    def known(self, key: tuple[str, str, str]) -> bool:
        if self.ttl == 0:
            return False
        with self._lock:
            until = self._seen.get(key)
            if until is None:
                return False
            if until < time.monotonic():
                del self._seen[key]
                return False
            self._seen.move_to_end(key)
            return True

    def remember(self, key: tuple[str, str, str]) -> None:
        ttl, size = self.ttl, self.size
        if ttl == 0:
            return
        with self._lock:
            self._seen[key] = time.monotonic() + ttl
            self._seen.move_to_end(key)
            while len(self._seen) > size:
                self._seen.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


verified_tokens = VerifiedTokens()


def find_token(query, model, token: str):
    """The row of `query` (enabled tokens of `model`, which has token_hash and token_lookup) that `token` belongs
    to, or None. Found by its lookup and confirmed with bcrypt — once: later requests with the same token skip
    the check while `verified_tokens` remembers it (see there for why that is safe). A token stored before
    token_lookup existed is found the old way — bcrypt against each such row — and gets its lookup on the way,
    so that scan shrinks to nothing as old tokens are used."""
    lookup = token_lookup(token)
    row = query.filter(model.token_lookup == lookup).first()
    if row is not None:
        key = (model.__tablename__, lookup, row.token_hash)
        if verified_tokens.known(key):
            return row
        if not get_hasher().verify(token, row.token_hash):
            return None
        verified_tokens.remember(key)
        return row
    for row in query.filter(model.token_lookup.is_(None)).all():
        if get_hasher().verify(token, row.token_hash):
            row.token_lookup = lookup
            verified_tokens.remember((model.__tablename__, lookup, row.token_hash))
            return row
    return None
