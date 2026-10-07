"""Tag routes — CRUD over the workspace's shared tag vocabulary, plus entry attach/detach.

``POST /tags`` is find-or-create by slug (see ``TagsRepository``), so the UI can resolve a
freshly typed tag name to a stable id in one call. Attach/detach are lightweight and emit no
events — tags are labels, not curated placements like collections.

Any member reads. ``POST /tags`` is AUTHOR and above: it is how the entry editor resolves a typed tag
name, and an AUTHOR tags their own entries. Renaming or deleting a tag changes every entry carrying
it, so that is EDITOR and above. Tagging an entry is an edit of that entry (`require_can_edit_entry`);
tagging an asset or resource is EDITOR and above, like editing one.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4
from sqlalchemy import func

from marvin.db.models.platform import Assets, AssetTags, Entries, EntryTags, Resources, ResourceTags, Tags
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import editable_entry, require_workspace_editor, require_workspace_role
from marvin.schemas.platform import TagCreate, TagRead, TagUpdate

router = APIRouter(prefix="/tags")


@controller(router)
class TagsController(BaseUserController):
    """Authenticated CRUD routes for tags."""

    @router.get("", response_model=list[TagRead], summary="List Tags")
    def list_tags(self) -> list[TagRead]:
        tags = self.repos.tags.get_all(order_by="name", order_descending=False)

        # Per-junction counts, each in one grouped query (avoids N+1). entry_count drives the
        # entries-list filter; usage_count (entries + assets + resources) is the admin total.
        def _counts(junction, fk, *, entries: bool = False, item=None):
            q = self.session.query(junction.tag_id, func.count(getattr(junction, fk))).join(Tags, Tags.id == junction.tag_id)
            if entries:  # an entry in the Trash doesn't count as using the tag
                from marvin.services.entries.trash import not_trashed

                q = q.join(Entries, Entries.id == junction.entry_id).filter(not_trashed())
            if item is not None:  # nor does an asset or resource in the Trash
                q = q.join(item, item.id == getattr(junction, fk)).filter(item.trashed_at.is_(None))
            return dict(q.filter(Tags.group_id == self.group_id).group_by(junction.tag_id).all())

        entry_counts = _counts(EntryTags, "entry_id", entries=True)
        asset_counts = _counts(AssetTags, "asset_id", item=Assets)
        resource_counts = _counts(ResourceTags, "resource_id", item=Resources)
        for tag in tags:
            tag.entry_count = entry_counts.get(tag.id, 0)
            tag.usage_count = tag.entry_count + asset_counts.get(tag.id, 0) + resource_counts.get(tag.id, 0)
        return tags

    @router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED, summary="Create Tag")
    def create_tag(self, data: TagCreate) -> TagRead:
        """Find-or-create a tag by slug. Returns the existing tag if the name already resolves to one."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        return self.repos.tags.create(data)

    @router.get("/{item_id}", response_model=TagRead, summary="Get Tag")
    def get_tag(self, item_id: UUID4) -> TagRead:
        tag = self.repos.tags.get_one(item_id)
        if not tag:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        return tag

    @router.patch("/{item_id}", response_model=TagRead, summary="Update Tag")
    def update_tag(self, item_id: UUID4, data: TagUpdate) -> TagRead:
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.tags.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        return self.repos.tags.update(item_id, data)

    @router.delete("/{item_id}", summary="Delete Tag")
    def delete_tag(self, item_id: UUID4) -> dict:
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.tags.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        # FK cascade on entry_tags clears the junction rows; deleting a tag just unlabels entries.
        self.repos.tags.delete(item_id)
        return {"status": "ok", "message": "Tag deleted successfully"}

    @router.post("/{tag_id}/entries/{entry_id}", status_code=status.HTTP_201_CREATED, summary="Attach Tag to Entry")
    def attach_tag(self, tag_id: UUID4, entry_id: UUID4) -> dict:
        """Apply a tag to an entry. Idempotent — re-attaching an existing pair is a no-op."""
        entry = editable_entry(self.user, self.group_id, self.repos, entry_id)
        tag = self.repos.tags.get_one(tag_id)
        if not tag:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        if entry.group_id != tag.group_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Entry and tag must belong to the same workspace.")

        existing = self.session.query(EntryTags).filter(EntryTags.entry_id == entry_id, EntryTags.tag_id == tag_id).first()
        if existing is None:
            self.session.add(EntryTags(entry_id=entry_id, tag_id=tag_id))
            self.session.commit()
            self._resync_smart_membership(entry_id)
        return {"status": "ok", "message": "Tag attached"}

    @router.delete("/{tag_id}/entries/{entry_id}", summary="Detach Tag from Entry")
    def detach_tag(self, tag_id: UUID4, entry_id: UUID4) -> dict:
        # The lookup also scopes the delete to this workspace: the junction row alone has no group_id.
        editable_entry(self.user, self.group_id, self.repos, entry_id)
        deleted = self.session.query(EntryTags).filter(EntryTags.entry_id == entry_id, EntryTags.tag_id == tag_id).delete()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry does not carry this tag.")
        self.session.commit()
        self._resync_smart_membership(entry_id)
        return {"status": "ok", "message": "Tag detached"}

    def _resync_smart_membership(self, entry_id: UUID4) -> None:
        """A tag change can flip a tag-based smart collection's membership — re-materialize it."""
        from marvin.db.models.platform import Entries
        from marvin.services.collections.smart_collections import sync_entry

        entry = self.session.get(Entries, entry_id)
        if entry and sync_entry(self.session, entry.group_id, entry):
            self.session.commit()

    # ── Asset / resource tagging ───────────────────────────────────────────
    # Same lightweight attach/detach as entries, minus smart-collection resync (collections
    # only hold entries today).

    @router.post("/{tag_id}/assets/{asset_id}", status_code=status.HTTP_201_CREATED, summary="Attach Tag to Asset")
    def attach_tag_to_asset(self, tag_id: UUID4, asset_id: UUID4) -> dict:
        """Apply a tag to an asset. Idempotent."""
        require_workspace_editor(self.user, self.group_id)
        # Both lookups are scoped to this workspace, so a tag or asset from another one is a 404.
        if not self.repos.tags.get_one(tag_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        if not self.repos.assets.get_one(asset_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")

        existing = self.session.query(AssetTags).filter(AssetTags.asset_id == asset_id, AssetTags.tag_id == tag_id).first()
        if existing is None:
            self.session.add(AssetTags(asset_id=asset_id, tag_id=tag_id))
            self.session.commit()
            self._resync_item("asset", asset_id)
        return {"status": "ok", "message": "Tag attached"}

    @router.delete("/{tag_id}/assets/{asset_id}", summary="Detach Tag from Asset")
    def detach_tag_from_asset(self, tag_id: UUID4, asset_id: UUID4) -> dict:
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.assets.get_one(asset_id):  # scopes the delete to this workspace
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        deleted = self.session.query(AssetTags).filter(AssetTags.asset_id == asset_id, AssetTags.tag_id == tag_id).delete()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset does not carry this tag.")
        self.session.commit()
        self._resync_item("asset", asset_id)
        return {"status": "ok", "message": "Tag detached"}

    @router.post("/{tag_id}/resources/{resource_id}", status_code=status.HTTP_201_CREATED, summary="Attach Tag to Resource")
    def attach_tag_to_resource(self, tag_id: UUID4, resource_id: UUID4) -> dict:
        """Apply a tag to a resource. Idempotent."""
        require_workspace_editor(self.user, self.group_id)
        # Both lookups are scoped to this workspace, so a tag or resource from another one is a 404.
        if not self.repos.tags.get_one(tag_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
        if not self.repos.resources.get_one(resource_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")

        existing = self.session.query(ResourceTags).filter(ResourceTags.resource_id == resource_id, ResourceTags.tag_id == tag_id).first()
        if existing is None:
            self.session.add(ResourceTags(resource_id=resource_id, tag_id=tag_id))
            self.session.commit()
            self._resync_item("resource", resource_id)
        return {"status": "ok", "message": "Tag attached"}

    @router.delete("/{tag_id}/resources/{resource_id}", summary="Detach Tag from Resource")
    def detach_tag_from_resource(self, tag_id: UUID4, resource_id: UUID4) -> dict:
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.resources.get_one(resource_id):  # scopes the delete to this workspace
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        deleted = self.session.query(ResourceTags).filter(ResourceTags.resource_id == resource_id, ResourceTags.tag_id == tag_id).delete()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource does not carry this tag.")
        self.session.commit()
        self._resync_item("resource", resource_id)
        return {"status": "ok", "message": "Tag detached"}

    def _resync_item(self, target_type: str, item_id: UUID4) -> None:
        """Re-materialize asset/resource smart-collection membership after a tag change."""
        from marvin.db.models.platform import Assets, Resources
        from marvin.services.collections.smart_collections import sync_item

        model = {"asset": Assets, "resource": Resources}[target_type]
        item = self.session.get(model, item_id)
        if item and sync_item(self.session, item.group_id, item, target_type):
            self.session.commit()
