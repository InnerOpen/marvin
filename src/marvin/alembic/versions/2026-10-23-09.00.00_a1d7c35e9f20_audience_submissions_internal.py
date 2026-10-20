"""internal entry types are the flag only: ``listed: false`` on the Social types and on the forms (a data migration)

"Internal" used to be three things: ``capabilities.listed: false``, a core slug rule for the Social types (``social-auto-reply``,
``social-reply-log``) and, in this release's first design, "a form whose submissions go to the Audience". It is one thing now:
``capabilities.listed`` is false (services/entry_listing.py), shown as a switch on the entry type editor. So that nothing
reappears among the content when the slug rule goes, this sets ``listed: false`` on

  1. every entry type with the slug ``social-auto-reply`` or ``social-reply-log`` (any workspace);
  2. every submittable entry type whose ``submission.destination`` isn't ``entries``: the default is ``audience``, which also
     covers a form that never stored the setting (what a form's destination means for ``listed`` from here on is a default applied
     when the setting is changed).

and, for the entries of the types it changed, removes what is derived from the listing rule:

  - their membership in the smart collections that don't name their type (Inbox, Needs review, Drafts, Archive…; not the Trash,
    which lists internal entries so they can be restored): membership is derived, so the sidebar's Inbox count would otherwise
    keep counting entries that are no longer in any list;
  - their embeddings in the AI index (an entry of an unlisted type is never indexed).

No entry or collection is changed or deleted, and nothing else on an entry type changes. Idempotent: a type already unlisted is
left as it is. The downgrade does nothing: the flags are data (a person may have switched one on since) and the derived rows come
back from the nightly smart-collection resync; the schema didn't change.

Revision ID: a1d7c35e9f20
Revises: b8d4e2f61a73
Create Date: 2026-10-23 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "a1d7c35e9f20"
down_revision: str | None = "b8d4e2f61a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = marvin.db.migration_types.GUID


def upgrade() -> None:
    leave_listing(op.get_bind())


def downgrade() -> None:
    """Nothing to undo: derived data, rebuilt by the smart-collection resync."""


SOCIAL_SLUGS = ("social-auto-reply", "social-reply-log")


def _tables():
    return {
        "types": sa.table("entry_types", sa.column("id", GUID()), sa.column("slug", sa.String()), sa.column("capabilities_json", sa.JSON())),
        "entries": sa.table("entries", sa.column("id", GUID()), sa.column("entry_type_id", GUID())),
        "collections": sa.table(
            "collections",
            sa.column("id", GUID()),
            sa.column("is_smart", sa.Boolean()),
            sa.column("target_type", sa.String()),
            sa.column("smart_rules", sa.JSON()),
        ),
        "links": sa.table("entry_collections", sa.column("collection_id", GUID()), sa.column("entry_id", GUID())),
        "embeddings": sa.table("ai_embeddings", sa.column("entity_type", sa.String()), sa.column("entity_id", GUID())),
    }


def types_to_unlist(bind) -> list[tuple]:
    """``(id, slug, capabilities)`` of every type that should be unlisted and isn't yet."""
    t = _tables()["types"]
    found = []
    for type_id, slug, caps in bind.execute(sa.select(t.c.id, t.c.slug, t.c.capabilities_json)).all():
        caps = caps if isinstance(caps, dict) else {}
        if caps.get("listed") is False:
            continue
        submission = caps.get("submission")
        audience_form = caps.get("submittable") is True and not (isinstance(submission, dict) and submission.get("destination") == "entries")
        if slug in SOCIAL_SLUGS or audience_form:
            found.append((type_id, slug, caps))
    return found


def leave_listing(bind) -> None:
    t = _tables()
    smart = t["collections"]
    for type_id, slug, caps in types_to_unlist(bind):
        bind.execute(t["types"].update().where(t["types"].c.id == type_id).values(capabilities_json={**caps, "listed": False}))
        of_type = sa.select(t["entries"].c.id).where(t["entries"].c.entry_type_id == type_id)
        rules = sa.cast(smart.c.smart_rules, sa.Text)
        # The Trash (rules ask for "trashed") keeps a trashed entry: it lists internal entries so they can be restored.
        not_naming = sa.select(smart.c.id).where(
            smart.c.is_smart == sa.true(), smart.c.target_type == "entry", ~rules.like(f'%"{slug}"%'), ~rules.like('%"trashed"%')
        )
        bind.execute(t["links"].delete().where(t["links"].c.entry_id.in_(of_type), t["links"].c.collection_id.in_(not_naming)))
        bind.execute(t["embeddings"].delete().where(t["embeddings"].c.entity_type == "entry", t["embeddings"].c.entity_id.in_(of_type)))
