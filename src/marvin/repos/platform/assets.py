"""Assets repository."""

from typing import Any

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.models.platform import Assets, AssetTags, Tags
from marvin.repos.platform._suggestions import SuggestionWritebackMixin
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import AssetRead


class AssetsRepository(SuggestionWritebackMixin, GroupRepositoryGeneric):
    """Repository for managing assets."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Assets,
            schema=AssetRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> AssetRead:
        asset = super().create(data)
        self._resync_membership(asset.id)  # asset_type-target smart collections
        return asset

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> AssetRead:
        # Assets are created via upload; tags are applied here (PATCH) or via the attach endpoint.
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)
        tag_ids = data_dict.pop("tag_ids", None)
        asset = super().update(match_value, data_dict, match_key=match_key)
        if tag_ids is not None:
            self._replace_tags(asset.id, tag_ids)
            asset = self.get_one(asset.id)
        self._resync_membership(asset.id)
        return asset

    def _resync_membership(self, asset_id: UUID4) -> None:
        """Re-evaluate this asset against asset-target smart collections (tags / asset_type)."""
        from marvin.services.collections.smart_collections import sync_item

        asset = self.session.get(Assets, asset_id)
        if asset and sync_item(self.session, asset.group_id, asset, "asset"):
            self.session.commit()

    def _replace_tags(self, asset_id: UUID4, tag_ids: list[UUID4]) -> None:
        """Replace all tags on an asset (empty list clears them)."""
        self.session.query(AssetTags).filter(AssetTags.asset_id == asset_id).delete()
        seen: set = set()
        for tag_id in tag_ids or []:
            if tag_id in seen:
                continue
            seen.add(tag_id)
            self.session.add(AssetTags(asset_id=asset_id, tag_id=tag_id))
        self.session.commit()

    # ── AI write-back (apply staged suggestions) ───────────────────────────

    def apply_fields(self, asset_id: Any, fields: dict) -> None:
        """Apply a {target: value} map onto an asset and commit.

        Targets: the special "tags" target (find-or-create + link, unioned), a "metadata_json.<key>"
        path, or a real column (e.g. "alt_text"/"description"). Unknown targets are ignored.
        """
        asset = self.session.get(Assets, asset_id)
        if not asset:
            return
        columns = {c.key for c in Assets.__table__.columns}
        for target, value in fields.items():
            if target == "_meta":
                continue
            if target == "tags":
                self._apply_tag_names(asset, value)
            elif target.startswith("metadata_json."):
                meta = dict(asset.metadata_json or {})
                meta[target.split(".", 1)[1]] = value
                asset.metadata_json = meta
            elif target in columns:
                setattr(asset, target, value)
        self.session.commit()

    def _apply_tag_names(self, asset: Assets, names: Any) -> None:
        """Find-or-create each tag name (group-scoped, by slug) and link it, unioned with existing."""
        if not isinstance(names, list | tuple):
            return
        from slugify import slugify

        have = {t.slug for t in asset.tags}
        for raw in names:
            slug = slugify(str(raw))
            if not slug or slug in have:
                continue
            tag = self.session.query(Tags).filter(Tags.group_id == asset.group_id, Tags.slug == slug).first()
            if tag is None:
                tag = Tags(session=self.session, group_id=asset.group_id, name=str(raw).strip(), slug=slug)
                self.session.add(tag)
                self.session.flush()
            self.session.add(AssetTags(asset_id=asset.id, tag_id=tag.id))
            have.add(slug)
