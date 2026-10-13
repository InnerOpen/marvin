"""Extract metadata from uploaded files."""

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

AssetType = Literal["image", "document", "video", "audio", "archive", "svg", "other"]

try:
    from PIL import Image
    from PIL.ExifTags import TAGS

    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


@dataclass
class ExtractedMetadata:
    """Metadata extracted from an uploaded file."""

    mime_type: str
    """MIME type of the file."""
    size: int
    """File size in bytes."""
    checksum: str
    """SHA-256 checksum."""
    asset_type: AssetType
    """Classified asset type."""
    width: int | None = None
    """Width in pixels (for images)."""
    height: int | None = None
    """Height in pixels (for images)."""
    orientation: int | None = None
    """EXIF orientation (1-8) for images."""


class AssetMetadataExtractor:
    """Extract technical metadata from uploaded files."""

    # MIME type to asset type mapping
    MIME_TO_ASSET_TYPE = {
        # Images
        "image/jpeg": "image",
        "image/jpg": "image",
        "image/png": "image",
        "image/gif": "image",
        "image/webp": "image",
        "image/avif": "image",
        "image/bmp": "image",
        "image/tiff": "image",
        "image/svg+xml": "svg",
        # Documents
        "application/pdf": "document",
        "application/msword": "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
        "application/vnd.ms-excel": "document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
        "application/vnd.ms-powerpoint": "document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
        "text/plain": "document",
        "text/csv": "document",
        "text/markdown": "document",
        # Video
        "video/mp4": "video",
        "video/mpeg": "video",
        "video/quicktime": "video",
        "video/webm": "video",
        "video/x-msvideo": "video",
        # Audio
        "audio/mpeg": "audio",
        "audio/mp3": "audio",
        "audio/wav": "audio",
        "audio/wave": "audio",
        "audio/ogg": "audio",
        "audio/webm": "audio",
        "audio/aac": "audio",
        "audio/flac": "audio",
        # Archives
        "application/zip": "archive",
        "application/x-zip-compressed": "archive",
        "application/gzip": "archive",
        "application/x-gzip": "archive",
        "application/x-tar": "archive",
        "application/x-7z-compressed": "archive",
        "application/x-rar-compressed": "archive",
    }

    def extract_metadata(self, file_path: Path) -> ExtractedMetadata:
        """
        Extract metadata from a file.

        Args:
            file_path: Path to the file to analyze

        Returns:
            ExtractedMetadata with technical information about the file
        """
        # Get MIME type
        mime_type = self._detect_mime_type(file_path)

        # Get file size
        size = file_path.stat().st_size

        # Calculate checksum
        checksum = self._calculate_checksum(file_path)

        # Classify asset type
        asset_type = self._classify_asset_type(mime_type)

        # Extract image-specific metadata if applicable
        width = None
        height = None
        orientation = None

        if asset_type == "image" and mime_type != "image/svg+xml":
            width, height, orientation = self._extract_image_metadata(file_path)

        return ExtractedMetadata(
            mime_type=mime_type,
            size=size,
            checksum=checksum,
            asset_type=asset_type,
            width=width,
            height=height,
            orientation=orientation,
        )

    def _detect_mime_type(self, file_path: Path) -> str:
        """Detect MIME type from file."""
        # Use mimetypes module to guess
        mime_type, _ = mimetypes.guess_type(str(file_path))

        if mime_type:
            return mime_type

        # Fallback to extension-based detection
        ext = file_path.suffix.lower()
        extension_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".zip": "application/zip",
        }

        return extension_map.get(ext, "application/octet-stream")

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of file."""
        hasher = hashlib.sha256()

        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

        return hasher.hexdigest()

    def _classify_asset_type(self, mime_type: str) -> AssetType:
        """Classify asset type based on MIME type."""
        return cast(AssetType, self.MIME_TO_ASSET_TYPE.get(mime_type, "other"))

    def _extract_image_metadata(self, file_path: Path) -> tuple[int | None, int | None, int | None]:
        """Extract width, height, and orientation from image files."""
        if not PILLOW_AVAILABLE:
            return None, None, None

        try:
            with Image.open(file_path) as img:
                width, height = img.size

                # Try to get EXIF orientation
                orientation = None
                try:
                    exif = img._getexif()
                    if exif:
                        for tag_id, value in exif.items():
                            tag = TAGS.get(tag_id, tag_id)
                            if tag == "Orientation":
                                orientation = value
                                break
                except (AttributeError, KeyError, IndexError):
                    pass

                return width, height, orientation

        except Exception:
            # If we can't extract metadata, return None
            return None, None, None
