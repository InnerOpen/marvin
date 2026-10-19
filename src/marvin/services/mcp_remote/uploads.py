"""Photo upload links for MCP connections: how a photo in a chat reaches Marvin.

claude.ai and ChatGPT don't pass a chat attachment's bytes to a tool, so a connection asks for a link (`upload_link`),
the assistant gives it to the user, and the user sends the file from a browser page (`/mcp/upload`, served by the API
host: no sign-in needed, none possible from a chat's in-app browser). The file becomes an ordinary library asset
through the same service as the Assets page (`AssetStorageService`: the workspace's own bucket when it keeps one, the
detected type and size checked against ASSET_ALLOWED_MIME_TYPES / ASSET_MAX_FILE_SIZE). The assistant then asks
`check_upload` with the link's id and gets the asset.

The link is a bearer capability, so it is kept narrow:
- 256 random bits behind a ``marvin_ul_`` prefix, stored as SHA-256 only; the URL carries it in the ``#fragment``, which
  a browser never sends, so no server, proxy or access log holds it;
- 15 minutes, one use (claimed by one conditional UPDATE: two uploads can't both win), and bound to the grant that asked,
  its user and its workspace; a refused file (wrong type, too big) gives the attempt back, three refusals spend it;
- checked again when used: the connection must be unrevoked and write-scoped, the user still a member with the role
  `import_asset` needs, the workspace still allowing MCP hosts, and Marvin's matrix still allowing `import_asset`;
- no cookie is read or set, so there is nothing for a cross-site request to ride on (CSRF), and the secret is in the
  request body, never a query string.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa

from marvin.core.root_logger import get_logger
from marvin.db.locking import begin_write

logger = get_logger(__name__)

PREFIX = "marvin_ul_"
LINK_MINUTES = 15
MAX_ATTEMPTS = 3  # refused uploads before the link is spent
MAX_LIVE_PER_CONNECTION = 5  # unused, unexpired links one connection may hold
MAX_BYTES = 25 * 1024 * 1024  # a phone photo; the platform's ASSET_MAX_FILE_SIZE applies too, if lower
MULTIPART_OVERHEAD = 64 * 1024  # what a form adds around the file
KEEP_DAYS = 1  # how long a spent or expired link stays (for `check_upload`) before the purge takes it
TOOL = "import_asset"  # the tool whose rules a link follows: same role floor, matrix and scope


class UploadError(Exception):
    """A refusal with a message that is safe to show to whoever holds the link, and the HTTP status for it."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def size_cap() -> int:
    from marvin.core.config import get_app_settings

    platform = get_app_settings().ASSET_MAX_FILE_SIZE
    return min(MAX_BYTES, platform) if platform else MAX_BYTES


def refusal(session, user, group_id, *, can_write: bool) -> str | None:
    """Why this user/connection may not upload into the workspace, or None. Same rules as `import_asset` for a remote
    connection: write scope, its role floor (Editor), and Marvin's permission matrix."""
    from marvin.services.ai.agents import unattended_refusal
    from marvin.services.ai.tool_gateway import READ_ONLY_REFUSAL, router_agent
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import user_role
    from marvin.services.ai.tools.categories import category_of

    if not can_write:
        return READ_ONLY_REFUSAL
    spec = get_tool(TOOL)
    role = user_role(user, group_id)
    if role < spec.min_role:
        return "Uploading needs the Editor role in this workspace."
    blocked = unattended_refusal(router_agent(session, group_id), spec.name, category_of(spec.name, read_only=spec.read_only), role)
    return None if blocked is None else str(blocked.get("error") or "Marvin's permissions don't allow uploads here.")


def create_link(session, conn, user, *, name: str | None, alt_text: str | None, ip: str | None) -> tuple[object, str]:
    """A new link for the connection (`conn`: grant, user and workspace ids, can_write). Returns (row, secret): the secret
    is shown once. Raises UploadError."""
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    why = refusal(session, user, conn.group_id, can_write=conn.can_write)
    if why:
        raise UploadError(why, 403)
    live = (
        session.query(sa.func.count(McpUploadLinkModel.id))
        .filter(McpUploadLinkModel.grant_id == conn.grant_id, McpUploadLinkModel.used_at.is_(None), McpUploadLinkModel.expires_at > _now())
        .scalar()
    )
    if live >= MAX_LIVE_PER_CONNECTION:
        raise UploadError("There are already several unused upload links: use one, or wait up to 15 minutes for them to expire.", 429)
    secret = f"{PREFIX}{secrets.token_urlsafe(32)}"
    row = McpUploadLinkModel(
        session=session,
        token_lookup=_hash(secret),
        grant_id=conn.grant_id,
        user_id=conn.user_id,
        group_id=conn.group_id,
        name=" ".join((name or "").split())[:200] or None,
        alt_text=" ".join((alt_text or "").split())[:1000] or None,
        expires_at=_now() + timedelta(minutes=LINK_MINUTES),
        created_ip=(ip or "")[:64] or None,
    )
    session.add(row)
    session.commit()
    return row, secret


def page_url(issuer_url: str, secret: str) -> str:
    return f"{issuer_url}/mcp/upload#{secret}"


def _by_secret(session, secret: str):
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    if not secret or not secret.startswith(PREFIX) or len(secret) > 200:
        return None
    return session.query(McpUploadLinkModel).filter_by(token_lookup=_hash(secret)).one_or_none()


@dataclass
class Usable:
    link: object
    grant: object
    user: object
    group: object


def _usable(session, secret: str, *, claimed: bool = False) -> Usable:
    """The link's grant, user and workspace, if it can still be used. Raises UploadError. `claimed`: the caller holds
    the single use already, so a set `used_at` is its own."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.oauth import OAuthGrantModel
    from marvin.db.models.users.users import Users
    from marvin.services.mcp_remote import oauth as oauth_svc

    link = _by_secret(session, secret)
    if link is None:
        raise UploadError("This upload link isn't valid. Ask the assistant for a new one.", 404)
    if link.used_at is not None and not claimed:
        raise UploadError("This upload link was already used. Ask the assistant for a new one.", 410)
    if _aware(link.expires_at) < _now():
        raise UploadError("This upload link has expired. Ask the assistant for a new one.", 410)
    grant = session.get(OAuthGrantModel, link.grant_id)
    if grant is None or grant.revoked_at is not None:
        raise UploadError("The assistant's connection to Marvin was ended, so this link no longer works.", 403)
    user = session.get(Users, link.user_id)
    group = session.get(Groups, link.group_id)
    if user is None or group is None or oauth_svc.member_role(session, link.user_id, link.group_id) <= 0:
        raise UploadError("This link's user is no longer a member of the workspace.", 403)
    if not oauth_svc._mcp_allowed(session, link.group_id):
        raise UploadError("This workspace has turned off AI from external MCP hosts.", 403)
    from marvin.services.mcp_remote.policy import SCOPE_WRITE

    why = refusal(session, user, link.group_id, can_write=SCOPE_WRITE in grant.scope.split())
    if why:
        raise UploadError(why, 403)
    return Usable(link, grant, user, group)


def describe(session, secret: str) -> dict:
    """What the upload page shows before the file is chosen (nothing is consumed)."""
    ok = _usable(session, secret)
    return {
        "workspace": ok.group.name,
        "user": ok.user.full_name or ok.user.username,
        "app": ok.grant.client_name_snapshot,
        "name": ok.link.name,
        "expiresAt": _aware(ok.link.expires_at).isoformat(),
        "maxBytes": size_cap(),
    }


def _claim(session, link) -> bool:
    """Take the link's one use. True for exactly one caller, however many race."""
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    now = _now()
    begin_write(session)  # SQLite: the one use is a compare-and-set write; take the lock first so a rival waits for it
    taken = session.execute(
        sa.update(McpUploadLinkModel)
        .where(McpUploadLinkModel.id == link.id, McpUploadLinkModel.used_at.is_(None), McpUploadLinkModel.expires_at > now)
        .values(used_at=now)
    ).rowcount
    session.commit()
    return taken == 1


def _give_back(session, link, *, count: bool) -> None:
    """The upload was refused: free the link for another try (a few times), or spend it for good."""
    session.refresh(link)
    link.attempts = (link.attempts or 0) + (1 if count else 0)
    link.used_at = None if link.attempts < MAX_ATTEMPTS else _now()
    session.commit()


# What the bytes are, not what the name or the browser says: Pillow's format → the extension the stored file gets (the
# platform's type detection goes by the extension). A link is for photos, so anything else is refused, SVG and HTML included.
PHOTO_FORMATS = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}  # MPO: an iPhone's JPEG
MAX_PIXELS = 100_000_000


def sniff_photo(data: bytes) -> str:
    """The extension for a photo's real format, or UploadError(415) when the bytes aren't a JPEG, PNG, WebP or GIF."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            ext = PHOTO_FORMATS.get(img.format or "")
            pixels = img.width * img.height
    except Exception:  # noqa: BLE001 — not an image, or a broken one
        ext, pixels = None, 0
    if ext is None:
        raise UploadError("That isn't a photo Marvin can take here (JPEG, PNG, WebP or GIF).", 415)
    if pixels > MAX_PIXELS:
        raise UploadError("That picture is too large (over 100 megapixels).", 413)
    return ext


_BAD = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_filename(raw: str | None) -> str:
    name = _BAD.sub("_", os.path.basename((raw or "").replace("\\", "/"))).strip(" .")[:120]
    return name or "photo.jpg"


def store(session, secret: str, *, filename: str | None, file, bg_tasks=None) -> dict:
    """Take the link's one use and store the file as a library asset. Returns the asset's details. Raises UploadError.
    `bg_tasks` (FastAPI's) defers `asset_uploaded`'s listeners until the response is sent, as the Assets page does."""
    from slugify import slugify

    from marvin.repos.all_repositories import get_repositories
    from marvin.schemas.platform.assets import AssetUploadRequest
    from marvin.services.assets.asset_storage_service import AssetRejected, AssetStorageService
    from marvin.services.storage.workspace import WorkspaceStorageUnavailable

    ok = _usable(session, secret)
    link, user, group = ok.link, ok.user, ok.group
    if not _claim(session, link):
        raise UploadError("This upload link was already used (or has just expired). Ask the assistant for a new one.", 410)
    cap = size_cap()
    try:
        data = file.read(cap + 1)
        if not data:
            raise UploadError("The file is empty.", 400)
        if len(data) > cap:
            raise UploadError(f"The file is bigger than {cap // (1024 * 1024)} MB.", 413)
        stem = os.path.splitext(_safe_filename(filename))[0] or "photo"
        safe = f"{stem}.{sniff_photo(data)}"  # named by what it is, whatever the browser called it
        name = link.name or stem
        upload = SimpleNamespace(filename=safe, file=io.BytesIO(data))
        request = AssetUploadRequest(slug=f"{slugify(name) or 'photo'}-{uuid.uuid4().hex[:6]}", name=name, alt_text=link.alt_text)
        asset = AssetStorageService.for_workspace(get_repositories(session, group_id=link.group_id)).upload_asset(
            upload_file=upload, upload_request=request, group_id=link.group_id, user_id=user.id
        )
    except UploadError:
        _give_back(session, link, count=True)
        raise
    except AssetRejected as e:
        _give_back(session, link, count=True)
        raise UploadError(str(e), e.status_code) from None
    except WorkspaceStorageUnavailable as e:
        _give_back(session, link, count=False)
        raise UploadError(str(e) or "This workspace's storage can't take uploads right now.", 503) from None
    except Exception:
        session.rollback()
        logger.exception("MCP upload link: storing the file failed")
        _give_back(session, link, count=True)
        raise UploadError("Marvin couldn't store that file. Try another, or ask the assistant for a new link.", 500) from None
    link.asset_id = asset.id
    session.commit()
    _announce(asset, group, user, bg_tasks)
    logger.info("MCP upload link: asset stored for grant %s (%s, %d bytes)", link.grant_id, asset.mime_type, asset.file_size)
    return {
        "assetId": str(asset.id),
        "slug": asset.slug,
        "name": asset.name,
        "mimeType": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "size": asset.file_size,
    }


def _announce(asset, group, user, bg_tasks) -> None:
    """`asset_uploaded`, as the Assets page's upload sends it."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAssetData, EventTypes

    EventBusService(bg_tasks=bg_tasks).dispatch(
        integration_id="asset_management",
        group_id=group.id,
        event_type=EventTypes.asset_uploaded,
        document_data=EventAssetData.from_schema(
            asset, workspace_id=group.id, workspace_name=group.name, uploader_id=user.id, uploader_name=user.full_name
        ),
        message=f"Asset {asset.name} uploaded",
    )


def status_of(session, conn, link_id: str) -> dict:
    """`check_upload`: where a link the connection asked for stands. Another connection's link is 'unknown'."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    try:
        key = uuid.UUID(str(link_id).strip())
    except ValueError:
        return {"error": "link_id is the linkId upload_link returned"}
    link = session.get(McpUploadLinkModel, key)
    if link is None or str(link.grant_id) != str(conn.grant_id):
        return {"error": "no such upload link for this connection"}
    asset = session.get(Assets, link.asset_id) if link.asset_id else None
    if asset is not None and asset.group_id == link.group_id and asset.trashed_at is None:
        return {"status": "uploaded", "asset": asset}
    if asset is not None:
        return {"status": "uploaded", "asset": None, "note": "the uploaded asset was since moved to the Trash"}
    if link.used_at is not None and link.attempts < MAX_ATTEMPTS:
        return {"status": "uploading"}  # claimed: the file is on its way in
    if link.used_at is not None:
        return {"status": "failed", "note": "the file was refused too many times; ask for a new link"}
    if _aware(link.expires_at) < _now():
        return {"status": "expired"}
    return {"status": "waiting", "expiresAt": _aware(link.expires_at).isoformat()}


def purge(session, now: datetime) -> int:
    """Delete links a day past their expiry (the table's retention rule)."""
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    return session.query(McpUploadLinkModel).filter(McpUploadLinkModel.expires_at < now - timedelta(days=KEEP_DAYS)).delete(synchronize_session=False)
