"""Target selector for Flavor B automations — the "FROM" clause.

Normally an automation operates on the single entity its trigger handed it. A ``target`` turns that
around: it runs a *query* to select the entities to operate on, so the automation becomes set-based
(``FROM query WHERE conditions DO actions-per-row``). The query reuses the same fields as the
``find_entries`` agent tool, and its values may be ``$event.*`` templates so a webhook can carry the
query in its payload.

Deliberately **capped** (``MAX_TARGET_ENTITIES``): fanning an action — especially an AI op — over an
unbounded result set is a cost/observability hazard, and there's no per-row execution history yet.
The dry-run preview (see the controller) resolves the same set *without* executing, so an author sees
the count before committing. Unbounded fan-out waits for execution history.

MVP: entity == "entry". Collections/assets can plug in here with their own query builders later.
"""

from .matcher import interpolate

# Hard ceiling on how many entities one automation run will touch. Now that every run + step is
# recorded (automation_executions), a capped batch is fully inspectable, so the cap can be generous —
# but it stays bounded: a runaway query fanning an AI op over the whole workspace is still a real
# cost/rate hazard, and the preview shows the true count so an author sees when it's clipped.
MAX_TARGET_ENTITIES = 250


def resolve_target_entities(session, group_id, target: dict, context: dict, *, cap: int = MAX_TARGET_ENTITIES):
    """Resolve a ``target`` to a list of entities (capped) + the true match count.

    Returns ``(entities, total)`` where ``total`` is the full count before the cap, so callers can
    tell the user "matched 240, acting on the first 25". Raises nothing for an empty match — an empty
    list is a valid (no-op) result. Unknown entity kinds return ``([], 0)``.
    """
    entity = (target or {}).get("entity", "entry")
    if entity != "entry":
        return [], 0

    from marvin.services.entries.query import run as run_entry_query

    query = interpolate((target or {}).get("query", {}) or {}, context)
    result = run_entry_query(session, group_id, query, limit=max(1, min(cap, MAX_TARGET_ENTITIES)))
    return result.rows, result.total


def entity_ref(entity) -> dict:
    """The lean context/preview shape for a resolved entry (matches the engine's entry context)."""
    etype = entity.entry_type.slug if getattr(entity, "entry_type", None) else None
    return {
        "id": str(entity.id),
        "entry_type": etype,
        "status": entity.status,
        "title": entity.title,
        "slug": entity.slug,
    }


def json_field_equals(column, key: str, value, dialect: str = "sqlite"):
    """`column[key] == value` for a JSON column, reading typed-in text the way people mean it.

    Workflow editors and agents pass values as text, but a checkbox is stored as true/false and a
    number as a number, so "true" or "45" must also match those.

    Postgres compares the field's JSON text against every form the value can take (`"text"`,
    `true`, `45`) — no casts, because casting a text field to boolean/float raises there. SQLite has
    no such errors, so it compares typed extractions directly.
    """
    import json as _json

    import sqlalchemy as sa

    from .matcher import as_bool, as_number

    if isinstance(value, bool):
        typed: list = [value]
    elif isinstance(value, int | float):
        typed = [value]
    else:
        text = str(value)
        typed = [text]
        if text.strip().lower() in ("true", "false"):
            typed.append(as_bool(text))
        if (n := as_number(text)) is not None:
            typed.append(n)

    field = column[key]
    if dialect == "postgresql":
        forms: set[str] = set()
        for v in typed:
            forms.add(_json.dumps(v))
            if isinstance(v, int | float) and not isinstance(v, bool):
                forms.update({_json.dumps(int(v)) if float(v).is_integer() else _json.dumps(v), _json.dumps(float(v))})
        return sa.cast(field, sa.Text).in_(sorted(forms))

    options = []
    for v in typed:
        if isinstance(v, bool):
            options.append(field.as_boolean() == v)
        elif isinstance(v, int | float):
            options.append(field.as_float() == float(v))
        else:
            options.append(field.as_string() == v)
    return sa.or_(*options) if len(options) > 1 else options[0]


def _entries_query(session, group_id, query: dict):
    """The SQL part of an entry query (services/entries/query.py) — for callers that page or count
    themselves (an entry step's entity_query, the integration-action scheduled handler)."""
    from marvin.services.entries.query import build

    q, _note = build(session, group_id, query or {})
    return q
