"""Form submission model."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class FormSubmissions(SqlAlchemyBase, BaseMixins):
    """Form submission record.

    Submissions are optionally persisted based on form settings.
    The data_json contains the actual submitted field values,
    and metadata_json tracks request context (IP, user agent, etc.).
    """

    __tablename__ = "form_submissions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    form_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)

    data_json: Mapped[dict] = mapped_column("data_json", sa.JSON, nullable=False, default=dict, server_default="{}")
    """Submitted field values."""

    metadata_json: Mapped[dict | None] = mapped_column("metadata_json", sa.JSON, nullable=True)
    """Request metadata (API client ID, referrer, etc.)."""

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="received", server_default="received")
    """Submission status: received | processed | failed."""

    # sa.String, not postgresql.INET: the column has always been VARCHAR in the schema (the
    # initial migration created it as sa.String), and INET is unrenderable on SQLite — it broke
    # autogenerate outright. Portable type, matching what's actually stored.
    ip_address: Mapped[str | None] = mapped_column(sa.String, nullable=True, index=True)
    """Submitter IP address."""

    user_agent: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Submitter browser user agent."""

    referrer: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """HTTP referrer URL."""

    submitted_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, default=datetime.utcnow, index=True)
    """Submission timestamp."""

    processed_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """When submission was processed."""

    __table_args__ = (sa.CheckConstraint("status IN ('received', 'processed', 'failed')", name="chk_submissions_status"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
