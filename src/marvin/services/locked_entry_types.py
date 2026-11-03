"""Entry types a feature of Marvin is built on: their fields and settings are fixed, so they can't be edited or deleted.

A workspace owns most of its entry types, and the type editor changes any of them. The Playbook type is different: Marvin
reads a Playbook's fields by key (``name``, ``description``, ``body``…) and makes the type itself (``services/playbooks``), so
a changed field would break agents that load Playbooks. Such a type is *locked*, by its slug in the workspace that owns it:
the repository refuses to update or delete it, and the type's page says why.

Not the same as ``is_system``, which marks a type shipped to every workspace (``group_id`` NULL) and only limits what can be
changed, and not the same as an *internal* type (``capabilities_json.listed: false``, ``services/entry_listing.py``), which
is only kept out of content lists.
"""

from __future__ import annotations

LOCKED_ENTRY_TYPES: dict[str, str] = {
    "playbook": (
        "Playbooks are built on this type, and agents read its fields by name, so it can't be edited or deleted. "
        "Edit the Playbooks themselves instead."
    ),
}


def lock_reason(slug: str | None, group_id: object | None) -> str | None:
    """Why the entry type can't be changed (safe to show), or None. Only a workspace's own type is locked (``group_id`` set)."""
    return LOCKED_ENTRY_TYPES.get(slug or "") if group_id is not None else None
