"""Collections repository."""

from typing import Any

from fastapi import HTTPException, status
from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.models.platform import Collections, Entries, EntryCollections
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import CollectionRead
from marvin.schemas.platform.entries import TRASHED


class CollectionsRepository(GroupRepositoryGeneric[CollectionRead, Collections]):
    """Repository for managing collections."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Collections,
            schema=CollectionRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> CollectionRead:
        from slugify import slugify

        data_dict = data if isinstance(data, dict) else data.model_dump()
        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Auto-generate slug from name if not provided
        if not data_dict.get("slug") and data_dict.get("name"):
            data_dict["slug"] = slugify(data_dict["name"])

        # Extract entry_ids before creating collection
        entry_ids = data_dict.pop("entry_ids", None)

        # Create collection model instance but don't commit yet
        new_collection = self.model(session=self.session, **data_dict)
        self.session.add(new_collection)
        self.session.flush()  # Flush to get the collection ID

        # Attach entries if provided
        if entry_ids:
            self._attach_entries(new_collection.id, entry_ids)

        # Now commit everything together
        self.session.commit()

        # If this is a smart collection, materialize its membership from the rules.
        self._resync_smart_membership(new_collection.id)

        # Return via get_one to get all relationships loaded
        created = self.get_one(new_collection.id)
        assert created is not None  # just created
        return created

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> CollectionRead:
        # System workflow collections are locked (managed by Marvin).
        target = self.session.get(Collections, match_value)
        if target is not None and target.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System collections are managed by Marvin and cannot be modified.",
            )

        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Don't auto-regenerate slug on update - slugs should remain stable once created
        # to avoid breaking references in Publishing API, external integrations, and bookmarks
        data_dict.pop("slug", None)
        data_dict.pop("group_id", None)

        # Extract entry_ids before updating collection
        entry_ids = data_dict.pop("entry_ids", None)

        # Update the collection
        collection = super().update(match_value, data_dict, match_key=match_key)

        # Replace entries if provided
        if entry_ids is not None:
            self._replace_entries(collection.id, entry_ids)
            # Refresh to get updated relationships
            self.session.refresh(self.session.get(Collections, collection.id))
            refreshed = self.get_one(collection.id)
            assert refreshed is not None
            collection = refreshed

        # Re-materialize membership when this is (or just became) a smart collection, so a
        # rules change immediately re-evaluates which entries belong.
        if self._resync_smart_membership(collection.id):
            resynced = self.get_one(collection.id)
            assert resynced is not None
            collection = resynced

        return collection

    def _resync_smart_membership(self, collection_id: Any) -> bool:
        """Re-materialize a smart collection's membership from its rules. No-op if not smart.

        Returns True if the collection is smart (membership was (re)evaluated).
        """
        from marvin.services.collections.smart_collections import sync_collection

        collection = self.session.get(Collections, collection_id)
        if not collection or not collection.is_smart:
            return False
        if sync_collection(self.session, collection.group_id, collection):
            self.session.commit()
        return True

    def delete(self, value: Any, match_key: str | None = None) -> CollectionRead:
        collection = self.session.get(Collections, value)
        # System workflow collections cannot be deleted.
        if collection is not None and collection.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System collections cannot be deleted.",
            )
        # Smart collections own their membership — rows are auto-materialized from rules, not
        # curated — so the "in use by entries" guard doesn't apply; the FK cascade clears the
        # junction rows on delete.
        if not (collection and collection.is_smart):
            entry_count = self._count_entries_in_collection(value)
            if entry_count:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Collection is in use by entries and cannot be deleted.",
                )
        return super().delete(value, match_key=match_key)

    def _count_entries_in_collection(self, collection_id: Any) -> int:
        """Entries outside the Trash: a trashed entry doesn't keep its collection "in use" (deleting an entry trashes
        it, so a collection whose entries were all deleted would otherwise never be deletable). Its membership row
        goes with the collection, so a later restore brings the entry back without it."""
        count_query = (
            self.session.query(EntryCollections)
            .join(Entries, Entries.id == EntryCollections.entry_id)
            .filter(EntryCollections.collection_id == collection_id, Entries.status != TRASHED)
        )
        return count_query.count()

    def _attach_entries(self, collection_id: UUID4, entry_ids: list[UUID4]) -> None:
        """Attach entries to a collection."""
        for sort_order, entry_id in enumerate(entry_ids):
            junction = EntryCollections(entry_id=entry_id, collection_id=collection_id, sort_order=sort_order)
            self.session.add(junction)
        self.session.flush()

    def _replace_entries(self, collection_id: UUID4, entry_ids: list[UUID4]) -> None:
        """Replace all entries in a collection."""
        # Delete existing
        self.session.query(EntryCollections).filter(EntryCollections.collection_id == collection_id).delete()
        # Add new
        if entry_ids:
            self._attach_entries(collection_id, entry_ids)
