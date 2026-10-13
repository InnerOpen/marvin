"""Resources repository."""

from typing import Any

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.models.platform import Resources, ResourceTags, Tags
from marvin.repos.platform._suggestions import SuggestionWritebackMixin
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import ResourceRead


class ResourcesRepository(SuggestionWritebackMixin, GroupRepositoryGeneric):
    """Repository for managing resources."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Resources,
            schema=ResourceRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> ResourceRead:
        data_dict = data if isinstance(data, dict) else data.model_dump()
        tag_ids = data_dict.pop("tag_ids", None)
        resource = super().create(data_dict)
        if tag_ids:
            self._replace_tags(resource.id, tag_ids)
            resource = self.get_one(resource.id)
        self._resync_membership(resource.id)
        return resource

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> ResourceRead:
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)
        tag_ids = data_dict.pop("tag_ids", None)
        resource = super().update(match_value, data_dict, match_key=match_key)
        if tag_ids is not None:
            self._replace_tags(resource.id, tag_ids)
            resource = self.get_one(resource.id)
        self._resync_membership(resource.id)
        return resource

    def _resync_membership(self, resource_id: UUID4) -> None:
        """Re-evaluate this resource against resource-target smart collections (tags / resource_type)."""
        from marvin.services.collections.smart_collections import sync_item

        resource = self.session.get(Resources, resource_id)
        if resource and sync_item(self.session, resource.group_id, resource, "resource"):
            self.session.commit()

    def _replace_tags(self, resource_id: UUID4, tag_ids: list[UUID4]) -> None:
        """Replace all tags on a resource (empty list clears them)."""
        self.session.query(ResourceTags).filter(ResourceTags.resource_id == resource_id).delete()
        seen: set = set()
        for tag_id in tag_ids or []:
            if tag_id in seen:
                continue
            seen.add(tag_id)
            self.session.add(ResourceTags(resource_id=resource_id, tag_id=tag_id))
        self.session.commit()

    # ── AI write-back (apply staged suggestions) ───────────────────────────

    def apply_fields(self, resource_id: Any, fields: dict) -> None:
        """Apply a {target: value} map onto a resource and commit.

        Targets: the special "tags" target (find-or-create + link, unioned), a "metadata_json.<key>"
        path, or a real column (e.g. "description"). Unknown targets are ignored (so e.g. a
        generate-summary "summary" target on a resource — which has no summary column — is a no-op).
        """
        resource = self.session.get(Resources, resource_id)
        if not resource:
            return
        columns = {c.key for c in Resources.__table__.columns}
        for target, value in fields.items():
            if target == "_meta":
                continue
            if target == "tags":
                self._apply_tag_names(resource, value)
            elif target.startswith("metadata_json."):
                meta = dict(resource.metadata_json or {})
                meta[target.split(".", 1)[1]] = value
                resource.metadata_json = meta
            elif target in columns:
                setattr(resource, target, value)
        self.session.commit()

    def _apply_tag_names(self, resource: Resources, names: Any) -> None:
        """Find-or-create each tag name (group-scoped, by slug) and link it, unioned with existing."""
        if not isinstance(names, list | tuple):
            return
        from slugify import slugify

        have = {t.slug for t in resource.tags}
        for raw in names:
            slug = slugify(str(raw))
            if not slug or slug in have:
                continue
            tag = self.session.query(Tags).filter(Tags.group_id == resource.group_id, Tags.slug == slug).first()
            if tag is None:
                tag = Tags(session=self.session, group_id=resource.group_id, name=str(raw).strip(), slug=slug)
                self.session.add(tag)
                self.session.flush()
            self.session.add(ResourceTags(resource_id=resource.id, tag_id=tag.id))
            have.add(slug)
