"""Is a storage provider or backup target reachable with the credentials it has? And what does an error
from one mean, in words an operator can act on?

``check_provider`` / ``check_target`` list, put, get and delete one tiny object under a reserved prefix
(``_marvin-healthcheck/<uuid>.txt``), time each step, and always try the delete, so the object is never
left behind. They use only the storage contract, so they work for the built-in ``local`` and for any
plugin. ``explain`` maps an exception (botocore's ``ClientError`` codes, network errors, the contract's
own errors) to a plain message; the backup engine uses it for its failure lines and run records.

Like the rest of the storage package it imports no Marvin settings or database code: the backup CronJob
uses it too. Messages never carry a credential (the codes and texts S3-compatible services return don't
include one; ``scrub`` is the belt and braces for anything written down).
"""

from __future__ import annotations

import hashlib
import io
import re
import socket
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marvin_integration_sdk.storage import BackupTarget, StorageConfigError, StorageProvider

HEALTHCHECK_PREFIX = "_marvin-healthcheck/"

KEY_INVALID = "the key is invalid or revoked — update the Secret that holds it"
KEY_NO_ACCESS = "the key can't access this bucket — check which buckets the token is scoped to"
NO_BUCKET = "the bucket doesn't exist — check the bucket name and the endpoint (account)"
UNREACHABLE = "the endpoint can't be reached (DNS or network) — check the endpoint URL"
TIMED_OUT = "the endpoint didn't answer in time"
CLOCK = "the request was refused as too old — check the clock of the machine running this"

# Error codes S3-compatible services return (AWS S3, Cloudflare R2, MinIO, B2), by what they mean.
_CODES: dict[str, str] = {
    "InvalidAccessKeyId": KEY_INVALID,
    "SignatureDoesNotMatch": KEY_INVALID,
    "Unauthorized": KEY_INVALID,
    "InvalidToken": KEY_INVALID,
    "ExpiredToken": KEY_INVALID,
    "TokenRefreshRequired": KEY_INVALID,
    "AccessDenied": KEY_NO_ACCESS,
    "AllAccessDisabled": KEY_NO_ACCESS,
    "Forbidden": KEY_NO_ACCESS,
    "NoSuchBucket": NO_BUCKET,
    "RequestTimeTooSkewed": CLOCK,
}
# When a service answers with no code (a HEAD request has no body: botocore's code is then just "403"),
# its HTTP status — which can't tell a revoked key from one without access to the bucket.
REFUSED = "access refused — the key is invalid, revoked, or can't access this bucket"
_STATUSES: dict[int, str] = {401: KEY_INVALID, 403: REFUSED}
_UNREACHABLE = ("EndpointConnectionError", "ConnectionError", "ProxyConnectionError", "gaierror", "ConnectionRefusedError")
_TIMEOUTS = ("ConnectTimeoutError", "ReadTimeoutError", "TimeoutError", "timeout")


@dataclass(frozen=True)
class Explanation:
    message: str
    """What it means, for a person: a plain sentence, or the exception's own text when it is unknown."""
    code: str | None = None
    """The service's error code (``InvalidAccessKeyId``) or the exception's class, when there is one."""

    def __str__(self) -> str:
        return f"{self.message} ({self.code})" if self.code else self.message


def _client_error(exc: BaseException) -> tuple[str, int | None]:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return "", None
    code = str((response.get("Error") or {}).get("Code") or "")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code, status if isinstance(status, int) else None


def _chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def explain(exc: BaseException) -> Explanation:
    """A plain explanation of a storage error (and the code it came with)."""
    for e in _chain(exc):
        code, status = _client_error(e)
        if code in _CODES:
            return Explanation(_CODES[code], code)
        if code == "NoSuchKey":
            return Explanation("the object wasn't found", code)
        if status in _STATUSES and (not code or code.isdigit()):
            return Explanation(_STATUSES[status], f"HTTP {status}")
        if code:
            return Explanation(_text(e) or code, code)
        names = {cls.__name__ for cls in type(e).__mro__}
        if names & set(_TIMEOUTS):
            return Explanation(TIMED_OUT, type(e).__name__)
        if names & set(_UNREACHABLE) or isinstance(e, socket.gaierror):
            return Explanation(UNREACHABLE, type(e).__name__)
        if isinstance(e, StorageConfigError):
            return Explanation(f"settings: {e}", "StorageConfigError")
        if isinstance(e, PermissionError):
            return Explanation(f"no permission: {_text(e)}", "PermissionError")
    return Explanation(_text(exc) or type(exc).__name__)


def _text(exc: BaseException) -> str:
    """The exception's message on one line, at most 500 characters."""
    text = " / ".join(line.strip() for line in str(exc).strip().splitlines() if line.strip())
    return text if len(text) <= 500 else text[:499] + "…"


# --------------------------------------------------------------------------------------------------
# Scrubbing what gets written down
# --------------------------------------------------------------------------------------------------

_SECRET_NAME = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|ACCESS_KEY|KEY_ID|CREDENTIAL|PRIVATE)", re.IGNORECASE)
_URL_USERINFO = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s@]+@", re.IGNORECASE)
MAX_TEXT = 2000


def is_credential_name(name: str) -> bool:
    """A variable whose value must never be shown or stored (keys, secrets, passwords, tokens)."""
    return bool(_SECRET_NAME.search(name))


def scrub(text: str | None, env: Mapping[str, Any] | None = None, extra: Iterable[str] = ()) -> str | None:
    """``text`` without credentials: user info in URLs, and the value of every credential-like variable in
    ``env`` (plus ``extra`` values) wherever it appears; cut to MAX_TEXT characters."""
    if not text:
        return text
    text = _URL_USERINFO.sub(r"\1****@", text)
    values = {str(v) for k, v in (env or {}).items() if v and is_credential_name(str(k))} | {str(v) for v in extra if v}
    for value in sorted(values, key=len, reverse=True):
        if len(value) >= 4:
            text = text.replace(value, "****")
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


# --------------------------------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------------------------------


@dataclass
class CheckStep:
    name: str
    """``list``, ``put``, ``get`` or ``delete``."""
    ok: bool
    ms: float
    error: str | None = None
    code: str | None = None


@dataclass
class CheckResult:
    ok: bool
    key: str
    location: str | None = None
    checked_at: str = ""
    steps: list[CheckStep] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def lines(self) -> list[str]:
        """One line per step, for a terminal: ``put   ok      84 ms`` / ``put   FAILED  91 ms  <why>``."""
        out = []
        for s in self.steps:
            why = f"  {s.error}" + (f" ({s.code})" if s.code else "") if s.error else ""
            out.append(f"{s.name:<6} {'ok' if s.ok else 'FAILED':<6} {s.ms:6.0f} ms{why}")
        return out


def healthcheck_key() -> str:
    return f"{HEALTHCHECK_PREFIX}{uuid.uuid4()}.txt"


def _payload(key: str) -> bytes:
    return f"Marvin storage health check {datetime.now(UTC).isoformat()} {key}\n".encode()


class _Steps:
    def __init__(self) -> None:
        self.steps: list[CheckStep] = []

    def run(self, name: str, fn: Callable[[], Any]) -> tuple[bool, Any]:
        started = time.perf_counter()
        try:
            value = fn()
        except Exception as exc:  # every failure is reported as the step's result, never raised
            why = explain(exc)
            self.steps.append(CheckStep(name, False, (time.perf_counter() - started) * 1000, why.message, why.code))
            return False, None
        self.steps.append(CheckStep(name, True, (time.perf_counter() - started) * 1000))
        return True, value

    def fail(self, name: str, message: str) -> None:
        self.steps.append(CheckStep(name, False, 0.0, message))


def check_provider(provider: StorageProvider, location: str | None = None) -> CheckResult:
    """List, put, get and delete a tiny object through an asset storage provider. The delete always runs
    once the put was attempted, so a failed get never leaves the object behind."""
    key = healthcheck_key()
    data = _payload(key)
    steps = _Steps()

    def _list() -> None:
        for _ in zip(range(10), provider.iter_keys(HEALTHCHECK_PREFIX), strict=False):  # one page is enough
            pass

    def _get() -> None:
        handle = provider.get(key)
        try:
            got = handle.read()
        finally:
            handle.close()
        if got != data:
            raise ValueError(f"read back {len(got)} bytes that differ from the {len(data)} written")

    steps.run("list", _list)
    put_ok, _ = steps.run("put", lambda: provider.put(key, io.BytesIO(data), "text/plain", {}))
    if put_ok:
        steps.run("get", _get)
    else:
        steps.fail("get", "skipped: the put failed")
    steps.run("delete", lambda: provider.delete(key))
    return _result(key, location, steps)


def check_target(target: BackupTarget) -> CheckResult:
    """The same check through a backup target: list, put_file, get (sha256 compared) and delete."""
    key = healthcheck_key()
    data = _payload(key)
    digest = hashlib.sha256(data).hexdigest()
    steps = _Steps()
    with tempfile.TemporaryDirectory(prefix="marvin-healthcheck-") as tmp:
        src, dest = Path(tmp) / "out.txt", Path(tmp) / "in.txt"
        src.write_bytes(data)

        def _get() -> None:
            target.get(key, dest)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                raise ValueError("read back bytes that differ from the ones written")

        steps.run("list", lambda: target.list(HEALTHCHECK_PREFIX))
        put_ok, _ = steps.run("put", lambda: target.put_file(key, src, {"sha256": digest}, "text/plain"))
        if put_ok:
            steps.run("get", _get)
        else:
            steps.fail("get", "skipped: the put failed")
        steps.run("delete", lambda: target.delete([key]))
    try:
        location = target.describe()
    except Exception:
        location = None
    return _result(key, location, steps)


def _result(key: str, location: str | None, steps: _Steps) -> CheckResult:
    return CheckResult(
        ok=all(s.ok for s in steps.steps),
        key=key,
        location=location,
        checked_at=datetime.now(UTC).isoformat(),
        steps=steps.steps,
    )
