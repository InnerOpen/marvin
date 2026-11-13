"""Delete many entries at once: the entries a saved search selects, moved to the Trash or deleted for good, in chunks.

The one-at-a-time path (EntryService.trash / delete) does per-entry work: an `entry_updated` + `entry_trashed` (or
`entry_deleted`), and each of those runs the listeners (smart collections, the search index, the site rebuild, the
workflows and webhooks on those events). That is right for one entry and far too slow for an import's worth of them
(2,000 entries took over an hour and starved the backend). This path does the same bookkeeping once per chunk of rows
instead, and skips the per-entry events on purpose: one ``entries_bulk_deleted`` says what went.

- The selection is an entry query spec (services/entries/query.py, the language of ``POST /entries/query``). Only the
  keys that spec knows are accepted (an unknown key would be ignored, which widens a selection), and it must narrow by
  something (types, fields, entries, a collection, tags, text or ``where``): never the whole workspace.
- ``preview`` counts what a spec selects, by entry type, and changes nothing. ``execute`` must be passed the preview's
  ``total`` back (``confirm_total``): if the selection no longer has that many entries, nothing is done
  (:class:`BulkDeleteMismatch`, with the fresh counts). That is what makes "preview first" a rule rather than advice.
- ``trash`` (restorable): status ``trashed`` and ``metadata_json.trash`` exactly as EntryService records it
  (previous_status, trashed_at, trashed_by), plus ``slug``: each slug is moved aside (``<slug>--trashed-<id>``) so the
  slugs are free for new entries (an import made again) — a restore puts the slug back when no other entry took it
  (EntryService._trash_bookkeeping). Entries already in the Trash are not touched. A scheduled publish is cleared.
  Smart-collection membership is updated (out of every smart collection but the Trash, into the Trash); manual
  collections, attachments and tags stay, as for one entry.
- ``permanent``: a set-based ``DELETE``. Collection, asset, resource and tag links, snapshots and automation results go
  with the rows (ON DELETE CASCADE); assets and resources themselves are never deleted.
- Both remove the entries' search-index rows (``ai_embeddings``, which has no foreign key) and, when a published entry
  went, ask for one site rebuild.

Each chunk (CHUNK_SIZE rows) is its own transaction, with a short pause after it, so a long job never holds one
transaction and leaves the (single) worker room for other requests. A chunk that fails stops the job; the chunks before
it stay done and the summary event says how far it got.

``start_job`` runs ``execute`` in the background for the REST endpoint, one at a time per workspace, like the search
reindex (services/ai/reindex_jobs.py): in-process progress for ``job_status``, the summary event for the record.
A workflow's ``delete_entries`` step calls ``execute`` itself: the run is the job there.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import UTC, datetime

from marvin.core.root_logger import get_logger

from . import query as entry_query
from .trash import TRASHED

logger = get_logger(__name__)

CHUNK_SIZE = 500
"""Rows per transaction."""
PAUSE_SECONDS = 0.05
"""Pause after each chunk, so the other requests of a single worker get their turn."""
MODES = ("trash", "permanent")
TRASH_KEY = "trash"  # metadata_json key, as in entry_service
ASIDE = "--trashed-"
"""What a bulk trash adds to a slug (with 8 characters of the entry's id) to free it for new entries."""
NARROWING_KEYS = (
    *("entry_type", "entry_types", "text", "query", "tags", "collection", "collections"),
    *("entries", "asset", "resource", "fields", "data", "metadata", "where"),
)
"""A spec must use at least one of these: status, dates and has_* alone would select most of a workspace."""


class BulkDeleteError(ValueError):
    """The request can't be carried out as asked (a spec that is too wide or unknown, a missing confirmation)."""


class BulkDeleteMismatch(BulkDeleteError):
    """The selection changed since the preview: ``confirm_total`` is not what it selects now."""

    def __init__(self, expected: int, preview: dict) -> None:
        self.expected, self.preview = expected, preview
        super().__init__(
            f"The selection changed since the preview: {expected} previewed, {preview['total']} now. Nothing was deleted; preview again."
        )


# ── The selection ─────────────────────────────────────────────────────────────────────────────────
def check_spec(spec) -> dict:
    """The spec, or BulkDeleteError when it has a key the query does not know or narrows by nothing."""
    if not isinstance(spec, dict):
        raise BulkDeleteError("spec must be an object: an entry query, as POST /entries/query takes")
    unknown = sorted(set(spec) - set(entry_query.SPEC_KEYS))
    if unknown:
        raise BulkDeleteError(f"unknown query key(s): {', '.join(unknown)} (a bulk delete never ignores a condition)")
    if not any(spec.get(k) not in (None, "", [], {}) for k in NARROWING_KEYS):
        raise BulkDeleteError(
            "the query is too wide: name entry types, fields, entries, a collection, tags, a text match or where conditions"
            " (a bulk delete never takes a whole workspace)"
        )
    return spec


def _check_mode(mode: str) -> str:
    if mode not in MODES:
        raise BulkDeleteError(f"mode must be one of: {', '.join(MODES)}")
    return mode


def _matching(session, group_id, spec: dict, mode: str) -> list:
    """(id, entry_type_id, status) of every entry the spec selects, oldest first. Trash mode leaves out what is already in
    the Trash. A spec with ``where`` is read row by row, at most entry_query.SCAN_CAP rows before the conditions."""
    from marvin.db.models.platform.entries import Entries

    q, note = entry_query.build(session, group_id, spec)
    if note:
        raise BulkDeleteError(note)
    if mode == "trash":
        q = q.filter(Entries.status != TRASHED)
    q = q.order_by(Entries.created_at, Entries.id)
    where = [w for w in (spec.get("where") or []) if isinstance(w, dict) and w.get("field")]
    if not where:
        return [tuple(r) for r in q.with_entities(Entries.id, Entries.entry_type_id, Entries.status).all()]
    unknown = sorted({str(w.get("op")) for w in where if (w.get("op") or "eq") not in entry_query.WHERE_OPS})
    if unknown:
        raise BulkDeleteError(f"unknown where op(s): {', '.join(unknown)}. Valid: {', '.join(entry_query.WHERE_OPS)}.")
    rows = q.limit(entry_query.SCAN_CAP + 1).all()
    if len(rows) > entry_query.SCAN_CAP:
        raise BulkDeleteError(f"more than {entry_query.SCAN_CAP} entries to check against `where`: narrow the query with entry types or fields")
    return [(e.id, e.entry_type_id, e.status) for e in rows if all(entry_query.condition_matches(e, w) for w in where)]


def _plural(name: str, n: int) -> str:
    word = (name or "entry").strip().lower()
    if n == 1:
        return word
    if word.endswith("y") and word[-2:-1] not in ("a", "e", "i", "o", "u"):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


def _describe(session, group_id, rows: list) -> dict:
    """What ``rows`` (from _matching) are: the counts a preview shows and the summary event carries."""
    from marvin.db.models.platform.entry_types import EntryTypes

    counts = Counter(r[1] for r in rows)
    names = {t.id: (t.slug, t.name) for t in session.query(EntryTypes.id, EntryTypes.slug, EntryTypes.name).filter(EntryTypes.id.in_(list(counts)))}
    types = sorted(
        ({"entry_type": names.get(tid, ("?", "entry"))[0], "name": names.get(tid, ("?", "entry"))[1], "count": n} for tid, n in counts.items()),
        key=lambda t: (-t["count"], t["entry_type"]),
    )
    said = [f"{t['count']:,} {_plural(t['name'], t['count'])}" for t in types]
    text = ", ".join(said[:-1]) + " and " + said[-1] if len(said) > 1 else "".join(said) or "nothing"
    return {
        "total": len(rows),
        "by_type": {t["entry_type"]: t["count"] for t in types},
        "types": types,
        "text": text,
        "published": sum(1 for r in rows if r[2] == "published"),
        "in_trash": sum(1 for r in rows if r[2] == TRASHED),
    }


def preview(session, group_id, spec, *, mode: str = "trash") -> dict:
    """What ``execute`` would remove now, counted by entry type. Changes nothing. Raises BulkDeleteError for a spec it
    refuses (too wide, an unknown key, a filter that can't match such as an empty field value)."""
    mode = _check_mode(mode)
    return {"mode": mode, **_describe(session, group_id, _matching(session, group_id, check_spec(spec), mode))}


ROLE_AUTHOR, ROLE_EDITOR, ROLE_ADMIN = 2, 3, 4  # WORKSPACE_ROLE_HIERARCHY ranks (services/automation/authz.py)
AUTHOR_LOCKED = ("approved", "published")  # routes/_base/checks.AUTHOR_LOCKED_STATUSES


def refusal(session, group_id, spec, mode: str, *, role: int, user_id=None) -> str | None:
    """Why someone of workspace rank ``role`` may not do this bulk delete, or None. The rules of deleting one entry, for
    all of them: deleting for good is ADMIN/OWNER; moving to the Trash is EDITOR and above for any entry, an AUTHOR only for
    their own entries that are not approved or published, and a published Playbook needs ADMIN."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.playbooks import PLAYBOOK_TYPE

    if mode == "permanent":
        return None if role >= ROLE_ADMIN else "Deleting entries for good in bulk needs the ADMIN or OWNER role."
    if role < ROLE_AUTHOR:
        return "AUTHOR role or higher required."
    if role >= ROLE_ADMIN:
        return None
    ids = [r[0] for r in _matching(session, group_id, check_spec(spec), mode)]
    others = locked = playbooks = 0
    playbook_type = session.query(EntryTypes.id).filter(EntryTypes.group_id == group_id, EntryTypes.slug == PLAYBOOK_TYPE).scalar()
    for start in range(0, len(ids), 1000):
        part = session.query(Entries.created_by, Entries.status, Entries.entry_type_id).filter(Entries.id.in_(ids[start : start + 1000])).all()
        others += sum(1 for r in part if str(r[0]) != str(user_id))
        locked += sum(1 for r in part if r[1] in AUTHOR_LOCKED)
        playbooks += sum(1 for r in part if r[1] == "published" and r[2] == playbook_type)
    if role < ROLE_EDITOR and (others or locked):
        return f"An AUTHOR deletes only their own entries that are not approved or published: {others + locked} of these are not."
    if playbooks:
        return f"Only an ADMIN or above can remove a published Playbook: {playbooks} of these are."
    return None


# ── Doing it ──────────────────────────────────────────────────────────────────────────────────────
def _confirmed(value) -> int:
    try:
        n = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        n = -1
    if n < 0:
        raise BulkDeleteError("confirm_total is required: the total the preview counted (run the preview first)")
    return n


def aside_slug(slug: str, entry_id) -> str:
    """The slug a bulk-trashed entry carries while in the Trash: its own with its id's first 8 characters added (once:
    an entry restored where its slug had been taken, and trashed again, keeps the one it has)."""
    tail = f"{ASIDE}{str(entry_id).replace('-', '')[:8]}"
    return slug if slug.endswith(tail) else f"{slug}{tail}"


def _smart_collections(session, group_id) -> tuple[list, list]:
    """(ids of the entry smart collections a trashed entry leaves, the collections that ask for trashed entries)."""
    from marvin.db.models.platform.collections import Collections

    from .trash import is_trash_collection

    rows = [c for c in session.query(Collections).filter_by(group_id=group_id, is_smart=True).all() if (c.target_type or "entry") == "entry"]
    return [c.id for c in rows if not is_trash_collection(c)], [c for c in rows if is_trash_collection(c)]


def _trash_chunk(session, group_id, ids: list, actor_id, smart: tuple[list, list]) -> list:
    """Move these entries (those still out of the Trash) to the Trash. Returns (id, entry_type_id, status before) of
    each one moved. Does not commit."""
    from sqlalchemy.orm import selectinload

    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.services.collections.smart_collections import matches_rules

    leave, trash_collections = smart
    rows = (
        session.query(Entries)
        .options(selectinload(Entries.entry_type), selectinload(Entries.tags))
        .filter(Entries.group_id == group_id, Entries.id.in_(ids), Entries.status != TRASHED)
        .all()
    )
    when = datetime.now(UTC).isoformat()
    moved = []
    for e in rows:
        moved.append((e.id, e.entry_type_id, e.status))
        meta = {k: v for k, v in (e.metadata_json or {}).items() if k != TRASH_KEY}
        meta[TRASH_KEY] = {
            "previous_status": e.status,
            "trashed_at": when,
            "trashed_by": str(actor_id) if actor_id else None,
            "slug": e.slug,
        }
        e.metadata_json = meta
        e.status = TRASHED
        e.publish_at = None  # as EntryService: a restored entry never goes live on an old schedule
        e.published_at = None  # as the repository does for any status but published
        e.scheduled_publish_blocked = None
        e.slug = aside_slug(e.slug, e.id)
    session.flush()
    moved_ids = [m[0] for m in moved]
    if moved_ids and leave:
        session.query(EntryCollections).filter(EntryCollections.entry_id.in_(moved_ids), EntryCollections.collection_id.in_(leave)).delete(
            synchronize_session=False
        )
    for collection in trash_collections:
        held = {
            r[0]
            for r in session.query(EntryCollections.entry_id).filter(
                EntryCollections.collection_id == collection.id, EntryCollections.entry_id.in_(moved_ids)
            )
        }
        for e in rows:
            if e.id not in held and matches_rules(e, collection.smart_rules, "entry"):
                session.add(EntryCollections(entry_id=e.id, collection_id=collection.id, sort_order=0))
    return moved


def _delete_chunk(session, group_id, ids: list) -> list:
    """Delete these entries for good. Returns (id, entry_type_id, status) of each one deleted. Does not commit."""
    from marvin.db.models.platform.entries import Entries

    rows = [
        tuple(r) for r in session.query(Entries.id, Entries.entry_type_id, Entries.status).filter(Entries.group_id == group_id, Entries.id.in_(ids))
    ]
    if rows:
        session.query(Entries).filter(Entries.group_id == group_id, Entries.id.in_([r[0] for r in rows])).delete(synchronize_session=False)
    return rows


def _forget_embeddings(session, group_id, ids: list) -> None:
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

    session.query(AIEmbeddingModel).filter(
        AIEmbeddingModel.group_id == group_id, AIEmbeddingModel.entity_type == "entry", AIEmbeddingModel.entity_id.in_(ids)
    ).delete(synchronize_session=False)


def execute(
    session,
    group_id,
    spec,
    *,
    mode: str,
    confirm_total,
    actor_id=None,
    description: str | None = None,
    event_bus=None,
    progress=None,
    chunk_size: int = CHUNK_SIZE,
    pause: float = PAUSE_SECONDS,
    integration_id: str = "entry_management",
    reaction_depth: int = 0,
) -> dict:
    """Move what ``spec`` selects to the Trash (``mode`` trash) or delete it for good (permanent), CHUNK_SIZE rows per
    transaction. ``confirm_total`` is the preview's total: when the selection no longer counts that many, nothing is done
    (BulkDeleteMismatch). ``progress(done, total)`` is called after each chunk. Returns what was done: ``mode``,
    ``deleted``, ``by_type``, ``types``, ``text``, ``published``, ``chunks``, ``seconds``. Permissions are the caller's to
    check (the route and the workflow step do)."""
    mode = _check_mode(mode)
    spec = check_spec(spec)
    expected = _confirmed(confirm_total)
    rows = _matching(session, group_id, spec, mode)
    found = {"mode": mode, **_describe(session, group_id, rows)}
    if found["total"] != expected:
        raise BulkDeleteMismatch(expected, found)
    session.commit()  # end the read: each chunk below is a transaction of its own

    ids = [r[0] for r in rows]
    started = time.monotonic()
    smart = _smart_collections(session, group_id) if mode == "trash" else ([], [])
    done: list = []
    chunks, error = 0, None
    try:
        for start in range(0, len(ids), max(1, chunk_size)):
            part = ids[start : start + max(1, chunk_size)]
            went = _trash_chunk(session, group_id, part, actor_id, smart) if mode == "trash" else _delete_chunk(session, group_id, part)
            _forget_embeddings(session, group_id, [r[0] for r in went])
            session.commit()
            done += went
            chunks += 1
            if progress:
                progress(start + len(part), len(ids))
            if pause and start + len(part) < len(ids):
                time.sleep(pause)
    except Exception as e:  # noqa: BLE001 — what was done stays done; the summary says how far it got, then the caller hears
        session.rollback()
        error = e
    result = {
        **_describe(session, group_id, done),
        "mode": mode,
        "deleted": len(done),
        "chunks": chunks,
        "seconds": round(time.monotonic() - started, 2),
        "description": description or None,
    }
    result.pop("total")
    if done:
        _after(
            session,
            group_id,
            result,
            actor_id=actor_id,
            event_bus=event_bus,
            integration_id=integration_id,
            reaction_depth=reaction_depth,
            error=error,
        )
    if error is not None:
        raise BulkDeleteError(f"stopped after {len(done)} of {len(ids)}: {error}") from error
    return result


def _after(session, group_id, result: dict, *, actor_id, event_bus, integration_id: str, reaction_depth: int, error) -> None:
    """The bookkeeping done once: a site rebuild when a published entry went, and the one summary event."""
    if result["published"]:
        try:
            from marvin.services.site_rebuild import auto_rebuild_enabled, rebuild_change, request_rebuild

            if auto_rebuild_enabled(session, group_id):
                label = f"{result['published']} published entr{'y' if result['published'] == 1 else 'ies'} removed in bulk"
                request_rebuild(session, group_id, label, change=rebuild_change(label, "entries_bulk_deleted"))
                session.commit()
        except Exception as e:  # noqa: BLE001 — best-effort, as the listener is
            session.rollback()
            logger.warning(f"bulk delete: could not queue a site rebuild: {e}")
    try:
        _emit(
            session,
            group_id,
            result,
            actor_id=actor_id,
            event_bus=event_bus,
            integration_id=integration_id,
            reaction_depth=reaction_depth,
            error=error,
        )
    except Exception as e:  # noqa: BLE001 — the deletes are done; a lost event is logged
        logger.error(f"bulk delete: could not send entries_bulk_deleted: {e}", exc_info=True)


def _emit(session, group_id, result: dict, *, actor_id, event_bus, integration_id: str, reaction_depth: int, error) -> None:
    from marvin.db.models.groups import Groups
    from marvin.services.event_bus_service.event_types import EventEntriesBulkDeletedData, EventOperation, EventTypes

    if event_bus is None:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)
    group = session.get(Groups, group_id)
    n, how = result["deleted"], ("moved to the Trash" if result["mode"] == "trash" else "deleted for good")
    message = (
        f"{n:,} entr{'y' if n == 1 else 'ies'} {how}"
        + (f" from {result['description']}" if result.get("description") else "")
        + f": {result['text']}"
    )
    if error is not None:
        message += f" (stopped early: {str(error)[:200]})"
    event_bus.dispatch(
        integration_id=integration_id,
        group_id=group_id,
        event_type=EventTypes.entries_bulk_deleted,
        document_data=EventEntriesBulkDeletedData(
            operation=EventOperation.delete,
            workspace_id=group_id,
            workspace_name=getattr(group, "name", None),
            mode=result["mode"],
            total=n,
            by_type=result["by_type"],
            description=result.get("description"),
            complete=error is None,
        ),
        message=message[:1000],
        user_id=actor_id,
        reaction_depth=reaction_depth,
    )


# ── In the background (the REST endpoint) ──────────────────────────────────────────────────────────
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def job_status(group_id) -> dict | None:
    """The workspace's bulk delete in progress, or the last one since the server started; None when there was none."""
    with _lock:
        job = _jobs.get(str(group_id))
        return dict(job) if job else None


def start_job(group_id, spec: dict, *, mode: str, total: int, actor_id=None, description: str | None = None) -> dict | None:
    """Start ``execute`` in a thread of its own (its own session) and return the job as it starts; None when one is
    already running for this workspace. The caller has checked the spec, the permissions and the confirmation."""
    key = str(group_id)
    with _lock:
        if (_jobs.get(key) or {}).get("state") == "running":
            return None
        job = {
            "state": "running",
            "mode": mode,
            "description": description or None,
            "total": total,
            "done": 0,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "error": None,
            "result": None,
        }
        _jobs[key] = job
        snapshot = dict(job)
    threading.Thread(target=_run_job, args=(group_id, spec, mode, total, actor_id, description), name=f"bulk-delete-{key[:8]}", daemon=True).start()
    return snapshot


def _set(key: str, **fields) -> None:
    with _lock:
        if key in _jobs:
            _jobs[key].update(fields)


def _run_job(group_id, spec: dict, mode: str, total: int, actor_id, description) -> None:
    from marvin.db.db_setup import session_context

    key = str(group_id)
    try:
        with session_context() as session:
            result = execute(
                session,
                group_id,
                spec,
                mode=mode,
                confirm_total=total,
                actor_id=actor_id,
                description=description,
                progress=lambda done, all_: _set(key, done=done, total=all_),
            )
        _set(key, state="done", done=total, result=result, finished_at=datetime.now(UTC).isoformat())
        logger.info(f"bulk delete: {result['deleted']} entries ({mode}) in {result['seconds']} s, workspace {group_id}")
    except Exception as e:  # noqa: BLE001 — a background job must never take the worker down
        logger.error(f"bulk delete failed in workspace {group_id}: {e}", exc_info=True)
        _set(key, state="failed", error=str(e), finished_at=datetime.now(UTC).isoformat())
