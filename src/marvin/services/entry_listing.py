"""Which entry types are *listed*: shown wherever entries are listed, counted, searched or indexed.

An internal entry type (``capabilities_json.listed: false``) holds helper content that a feature of Marvin owns and edits
through its own pages: the Social auto-reply rules are the example. Its entries are real entries (they have the normal
editor, history and workflow events), but they stay out of All entries, the status lists (Inbox, Drafts, Needs review,
Approved, Published, Archive, Trash), the sidebar and dashboard counts, search, the AI content index and the default
answer of an entry query. They are still found by naming the type (``entry_type: social-auto-reply``) or the entry
itself (``entries: [slug]``), so the pages and workflows that own them reach them.

Two things make a type internal: the capability flag, and ``INTERNAL_SLUGS``, a core rule for the types of the Social
engagement feature (the shared rule type, and the retired ``social-reply-log`` type, which a workspace that ran the
engine early may still hold: the rule keeps those leftovers out of All entries without a data migration). It can't be
switched off for them. Instagram's older ``ig-*`` types are not on the list: the plugin stopped shipping them and a
migration removed them.

Same shape as ``publish_visibility`` (which says what the publishing API serves): one answer to "is this type listed?".
"""

from __future__ import annotations

INTERNAL_SLUGS = frozenset({"social-auto-reply", "social-reply-log"})
"""Entry types that are internal whatever their capabilities say."""


def is_listed_type(entry_type) -> bool:
    """False for an internal entry type. ``None`` (an entry whose type is unknown) counts as listed."""
    if entry_type is None:
        return True
    caps = getattr(entry_type, "capabilities_json", None)
    caps = caps if isinstance(caps, dict) else {}
    return caps.get("listed") is not False and getattr(entry_type, "slug", None) not in INTERNAL_SLUGS


def unlisted_type_ids(session, group_id) -> list:
    """The ids of the workspace's internal entry types (and any internal system type)."""
    from sqlalchemy import or_

    from marvin.db.models.platform.entry_types import EntryTypes

    rows = session.query(EntryTypes).filter(or_(EntryTypes.group_id == group_id, EntryTypes.group_id.is_(None))).all()
    return [et.id for et in rows if not is_listed_type(et)]


def only_listed(session, group_id, query, column=None):
    """``query`` without the entries of internal types. ``column`` is the entry-type id column of the query
    (default ``Entries.entry_type_id``)."""
    from marvin.db.models.platform.entries import Entries

    excluded = unlisted_type_ids(session, group_id)
    return query.filter((column if column is not None else Entries.entry_type_id).notin_(excluded)) if excluded else query


def unlisted_entry_ids(session, group_id) -> set:
    """The ids of the workspace's entries of internal types — for a result set that has to drop them after the fact
    (an index search returns ids)."""
    from marvin.db.models.platform.entries import Entries

    excluded = unlisted_type_ids(session, group_id)
    if not excluded:
        return set()
    return {r[0] for r in session.query(Entries.id).filter(Entries.group_id == group_id, Entries.entry_type_id.in_(excluded))}


def hidden_type_ids(session, group_id, collection=None) -> list:
    """The internal type ids to leave out of a collection's listing: all of them, except the ones its smart rules name
    (a collection that asks for a type by name lists it)."""
    from marvin.db.models.platform.entry_types import EntryTypes

    excluded = unlisted_type_ids(session, group_id)
    named = ((getattr(collection, "smart_rules", None) or {}).get("entry_types") or []) if collection is not None else []
    if not excluded or not named:
        return excluded
    keep = {r[0] for r in session.query(EntryTypes.id).filter(EntryTypes.id.in_(excluded), EntryTypes.slug.in_(list(named)))}
    return [i for i in excluded if i not in keep]


def listed_clause(session, group_id):
    """A SQL condition for ``select(Entries)`` / ``.where(...)`` queries: the entry's type is listed."""
    import sqlalchemy as sa

    from marvin.db.models.platform.entries import Entries

    excluded = unlisted_type_ids(session, group_id)
    return Entries.entry_type_id.notin_(excluded) if excluded else sa.true()
