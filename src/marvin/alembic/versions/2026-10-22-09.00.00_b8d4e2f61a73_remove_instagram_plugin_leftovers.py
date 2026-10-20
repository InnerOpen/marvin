"""remove the Instagram plugin's old auto-reply leftovers (a data migration; there is nothing to undo)

Jared's decision (2026-10-21): the Instagram plugin's own auto-reply (``ig-auto-reply`` rules, ``ig-reply-log`` entries, the
"Social — Auto-Responses" and "Social — Sent" collections, the ``instagram-auto-reply`` scheduled task) is replaced by Social
in Marvin, nothing of it is live, and core no longer reads any of it. For every workspace that has them, this removes exactly:

  * the entries of the entry types ``ig-auto-reply`` and ``ig-reply-log`` (with their tags, assets, resources, snapshots,
    collection links and embeddings), then those two entry types;
  * the collections ``social-auto-responses`` and ``social-sent``, when they are the plugin's smart collections over those
    types (a collection of the same slug that someone made for something else is left alone). The sidebar's "Instagram" group
    is drawn from the collections an integration installed, so it goes with them;
  * the scheduled task ``instagram-auto-reply`` (a ``run_integration_action`` task whose action is ``auto_reply``), with its
    execution log. The ``instagram-token-refresh`` task and every other task are untouched.

Nothing else is touched. It is idempotent (a second run finds nothing), and works on SQLite and PostgreSQL alike with plain
statements, so it needs no model code. A migration rather than an admin command because it must happen once, for every
workspace, on the deploy that stops reading these types, and nobody has to remember to run it. The downgrade does nothing:
deleted entries can't be rebuilt, and the schema didn't change.

Revision ID: b8d4e2f61a73
Revises: ef911a9c1779
Create Date: 2026-10-22 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "b8d4e2f61a73"
down_revision: str | None = "ef911a9c1779"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_TYPES = ("ig-auto-reply", "ig-reply-log")
COLLECTIONS = {"social-auto-responses": "ig-auto-reply", "social-sent": "ig-reply-log"}
TASK_SLUG = "instagram-auto-reply"
TASK_TYPE = "run_integration_action"
TASK_ACTION = "auto_reply"
GUID = marvin.db.migration_types.GUID


def upgrade() -> None:
    remove_leftovers(op.get_bind())


def downgrade() -> None:
    """Nothing to undo: removed content isn't rebuilt and the schema is unchanged."""


def _tables():
    id_ = lambda: sa.column("id", GUID())  # noqa: E731
    return {
        "entries": sa.table("entries", id_(), sa.column("entry_type_id", GUID())),
        "types": sa.table("entry_types", id_(), sa.column("slug", sa.String())),
        "entry_children": [
            sa.table(name, sa.column("entry_id", GUID())) for name in ("entry_collections", "entry_tags", "entry_assets", "entry_resources", "entry_snapshots")
        ],
        "embeddings": sa.table("ai_embeddings", sa.column("entity_type", sa.String()), sa.column("entity_id", GUID())),
        "collections": sa.table(
            "collections", id_(), sa.column("slug", sa.String()), sa.column("is_smart", sa.Boolean()), sa.column("smart_rules", sa.JSON())
        ),
        "collection_children": [
            sa.table(name, sa.column("collection_id", GUID())) for name in ("entry_collections", "collection_assets", "collection_resources")
        ],
        "tasks": sa.table(
            "scheduled_tasks", id_(), sa.column("slug", sa.String()), sa.column("task_type", sa.String()), sa.column("task_config", sa.JSON())
        ),
        "task_log": sa.table("scheduled_task_execution_log", sa.column("task_id", GUID())),
    }  # fmt: skip


def remove_leftovers(bind) -> dict:
    """The whole clean-up on one connection; returns what it removed (``entries``, ``entry_types``, ``collections``, ``tasks``)."""
    t = _tables()
    removed = {"entries": 0, "entry_types": 0, "collections": 0, "tasks": 0}
    removed["tasks"] = _remove_tasks(bind, t)
    removed["collections"] = _remove_collections(bind, t)
    removed["entries"], removed["entry_types"] = _remove_entries_and_types(bind, t)
    return removed


def _remove_tasks(bind, t) -> int:
    tasks = t["tasks"]
    rows = bind.execute(sa.select(tasks.c.id, tasks.c.task_config).where(tasks.c.slug == TASK_SLUG, tasks.c.task_type == TASK_TYPE)).all()
    ids = [i for i, config in rows if isinstance(config, dict) and config.get("action") == TASK_ACTION]
    for chunk in _chunks(ids):
        bind.execute(t["task_log"].delete().where(t["task_log"].c.task_id.in_(chunk)))
        bind.execute(tasks.delete().where(tasks.c.id.in_(chunk)))
    return len(ids)


def _remove_collections(bind, t) -> int:
    coll = t["collections"]
    rows = bind.execute(sa.select(coll.c.id, coll.c.slug, coll.c.is_smart, coll.c.smart_rules).where(coll.c.slug.in_(list(COLLECTIONS)))).all()
    ids = []
    for cid, slug, is_smart, rules in rows:
        named = (rules or {}).get("entry_types") if isinstance(rules, dict) else None
        if is_smart and named == [COLLECTIONS[slug]]:
            ids.append(cid)
    for chunk in _chunks(ids):
        for child in t["collection_children"]:
            bind.execute(child.delete().where(child.c.collection_id.in_(chunk)))
        bind.execute(coll.delete().where(coll.c.id.in_(chunk)))
    return len(ids)


def _remove_entries_and_types(bind, t) -> tuple[int, int]:
    types, entries = t["types"], t["entries"]
    type_ids = [r[0] for r in bind.execute(sa.select(types.c.id).where(types.c.slug.in_(ENTRY_TYPES)))]
    removed = 0
    for type_id in type_ids:
        entry_ids = [r[0] for r in bind.execute(sa.select(entries.c.id).where(entries.c.entry_type_id == type_id))]
        for chunk in _chunks(entry_ids):
            for child in t["entry_children"]:
                bind.execute(child.delete().where(child.c.entry_id.in_(chunk)))
            bind.execute(t["embeddings"].delete().where(t["embeddings"].c.entity_type == "entry", t["embeddings"].c.entity_id.in_(chunk)))
            bind.execute(entries.delete().where(entries.c.id.in_(chunk)))
        removed += len(entry_ids)
        bind.execute(types.delete().where(types.c.id == type_id))
    return removed, len(type_ids)


def _chunks(items: list, size: int = 500):
    for start in range(0, len(items), size):
        yield items[start : start + size]
