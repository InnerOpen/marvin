"""Entry routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.platform import EntryCollections, EntryTypes
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import editable_entry, require_can_create_entry
from marvin.schemas.platform import CollectionRead, EntryCreate, EntryRead, EntryUpdate
from marvin.services.entries import EntryService
from marvin.services.entries.entry_service import count_by_status
from marvin.services.entry_urls import entry_url, site_base_url

router = APIRouter(prefix="/entries")


@controller(router)
class EntriesController(BaseUserController):
    """Authenticated CRUD routes for entries. Entry mutation + its events live in EntryService;
    this controller owns the HTTP concerns (auth, 404s, response shape).

    Any member reads. Writes follow the content roles: EDITORs and above change any entry; an AUTHOR
    creates entries and changes their own until they are approved or published (see
    `require_can_edit_entry`); a VIEWER gets a 403."""

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
        return self.repos.entries.get_all(order_by="created_at")

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
        editable_entry(self.user, self.group_id, self.repos, item_id, data.status, data.publish_at)
        entry = self._entries().update(item_id, data)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return entry

    @router.delete("/{item_id}", summary="Delete Entry")
    def delete_entry(self, item_id: UUID4) -> dict:
        editable_entry(self.user, self.group_id, self.repos, item_id)
        if not self._entries().delete(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return {"status": "ok", "message": "Entry deleted successfully"}

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
