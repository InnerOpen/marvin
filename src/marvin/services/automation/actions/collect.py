"""`collect` step — gather a set of entries, assets or resources into one output, so later steps see them all.

A workflow runs once per item (the trigger's, or each target row); this is the many → one step: a weekly digest from
the week's articles, a contact sheet from a series' images, a report over a project's notes. `entity` and `query` are
a target's — the shared entry query (services/entries/query.py) or the asset/resource one (services/item_query.py) —
and dates may be relative (`published_after: "-7d"`). It works under any trigger.

Output: `rows` — each the same facts a run binds as `${entry.*}` / `${asset.*}` / `${resource.*}` (trimmed to the
useful ones, plus any extra `fields` paths) — `count` (rows returned), `total` (all that matched, before `limit`) and
`text`, a plain list (one line per row, with any extra fields under it) to put straight into an AI prompt. A render
step's `images` can take `rows` whole (a contact sheet). Reading only: it changes nothing, so a dry run runs it too.

`only_invalid` (entries): keep only the entries that don't pass their type's current rules — each row gains `problem`
(the first rule it breaks) — e.g. after an entry type's fields change. It checks up to CHECK_CAP matches.
"""

from __future__ import annotations

from ..matcher import interpolate, resolve_path
from .base import AutomationActionError, register_action

DEFAULT_LIMIT = 25
CHECK_CAP = 1000  # entries read to find the ones that break their type's rules (only_invalid)
MAX_TEXT_CHARS = 4000  # one value in a row; a digest of long bodies stays a digest
TEXT_FIELD_CHARS = 600  # an extra field as the `text` list shows it
DEFAULT_FIELDS = {
    "entry": ("id", "entry_type", "status", "title", "slug", "summary", "url", "image", "published_at"),
    "asset": ("id", "name", "slug", "url", "mime_type", "width", "height", "alt_text", "tags", "origin"),
    "resource": ("id", "name", "slug", "resource_type", "url", "description", "tags"),
}


@register_action("collect")
def run_collect_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    entity = action.get("entity") or "entry"
    if entity not in DEFAULT_FIELDS:
        raise AutomationActionError(f"collect gathers entry, asset or resource, not {entity!r}")
    query = interpolate(action.get("query") or {}, context)
    if not isinstance(query, dict):
        raise AutomationActionError("collect `query` is an object of the target's keys")
    try:
        limit = max(1, min(int(action.get("limit") or DEFAULT_LIMIT), _cap()))
    except (TypeError, ValueError) as e:
        raise AutomationActionError("collect `limit` is a whole number") from e
    only_invalid = bool(action.get("only_invalid")) and entity == "entry"
    rows, total = _query(session, group_id, entity, query, CHECK_CAP if only_invalid else limit)
    problems: dict = {}
    if only_invalid:
        problems = {row.id: problem for row in rows if (problem := entry_problem(row))}
        rows, total = [row for row in rows if row.id in problems][:limit], len(problems)
    extra = [str(f) for f in (action.get("fields") or []) if str(f).strip()]
    facts = [_row(session, group_id, entity, row, extra) | ({"problem": problems[row.id]} if only_invalid else {}) for row in rows]
    return {"entity": entity, "count": len(facts), "total": total, "rows": facts, "text": _text(entity, facts, extra)}


def _cap() -> int:
    from ..selector import MAX_TARGET_ENTITIES

    return MAX_TARGET_ENTITIES


def _query(session, group_id, entity: str, query: dict, limit: int) -> tuple[list, int]:
    if entity == "entry":
        from marvin.services.entries.query import run as run_entry_query

        result = run_entry_query(session, group_id, query, limit=limit)
    else:
        from marvin.services import item_query

        from ..selector import originals_unless_asked

        result = item_query.run(session, group_id, entity, originals_unless_asked(query) if entity == "asset" else query, limit=limit)
    if result.note:
        raise AutomationActionError(f"collect: {result.note}")
    return result.rows, result.total


def entry_problem(entry) -> str | None:
    """The first rule of its type's current schema the entry breaks ("Field 'price': Required field is missing or
    null"), or None when it passes (or the type has no fields)."""
    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
    from marvin.services.content_validator import ContentValidationError, validate_entry_content

    schema = (entry.entry_type.schema_json if entry.entry_type else None) or {}
    if not schema.get("fields"):
        return None
    try:
        validate_entry_content(EntryTypeSchemaDefinition.model_validate(schema), entry.data_json or {})
    except ContentValidationError as e:
        return str(e)
    return None


def _row(session, group_id, entity: str, row, extra: list[str]) -> dict:
    """A row as the run sees an item of its kind, trimmed to the defaults plus the extra paths asked for."""
    from ..engine import _entry_context, _item_context

    facts = (_entry_context(session, group_id, row.id) if entity == "entry" else _item_context(session, group_id, entity, row.id)) or {}
    if entity == "entry" and getattr(row, "published_at", None):
        facts["published_at"] = row.published_at.isoformat()
    out = {k: _trim(facts.get(k)) for k in DEFAULT_FIELDS[entity] if k in facts}
    for path in extra:
        _set_path(out, path, _trim(resolve_path(path, facts)))
    return out


def _trim(value):
    if isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
        return value[:MAX_TEXT_CHARS] + "…"
    return value


def _set_path(out: dict, path: str, value) -> None:
    """`data.body` → out["data"]["body"], so `${steps.x.output.rows.0.data.body}` reads as it does on an entry."""
    *parents, last = path.split(".")
    node = out
    for key in parents:
        node = node.setdefault(key, {}) if isinstance(node.get(key, {}), dict) else node
    node[last] = value


def _text(entity: str, rows: list[dict], extra: list[str]) -> str:
    """One line per row (title or name, its summary or size, its link), with each extra field under it."""
    lines = []
    for row in rows:
        if entity == "entry":
            head = row.get("title") or row.get("slug") or ""
            detail = row.get("problem") or row.get("summary")
        elif entity == "asset":
            head = row.get("name") or row.get("slug") or ""
            size = f"{row['width']}×{row['height']}" if row.get("width") and row.get("height") else None
            detail = " · ".join(str(x) for x in (size, row.get("alt_text")) if x)
        else:
            head = row.get("name") or row.get("slug") or ""
            detail = row.get("description")
        line = f"- {head}" + (f" — {detail}" if detail else "") + (f" ({row['url']})" if row.get("url") else "")
        lines.append(line)
        for path in extra:
            value = resolve_path(path, row)
            if value not in (None, "", [], {}):
                text = value if isinstance(value, str) else str(value)
                lines.append(f"  {path}: {text[:TEXT_FIELD_CHARS]}{'…' if len(text) > TEXT_FIELD_CHARS else ''}")
    return "\n".join(lines)
