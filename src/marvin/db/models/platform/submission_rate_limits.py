"""Rate limiting model for public submissions to submittable entry types.

Generalizes the form-specific ``form_rate_limits`` (which FK's to ``forms.id``) to a plain
``subject_id`` so it can key off an entry type. No foreign key — the subject is a submittable
entry type today, and the rows are ephemeral (windowed), so a dangling subject just expires.
Replaces ``form_rate_limits`` once the legacy Forms tables are dropped (see
tasks/forms-as-entry-types.md).
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class SubmissionRateLimits(SqlAlchemyBase, BaseMixins):
    """Tracks submission counts per identifier (IP) within sliding windows, keyed by subject."""

    __tablename__ = "submission_rate_limits"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    subject_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)
    """The submittable subject (an entry type id). No FK — the subject may outlive/precede its rows."""

    identifier: Mapped[str] = mapped_column(sa.String, nullable=False)
    """IP address or API client ID."""

    window_start: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False, index=True)
    """Start of the rate limit window."""

    submission_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default="1")
    """Number of submissions in this window."""

    __table_args__ = (
        sa.UniqueConstraint("subject_id", "identifier", "window_start", name="uq_submission_rate_limit_window"),
        sa.Index("ix_submission_rate_limits_subject_identifier", "subject_id", "identifier"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
