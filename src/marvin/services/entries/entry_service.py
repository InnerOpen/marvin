"""Entry domain service — mutation + event emission in one place.

Marvin had no service layer for entries: the create/update/publish/archive rules and *which events
each transition emits* lived in the entry controller, and the automation write-back
(`runner._apply_writeback`) re-implemented a thinner copy — mutating the entry and emitting a bare
`entry_updated`, but NOT the status-transition events. So an AI write-back (or any future caller)
that flipped an entry to published silently skipped `entry_published`, and chained automations that
key on publish quietly stopped firing.

This service is the single seam. Every entry write goes through it, and it owns the emit — so status
transitions (`entry_published` / `entry_unpublished` / `entry_archived` / `entry_trashed` / `entry_restored`) fire
*by construction*, from any caller, and chaining becomes reliable. It's also the natural home for
`changed_fields` / `before` / `after` (added next).

The event shape is preserved exactly from the controller (same integration_id, document data,
messages, and — importantly — the `entry_updated`-before-`entry_published` ordering the embedding
reaction depends on). `reaction_depth` is threaded so an automation's write-back re-emits at
`depth + 1`, keeping the loop-guard intact.
"""

from fastapi import HTTPException

from marvin.core.root_logger import get_logger
from marvin.repos.repository_factory import AllRepositories
from marvin.services.event_bus_service.event_types import (
    Event,
    EventBusMessage,
    EventEntryCollectionData,
    EventEntryData,
    EventOperation,
    EventScheduledPublishBlockedData,
    EventTypes,
)

logger = get_logger("entry_service")

# Scalar entry fields we diff for `changed_fields`/`before`/`after` on update events. Deliberately
# small and scalar — never body/content/metadata (large, and by-value content shouldn't land in the
# audit log) or relationships. These are exactly the fields automation conditions key on.
_TRACKED_FIELDS = ("status", "title", "slug")

# The status-transition events: each one is a change of `status`, so its diff always names it.
_TRANSITION_EVENTS = (
    EventTypes.entry_published,
    EventTypes.entry_unpublished,
    EventTypes.entry_archived,
    EventTypes.entry_restored,
    EventTypes.entry_trashed,
)

TRASHED = "trashed"
# Where a trashed entry came from, kept in its metadata_json while it is in the Trash:
# {previous_status, trashed_at (ISO, UTC), trashed_by (user id or null)}. Written on the way in, removed on
# the way out, by whatever path changes the status (EntryService.update), so it can't go stale.
TRASH_KEY = "trash"
# Statuses a restore must not return an entry to: restoring never re-publishes by itself (nor does it
# re-approve an entry that may be scheduled), and "processing" belongs to a run that is long gone.
_RESTORE_AS_DRAFT = frozenset({"published", "processing", TRASHED})


def _is_uuid(value: str) -> bool:
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _diff(old, new) -> tuple[list[str], dict, dict]:
    """(changed_fields, before, after) over the tracked scalar fields. before/after carry ONLY the
    changed fields, so `event.after.status == X` reads as "status changed to X"."""
    changed = [f for f in _TRACKED_FIELDS if getattr(old, f, None) != getattr(new, f, None)]
    before = {f: getattr(old, f, None) for f in changed}
    after = {f: getattr(new, f, None) for f in changed}
    return changed, before, after


def count_by_status(session, group_id) -> dict[str, int]:
    """`{status: n}` for every known status (zero-filled) plus `total` — the sidebar's inbox badge.
    `trashed` is counted on its own and left out of `total`: the Trash is out of sight.

    One grouped query on the (group_id, status) index; cheap enough to run on every page load.
    """
    from sqlalchemy import func

    from marvin.db.models.platform import Entries
    from marvin.schemas.platform.entries import ENTRY_STATUSES

    rows = session.query(Entries.status, func.count(Entries.id)).filter(Entries.group_id == group_id).group_by(Entries.status).all()
    counts = dict.fromkeys(sorted(ENTRY_STATUSES), 0)
    for status_value, n in rows:
        counts[status_value] = int(n)
    counts["total"] = sum(n for k, n in counts.items() if k not in ("total", TRASHED))
    return counts


def restore_status(entry) -> str:
    """The status a trashed entry goes back to: the one it had before (metadata_json.trash), except that
    a published entry comes back as a draft — restoring must never put an entry on the site by itself."""
    record = (getattr(entry, "metadata_json", None) or {}).get(TRASH_KEY) or {}
    previous = record.get("previous_status") if isinstance(record, dict) else None
    from marvin.schemas.platform.entries import ENTRY_STATUSES

    if previous not in ENTRY_STATUSES or previous in _RESTORE_AS_DRAFT:
        return "draft"
    return previous


class EntryService:
    """Own entry mutations and the events they emit. Construct per request/run with the actor + bus.

    Args:
        session:   an active SQLAlchemy session.
        group_id:  the workspace scope.
        event_bus: the EventBusService to dispatch through (the controller passes its request-scoped
                   one so events publish in the background; automation write-back passes a synchronous
                   one). Created synchronous if omitted.
        actor_id:  the user performing the action (goes on the event's `user_id`).
        integration_id: source tag on emitted events ("entry_management" for user actions,
                   "automation" for write-back).
    """

    def __init__(self, session, group_id, *, event_bus=None, actor_id=None, integration_id: str = "entry_management") -> None:
        self.session = session
        self.group_id = group_id
        self.actor_id = actor_id
        self.integration_id = integration_id
        self._event_bus = event_bus
        self.repos = AllRepositories(session, group_id=group_id)

    @property
    def event_bus(self):
        if self._event_bus is None:
            from marvin.services.event_bus_service.event_bus_service import EventBusService

            self._event_bus = EventBusService(bg_tasks=None)  # synchronous fan-out
        return self._event_bus

    # ── Writes ────────────────────────────────────────────────────────────────
    def create(self, data_dict: dict):
        """Create an entry and emit `entry_created`. `data_dict` should already carry created_by."""
        entry = self.repos.entries.create(data_dict)
        names = self._names(entry)
        self._emit(entry, EventTypes.entry_created, EventOperation.create, f"Entry '{entry.title}' created", names)
        return entry

    def update(self, entry_id, data, *, reaction_depth: int = 0):
        """Update an entry, emit `entry_updated`, then any status-transition events. Returns the
        updated entry, or None if it doesn't exist. A publish transition is gated on the type's
        completeness contract — required fields/assets/resources/tags must be satisfied first."""
        old = self.repos.entries.get_one(entry_id)
        if not old:
            return None
        self._gate_publish(entry_id, old, data)
        data = self._trash_bookkeeping(old, data)
        entry = self.repos.entries.update(entry_id, data)
        self._emit_updated_and_transitions(old, entry, "updated", reaction_depth)
        return entry

    def _trash_bookkeeping(self, old, data):
        """Record where an entry came from as it enters the Trash (metadata_json.trash), and drop that
        record as it leaves. Entering also clears a scheduled publish, so the Publish Scheduled Entries
        task can't put a trashed (or later restored) entry live. Returns `data` unchanged otherwise."""
        from datetime import UTC, datetime

        pending = data if isinstance(data, dict) else data.model_dump(exclude_unset=True)
        new_status = pending.get("status")
        old_status = getattr(old, "status", None)
        if new_status is None or new_status == old_status or TRASHED not in (new_status, old_status):
            return data

        pending = dict(pending)
        base = pending.get("metadata_json")
        meta = {k: v for k, v in (base if base is not None else (getattr(old, "metadata_json", None) or {})).items() if k != TRASH_KEY}
        if new_status == TRASHED:
            meta[TRASH_KEY] = {
                "previous_status": old_status,
                "trashed_at": datetime.now(UTC).isoformat(),
                "trashed_by": str(self.actor_id) if self.actor_id else None,
            }
            pending["publish_at"] = None
        pending["metadata_json"] = meta
        return pending

    def _gate_publish(self, entry_id, old, data) -> None:
        """Block an inbox/draft → published transition when the entry doesn't satisfy its type's
        completeness contract, or its expiration date has already passed. Evaluates the *projected*
        state (pending field changes overlaid on the persisted entry). Fail-open on any internal
        error — never block on our own bug — but a genuine unmet requirement raises HTTP 422 with
        the specific gaps."""
        from marvin.services.entries import completeness as C

        def _get(attr):
            return data.get(attr) if isinstance(data, dict) else getattr(data, attr, None)

        def _projected(attr):
            pending = data if isinstance(data, dict) else getattr(data, "model_fields_set", set())
            return _get(attr) if attr in pending else getattr(old, attr, None)

        if _get("status") != "published" or getattr(old, "status", None) == "published":
            return

        report = None
        try:
            from marvin.db.models.platform.entries import Entries
            from marvin.db.models.platform.entry_types import EntryTypes

            orm = self.session.get(Entries, entry_id)
            entry_type = self.session.get(EntryTypes, orm.entry_type_id) if orm is not None and orm.entry_type_id else None
            if entry_type is not None:
                report = C.evaluate_entry(
                    orm,
                    entry_type,
                    data_json=_get("data_json"),  # None → uses the entry's stored data_json
                    title=_get("title"),
                    summary=_get("summary"),
                    description=_get("description"),
                )
        except Exception as e:  # noqa: BLE001 — a gate bug must not break publishing
            logger.warning("Publish completeness gate skipped for %s: %s", entry_id, e)

        issues = report.blocking_messages() if report is not None else []
        expired = C.expiry_issue(_projected("expire_at"))
        if expired is not None:
            issues.append(expired.message)
        if issues:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Cannot publish — {len(issues)} requirement(s) unmet.",
                    "issues": issues,
                },
            )

    def apply_fields(self, entry_id, fields: dict, *, reaction_depth: int = 0):
        """Apply a dict of fields to an entry (the automation write-back path) — same mutation the AI
        write-back used, but now emitting `entry_updated` AND status transitions, so a write-back that
        changes status fires the right events and chains reliably. Returns the entry or None."""
        old = self.repos.entries.get_one(entry_id)
        if not old:
            return None
        self.repos.entries.apply_fields(entry_id, fields)
        entry = self.repos.entries.get_one(entry_id)
        self._emit_updated_and_transitions(old, entry, "updated by automation write-back", reaction_depth)
        return entry

    def apply_suggestion(self, entry_id):
        """Commit an entry's staged AI suggestion (suggestion_json) and emit `entry_updated`."""
        entry = self.repos.entries.apply_suggestion(entry_id)
        names = self._names(entry)
        self._emit(entry, EventTypes.entry_updated, EventOperation.update, f"AI suggestion applied to '{entry.title}'", names)
        return entry

    def approve_suggested_asset(self, entry_id, asset_id):
        """Approve a pending AI-suggested asset: clear the ``suggested`` flag on the entry↔asset
        junction (keeping the link, so the asset becomes a normal confirmed one) and emit
        `entry_updated`. Returns the updated EntryRead, or None if no such suggested link exists."""
        junction = self.repos.entries.get_suggested_asset_link(entry_id, asset_id)
        if junction is None:
            return None
        meta = {k: v for k, v in (junction.metadata_json or {}).items() if k != "suggested"}
        junction.metadata_json = meta or None
        self.session.commit()
        entry = self.repos.entries.get_one(entry_id)
        self._emit(entry, EventTypes.entry_updated, EventOperation.update, f"Suggested asset approved on '{entry.title}'", self._names(entry))
        return entry

    def reject_suggested_asset(self, entry_id, asset_id):
        """Reject a pending AI-suggested asset: unlink the entry↔asset junction and — if the asset
        is now orphaned (no remaining entry links) — delete it from storage + DB. Emits
        `entry_updated`. Returns the updated EntryRead, or None if no such suggested link exists."""
        from marvin.db.models.platform.entry_assets import EntryAssets

        junction = self.repos.entries.get_suggested_asset_link(entry_id, asset_id)
        if junction is None:
            return None
        self.session.delete(junction)
        self.session.commit()

        # Orphan cleanup: a suggested asset that no other entry links to is discarded outright.
        remaining = self.session.query(EntryAssets).filter(EntryAssets.asset_id == asset_id).count()
        if remaining == 0:
            from marvin.services import trash

            # The one asset delete: file, old-key copies, row, then asset_deleted.
            trash.delete_asset(self.session, self.group_id, asset_id, actor_id=self.actor_id, event_bus=self.event_bus)

        entry = self.repos.entries.get_one(entry_id)
        self._emit(entry, EventTypes.entry_updated, EventOperation.update, f"Suggested asset rejected on '{entry.title}'", self._names(entry))
        return entry

    def emit_scheduled_publish_blocked(self, entry, block: dict) -> None:
        """Emit `entry_scheduled_publish_blocked` for an entry the Publish Scheduled Entries task is
        holding back; `block` is its record (services/entries/scheduled_block.py). Best-effort, like
        every entry event."""
        why = "for approval" if block["waiting_for"] == "approval" else f"— can't publish: {block['reason']}"
        data = self._event_data(
            entry,
            EventOperation.info,
            self._names(entry),
            data_cls=EventScheduledPublishBlockedData,
            waiting_for=block["waiting_for"],
            reason=block["reason"],
            issues=block["issues"],
            publish_at=entry.publish_at,
        )
        try:
            self.event_bus.dispatch(
                integration_id=self.integration_id,
                group_id=self.group_id,
                event_type=EventTypes.entry_scheduled_publish_blocked,
                document_data=data,
                message=f"Scheduled publish of '{entry.title}' is waiting {why}",
                user_id=self.actor_id,
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:  # noqa: BLE001 — event dispatch is best-effort
            logger.error(f"Failed to dispatch entry_scheduled_publish_blocked event: {e}", exc_info=True)

    def delete(self, entry_id) -> bool:
        """Emit `entry_deleted` (before the row is gone) then delete. Returns False if not found."""
        entry = self.repos.entries.get_one(entry_id)
        if not entry:
            return False
        names = self._names(entry)
        self._emit(entry, EventTypes.entry_deleted, EventOperation.delete, f"Entry '{entry.title}' deleted", names)
        self.repos.entries.delete(entry_id)
        return True

    def set_status(self, entry_id, new_status: str, *, reaction_depth: int = 0):
        """Convenience for the entry status actions (publish/unpublish/archive/trash/restore) — an update
        that only changes status, emitting `entry_updated` + the transition event."""
        from marvin.schemas.platform import EntryUpdate

        return self.update(entry_id, EntryUpdate(status=new_status), reaction_depth=reaction_depth)

    # ── Trash ─────────────────────────────────────────────────────────────────
    def trash(self, entry_id, *, reaction_depth: int = 0):
        """Move an entry to the Trash: `entry_updated` + `entry_trashed` (and `entry_unpublished` when it
        was live). Already trashed → returned as is, nothing emitted. None if it doesn't exist."""
        entry = self.repos.entries.get_one(entry_id)
        if entry is None or entry.status == TRASHED:
            return entry
        return self.set_status(entry_id, TRASHED, reaction_depth=reaction_depth)

    def restore_from_trash(self, entry_id, *, reaction_depth: int = 0):
        """Take an entry out of the Trash, back to the status it had (`restore_status`): `entry_updated` +
        `entry_restored`. Not trashed → returned as is. None if it doesn't exist."""
        entry = self.repos.entries.get_one(entry_id)
        if entry is None or entry.status != TRASHED:
            return entry
        return self.set_status(entry_id, restore_status(entry), reaction_depth=reaction_depth)

    # ── Collection membership ──────────────────────────────────────────────────
    def _resolve_collection(self, collection_ref):
        """Resolve a collection within this workspace by id, slug, or name (same vocabulary the
        target selector uses). Returns the Collections row or None."""
        import uuid as _uuid

        from marvin.db.models.platform.collections import Collections

        ref = collection_ref
        if isinstance(ref, _uuid.UUID) or (isinstance(ref, str) and _is_uuid(ref)):
            coll = self.session.get(Collections, ref if isinstance(ref, _uuid.UUID) else _uuid.UUID(str(ref)))
            return coll if coll and coll.group_id == self.group_id else None
        return (
            self.session.query(Collections)
            .filter(Collections.group_id == self.group_id)
            .filter((Collections.slug == str(ref)) | (Collections.name == str(ref)))
            .first()
        )

    def add_to_collection(self, entry_id, collection_ref, *, reaction_depth: int = 0) -> str | None:
        """Add an entry to a collection (idempotent). Returns ``"added"`` (newly added, emits
        `entry_added_to_collection`), ``"exists"`` (already a member — no-op, no event), or ``None``
        (entry or collection not found in this workspace)."""
        import sqlalchemy as sa

        from marvin.db.models.platform.entry_collections import EntryCollections

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        collection = self._resolve_collection(collection_ref)
        if not collection:
            return None

        existing = (
            self.session.query(EntryCollections)
            .filter(EntryCollections.entry_id == entry.id, EntryCollections.collection_id == collection.id)
            .first()
        )
        if existing:
            return "exists"

        max_sort = self.session.query(sa.func.max(EntryCollections.sort_order)).filter(EntryCollections.collection_id == collection.id).scalar()
        self.session.add(EntryCollections(entry_id=entry.id, collection_id=collection.id, sort_order=(max_sort or -1) + 1))
        self.session.commit()
        self._emit(
            entry,
            EventTypes.entry_added_to_collection,
            EventOperation.update,
            f"Entry '{entry.title}' added to collection '{collection.name}'",
            self._names(entry),
            reaction_depth=reaction_depth,
            data_cls=EventEntryCollectionData,
            collection_id=collection.id,
            collection_name=collection.name,
        )
        return "added"

    def remove_from_collection(self, entry_id, collection_ref, *, reaction_depth: int = 0) -> str | None:
        """Remove an entry from a collection (idempotent). Returns ``"removed"`` (emits
        `entry_removed_from_collection`), ``"absent"`` (wasn't a member — no-op, no event), or ``None``
        (entry or collection not found in this workspace)."""
        from marvin.db.models.platform.entry_collections import EntryCollections

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        collection = self._resolve_collection(collection_ref)
        if not collection:
            return None

        deleted = (
            self.session.query(EntryCollections)
            .filter(EntryCollections.entry_id == entry.id, EntryCollections.collection_id == collection.id)
            .delete()
        )
        if not deleted:
            return "absent"
        self.session.commit()
        self._emit(
            entry,
            EventTypes.entry_removed_from_collection,
            EventOperation.update,
            f"Entry '{entry.title}' removed from collection '{collection.name}'",
            self._names(entry),
            reaction_depth=reaction_depth,
            data_cls=EventEntryCollectionData,
            collection_id=collection.id,
            collection_name=collection.name,
        )
        return "removed"

    # ── Resource attachments ───────────────────────────────────────────────────
    def _resolve_resource(self, resource_ref):
        """Resolve a resource within this workspace by id, slug, or name. Returns the row or None."""
        import uuid as _uuid

        from marvin.db.models.platform.resources import Resources

        ref = resource_ref
        if isinstance(ref, _uuid.UUID) or (isinstance(ref, str) and _is_uuid(ref)):
            res = self.session.get(Resources, ref if isinstance(ref, _uuid.UUID) else _uuid.UUID(str(ref)))
            return res if res and res.group_id == self.group_id else None
        return (
            self.session.query(Resources)
            .filter(Resources.group_id == self.group_id)
            .filter((Resources.slug == str(ref)) | (Resources.name == str(ref)))
            .first()
        )

    def attach_resource(self, entry_id, resource_ref, *, role: str | None = None, reaction_depth: int = 0) -> str | None:
        """Attach a reusable resource to an entry (idempotent). Returns ``"attached"`` (newly linked,
        emits `entry_resource_attached`), ``"exists"`` (already linked — no-op, no event), or ``None``
        (entry or resource not found in this workspace, or the resource is in the Trash)."""
        import sqlalchemy as sa

        from marvin.db.models.platform.entry_resources import EntryResources

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        resource = self._resolve_resource(resource_ref)
        if not resource or resource.trashed_at is not None:  # one in the Trash can't be attached
            return None

        existing = self.session.query(EntryResources).filter(EntryResources.entry_id == entry.id, EntryResources.resource_id == resource.id).first()
        if existing:
            return "exists"

        max_pos = self.session.query(sa.func.max(EntryResources.position)).filter(EntryResources.entry_id == entry.id).scalar()
        self.session.add(EntryResources(entry_id=entry.id, resource_id=resource.id, role=role, position=(max_pos + 1) if max_pos is not None else 0))
        self.session.commit()
        self._emit(
            entry,
            EventTypes.entry_resource_attached,
            EventOperation.update,
            f"Resource '{resource.name}' attached to entry '{entry.title}'",
            self._names(entry),
            reaction_depth=reaction_depth,
        )
        return "attached"

    def detach_resource(self, entry_id, resource_ref, *, reaction_depth: int = 0) -> str | None:
        """Detach a resource from an entry (idempotent). Returns ``"detached"`` (emits
        `entry_resource_detached`), ``"absent"`` (wasn't linked — no-op, no event), or ``None``
        (entry or resource not found in this workspace)."""
        from marvin.db.models.platform.entry_resources import EntryResources

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        resource = self._resolve_resource(resource_ref)
        if not resource:
            return None

        deleted = self.session.query(EntryResources).filter(EntryResources.entry_id == entry.id, EntryResources.resource_id == resource.id).delete()
        if not deleted:
            return "absent"
        self.session.commit()
        self._emit(
            entry,
            EventTypes.entry_resource_detached,
            EventOperation.update,
            f"Resource '{resource.name}' detached from entry '{entry.title}'",
            self._names(entry),
            reaction_depth=reaction_depth,
        )
        return "detached"

    # ── Tag attachments (entry-scoped convenience over the shared tagging service) ──────
    def attach_tag(self, entry_id, tag_ref, *, reaction_depth: int = 0) -> str | None:
        """Attach a tag to an entry (idempotent, find-or-creates the tag). Delegates to the shared
        tagging service (which also tags assets/resources). Returns attached/exists/None; emits
        `entry_tag_attached`."""
        from marvin.services.tagging import link_tag

        return link_tag(
            self.session,
            self.group_id,
            "entry",
            entry_id,
            tag_ref,
            attach=True,
            actor_id=self.actor_id,
            event_bus=self._event_bus,
            reaction_depth=reaction_depth,
        )

    def detach_tag(self, entry_id, tag_ref, *, reaction_depth: int = 0) -> str | None:
        """Detach a tag from an entry (idempotent). Returns detached/absent/None; emits
        `entry_tag_detached`."""
        from marvin.services.tagging import link_tag

        return link_tag(
            self.session,
            self.group_id,
            "entry",
            entry_id,
            tag_ref,
            attach=False,
            actor_id=self.actor_id,
            event_bus=self._event_bus,
            reaction_depth=reaction_depth,
        )

    # ── Asset attachments ──────────────────────────────────────────────────────
    def _resolve_asset(self, asset_ref):
        """Resolve an asset within this workspace by id or slug. Returns the row or None."""
        import uuid as _uuid

        from marvin.db.models.platform.assets import Assets

        ref = asset_ref
        if isinstance(ref, _uuid.UUID) or (isinstance(ref, str) and _is_uuid(ref)):
            a = self.session.get(Assets, ref if isinstance(ref, _uuid.UUID) else _uuid.UUID(str(ref)))
            return a if a and a.group_id == self.group_id else None
        return self.session.query(Assets).filter(Assets.group_id == self.group_id, Assets.slug == str(ref)).first()

    def attach_asset(self, entry_id, asset_ref, *, role: str | None = None, reaction_depth: int = 0) -> str | None:
        """Attach an asset to an entry (idempotent). Returns ``"attached"`` (emits
        `asset_attached_to_entry`), ``"exists"`` (already linked), or ``None`` (entry or asset not
        found in this workspace, or the asset is in the Trash)."""
        import sqlalchemy as sa

        from marvin.db.models.platform.entry_assets import EntryAssets
        from marvin.services.assets.scope import is_ask_file, move_to_library

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        asset = self._resolve_asset(asset_ref)
        if not asset or asset.trashed_at is not None:  # one in the Trash can't be attached
            return None
        if is_ask_file(asset):  # an entry shows only library assets: attaching files a chat attachment there
            move_to_library(self.session, self.group_id, [asset.id], actor_id=self.actor_id, event_bus=self.event_bus)
        existing = self.session.query(EntryAssets).filter(EntryAssets.entry_id == entry.id, EntryAssets.asset_id == asset.id).first()
        if existing:
            return "exists"
        max_pos = self.session.query(sa.func.max(EntryAssets.position)).filter(EntryAssets.entry_id == entry.id).scalar()
        self.session.add(EntryAssets(entry_id=entry.id, asset_id=asset.id, role=role, position=(max_pos + 1) if max_pos is not None else 0))
        self.session.commit()
        self._emit_asset_link(
            entry, asset, EventTypes.asset_attached_to_entry, f"Asset '{asset.name}' attached to entry '{entry.title}'", reaction_depth
        )
        return "attached"

    def detach_asset(self, entry_id, asset_ref, *, reaction_depth: int = 0) -> str | None:
        """Detach an asset from an entry (idempotent). Returns ``"detached"`` (emits
        `asset_detached_from_entry`), ``"absent"`` (wasn't linked), or ``None`` (not found)."""
        from marvin.db.models.platform.entry_assets import EntryAssets

        entry = self.repos.entries.get_one(entry_id)
        if not entry or entry.group_id != self.group_id:
            return None
        asset = self._resolve_asset(asset_ref)
        if not asset:
            return None
        deleted = self.session.query(EntryAssets).filter(EntryAssets.entry_id == entry.id, EntryAssets.asset_id == asset.id).delete()
        if not deleted:
            return "absent"
        self.session.commit()
        self._emit_asset_link(
            entry, asset, EventTypes.asset_detached_from_entry, f"Asset '{asset.name}' detached from entry '{entry.title}'", reaction_depth
        )
        return "detached"

    def _emit_asset_link(self, entry, asset, event_type, message: str, reaction_depth: int) -> None:
        """Dispatch an asset↔entry link event (EventAssetData, keyed to the entry so automations can
        react on $event.entry_id). Best-effort — never breaks the write."""
        from marvin.services.event_bus_service.event_types import EventAssetData

        _, workspace_name, _ = self._names(entry)
        try:
            self.event_bus.dispatch(
                integration_id=self.integration_id,
                group_id=self.group_id,
                event_type=event_type,
                document_data=EventAssetData(
                    operation=EventOperation.update,
                    asset_id=asset.id,
                    slug=asset.slug,
                    name=asset.name,
                    mime_type=asset.mime_type,
                    asset_type=asset.asset_type,
                    storage_key=asset.storage_key,
                    workspace_id=self.group_id,
                    workspace_name=workspace_name,
                    uploader_id=self.actor_id,
                ),
                message=message,
                user_id=self.actor_id,
                entity_id=entry.id,
                entity_type="entry",
                reaction_depth=reaction_depth,
            )
        except Exception as e:  # noqa: BLE001 — event dispatch is best-effort
            logger.error(f"Failed to dispatch {getattr(event_type, 'name', event_type)} event: {e}", exc_info=True)

    # ── Emission ──────────────────────────────────────────────────────────────
    def _emit_updated_and_transitions(self, old, entry, verb: str, reaction_depth: int) -> None:
        """Emit `entry_updated` first, then any status-transition events (published/unpublished/
        archived/trashed/restored). Each carries the scalar diff (changed_fields/before/after). The
        updated-then-published ordering is relied on by the embedding reaction — keep it.

        Wrapped in one correlation scope so `entry_updated` and its transition event share a chain id
        (inheriting the ambient id when this runs inside an automation, minting one from the controller).
        """
        from marvin.services.event_bus_service.correlation import correlation_scope

        names = self._names(entry)
        diff = _diff(old, entry)
        old_status = getattr(old, "status", None)
        with correlation_scope():
            self._emit(
                entry,
                EventTypes.entry_updated,
                EventOperation.update,
                f"Entry '{entry.title}' {verb}",
                names,
                reaction_depth=reaction_depth,
                diff=diff,
            )
            if old_status == entry.status:
                return
            if entry.status == "published":
                self._emit(
                    entry,
                    EventTypes.entry_published,
                    EventOperation.update,
                    f"Entry '{entry.title}' published",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )
            elif old_status == "published":
                self._emit(
                    entry,
                    EventTypes.entry_unpublished,
                    EventOperation.update,
                    f"Entry '{entry.title}' unpublished",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )
            # Leaving the Trash is a restore whatever the status it returns to (even Archived).
            if old_status == TRASHED:
                self._emit(
                    entry,
                    EventTypes.entry_restored,
                    EventOperation.update,
                    f"Entry '{entry.title}' restored from the Trash",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )
            elif entry.status == "archived":
                self._emit(
                    entry,
                    EventTypes.entry_archived,
                    EventOperation.update,
                    f"Entry '{entry.title}' archived",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )
            elif entry.status == TRASHED:
                self._emit(
                    entry,
                    EventTypes.entry_trashed,
                    EventOperation.update,
                    f"Entry '{entry.title}' moved to the Trash",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )
            elif old_status == "archived":
                self._emit(
                    entry,
                    EventTypes.entry_restored,
                    EventOperation.update,
                    f"Entry '{entry.title}' restored from archive",
                    names,
                    reaction_depth=reaction_depth,
                    diff=diff,
                )

    def _names(self, entry) -> tuple[str | None, str | None, str | None]:
        """(entry_type_slug, workspace_name, author_name) for the event payload."""
        entry_type_slug = None
        if getattr(entry, "entry_type_id", None):
            etype = self.repos.entry_types.get_one(entry.entry_type_id)
            if etype:
                entry_type_slug = etype.slug

        group = self.repos.groups.get_one(self.group_id)
        workspace_name = group.name if group else None

        author_name = None
        if getattr(entry, "created_by", None):
            author = self.repos.users.get_one(entry.created_by)
            if author:
                author_name = author.full_name
        return entry_type_slug, workspace_name, author_name

    def _emit(
        self,
        entry,
        event_type,
        operation,
        message: str,
        names: tuple[str | None, str | None, str | None],
        *,
        reaction_depth: int = 0,
        diff: tuple[list[str], dict, dict] | None = None,
        data_cls=EventEntryData,
        **extra,
    ) -> None:
        """Dispatch one entry event. Best-effort — a dispatch failure never breaks the write."""
        try:
            self.event_bus.dispatch(
                integration_id=self.integration_id,
                group_id=self.group_id,
                event_type=event_type,
                document_data=self._event_data(entry, operation, names, diff, data_cls=data_cls, **extra),
                message=message,
                user_id=self.actor_id,
                entity_id=entry.id,
                entity_type="entry",
                reaction_depth=reaction_depth,
            )
        except Exception as e:  # noqa: BLE001 — event dispatch is best-effort
            logger.error(f"Failed to dispatch {getattr(event_type, 'name', event_type)} event: {e}", exc_info=True)

    @staticmethod
    def _event_data(entry, operation, names, diff=None, *, data_cls=EventEntryData, **extra) -> EventEntryData:
        entry_type_slug, workspace_name, author_name = names
        changed_fields, before, after = diff or ([], {}, {})
        return data_cls(
            operation=operation,
            entry_id=entry.id,
            entry_title=entry.title,
            entry_type=entry_type_slug,
            workspace_id=entry.group_id,
            workspace_name=workspace_name,
            author_id=getattr(entry, "created_by", None),
            author_name=author_name,
            changed_fields=changed_fields,
            before=before,
            after=after,
            **extra,
        )

    def sample_event(self, entry, event_type) -> Event:
        """The event this service emits for `entry` on an entry lifecycle `event_type`, built but not
        dispatched — what a workflow dry run tests against when the event log holds none.

        A status transition carries the status it moved to (`after.status`), as every real one does;
        what it moved from isn't known, so `before` stays empty.
        """
        operation = EventOperation.create if event_type == EventTypes.entry_created else EventOperation.update
        diff = (["status"], {}, {"status": entry.status}) if event_type in _TRANSITION_EVENTS else None
        return Event(
            message=EventBusMessage.from_type(event_type),
            event_type=event_type,
            integration_id=self.integration_id,
            document_data=self._event_data(entry, operation, self._names(entry), diff),
            workspace_id=self.group_id,
            user_id=self.actor_id,
            entity_id=entry.id,
            entity_type="entry",
        )
