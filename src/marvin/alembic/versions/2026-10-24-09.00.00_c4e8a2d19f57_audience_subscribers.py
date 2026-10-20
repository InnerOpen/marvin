"""Audience › Subscribers: remove the Buttondown plugin's two smart collections, and mark the signup form (a data migration)

Audience › Subscribers replaces the two private smart collections the Buttondown plugin used to offer ("Confirmed subscribers" and
"Unsubscribed": a smart collection over the signup type and one status), and the plugin stops shipping them. For every workspace
that applied them, this removes exactly the plugin's own collections:

  * ``confirmed-subscribers`` named "Confirmed subscribers", and ``unsubscribed`` named "Unsubscribed", when each is still what
    the plugin created: a smart entry collection, private, that nobody installed from another blueprint, whose rules are exactly
    ``{"entry_types": [<one type>], "statuses": ["published"] | ["archived"], "match": "all"}`` (published for the first, archived
    for the second). Anything else under those slugs (a renamed or public one, an extra rule, another status, two types, a manual
    collection) is a person's own and is left alone. Their membership rows go with them; no entry is touched.

and marks the signup form: sets ``submission.kind: signup`` (and ``destination: audience``, when the type stores none) on the
entry type Buttondown was applied with. A workspace that applied the plugin before this release has the signup form but nothing says
it is one, so Audience › Submissions would list its signups as messages and Subscribers would not show. The plugin's
``signup_type`` is not stored anywhere on its own (a parameter is substituted into the content it creates), so the record is that
content: the workflows name the form,

  1. the subscribe workflow (slug ``buttondown-subscribe-on-signup``, or installed from that blueprint): the condition
     ``entry.entry_type eq <slug>``;
  2. else the confirm / unsubscribe workflows (``buttondown-subscriber-confirmed`` / ``-unsubscribed``): their entry step's
     ``entity_query.entry_type``;
  3. else, a workspace with a ``buttondown`` integration and none of those workflows falls back to the plugin's default,
     ``newsletter``, when it has a submittable type of that slug.

Only a submittable type is touched, and only keys it doesn't already store: a ``kind`` or ``destination`` someone set (message and
entries included) is theirs. Nothing else on the type changes (``listed`` was set by the earlier migration).

A workspace where none of this finds the form keeps the one-click way: the entry type editor's Signup setting.

Idempotent (a second run finds nothing to remove or set), works on SQLite and PostgreSQL with plain statements (no model code, which
a migration must not import), and the downgrade does nothing: removed collections are derived and can be applied again, the flag is
data, and the schema didn't change.

Revision ID: c4e8a2d19f57
Revises: a1d7c35e9f20
Create Date: 2026-10-24 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "c4e8a2d19f57"
down_revision: str | None = "a1d7c35e9f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = marvin.db.migration_types.GUID

# the plugin's collections: slug -> (name, the one status its rules ask for)
COLLECTIONS = {"confirmed-subscribers": ("Confirmed subscribers", "published"), "unsubscribed": ("Unsubscribed", "archived")}
SUBSCRIBE_WORKFLOW = "buttondown-subscribe-on-signup"
EVENT_WORKFLOWS = ("buttondown-subscriber-confirmed", "buttondown-subscriber-unsubscribed")
PROVIDER = "buttondown"
DEFAULT_SIGNUP_TYPE = "newsletter"  # the plugin's signup_type default


def upgrade() -> None:
    bind = op.get_bind()
    remove_collections(bind)
    mark_signup_forms(bind)


def downgrade() -> None:
    """Nothing to undo: the collections are derived and can be applied again; the flag is data; the schema is unchanged."""


def _tables():
    id_ = lambda: sa.column("id", GUID())  # noqa: E731
    return {
        "collections": sa.table(
            "collections",
            id_(),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_smart", sa.Boolean()),
            sa.column("is_public", sa.Boolean()),
            sa.column("target_type", sa.String()),
            sa.column("smart_rules", sa.JSON()),
            sa.column("source_blueprint", sa.String()),
        ),
        "collection_children": [
            sa.table(name, sa.column("collection_id", GUID())) for name in ("entry_collections", "collection_assets", "collection_resources")
        ],
        "workflows": sa.table(
            "workspace_automations",
            id_(),
            sa.column("group_id", GUID()),
            sa.column("slug", sa.String()),
            sa.column("definition", sa.JSON()),
            sa.column("source_blueprint", sa.String()),
        ),
        "integrations": sa.table("integrations", sa.column("group_id", GUID()), sa.column("provider", sa.String())),
        "types": sa.table(
            "entry_types", id_(), sa.column("group_id", GUID()), sa.column("slug", sa.String()), sa.column("capabilities_json", sa.JSON())
        ),
    }  # fmt: skip


def is_plugin_collection(slug, name, is_smart, is_public, target_type, rules, source_blueprint) -> bool:
    """Whether a row under one of the plugin's slugs is still exactly what the plugin created."""
    expected_name, status = COLLECTIONS[slug]
    if name != expected_name or is_smart is not True or is_public is not False or (target_type or "entry") != "entry":
        return False
    if source_blueprint not in (None, slug):
        return False
    if not isinstance(rules, dict) or set(rules) != {"entry_types", "statuses", "match"}:
        return False
    types = rules["entry_types"]
    return (
        isinstance(types, list)
        and len(types) == 1
        and isinstance(types[0], str)
        and bool(types[0])
        and rules["statuses"] == [status]
        and rules["match"] == "all"
    )


def remove_collections(bind) -> int:
    """Remove the plugin's two collections where they are still its own; returns how many."""
    t = _tables()
    coll = t["collections"]
    rows = bind.execute(
        sa.select(
            coll.c.id, coll.c.slug, coll.c.name, coll.c.is_smart, coll.c.is_public, coll.c.target_type, coll.c.smart_rules, coll.c.source_blueprint
        ).where(coll.c.slug.in_(list(COLLECTIONS)))
    ).all()
    ids = [cid for cid, *rest in rows if is_plugin_collection(*rest)]
    for chunk in _chunks(ids):
        for child in t["collection_children"]:
            bind.execute(child.delete().where(child.c.collection_id.in_(chunk)))
        bind.execute(coll.delete().where(coll.c.id.in_(chunk)))
    return len(ids)


def named_entry_types(definition) -> list[str]:
    """The entry type slugs a workflow's conditions name with ``entry.entry_type eq <slug>``."""
    conditions = definition.get("conditions") if isinstance(definition, dict) else None
    return [
        c["value"]
        for c in (conditions if isinstance(conditions, list) else [])
        if isinstance(c, dict) and c.get("field") == "entry.entry_type" and c.get("op") == "eq" and isinstance(c.get("value"), str) and c["value"]
    ]


def queried_entry_types(definition) -> list[str]:
    """The entry type slugs a workflow's entry steps look up with ``entity_query.entry_type``."""
    actions = definition.get("actions") if isinstance(definition, dict) else None
    return [
        a["entity_query"]["entry_type"]
        for a in (actions if isinstance(actions, list) else [])
        if isinstance(a, dict)
        and isinstance(a.get("entity_query"), dict)
        and isinstance(a["entity_query"].get("entry_type"), str)
        and a["entity_query"]["entry_type"]
    ]


def signup_type_slugs(bind) -> dict:
    """``{group id: signup type slug}`` for every workspace Buttondown was applied in (see the module docstring for where it is read)."""
    t = _tables()
    wf = t["workflows"]
    named: dict = {}
    from_events: dict = {}
    for group_id, slug, body, source in bind.execute(sa.select(wf.c.group_id, wf.c.slug, wf.c.definition, wf.c.source_blueprint)).all():
        name = source if source in (SUBSCRIBE_WORKFLOW, *EVENT_WORKFLOWS) else slug
        if name == SUBSCRIBE_WORKFLOW:
            found = named_entry_types(body)
            if found:
                named.setdefault(group_id, found[0])
        elif name in EVENT_WORKFLOWS:
            found = queried_entry_types(body)
            if found:
                from_events.setdefault(group_id, found[0])
    for group_id, slug in from_events.items():
        named.setdefault(group_id, slug)
    ints = t["integrations"]
    for (group_id,) in bind.execute(sa.select(ints.c.group_id).where(ints.c.provider == PROVIDER)).all():
        named.setdefault(group_id, DEFAULT_SIGNUP_TYPE)
    return named


def mark_signup_forms(bind) -> int:
    """Set ``submission.kind: signup`` and ``destination: audience`` (each only where the type stores none) on the submittable type
    Buttondown was applied with; returns how many types changed."""
    types = _tables()["types"]
    changed = 0
    for group_id, type_slug in signup_type_slugs(bind).items():
        row = bind.execute(sa.select(types.c.id, types.c.capabilities_json).where(types.c.group_id == group_id, types.c.slug == type_slug)).first()
        if row is None:
            continue
        caps = row[1] if isinstance(row[1], dict) else {}
        submission = caps.get("submission") if isinstance(caps.get("submission"), dict) else {}
        if caps.get("submittable") is not True:
            continue
        missing = {k: v for k, v in (("kind", "signup"), ("destination", "audience")) if k not in submission}
        if not missing:
            continue
        bind.execute(types.update().where(types.c.id == row[0]).values(capabilities_json={**caps, "submission": {**submission, **missing}}))
        changed += 1
    return changed


def _chunks(items: list, size: int = 500):
    for start in range(0, len(items), size):
        yield items[start : start + size]
