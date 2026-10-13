"""
This module defines the SQLAlchemy model for webhook execution logging.

It includes:
- `WebhookExecutionLogModel`: Tracks all webhook execution attempts including
  success, failure, and retry information for debugging and audit purposes.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import DateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    pass


class WebhookExecutionLogModel(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing a webhook execution log entry.

    Tracks every webhook execution attempt including success, failure,
    and retry information for debugging and audit purposes.
    """

    __tablename__ = "webhook_execution_logs"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate, doc="Unique identifier for the log entry.")

    # Foreign key to the webhook configuration
    webhook_id: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("webhook_urls.id", ondelete="CASCADE"),
        index=True,
        doc="ID of the webhook that was executed.",
    )

    # Foreign key to the group
    group_id: Mapped[GUID] = mapped_column(
        GUID, ForeignKey("groups.id", ondelete="CASCADE"), index=True, doc="ID of the group this webhook belongs to."
    )

    # Execution metadata
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
        doc="Timestamp when the webhook was executed (UTC).",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Execution status: 'success', 'failed', or 'retrying'.",
    )

    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True, doc="HTTP status code returned by the webhook endpoint.")

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Error message if the execution failed.")

    retry_attempt: Mapped[int] = mapped_column(Integer, default=0, doc="Retry attempt number (0 for first attempt).")

    request_payload: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True, doc="The JSON payload sent to the webhook endpoint.")

    response_body: Mapped[str | None] = mapped_column(Text, nullable=True, doc="HTTP response body returned by the endpoint (captured on failure).")

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """
        Initializes a WebhookExecutionLogModel instance.

        Attributes are set by the `auto_init` decorator from `kwargs`.
        The `session` argument is required by `auto_init`.

        Args:
            session (Session): The SQLAlchemy session, required by `auto_init`.
            **kwargs: Attributes for the model, such as `webhook_id`, `status`, etc.
        """
        pass
