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
| `asset` | one asset id | none |
| `asset-list` | list of asset ids | `min`, `max` |
| `resource` | one resource id | none |
| `resource-list` | list of resource ids | `min`, `max` |

An `embed` field and a markdown field with `autoEmbed` are published resolved, under the entry's `embeds`; see [Media embeds](../whats-new/media-embeds.md). Asset and resource fields are published resolved too, as the asset or resource object itself; see the [Publishing API reference](publishing-api.md).

## What is checked

- A required field that is missing or `null` is refused: `Field 'key': Required field is missing or null`.
- A `null` value on an optional field is accepted without further checks.
- A value with the wrong type is refused (a number field takes integers and floats, a select field with `multiple` takes a list of strings, an `asset-list` takes a list of id strings).
- `min` and `max` on text fields are lengths; on number fields they are values; `pattern` must match.
- A select value must be one of `options`.
- A key that is not in the schema is stored and not checked.
