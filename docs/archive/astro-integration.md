# Astro Integration Guide

**How to use Marvin as the single source of truth for an Astro website**

---

## Overview

Marvin provides a read-only Publishing API that Astro can use to fetch all content at build time. This eliminates the need for local Markdown files and centralizes content management in Marvin.

**Benefits**:
- ✅ Single source of truth for all content
- ✅ Content reviewed and approved before publishing
- ✅ No git commits required for content updates
- ✅ Webhook-triggered rebuilds on publish
- ✅ Assets managed centrally
- ✅ Metadata structured in database

---

## Prerequisites

1. **Marvin instance** running and accessible
2. **API Client** created in Marvin for your workspace
3. **API Client token** (starts with `marvin_sk_`)
4. **Astro 4.0+** project

---

## Step 1: Environment Configuration

Create `.env` file in your Astro project:

```bash
# Marvin Publishing API Configuration
MARVIN_API_URL=https://marvin.your-domain.com
MARVIN_API_TOKEN=marvin_sk_your_token_here
MARVIN_WORKSPACE=default
```

---

## Step 2: Create API Client

```typescript
// src/lib/marvin.ts
export async function fetchFromMarvin<T>(endpoint: string): Promise<T> {
  const apiUrl = import.meta.env.MARVIN_API_URL;
  const apiToken = import.meta.env.MARVIN_API_TOKEN;
  const workspace = import.meta.env.MARVIN_WORKSPACE;
  
  const url = `${apiUrl}/api/publish/${workspace}${endpoint}`;

  const response = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${apiToken}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Marvin API error: ${response.status}`);
  }

  return response.json();
}
```

---

## Publishing API Endpoints

### Workspace Info
```
GET /api/publish/{workspace}
```

### List Published Entries
```
GET /api/publish/{workspace}/entries

Filters:
  ?entry_type=page         # Filter by type
  ?collection=projects     # Filter by collection
  ?slug=about,contact      # Batch fetch specific slugs
  ?updated_since=2026-07-01T00:00:00Z  # Incremental builds
  ?limit=1000              # Page size
```

### Get Single Entry
```
GET /api/publish/{workspace}/entries/{slug}

Returns:
  - Full markdown content
  - Metadata JSON
  - Collections
  - Resources (with quantities)
  - Assets (with dimensions)
```

### List Collections
```
GET /api/publish/{workspace}/collections

Returns all collections with entry counts, sorted by sort_order
```

### Get Collection with Entries
```
GET /api/publish/{workspace}/collections/{slug}
```

---

## Step 3: Fetch Content in Astro

```typescript
// src/content/config.ts
import { defineCollection, z } from 'astro:content';
import { fetchFromMarvin } from '../lib/marvin';

const entries = defineCollection({
  loader: async () => {
    const { data } = await fetchFromMarvin('/entries?limit=1000');
    
    // Fetch full content for each entry
    const fullEntries = await Promise.all(
      data.map(async (entry) => {
        const full = await fetchFromMarvin(`/entries/${entry.slug}`);
        return { id: entry.slug, ...full };
      })
    );
    
    return fullEntries;
  },
  schema: z.object({
    slug: z.string(),
    title: z.string(),
    entry_type: z.string(),
    content_markdown: z.string().optional(),
    metadata: z.record(z.any()).optional(),
    resources: z.array(z.any()).default([]),
    assets: z.array(z.any()).default([]),
  }),
});

export const collections = { entries };
```

---

## Step 4: Generate Pages

```astro
---
// src/pages/[...slug].astro
import { getCollection } from 'astro:content';

export async function getStaticPaths() {
  const entries = await getCollection('entries');
  return entries.map(entry => ({
    params: { slug: entry.data.slug },
    props: { entry },
  }));
}

const { entry } = Astro.props;
---

<!DOCTYPE html>
<html>
  <head>
    <title>{entry.data.title}</title>
  </head>
  <body>
    <h1>{entry.data.title}</h1>
    <div set:html={entry.data.content_markdown} />
  </body>
</html>
```

---

## Mash & Burn Co. Example

**Entry Types**:
- `page` - Static pages (About, Contact, Sizing)
- `project` - Project writeups
- `bench-note` - Process notes

**Collections**:
- Featured Projects
- Denim
- 2024 Projects

**Resources**:
```json
{
  "name": "13oz Black Denim",
  "resource_type": "fabric",
  "quantity": "2",
  "unit": "yards",
  "url": "https://supplier.com/product"
}
```

**Result**: Complete site built from Marvin, zero local Markdown files.

---

## Performance Tips

1. **Parallel fetching**: Use `Promise.all()` for details
2. **Batch fetch pages**: `?slug=about,contact,sizing`
3. **Incremental builds**: `?updated_since=...`
4. **Cache responses**: 5-minute TTL during development

---

## Testing

```bash
# Test API directly
curl -H "Authorization: Bearer marvin_sk_your_token" \
  http://localhost:8080/api/publish/default/entries?entry_type=page

# Should return all published pages
```

---

## Summary

**Marvin provides**:
- Published entries with full content
- Collections for navigation
- Resources with quantities
- Assets with dimensions
- Metadata for Astro frontmatter

**Astro consumes**:
- Via Publishing API
- At build time
- No local files needed

**Result**: Single source of truth validated ✅
