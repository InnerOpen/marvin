# Asset Upload and Storage Architecture

## Overview

Marvin's asset subsystem provides a production-ready upload, storage, and delivery system for media files. The architecture is built on clean abstractions that support multiple storage backends (local filesystem, S3-compatible services) with automatic metadata extraction and event-driven integration.

## Core Components

### 1. Storage Provider Abstraction

**Location:** `/src/marvin/services/storage/`

The storage layer uses the Strategy pattern to support swappable backends without changing application code.

**Base Interface:** `BaseStorageProvider`

```python
class BaseStorageProvider(ABC):
    @abstractmethod
    def put(self, storage_key: str, file_data: BinaryIO, ...) -> StorageMetadata

    @abstractmethod
    def get(self, storage_key: str) -> BinaryIO

    @abstractmethod
    def delete(self, storage_key: str) -> bool

    @abstractmethod
    def exists(self, storage_key: str) -> bool

    @abstractmethod
    def get_public_url(self, storage_key: str) -> str
```

**Implementations:**

1. **LocalStorageProvider** (`local_provider.py`)
   - Stores files in local filesystem
   - Configurable root directory (defaults to `{DATA_DIR}/uploads`)
   - Generates public URLs as `/uploads/{storage_key}`
   - Creates directory structure automatically
   - Suitable for development and single-server deployments

2. **S3StorageProvider** (`s3_provider.py`)
   - Works with S3-compatible APIs (AWS S3, Cloudflare R2, MinIO, Backblaze B2)
   - Configurable endpoint for non-AWS providers
   - Supports public and private buckets
   - Optional CDN URL override for CloudFront, etc.
   - Handles multipart uploads for large files

**Provider Selection:** `provider_factory.py`

```python
def get_storage_provider() -> BaseStorageProvider:
    settings = get_app_settings()
    if settings.STORAGE_PROVIDER == "local":
        return LocalStorageProvider(...)
    elif settings.STORAGE_PROVIDER == "s3":
        return S3StorageProvider(...)
```

### 2. Upload Pipeline

**Location:** `/src/marvin/services/assets/asset_storage_service.py`

The `AssetStorageService` orchestrates the complete upload workflow:

**Pipeline Stages:**

1. **Validation**
   - Verify workspace exists
   - Check file size limits (default 100MB)
   - Validate MIME types (if allowlist configured)

2. **Temporary Storage**
   - Save upload to secure temp directory
   - Generate unique temp filename to prevent collisions

3. **Metadata Extraction**
   - Extract technical metadata via `AssetMetadataExtractor`
   - MIME type, file size, checksum (SHA-256)
   - Image dimensions, EXIF orientation (for images)
   - Asset type classification

4. **Storage**
   - Generate storage key: `{workspace_slug}/assets/{YYYY}/{MM}/{uuid}-{filename}`
   - Upload to storage provider via `put()`
   - Retrieve public URL from provider

5. **Database Record**
   - Create asset record with combined metadata
   - Technical metadata (server-generated)
   - Editorial metadata (client-provided)
   - Link to uploader and workspace

6. **Cleanup**
   - Delete temporary file
   - Rollback storage on database failure

7. **Event Emission**
   - Emit `asset.uploaded` event for background processing
   - Includes asset ID, workspace ID, uploader ID

**Error Handling:**

- Storage failures trigger rollback (no orphaned DB records)
- Database failures trigger storage cleanup (no orphaned files)
- Temp files cleaned up on all paths (success and failure)

### 3. Metadata Extraction

**Location:** `/src/marvin/services/assets/metadata_extractor.py`

The `AssetMetadataExtractor` analyzes uploaded files to generate technical metadata.

**All Files:**

- **MIME Type:** Detected via `mimetypes` module + magic number fallback
- **File Size:** Exact byte count
- **Checksum:** SHA-256 hash for integrity verification and deduplication
- **Asset Type:** Classification into `image`, `document`, `video`, `audio`, `archive`, `svg`, `other`
- **Extension:** Normalized from filename

**Images (via Pillow):**

- **Dimensions:** Width and height in pixels
- **Orientation:** EXIF orientation tag (1-8) for rotation correction

**Supported Asset Types:**

| Type | Extensions |
|------|-----------|
| image | jpg, jpeg, png, gif, webp, avif, bmp, tiff |
| svg | svg (text-based vector graphics) |
| document | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, md |
| video | mp4, mpeg, mov, webm, avi |
| audio | mp3, wav, ogg, webm, aac, flac |
| archive | zip, gz, tar, 7z, rar |
| other | Any unrecognized type |

**Extensibility:**

To add new metadata extraction:

1. Extend `AssetMetadataExtractor._extract_image_metadata()` for image-specific data
2. Add new `_extract_video_metadata()` method for video processing
3. Update `extract_metadata()` to route by MIME type

### 4. Data Model

**Location:** `/src/marvin/db/models/platform/assets.py`

**Asset Fields:**

**Identifiers:**
- `id`: UUID4 primary key
- `slug`: URL-friendly unique identifier
- `group_id`: Workspace FK (scoping)

**File Metadata (Server-Generated):**
- `original_filename`: Original upload name
- `filename`: Sanitized filename
- `extension`: File extension
- `file_size`: Bytes
- `mime_type`: MIME type string
- `asset_type`: Enum classification
- `checksum`: SHA-256 hex digest

**Image Metadata (Server-Generated):**
- `width`: Pixels (nullable)
- `height`: Pixels (nullable)
- `orientation`: EXIF orientation 1-8 (nullable)

**Storage Metadata (Server-Generated):**
- `storage_provider`: Provider name (`local`, `s3`)
- `storage_key`: Path within provider
- `public_url`: CDN or direct URL (nullable)

**Editorial Metadata (Client-Provided):**
- `name`: Display name
- `alt_text`: Accessibility description (nullable)
- `description`: Long-form description (nullable)
- `metadata_`: JSON object for custom fields (nullable)

**Tracking:**
- `uploaded_by`: User FK
- `created_at`: Timestamp
- `updated_at`: Timestamp

### 5. Asset Relationships

**Location:** `/src/marvin/db/models/platform/entry_assets.py`

Assets attach to Entries via the `entry_assets` junction table.

**Placement Fields:**

- `asset_id`: FK to Assets
- `entry_id`: FK to Entries
- `role`: Usage role (`hero`, `featured`, `support`, `inline`, `download`)
- `usage`: Domain-specific hint (`material`, `process`, `detail`, `texture`, `workshop`)
- `position`: Display order integer
- `focal_point`: CSS-style focal point for cropping (`"50% 50%"`)
- `caption`: Optional caption for this placement
- `metadata_`: Placement-specific JSON metadata

**Design Rationale:**

This junction table separates core asset data from usage context. The same asset can be placed in multiple entries with different roles, positions, and captions.

**Future Expansion:**

The pattern can extend to:
- `resource_assets` - Assets used in Resources
- `collection_assets` - Assets for Collection thumbnails
- `site_settings_assets` - Site logos, favicons, etc.

Or a generic polymorphic table:

```python
class AssetRelationships:
    asset_id: UUID4
    related_type: str  # 'entry', 'resource', 'collection'
    related_id: UUID4
    # ... placement fields
```

## API Design

### Platform API (Authenticated)

**Endpoints:** `/api/platform/assets/*`

Full CRUD operations for workspace members:

- `POST /upload` - Upload new asset (multipart/form-data)
- `GET /` - List assets (filtered, paginated)
- `GET /{asset_id}` - Get single asset
- `PATCH /{asset_id}` - Update editorial fields only
- `DELETE /{asset_id}` - Delete asset and file

**Skinny Upload Request:**

Clients provide only editorial metadata:

```json
{
  "slug": "hero-image",
  "name": "Hero Image",
  "alt_text": "Hero section background",
  "description": "Landscape photo for hero",
  "metadata": { "photographer": "Jane Doe" }
}
```

Server generates all technical metadata:

```json
{
  "id": "...",
  "slug": "hero-image",
  "name": "Hero Image",
  "mime_type": "image/jpeg",  // Server-generated
  "asset_type": "image",      // Server-generated
  "file_size": 2048576,       // Server-generated
  "checksum": "abc123...",    // Server-generated
  "width": 1920,              // Server-generated
  "height": 1080,             // Server-generated
  "storage_provider": "s3",   // Server-generated
  "storage_key": "...",       // Server-generated
  "public_url": "https://...", // Server-generated
  "uploaded_by": "...",       // Server-generated
  "created_at": "..."         // Server-generated
}
```

**Update Restrictions:**

Only editorial fields can be updated:
- `slug`, `name`, `alt_text`, `description`, `metadata`

Technical fields are immutable:
- `mime_type`, `file_size`, `checksum`, `width`, `height`, etc.

To change technical metadata, delete and re-upload.

### Publishing API (Read-Only)

**Endpoints:** `/api/publish/{workspace_slug}/assets/*`

Public read-only access for external sites:

- `GET /{workspace_slug}/assets` - List assets
- `GET /{workspace_slug}/assets/{slug}` - Get single asset

**Response:** `AssetSummary` schema (excludes internal fields)

Includes:
- `id`, `slug`, `name`, `mime_type`, `alt_text`

Excludes:
- `storage_key` (internal)
- `uploaded_by` (private)
- `checksum` (internal)

**Future:** Will require Site Client token authentication.

## Configuration

**Location:** `/src/marvin/core/settings/settings.py`

### Local Storage

```python
STORAGE_PROVIDER = "local"
STORAGE_LOCAL_ROOT = "/var/marvin/uploads"  # Optional, defaults to {DATA_DIR}/uploads
STORAGE_LOCAL_PUBLIC_URL = "/uploads"      # URL prefix for public access
```

### S3-Compatible Storage

```python
STORAGE_PROVIDER = "s3"
STORAGE_S3_BUCKET = "marvin-assets"
STORAGE_S3_REGION = "us-east-1"             # Or "auto" for R2
STORAGE_S3_ACCESS_KEY = "..."
STORAGE_S3_SECRET_KEY = "..."
STORAGE_S3_ENDPOINT = None                  # For non-AWS: "https://...r2.cloudflarestorage.com"
STORAGE_S3_PUBLIC_URL = None                # Optional CDN URL: "https://cdn.example.com"
```

### Upload Limits

```python
ASSET_MAX_FILE_SIZE = 100 * 1024 * 1024     # 100MB default
ASSET_ALLOWED_MIME_TYPES = None             # None = allow all, or ["image/jpeg", "image/png"]
```

### Example Configurations

**Development (Local Storage):**

```bash
STORAGE_PROVIDER=local
STORAGE_LOCAL_ROOT=./storage/uploads
STORAGE_LOCAL_PUBLIC_URL=/uploads
```

**Production (Cloudflare R2):**

```bash
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-prod-assets
STORAGE_S3_REGION=auto
STORAGE_S3_ENDPOINT=https://abc123.r2.cloudflarestorage.com
STORAGE_S3_ACCESS_KEY=...
STORAGE_S3_SECRET_KEY=...
STORAGE_S3_PUBLIC_URL=https://assets.example.com
```

**Production (AWS S3 + CloudFront):**

```bash
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ACCESS_KEY=...
STORAGE_S3_SECRET_KEY=...
STORAGE_S3_PUBLIC_URL=https://d111111abcdef8.cloudfront.net
```

## Event Bus Integration

**Location:** `/src/marvin/services/events/`

The asset service emits events for background processing:

**Events:**

- `asset.uploaded` - Fires after successful upload
- `asset.updated` - Fires after metadata update
- `asset.deleted` - Fires before deletion (cleanup hook)

**Event Payload:**

```python
{
  "asset_id": "uuid",
  "workspace_id": "uuid",
  "uploader_id": "uuid",
  "mime_type": "image/jpeg",
  "asset_type": "image",
  "storage_key": "workspace/assets/2026/07/..."
}
```

**Listeners:**

Future event listeners can implement:

- **Thumbnail Generation:** Create responsive variants on `asset.uploaded`
- **Image Optimization:** Compress and convert formats
- **AI Tagging:** Auto-generate alt text via ML model
- **Virus Scanning:** Scan uploads for malware
- **Analytics:** Track asset usage across entries

## Extension Points

The architecture is designed for future enhancements:

### Image Processing

**Thumbnail Generation:**

```python
# Event listener
@event_bus.on("asset.uploaded")
def generate_thumbnails(event):
    if event.asset_type == "image":
        # Create 100x100, 300x300, 600x600 variants
        # Store in same provider under {storage_key}-{size}.jpg
        pass
```

**Responsive Variants:**

```python
# Extend AssetRead schema
class AssetRead:
    variants: dict[str, str] = {}  # {"thumbnail": "url", "medium": "url"}
```

### Media Processing

**Video Transcoding:**

```python
@event_bus.on("asset.uploaded")
def transcode_video(event):
    if event.asset_type == "video":
        # Transcode to web-optimized MP4
        # Generate HLS playlist for adaptive streaming
        pass
```

**Audio Normalization:**

```python
@event_bus.on("asset.uploaded")
def normalize_audio(event):
    if event.asset_type == "audio":
        # Normalize volume levels
        # Convert to web-friendly formats
        pass
```

### Advanced Features

**Deduplication:**

The `checksum` field enables deduplication:

```python
existing = AssetsRepository.get_one(match_key="checksum", match_value=checksum)
if existing:
    # Reuse existing storage, create new DB record pointing to same file
    pass
```

**Signed URLs (Private Assets):**

```python
# Extend S3StorageProvider
def get_signed_url(self, storage_key: str, expires_in: int = 3600) -> str:
    return s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': self.bucket, 'Key': storage_key},
        ExpiresIn=expires_in
    )
```

**CDN Integration:**

Already supported via `STORAGE_S3_PUBLIC_URL` setting. For cache invalidation:

```python
@event_bus.on("asset.deleted")
def invalidate_cdn_cache(event):
    cloudflare.purge_cache(urls=[event.public_url])
```

**Background Processing Queue:**

```python
# Replace direct event processing with task queue
@event_bus.on("asset.uploaded")
def queue_processing(event):
    celery.send_task("process_asset", args=[event.asset_id])
```

**Asset Versioning:**

```python
# Extend Assets model
class Assets:
    version: int = 1
    previous_version_id: UUID4 | None = None  # FK to self
```

**Lifecycle Policies:**

```python
# S3 lifecycle rules for archival
s3_client.put_bucket_lifecycle_configuration(
    Bucket=bucket,
    LifecycleConfiguration={
        'Rules': [{
            'Prefix': 'workspace/assets/',
            'Status': 'Enabled',
            'Transitions': [{'Days': 90, 'StorageClass': 'GLACIER'}]
        }]
    }
)
```

### AI Features

**Auto-Generated Alt Text:**

```python
@event_bus.on("asset.uploaded")
async def generate_alt_text(event):
    if event.asset_type == "image" and not event.alt_text:
        alt_text = await vision_api.describe_image(event.storage_key)
        AssetsRepository.update(event.asset_id, {"alt_text": alt_text})
```

**Content Tagging:**

```python
@event_bus.on("asset.uploaded")
async def tag_content(event):
    tags = await ml_model.classify_image(event.storage_key)
    metadata = event.metadata or {}
    metadata["auto_tags"] = tags
    AssetsRepository.update(event.asset_id, {"metadata": metadata})
```

## Storage Key Structure

The storage key format is hierarchical for organization:

```
{workspace_slug}/assets/{YYYY}/{MM}/{uuid}-{filename}
```

**Example:**

```
acme-corp/assets/2026/07/a1b2c3d4-hero-image.jpg
```

**Benefits:**

- **Workspace Isolation:** Each workspace has its own namespace
- **Temporal Organization:** Easy to find assets by upload date
- **Collision Prevention:** UUID prefix ensures uniqueness
- **Human Readability:** Original filename preserved for debugging
- **Lifecycle Policies:** Easy to apply retention rules by date prefix

## Security Considerations

### Upload Validation

1. **File Size Limits:** Enforced via `ASSET_MAX_FILE_SIZE`
2. **MIME Type Allowlist:** Optional `ASSET_ALLOWED_MIME_TYPES` filter
3. **Workspace Scoping:** Assets are always scoped to uploader's workspace
4. **Filename Sanitization:** Remove path traversal characters

### Access Control

1. **Platform API:** Requires user authentication
2. **Publishing API:** Read-only, workspace-scoped (future: site client tokens)
3. **Storage URLs:** Can be private (signed URLs) or public (CDN)

### Data Integrity

1. **Checksums:** SHA-256 for integrity verification
2. **Atomic Operations:** Storage + DB writes are transactional
3. **Rollback on Failure:** Storage cleanup if DB write fails

### Future Enhancements

1. **Virus Scanning:** Scan uploads before storage
2. **Rate Limiting:** Prevent abuse via upload quotas
3. **Content Policy:** Block inappropriate content via ML
4. **Encryption:** Encrypt files at rest in storage backend

## Performance Considerations

### Current Implementation

- **Synchronous Processing:** Upload blocks until complete
- **Single-Threaded:** Metadata extraction on main thread
- **Direct Writes:** No intermediate caching layer

### Optimization Strategies

**Background Processing:**

Move heavy operations to background queue:

```python
# Quick upload, queue processing
asset = upload_to_storage(file)
celery.send_task("extract_metadata", args=[asset.id])
celery.send_task("generate_thumbnails", args=[asset.id])
```

**Streaming Uploads:**

For large files, stream directly to storage without temp file:

```python
# Stream multipart upload to S3
s3_client.upload_fileobj(file_stream, bucket, key)
```

**CDN Caching:**

Configure aggressive caching for immutable assets:

```
Cache-Control: public, max-age=31536000, immutable
```

**Database Indexing:**

Key indexes for fast queries:

```sql
CREATE INDEX idx_assets_workspace_type ON assets (group_id, asset_type);
CREATE INDEX idx_assets_checksum ON assets (checksum);  -- Deduplication
CREATE INDEX idx_assets_created ON assets (created_at);  -- Time-based queries
```

## Testing Strategy

**Unit Tests:**

- Storage provider implementations
- Metadata extractor accuracy
- Upload pipeline stages

**Integration Tests:**

- Full upload workflow (API → storage → DB)
- Provider swapping (local ↔ S3)
- Workspace scoping enforcement
- Publishing API read-only access

**Example:** See `/tests/test_asset_upload.py`

## Troubleshooting

### Common Issues

**"File not found" after upload:**

- Check `STORAGE_LOCAL_ROOT` path exists and is writable
- Verify storage provider configuration matches upload settings
- Check storage key format matches provider expectations

**S3 upload fails:**

- Verify `STORAGE_S3_BUCKET` exists and is accessible
- Check IAM permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- For R2/MinIO: ensure `STORAGE_S3_ENDPOINT` is correct

**Public URL returns 404:**

- For local storage: ensure `STORAGE_LOCAL_PUBLIC_URL` route is configured
- For S3: verify bucket policy allows public reads or use signed URLs
- For CDN: check CDN origin configuration points to bucket

**Metadata extraction fails:**

- Ensure Pillow is installed for image processing
- Check file is not corrupted
- Verify MIME type is supported

### Debug Mode

Enable debug logging:

```python
import logging
logging.getLogger("marvin.services.assets").setLevel(logging.DEBUG)
```

### Health Checks

Verify storage provider connectivity:

```python
from marvin.services.storage.provider_factory import get_storage_provider

provider = get_storage_provider()
test_key = "health-check.txt"
provider.put(test_key, io.BytesIO(b"test"), "text/plain")
assert provider.exists(test_key)
provider.delete(test_key)
```

## Migration Guide

### From External Storage to Marvin

**Step 1:** Bulk import existing assets

```python
for file in existing_files:
    # Upload via AssetStorageService
    asset = asset_service.upload_asset(
        file=file,
        workspace_id=workspace.id,
        uploader_id=admin.id,
        metadata={"slug": file.slug, "name": file.name}
    )
```

**Step 2:** Update references in entries

```python
for entry in entries:
    # Create entry_assets relationships
    for old_asset in entry.legacy_assets:
        new_asset = Asset.get_by_slug(old_asset.slug)
        EntryAsset.create(entry_id=entry.id, asset_id=new_asset.id)
```

### Between Storage Providers

**Step 1:** Configure new provider

```bash
# Old config (local)
STORAGE_PROVIDER=local

# New config (S3)
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=us-east-1
```

**Step 2:** Migrate files

```python
old_provider = LocalStorageProvider(...)
new_provider = S3StorageProvider(...)

for asset in Assets.all():
    # Download from old provider
    file_data = old_provider.get(asset.storage_key)

    # Upload to new provider
    new_provider.put(asset.storage_key, file_data, asset.mime_type)

    # Update database
    asset.storage_provider = "s3"
    asset.public_url = new_provider.get_public_url(asset.storage_key)
    asset.save()

    # Delete from old provider
    old_provider.delete(asset.storage_key)
```

**Step 3:** Update application config

Switch `STORAGE_PROVIDER` setting and restart application.

## Summary

Marvin's asset subsystem is production-ready with:

- ✅ Clean storage abstraction (local + S3-compatible)
- ✅ Automatic metadata extraction (MIME type, dimensions, checksum)
- ✅ Skinny upload API (client provides editorial metadata only)
- ✅ Event bus integration (extensible processing pipeline)
- ✅ Entry relationships (junction table pattern)
- ✅ Platform + Publishing APIs (authenticated + read-only)

The architecture supports future enhancements without redesign:
- Image/video processing
- AI-powered tagging
- Deduplication
- Signed URLs
- CDN integration
- Background queues
- Asset versioning
- Lifecycle policies

Next: See [ASSET-USAGE-GUIDE.md](./ASSET-USAGE-GUIDE.md) for practical usage examples.
