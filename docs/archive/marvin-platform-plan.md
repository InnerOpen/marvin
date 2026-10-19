# Marvin Platform Plan

Marvin is a private administrative content engine. It should create, organize, review, and publish structured content for external sites. Public sites such as Mash & Burn Co. and InnerOpen should remain separate presentation layers that consume approved content from Marvin through scoped publishing APIs.

## Direction

Marvin should not become a public website builder. It should be the source of truth for content, assets, collections, review state, API publishing, and later AI-assisted intake.

```text
Marvin Admin
  manages workspaces, collections, entries, resources, assets, site clients, publishing

Astro / external sites
  read published content through scoped API keys
```

## Existing Foundation

Use the existing Mealie-derived foundation instead of creating parallel structures too early.

```text
groups = workspaces
group_preferences = workspace preferences
users.group_id = user's current/default workspace
long_live_tokens = user-owned API tokens for authenticated users
```

Do not create a separate `workspaces` table in the first implementation phase. Treat `groups` as the workspace boundary and evolve terminology through docs, schemas, API responses, and UI labels before considering a database rename.

## Core Concepts

### Workspace

A workspace is the tenant boundary. In the current database this maps to `groups`.

Rules:

- Every content item belongs to one workspace.
- Every publishing token belongs to one workspace.
- Public sites only see content from the workspace their token is scoped to.
- Admin users may manage content according to existing group/user permissions.

### Collection

A collection replaces the cookbook concept. It is a curated grouping of entries.

Collections may be manual, smart, or both:

- Manual collections explicitly attach entries.
- Smart collections can later use rules such as entry type, tags, status, or metadata.

### Entry

An entry replaces recipes as the generic publishable object.

Entry examples:

- Bench note
- Article
- Product
- Project
- Guide
- Pattern
- Workflow
- Procedure
- Reference
- Recipe

Entries should be Markdown-backed and include frontmatter-style metadata for Astro/static site consumption.

### Resource

A resource replaces ingredients/tools/materials as a generic reusable object.

Examples:

- Fabric
- Thread
- Button
- Tool
- Supplier
- Git repository
- API
- Book
- Document

### Asset

Assets are uploaded files connected to entries and resources.

Examples:

- Images
- PDFs
- Audio
- Video
- SVGs
- Source files

### Site Client

A site client is a read-only API identity for an external site.

A site client is not a human user and should not reuse human user tokens.

Examples:

```text
Workspace: Mash & Burn Co.
Site Client: mashandburnco.com
Permissions:
  read:published_entries
  read:collections
  read:assets
```

## Publishing Rules

Publishing API routes must:

- Validate a site client token.
- Match the token to a workspace/group.
- Return only `status = published` content.
- Respect collection restrictions when configured.
- Never expose drafts, private notes, admin-only fields, or human user permissions.

## Initial Implementation Phases

1. Add architecture docs and implementation checklist.
2. Add Alembic migration for new platform tables.
3. Add SQLAlchemy models, schemas, and repositories.
4. Add authenticated admin APIs for entries, collections, resources, assets, and site clients.
5. Add read-only publishing APIs.
6. Add Astro integration documentation.
7. Add AI intake as a later phase.

## Guiding Principle

Keep the existing Marvin architecture. Replace the domain model.

The goal is not to rewrite Marvin. The goal is to evolve it from a de-recipes Mealie fork into a workspace-scoped publishing engine.