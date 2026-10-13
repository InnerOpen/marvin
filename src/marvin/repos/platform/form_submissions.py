"""Form submission repositories."""

from datetime import UTC, datetime
from typing import Any

from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy.orm import Session

from marvin.db.models.platform.form_submissions import FormSubmissions
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform.form_submissions import FormSubmissionRead


class FormSubmissionsRepository(GroupRepositoryGeneric[FormSubmissionRead, FormSubmissions]):
    """Repository for form submissions."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=FormSubmissions,
            schema=FormSubmissionRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> FormSubmissionRead:
        data_dict = data if isinstance(data, dict) else data.model_dump()

        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Always set submitted_at to now
        data_dict["submitted_at"] = datetime.now(UTC)

        return super().create(data_dict)

    def get_by_form(self, form_id: UUID4, limit: int = 100, offset: int = 0) -> list[FormSubmissionRead]:
        """Get submissions for a specific form.

        Args:
            form_id: Form UUID
            limit: Max results to return
            offset: Number of results to skip

        Returns:
            List of form submissions ordered by submission time (newest first)
        """
        query = (
            select(FormSubmissions)
            .where(FormSubmissions.form_id == form_id)
            .order_by(FormSubmissions.submitted_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if self.group_id:
            query = query.where(FormSubmissions.group_id == self.group_id)

        results = self.session.execute(query).scalars().all()
        return [self.schema.model_validate(r) for r in results]
