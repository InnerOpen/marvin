> **Superseded (2026-09-25):** this page predates the current API. See the manual — https://inneropen.github.io/marvin/whats-new/publishing-api/ — which follows the code.

# Publishing API

The Publishing API is a read-only interface for external sites to consume published content from Marvin workspaces. It is authenticated via site client tokens and scoped to one workspace.

## Authentication

All publishing API requests must include a bearer token:

```http
GET /api/publish/{group_slug}/entries
Authorization: Bearer <site_client_token>
```

Token validation flow:

1. Extract token from `Authorization: Bearer <token>` header
2. Hash token using bcrypt
3. Look up site client by token hash
4. Verify site client is active (not revoked)
5. Resolve group/workspace from site client
6. Verify path group_slug matches site client's group

## Base URL

```
/api/publish/{group_slug}
```

The `group_slug` is the slug of the workspace/group that the requesting site client is scoped to.

## Endpoints

### List Collections

```http
GET /api/publish/{group_slug}/collections
Authorization: Bearer <site_client_token>
```

Returns all published collections visible to the site client.

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "slug": "home-goods",
      "name": "Home Goods",
      "description": "A curated collection of home items",
      "entry_count": 12,
      "entries": [
        {
          "id": "uuid",
          "slug": "linen-napkins",
          "title": "Linen Napkins"
        }
      ]
    }
  ],
  "meta": {
    "total": 3,
    "page": 1,
    "page_size": 20
  }
}
```

### List Entries

```http
GET /api/publish/{group_slug}/entries?page=1&limit=20&collection_slug=home-goods
Authorization: Bearer <site_client_token>
```

Returns all published entries, optionally filtered by collection.

**Query Parameters:**
- `page`: Page number (default: 1)
- `limit`: Entries per page (default: 20, max: 100)
- `collection_slug`: Filter by collection slug (optional)
- `entry_type`: Filter by entry type (optional)

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "slug": "linen-napkins",
      "title": "Linen Napkins",
      "entry_type": "product",
      "summary": "High-quality Irish linen napkins for everyday use",
      "published_at": "2025-01-15T10:30:00Z",
      "collections": ["home-goods"],
      "assets": [
        {
          "id": "uuid",
          "slug": "napkin-flat-lay",
          "url": "/api/publish/group/assets/napkin-flat-lay",
          "alt_text": "Folded napkins on a table",
          "role": "featured",
          "usage": "detail",
          "position": 0,
          "focal_point": "50% 50%"
        }
      ]
    }
  ],
  "meta": {
    "total": 12,
    "page": 1,
    "page_size": 20
  }
}
```

### Get Entry

```http
GET /api/publish/{group_slug}/entries/{entry_slug}
Authorization: Bearer <site_client_token>
```

Returns a single published entry with full Markdown content and metadata.

**Response:**

```json
{
  "id": "uuid",
  "slug": "linen-napkins",
  "title": "Linen Napkins",
  "entry_type": "product",
  "summary": "High-quality Irish linen napkins for everyday use",
  "content_markdown": "# Linen Napkins\n\n...",
  "frontmatter": {
    "color": "ivory",
    "size": "18x18",
    "material": "100% linen",
    "care": "machine wash warm"
  },
  "published_at": "2025-01-15T10:30:00Z",
  "collections": [
    {
      "id": "uuid",
      "slug": "home-goods",
      "name": "Home Goods"
    }
  ],
  "assets": [
    {
      "id": "uuid",
      "slug": "napkin-flat-lay",
      "name": "Flat lay of napkins",
      "url": "/api/publish/group/assets/napkin-flat-lay",
      "alt_text": "Folded napkins on a table",
      "mime_type": "image/jpeg",
      "role": "featured",
      "usage": "detail",
      "position": 0,
      "focal_point": "50% 50%",
      "caption": "Folded linen napkins ready for packing"
    }
  ]
}
```

### List Entry Types

```http
GET /api/publish/{group_slug}/entry-types
Authorization: Bearer <site_client_token>
```

Returns all entry types in the workspace with their rendering and capability metadata.

**Response:**

```json
{
  "data": [
    {
      "slug": "page",
      "name": "Page",
      "is_rendered": true,
      "rendering": {
        "renderer": "page",
        "package": "@inneropen/marvin-renderers-core",
        "version": null,
        "config": null
      },
      "capabilities": {
        "publishable": true,
        "submittable": false,
        "routable": true
      }
    },
    {
      "slug": "navigation-item",
      "name": "Navigation Item",
      "is_rendered": true,
      "rendering": {
        "renderer": "navigation",
        "package": "@inneropen/marvin-renderers-core"
      },
      "capabilities": {
        "publishable": true,
        "submittable": false,
        "routable": false
      }
    }
  ]
}
```

Used by the SDK `renderers.list()` method and the CLI `publish renderers` command. The `is_rendered` flag allows frontends to filter to only entry types that have a corresponding renderer component.

### List Assets

```http
GET /api/publish/{group_slug}/assets?limit=20&mime_type=image/jpeg
Authorization: Bearer <site_client_token>
```

Returns all published assets available in the workspace.

**Query Parameters:**
- `page`: Page number (default: 1)
- `limit`: Assets per page (default: 20, max: 100)
- `mime_type`: Filter by MIME type (optional)

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "slug": "napkin-flat-lay",
      "name": "Flat lay of napkins",
      "url": "/api/publish/group/assets/napkin-flat-lay",
      "alt_text": "Folded napkins on a table",
      "mime_type": "image/jpeg",
      "width": 1200,
      "height": 800,
      "metadata": {
        "tone": "linen"
      }
    }
  ],
  "meta": {
    "total": 45,
    "page": 1,
    "page_size": 20
  }
}
```

### Get Asset

```http
GET /api/publish/{group_slug}/assets/{asset_slug}
Authorization: Bearer <site_client_token>
```

Downloads or redirects to the asset file.

May return:
- `200 OK` with file content and appropriate `Content-Type` header
- `302 Found` redirect to cloud storage (S3, etc)

## Error Responses

### 401 Unauthorized

Missing, invalid, or revoked token.

```json
{
  "error": "Unauthorized",
  "message": "Invalid or expired site client token"
}
```

### 403 Forbidden

Site client exists but workspace doesn't match.

```json
{
  "error": "Forbidden",
  "message": "Site client does not have access to this workspace"
}
```

### 404 Not Found

Entry, collection, or asset not found or not published.

```json
{
  "error": "Not Found",
  "message": "Entry not found or not published"
}
```

### 429 Too Many Requests

Rate limited. Include `Retry-After` header.

```json
{
  "error": "Too Many Requests",
  "message": "Rate limit exceeded",
  "retry_after": 60
}
```

## Response Guarantees

Publishing API responses are boring and stable:

- ✅ Include: ID, slug, title, type, status, markdown content, frontmatter, assets, timestamps
- ❌ Never expose: admin notes, draft history, private metadata, user permissions, unpublished content

Asset responses separate reusable file metadata from entry-specific placement metadata:

- Asset fields: `slug`, `url`, `mime_type`, `width`, `height`, `alt_text`, `metadata`
- Placement fields on entry asset lists: `role`, `usage`, `position`, `focal_point`, `caption`, `placement_metadata`

This allows one uploaded asset to be reused differently across entries without duplicating the file record.

## Rate Limiting

Site clients are rate-limited:

- Default: 1000 requests per hour per site client
- Shared pool: Multiple tokens from same workspace share one pool
- Header: `X-RateLimit-Remaining: 999`

## Versioning

API version is NOT in the URL. When breaking changes are needed:

1. Add new endpoint: `/api/publish/v2/...`
2. Keep v1 running for 6+ months
3. Migrate site clients before deprecation
4. Send email notifications before sunset

## Astro Integration Example

```javascript
// src/lib/marvin.js
const MARVIN_BASE = import.meta.env.MARVIN_API_URL;
const MARVIN_TOKEN = import.meta.env.MARVIN_SITE_CLIENT_TOKEN;
const GROUP_SLUG = import.meta.env.MARVIN_GROUP_SLUG;

export async function getPublishedEntries() {
  const res = await fetch(
    `${MARVIN_BASE}/api/publish/${GROUP_SLUG}/entries`,
    {
      headers: {
        'Authorization': `Bearer ${MARVIN_TOKEN}`
      }
    }
  );
  return res.json();
}

export async function getEntry(slug) {
  const res = await fetch(
    `${MARVIN_BASE}/api/publish/${GROUP_SLUG}/entries/${slug}`,
    {
      headers: {
        'Authorization': `Bearer ${MARVIN_TOKEN}`
      }
    }
  );
  return res.json();
}
```
