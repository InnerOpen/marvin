# Publishing API Implementation Plan

**Goal**: Validate that Marvin can power a real Astro website as the single source of truth.

**Target**: Mash & Burn Co. website

---

## Current State Analysis

### ✅ Already Implemented

**Endpoints**:
- `GET /api/publish/{workspace}` - Workspace info
- `GET /api/publish/{workspace}/entries` - List published entries
  - Filters: `entry_type`, `collection`, pagination
- `GET /api/publish/{workspace}/entries/{slug}` - Get single entry
  - Includes: assets, collections, metadata
- `GET /api/publish/{workspace}/collections/{slug}` - Get collection with entries
- `GET /api/publish/{workspace}/assets/{slug}` - Get asset metadata

**Authentication**:
- API Client tokens (`marvin_sk_*`)
- Workspace scoping via `get_publishing_context`
- Only returns `status='published'` content

**Schemas**:
- `PublishedEntryRead` - Full entry with markdown, metadata, assets
- `PublishedEntryListItem` - Summary for lists
- `PublishedCollectionRead` - Collection with entries
- `PublishedAssetRead` - Asset metadata
- `WorkspaceInfo` - Basic workspace info

### ❌ Missing Features

1. **Collections List Endpoint**
   - `GET /api/publish/{workspace}/collections`
   - Needed for building navigation

2. **Entry Filters**
   - `slug` filter (for batch fetching specific pages)
   - `updated_since` filter (for incremental builds)

3. **Resources in Entry Response**
   - Currently only includes assets
   - Should include resources with role/quantity/unit

4. **Performance Optimizations**
   - Eager loading for relationships
   - Avoid N+1 queries on collection slugs, entry_type slugs

5. **Entry Type Information**
   - Entry response only has `entry_type` slug
   - May need `entry_type_name` or separate endpoint

---

## Implementation Tasks

### Task 1: Add Collections List Endpoint

**Endpoint**: `GET /api/publish/{workspace}/collections`

**Purpose**: List all collections for navigation/menu building

**Response**:
```json
{
  "data": [
    {
      "slug": "projects",
      "name": "Projects",
      "description": "All project entries",
      "entry_count": 12,
      "sort_order": 1,
      "icon": "folder",
      "color": "#3B82F6"
    }
  ]
}
```

**Schema**: `PublishedCollectionSummary`

### Task 2: Add Entry Filters

**Add to** `GET /api/publish/{workspace}/entries`:

1. **`slug` filter** (Query param: `slug`)
   - Comma-separated slugs
   - Example: `?slug=about,contact,sizing`
   - Use case: Batch fetch specific pages

2. **`updated_since` filter** (Query param: `updated_since`)
   - ISO datetime
   - Example: `?updated_since=2026-07-01T00:00:00Z`
   - Use case: Incremental builds

### Task 3: Add Resources to Entry Response

**Update** `PublishedEntryRead`:
```python
resources: list[PublishedResourceRead] = []
```

**New Schema**: `PublishedResourceRead`
```python
class PublishedResourceRead(_MarvinModel):
    slug: str
    name: str
    resource_type: str
    description: str | None
    url: str | None
    external_id: str | None
    # Junction table fields:
    role: str | None  # "primary", "alternative"
    quantity: str | None  # "2 yards"
    unit: str | None  # "meters"
    position: int
```

### Task 4: Performance Optimization

**Current Issues**:
- N+1 queries for `entry.entry_type.slug`
- N+1 queries for `entry.entry_collections`
- Assets loaded per-entry in loops

**Solutions**:
1. Use `joinedload` for relationships:
   ```python
   query = query.options(
       joinedload(Entries.entry_type),
       joinedload(Entries.entry_collections).joinedload(EntryCollections.collection),
       joinedload(Entries.entry_assets).joinedload(EntryAssets.asset),
       joinedload(Entries.entry_resources).joinedload(EntryResources.resource)
   )
   ```

2. Batch load collections for list views

### Task 5: Documentation

**Create**: `docs/ASTRO-INTEGRATION.md`

Contents:
- How to configure Astro to fetch from Marvin
- Example Astro content loader
- Environment variables
- Error handling
- Caching strategies

---

## Astro Integration Pattern

### Content Loader Approach

```typescript
// src/content/config.ts
import { defineCollection, z } from 'astro:content';

const entries = defineCollection({
  loader: async () => {
    const API_URL = import.meta.env.MARVIN_API_URL;
    const API_TOKEN = import.meta.env.MARVIN_API_TOKEN;
    const WORKSPACE = import.meta.env.MARVIN_WORKSPACE;

    const response = await fetch(
      `${API_URL}/api/publish/${WORKSPACE}/entries?limit=1000`,
      {
        headers: { 'Authorization': `Bearer ${API_TOKEN}` }
      }
    );

    const { data } = await response.json();
    return data.map(entry => ({
      id: entry.slug,
      ...entry
    }));
  },
  schema: z.object({
    slug: z.string(),
    title: z.string(),
    entry_type: z.string(),
    summary: z.string().optional(),
    published_at: z.string().optional(),
    collections: z.array(z.string()),
  })
});

export const collections = { entries };
```

### Page Generation

```astro
---
// src/pages/[...slug].astro
import { getCollection } from 'astro:content';

export async function getStaticPaths() {
  const entries = await getCollection('entries');
  
  return entries.map(entry => ({
    params: { slug: entry.slug },
    props: { entry }
  }));
}

const { entry } = Astro.props;
---

<html>
  <head>
    <title>{entry.title}</title>
  </head>
  <body>
    <h1>{entry.title}</h1>
    <div set:html={entry.content_markdown} />
  </body>
</html>
```

---

## Performance Requirements

### Astro Build Performance

**Target**: Full site build with 100 entries in < 30 seconds

**Current approach** (N requests):
- 1 request for entries list
- N requests for full entry details
- Total: 1 + 100 = 101 requests

**Optimized approach** (2-3 requests):
- 1 request for entries list with `limit=1000`
- 1-2 requests for collections
- Full entry content included in list response (with expand param)
- Total: 2-3 requests

### Proposed Enhancement (Optional)

Add `?expand=full` to entries list endpoint:
- Returns `PublishedEntryRead` instead of `PublishedEntryListItem`
- Includes content_markdown, assets, resources
- Allows single-request site builds

---

## Schema Validation Points

### Resources

**Question**: Do resources model real use cases?

**Test with Mash & Burn Co**:
- "2 yards of 13oz black denim"
- "1 set of brass buttons"
- "Kwik Sew 3888 pattern"

**Required fields**:
- ✅ `resource_type` (fabric, notion, pattern)
- ✅ `quantity` + `unit` (junction table)
- ✅ `url` (supplier link, pattern PDF)
- ⚠️ Missing: supplier name, price, availability

### Metadata JSON

**Question**: Is `metadata_json` sufficient for Astro frontmatter?

**Test with Mash & Burn Co**:
```json
{
  "order": 1,
  "layout": "project",
  "hero_style": "full-bleed",
  "completion_date": "2024-03-15",
  "difficulty": "intermediate",
  "time_estimate": "8 hours"
}
```

**Result**: ✅ Flexible enough

### Entry Types as Pages

**Question**: Can static pages be entries?

**Test**:
- About page → `entry_type=page`
- Contact page → `entry_type=page`
- Sizing guide → `entry_type=page`

**Result**: ✅ Works naturally

---

## Architectural Discoveries

### What Works Well ✅

1. **Entry Model Generality**
   - Pages, projects, bench notes all use same model
   - No special cases needed

2. **Collections for Navigation**
   - Collections naturally group entries
   - Can build menus from collection list

3. **Metadata JSON for Frontmatter**
   - Flexible without schema changes
   - Maps cleanly to Astro

4. **Workspace Scoping**
   - API client tokens enforce boundaries
   - No cross-workspace leaks

### Potential Issues ⚠️

1. **No Entry Type Metadata**
   - Entry response has `entry_type: "project"` (slug only)
   - May need entry type name/description for display
   - **Solution**: Add entry type info to response or separate endpoint

2. **Asset File Serving**
   - Currently only returns metadata
   - Astro needs actual files
   - **Solution**: Phase 8 - implement file serving endpoint

3. **Resource URLs**
   - Added in Phase 7
   - Need to test with real supplier links

4. **Incremental Builds**
   - `updated_since` filter helps
   - But Astro may still rebuild entire site
   - **Solution**: Document Astro caching strategies

---

## Testing Strategy

### Manual Testing

1. **Create test content**:
   - 3 entry types (Page, Project, Bench Note)
   - 10 entries across types
   - 3 collections
   - Mix of published/draft

2. **Test endpoints**:
   ```bash
   # List entries
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/publish/default/entries

   # Get specific entry
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/publish/default/entries/black-denim-jacket

   # Filter by entry type
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/publish/default/entries?entry_type=page

   # Get collection
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/publish/default/collections/projects
   ```

3. **Verify**:
   - Only published content returned
   - Draft entries excluded
   - Cross-workspace isolation
   - Pagination works
   - Filters work

### Integration Testing

1. **Create minimal Astro site**:
   - Configure Marvin as content source
   - Generate 10 pages
   - Build static site
   - Verify all content present

2. **Performance testing**:
   - Measure API response times
   - Count queries per request
   - Verify no N+1 queries

---

## Definition of Done

### Endpoints ✅ / ❌

- [x] `GET /api/publish/{workspace}` - workspace info
- [x] `GET /api/publish/{workspace}/entries` - list entries
  - [x] Filter: `entry_type`
  - [x] Filter: `collection`
  - [ ] Filter: `slug` (batch fetch)
  - [ ] Filter: `updated_since` (incremental)
- [x] `GET /api/publish/{workspace}/entries/{slug}` - get entry
  - [x] Includes: assets
  - [x] Includes: collections
  - [x] Includes: metadata
  - [ ] Includes: resources
- [ ] `GET /api/publish/{workspace}/collections` - list collections
- [x] `GET /api/publish/{workspace}/collections/{slug}` - get collection
- [x] `GET /api/publish/{workspace}/assets/{slug}` - get asset

### Performance ✅ / ❌

- [ ] No N+1 queries in list endpoints
- [ ] Eager loading for relationships
- [ ] < 100ms response time for list endpoints
- [ ] < 50ms response time for single entry

### Documentation ✅ / ❌

- [ ] Astro integration guide
- [ ] Example content loader
- [ ] Environment variable setup
- [ ] Caching recommendations

### Validation ✅ / ❌

- [ ] Can build complete Astro site from Marvin
- [ ] No local Markdown files needed
- [ ] Pages, projects, bench notes all supported
- [ ] Static pages work as entries
- [ ] Navigation built from collections

---

## Next Steps

1. Implement missing endpoints
2. Add missing filters
3. Add resources to entry response
4. Optimize queries
5. Write Astro integration guide
6. Test with real content
7. Document architectural discoveries

