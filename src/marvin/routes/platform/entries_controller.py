"""Entry routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.platform import EntryCollections, EntryTypes
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import editable_entry, require_can_create_entry, require_can_edit_entry, require_workspace_admin
from marvin.schemas.platform import CollectionRead, EntryCreate, EntryRead, EntryUpdate
from marvin.services.entries import EntryService, trash
from marvin.services.entries.entry_service import TRASHED, count_by_status, restore_status
from marvin.services.entry_urls import entry_url, site_base_url

router = APIRouter(prefix="/entries")


@controller(router)
class EntriesController(BaseUserController):
    """Authenticated CRUD routes for entries. Entry mutation + its events live in EntryService;
    this controller owns the HTTP concerns (auth, 404s, response shape).

    Any member reads. Writes follow the content roles: EDITORs and above change any entry; an AUTHOR
    creates entries and changes their own until they are approved or published (see
    `require_can_edit_entry`); a VIEWER gets a 403.

    Delete moves an entry to the Trash (reversible); only a trashed entry can be deleted forever, and
    only an ADMIN/OWNER empties the whole Trash (services/entries/trash.py). Trashed entries are left
    out of the list; fetching one by id still works and shows its status."""

    def _entries(self) -> EntryService:
        """The entry domain service, wired with this request's actor + event bus."""
        return EntryService(
            self.session,
            self.group_id,
            event_bus=self.event_bus,
            actor_id=self.user.id if self.user else None,
        )

    @router.get("", response_model=list[EntryRead], summary="List Entries")
    def list_entries(self) -> list[EntryRead]:
        """Every entry but those in the Trash (the Trash collection lists those)."""
        return [e for e in self.repos.entries.get_all(order_by="created_at") if e.status != TRASHED]

    @router.post("", response_model=EntryRead, status_code=status.HTTP_201_CREATED, summary="Create Entry")
    def create_entry(self, data: EntryCreate) -> EntryRead:
        require_can_create_entry(self.user, self.group_id, data.status, data.publish_at)
        data_dict = data.model_dump()
        data_dict["created_by"] = self.user.id  # inject the authenticated author
        return self._entries().create(data_dict)

    @router.get("/counts", summary="Entry counts by status")
    def entry_counts(self) -> dict[str, int]:
        """`{inbox, draft, …, total}` for this workspace — what the sidebar badge reads. Declared before `/{item_id}`."""
        return count_by_status(self.session, self.group_id)

    @router.get("/trash", summary="Trash summary")
    def trash_summary(self) -> dict:
        """How many entries are in the Trash and how long it keeps them (`effective_days`, 0 = until
        emptied; the platform default and this workspace's override beside it). Declared before `/{item_id}`."""
        return {"count": len(trash.trashed_ids(self.session, self.group_id)), **trash.auto_empty_status(self.session, self.group_id)}

    @router.post("/trash/empty", summary="Empty the Trash")
    def empty_trash(self) -> dict:
        """Delete every entry in the Trash forever (ADMIN/OWNER). Each goes through the normal delete, so
        `entry_deleted` fires per entry. Returns `{deleted: n}`."""
        require_workspace_admin(self.user, self.group_id)
        deleted = trash.empty_trash(self.session, self.group_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "deleted": deleted}

    @router.get("/{item_id}", response_model=EntryRead, summary="Get Entry")
    def get_entry(self, item_id: UUID4) -> EntryRead:
        entry = self.repos.entries.get_one(item_id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        entry.page_url = entry_url(
            entry,
            absolute=True,
            site_url=site_base_url(self.session, self.group_id),
            entry_type=self.session.get(EntryTypes, entry.entry_type_id),
        )
        return entry

    @router.post("/{item_id}/apply-suggestion", response_model=EntryRead, summary="Apply AI Suggestion")
    def apply_suggestion(self, item_id: UUID4) -> EntryRead:
        """Apply the entry's staged AI suggestion (suggestion_json) and clear it.

        This is the human-approval half of write-back: an AI op stages proposed changes under
        suggestion_json (when approval_mode doesn't auto-apply); this endpoint commits them.
        """
        editable_entry(self.user, self.group_id, self.repos, item_id)
        return self._entries().apply_suggestion(item_id)

    @router.post("/{item_id}/reject-suggestion", response_model=EntryRead, summary="Reject AI Suggestion")
    def reject_suggestion(self, item_id: UUID4) -> EntryRead:
        """Discard the entry's staged AI suggestion without applying it."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        return self.repos.entries.clear_suggestion(item_id)

    @router.post("/{item_id}/suggested-assets/{asset_id}/approve", response_model=EntryRead, summary="Approve Suggested Asset")
    def approve_suggested_asset(self, item_id: UUID4, asset_id: UUID4) -> EntryRead:
        """Approve a pending AI-generated asset: clear the `suggested` flag on the entry↔asset link
        so it becomes a normal confirmed asset (and reaches published output)."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        entry = self._entries().approve_suggested_asset(item_id, asset_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No suggested asset found for this entry.")
        return entry

    @router.post("/{item_id}/suggested-assets/{asset_id}/reject", response_model=EntryRead, summary="Reject Suggested Asset")
    def reject_suggested_asset(self, item_id: UUID4, asset_id: UUID4) -> EntryRead:
        """Reject a pending AI-generated asset: unlink it, and delete the asset if it's now orphaned."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        entry = self._entries().reject_suggested_asset(item_id, asset_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No suggested asset found for this entry.")
        return entry

    @router.patch("/{item_id}", response_model=EntryRead, summary="Update Entry")
    def update_entry(self, item_id: UUID4, data: EntryUpdate) -> EntryRead:
        # The service emits entry_updated + any status-transition events (published/unpublished/
        # archived/restored), in that order.
        current = editable_entry(self.user, self.group_id, self.repos, item_id, data.status, data.publish_at)
        # The Trash has its own doors: DELETE puts an entry in, POST /restore takes it out. A trashed
        # entry is read-only until restored.
        if current.status == TRASHED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This entry is in the Trash. Restore it before editing it.")
        if data.status == TRASHED:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Move an entry to the Trash with DELETE /entries/{id}.")
        entry = self._entries().update(item_id, data)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return entry

    @router.delete("/{item_id}", summary="Move Entry to Trash (or delete a trashed entry forever)")
    def delete_entry(self, item_id: UUID4, permanent: bool = False) -> dict:
        """Move the entry to the Trash (`entry_trashed`; restorable). With `permanent=true`, delete an entry
        that is already in the Trash forever (`entry_deleted`); any other entry gets a 409."""
        entry = editable_entry(self.user, self.group_id, self.repos, item_id)
        if permanent:
            if entry.status != TRASHED:
                detail = "Only an entry in the Trash can be deleted forever. Move it to the Trash first."
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
            if not trash.delete_forever(self.session, self.group_id, [item_id], actor_id=self.user.id, event_bus=self.event_bus):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
            return {"status": "ok", "message": "Entry deleted forever", "deleted": True}
        if self._entries().trash(item_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return {"status": "ok", "message": "Entry moved to the Trash", "trashed": True}

    @router.post("/{item_id}/restore", response_model=EntryRead, summary="Restore Entry from Trash")
    def restore_entry(self, item_id: UUID4) -> EntryRead:
        """Take an entry out of the Trash, back to the status it had — a published entry comes back as a
        draft, so a restore never puts anything on the site by itself. Emits `entry_restored`."""
        entry = editable_entry(self.user, self.group_id, self.repos, item_id)
        if entry.status != TRASHED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This entry is not in the Trash.")
        require_can_edit_entry(self.user, self.group_id, entry, restore_status(entry))  # e.g. an AUTHOR restoring to Approved
        restored = self._entries().restore_from_trash(item_id)
        if restored is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return restored

    @router.get("/{entry_id}/collections", response_model=list[CollectionRead], summary="List Entry Collections")
    def list_entry_collections(self, entry_id: UUID4) -> list[CollectionRead]:
        """Get all collections this entry belongs to."""
        entry = self.repos.entries.get_one(entry_id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")

        # Query collections via junction table
        collection_ids = self.session.query(EntryCollections.collection_id).filter(EntryCollections.entry_id == entry_id).all()
        collection_ids = [cid[0] for cid in collection_ids]

        if not collection_ids:
            return []

        return [collection for collection in self.repos.collections.get_all() if collection.id in collection_ids]

    @router.post("/{entry_id}/collections/{collection_id}", status_code=status.HTTP_201_CREATED, summary="Add Entry to Collection")
    def add_entry_to_collection(self, entry_id: UUID4, collection_id: UUID4) -> dict:
        """Add an entry to a collection (via EntryService — emits `entry_added_to_collection`). Gated as
        an edit of the entry: an entry PATCH can set its collections too."""
        editable_entry(self.user, self.group_id, self.repos, entry_id)
        result = self._entries().add_to_collection(entry_id, collection_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry or collection not found in this workspace.")
        if result == "exists":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is already in this collection.")
        return {"message": "Entry added to collection successfully"}

    @router.delete("/{entry_id}/collections/{collection_id}", summary="Remove Entry from Collection")
    def remove_entry_from_collection(self, entry_id: UUID4, collection_id: UUID4) -> dict:
        """Remove an entry from a collection (via EntryService — emits `entry_removed_from_collection`)."""
        editable_entry(self.user, self.group_id, self.repos, entry_id)
        result = self._entries().remove_from_collection(entry_id, collection_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry or collection not found in this workspace.")
        if result == "absent":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry is not in this collection.")
        return {"status": "ok", "message": "Entry removed from collection successfully"}
