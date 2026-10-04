"""Entry repositories."""

from datetime import UTC
from typing import Any

from fastapi import HTTPException, status
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.orm import Session

from marvin.db.models.platform import Entries, EntryAssets, EntryCollections, EntryResources, EntryTags, EntryTypes
from marvin.repos.platform._suggestions import SuggestionWritebackMixin
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import EntryRead
from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
from marvin.services.content_validator import ContentValidationError, ContentValidator


class EntriesRepository(SuggestionWritebackMixin, GroupRepositoryGeneric[EntryRead, Entries]):
    """Repository for workspace-scoped entries.

    Validates entry content (data_json) against entry type schema (schema_json)
    when creating or updating entries.
    """

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Entries,
            schema=EntryRead,
            group_id=group_id,
        )
        self.content_validator = ContentValidator()

    def _entry_type_exists(self, entry_type_id: UUID4) -> bool:
        """Check if entry type exists (includes system types)."""
        from sqlalchemy import or_

        query = select(EntryTypes.id).filter_by(id=entry_type_id)
        if self.group_id:
            # Include both workspace types AND system types
            query = query.filter(
                or_(
                    EntryTypes.group_id == self.group_id,
                    EntryTypes.group_id.is_(None),
                )
            )
        else:
            query = query.filter(EntryTypes.group_id.is_(None))
        return self.session.scalar(query) is not None

    def _get_entry_type(self, entry_type_id: UUID4) -> EntryTypes | None:
        """Get entry type by ID.

        Includes both workspace-scoped types AND system types (group_id=NULL).

        Args:
            entry_type_id: Entry type UUID

        Returns:
            EntryTypes model or None if not found
        """
        from sqlalchemy import or_

        query = select(EntryTypes).filter_by(id=entry_type_id)
        if self.group_id:
            # Include both workspace types AND system types
            query = query.filter(
                or_(
                    EntryTypes.group_id == self.group_id,
                    EntryTypes.group_id.is_(None),
                )
            )
        else:
            # If no group_id, only system types
            query = query.filter(EntryTypes.group_id.is_(None))
        return self.session.scalar(query)

    def _validate_content(self, entry_type_id: UUID4, data_json: dict) -> None:
        """Validate entry content against entry type schema.

        Args:
            entry_type_id: Entry type UUID
            data_json: Entry content data to validate

        Raises:
            HTTPException: If validation fails
        """
        # Get entry type with schema
        entry_type = self._get_entry_type(entry_type_id)
        if not entry_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entry type does not exist in this group.",
            )

        # Skip validation if no schema defined (legacy/default behavior)
        if not entry_type.schema_json or not entry_type.schema_json.get("fields"):
            return

        # Parse schema definition
        try:
            schema_def = EntryTypeSchemaDefinition.model_validate(entry_type.schema_json)
        except Exception as e:
            # Schema is invalid - this shouldn't happen if entry type was validated on create
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Entry type has invalid schema: {e}",
            ) from e

        # Validate content against schema
        try:
            self.content_validator.validate_content(schema_def, data_json)
        except ContentValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Content validation failed: {e.message}",
            ) from e

    def create(self, data: Any) -> EntryRead:
        from datetime import datetime

        from slugify import slugify

        data_dict = data if isinstance(data, dict) else data.model_dump()
        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Auto-generate slug from title if not provided
        if not data_dict.get("slug") and data_dict.get("title"):
            data_dict["slug"] = slugify(data_dict["title"])

        # Ensure slug uniqueness within the group (append -2, -3, … on collision) so
        # two entries with the same title don't violate the (group_id, slug) constraint.
        base_slug = data_dict.get("slug")
        if base_slug:
            slug, n = base_slug, 2
            while self.session.query(self.model.id).filter_by(group_id=data_dict.get("group_id"), slug=slug).first():
                slug, n = f"{base_slug}-{n}", n + 1
            data_dict["slug"] = slug

        # Validate entry type exists
        if not self._entry_type_exists(data_dict["entry_type_id"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entry type does not exist in this group.",
            )

        # Validate content against entry type schema
        if "data_json" in data_dict:
            self._validate_content(data_dict["entry_type_id"], data_dict["data_json"])

        # Auto-set published_at when creating with status 'published'; a schedule is moot then
        # (see update)
        if data_dict.get("status") == "published":
            if not data_dict.get("published_at"):
                data_dict["published_at"] = datetime.now(UTC)
            data_dict["publish_at"] = None

        # Extract relationship IDs before creating entry
        collection_ids = data_dict.pop("collection_ids", None)
        collection_attachments = data_dict.pop("collection_attachments", None)
        asset_ids = data_dict.pop("asset_ids", None)
        resource_ids = data_dict.pop("resource_ids", None)
        asset_attachments = data_dict.pop("asset_attachments", None)
        resource_attachments = data_dict.pop("resource_attachments", None)
        tag_ids = data_dict.pop("tag_ids", None)

        new_entry = self.model(session=self.session, **data_dict)
        self.session.add(new_entry)
        self.session.flush()

        if collection_attachments:
            self._attach_collection_attachments(new_entry.id, collection_attachments)
        elif collection_ids:
            self._attach_collections(new_entry.id, collection_ids)
        if asset_attachments:
            self._attach_asset_attachments(new_entry.id, asset_attachments)
        elif asset_ids:
            self._attach_assets(new_entry.id, asset_ids)
        if resource_attachments:
            self._attach_resource_attachments(new_entry.id, resource_attachments)
        elif resource_ids:
            self._attach_resources(new_entry.id, resource_ids)
        if tag_ids:
            self._attach_tags(new_entry.id, tag_ids)

        self.session.commit()

        created = self.get_one(new_entry.id)
        assert created is not None  # just created
        return created

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> EntryRead:
        from datetime import datetime

        from slugify import slugify

        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Get existing entry to check publish status
        existing_entry = self.get_one(match_value, key=match_key)
        assert existing_entry is not None  # updating an existing entry

        # Slug handling based on publish status
        if existing_entry.status == "published":
            # Published entries: slug is immutable to protect external URLs/SEO
            data_dict.pop("slug", None)
        else:
            # Unpublished entries: allow manual slug override, otherwise auto-generate from title
            if "slug" not in data_dict or not data_dict.get("slug"):
                # No manual slug provided - auto-generate if title is changing
                if "title" in data_dict and data_dict.get("title"):
                    data_dict["slug"] = slugify(data_dict["title"])
            # else: user provided explicit slug, use it as-is

        # Skip slug update if unchanged — SQLite re-checks UNIQUE constraints on every
        # UPDATE even when the value doesn't change, which causes spurious conflicts.
        if "slug" in data_dict and existing_entry and data_dict.get("slug") == existing_entry.slug:
            data_dict.pop("slug")

        # Handle published_at based on status changes
        if "status" in data_dict:
            if data_dict["status"] == "published":
                # Publishing by any route consumes the schedule, so the Publish Scheduled Entries
                # task can't put the entry live again after a later unpublish.
                data_dict["publish_at"] = None
                # Only set published_at if not already provided (first publish)
                if "published_at" not in data_dict:
                    # Get current entry to check if it was already published
                    current_entry = self.get_one(match_value, key=match_key)
                    if current_entry and not current_entry.published_at:
                        data_dict["published_at"] = datetime.now(UTC)
            else:
                # If unpublishing (changing to draft/etc), clear published_at
                data_dict["published_at"] = None

        # A scheduled publish the task is holding back (services/entries/scheduled_block.py): publishing,
        # archiving or rescheduling ends the wait; any other edit re-arms its notification.
        from marvin.services.entries.scheduled_block import after_edit

        stored = self.session.get(Entries, existing_entry.id)
        block_changed, block = after_edit(stored.scheduled_publish_blocked if stored else None, data_dict, existing_entry.publish_at)
        if block_changed:
            data_dict["scheduled_publish_blocked"] = block

        # Validate entry type exists if being changed
        entry_type_id = data_dict.get("entry_type_id")
        if entry_type_id and not self._entry_type_exists(entry_type_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entry type does not exist in this group.",
            )

        # Validate content if being updated
        # Need to determine which entry_type_id to use (new or existing)
        if "data_json" in data_dict:
            # Get the entry to find its entry_type_id if not being changed
            if not entry_type_id:
                existing_entry = self.get_one(match_value, key=match_key or self.primary_key)
                if existing_entry:
                    entry_type_id = existing_entry.entry_type_id

            if entry_type_id:
                self._validate_content(entry_type_id, data_dict["data_json"])

        data_dict.pop("group_id", None)

        # Extract relationship IDs before updating entry
        collection_ids = data_dict.pop("collection_ids", None)
        collection_attachments = data_dict.pop("collection_attachments", None)
        asset_ids = data_dict.pop("asset_ids", None)
        resource_ids = data_dict.pop("resource_ids", None)
        asset_attachments = data_dict.pop("asset_attachments", None)
        resource_attachments = data_dict.pop("resource_attachments", None)
        tag_ids = data_dict.pop("tag_ids", None)

        # Update the entry
        entry = super().update(match_value, data_dict, match_key=match_key)

        has_rel_changes = False

        # Update relationships if provided (replace existing)
        if collection_attachments is not None:
            self._replace_collection_attachments(entry.id, collection_attachments)
            has_rel_changes = True
        elif collection_ids is not None:
            self._replace_collections(entry.id, collection_ids)
            has_rel_changes = True
        if asset_attachments is not None:
            self._replace_asset_attachments(entry.id, asset_attachments)
            has_rel_changes = True
        elif asset_ids is not None:
            self._replace_assets(entry.id, asset_ids)
            has_rel_changes = True
        if resource_attachments is not None:
            self._replace_resource_attachments(entry.id, resource_attachments)
            has_rel_changes = True
        elif resource_ids is not None:
            self._replace_resources(entry.id, resource_ids)
            has_rel_changes = True
        if tag_ids is not None:
            self._replace_tags(entry.id, tag_ids)
            has_rel_changes = True

        if has_rel_changes:
            self.session.commit()
            self.session.refresh(self.session.get(Entries, entry.id))
            entry = self.get_one(entry.id)

        return entry

    # ── AI write-back (apply / stage suggestions) ──────────────────────────

    def apply_fields(self, entry_id: Any, fields: dict) -> None:
        """Apply a {target: value} map onto an entry and commit.

        Targets: a top-level column ("summary"/"title"/"description"), a "data_json.<key>"
        path, a "metadata_json.<key>" path, the special "tags" target (a list of tag names
        that get find-or-created and linked, unioned with the entry's existing tags), or the
        special "resources" target (a list of refs — id/slug/name — attached reuse-only, unioned
        with the entry's existing resources). `_meta` keys are ignored.
        """
        from marvin.services.entries.scheduled_block import after_edit

        entry = self.session.get(Entries, entry_id)
        if not entry:
            return
        columns = {t: v for t, v in fields.items() if t not in ("_meta", "tags", "resources") and "." not in t}
        block_changed, block = after_edit(entry.scheduled_publish_blocked, columns, entry.publish_at)
        if block_changed:
            entry.scheduled_publish_blocked = block
        for target, value in fields.items():
            if target == "_meta":
                continue
            if target == "tags":
                self._apply_tag_names(entry, value)
            elif target == "resources":
                self._apply_resource_refs(entry, value)
            elif target.startswith("data_json."):
                data = dict(entry.data_json or {})
                data[target.split(".", 1)[1]] = value
                entry.data_json = data
            elif target.startswith("metadata_json."):
                meta = dict(entry.metadata_json or {})
                meta[target.split(".", 1)[1]] = value
                entry.metadata_json = meta
            else:
                setattr(entry, target, value)
        self.session.commit()

    def _apply_tag_names(self, entry: Entries, names: Any) -> None:
        """Find-or-create each tag name (group-scoped, by slug) and link it to the entry.

        Additive (union with existing tags) — generate-tags SUGGESTS tags, it doesn't replace
        the curated set. No-op for a non-list value.
        """
        if not isinstance(names, list | tuple):
            return
        from slugify import slugify

        from marvin.db.models.platform import Tags

        have = {t.slug for t in entry.tags}
        for raw in names:
            slug = slugify(str(raw))
            if not slug or slug in have:
                continue
            tag = self.session.query(Tags).filter(Tags.group_id == entry.group_id, Tags.slug == slug).first()
            if tag is None:
                tag = Tags(session=self.session, group_id=entry.group_id, name=str(raw).strip(), slug=slug)
                self.session.add(tag)
                self.session.flush()
            self.session.add(EntryTags(entry_id=entry.id, tag_id=tag.id))
            have.add(slug)

    def _apply_resource_refs(self, entry: Entries, refs: Any) -> None:
        """Attach existing resources (reuse-only) referenced by id, slug, OR name — additive.

        The grounding lists resources by name, so a suggestion carries names; matching by name is
        essential. Unknown refs are ignored (never invents resources). No-op for a non-list value.
        """
        if not isinstance(refs, list | tuple):
            return
        import uuid as _uuid

        from marvin.db.models.platform import Resources

        have = {er.resource_id for er in self.session.query(EntryResources).filter_by(entry_id=entry.id)}
        for raw in refs:
            ref = str(raw).strip()
            if not ref:
                continue
            resource = None
            try:
                resource = self.session.get(Resources, _uuid.UUID(ref))
            except (ValueError, TypeError):
                resource = (
                    self.session.query(Resources)
                    .filter(Resources.group_id == entry.group_id)
                    .filter((Resources.slug == ref) | (Resources.name == ref))
                    .first()
                )
            if not resource or resource.group_id != entry.group_id or resource.id in have:
                continue
            self.session.add(EntryResources(entry_id=entry.id, resource_id=resource.id, position=0))
            have.add(resource.id)

    # ── Suggested (pending-review) asset links ─────────────────────────────

    def get_suggested_asset_link(self, entry_id: Any, asset_id: Any) -> EntryAssets | None:
        """The entry↔asset junction flagged ``suggested`` in its metadata_json, or None.

        Only pending AI-suggested links qualify — a normal (confirmed) link returns None, so
        approve/reject can never touch a curated asset.
        """
        junction = self.session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id, EntryAssets.asset_id == asset_id).first()
        if junction is None or not (junction.metadata_json or {}).get("suggested"):
            return None
        return junction

    # stage_suggestion / apply_suggestion / clear_suggestion come from SuggestionWritebackMixin.

    def _attach_collections(self, entry_id: UUID4, collection_ids: list[UUID4]) -> None:
        """Attach collections to an entry."""
        for sort_order, collection_id in enumerate(collection_ids):
            junction = EntryCollections(entry_id=entry_id, collection_id=collection_id, sort_order=sort_order)
            self.session.add(junction)
        self.session.flush()

    def _attach_assets(self, entry_id: UUID4, asset_ids: list[UUID4]) -> None:
        """Attach assets to an entry."""
        for position, asset_id in enumerate(asset_ids):
            junction = EntryAssets(entry_id=entry_id, asset_id=asset_id, position=position)
            self.session.add(junction)
        self.session.flush()

    def _attach_resources(self, entry_id: UUID4, resource_ids: list[UUID4]) -> None:
        """Attach resources to an entry."""
        for position, resource_id in enumerate(resource_ids):
            junction = EntryResources(entry_id=entry_id, resource_id=resource_id, position=position)
            self.session.add(junction)
        self.session.flush()

    def _attach_tags(self, entry_id: UUID4, tag_ids: list[UUID4]) -> None:
        """Attach tags to an entry, skipping any already present (idempotent)."""
        existing = {row.tag_id for row in self.session.query(EntryTags.tag_id).filter(EntryTags.entry_id == entry_id).all()}
        for tag_id in tag_ids:
            if tag_id in existing:
                continue
            existing.add(tag_id)
            self.session.add(EntryTags(entry_id=entry_id, tag_id=tag_id))
        self.session.flush()

    def _replace_tags(self, entry_id: UUID4, tag_ids: list[UUID4]) -> None:
        """Replace all tags on an entry (empty list clears them)."""
        self.session.query(EntryTags).filter(EntryTags.entry_id == entry_id).delete()
        if tag_ids:
            self._attach_tags(entry_id, tag_ids)

    def _replace_collections(self, entry_id: UUID4, collection_ids: list[UUID4]) -> None:
        """Replace all collections for an entry."""
        # Delete existing
        self.session.query(EntryCollections).filter(EntryCollections.entry_id == entry_id).delete()
        # Add new
        if collection_ids:
            self._attach_collections(entry_id, collection_ids)

    def _replace_assets(self, entry_id: UUID4, asset_ids: list[UUID4]) -> None:
        """Replace all assets for an entry."""
        # Delete existing
        self.session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id).delete()
        # Add new
        if asset_ids:
            self._attach_assets(entry_id, asset_ids)

    def _replace_resources(self, entry_id: UUID4, resource_ids: list[UUID4]) -> None:
        """Replace all resources for an entry."""
        # Delete existing
        self.session.query(EntryResources).filter(EntryResources.entry_id == entry_id).delete()
        # Add new
        if resource_ids:
            self._attach_resources(entry_id, resource_ids)

    def _attach_asset_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Attach assets with rich placement data."""
        for idx, att in enumerate(attachments):
            att_dict = att if isinstance(att, dict) else att.model_dump()
            junction = EntryAssets(
                entry_id=entry_id,
                asset_id=att_dict["asset_id"],
                position=att_dict.get("position") if att_dict.get("position") is not None else idx,
                role=att_dict.get("role"),
                metadata_json=att_dict.get("metadata"),
            )
            self.session.add(junction)
        self.session.flush()

    def _attach_resource_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Attach resources with rich placement data."""
        for idx, att in enumerate(attachments):
            att_dict = att if isinstance(att, dict) else att.model_dump()
            junction = EntryResources(
                entry_id=entry_id,
                resource_id=att_dict["resource_id"],
                position=att_dict.get("position") if att_dict.get("position") is not None else idx,
                role=att_dict.get("role"),
                metadata_json=att_dict.get("metadata"),
            )
            self.session.add(junction)
        self.session.flush()

    def _replace_asset_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Replace all asset attachments for an entry."""
        self.session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id).delete()
        if attachments:
            self._attach_asset_attachments(entry_id, attachments)

    def _replace_resource_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Replace all resource attachments for an entry."""
        self.session.query(EntryResources).filter(EntryResources.entry_id == entry_id).delete()
        if attachments:
            self._attach_resource_attachments(entry_id, attachments)

    def _attach_collection_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Attach collections with rich placement data."""
        for idx, att in enumerate(attachments):
            att_dict = att if isinstance(att, dict) else att.model_dump()
            junction = EntryCollections(
                entry_id=entry_id,
                collection_id=att_dict["collection_id"],
                sort_order=idx,
                role=att_dict.get("role"),
                metadata_json=att_dict.get("metadata"),
            )
            self.session.add(junction)
        self.session.flush()

    def _replace_collection_attachments(self, entry_id: UUID4, attachments: list) -> None:
        """Replace all collection attachments for an entry."""
        self.session.query(EntryCollections).filter(EntryCollections.entry_id == entry_id).delete()
        if attachments:
            self._attach_collection_attachments(entry_id, attachments)
