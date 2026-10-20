"""social replies on inbox items; internal entry types; retire the Social blueprint collections

Schema (additive):
  - ``social_inbox_items.reply_rule`` / ``reply_text`` / ``reply_note`` — the reply is recorded on the inbox item (the item
    is the reply log now), next to the columns the inbox already had (``reply_mode``, ``reply_rehearsal``, ``reply_id``,
    ``replied_at``, ``replied_by``).

Data (idempotent, none of it touches an entry or its content):
  1. items answered before this (they point at a ``social-reply-log`` entry) get ``reply_rule`` / ``reply_text`` /
     ``reply_note`` copied from that entry, so the Replies view has them;
  2. entries of the internal Social types (``social-auto-reply``, ``social-reply-log``, ``ig-auto-reply``, ``ig-reply-log``;
     services/entry_listing.py) leave every smart collection that doesn't name their type (Inbox, Drafts, Published…): the
     membership is derived, and the live rules no longer add it;
  3. their embeddings are removed from the AI index;
  4. the two collections the retired Social blueprint set made (``social-auto-reply-rules``, ``social-replies``): removed
     when still as the blueprint made them and empty (a smart collection's membership is derived, so no entry is touched),
     else only taken off the sidebar.

Downgrade drops the three columns. The data steps are not reversed (the collections and memberships are derived and come
back from the blueprints / the nightly smart-collection resync).

Revision ID: ef911a9c1779
Revises: 7c3f9a1e5b82
Create Date: 2026-10-21 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "ef911a9c1779"
down_revision: str | None = "7c3f9a1e5b82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTERNAL_SLUGS = ("social-auto-reply", "social-reply-log", "ig-auto-reply", "ig-reply-log")
RETIRED_COLLECTIONS = {
    "social-auto-reply-rules": ("Social — Auto-reply rules", "social-auto-reply"),
    "social-replies": ("Social — Replies", "social-reply-log"),
}
GUID = marvin.db.migration_types.GUID


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reply_rule", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reply_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reply_note", sa.String(), nullable=True))
    bind = op.get_bind()
    _backfill_replies(bind)
    _leave_collections(bind)
    _purge_embeddings(bind)
    _retire_collections(bind)


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_column("reply_note")
        batch_op.drop_column("reply_text")
        batch_op.drop_column("reply_rule")


def _tables():
    return {
        "items": sa.table(
            "social_inbox_items",
            sa.column("id", GUID()),
            sa.column("group_id", GUID()),
            sa.column("reply_log_slug", sa.String()),
            sa.column("reply_rule", sa.String()),
            sa.column("reply_text", sa.Text()),
            sa.column("reply_note", sa.String()),
        ),
        "entries": sa.table("entries", sa.column("id", GUID()), sa.column("group_id", GUID()), sa.column("slug", sa.String()),
                            sa.column("entry_type_id", GUID()), sa.column("data_json", sa.JSON())),
        "types": sa.table("entry_types", sa.column("id", GUID()), sa.column("slug", sa.String())),
        "collections": sa.table(
            "collections",
            sa.column("id", GUID()),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_smart", sa.Boolean()),
            sa.column("target_type", sa.String()),
            sa.column("smart_rules", sa.JSON()),
            sa.column("in_sidebar", sa.Boolean()),
        ),
        "links": sa.table("entry_collections", sa.column("collection_id", GUID()), sa.column("entry_id", GUID())),
        "embeddings": sa.table("ai_embeddings", sa.column("entity_type", sa.String()), sa.column("entity_id", GUID())),
    }  # fmt: skip


def _internal_entry_ids(t):
    return sa.select(t["entries"].c.id).join(t["types"], t["types"].c.id == t["entries"].c.entry_type_id).where(t["types"].c.slug.in_(INTERNAL_SLUGS))


def _backfill_replies(bind) -> None:
    t = _tables()
    items, entries = t["items"], t["entries"]
    rows = bind.execute(sa.select(items.c.id, items.c.group_id, items.c.reply_log_slug).where(items.c.reply_log_slug.isnot(None))).all()
    for item_id, group_id, slug in rows:
        data = bind.execute(sa.select(entries.c.data_json).where(entries.c.group_id == group_id, entries.c.slug == slug)).scalar()
        if not isinstance(data, dict):
            continue
        rule = data.get("rule")
        bind.execute(
            items.update()
            .where(items.c.id == item_id, items.c.reply_rule.is_(None))
            .values(
                reply_rule=None if rule == "inbox" else rule,  # "inbox" was a person's reply, which has no rule
                reply_text=data.get("reply"),
                reply_note=data.get("error"),
            )
        )


def _leave_collections(bind) -> None:
    """Remove internal entries from every smart collection that doesn't name their type."""
    t = _tables()
    smart = t["collections"]
    for slug in INTERNAL_SLUGS:
        named = sa.cast(smart.c.smart_rules, sa.Text).like(f'%"{slug}"%')
        not_naming = sa.select(smart.c.id).where(smart.c.is_smart == sa.true(), smart.c.target_type == "entry", ~named)
        of_type = sa.select(t["entries"].c.id).join(t["types"], t["types"].c.id == t["entries"].c.entry_type_id).where(t["types"].c.slug == slug)
        bind.execute(t["links"].delete().where(t["links"].c.entry_id.in_(of_type), t["links"].c.collection_id.in_(not_naming)))


def _purge_embeddings(bind) -> None:
    t = _tables()
    bind.execute(t["embeddings"].delete().where(t["embeddings"].c.entity_type == "entry", t["embeddings"].c.entity_id.in_(_internal_entry_ids(t))))


def _retire_collections(bind) -> None:
    t = _tables()
    coll, links = t["collections"], t["links"]
    rows = bind.execute(
        sa.select(coll.c.id, coll.c.slug, coll.c.name, coll.c.is_smart, coll.c.smart_rules).where(coll.c.slug.in_(list(RETIRED_COLLECTIONS)))
    ).all()
    for cid, slug, name, is_smart, rules in rows:
        expected_name, type_slug = RETIRED_COLLECTIONS[slug]
        pristine = bool(is_smart) and name == expected_name and rules == {"entry_types": [type_slug], "match": "all"}
        held = bind.execute(sa.select(sa.func.count()).select_from(links).where(links.c.collection_id == cid)).scalar() or 0
        if pristine and held == 0:
            bind.execute(coll.delete().where(coll.c.id == cid))
        else:
            bind.execute(coll.update().where(coll.c.id == cid).values(in_sidebar=False))
