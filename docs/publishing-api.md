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

Returns a single published entry with full Markdown content and metadata. Media links in the entry are
resolved under `embeds` (see [Media embeds](#media-embeds)); list items carry the same `embeds`.

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

## Media embeds

Entries carry their media players under `embeds`, on both the entry (`GET .../entries/{slug}`) and every
list item (`GET .../entries`, collection and resource entry lists). Stored markdown is never rewritten:
`data` still holds the link, and a site that ignores `embeds` keeps showing it as a link.

A link becomes an embed when it is from an allow-listed provider (YouTube, Vimeo, Spotify, SoundCloud,
Apple Music, Apple Podcasts, TIDAL, Simplecast, Transistor; Bandcamp only from its embed code) and either

- sits **alone on its own line** in a markdown field (a paragraph that is exactly the URL; `<https://…>`,
  `[text](https://…)` and a URL inside a sentence, list, quote or code stay links), unless the field sets
  `autoEmbed: false`; or
- is the value of an `embed` field.

`embeds` is keyed by the **URL exactly as written** in the field (trimmed; http(s) only), so a renderer
that meets a paragraph consisting of one link looks the link's text up in `embeds` and, on a hit, uses
the entry's `html` in place of the paragraph. `embeds` is `{}` when the entry has none.

```json
"embeds": {
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ": {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "canonicalUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "provider": "youtube",
    "providerName": "YouTube",
    "kind": "video",
    "status": "ok",
    "title": "Never Gonna Give You Up",
    "authorName": "Rick Astley",
    "thumbnailUrl": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "iframe": {
      "src": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
      "title": "Never Gonna Give You Up",
      "allow": "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen",
      "sandbox": "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-presentation",
      "referrerpolicy": "strict-origin-when-cross-origin",
      "aspectRatio": "16/9",
      "height": null
    },
    "link": { "href": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Never Gonna Give You Up", "providerName": "YouTube" },
    "html": "<figure class=\"marvin-embed marvin-embed--video marvin-embed--facade\" …>…</figure>"
  }
}
```

| Field | Notes |
|---|---|
| `kind` | `video`, `audio`, `podcast` or `playlist` |
| `status` | `ok` — `iframe` is set; `link` — no safe player (a plain Bandcamp page, a link whose player id needs a lookup that hasn't happened yet); `unavailable` — the provider says private, removed or blocked. For `link`/`unavailable` show `link` |
| `title`, `authorName`, `thumbnailUrl` | from the provider's oEmbed; `null` until Marvin has looked the link up. The thumbnail is the provider's URL — loading it contacts the provider |
| `iframe` | only when `status` is `ok`. Every attribute comes from Marvin's provider registry; the `src` is rebuilt by Marvin and always on one of `site.embeds.frameSources`. Video players carry `aspectRatio` (e.g. `"16/9"`, `"9/16"` for Shorts), audio/podcast/playlist players a fixed `height` in px |
| `html` | ready-to-insert HTML built by Marvin per `site.embeds.mode`; every attribute is escaped |

**`html` shapes.**

- *click_to_load* (the default):
  `<figure class="marvin-embed marvin-embed--{kind} marvin-embed--facade" data-provider="youtube" style="--marvin-embed-aspect:16/9">`
  holding a `<button type="button" class="marvin-embed__load" data-marvin-embed-src="…" data-marvin-embed-attrs="{…}" data-marvin-embed-hosts="[…]">`
  (spans `marvin-embed__provider`, `marvin-embed__title`, `marvin-embed__consent`) and then a plain
  `<a class="marvin-embed__link" href="…" rel="noopener noreferrer">` fallback. Nothing third-party loads
  until the visitor clicks; no remote thumbnail is used. `data-marvin-embed-attrs` is a JSON object of
  string attributes for the iframe (`src`, `title`, `allow`, `sandbox`, `referrerpolicy`, `loading`);
  `data-marvin-embed-hosts` is a JSON list of the hostnames the src may load from. A loader should check
  the src host against that list before creating the iframe. Fullscreen is granted through `allow`.
- *direct*: the same figure (without `marvin-embed--facade`) holding the `<iframe>` itself.
- *link card* (`status` `link`/`unavailable`): `<a class="marvin-embed-link" href="…" rel="noopener noreferrer" data-provider="…">`.

Sizing travels on the figure as a CSS custom property: `--marvin-embed-aspect:{ratio}` for video players,
`--marvin-embed-height:{n}px` for fixed-height ones.

Publishing reads never contact a provider: details come from Marvin's embed cache, which the editor's
preview and a save of the entry fill. A link with nothing cached yet still publishes, as a player when
the link alone is enough to build one, else as a link card.

**`site.embeds`** (on `GET /api/publish/{workspace_slug}/site`, beside `site.seo`, always present):

```json
"embeds": {
  "mode": "click_to_load",
  "consentText": "Loading this player connects to {provider}, which may set cookies.",
  "frameSources": ["https://bandcamp.com", "https://embed.music.apple.com", "https://www.youtube-nocookie.com", "…"]
}
```

`mode` is `click_to_load` or `direct` (Site settings → Embeds & privacy). `consentText` may contain
`{provider}`, replaced with the provider's name; Marvin's own facade html already has it substituted.
`frameSources` lists every origin a Marvin-built player may load from, for a site's `frame-src` CSP.

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
