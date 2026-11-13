"""Asset routes."""

import json
from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import UUID4

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_editor, require_workspace_role
from marvin.routes._base.paging import paged
from marvin.schemas.platform import AssetRead, AssetUpdate, AssetUploadRequest
from marvin.schemas.platform.assets import AssetUsage, TypeCount
from marvin.services import trash
from marvin.services.assets import scope
from marvin.services.assets import usage as asset_usage
from marvin.services.assets.asset_storage_service import AssetRejected, AssetStorageService
from marvin.services.assets.scope import ASK, LIBRARY, SCOPES, upload_scope
from marvin.services.event_bus_service.event_types import EventAssetData, EventTypes
from marvin.services.storage import StorageConfigError
from marvin.services.storage.keys import content_disposition
from marvin.services.storage.provider_factory import provider_for, public_url_for

MAX_CONTENT_BYTES = 50_000_000  # what /content will carry

router = APIRouter(prefix="/assets")

SORTS = {"name": ("name", False), "newest": ("created_at", True), "oldest": ("created_at", False), "largest": ("file_size", True)}


def unsearchable_image():
    """A picture search and the assistants can't find: an image with no alt text and no description (as the library
    page's ``isUnsearchableImage`` says)."""
    import sqlalchemy as sa

    from marvin.db.models.platform import Assets

    blank = lambda column: sa.func.coalesce(sa.func.trim(column), "") == ""  # noqa: E731
    return sa.and_(Assets.mime_type.like("image/%"), blank(Assets.alt_text), blank(Assets.description))


def library_page(
    session, group_id, spec: dict, sort: str, response: Response, *, limit: int | None = None, offset: int = 0, searchable: bool | None = None
) -> list[AssetRead]:
    """The library's assets matching ``spec`` (services/item_query.py), sorted, each with its versions count; with
    ``spec["trashed"]``, the Trash's (Ask files too: the Trash is one place for every deleted asset). A filter that
    can't match (an unknown tag or collection) is a 422 saying which. ``limit``/``offset`` cut one page in SQL, and
    ``response`` gets the total in ``X-Total-Count``; the page's tags and versions counts come in one query each."""
    import sqlalchemy as sa
    from sqlalchemy.orm import selectinload

    from marvin.db.models.platform import Assets
    from marvin.services import item_query

    query, note = item_query.build(session, group_id, item_query.ASSET, spec, library_only=not spec.get("trashed"))
    if note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=note)
    if searchable is not None:
        query = query.filter(~unsearchable_image() if searchable else unsearchable_image())
    column, descending = SORTS[sort]
    order = getattr(Assets, column)
    page = paged(query.order_by(order.desc() if descending else order, Assets.name, Assets.id), response, limit, offset)
    rows = page.options(selectinload(Assets.tags)).all()
    if not rows or spec.get("trashed"):  # a trashed original's versions aren't listed under it: no count, no link
        return [AssetRead.model_validate(r) for r in rows]
    counts = dict(
        session.query(Assets.source_asset_id, sa.func.count(Assets.id))
        .filter(
            Assets.group_id == group_id,
            Assets.source_asset_id.in_([r.id for r in rows]),
            Assets.trashed_at.is_(None),
            Assets.scope == "library",
        )
        .group_by(Assets.source_asset_id)
        .all()
    )
    return [AssetRead.model_validate(r).model_copy(update={"versions_count": counts.get(r.id, 0)}) for r in rows]


@controller(router)
class AssetsController(BaseUserController):
    """Authenticated CRUD routes for assets with file upload support. Any member reads; AUTHORs and
    above upload; editing, deleting and accepting AI suggestions on an asset is EDITOR and above (an
    asset has no owner, so an AUTHOR can't be limited to their own).

    Delete moves an asset to the Trash (services/trash.py): its file stays in storage, it leaves the list,
    and fetching it by id shows its `trashed_at`. Only a trashed asset can be deleted forever."""

    @router.get("", response_model=list[AssetRead], summary="List Assets")
    def list_assets(
        self,
        response: Response,
        scope: str = Query(LIBRARY, description="'library' (the Assets library) or 'ask' (files attached to chat questions)"),
        q: str | None = Query(None, description="Name, slug or filename contains"),
        asset_type: list[str] = Query(default_factory=list, description="image, svg, document, video, audio, archive, other"),
        origin: list[str] = Query(default_factory=list, description="upload, derived (made from another asset), generated"),
        decision: str | None = Query(None, description="what an approval that showed the picture decided: approved, denied, expired, stale, or none"),
        tag: list[str] = Query(default_factory=list, description="Carrying any of these tags (slug or name)"),
        collection: str | None = Query(None, description="In this collection (slug or name)"),
        unattached: bool | None = Query(None, description="true: on no entry; false: on at least one"),
        versions: bool | None = Query(None, description="false: fold versions under their original; true: only versions"),
        source: str | None = Query(None, description="The versions made from this asset (id or slug)"),
        searchable: bool | None = Query(None, description="false: only pictures search can't find (no alt text or description); true: the rest"),
        trashed: bool = Query(False, description="true: the Trash's assets instead (Ask files too), with the same filters"),
        sort: Literal["name", "newest", "oldest", "largest"] = Query("name"),
        limit: int | None = Query(None, ge=1, description="At most this many (default: all of them)"),
        offset: int = Query(0, ge=0, description="Skip this many first (with `limit`, one page)"),
    ) -> list[AssetRead]:
        """The library's assets (filtered as the workflow and agent asset queries are), each with how many versions
        were made from it; with `scope=ask`, the Ask files, newest first. Never those in the Trash, unless `trashed`
        asks for them. `limit`/`offset` page it; the `X-Total-Count` header says how many match in all."""
        from sqlalchemy.orm import selectinload

        from marvin.db.models.platform import Assets

        if scope not in SCOPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"scope must be one of: {', '.join(SCOPES)}")
        if scope == ASK:
            query = self.session.query(Assets).filter(Assets.group_id == self.group_id, Assets.trashed_at.is_(None), Assets.scope == ASK)
            page = paged(query.order_by(Assets.created_at.desc(), Assets.id.desc()), response, limit, offset)
            return [AssetRead.model_validate(a) for a in page.options(selectinload(Assets.tags)).all()]
        spec = {
            "text": q,
            "asset_types": asset_type,
            "origins": origin,
            "decision": decision,
            "tags": tag,
            "collection": collection,
            "unattached": unattached,
            "versions": versions,
            "source": source,
            "trashed": trashed or None,
        }
        spec = {k: v for k, v in spec.items() if v not in (None, "", [])}
        return library_page(self.session, self.group_id, spec, sort, response, limit=limit, offset=offset, searchable=searchable)

    @router.post("/upload", response_model=AssetRead, status_code=status.HTTP_201_CREATED, summary="Upload Asset")
    async def upload_asset(
        self,
        file: UploadFile = File(...),
        slug: str = Form(...),
        name: str = Form(...),
        alt_text: str | None = Form(None),
        description: str | None = Form(None),
        metadata: str | None = Form(None),
    ) -> AssetRead:
        """
        Upload a new asset file.

        Accepts multipart/form-data with:
        - file: The binary file
        - slug: URL-friendly identifier
        - name: Display name
        - alt_text: Accessibility text (optional)
        - description: Description (optional)
        - metadata: JSON string of custom metadata (optional)

        Server automatically extracts:
        - MIME type, file size, checksum
        - Image dimensions (width, height, orientation)
        - Asset type classification

        Refused when bigger than ASSET_MAX_FILE_SIZE (413) or of a type ASSET_ALLOWED_MIME_TYPES leaves out (415).
        """
        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        # Parse metadata JSON if provided
        metadata_dict = None
        if metadata:
            try:
                metadata_dict = json.loads(metadata)
            except json.JSONDecodeError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON in metadata field.") from None

        # Create upload request
        upload_request = AssetUploadRequest(
            slug=slug,
            name=name,
            alt_text=alt_text,
            description=description,
            metadata_json=metadata_dict,
            scope=upload_scope(metadata_dict),
        )

        # Get storage provider and create service
        asset_service = AssetStorageService.for_workspace(self.repos)

        # Upload through service
        try:
            asset = asset_service.upload_asset(
                upload_file=file,
                upload_request=upload_request,
                group_id=self.group_id,
                user_id=self.user.id,
            )
        except AssetRejected as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e

        # An Ask file isn't a new library asset: workflows and webhooks on `asset_uploaded` hear of it when it's
        # moved to the library (move_to_library), not while it is a chat attachment.
        if asset.scope == ASK:
            return asset
        # Emit event
        self.event_bus.dispatch(
            integration_id="asset_management",
            group_id=self.group_id,
            event_type=EventTypes.asset_uploaded,
            document_data=EventAssetData.from_schema(
                asset,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
                uploader_id=self.user.id if self.user else None,
                uploader_name=self.user.full_name if self.user else None,
            ),
            message=f"Asset {asset.name} uploaded",
        )

        return asset

    @router.get("/types", response_model=list[TypeCount], summary="Asset types in use")
    def asset_types(self) -> list[TypeCount]:
        """Each asset type in the library and how many assets it has (most first) — never the Trash or Ask files."""
        from sqlalchemy import func

        from marvin.db.models.platform.assets import Assets

        rows = (
            self.session.query(Assets.asset_type, func.count(Assets.id))
            .filter(Assets.group_id == self.group_id, Assets.trashed_at.is_(None), Assets.scope == LIBRARY)
            .group_by(Assets.asset_type)
            .order_by(func.count(Assets.id).desc(), Assets.asset_type)
            .all()
        )
        return [TypeCount(type=kind, count=n) for kind, n in rows]

    @router.get("/{item_id}/usage", response_model=list[AssetUsage], summary="Where an asset is used")
    def get_asset_usage(self, item_id: UUID4) -> list[AssetUsage]:
        """The entries this asset is attached to, and the role each attachment carries (the asset itself has no role). Entries in the Trash and
        internal ones are left out."""
        if not self.repos.assets.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        return [AssetUsage(**row) for row in asset_usage.usage(self.session, self.group_id, item_id)]

    @router.get("/{item_id}", response_model=AssetRead, summary="Get Asset")
    def get_asset(self, item_id: UUID4) -> AssetRead:
        asset = self.repos.assets.get_one(item_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        return asset

    @router.patch("/{item_id}", response_model=AssetRead, summary="Update Asset Metadata")
    def update_asset(self, item_id: UUID4, data: AssetUpdate) -> AssetRead:
        """
        Update asset metadata (slug, name, alt text, description, metadata).

        Note: Technical metadata (MIME type, dimensions, checksum, etc) cannot be changed.
        """
        require_workspace_editor(self.user, self.group_id)
        current = self.repos.assets.get_one(item_id)
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        if current.trashed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This asset is in the Trash. Restore it before editing it.")

        # Use exclude_none=False to allow explicit null values to clear fields
        # exclude_unset=True only excludes fields not sent in the request
        updated_asset = self.repos.assets.update(item_id, data.model_dump(exclude_unset=True, exclude_none=False))

        # Emit event
        self.event_bus.dispatch(
            integration_id="asset_management",
            group_id=self.group_id,
            event_type=EventTypes.asset_updated,
            document_data=EventAssetData.from_schema(
                AssetRead.model_validate(updated_asset),
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
                uploader_id=self.user.id if self.user else None,
                uploader_name=self.user.full_name if self.user else None,
            ),
            message=f"Asset {updated_asset.name} updated",
        )

        return updated_asset

    @router.post("/{item_id}/apply-suggestion", response_model=AssetRead, summary="Apply AI Suggestion")
    def apply_suggestion(self, item_id: UUID4) -> AssetRead:
        """Apply the asset's staged AI suggestion (suggestion_json) and clear it."""
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.assets.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        return self.repos.assets.apply_suggestion(item_id)

    @router.post("/{item_id}/reject-suggestion", response_model=AssetRead, summary="Reject AI Suggestion")
    def reject_suggestion(self, item_id: UUID4) -> AssetRead:
        """Discard the asset's staged AI suggestion without applying it."""
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.assets.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        return self.repos.assets.clear_suggestion(item_id)

    @router.delete("/{item_id}", summary="Move Asset to Trash (or delete a trashed asset forever)")
    def delete_asset(self, item_id: UUID4, permanent: bool = False) -> dict:
        """Move the asset to the Trash (`asset_trashed`; its file stays in storage). With `permanent=true`,
        delete an asset already in the Trash forever, file included (`asset_deleted`); any other asset gets a 409."""
        require_workspace_editor(self.user, self.group_id)
        asset = self.repos.assets.get_one(item_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        if permanent:
            if asset.trashed_at is None:
                detail = "Only an asset in the Trash can be deleted forever. Move it to the Trash first."
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
            if not trash.delete_forever(self.session, self.group_id, trash.ASSET, [item_id], actor_id=self.user.id, event_bus=self.event_bus):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
            return {"status": "ok", "message": "Asset deleted forever", "deleted": True}
        trash.trash(self.session, self.group_id, trash.ASSET, item_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "message": "Asset moved to the Trash", "trashed": True}

    @router.post("/{item_id}/restore", response_model=AssetRead, summary="Restore Asset from Trash")
    def restore_asset(self, item_id: UUID4) -> AssetRead:
        """Take an asset out of the Trash (`asset_restored`)."""
        require_workspace_editor(self.user, self.group_id)
        asset = self.repos.assets.get_one(item_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        if asset.trashed_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This asset is not in the Trash.")
        trash.restore(self.session, self.group_id, trash.ASSET, item_id, actor_id=self.user.id, event_bus=self.event_bus)
        return self.repos.assets.get_one(item_id)

    @router.post("/{item_id}/move-to-library", response_model=AssetRead, summary="Move an Ask File to the Assets Library")
    def move_to_library(self, item_id: UUID4) -> AssetRead:
        """File an Ask file (a chat attachment) in the Assets library. It then lists, counts and publishes like any
        asset, and `asset_uploaded` fires for it. AUTHOR and above, like uploading straight to the library."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        asset = self.repos.assets.get_one(item_id)
        if not asset or asset.trashed_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        if asset.scope != ASK:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This asset is already in the library.")
        scope.move_to_library(self.session, self.group_id, [item_id], actor_id=self.user.id, event_bus=self.event_bus)
        return self.repos.assets.get_one(item_id)

    @router.get("/{item_id}/file", summary="Serve Asset File")
    def serve_asset_file(self, item_id: UUID4):
        """
        Serve the actual asset file content directly.

        For local storage, serves the file from disk.
        For S3 storage, redirects to the public URL or signed URL.
        """
        from pathlib import Path

        from fastapi.responses import FileResponse, RedirectResponse

        asset = self.repos.assets.get_one(item_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")

        from marvin.services.storage.local_provider import LocalStorageProvider

        # The provider the row lives in, whatever STORAGE_PROVIDER says now: rows on different
        # providers are served side by side.
        try:
            storage_provider = provider_for(asset)
        except StorageConfigError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Asset storage unavailable: {e}") from e

        # For local storage, serve file directly
        if isinstance(storage_provider, LocalStorageProvider):
            file_path = Path(storage_provider.root) / asset.storage_key

            if not file_path.exists():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found on disk.")

            # Inline, under the name it was uploaded with (keys carry no filename).
            disposition = content_disposition(asset.original_filename)
            return FileResponse(
                path=str(file_path),
                media_type=asset.mime_type or "application/octet-stream",
                headers={"Content-Disposition": disposition} if disposition else None,
            )

        # For remote providers, redirect to the file's URL (the workspace's public domain when it has
        # one); the object carries its Content-Disposition from the upload.
        return RedirectResponse(url=public_url_for(asset.storage_provider, asset.storage_key, self.group_id, provider=storage_provider))

    @router.get("/{item_id}/content", summary="Serve Asset Bytes (never redirects)")
    def serve_asset_content(self, item_id: UUID4):
        """
        The file's bytes, from this API in every case.

        ``/file`` redirects to the storage domain for remote storage, and a page that has to read the picture itself (the
        cropper behind Edit picture) can't follow that: the browser blocks the cross-origin read when that domain sends
        no CORS headers. So for a remote file the API fetches it from its storage URL and hands the bytes on. Up to
        ``MAX_CONTENT_BYTES``: larger files answer 413 (this is for editing pictures, not for serving video).
        """
        from fastapi.responses import RedirectResponse

        served = self.serve_asset_file(item_id)
        if not isinstance(served, RedirectResponse):
            return served
        asset = self.repos.assets.get_one(item_id)
        try:
            got = httpx.get(served.headers["location"], timeout=30, follow_redirects=True)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"The file could not be fetched from storage: {e}") from e
        if got.status_code != 200:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Storage answered {got.status_code} for the file.")
        if len(got.content) > MAX_CONTENT_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="That file is too large to read through the API.")
        return Response(content=got.content, media_type=asset.mime_type or got.headers.get("content-type") or "application/octet-stream")
