"""Where an asset lives: the Assets library, or Ask files.

A file attached to a question in the bubble or on the Ask page is an *Ask file*: uploaded so the agent can open
it, not added to the library. It stays out of everything that lists, counts, searches, publishes or sweeps the
library (the Assets page, the AI's asset queries, smart collections, the site API, the search index, the
orphaned-assets task) until someone moves it there — the Ask files tab, or the agent's `move_to_assets` — and
attaching it to an entry moves it first, so a site never links a file the site API won't serve.
"""

from typing import Any

LIBRARY = "library"
ASK = "ask"
SCOPES = (LIBRARY, ASK)

# The `metadata.attachedVia` values the bubble and the Ask page upload with: such an upload is an Ask file.
ASK_SURFACES = ("bubble", "ask_page")


def upload_scope(metadata: dict | None) -> str:
    """The scope an upload lands in: an Ask file when a chat surface sent it, else the library."""
    return ASK if (metadata or {}).get("attachedVia") in ASK_SURFACES else LIBRARY


def in_library(column: Any | None = None):
    """SQL filter for library assets (``Assets.scope == 'library'``); pass another mapped column to filter a join."""
    if column is None:
        from marvin.db.models.platform import Assets

        column = Assets.scope
    return column == LIBRARY


def is_ask_file(asset: Any) -> bool:
    return getattr(asset, "scope", LIBRARY) == ASK


def move_to_library(session, group_id, asset_ids, *, actor_id=None, event_bus=None, commit: bool = True) -> list:
    """Move the Ask files among ``asset_ids`` (this workspace's, not in the Trash) into the library, and emit
    ``asset_uploaded`` for each, as a new library asset — workflows and webhooks on it run now. Returns the rows
    moved; library assets and unknown ids are skipped."""
    from marvin.db.models.platform import Assets
    from marvin.services import trash
    from marvin.services.collections.smart_collections import sync_item
    from marvin.services.event_bus_service.event_types import EventOperation, EventTypes

    ids = [i for i in asset_ids or [] if i]
    if not ids:
        return []
    rows = session.query(Assets).filter(Assets.group_id == group_id, Assets.id.in_(ids), Assets.scope == ASK, Assets.trashed_at.is_(None)).all()
    for row in rows:
        row.scope = LIBRARY
        sync_item(session, group_id, row, "asset")  # it can join asset-type smart collections now
    if not rows:
        return []
    if commit:
        session.commit()
    else:
        session.flush()
    for row in rows:
        trash._emit(
            session, group_id, trash.ASSET, row, EventTypes.asset_uploaded, EventOperation.create,
            f"Asset {row.name} moved from Ask files to the library", actor_id=actor_id, event_bus=event_bus,
        )  # fmt: skip
    return rows


def _uuids(ids) -> list:
    import uuid

    out = []
    for i in ids:
        try:
            out.append(uuid.UUID(str(i)))
        except ValueError:
            continue
    return out


def _attachment_ids(meta) -> set[str]:
    return {str(a.get("id")) for a in ((meta or {}).get("attachments") or []) if isinstance(a, dict) and a.get("id")}


def trash_thread_files(session, group_id, thread, *, actor_id=None, event_bus=None) -> list:
    """A thread is being deleted: move the Ask files its questions carried to the Trash (restorable), except those
    another thread of the workspace still carries (a hand-off's specialist gets its parent's). Library assets are
    never touched. Returns the ids trashed; call before deleting the thread."""
    from marvin.db.models.groups.ai_threads import AIThreadMessageModel
    from marvin.db.models.platform import Assets
    from marvin.services import trash

    ids = set().union(*(_attachment_ids(m.meta_json) for m in thread.messages if m.role == "user"))
    if not ids:
        return []
    elsewhere = (
        session.query(AIThreadMessageModel.meta_json)
        .filter(
            AIThreadMessageModel.group_id == group_id,
            AIThreadMessageModel.thread_id != thread.id,
            AIThreadMessageModel.role == "user",
            AIThreadMessageModel.meta_json.isnot(None),
        )
        .all()
    )
    for (meta,) in elsewhere:
        ids -= _attachment_ids(meta)
    asks = session.query(Assets.id).filter(Assets.group_id == group_id, Assets.id.in_(_uuids(ids)), Assets.scope == ASK, Assets.trashed_at.is_(None))
    trashed = []
    for (asset_id,) in asks.all():
        trash.trash(session, group_id, trash.ASSET, asset_id, actor_id=actor_id, event_bus=event_bus)
        trashed.append(asset_id)
    return trashed
