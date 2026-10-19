# Marvin Ideas

This file is a design notebook for Marvin. It captures ideas, direction, and possible future architecture. Not every idea here is a committed requirement.

## Guiding Principles

- Marvin is a private administrative platform.
- Public sites are consumers, not editors.
- Use one source of truth for content, assets, metadata, publishing, and review state.
- Prefer the existing Marvin architecture over rewrites.
- Build generic capabilities instead of brand-specific features.
- Use events, scheduler, emailer, and webhooks where possible.
- AI assists. Humans approve.
- Favor composition over specialization.

## Core Model

```text
Workspace
  Spaces
  Collections
  Entries
    Resources
    Steps
    Assets
    Notes
    Comments
    Relationships
    Custom Fields
    Publishing
  Site Clients
  Events
```

## Workspaces

The existing Mealie-derived `groups` table should act as Marvin's workspace boundary for now.

```text
groups = workspaces
```

A workspace is the hard tenant/security boundary.

Examples:

- Mash & Burn Co.
- InnerOpen
- Sailing Manual
- Personal Knowledge Base

## Spaces

Mealie has both groups and households. In Marvin, households could become Spaces.

A Space is an internal context inside a workspace. It is not the hard security boundary.

Possible examples for Mash & Burn Co.:

- Workshop
- Website
- Marketing
- Archive
- Private R&D

This should be deferred until the core platform proves it needs another subdivision.

## Entries

Everything publishable should be an Entry.

A project is not a special database system. It is an entry with an entry type.

Examples:

- Project
- Bench Note
- Product
- Guide
- Article
- Pattern
- Workflow
- Procedure
- Reference
- Page

## Entry Types

Entry types should probably become first-class, workspace-defined objects instead of a hardcoded enum.

Suggested future table:

```text
entry_types
  id
  group_id
  name
  slug
  icon
  color
  description
  sort_order
  is_system
```

This lets each workspace define its own language.

Mash & Burn Co. examples:

- Bench Note
- Project
- Product
- Pattern
- Page

InnerOpen examples:

- Runbook
- Workflow
- Architecture
- Playbook
- Automation
- SOP

## Static Pages as Entries

Non-dynamic site pages can be entries too.

Examples:

- About
- Contact
- Sizing
- Care
- Terms

These would use:

```text
entry_type = Page
publishing_target = Website
status = Published
```

Astro can pull these from Marvin just like it pulls projects and bench notes.

Example API shape:

```text
GET /api/publish/{workspace_slug}/entries?entry_type=page
GET /api/publish/{workspace_slug}/pages/{slug}
```

Marvin should store structured content, not raw files only. Markdown is an export format, not necessarily the internal source of truth.

## Frontmatter and Metadata

Astro Markdown files use frontmatter for metadata.

Example:

```markdown
---
title: Sizing
slug: sizing
description: A practical note on fit, measurements, and choosing the right size.
order: 6
---

Markdown body goes here.
```

Marvin should store the metadata as structured fields instead of treating frontmatter as raw text.

Common fields should be real columns:

- title
- slug
- summary
- description
- status
- published_at
- entry_type_id

Workspace-specific values should use custom fields.

When Astro requests Markdown, Marvin can generate frontmatter from the database.

## Collections

Collections answer: where should this appear?

Entry types answer: what is this?

A single entry can belong to many collections.

Example:

```text
Entry: Black Denim Jacket
Type: Project
Collections:
  - Projects
  - Denim
  - Featured
```

Collections should start manual. Smart collections can come later.

## Smart Collections

Smart collections are dynamic views generated from rules.

Example:

```text
Collection: Denim
Rules:
  entry_type = product
  tags contain denim
  status = published
```

This is useful, but should not block the first platform implementation.

## Resources

Resources are reusable objects attached to entries.

They generalize Mealie ingredients, tools, and materials.

Examples:

- 13oz black denim
- Brass buttons
- Cotton thread
- Pattern block
- GitHub repository
- API
- Supplier
- Book

Mealie's recipeIngredient structure is worth adapting.

Suggested relation shape:

```text
entry_resource
  entry_id
  resource_id
  quantity
  unit
  note
  display
  role
  reference_id
```

This keeps materials structured and searchable.

## Steps

Mealie has recipeInstructions. Marvin can generalize this as steps.

Examples:

- Cut panels
- Sew body
- Attach collar
- Fit sleeves
- Finish cuffs

Steps should support title, summary, text, sort order, and references to resources or assets.

## Assets

Assets are not just uploads. They should become structured media objects.

Examples:

- Hero image
- Gallery image
- Detail shot
- Pattern scan
- PDF
- Audio note
- SVG

Future AI asset intelligence:

- suggest hero crop
- suggest social crop
- generate alt text
- identify focal point
- detect materials or construction details

## Site Clients

Site clients are read-only API identities for external sites.

They are not human users.

Examples:

```text
Workspace: Mash & Burn Co.
Site Client: mashandburnco.com
Permissions:
  read:published_entries
  read:collections
  read:assets
```

Astro sites should use site client tokens, not admin user tokens.

## Publishing Targets

Publishing targets describe where content should go.

Examples:

- Website
- Instagram
- YouTube
- Newsletter
- RSS
- PDF

An entry may be published to one or more targets.

```text
Entry: Black Denim Jacket
Targets:
  - Website
  - Instagram
```

This may be better than making Instagram or YouTube into Spaces.

## Events

Marvin already has events, scheduler, emailer, and webhooks. Use them.

Potential platform events:

```text
entry.created
entry.updated
entry.published
entry.unpublished
entry.archived
asset.uploaded
site_client.created
site_client.revoked
intake.received
intake.processed
```

Example flow:

```text
entry.published
  -> webhook triggers Astro rebuild
  -> emailer notifies admin/editor
  -> publishing target job runs if configured
```

Do not build a new automation engine until the existing event system has been fully used.

## AI Intake

AI intake should be a future phase.

Flow:

```text
voice note / quick note / images / document
  -> inbox item
  -> AI parses metadata
  -> draft entry is created
  -> human reviews
  -> publish
```

For Mash & Burn Co., this could turn a few photos and a voice note into a bench note.

AI should create drafts, not publish directly.

## Custom Fields

Custom fields let each workspace define its own metadata without changing the database every time.

Suggested design:

```text
custom_field_definitions
  id
  group_id
  applies_to
  key
  label
  field_type
  required
  options_json
  sort_order

custom_field_values
  id
  group_id
  definition_id
  entity_type
  entity_id
  value_json
```

Custom fields could apply to:

- entries
- resources
- assets
- collections

Examples for Mash & Burn Co.:

- fabric_weight
- pattern_size
- garment_type
- material_origin

Examples for InnerOpen:

- openshift_version
- cloud_provider
- repo_url
- automation_type

## Relationships and Knowledge Graph

Entries should eventually be able to reference each other.

Example:

```text
Black Denim Jacket
  uses -> 13oz black denim
  related to -> Shop Apron
  has bench note -> First Fitting Notes
  inspired by -> 1930s Workwear
```

This turns Marvin from a CMS into a connected knowledge system.

## Versioning

Entry version history would be useful for:

- patterns
- procedures
- articles
- guides
- project documentation

Future idea:

```text
entry_revisions
  id
  entry_id
  version
  content_snapshot
  metadata_snapshot
  created_by
  created_at
```

## Project Timelines

Projects can build timelines automatically from events, notes, steps, assets, and status changes.

Example:

```text
Started
Materials ordered
First fitting
Sleeves revised
Finished
Published
```

This could become a public-facing project history or a private workshop log.

## Templates

Entry types could eventually have templates.

Example Bench Note template:

```markdown
# Today's Work

## Objective

## What Changed

## Problems

## Next Steps
```

Example Project template:

```markdown
# Overview

## Resources

## Steps

## Photos

## Lessons Learned
```

Templates should be workspace-specific.

## Parking Lot

Ideas to defer until the base platform is stable:

- Smart collections
- AI image intelligence
- AI voice intake
- Knowledge graph UI
- Entry revisions
- Publishing target automation
- Social media draft generation
- Project timelines
- Workspace-defined entry type behavior
- Templates
- Advanced custom field UI
