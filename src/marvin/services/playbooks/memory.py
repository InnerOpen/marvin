"""What a conversation remembers of the Playbooks it loaded, and where each Playbook was used lately.

An Ask thread replays only the user's and the assistant's words to the model: the tool results of old turns (where a
loaded Playbook's text lives) are stored for the page but never sent again. So a Playbook loaded on turn 1 would be
gone by turn 2. The thread therefore records the Playbooks in effect in each assistant turn's ``meta_json["playbooks"]``
(``[{"id", "name"}]``, no migration), and ``reload_block`` puts their current text back in the system prompt on every
later turn. Pure functions over a session, a thread or a trace.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from marvin.services.playbooks import USED_KEY, playbooks_used, published_playbook

META_KEY = "playbooks"  # AIThreadMessageModel.meta_json[META_KEY] = [{"id", "name"}, …]: the Playbooks in effect for that reply
RELOAD_MAX_CHARS = 40_000  # one thread's re-included text; a Playbook that doesn't fit is named so the agent can load it again
RECENT_SCAN = 2000  # newest executions looked at for "used recently"
RECENT_PER_PLAYBOOK = 20


def in_effect(thread, steps) -> list[dict]:
    """The Playbooks in effect after this run: the thread's earlier ones, then any this run loaded (first-load order)."""
    kept: dict[str, dict] = {}
    for entry in [*thread_playbooks(thread), *playbooks_used(steps)]:
        kept.setdefault(entry["id"], {"id": entry["id"], "name": entry.get("name")})
    return list(kept.values())


def thread_playbooks(thread) -> list[dict]:
    """The Playbooks the thread has loaded so far, as ``{"id", "name"}`` in first-load order ([] with no thread)."""
    kept: dict[str, dict] = {}
    for message in sorted(getattr(thread, "messages", None) or [], key=lambda m: m.seq):
        for entry in (message.meta_json or {}).get(META_KEY) or []:
            if isinstance(entry, dict) and entry.get("id"):
                kept.setdefault(str(entry["id"]), {"id": str(entry["id"]), "name": entry.get("name")})
    return list(kept.values())


def reload_block(session, group_id, thread, skip: Iterable[str] = ()) -> str:
    """The system-prompt section that keeps the thread's Playbooks in effect ("" when it has loaded none).

    The text is the Playbook's published text now: an edit reaches the conversation, and one that has since been
    unpublished or trashed is dropped (an agent never sees what it could not load). Names in ``skip`` (the agent's
    always-load Playbooks, already in the frame in full) are left out so none appears twice.
    """
    skip = set(skip)
    sections: list[str] = []
    skipped: list[str] = []
    room = RELOAD_MAX_CHARS
    for entry in thread_playbooks(thread):
        if (entry.get("name") or "") in skip:
            continue
        found = published_playbook(session, group_id, entry.get("name") or "")
        if found is None or found.id != entry["id"]:
            continue
        if len(found.body) > room:
            skipped.append(found.name)
            continue
        room -= len(found.body)
        sections.append(f"### {found.name}\n{found.body}")
    if not sections and not skipped:
        return ""
    block = (
        "## Playbooks loaded earlier in this conversation\n"
        "You loaded these Playbooks on an earlier turn. They stay in effect for the rest of the conversation: keep following "
        "them where they apply, without loading them again. They do not grant any tools you were not already given.\n\n" + "\n\n".join(sections)
    )
    if skipped:
        block += f"\n\n(Too long to repeat here: {', '.join(skipped)}. Load again if needed.)"
    return block


def recent_uses(session, group_id, *, per_playbook: int = RECENT_PER_PLAYBOOK) -> dict[str, list[dict]]:
    """``{playbook id: [use, …]}``, newest first, from the executions that recorded loading it.

    A use is ``{"execution_id", "agent_slug", "used_at", "thread_id"}``; ``thread_id`` is the Ask conversation the run
    belongs to, when there is one (the "run" a person can open). Reads the newest RECENT_SCAN executions of the workspace.
    """
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    rows = (
        session.query(AIExecutionModel)
        .filter(AIExecutionModel.group_id == group_id, AIExecutionModel.metadata_json.isnot(None))
        .order_by(AIExecutionModel.created_at.desc())
        .limit(RECENT_SCAN)
    )
    uses: dict[str, list[dict]] = {}
    for row in rows:
        meta = row.metadata_json or {}
        for entry in meta.get(USED_KEY) or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            bucket = uses.setdefault(str(entry["id"]), [])
            if len(bucket) < per_playbook:
                bucket.append(
                    {
                        "execution_id": row.id,
                        "agent_slug": row.operation_slug.removeprefix("agent:") if row.operation_slug.startswith("agent:") else None,
                        "used_at": _when(row),
                        "thread_id": meta.get("thread_id"),
                    }
                )
    return uses


def _when(row) -> datetime | None:
    return row.started_at or row.created_at
