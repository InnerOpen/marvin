"""Business logic for asset upload and storage."""

import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from pydantic import UUID4

from marvin.repos import AllRepositories
from marvin.schemas.platform.assets import AssetCreateInternal, AssetRead, AssetUploadRequest
from marvin.services import BaseService
from marvin.services.storage.base_provider import BaseStorageProvider

from .metadata_extractor import AssetMetadataExtractor


class AssetStorageService(BaseService):
    """Business logic for asset upload and storage."""

    def __init__(self, repos: AllRepositories, storage_provider: BaseStorageProvider):
        """
        Initialize asset storage service.

        Args:
            repos: Repository instances for database access
            storage_provider: Storage provider for file operations
        """
        super().__init__()
        self.repos = repos
        self.storage = storage_provider
        self.metadata_extractor = AssetMetadataExtractor()

    def upload_asset(
        self,
        upload_file: UploadFile,
        upload_request: AssetUploadRequest,
        group_id: UUID4,
        user_id: UUID4,
    ) -> AssetRead:
        """
        Complete upload pipeline for a new asset.

        Steps:
        1. Validate file
        2. Save to temporary location
        3. Extract metadata
        4. Generate storage key
        5. Store file via provider
        6. Create database record
        7. Return AssetRead

        Args:
            upload_file: The uploaded file
            upload_request: Editorial metadata from client
            group_id: Workspace ID
            user_id: User uploading the asset

        Returns:
            AssetRead with complete asset information

        Raises:
            ValueError: If file validation fails
            Exception: If upload or storage fails
        """
        # Get workspace slug for storage key generation
        group = self.repos.groups.get_one(group_id)
        if not group:
            raise ValueError(f"Workspace not found: {group_id}")

        # Extract original filename
        original_filename = upload_file.filename or "unnamed"

        # Save to temporary file for metadata extraction
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(original_filename).suffix) as temp_file:
            temp_path = Path(temp_file.name)

            # Write uploaded content to temp file
            content = upload_file.file.read()
            temp_file.write(content)
            temp_file.flush()

            try:
                # Extract metadata from temporary file
                metadata = self.metadata_extractor.extract_metadata(temp_path)

                # Generate storage key
                storage_key = self.generate_storage_key(
                    workspace_slug=group.slug or "workspace",
                    filename=original_filename,
                    upload_date=datetime.now(UTC),
                )

                # Reset file pointer and store via provider
                upload_file.file.seek(0)
                self.storage.put(
                    storage_key=storage_key,
                    file_data=upload_file.file,
                    content_type=metadata.mime_type,
                    metadata=upload_request.metadata_json,
                )

                # Get public URL
                public_url = self.storage.get_public_url(storage_key)

                # Parse filename and extension
                path = Path(original_filename)
                extension = path.suffix.lstrip(".")
                filename = path.stem

                # Create internal schema for database
                asset_create = AssetCreateInternal(
                    slug=upload_request.slug,
                    name=upload_request.name,
                    original_filename=original_filename,
                    filename=filename,
                    extension=extension,
                    file_size=metadata.size,
                    mime_type=metadata.mime_type,
                    asset_type=metadata.asset_type,
                    checksum=metadata.checksum,
                    width=metadata.width,
                    height=metadata.height,
                    orientation=metadata.orientation,
                    storage_provider=self._get_provider_name(),
                    storage_key=storage_key,
                    public_url=public_url,
                    alt_text=upload_request.alt_text,
                    description=upload_request.description,
                    metadata_json=upload_request.metadata_json,
                )

                # Create database record
                asset_data = asset_create.model_dump(exclude_unset=True)
                asset_data["group_id"] = group_id
                asset_data["uploaded_by"] = user_id
                asset = self.repos.assets.create(asset_data)

                return AssetRead.model_validate(asset)

            finally:
                # Clean up temporary file
                temp_path.unlink(missing_ok=True)

    def create_derivative(
        self,
        *,
        source,
        data: bytes,
        group_id: UUID4,
        derivation: str,
        slug: str,
        name: str,
        user_id: UUID4 | None = None,
        extra_metadata: dict | None = None,
    ) -> AssetRead:
        """Persist transformed image `data` as a NEW asset derived from `source`.

        Used by the media pipeline (grade/crop) to store a produced image with provenance
        (`metadata_json.derived_from` / `.derivation`) linking it back to the source asset. The
        source asset is left untouched. `slug` must be unique in the workspace — callers keep this
        idempotent by not re-deriving the same (source, derivation) pair.
        """
        group = self.repos.groups.get_one(group_id)
        if not group:
            raise ValueError(f"Workspace not found: {group_id}")

        ext = (getattr(source, "extension", None) or "jpg").lstrip(".")
        original_filename = f"{slug}.{ext}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
            try:
                metadata = self.metadata_extractor.extract_metadata(temp_path)
                storage_key = self.generate_storage_key(
                    workspace_slug=group.slug or "workspace",
                    filename=original_filename,
                    upload_date=datetime.now(UTC),
                )
                provenance = {
                    "derived_from": str(getattr(source, "id", "")),
                    "derivation": derivation,
                    **(extra_metadata or {}),
                }
                with open(temp_path, "rb") as fh:
                    self.storage.put(
                        storage_key=storage_key,
                        file_data=fh,
                        content_type=metadata.mime_type,
                        metadata=None,
                    )
                public_url = self.storage.get_public_url(storage_key)
                asset_create = AssetCreateInternal(
                    slug=slug,
                    name=name,
                    original_filename=original_filename,
                    filename=slug,
                    extension=ext,
                    file_size=metadata.size,
                    mime_type=metadata.mime_type,
                    asset_type=metadata.asset_type,
                    checksum=metadata.checksum,
                    width=metadata.width,
                    height=metadata.height,
                    orientation=metadata.orientation,
                    storage_provider=self._get_provider_name(),
                    storage_key=storage_key,
                    public_url=public_url,
                    alt_text=getattr(source, "alt_text", None),
                    metadata_json=provenance,
                )
                asset_data = asset_create.model_dump(exclude_unset=True)
                asset_data["group_id"] = group_id
                # A derivative inherits the source asset's uploader when no actor is supplied
                # (system/AI-produced images still need a non-null uploaded_by).
                asset_data["uploaded_by"] = user_id or getattr(source, "uploaded_by", None)
                asset = self.repos.assets.create(asset_data)
                return AssetRead.model_validate(asset)
            finally:
                temp_path.unlink(missing_ok=True)

    def storage_for(self, asset) -> BaseStorageProvider:
        """The provider an existing asset row lives in: this service's own provider when the row is on
        it, else the row's (assets on different providers are served side by side)."""
        slug = getattr(asset, "storage_provider", None)
        if not slug or slug == self._get_provider_name():
            return self.storage
        from marvin.services.storage.provider_factory import provider_for

        return provider_for(slug)

    def read_bytes(self, asset) -> bytes:
        """Read an asset's raw bytes (source for a derivation) from the provider it lives in. A bare
        storage key reads from this service's provider."""
        if isinstance(asset, str):
            return self.storage.get(asset).read()
        with self.storage_for(asset).get(asset.storage_key) as fh:
            return fh.read()

    def delete_asset(self, asset_id: UUID4) -> bool:
        """
        Delete asset from storage and database.

        Args:
            asset_id: ID of the asset to delete

        Returns:
            True if asset was deleted, False if not found

        Raises:
            Exception: If deletion fails
        """
        # Get asset from database
        asset = self.repos.assets.get_one(asset_id)
        if not asset:
            return False

        # Delete from storage (the provider the row lives in)
        try:
            self.storage_for(asset).delete(asset.storage_key)
        except Exception as e:
            # Log but don't fail if storage deletion fails
            # The database record should still be removed
            self.logger.warning(f"Failed to delete asset from storage: {e}")

        # Delete database record
        self.repos.assets.delete(asset_id)

        return True

    def generate_storage_key(
        self,
        workspace_slug: str,
        filename: str,
        upload_date: datetime,
    ) -> str:
        """
        Generate storage key with format:
        {workspace_slug}/assets/{YYYY}/{MM}/{uuid}-{sanitized_filename}

        Args:
            workspace_slug: Workspace slug for namespacing
            filename: Original filename
            upload_date: Date of upload

        Returns:
            Storage key string
        """
        # Generate UUID
        file_uuid = uuid.uuid4()

        # Sanitize filename
        sanitized_filename = self._sanitize_filename(filename)

        # Format: workspace-slug/assets/YYYY/MM/uuid-filename.ext
        year = upload_date.strftime("%Y")
        month = upload_date.strftime("%m")

        storage_key = f"{workspace_slug}/assets/{year}/{month}/{file_uuid}-{sanitized_filename}"

        return storage_key

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for safe storage.

        Removes unsafe characters and limits length.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Convert to lowercase
        filename = filename.lower()

        # Replace spaces and unsafe characters with hyphens
        filename = re.sub(r"[^a-z0-9._-]", "-", filename)

        # Remove consecutive hyphens
        filename = re.sub(r"-+", "-", filename)

        # Remove leading/trailing hyphens
        filename = filename.strip("-")

        # Limit length (keep extension)
        max_length = 100
        if len(filename) > max_length:
            path = Path(filename)
            ext = path.suffix
            stem = path.stem[: max_length - len(ext)]
            filename = f"{stem}{ext}"

        return filename

    def _get_provider_name(self) -> str:
        """The slug new rows record as their ``storage_provider``."""
        from marvin.services.storage.provider_factory import provider_slug

        return provider_slug(self.storage)
