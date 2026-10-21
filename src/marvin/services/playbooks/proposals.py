"""Proposed Playbook changes: an agent drafts a change as a separate inbox draft, and publishing it replaces the live one.

A change is an entry of the ``playbook`` type whose ``replaces`` field names the published Playbook it would replace
(``propose_playbook_change``, ``EntryService._publish_playbook_change``). Agents themselves never edit a published Playbook:
``agent_change_refusal`` is what their write tools ask first.
"""

from __future__ import annotations

from marvin.services.playbooks import PLAYBOOK_STATUS, is_playbook

REPLACES_KEY = "replaces"  # data_json key of a proposed change: the name (slug) of the published Playbook it would replace
CHANGE_KEYS = ("description", "body", "license", "compatibility", "allowed_tools", "manual_only")  # what publishing a change copies over
CHANGE_SUFFIX = "-change"


def agent_change_refusal(session, entry) -> str | None:
    """Why an agent's write tool may not change ``entry``, or None. A published Playbook steers every agent run, so
    changing, archiving or trashing it is a person's call (an Admin's), whoever the agent is working for."""
    if entry.status == PLAYBOOK_STATUS and is_playbook(session, entry):
        return (
            f"'{entry.title}' is a published Playbook: agents can draft Playbooks but never change or remove a published one. "
            "An Admin does that from the Playbooks page."
        )
    return None


def change_target(session, entry):
    """For a Playbook draft that proposes a change (its ``replaces`` field names a Playbook), the live entry row it would
    replace; None for any other entry. Raises HTTP 409 when it names one that is gone or no longer published, so a change
    is never published as a second, differently named Playbook. An Admin can clear ``replaces`` to publish it as a new one."""
    from fastapi import HTTPException

    from marvin.db.models.platform.entries import Entries

    name = str((getattr(entry, "data_json", None) or {}).get(REPLACES_KEY) or "").strip().lower()
    if not name or name == (entry.slug or "").lower() or not is_playbook(session, entry):
        return None  # naming itself is no change (an agent once filled the field that way): it publishes as itself
    target = (
        session.query(Entries)
        .filter(Entries.group_id == entry.group_id, Entries.entry_type_id == entry.entry_type_id, Entries.slug == name, Entries.id != entry.id)
        .first()
    )
    if target is None or target.status != PLAYBOOK_STATUS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This change replaces the Playbook '{name}', which isn't published. "
                "Publish that one again, or clear 'Replaces' to publish this as a new Playbook."
            ),
        )
    return target


def changed_data(live_data: dict | None, change_data: dict | None) -> dict:
    """The live Playbook's data once a proposed change is published: its content (``CHANGE_KEYS``) comes from the change
    (a key the change leaves out is cleared), everything else (name, any other field) stays as it was."""
    merged = {k: v for k, v in (live_data or {}).items() if k not in CHANGE_KEYS}
    merged.update({k: v for k, v in (change_data or {}).items() if k in CHANGE_KEYS})
    return merged
