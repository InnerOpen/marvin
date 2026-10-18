"""The upload link's page and endpoints, at the API host's root like the OAuth endpoints (404 while the platform switch
is off). See services/mcp_remote/uploads.py for what a link is and how it is held.

- GET  /mcp/upload        the page (the secret is in its #fragment, which never reaches the server)
- POST /mcp/upload/check  {token} → who and where, nothing consumed
- POST /mcp/upload        multipart: token + file → the new asset

No cookie is read or set and the secret travels only in request bodies, so nothing is logged with it and a cross-site
request has nothing to ride on. Every answer is no-store.
"""

from __future__ import annotations

import json
import secrets

import anyio
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.services.mcp_remote import limits, upload_page, uploads
from marvin.services.mcp_remote.policy import issuer

logger = get_logger(__name__)
router = APIRouter()
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _on(request: Request) -> None:
    from marvin.services.platform_policy import remote_mcp

    if not (remote_mcp().enabled and issuer(request)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _ip(request: Request) -> str:
    from marvin.services.security.login_throttle import login_client_ip

    return login_client_ip(request)


def _refused(e: uploads.UploadError) -> JSONResponse:
    logger.warning("MCP upload link refused: %s (%d)", e.message, e.status)  # the message never carries the secret
    return JSONResponse({"error": e.message}, status_code=e.status, headers=NO_STORE)


def _limited(request: Request) -> JSONResponse | None:
    ip = _ip(request)
    try:
        limits.check("upload_try", ip)
    except limits.RateLimited as e:
        return JSONResponse(
            {"error": "Too many attempts; wait a few minutes."}, status_code=429, headers={**NO_STORE, "Retry-After": str(e.retry_after)}
        )
    limits.hit("upload_try", ip)
    return None


@router.get("/mcp/upload", include_in_schema=False)
def page(request: Request) -> Response:
    _on(request)
    nonce = secrets.token_urlsafe(16)
    csp = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src blob:; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return HTMLResponse(
        upload_page.render(nonce), headers={**NO_STORE, "Content-Security-Policy": csp, "X-Frame-Options": "DENY", "X-Robots-Tag": "noindex"}
    )


@router.post("/mcp/upload/check", include_in_schema=False)
async def check(request: Request) -> Response:
    _on(request)
    if (limited := _limited(request)) is not None:
        return limited
    try:
        body = await request.json()
        token = str(body.get("token") or "") if isinstance(body, dict) else ""
    except (json.JSONDecodeError, UnicodeDecodeError):
        token = ""

    def run() -> dict:
        with session_context() as session:
            return uploads.describe(session, token)

    try:
        return JSONResponse(await anyio.to_thread.run_sync(run), headers=NO_STORE)
    except uploads.UploadError as e:
        return _refused(e)


@router.post("/mcp/upload", include_in_schema=False)
async def upload(request: Request, background: BackgroundTasks) -> Response:
    _on(request)
    if (limited := _limited(request)) is not None:
        return limited
    cap = uploads.size_cap()
    declared = request.headers.get("content-length")
    if not declared or not declared.isdigit():
        return _refused(uploads.UploadError("The upload needs a Content-Length.", 411))
    if int(declared) > cap + uploads.MULTIPART_OVERHEAD:  # refused before the body is read or spooled
        return _refused(uploads.UploadError(f"The file is bigger than {cap // (1024 * 1024)} MB.", 413))
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 — not a multipart form
        return _refused(uploads.UploadError("That wasn't a file upload.", 400))
    token, file = form.get("token"), form.get("file")
    if not isinstance(token, str) or file is None or isinstance(file, str):
        return _refused(uploads.UploadError("Send the link's token and a file.", 400))

    def run() -> dict:
        with session_context() as session:
            return uploads.store(session, token, filename=file.filename, file=file.file, bg_tasks=background)

    try:
        out = await anyio.to_thread.run_sync(run)  # the database and the storage provider are synchronous
    except uploads.UploadError as e:
        return _refused(e)
    finally:
        await form.close()
    return JSONResponse(out, status_code=201, headers=NO_STORE, background=background)  # the event goes out after the reply
