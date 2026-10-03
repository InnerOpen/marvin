"""Collection routes."""

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4, BaseModel, ConfigDict, Field

from marvin.db.models.platform import EntryCollections
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.platform import (
    CollectionCreate,
    CollectionRead,
    CollectionUpdate,
    EntryRead,
    SmartRulesPreview,
    SmartRulesPreviewRequest,
    UpdateEntryCollectionRequest,
)
from marvin.services.event_bus_service.event_types import EventCollectionData, EventOperation, EventTypes

router = APIRouter(prefix="/collections")


class EntryOrderItem(BaseModel):
    """Schema for a single entry order update."""

    entry_id: UUID4 = Field(validation_alias="entryId")
    sort_order: int = Field(validation_alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)


class ReorderEntriesRequest(BaseModel):
    """Schema for bulk reordering entries in a collection."""

    entries: list[EntryOrderItem]


class CollectionOrderItem(BaseModel):
    """Schema for a single collection order update."""

    id: UUID4
    sort_order: int = Field(validation_alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)


class ReorderCollectionsRequest(BaseModel):
    """Schema for bulk reordering collections in the workspace."""

    collections: list[CollectionOrderItem]


@controller(router)
class CollectionsController(BaseUserController):
    """Authenticated CRUD routes for collections."""

    @router.get("", response_model=list[CollectionRead], summary="List Collections")
    def list_collections(self) -> list[CollectionRead]:
        # Ordered by sort_order (ascending) so the system workflow collections (negative
        # sort_order) lead — Inbox first — and drag-and-drop reordering is reflected.
        collections = self.repos.collections.get_all(order_by="sort_order", order_descending=False)

        # Attach member counts. entry_count carries the count of whatever the collection targets
        # (entries / assets / resources) — one grouped query per junction (avoids N+1).
        from sqlalchemy import func

        from marvin.db.models.platform import CollectionAssets, CollectionResources, Collections, EntryCollections

        def _counts(junction, fk):
            return dict(
                self.session.query(junction.collection_id, func.count(getattr(junction, fk)))
                .join(Collections, Collections.id == junction.collection_id)
                .filter(Collections.group_id == self.group_id)
                .group_by(junction.collection_id)
                .all()
            )

        by_type = {
            "entry": _counts(EntryCollections, "entry_id"),
            "asset": _counts(CollectionAssets, "asset_id"),
            "resource": _counts(CollectionResources, "resource_id"),
        }
        for collection in collections:
            counts = by_type.get(getattr(collection, "target_type", "entry") or "entry", {})
            collection.entry_count = counts.get(collection.id, 0)
        return collections

    @router.patch("/order", summary="Reorder Collections")
    def reorder_collections(self, data: ReorderCollectionsRequest) -> dict:
        """Bulk-update collection sort_order for this workspace.

        Writes sort_order directly (not via the repo update), so it works for system
        collections too — reordering is display-only and doesn't touch their locked content.
        """
        from marvin.db.models.platform import Collections

        ids = [item.id for item in data.collections]
        rows = self.session.query(Collections).filter(Collections.group_id == self.group_id, Collections.id.in_(ids)).all()
        by_id = {row.id: row for row in rows}
        for item in data.collections:
            row = by_id.get(item.id)
            if row is not None:
                row.sort_order = item.sort_order
        self.session.commit()
        return {"updated": len(rows)}

    @router.post("", response_model=CollectionRead, status_code=status.HTTP_201_CREATED, summary="Create Collection")
    def create_collection(self, data: CollectionCreate) -> CollectionRead:
        collection = self.repos.collections.create(data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="collection_management",
            group_id=self.group_id,
            event_type=EventTypes.collection_created,
            document_data=EventCollectionData(
                operation=EventOperation.create,
                collection_id=collection.id,
                collection_name=collection.name,
                workspace_id=collection.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Collection '{collection.name}' created",
            user_id=self.user.id if self.user else None,
            entity_id=collection.id,
            entity_type="collection",
        )

        return collection

    @router.post("/preview", response_model=SmartRulesPreview, summary="Preview Smart Collection Rules")
    def preview_smart_rules(self, data: SmartRulesPreviewRequest) -> SmartRulesPreview:
        """What a smart collection with these (unsaved) rules would contain, without saving anything.

        Evaluated by ``matching_items`` — the same code that materializes membership on save — so
        the count is exactly what the collection would hold. Scoped to the caller's workspace.
        """
        from marvin.services.collections.smart_collections import has_rules, ignored_keys, matching_items

        rules = data.smart_rules or {}
        matches = matching_items(self.session, self.group_id, rules, data.target_type)
        label_attr = "title" if data.target_type == "entry" else "name"
        items = [
            {"id": m.id, "label": getattr(m, label_attr, None) or m.slug or str(m.id), "slug": m.slug, "type": data.target_type}
            for m in matches[: data.limit]
        ]
        ignored = ignored_keys(rules, data.target_type)
        note = None
        if not has_rules(rules, data.target_type):
            note = "None of these keys is a rule here, so nothing matches." if ignored else "No rules yet. An empty rule set matches nothing."
        return SmartRulesPreview(total=len(matches), items=items, ignored_keys=ignored, note=note)

    @router.get("/{item_id}", response_model=CollectionRead, summary="Get Collection")
    def get_collection(self, item_id: UUID4) -> CollectionRead:
        collection = self.repos.collections.get_one(item_id)
        if not collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")
        return collection

    @router.patch("/{item_id}", response_model=CollectionRead, summary="Update Collection")
    def update_collection(self, item_id: UUID4, data: CollectionUpdate) -> CollectionRead:
        if not self.repos.collections.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")

        collection = self.repos.collections.update(item_id, data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="collection_management",
            group_id=self.group_id,
            event_type=EventTypes.collection_updated,
            document_data=EventCollectionData(
                operation=EventOperation.update,
                collection_id=collection.id,
                collection_name=collection.name,
                workspace_id=collection.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Collection '{collection.name}' updated",
            user_id=self.user.id if self.user else None,
            entity_id=collection.id,
            entity_type="collection",
        )

        return collection

    @router.delete("/{item_id}", summary="Delete Collection")
    def delete_collection(self, item_id: UUID4) -> dict:
        collection = self.repos.collections.get_one(item_id)
        if not collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")

        # Emit event before deletion
        self.event_bus.dispatch(
            integration_id="collection_management",
            group_id=self.group_id,
            event_type=EventTypes.collection_deleted,
            document_data=EventCollectionData(
                operation=EventOperation.delete,
                collection_id=collection.id,
                collection_name=collection.name,
                workspace_id=collection.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Collection '{collection.name}' deleted",
            user_id=self.user.id if self.user else None,
            entity_id=collection.id,
            entity_type="collection",
        )

        self.repos.collections.delete(item_id)
        return {"status": "ok", "message": "Collection deleted successfully"}

    @router.get("/{item_id}/members", summary="Get Collection Members")
    def get_collection_members(self, item_id: UUID4) -> list[dict]:
        """Lightweight membership list for a collection of any target type.

        Returns ``[{id, label, slug, type}]`` — entries (title), assets (name), or resources (name)
        depending on the collection's target_type. Used by the admin UI to show membership of
        asset/resource smart collections uniformly.
        """
        collection = self.repos.collections.get_one(item_id)
        if not collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")

        from marvin.db.models.platform import (
            Assets,
            CollectionAssets,
            CollectionResources,
            Entries,
            Resources,
        )

        target = getattr(collection, "target_type", "entry") or "entry"
        model, junction, fk, label_col = {
            "entry": (Entries, EntryCollections, EntryCollections.entry_id, "title"),
            "asset": (Assets, CollectionAssets, CollectionAssets.asset_id, "name"),
            "resource": (Resources, CollectionResources, CollectionResources.resource_id, "name"),
        }[target]

        rows = (
            self.session.query(model)
            .join(junction, model.id == fk)
            .filter(junction.collection_id == item_id)
            .order_by(getattr(model, label_col))
            .all()
        )
        return [{"id": str(r.id), "label": getattr(r, label_col), "slug": r.slug, "type": target} for r in rows]

    @router.get("/{item_id}/entries", response_model=list[EntryRead], summary="Get Collection Entries")
    def get_collection_entries(self, item_id: UUID4) -> list[EntryRead]:
        """Get all entries in a collection, ordered by sort_order."""
        collection = self.repos.collections.get_one(item_id)
        if not collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")

        from marvin.db.models.platform.entries import Entries

        entries = (
            self.session.query(Entries)
            .join(EntryCollections, Entries.id == EntryCollections.entry_id)
            .filter(EntryCollections.collection_id == item_id)
            .options(*EntryRead.loader_options())
            .order_by(
                sa.case(
                    (EntryCollections.sort_order.is_(None), 1),
                    else_=0,
                ),
                EntryCollections.sort_order.asc(),
                Entries.published_at.desc(),
            )
            .all()
        )

        return [EntryRead.model_validate(entry) for entry in entries]

    @router.patch("/{item_id}/entries/order", summary="Reorder Collection Entries")
    def reorder_collection_entries(self, item_id: UUID4, data: ReorderEntriesRequest) -> dict:
        """Bulk update sort_order for entries in a collection."""
        collection = self.repos.collections.get_one(item_id)
        if not collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found.")

        # Verify all entries belong to this collection
        entry_ids = [item.entry_id for item in data.entries]
        existing_junctions = (
            self.session.query(EntryCollections).filter(EntryCollections.collection_id == item_id, EntryCollections.entry_id.in_(entry_ids)).all()
        )

        existing_entry_ids = {j.entry_id for j in existing_junctions}
        missing_entries = set(entry_ids) - existing_entry_ids

        if missing_entries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Some entries are not in this collection: {missing_entries}",
            )

        # Update sort_order for each entry
        for item in data.entries:
            junction = next((j for j in existing_junctions if j.entry_id == item.entry_id), None)
            if junction:
                junction.sort_order = item.sort_order
                junction.update_at = sa.func.now()

        self.session.commit()

        # Emit event
        self.event_bus.dispatch(
            integration_id="collection_management",
            group_id=self.group_id,
            event_type=EventTypes.collection_updated,
            document_data=EventCollectionData(
                operation=EventOperation.update,
                collection_id=collection.id,
                collection_name=collection.name,
                workspace_id=collection.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Collection '{collection.name}' entries reordered",
            user_id=self.user.id if self.user else None,
            entity_id=collection.id,
            entity_type="collection",
        )

        return {"status": "ok", "message": f"Reordered {len(data.entries)} entries"}

    @router.patch("/{item_id}/entries/{entry_id}", summary="Update Entry-Collection Junction")
    def update_entry_junction(self, item_id: UUID4, entry_id: UUID4, data: UpdateEntryCollectionRequest) -> dict:
        """Update role and metadata_json on a specific entry-collection junction record."""
        junction = (
            self.session.query(EntryCollections).filter(EntryCollections.collection_id == item_id, EntryCollections.entry_id == entry_id).first()
        )
        if not junction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Entry is not in this collection.",
            )

        if data.role is not None:
            junction.role = data.role
        if data.metadata_json is not None:
            junction.metadata_json = data.metadata_json
        junction.update_at = sa.func.now()

        self.session.commit()

        return {"status": "ok", "message": "Junction updated"}
