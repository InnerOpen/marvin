"""Which entry types are *listed*: shown wherever entries are listed, counted, searched or indexed.

An internal entry type (``capabilities_json.listed: false``) holds helper content that a feature of Marvin owns and edits
through its own pages: the Social auto-reply rules are the example. Its entries are real entries (they have the normal
editor, history and workflow events), but they stay out of All entries, the status lists (Inbox, Drafts, Needs review,
Approved, Published, Archive), the sidebar and dashboard counts, search, the AI content index and the default
answer of an entry query. The one exception is the Trash: a trashed internal entry is listed and counted there, so it can
be restored (a trashed Social rule would otherwise be lost to its owner), and emptying the Trash deletes it like any other.
They are still found by naming the type (``entry_type: social-auto-reply``) or the entry
itself (``entries: [slug]``), so the pages and workflows that own them reach them.

One thing makes a type internal: ``capabilities_json.listed`` is false. It is a single, visible switch (the entry type editor's
"Show in content lists", and an **Internal** badge on the Content model list), independent of whatever feature uses the type:

* Social creates its rule type unlisted (``services/integrations/social_setup.py``); a migration set the flag on the older
  ``social-auto-reply`` and ``social-reply-log`` types, so there is no slug rule any more.
* A submittable type (a "form") has ``submission.destination``: ``audience`` (the default) shows its submissions under Audience ›
  Submissions, ``entries`` handles them as ordinary entries to review and publish. Choosing the destination sets ``listed`` as a
  convenience default (audience unlisted, entries listed; ``EntryTypesRepository``); after that ``listed`` is toggled on its own. A
  form switched to listed shows its entries in both Audience and the content lists.

Same shape as ``publish_visibility`` (which says what the publishing API serves): one answer to "is this type listed?".

A smart collection's ``listed`` rule (``any`` | ``listed`` | ``unlisted``, below) is the one place that chooses between the two
kinds: ``any`` is the behaviour above (listed types, plus an unlisted type the rules name), ``listed`` keeps only listed types
(naming an unlisted one then matches nothing) and ``unlisted`` keeps only unlisted types, all of them without naming each.
"""

from __future__ import annotations

LISTED_MODES = ("any", "listed", "unlisted")
"""The values of a smart collection's ``listed`` rule; absent means ``any``."""


def listed_mode(rules: dict | None) -> str | None:
    """A smart collection's ``listed`` rule: ``any`` (the default, also when absent or null), ``listed`` or ``unlisted``.
    None for a value that is none of those — callers fail closed on it, a typo must not widen a collection."""
    value = (rules or {}).get("listed")
    if value is None:
        return "any"
    return value if isinstance(value, str) and value in LISTED_MODES else None


def check_listed_rule(rules: dict | None) -> None:
    """Raise ``ValueError`` when ``rules`` carries a ``listed`` that isn't one of ``LISTED_MODES`` (the schema's validation)."""
    if listed_mode(rules) is None:
        raise ValueError(f"smart_rules.listed must be one of {', '.join(LISTED_MODES)}.")


def _caps(entry_type) -> dict:
    caps = getattr(entry_type, "capabilities_json", None)
    return caps if isinstance(caps, dict) else {}


def submission_settings(entry_type) -> dict | None:
    """The submission settings of a submittable type (``{}`` when it stores none), or None for a type that isn't a form."""
    caps = _caps(entry_type)
    if caps.get("submittable") is not True:
        return None
    submission = caps.get("submission")
    return submission if isinstance(submission, dict) else {}


def submission_destination(entry_type) -> str | None:
    """``audience`` or ``entries`` for a submittable type (the default is audience), None for a type that isn't a form."""
    submission = submission_settings(entry_type)
    if submission is None:
        return None
    return "entries" if submission.get("destination") == "entries" else "audience"


def submission_kind(entry_type) -> str | None:
    """``message`` or ``signup`` for a submittable type (the default is message), None for a type that isn't a form."""
    submission = submission_settings(entry_type)
    if submission is None:
        return None
    return "signup" if submission.get("kind") == "signup" else "message"


def with_destination_default(old_caps: dict | None, new_caps: dict) -> dict:
    """``new_caps`` with ``listed`` set from the form's destination, when the destination is what changes.

    The convenience default, applied on create and update of an entry type: choosing ``audience`` unlists the type (its
    submissions are read under Audience › Submissions), choosing ``entries`` lists it, and a type that stops being a form after
    being an Audience form is listed again. A new form that doesn't say is an Audience form (the default destination), so it is
    unlisted. It never overrides a ``listed`` the caller set in the same request (on create: present; on update: different from the
    stored one, since an editor always sends the stored value back), and never touches a type whose destination isn't changing.
    After this, ``listed`` is toggled on its own.
    """
    old = old_caps if isinstance(old_caps, dict) else {}
    old_dest = submission_destination(_Caps(old))
    new_dest = submission_destination(_Caps(new_caps))
    if new_dest == old_dest:
        return new_caps
    if old_caps is None:  # a new type: a `listed` in the request is the caller's own choice
        if "listed" in new_caps:
            return new_caps
    elif "listed" in new_caps and new_caps["listed"] != old.get("listed", True):  # changed in this request: the caller's own choice
        return new_caps
    if new_dest == "audience":
        return {**new_caps, "listed": False}
    if new_dest == "entries":
        return {**new_caps, "listed": True}
    if old_dest == "audience":  # no longer a form
        return {**new_caps, "listed": True}
    return new_caps


class _Caps:
    def __init__(self, caps: dict) -> None:
        self.capabilities_json = caps


def is_listed_type(entry_type) -> bool:
    """False for an internal entry type. ``None`` (an entry whose type is unknown) counts as listed."""
    if entry_type is None:
        return True
    return _caps(entry_type).get("listed") is not False


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
    (a collection that asks for a type by name lists it). None for the Trash, which lists its internal entries too.
    The ``listed`` rule overrides the naming: ``unlisted`` hides none, ``listed`` hides all of them."""
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.entries.trash import is_trash_collection

    if collection is not None and is_trash_collection(collection):
        return []

    excluded = unlisted_type_ids(session, group_id)
    rules = (getattr(collection, "smart_rules", None) or {}) if collection is not None else {}
    mode = listed_mode(rules)
    if mode == "unlisted":
        return []
    named = (rules.get("entry_types") or []) if mode == "any" else []
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
