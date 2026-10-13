"""SQLAlchemy model for AI execution audit log."""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class AIExecutionModel(SqlAlchemyBase, BaseMixins):
    """Immutable audit log row for every AI call."""

    __tablename__ = "ai_executions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="ai_executions")

    operation_slug: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    model_id: Mapped[str] = mapped_column(sa.String, nullable=False)

    # pending | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="pending")

    triggered_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)  # user_id
    # api | action | scheduler | mcp | renderer
    trigger_type: Mapped[str] = mapped_column(sa.String, nullable=False, default="api")

    entity_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)  # entry | asset | resource | ...
    entity_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True, index=True)

    # Stored only when workspace logging_config allows
    input_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    prompt_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    started_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime, nullable=True)
    completed_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime, nullable=True)

    # Spend/usage is almost always read as "this workspace, most recent first".
    __table_args__ = (sa.Index("ix_ai_executions_group_created", "group_id", "created_at"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
