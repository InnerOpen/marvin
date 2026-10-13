"""Form repositories."""

from datetime import UTC, datetime
from typing import Any

from pydantic import UUID4
from slugify import slugify
from sqlalchemy import update
from sqlalchemy.orm import Session

from marvin.db.models.platform.forms import Forms
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform.forms import FormRead


class FormsRepository(GroupRepositoryGeneric[FormRead, Forms]):
    """Repository for workspace-scoped forms."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=Forms,
            schema=FormRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> FormRead:
        data_dict = data if isinstance(data, dict) else data.model_dump()

        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Auto-generate slug from name if not provided
        if not data_dict.get("slug") and data_dict.get("name"):
            data_dict["slug"] = slugify(data_dict["name"])

        return super().create(data_dict)

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> FormRead:
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Never allow group_id to be changed
        data_dict.pop("group_id", None)

        # Get existing form to check publish status
        existing = self.get_one(match_value, key=match_key)
        assert existing is not None  # updating an existing form

        # Protect slug once published to preserve external URLs
        if existing.status == "published":
            data_dict.pop("slug", None)

        return super().update(match_value, data_dict, match_key=match_key)

    def increment_submission_count(self, form_id: UUID4) -> None:
        """Increment submissions_count and update last_submission_at.

        Uses raw SQL update for performance - avoids loading the full model.
        """
        stmt = (
            update(Forms)
            .where(Forms.id == form_id)
            .values(
                submissions_count=Forms.submissions_count + 1,
                last_submission_at=datetime.now(UTC),
            )
        )
        self.session.execute(stmt)
        self.session.commit()
