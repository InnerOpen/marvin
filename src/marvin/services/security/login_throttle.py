"""Throttling repeated failed sign-ins and password-reset requests.

Failures are counted per account and per client IP (AuthThrottleModel, in the database, so a restart
or a second replica doesn't reset them):

- An account refuses sign-ins for SECURITY_LOGIN_LOCKOUT_MINUTES once it has SECURITY_MAX_LOGIN_ATTEMPTS
  failures, and for SECURITY_LOGIN_LONG_LOCKOUT_MINUTES from twice that on — the refusal grows while
  the guessing goes on, then clears by itself. A successful sign-in clears the account's count.
- One IP refuses sign-ins the same way after SECURITY_LOGIN_IP_MAX_FAILURES failures across any
  accounts, so spraying many names from one place stops too.
- An account is counted by its user id when the name typed matches one (so its username and its email
  share a count) and by the name otherwise — an account that doesn't exist is refused exactly like one
  that does, so the answer never tells an attacker which names are real.

Refusals are decided before any password is hashed. Password-reset emails are capped per address and per
IP (SECURITY_PASSWORD_RESET_*), dropped silently past the cap so a reset form can't be used to flood
someone's inbox.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.db.models.platform.auth_throttles import AuthThrottleModel
from marvin.services.security.client_info import UNKNOWN_IP, get_client_ip

ACCOUNT, IP, RESET_EMAIL, RESET_IP = "login:account", "login:ip", "reset:email", "reset:ip"
_KEY_LENGTH = 320
_RESET_WINDOW = timedelta(hours=1)


@dataclass
class Throttled(Exception):
    """Too many failures: refused for `retry_after` more seconds."""

    retry_after: int

    @property
    def minutes(self) -> int:
        return max(1, math.ceil(self.retry_after / 60))


def login_client_ip(request: Request) -> str:
    """The signing-in client's IP. Cloudflare's CF-Connecting-IP first: Cloudflare sets it on every request it
    passes, overwriting whatever the caller sent, and the admin's login proxy forwards it — unlike the first
    X-Forwarded-For entry, a caller can't choose it. A spoofed IP could only dodge the per-IP count, never the
    per-account one."""
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    return cf_ip or get_client_ip(request)


def account_key(name: str, user_id: object | None = None) -> str:
    """The count an account's failures go into: its user id when the name matches a user, else the name."""
    return f"user:{user_id}" if user_id else f"name:{name.strip().lower()}"[:_KEY_LENGTH]


class LoginThrottle:
    def __init__(self, session: Session, settings=None) -> None:
        self.session = session
        self.settings = settings or get_app_settings()

    # --- sign-in -------------------------------------------------------------------------------------------------

    def check(self, account: str, ip: str) -> None:
        """Raise Throttled when the account or the IP is being refused right now."""
        now = datetime.now(UTC)
        waits = [
            (row.locked_until - now).total_seconds()
            for row in (self._row(ACCOUNT, account), self._row(IP, ip) if ip != UNKNOWN_IP else None)
            if row is not None and row.locked_until is not None and row.locked_until > now
        ]
        if waits:
            raise Throttled(retry_after=math.ceil(max(waits)))

    def failed(self, account: str, ip: str) -> int | None:
        """Count one failed sign-in. Returns the account's failure count when this failure is the one that starts
        a refusal (the first, and the longer one) — worth announcing — else None."""
        limit = self.settings.SECURITY_MAX_LOGIN_ATTEMPTS
        count = self._fail(ACCOUNT, account, limit)
        if ip != UNKNOWN_IP:
            self._fail(IP, ip, self.settings.SECURITY_LOGIN_IP_MAX_FAILURES)
        self.session.commit()
        return count if count in (limit, 2 * limit) else None

    def succeeded(self, account: str) -> None:
        """A successful sign-in clears its account's count (not the IP's: one right password among many wrong
        ones from the same place shouldn't wipe the slate)."""
        self.session.query(AuthThrottleModel).filter_by(scope=ACCOUNT, key=account).delete()
        self.session.commit()

    def release_accounts(self) -> int:
        """End every account's refusal now (POST /api/admin/users/unlock?force=true); how many were refused."""
        released = (
            self.session.query(AuthThrottleModel)
            .filter(AuthThrottleModel.scope == ACCOUNT, AuthThrottleModel.locked_until > datetime.now(UTC))
            .delete(synchronize_session=False)
        )
        self.session.commit()
        return released

    def _fail(self, scope: str, key: str, limit: int) -> int:
        now = datetime.now(UTC)
        row = self._row(scope, key) or self._new(scope, key, now)
        if row.window_start < now - timedelta(hours=self.settings.SECURITY_LOGIN_FAILURE_WINDOW_HOURS):
            row.count, row.window_start, row.locked_until = 0, now, None
        row.count += 1
        if row.count >= limit:
            long = row.count >= 2 * limit
            minutes = self.settings.SECURITY_LOGIN_LONG_LOCKOUT_MINUTES if long else self.settings.SECURITY_LOGIN_LOCKOUT_MINUTES
            row.locked_until = now + timedelta(minutes=minutes)
        return row.count

    # --- password reset ------------------------------------------------------------------------------------------

    def allow_reset(self, email: str, ip: str) -> bool:
        """Count one password-reset request; False when the address or the IP is over its hourly cap."""
        email_ok = self._within(RESET_EMAIL, email.strip().lower()[:_KEY_LENGTH], self.settings.SECURITY_PASSWORD_RESET_MAX_PER_HOUR)
        ip_ok = ip == UNKNOWN_IP or self._within(RESET_IP, ip, self.settings.SECURITY_PASSWORD_RESET_IP_MAX_PER_HOUR)
        self.session.commit()
        return email_ok and ip_ok

    def _within(self, scope: str, key: str, limit: int) -> bool:
        now = datetime.now(UTC)
        row = self._row(scope, key) or self._new(scope, key, now)
        if row.window_start < now - _RESET_WINDOW:
            row.count, row.window_start = 0, now
        row.count += 1
        return row.count <= limit

    # --- rows ----------------------------------------------------------------------------------------------------

    def _row(self, scope: str, key: str) -> AuthThrottleModel | None:
        return self.session.query(AuthThrottleModel).filter_by(scope=scope, key=key[:_KEY_LENGTH]).one_or_none()

    def _new(self, scope: str, key: str, now: datetime) -> AuthThrottleModel:
        row = AuthThrottleModel(session=self.session, scope=scope, key=key[:_KEY_LENGTH], count=0, window_start=now)
        try:
            with self.session.begin_nested():  # a savepoint: losing the race undoes only this row
                self.session.add(row)
        except IntegrityError:  # another request created it a moment ago
            return self._row(scope, key)
        return row
