# Data Model

## Overview

The Marvin data model is built on the existing Mealie-derived foundation, using `groups` as workspaces. This document describes the core tables and relationships for the platform.

## Core Tables

### Workspace (groups)

Existing table, repurposed as workspace boundary. Do not rename yet.

```sql
groups
  id (primary key)
  name
  slug (unique within tenant)
  created_at
  updated_at
```

Rules:
- Every content item belongs to one group/workspace
- Group admins manage content and publishing settings
- Group members may contribute entries

### Collections

Curated groupings of entries. May be manual, smart, or both.

```sql
collections
  id (primary key)
  group_id (foreign key to groups)
  name
  slug
  description (optional)
  is_smart (boolean, default false)
  smart_rules (json, nullable for manual collections)
  created_at
  updated_at
```

### Entries

Generic publishable objects replacing the old "recipe" concept.

```sql
entries
  id (primary key)
  group_id (foreign key to groups)
  slug (unique within group)
  title
  entry_type (enum: bench_note, article, product, project, guide, pattern, workflow, procedure, reference, recipe)
  summary (optional)
  content_markdown
  frontmatter (json, optional)
  status (enum: draft, review, published)
  created_by (foreign key to users)
  created_at
  updated_at
  published_at (nullable)
```

### Entry Collections (junction table)

Many-to-many relationship between entries and collections.

```sql
entry_collections
  id (primary key)
  entry_id (foreign key to entries)
  collection_id (foreign key to collections)
  position (int, for ordering)
  created_at
```

### Entry Types

Define content structure, rendering, and capabilities for entries.

```sql
entry_types
  id (primary key)
  group_id (foreign key to groups)
  name
  slug (unique within group)
  description (optional)
  schema_json (jsonb, field definitions)
  is_rendered (boolean, default false)
  rendering_json (jsonb, nullable — renderer name, package, version, config)
  capabilities_json (jsonb, nullable — publishable, submittable, routable)
  created_at
  updated_at
```

`is_rendered` marks entry types that have a corresponding frontend renderer component (e.g., page, article, faq, navigation-item). The Publishing API exposes this flag so SDKs and build tools can filter to only rendered types.

`rendering_json` stores a `RenderingDefinition`: `{ renderer, package, version, config }`. `capabilities_json` stores a `CapabilitiesDefinition`: `{ publishable, submittable, routable }`.

### Resources

Reusable objects referenced by entries (fabric, thread, tools, suppliers, repos, etc).

```sql
resources
  id (primary key)
  group_id (foreign key to groups)
  slug (unique within group)
  name
  resource_type (enum: fabric, thread, button, tool, supplier, repository, api, book, document)
  description (optional)
  metadata (json, optional)
  created_by (foreign key to users)
  created_at
  updated_at
```

### Entry Resources (junction table)

Many-to-many relationship between entries and resources.

```sql
entry_resources
  id (primary key)
  entry_id (foreign key to entries)
  resource_id (foreign key to resources)
  role (optional, e.g., "primary_tool", "supplier")
  quantity (optional)
  unit (optional, e.g., "yards", "count")
  created_at
```

### Assets

Uploaded files connected to entries and resources (images, PDFs, audio, video, etc).

```sql
assets
  id (primary key)
  group_id (foreign key to groups)
  name
  file_path (storage location)
  file_size (bytes)
  mime_type
  width (nullable, for images)
  height (nullable, for images)
  alt_text (nullable)
  description (optional)
  metadata (json, optional)
  uploaded_by (foreign key to users)
  created_at
  updated_at
```

Asset metadata describes the reusable file itself. Examples include source camera/import data, dominant colors, generated variants, rights notes, or AI analysis. Entry-specific layout choices belong on `entry_assets`, not here.

### Entry Assets (junction table)

Many-to-many relationship between entries and assets with ordering.

```sql
entry_assets
  id (primary key)
  entry_id (foreign key to entries)
  asset_id (foreign key to assets)
  position (int, for display ordering)
  role (optional, e.g., "hero", "featured", "support", "inline", "download")
  usage (optional, e.g., "material", "process", "detail", "texture", "workshop")
  focal_point (optional, e.g., "50% 50%" for cropped image presentation)
  caption (optional)
  metadata (json, optional)
  created_at
```

Entry asset metadata describes how a reusable asset is placed on one entry. For example, the same image may be a `hero` image for one entry and a `support` image with `usage = material` for another.

### Site Clients

Read-only API identities for external sites consuming published content.

```sql
site_clients
  id (primary key)
  group_id (foreign key to groups)
  name
  slug
  token_hash (hashed token, never store plaintext)
  permissions (json, array of permission strings)
  is_active (boolean, default true)
  last_used_at (nullable)
  created_by (foreign key to users)
  created_at
  updated_at
  revoked_at (nullable)
```

## Indexing Strategy

Key indices for performance:

```sql
CREATE INDEX idx_entries_group_id ON entries(group_id);
CREATE INDEX idx_entries_group_status ON entries(group_id, status);
CREATE INDEX idx_entries_slug ON entries(group_id, slug);
CREATE INDEX idx_collections_group_id ON collections(group_id);
CREATE INDEX idx_resources_group_id ON resources(group_id);
CREATE INDEX idx_assets_group_id ON assets(group_id);
CREATE INDEX idx_site_clients_group_id ON site_clients(group_id);
CREATE INDEX idx_site_clients_token_hash ON site_clients(token_hash);
```

## Constraints and Rules

1. **Workspace Isolation**: All queries must filter by `group_id` to ensure multi-tenant safety
2. **Slugs**: Must be unique within a workspace, never globally
3. **Status Workflow**: `draft` → `review` → `published` (unidirectional)
4. **Deletion**: Use soft deletes (added `deleted_at` nullable timestamp) for audit trail
5. **Timestamps**: All tables have `created_at` and `updated_at` for audit
6. **Token Hashing**: Site client tokens are hashed using bcrypt, never stored plaintext

## Future Considerations

- Smart collection rules engine (SQL/MongoDB style queries)
- Asset versioning and transformation pipeline
- Workflow state machine for multi-step reviews
- Workspace rename to separate table (after platform stabilizes)
