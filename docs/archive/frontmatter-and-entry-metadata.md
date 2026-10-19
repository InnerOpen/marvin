# Frontmatter and Entry Metadata

This note records the current Marvin decision around Astro-style Markdown frontmatter.

## Decision

Marvin should not store raw frontmatter as the primary source of truth.

Marvin should store structured content and metadata in the database. Frontmatter is an export/serialization format that can be generated when Astro or another static site requests Markdown.

## Why

Astro Markdown files often look like this:

```markdown
---
title: Sizing
slug: sizing
description: A practical note on fit, measurements, and choosing the right size.
order: 6
---

Markdown body goes here.
```

The values between the `---` markers are frontmatter. They are metadata, not the main body content.

In Marvin, common metadata should live as real database fields.

Examples:

```text
title
slug
summary
description
status
entry_type_id
created_at
updated_at
published_at
```

Framework-specific or presentation-specific metadata should live in `metadata_json` on the entry.

Examples:

```json
{
  "order": 6,
  "layout": "docs",
  "sidebar": true
}
```

## Entry Table Implication

The first `entries` table should include a `metadata_json` column.

Suggested first slice:

```text
entries
  id
  group_id
  entry_type_id
  title
  slug
  summary
  description
  content_markdown
  excerpt
  status
  metadata_json
  created_at
  updated_at
  published_at
```

Do not add a `frontmatter` text column.

## Publishing Implication

When a site requests Markdown, Marvin can combine real columns and `metadata_json` into generated frontmatter.

Example source data:

```text
title = Sizing
slug = sizing
description = A practical note on fit, measurements, and choosing the right size.
status = published
metadata_json = { "order": 6 }
content_markdown = Sizing is more useful when it starts with real measurements...
```

Generated Markdown output:

```markdown
---
title: Sizing
slug: sizing
description: A practical note on fit, measurements, and choosing the right size.
order: 6
---

Sizing is more useful when it starts with real measurements...
```

## Metadata Layers

Use three layers:

1. Real columns for fields Marvin understands.
2. `metadata_json` for site/framework/presentation metadata.
3. Future custom fields for workspace-specific domain data.

Examples:

```text
Real columns:
  title
  slug
  status
  published_at

metadata_json:
  order
  layout
  sidebar
  hero_style

custom fields later:
  fabric_weight
  pattern_size
  openshift_version
  repo_url
```

This keeps Marvin structured while still making it compatible with Astro Markdown workflows.