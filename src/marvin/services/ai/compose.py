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


def generate_recipe(schema_json: dict | None, slug: str, capabilities: dict | None = None) -> dict:
    """Heuristic, structure-only authoring recipe for an entry type based on its fields.

    Reads the raw schema_json (leniently — some types carry non-schema field types like
    'asset'). Content types (with a long-form text field) get a hero + gallery asset contract
    and supplier/tool extraction from that field; the `hero` type requires one image; forms and
    pure nav/meta types get no media recipe. Voice/prompt is intentionally NOT set here — that
    is a separate, overridable cascade layer, not baked into the type's recipe.
    """
    caps = capabilities or {}
    fields = (schema_json or {}).get("fields", []) or []
    long_text = [f.get("key") for f in fields if f.get("type") in ("markdown", "textarea")]

    # Forms and pure nav/meta types don't gather media.
    if caps.get("submittable") is True or slug in ("navigation-item", "faq", "value-bane", "bespoke-inquiry"):
        return {}

    roles: list[dict] = [{"role": "hero", "max": 1, "derive": ["thumbnail", "palette"]}]
    if long_text:
        roles.append({"role": "gallery", "max": 4})
    recipe: dict = {"assets": {"min": 1 if slug == "hero" else 0, "max": 5, "roles": roles}}
    if slug == "hero":
        recipe["assets"]["roles"][0]["required"] = True

    if long_text:
        recipe["resources"] = {
            "extract": [
                {"type": "supplier", "source": long_text[0], "capture": ["name", "url"]},
                {"type": "tool", "source": long_text[0], "capture": ["name"]},
            ]
        }
    return recipe


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
