# Phase 3: Publishing API

This is where Marvin starts becoming special.

## The Separation

Marvin has two completely separate APIs:

### Admin API (What we've built so far)
```
/api/entry-types
/api/entries
/api/collections
```

**Purpose**: Create, edit, organize, review content  
**Authentication**: User sessions (Bearer tokens from logged-in users)  
**Scope**: Current user's workspace  
**Sees**: Everything - drafts, archived, unpublished, admin fields

### Publishing API (Phase 3)
```
/api/publish/{workspace}
/api/publish/{workspace}/entries
/api/publish/{workspace}/pages/about
/api/publish/{workspace}/collections/projects
```

**Purpose**: Read published content for external sites  
**Authentication**: Site client tokens (long-lived, read-only)  
**Scope**: Specific workspace by slug  
**Sees**: Only published content, only public fields

## Why This Matters

**Astro doesn't care about your admin API. It only talks to the publish API.**

This means:
- Your blog/store/docs site never knows about drafts
- Your public site never sees admin metadata
- You can have multiple sites reading from one workspace
- Each site gets its own token with specific permissions

## Phase 3 Routes

### 1. Workspace Info
```http
GET /api/publish/{workspace}
```

Returns workspace metadata for site consumption.

**Response:**
```json
{
  "slug": "mash-burn",
  "name": "Mash & Burn Co.",
  "description": "Handcrafted home goods",
  "metadata": {
    "site_title": "Mash & Burn",
    "tagline": "Made by hand, made to last"
  }
}
```

### 2. List Published Entries
```http
GET /api/publish/{workspace}/entries
GET /api/publish/{workspace}/entries?type=article
GET /api/publish/{workspace}/entries?collection=featured
GET /api/publish/{workspace}/entries?page=2&limit=20
```

Returns all published entries, optionally filtered.

**Response:**
```json
{
  "data": [
    {
      "slug": "linen-napkins",
      "title": "Linen Napkins",
      "entry_type": "product",
      "summary": "Hand-hemmed Irish linen",
      "published_at": "2026-01-15T10:30:00Z",
      "collections": ["home-goods", "featured"],
      "metadata": {
        "color": "natural",
        "price": 42
      }
    }
  ],
  "meta": {
    "total": 45,
    "page": 1,
    "limit": 20
  }
}
```

### 3. Get Published Entry by Slug
```http
GET /api/publish/{workspace}/entries/{slug}
```

Returns full entry with Markdown content.

**Response:**
```json
{
  "slug": "linen-napkins",
  "title": "Linen Napkins",
  "entry_type": "product",
  "summary": "Hand-hemmed Irish linen napkins",
  "content_markdown": "# Linen Napkins\n\n...",
  "published_at": "2026-01-15T10:30:00Z",
  "collections": [
    {
      "slug": "home-goods",
      "name": "Home Goods"
    }
  ],
  "metadata": {
    "color": "natural",
    "price": 42,
    "material": "100% linen"
  },
  "assets": [
    {
      "slug": "napkin-flat-lay",
      "url": "/api/publish/mash-burn/assets/napkin-flat-lay",
      "alt_text": "Folded napkins on a table",
      "role": "featured"
    }
  ]
}
```

### 4. Get Entry by Type and Slug
```http
GET /api/publish/{workspace}/pages/{slug}
GET /api/publish/{workspace}/articles/{slug}
GET /api/publish/{workspace}/projects/{slug}
```

Convenience routes that filter by entry type.

Same response as `/entries/{slug}` but pre-filtered by type.

### 5. Get Collection with Entries
```http
GET /api/publish/{workspace}/collections/{collection_slug}
```

Returns collection metadata and its published entries.

**Response:**
```json
{
  "slug": "featured",
  "name": "Featured",
  "description": "Our favorite pieces",
  "entry_count": 12,
  "entries": [
    {
      "slug": "linen-napkins",
      "title": "Linen Napkins",
      "entry_type": "product",
      "summary": "Hand-hemmed Irish linen",
      "published_at": "2026-01-15T10:30:00Z"
    }
  ]
}
```

### 6. Get Asset
```http
GET /api/publish/{workspace}/assets/{slug}
```

Serves or redirects to the asset file.

Returns:
- `200 OK` with file content and `Content-Type` header
- `302 Found` redirect to cloud storage (S3)

## Authentication

All publishing API requests require a site client token:

```http
GET /api/publish/mash-burn/entries
Authorization: Bearer sc_live_abc123xyz...
```

### Token Validation Flow

1. Extract token from `Authorization: Bearer {token}` header
2. Parse token prefix (`sc_live_` or `sc_test_`)
3. Hash token and look up in `site_clients` table
4. Verify site client is active (not revoked)
5. Verify `{workspace}` in URL matches site client's workspace
6. Allow request if all checks pass

### Token Format

```
sc_live_abc123xyz456...  (production)
sc_test_abc123xyz456...  (development)
```

Tokens are:
- 48+ characters
- Prefixed for environment
- Hashed before storage
- Never shown again after creation

## What Gets Filtered

The publishing API **never** returns:

- ❌ Draft entries (`status != 'published'`)
- ❌ Archived entries
- ❌ Admin notes or private fields
- ❌ User information (created_by, updated_by)
- ❌ Edit history or revision data
- ❌ Unpublished collections
- ❌ Admin-only metadata

The publishing API **only** returns:

- ✅ Published entries (`status = 'published'`)
- ✅ Public metadata and content
- ✅ Asset URLs and alt text
- ✅ Collection membership
- ✅ Public-facing frontmatter

## Implementation Order

### Step 1: Site Clients Table
```sql
site_clients
  id
  group_id
  name
  slug
  token_hash (bcrypt)
  permissions (json: ["read:entries", "read:collections", "read:assets"])
  is_active
  last_used_at
  created_at
  revoked_at
```

**Routes needed:**
- `POST /api/site-clients` - Generate new token (shows plaintext once)
- `GET /api/site-clients` - List site clients for workspace
- `PATCH /api/site-clients/{id}` - Update name/permissions
- `DELETE /api/site-clients/{id}` - Revoke token

### Step 2: Auth Middleware

**File**: `src/marvin/routes/_base/publishing_auth.py`

```python
async def validate_site_client_token(
    authorization: str,
    workspace_slug: str,
    db: Session
) -> SiteClient:
    """
    Validate site client token and ensure workspace match.
    
    Raises:
        HTTPException 401: Invalid or missing token
        HTTPException 403: Workspace mismatch
    """
    # Extract token
    # Hash token
    # Look up site client
    # Verify active and workspace match
    # Update last_used_at
    # Return site client
```

### Step 3: Publishing Router

**File**: `src/marvin/routes/publish/__init__.py`

```python
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/publish/{workspace_slug}")

# Dependency that validates token and gets workspace
def get_publishing_context(
    workspace_slug: str,
    authorization: str = Header(...),
    session: Session = Depends(get_session)
) -> PublishingContext:
    site_client = validate_site_client_token(authorization, workspace_slug, session)
    group = get_group_by_slug(workspace_slug, session)
    return PublishingContext(site_client=site_client, group=group)
```

### Step 4: Publishing Routes

**File**: `src/marvin/routes/publish/entries.py`

```python
@router.get("/entries")
def list_published_entries(
    ctx: PublishingContext = Depends(get_publishing_context),
    entry_type: str | None = None,
    collection: str | None = None,
    page: int = 1,
    limit: int = 20
) -> PublishedEntriesResponse:
    """List published entries."""
    # Query entries where status='published' and group_id=ctx.group.id
    # Filter by entry_type if provided
    # Filter by collection if provided
    # Paginate
    # Return only public fields
```

### Step 5: Frontmatter Generation

**File**: `src/marvin/services/publishing/frontmatter.py`

```python
def generate_frontmatter(entry: Entry) -> dict:
    """
    Generate Astro-compatible frontmatter from entry.
    
    Combines:
    - Real columns (title, slug, published_at)
    - Entry metadata JSON
    - Never includes admin fields
    """
    frontmatter = {
        "title": entry.title,
        "slug": entry.slug,
        "type": entry.entry_type.slug,
        "published": entry.published_at.isoformat(),
    }
    
    if entry.summary:
        frontmatter["description"] = entry.summary
    
    # Merge metadata JSON
    if entry.metadata:
        frontmatter.update(entry.metadata)
    
    return frontmatter
```

## Testing Strategy

### Manual Testing
```bash
# 1. Create site client via admin API
TOKEN=$(curl -X POST http://localhost:8080/api/site-clients \
  -H "Authorization: Bearer {admin_token}" \
  -d '{"name": "My Blog"}' | jq -r '.token')

# 2. Test publishing API
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/publish/my-workspace/entries

# 3. Verify only published content returned
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/publish/my-workspace/entries/draft-post
# Should return 404

# 4. Test wrong workspace
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/publish/different-workspace/entries
# Should return 403
```

### Automated Tests
- Token validation (valid, invalid, revoked, expired)
- Workspace matching (correct, wrong, missing)
- Published filter (only published, never drafts)
- Pagination (page, limit, total)
- Collection filtering
- Entry type filtering
- Asset URLs and serving

## Astro Integration Example

**File**: `src/lib/marvin.ts`

```typescript
const MARVIN_API = import.meta.env.MARVIN_API_URL;
const MARVIN_TOKEN = import.meta.env.MARVIN_SITE_TOKEN;
const WORKSPACE = import.meta.env.MARVIN_WORKSPACE;

export async function getPublishedEntries(type?: string) {
  const url = type 
    ? `${MARVIN_API}/api/publish/${WORKSPACE}/${type}s`
    : `${MARVIN_API}/api/publish/${WORKSPACE}/entries`;
    
  const res = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${MARVIN_TOKEN}`
    }
  });
  
  if (!res.ok) throw new Error('Failed to fetch entries');
  return res.json();
}

export async function getEntry(slug: string, type?: string) {
  const url = type
    ? `${MARVIN_API}/api/publish/${WORKSPACE}/${type}s/${slug}`
    : `${MARVIN_API}/api/publish/${WORKSPACE}/entries/${slug}`;
    
  const res = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${MARVIN_TOKEN}`
    }
  });
  
  if (!res.ok) return null;
  return res.json();
}
```

**File**: `src/pages/[...slug].astro`

```astro
---
import { getEntry } from '../lib/marvin';

const { slug } = Astro.params;
const entry = await getEntry(slug);

if (!entry) return Astro.redirect('/404');
---

<article>
  <h1>{entry.title}</h1>
  <time>{new Date(entry.published_at).toLocaleDateString()}</time>
  <div set:html={entry.content_html} />
</article>
```

## Success Criteria

Phase 3 is complete when:

- ✅ Site client tokens can be created via admin API
- ✅ Tokens are hashed and stored securely
- ✅ Publishing API validates tokens
- ✅ Publishing API filters to published content only
- ✅ Publishing API enforces workspace matching
- ✅ All five core routes return correct data
- ✅ Astro can fetch and render published entries
- ✅ Multiple sites can use different tokens for same workspace
- ✅ Revoking a token immediately blocks access

## Security Checklist

Before Phase 3 ships:

- [ ] Tokens are hashed with bcrypt (cost 12+)
- [ ] Tokens never logged or exposed in responses
- [ ] Rate limiting per site client (1000 req/hour)
- [ ] Workspace mismatch returns 403, not 404
- [ ] Invalid token returns 401 with no details
- [ ] Status filter hardcoded to `published` (not a query param)
- [ ] Admin fields explicitly excluded from response schemas
- [ ] SQL injection prevention (use ORM, parameterized queries)
- [ ] CORS configured for expected domains only

## Why This Is Special

Most CMSs blur the line between admin and public APIs. Marvin doesn't.

**Admin API**: Full power, full access, user sessions  
**Publishing API**: Read-only, published-only, site tokens

This means:
- External sites can't accidentally expose drafts
- You can give each site exactly the permissions it needs
- Your admin workflow never leaks into your public site
- You can version the publishing API separately
- Public sites stay fast (no auth session overhead)

**This separation is what makes Marvin a publishing engine, not just a CMS.**
