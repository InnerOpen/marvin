# Asset Upload and Storage - Usage Guide

This guide shows how to use Marvin's asset system in practice: uploading assets via API/SDK/CLI, configuring storage providers, managing asset relationships, and publishing to external sites.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Uploading Assets](#uploading-assets)
3. [Managing Assets](#managing-assets)
4. [Storage Provider Configuration](#storage-provider-configuration)
5. [Asset Relationships](#asset-relationships)
6. [Publishing Assets](#publishing-assets)
7. [Advanced Usage](#advanced-usage)
8. [Troubleshooting](#troubleshooting)

## Quick Start

### Upload an Asset via CLI

```bash
# Upload image with metadata
marvin platform assets upload hero.jpg \
  --slug hero-image \
  --name "Hero Image" \
  --alt-text "Homepage hero background"

# Output:
# ✓ Uploaded: hero.jpg
# ID: 550e8400-e29b-41d4-a716-446655440000
# Public URL: https://cdn.example.com/acme/assets/2026/07/abc123-hero.jpg
```

### Upload an Asset via SDK

```typescript
import { createPlatformClient } from '@inneropen/marvin-sdk/platform';

const client = createPlatformClient({
  apiUrl: 'https://marvin.example.com',
  userToken: 'your-user-token'
});

const file = new File([buffer], 'hero.jpg', { type: 'image/jpeg' });

const asset = await client.assets.upload(file, {
  slug: 'hero-image',
  name: 'Hero Image',
  altText: 'Homepage hero background'
});

console.log('Uploaded:', asset.publicUrl);
console.log('Dimensions:', asset.width, 'x', asset.height);
console.log('Checksum:', asset.checksum);
```

### Upload an Asset via API

```bash
curl -X POST https://marvin.example.com/api/platform/assets/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@hero.jpg" \
  -F "slug=hero-image" \
  -F "name=Hero Image" \
  -F "alt_text=Homepage hero background"
```

Response:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "slug": "hero-image",
  "name": "Hero Image",
  "mime_type": "image/jpeg",
  "asset_type": "image",
  "file_size": 2048576,
  "width": 1920,
  "height": 1080,
  "checksum": "abc123def456...",
  "storage_provider": "s3",
  "storage_key": "acme/assets/2026/07/abc123-hero.jpg",
  "public_url": "https://cdn.example.com/acme/assets/2026/07/abc123-hero.jpg",
  "alt_text": "Homepage hero background",
  "uploaded_by": "user-uuid",
  "created_at": "2026-07-07T12:00:00Z"
}
```

## Uploading Assets

### What the Client Provides (Editorial Metadata)

When uploading, clients only provide editorial metadata:

**Required:**
- `slug` - URL-friendly identifier (unique within workspace)
- `name` - Display name for the asset

**Optional:**
- `alt_text` - Accessibility description for images
- `description` - Long-form description
- `metadata` - Custom JSON object for domain-specific fields

### What the Server Generates (Technical Metadata)

The server automatically extracts and generates:

**File Metadata:**
- `mime_type` - Detected from file content
- `file_size` - Exact byte count
- `asset_type` - Classification (image, document, video, audio, archive, svg, other)
- `checksum` - SHA-256 hash for integrity
- `original_filename` - Original upload name
- `filename` - Sanitized filename
- `extension` - Normalized extension

**Image Metadata (for images only):**
- `width` - Pixels
- `height` - Pixels
- `orientation` - EXIF orientation tag (1-8)

**Storage Metadata:**
- `storage_provider` - Provider name (local, s3)
- `storage_key` - Internal path
- `public_url` - Public access URL

**Tracking:**
- `uploaded_by` - User who uploaded
- `created_at` - Upload timestamp
- `updated_at` - Last modification timestamp

### Upload via CLI

**Basic Upload:**

```bash
marvin platform assets upload photo.jpg \
  --slug product-photo \
  --name "Product Photo"
```

**With Full Metadata:**

```bash
marvin platform assets upload photo.jpg \
  --slug product-photo \
  --name "Product Photo" \
  --alt-text "Red widget on white background" \
  --description "High-resolution product photo for homepage"
```

**With Custom Metadata:**

```bash
marvin platform assets upload photo.jpg \
  --slug product-photo \
  --name "Product Photo" \
  --metadata '{"photographer": "Jane Doe", "license": "CC-BY-SA"}'
```

**Batch Upload:**

```bash
for file in images/*.jpg; do
  slug=$(basename "$file" .jpg)
  marvin platform assets upload "$file" \
    --slug "$slug" \
    --name "$slug"
done
```

### Upload via SDK

**Simple Upload:**

```typescript
const file = new File([buffer], 'photo.jpg');

const asset = await client.assets.upload(file, {
  slug: 'product-photo',
  name: 'Product Photo'
});
```

**With Full Metadata:**

```typescript
const asset = await client.assets.upload(file, {
  slug: 'product-photo',
  name: 'Product Photo',
  altText: 'Red widget on white background',
  description: 'High-resolution product photo',
  metadata: {
    photographer: 'Jane Doe',
    license: 'CC-BY-SA'
  }
});
```

**From File Input:**

```typescript
// In a React/Vue/Svelte component
const handleUpload = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];

  if (!file) return;

  const asset = await client.assets.upload(file, {
    slug: generateSlug(file.name),
    name: file.name,
    altText: ''
  });

  console.log('Uploaded:', asset.publicUrl);
};
```

**With Progress Tracking:**

```typescript
// Note: Native Fetch API doesn't support progress
// Use XMLHttpRequest wrapper or library like axios

const uploadWithProgress = async (file: File, onProgress: (percent: number) => void) => {
  const xhr = new XMLHttpRequest();

  return new Promise((resolve, reject) => {
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const percent = (e.loaded / e.total) * 100;
        onProgress(percent);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status === 200) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error('Upload failed'));
      }
    });

    const formData = new FormData();
    formData.append('file', file);
    formData.append('slug', 'product-photo');
    formData.append('name', 'Product Photo');

    xhr.open('POST', `${apiUrl}/api/platform/assets/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  });
};
```

### Upload via API (Direct)

**cURL Example:**

```bash
curl -X POST https://marvin.example.com/api/platform/assets/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@photo.jpg" \
  -F "slug=product-photo" \
  -F "name=Product Photo" \
  -F "alt_text=Red widget" \
  -F "description=Product photo" \
  -F "metadata={\"photographer\":\"Jane Doe\"}"
```

**Python Example:**

```python
import requests

url = "https://marvin.example.com/api/platform/assets/upload"
headers = {"Authorization": "Bearer YOUR_TOKEN"}

with open("photo.jpg", "rb") as f:
    files = {"file": f}
    data = {
        "slug": "product-photo",
        "name": "Product Photo",
        "alt_text": "Red widget",
        "metadata": '{"photographer": "Jane Doe"}'
    }

    response = requests.post(url, headers=headers, files=files, data=data)
    asset = response.json()
    print(f"Uploaded: {asset['public_url']}")
```

**JavaScript (Fetch) Example:**

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('slug', 'product-photo');
formData.append('name', 'Product Photo');
formData.append('alt_text', 'Red widget');

const response = await fetch('https://marvin.example.com/api/platform/assets/upload', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_TOKEN'
  },
  body: formData
});

const asset = await response.json();
console.log('Uploaded:', asset.public_url);
```

## Managing Assets

### List Assets

**CLI:**

```bash
# List all assets
marvin platform assets

# Filter by asset type
marvin platform assets --asset-type image

# Pagination
marvin platform assets --limit 50 --offset 100

# JSON output
marvin platform assets --output json
```

**SDK:**

```typescript
// List all assets
const assets = await client.assets.list();

// With filters
const images = await client.assets.list({
  assetType: 'image',
  limit: 50,
  offset: 0
});
```

**API:**

```bash
curl https://marvin.example.com/api/platform/assets \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -G \
  -d "asset_type=image" \
  -d "limit=50" \
  -d "offset=0"
```

### Get Single Asset

**CLI:**

```bash
marvin platform asset product-photo
```

**SDK:**

```typescript
const asset = await client.assets.get('product-photo');
```

**API:**

```bash
curl https://marvin.example.com/api/platform/assets/550e8400-... \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Update Asset Metadata

**Only editorial fields can be updated:** `slug`, `name`, `alt_text`, `description`, `metadata`

**CLI:**

```bash
marvin platform assets update product-photo \
  --alt-text "Updated alt text" \
  --description "New description"
```

**SDK:**

```typescript
const updated = await client.assets.update('product-photo', {
  altText: 'Updated alt text',
  description: 'New description',
  metadata: {
    photographer: 'John Smith'
  }
});
```

**API:**

```bash
curl -X PATCH https://marvin.example.com/api/platform/assets/550e8400-... \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "alt_text": "Updated alt text",
    "description": "New description"
  }'
```

**Note:** Technical fields (`mime_type`, `width`, `height`, `checksum`, etc.) cannot be updated. To change these, delete and re-upload the asset.

### Delete Asset

**CLI:**

```bash
marvin platform assets delete product-photo
```

**SDK:**

```typescript
await client.assets.delete('product-photo');
```

**API:**

```bash
curl -X DELETE https://marvin.example.com/api/platform/assets/550e8400-... \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Behavior:**

- Deletes database record
- Deletes file from storage provider
- Emits `asset.deleted` event
- **Warning:** This cannot be undone

## Storage Provider Configuration

### Local Storage (Development)

**Use Case:** Development, testing, single-server deployments

**Configuration:**

```bash
# .env
STORAGE_PROVIDER=local
STORAGE_LOCAL_ROOT=/var/marvin/uploads  # Optional, defaults to {DATA_DIR}/uploads
STORAGE_LOCAL_PUBLIC_URL=/uploads       # URL prefix
```

**Serving Files:**

Configure your web server to serve the upload directory:

**Nginx:**

```nginx
location /uploads/ {
    alias /var/marvin/uploads/;
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

**Apache:**

```apache
Alias /uploads /var/marvin/uploads
<Directory /var/marvin/uploads>
    Require all granted
    ExpiresActive On
    ExpiresDefault "access plus 1 year"
</Directory>
```

**Django/FastAPI (Development Only):**

```python
from fastapi.staticfiles import StaticFiles

app.mount("/uploads", StaticFiles(directory="/var/marvin/uploads"), name="uploads")
```

### AWS S3

**Use Case:** Production deployments, global CDN, scalability

**Configuration:**

```bash
# .env
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
STORAGE_S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

**IAM Permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::marvin-assets/*",
        "arn:aws:s3:::marvin-assets"
      ]
    }
  ]
}
```

**Bucket Policy (Public Read):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::marvin-assets/*"
    }
  ]
}
```

### Cloudflare R2

**Use Case:** S3-compatible, zero egress fees, global CDN

**Configuration:**

```bash
# .env
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=auto
STORAGE_S3_ENDPOINT=https://abc123.r2.cloudflarestorage.com
STORAGE_S3_ACCESS_KEY=your_r2_access_key
STORAGE_S3_SECRET_KEY=your_r2_secret_key
STORAGE_S3_PUBLIC_URL=https://assets.example.com  # Custom domain
```

**R2 Setup:**

1. Create R2 bucket in Cloudflare dashboard
2. Generate API token with "Object Read & Write" permissions
3. Configure custom domain for public access
4. Set CORS if uploading from browser

**CORS Configuration:**

```json
[
  {
    "AllowedOrigins": ["https://admin.example.com"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3600
  }
]
```

### MinIO (Self-Hosted)

**Use Case:** On-premise S3-compatible storage

**Configuration:**

```bash
# .env
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ENDPOINT=https://minio.example.com
STORAGE_S3_ACCESS_KEY=minioadmin
STORAGE_S3_SECRET_KEY=minioadmin
STORAGE_S3_PUBLIC_URL=https://minio.example.com/marvin-assets
```

**MinIO Docker Setup:**

```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  -v /data/minio:/data \
  minio/minio server /data --console-address ":9001"
```

### CDN Integration

**AWS CloudFront + S3:**

```bash
# .env
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=marvin-assets
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ACCESS_KEY=...
STORAGE_S3_SECRET_KEY=...
STORAGE_S3_PUBLIC_URL=https://d111111abcdef8.cloudfront.net
```

**Cloudflare R2 + Custom Domain:**

```bash
# .env
STORAGE_S3_PUBLIC_URL=https://assets.example.com
```

Configure DNS:

```
assets.example.com  CNAME  abc123.r2.dev
```

**BunnyCDN + S3:**

1. Create BunnyCDN pull zone
2. Set S3 bucket as origin
3. Use BunnyCDN URL as `STORAGE_S3_PUBLIC_URL`

## Asset Relationships

### Attaching Assets to Entries

Assets can be attached to Entries via the `entry_assets` junction table. This allows the same asset to be used in multiple entries with different placement metadata.

**Placement Fields:**

- `role` - Usage role: `hero`, `featured`, `support`, `inline`, `download`
- `usage` - Domain hint: `material`, `process`, `detail`, `texture`, `workshop`
- `position` - Display order (integer)
- `focal_point` - CSS focal point for cropping: `"50% 50%"`
- `caption` - Optional caption for this placement
- `metadata` - Placement-specific JSON metadata

**Creating Relationships:**

Via Platform API:

```bash
# Attach asset to entry
curl -X POST https://marvin.example.com/api/platform/entries/my-entry/assets \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "hero",
    "position": 0,
    "focal_point": "50% 30%",
    "caption": "Hero image for homepage"
  }'
```

Via SDK:

```typescript
await client.entries.addAsset('my-entry', {
  assetId: '550e8400-e29b-41d4-a716-446655440000',
  role: 'hero',
  position: 0,
  focalPoint: '50% 30%',
  caption: 'Hero image for homepage'
});
```

**Fetching Entry with Assets:**

```typescript
const entry = await client.entries.get('my-entry', {
  include: ['assets']
});

// Assets are sorted by position
entry.assets.forEach(asset => {
  console.log(`${asset.role}: ${asset.name} at ${asset.focalPoint}`);
});
```

**Updating Placement:**

```typescript
await client.entries.updateAsset('my-entry', assetId, {
  role: 'featured',
  position: 1,
  caption: 'Updated caption'
});
```

**Removing from Entry:**

```typescript
await client.entries.removeAsset('my-entry', assetId);
```

### Usage Examples

**Hero Image:**

```typescript
await client.entries.addAsset('homepage', {
  assetId: heroImageId,
  role: 'hero',
  position: 0,
  focalPoint: '50% 30%'  // Focus on upper portion
});
```

**Image Gallery:**

```typescript
const galleryImages = [image1, image2, image3];

for (const [index, imageId] of galleryImages.entries()) {
  await client.entries.addAsset('gallery-post', {
    assetId: imageId,
    role: 'inline',
    usage: 'gallery',
    position: index
  });
}
```

**Downloadable PDF:**

```typescript
await client.entries.addAsset('whitepaper', {
  assetId: pdfAssetId,
  role: 'download',
  usage: 'document',
  caption: 'Download PDF (2.5MB)'
});
```

## Publishing Assets

The Publishing API provides read-only access to assets for external sites.

### List Published Assets

**CLI:**

```bash
marvin publish assets --workspace acme-corp
```

**SDK:**

```typescript
import { createPublishingClient } from '@inneropen/marvin-sdk/assets';

const client = createPublishingClient({
  apiUrl: 'https://marvin.example.com'
});

const assets = await client.assets.list('acme-corp', {
  assetType: 'image',
  limit: 50
});
```

**API:**

```bash
curl https://marvin.example.com/api/publish/acme-corp/assets \
  -G \
  -d "asset_type=image" \
  -d "limit=50"
```

**Response:** `AssetSummary` (excludes internal fields)

```json
[
  {
    "id": "550e8400-...",
    "slug": "hero-image",
    "name": "Hero Image",
    "mime_type": "image/jpeg",
    "alt_text": "Homepage hero"
  }
]
```

### Get Single Published Asset

**CLI:**

```bash
marvin publish asset hero-image --workspace acme-corp
```

**SDK:**

```typescript
const asset = await client.assets.get('acme-corp', 'hero-image');
```

**API:**

```bash
curl https://marvin.example.com/api/publish/acme-corp/assets/hero-image
```

### Integration with External Site

**Next.js Example:**

```typescript
// lib/marvin.ts
import { createPublishingClient } from '@inneropen/marvin-sdk/assets';

export const marvinClient = createPublishingClient({
  apiUrl: process.env.MARVIN_API_URL!
});

// pages/index.tsx
import { marvinClient } from '../lib/marvin';

export async function getStaticProps() {
  const assets = await marvinClient.assets.list('acme-corp', {
    assetType: 'image'
  });

  return {
    props: { assets },
    revalidate: 3600  // Revalidate every hour
  };
}

export default function Home({ assets }) {
  return (
    <div>
      {assets.map(asset => (
        <img
          key={asset.id}
          src={asset.publicUrl}
          alt={asset.altText}
        />
      ))}
    </div>
  );
}
```

**Gatsby Example:**

```javascript
// gatsby-node.js
const { createPublishingClient } = require('@inneropen/marvin-sdk/assets');

exports.sourceNodes = async ({ actions, createNodeId, createContentDigest }) => {
  const { createNode } = actions;

  const client = createPublishingClient({
    apiUrl: process.env.MARVIN_API_URL
  });

  const assets = await client.assets.list('acme-corp');

  assets.forEach(asset => {
    createNode({
      ...asset,
      id: createNodeId(`MarvinAsset-${asset.id}`),
      parent: null,
      children: [],
      internal: {
        type: 'MarvinAsset',
        contentDigest: createContentDigest(asset)
      }
    });
  });
};

// src/pages/gallery.js
import { graphql } from 'gatsby';

export const query = graphql`
  query {
    allMarvinAsset(filter: { assetType: { eq: "image" } }) {
      nodes {
        id
        slug
        name
        altText
        publicUrl
      }
    }
  }
`;

export default function Gallery({ data }) {
  return (
    <div>
      {data.allMarvinAsset.nodes.map(asset => (
        <img key={asset.id} src={asset.publicUrl} alt={asset.altText} />
      ))}
    </div>
  );
}
```

## Advanced Usage

### Custom Metadata Fields

Store domain-specific metadata:

```typescript
const asset = await client.assets.upload(file, {
  slug: 'product-photo',
  name: 'Product Photo',
  metadata: {
    photographer: 'Jane Doe',
    camera: 'Canon EOS R5',
    lens: 'RF 24-70mm f/2.8',
    settings: {
      iso: 100,
      aperture: 'f/8',
      shutter: '1/125'
    },
    keywords: ['product', 'red', 'widget'],
    license: 'CC-BY-SA',
    location: {
      lat: 37.7749,
      lng: -122.4194,
      city: 'San Francisco'
    }
  }
});
```

### Deduplication by Checksum

Avoid uploading duplicate files:

```typescript
const checksum = await calculateChecksum(file);
const existing = await client.assets.list({
  checksum: checksum  // Hypothetical filter
});

if (existing.length > 0) {
  console.log('File already exists:', existing[0].publicUrl);
} else {
  const asset = await client.assets.upload(file, {...});
}
```

### Responsive Images

Use asset metadata to generate responsive HTML:

```typescript
const asset = await client.assets.get('hero-image');

const imgSrcSet = `
  ${asset.publicUrl}?w=400 400w,
  ${asset.publicUrl}?w=800 800w,
  ${asset.publicUrl}?w=1200 1200w,
  ${asset.publicUrl}?w=1600 1600w
`.trim();

return (
  <img
    src={asset.publicUrl}
    srcSet={imgSrcSet}
    sizes="(max-width: 600px) 400px, (max-width: 1200px) 800px, 1200px"
    alt={asset.altText}
    width={asset.width}
    height={asset.height}
  />
);
```

**Note:** Image resizing requires a processing service (see Architecture docs for extension points).

### Lazy Loading with Focal Point

Use focal point for cropped previews:

```typescript
const asset = await client.entries.getAssets('my-entry');

// Asset has placement.focalPoint = "50% 30%"
return (
  <div
    style={{
      backgroundImage: `url(${asset.publicUrl})`,
      backgroundPosition: asset.placement.focalPoint,
      backgroundSize: 'cover'
    }}
  >
    <img
      src={asset.publicUrl}
      alt={asset.altText}
      loading="lazy"
      style={{ opacity: 0 }}  // Hidden, just for SEO
    />
  </div>
);
```

## Troubleshooting

### Upload Fails with "File too large"

**Cause:** File exceeds `ASSET_MAX_FILE_SIZE` limit

**Solution:**

```bash
# Increase limit in .env (in bytes)
ASSET_MAX_FILE_SIZE=200000000  # 200MB
```

Or compress the file before uploading.

### Upload Fails with "Invalid MIME type"

**Cause:** File type not in `ASSET_ALLOWED_MIME_TYPES` allowlist

**Solution:**

```bash
# Allow all MIME types (default)
ASSET_ALLOWED_MIME_TYPES=

# Or add specific types
ASSET_ALLOWED_MIME_TYPES=["image/jpeg", "image/png", "image/webp", "application/pdf"]
```

### S3 Upload Returns 403 Forbidden

**Causes:**

1. Invalid AWS credentials
2. Insufficient IAM permissions
3. Bucket doesn't exist
4. Bucket in wrong region

**Diagnosis:**

```bash
# Test credentials
aws s3 ls s3://marvin-assets --profile marvin

# Check bucket region
aws s3api get-bucket-location --bucket marvin-assets
```

**Solutions:**

- Verify `STORAGE_S3_ACCESS_KEY` and `STORAGE_S3_SECRET_KEY`
- Check IAM policy includes `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- Verify `STORAGE_S3_BUCKET` matches actual bucket name
- Ensure `STORAGE_S3_REGION` matches bucket region

### Public URL Returns 404

**Causes:**

1. **Local Storage:** Static file serving not configured
2. **S3:** Bucket policy doesn't allow public reads
3. **CDN:** CDN not configured or cache not populated

**Solutions:**

**Local Storage:**

Configure Nginx/Apache to serve `STORAGE_LOCAL_ROOT` at `STORAGE_LOCAL_PUBLIC_URL`.

**S3 Public Bucket:**

Add bucket policy (see S3 configuration above).

**S3 Private with Signed URLs:**

Extend storage provider to generate signed URLs (see Architecture docs).

### Image Dimensions Not Detected

**Causes:**

1. Pillow not installed
2. Corrupted image file
3. Unsupported image format

**Diagnosis:**

```python
from PIL import Image
img = Image.open('test.jpg')
print(img.size)  # Should print (width, height)
```

**Solutions:**

- Install Pillow: `pip install Pillow`
- Verify file is valid image: `file test.jpg`
- Convert to supported format (JPEG, PNG, GIF, WebP, etc.)

### Assets Not Showing in Publishing API

**Cause:** Assets are workspace-scoped, ensure correct workspace slug

**Diagnosis:**

```bash
# List assets for correct workspace
curl https://marvin.example.com/api/publish/correct-slug/assets

# Verify workspace slug
marvin workspaces list
```

**Solution:**

Use the exact workspace slug from the workspace list.

### SDK Upload Returns "Content-Type: multipart/form-data" Error

**Cause:** SDK HttpClient bug (fixed in this release)

**Solution:**

Update SDK to latest version:

```bash
npm install @inneropen/marvin-sdk@latest
```

## Summary

Marvin's asset system provides:

✅ **Simple Upload API** - Clients provide editorial metadata, server generates technical metadata
✅ **Automatic Metadata Extraction** - MIME type, dimensions, checksum, etc.
✅ **Flexible Storage** - Local filesystem or S3-compatible services
✅ **Asset Relationships** - Rich placement metadata for Entry-Asset associations
✅ **Publishing API** - Read-only access for external sites

**Next Steps:**

- Read [ASSET-ARCHITECTURE.md](./ASSET-ARCHITECTURE.md) for deep dive into internals
- Explore extension points for image processing, AI tagging, etc.
- Configure your preferred storage provider
- Integrate with your frontend application

**Need Help?**

- Check logs: `marvin logs` or `/var/log/marvin/`
- Run health check: See Architecture docs
- File an issue: GitHub repo issue tracker
