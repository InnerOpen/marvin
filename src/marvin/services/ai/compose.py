"""
Compose an entry from a brief.

The key idea: an entry type's field schema (schema_json) already describes exactly what a
valid entry looks like — so we reuse it as the LLM's *output schema*. The model is forced to
return precisely the fields the entry type defines; validation is then free (the entries repo
validates data_json against the same schema on create).

Asset/resource relationships live outside schema_json today (attached separately); when the
entry-type capability manifest (capabilities_json) lands, this is where "needs 1 image" etc.
would be read to drive what the composer gathers.
"""

from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition

# entry-type field type -> JSON-schema fragment the LLM must satisfy.
_TYPE_MAP: dict[str, dict] = {
    "text": {"type": "string"},
    "textarea": {"type": "string"},
    "markdown": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD)"},
    "datetime": {"type": "string", "description": "ISO 8601 datetime"},
    "embed": {"type": "string"},
}

# Never invent a media link: an embed field takes a link only when the brief supplies one.
_EMBED_GUIDANCE = "a media link (YouTube, Vimeo, Spotify, SoundCloud, Apple Music/Podcasts, …) copied exactly from the brief, or empty"

# Field types the model should not author in v1 (freeform / not content).
_SKIP_TYPES = {"json"}


def entry_type_to_output_schema(schema_def: EntryTypeSchemaDefinition, type_name: str) -> dict:
    """Turn an entry type's fields into a JSON output schema: title + summary + content fields.

    `title` maps to the entry's title column, `summary` to summary; everything else becomes
    data_json keyed by the field's `key`. read-only and json fields are skipped.
    """
    props: dict = {
        "title": {"type": "string", "description": f"A concise, human title for this {type_name}."},
        "summary": {"type": "string", "description": "A one-sentence summary."},
    }
    required = ["title"]

    for f in schema_def.fields:
        if getattr(f, "read_only", False) or f.type in _SKIP_TYPES:
            continue
        desc = f.label
        if getattr(f, "help_text", None):
            desc = f"{f.label} — {f.help_text}"
        if getattr(f, "ai_hint", None):
            desc = f"{desc} (AI guidance: {f.ai_hint})"

        if f.type == "select":
            opts = list(getattr(f, "options", []) or [])
            if getattr(f, "multiple", False):
                frag: dict = {"type": "array", "items": {"type": "string", "enum": opts}}
            else:
                frag = {"type": "string", "enum": opts}
        else:
            frag = dict(_TYPE_MAP.get(f.type, {"type": "string"}))
        frag["description"] = f"{desc} — {_EMBED_GUIDANCE}" if f.type == "embed" else desc

        props[f.key] = frag
        if f.required:
            required.append(f.key)

    return {"type": "object", "properties": props, "required": required}
