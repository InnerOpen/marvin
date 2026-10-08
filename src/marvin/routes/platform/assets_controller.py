"""Asset routes."""

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import UUID4

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_editor, require_workspace_role
from marvin.schemas.platform import AssetRead, AssetUpdate, AssetUploadRequest
from marvin.services import trash
from marvin.services.assets.asset_storage_service import AssetRejected, AssetStorageService
from marvin.services.event_bus_service.event_types import EventAssetData, EventTypes
from marvin.services.storage import StorageConfigError
from marvin.services.storage.keys import content_disposition
from marvin.services.storage.provider_factory import get_storage_provider, provider_for, public_url_for

router = APIRouter(prefix="/assets")


@controller(router)
class AssetsController(BaseUserController):
    """Authenticated CRUD routes for assets with file upload support. Any member reads; AUTHORs and
    above upload; editing, deleting and accepting AI suggestions on an asset is EDITOR and above (an
    asset has no owner, so an AUTHOR can't be limited to their own).

    Delete moves an asset to the Trash (services/trash.py): its file stays in storage, it leaves the list,
    and fetching it by id shows its `trashed_at`. Only a trashed asset can be deleted forever."""

    @router.get("", response_model=list[AssetRead], summary="List Assets")
    def list_assets(self) -> list[AssetRead]:
        """Every asset but those in the Trash."""
        return [a for a in self.repos.assets.get_all(order_by="name") if a.trashed_at is None]

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
        )

        # Get storage provider and create service
        storage_provider = get_storage_provider()
        asset_service = AssetStorageService(self.repos, storage_provider)

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
