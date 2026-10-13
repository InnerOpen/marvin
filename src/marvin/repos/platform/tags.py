"""Tags repository.

Tags are a shared, group-scoped vocabulary created on the fly. The distinguishing behavior
from other repos is **find-or-create by slug**: creating a tag whose slug already exists in the
workspace returns the existing row instead of raising, so "create-on-type" in the UI is safe to
call repeatedly and entry attach can resolve names to ids idempotently.
"""

from typing import Any

from pydantic import UUID4
from slugify import slugify
from sqlalchemy.orm import Session

from marvin.db.models.platform import Tags
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import TagRead


class TagsRepository(GroupRepositoryGeneric[TagRead, Tags]):
    """Repository for the workspace's shared tag vocabulary."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Tags,
            schema=TagRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> TagRead:
        """Find-or-create a tag by slug. Returns the existing tag if the slug is taken."""
        data_dict = data if isinstance(data, dict) else data.model_dump()
        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Slug is the identity; derive it from the display name when not supplied.
        if not data_dict.get("slug") and data_dict.get("name"):
            data_dict["slug"] = slugify(data_dict["name"])
        else:
            data_dict["slug"] = slugify(data_dict["slug"])

        existing = self._by_slug(data_dict["slug"])
        if existing is not None:
            found = self.get_one(existing.id)
            assert found is not None  # just matched by slug
            return found

        new_tag = self.model(session=self.session, **data_dict)
        self.session.add(new_tag)
        self.session.commit()
        created = self.get_one(new_tag.id)
        assert created is not None  # just created
        return created

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> TagRead:
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)
        # Slug is stable once created — protects smart-collection rules and publish-API references.
        data_dict.pop("slug", None)
        data_dict.pop("group_id", None)
        return super().update(match_value, data_dict, match_key=match_key)

    def find_or_create(self, name: str) -> Tags | None:
        """Resolve a tag name (or slug) to its ORM row, creating it if new. Returns None for blanks."""
        slug = slugify(str(name))
        if not slug:
            return None
        existing = self._by_slug(slug)
        if existing is not None:
            return existing
        tag = self.model(session=self.session, group_id=self.group_id, name=str(name).strip(), slug=slug)
        self.session.add(tag)
        self.session.flush()
        return tag

    def _by_slug(self, slug: str) -> Tags | None:
        query = self.session.query(Tags).filter(Tags.slug == slug)
        if self.group_id:
            query = query.filter(Tags.group_id == self.group_id)
        return query.first()
