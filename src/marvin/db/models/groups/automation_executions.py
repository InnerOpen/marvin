"""Execution records for Flavor B automations — observability for what actually ran.

Two tables:
  * ``automation_executions`` — one row per automation *run* (a triggering event/manual/schedule
    firing one automation). Carries a snapshot of the definition it ran, target/step counts, status,
    timing, and a correlation id so a chain of runs is readable.
  * ``automation_action_executions`` — one row per (target, action) — i.e. each step attempted for
    each matched entity when a run fans out over a `target` selector. This is what makes a batch run
    debuggable: which of the N entities succeeded, which step failed, and why.

Snapshots are truncated at a fixed byte cap (never persist unbounded content), and resolved secrets
are never recorded. History survives automation deletion (the automation FK is SET NULL), so an
audit trail isn't lost when a workflow is removed.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import DateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class AutomationExecutionModel(SqlAlchemyBase, BaseMixins):
    """One run of one automation. `status`: running | success | partial | failed."""

    __tablename__ = "automation_executions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups")

    # Keep the run even if the automation is later deleted (SET NULL); slug preserves the label.
    automation_id: Mapped[GUID | None] = mapped_column(
        GUID, sa.ForeignKey("workspace_automations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    automation_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="running")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Target selector accounting: matched = full query count; run = passed conditions + executed.
    targets_matched: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    targets_run: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    capped: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    steps_total: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    steps_ok: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    steps_failed: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    definition_snapshot: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String, nullable=True, index=True)
    triggered_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Integration error handling: every failure in the run was taken care of by the provider's error
    # policy (sent to review, retry scheduled, …) — still a failed run, but nobody needs to act on it.
    handled: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false(), nullable=False)
    # A retry run points at the run whose failed step it resumed (the chain reads back to the original).
    retry_of_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True, index=True)

    actions: Mapped[list["AutomationActionExecutionModel"]] = orm.relationship(
        "AutomationActionExecutionModel",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="AutomationActionExecutionModel.target_index, AutomationActionExecutionModel.action_index",
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass


class AutomationActionExecutionModel(SqlAlchemyBase, BaseMixins):
    """One action step attempted for one target within a run. `status`: success | failed."""

    __tablename__ = "automation_action_executions"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    execution_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    execution: Mapped["AutomationExecutionModel"] = orm.relationship("AutomationExecutionModel", back_populates="actions")
    group_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)

    target_index: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    target_entity_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    action_index: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(sa.String, nullable=False)
    label: Mapped[str | None] = mapped_column(sa.String, nullable=True)  # op / event / task / webhook name
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)  # truncated
    # How the provider's error policy handled this failed step: {code, policy, applied, summary, retry?}.
    handling: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
