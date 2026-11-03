# Entry type fields

An entry type's schema is a list of fields. Each entry of the type keeps its values in `data`, keyed by field `key`, and Marvin checks them against the schema whenever an entry is created or updated. The schema travels as `schemaJson` on the entry type (`/api/entry-types`) and has the shape `{ "fields": [ ... ] }`.

```json
{
  "fields": [
    { "key": "body", "label": "Content", "type": "markdown" },
    {
      "key": "difficulty",
      "label": "Difficulty",
      "type": "select",
      "options": ["beginner", "intermediate", "advanced"],
      "defaultValue": "beginner"
    }
  ]
}
```

This page follows `src/marvin/schemas/platform/entry_type_schema.py` and `src/marvin/services/content_validator.py`.

## Properties every field has

| Property | Type | Meaning |
|---|---|---|
| `key` | string | Where the value lives in `data`. Required; letters, digits and `_`, not starting with a digit. |
| `label` | string | What editors see. Required. |
| `type` | string | One of the types below. Required. |
| `required` | boolean | Default `false`. A required field must be present and not `null`. |
| `defaultValue` | any | Used when the field is not provided. |
| `placeholder` | string | Placeholder in an empty input. |
| `helpText` | string | Shown to editors, and given to the AI as context when it writes the field. |
| `aiHint` | string | Guidance for the AI only (length, voice, what to include); not shown as helper text. |
| `readOnly` | boolean | Default `false`. Editors cannot change the field. |

## Field types

| `type` | Value | Extra properties |
|---|---|---|
| `text` | single-line string | `min`, `max` (length), `pattern` (regex) |
| `textarea` | multi-line string | `min`, `max` (length), `rows` |
| `markdown` | string | `autoEmbed` (default `true`: a supported media link alone on its own line becomes a player; `false` keeps links plain) |
| `number` | integer or float | `min`, `max`, `step` |
| `boolean` | true or false | none |
| `select` | one of `options`, or a list of them | `options` (at least one string), `multiple` (default `false`) |
| `date` | ISO 8601 date string (`YYYY-MM-DD`) | none |
| `datetime` | ISO 8601 date-time string | none |
| `json` | any JSON value, unchecked | none; use sparingly |
| `embed` | a supported media link (YouTube, Vimeo, Spotify, SoundCloud and so on) | `providers` (allowed provider keys; empty means any) |
| `asset` | one asset id | `role` (the attachment role; default the field's key) |
| `asset-list` | list of asset ids | `min`, `max`, `role` |
| `resource` | one resource id | `role` |
| `resource-list` | list of resource ids | `min`, `max`, `role` |

**Asset and resource fields attach.** The content model editor offers them as **Image / file** (`asset`), **Images / files**
(`asset-list`), **Resource** (`resource`) and **Resources** (`resource-list`), each with an **Attach as role** box. In the
entry form they are pickers over the workspace's assets or resources (cards with thumbnails and a searchable list), never
ids. Saving brings the entry's attachments in line with the field, with the field's `role` (its key when none is set): what
the field names is attached in that role, and an id the field used to name and dropped is detached. Then the field is set
from the attachments: it is exactly the ones in its role, in their order — a list field all of them, a single field the
first. So a picture given the role by hand in the sidebar appears in the field, one whose role was changed away in the
sidebar leaves it, and a picture chosen in the field that was attached in another role takes the field's role. Attachments
in any other role, or none, are left alone. A site reads the attachment by role (Grace's site reads `featured`, a hero is
often `hero`), so set the role to what the site expects. A note under the field says which role it attaches as.

An `embed` field and a markdown field with `autoEmbed` are published resolved, under the entry's `embeds`; see [Media embeds](../whats-new/media-embeds.md). Asset and resource fields are published resolved too, as the asset or resource object itself; see the [Publishing API reference](publishing-api.md).

## What is checked

- A required field that is missing or `null` is refused: `Field 'key': Required field is missing or null`.
- A `null` value on an optional field is accepted without further checks.
- A value with the wrong type is refused (a number field takes integers and floats, a select field with `multiple` takes a list of strings, an `asset-list` takes a list of id strings).
- `min` and `max` on text fields are lengths; on number fields they are values; `pattern` must match.
- A select value must be one of `options`.
- A key that is not in the schema is stored and not checked.
