"""Business logic for asset upload and storage."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from pydantic import UUID4

from marvin.repos import AllRepositories
from marvin.schemas.platform.assets import AssetCreateInternal, AssetRead, AssetUploadRequest
from marvin.services import BaseService
from marvin.services.storage.base_provider import BaseStorageProvider
from marvin.services.storage.keys import new_key, object_metadata, workspace_code

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
        # The workspace must exist (its storage code names the key)
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

                # Generate storage key (opaque: no workspace slug, no filename)
                storage_key = self.generate_storage_key(group_id, original_filename, metadata.mime_type)

                # Reset file pointer and store via provider; the original name travels as the
                # object's Content-Disposition where the provider stores one.
                upload_file.file.seek(0)
                self.storage.put(
                    storage_key=storage_key,
                    file_data=upload_file.file,
                    content_type=metadata.mime_type,
                    metadata=object_metadata(original_filename, upload_request.metadata_json),
                )

                # Get public URL
                public_url = self.public_url(group_id, storage_key)

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
                storage_key = self.generate_storage_key(group_id, original_filename, metadata.mime_type)
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
                        metadata=object_metadata(original_filename),
                    )
                public_url = self.public_url(group_id, storage_key)
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
        self._delete_old_copies(asset_id)

        # Delete database record
        self.repos.assets.delete(asset_id)

        return True

    def _delete_old_copies(self, asset_id: UUID4) -> None:
        """Delete the copies an asset left at its old keys (``storage_migrate --rekey``, not pruned yet)
        and forget those keys: the asset is gone, so nothing should redirect to it."""
        from marvin.db.models.platform import StorageKeyAliasModel
        from marvin.services.storage.provider_factory import provider_for

        session = self.repos.session
        for alias in session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.asset_id == asset_id).all():
            if alias.pruned_at is None:
                try:
                    provider_for(alias.provider).delete(alias.storage_key)
                except Exception as e:
                    self.logger.warning(f"Failed to delete the old copy {alias.storage_key!r} of asset {asset_id}: {e}")
            session.delete(alias)

    def generate_storage_key(
        self, group_id: UUID4, filename: str | None, content_type: str | None = None, upload_date: datetime | None = None
    ) -> str:
        """A new opaque key for one of the workspace's files: ``<workspace code>/<yyyy>/<mm>/<uuid>.<ext>``
        (services/storage/keys.py). Neither the workspace's slug nor the filename appears in it."""
        code = workspace_code(self.repos.session, group_id)
        return new_key(code, filename, content_type, upload_date or datetime.now(UTC))

    def public_url(self, group_id: UUID4, storage_key: str) -> str:
        """The URL a new file on this service's provider is served at (with the workspace's public domain)."""
        from marvin.services.storage.provider_factory import public_url_for

        return public_url_for(self._get_provider_name(), storage_key, group_id, provider=self.storage)

    def _get_provider_name(self) -> str:
        """The slug new rows record as their ``storage_provider``."""
        from marvin.services.storage.provider_factory import provider_slug

        return provider_slug(self.storage)
