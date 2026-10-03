> **Superseded (2026-09-25):** this page predates the current API. See the manual — https://inneropen.github.io/marvin/whats-new/publishing-api/ — which follows the code.

# Site Clients and Publishing API

Site clients are read-only API identities for external sites.

They are different from human users.

A human user logs into Marvin Admin to create and manage content. A site client reads published content for one workspace and displays it somewhere else, such as an Astro site.

## Why Site Clients Exist

Public sites should not use admin user tokens.

For example:

```text
Mash & Burn Co. Astro site
  uses site client token
  can read published Mash & Burn content only

InnerOpen Astro site
  uses a different site client token
  can read published InnerOpen content only
```

## Site Client Rules

- Site clients belong to one group/workspace.
- Site clients are read-only.
- Site clients can be revoked.
- Site clients should only see published content.
- Site clients should never create, edit, delete, or impersonate users.
- Raw tokens should only be shown once at creation.

## Suggested Permissions

```text
read:published_entries
read:collections
read:assets
```

Later permissions may include:

```text
read:published_resources
read:public_metadata
```

## Publishing API Routes

Initial read-only routes:

```text
GET /api/publish/{group_slug}/collections
GET /api/publish/{group_slug}/entries
GET /api/publish/{group_slug}/entries/{slug}
GET /api/publish/{group_slug}/assets
```

## Request Pattern

External sites call Marvin with a bearer token:

```http
Authorization: Bearer <site_client_token>
```

The backend validates the token, resolves the site client, resolves the group/workspace, and only returns content from that group.

## Response Shape

Publishing responses should be boring and stable.

Entries should include:

```text
id
slug
title
entry_type
summary
content_markdown
frontmatter_json
published_at
collections
assets
```

Assets in entry responses should include both file facts and placement facts.

File facts describe the reusable upload:

```text
slug
url
mime_type
width
height
alt_text
metadata
```

Placement facts describe how that file is used on this entry:

```text
role
usage
position
focal_point
caption
placement_metadata
```

Do not expose:

```text
admin notes
draft status history
private metadata
human user permissions
unpublished content
```

## Astro Usage

Astro can fetch published entries at build time or runtime.

Build-time usage is probably best for Mash & Burn Co. because it keeps the public site fast, simple, and mostly static.

```text
Marvin Publishing API
  -> Astro content loader
  -> static pages
```

## First Implementation Goal

The first implementation does not need every permission feature.

The first version should prove:

- A site client can be created for a group.
- The site client can fetch published entries.
- Draft entries are not returned.
- A token for one group cannot read another group.
