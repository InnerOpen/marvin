"""Integration-owned error handling — the durable state behind a provider's error policy.

Two tables:

  * ``integration_retries`` — one row per failed workflow step the policy asked to retry (or whose
    partial progress is worth keeping). The 60s retry sweep claims due rows, rebuilds the run from
    the snapshot + the current entry, and resumes at the failed step. ``live_key`` is set while the
    row is pending/parked/running and cleared when it finishes, so the unique constraint allows one
    live row per automation + target + step (NULLs never collide) while finished rows pile up as
    history until the prune.
  * ``integration_alerts`` — one open row per integration + error code ("needs attention"), counted
    and sampled instead of one alert per item. ``open_key`` plays the same trick as ``live_key``.
    ``channels`` records which subscription rows the alert went out through, so the "resolved"
    notice goes back through exactly those, whatever the routing says by then.

Never stores secrets: the snapshot is the triggering event + earlier step outputs, which the run
history already keeps.
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

RETRY_LIVE = ("pending", "parked", "running")
"""Retry statuses that still have work to do; the rest (succeeded, exhausted, failed, superseded) are history."""


class IntegrationRetryModel(SqlAlchemyBase, BaseMixins):
    """A failed integration step and what happens to it next.

    `status`: pending (due at `next_attempt_at`) | parked (waits for the connection to recover) |
    running (claimed by the sweep until `lease_until`) | succeeded | exhausted (retries used up) |
    failed (no retry; kept for its partial progress) | superseded (a fresh run passed the step, the
    entry no longer matches, or the workflow/entry is gone)."""

    __tablename__ = "integration_retries"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups")
    automation_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("workspace_automations.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True, index=True)
    entry_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=True, index=True)

    integration_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    provider: Mapped[str] = mapped_column(sa.String, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The provider action key that failed."""
    step_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    """Position of the failed step in the workflow's `actions` — where a retry resumes."""
    code: Mapped[str] = mapped_column(sa.String, nullable=False)

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="pending", index=True)
    live_key: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    """Retries made so far (0 until the first one runs)."""
    max_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    handle: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """The policy (Handle.to_dict()) driving this chain; its `then` applies once retries run out."""
    snapshot: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """{event, steps, previous, target_ref, gated, trigger_kind, user_id} — enough to resume the run."""
    partial: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """The provider's partial progress, handed back as ctx.resume."""
    idempotency_seed: Mapped[str] = mapped_column(sa.String, nullable=False)
    last_error: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    origin_execution_id: Mapped[GUID | None] = mapped_column(
        GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_execution_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "live_key", name="uq_integration_retries_live"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass


class IntegrationAlertModel(SqlAlchemyBase, BaseMixins):
    """A connection that needs attention: one open row per integration + error code. `status`: open | resolved."""

    __tablename__ = "integration_alerts"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups")
    integration_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    provider: Mapped[str] = mapped_column(sa.String, nullable=False)
    code: Mapped[str] = mapped_column(sa.String, nullable=False)

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="open", index=True)
    open_key: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    message: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The latest failure's message."""
    count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    samples: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    """The last few failures: [{at, message, action, entry_id, automation_slug, source}]."""
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When integration_attention_needed last went out (the open, or the latest reminder)."""
    channels: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """Where the alert went: {"email": [subscription ids], "integration": [subscription ids]}. The bell always gets it."""
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """How it resolved: check | action | manual."""

    __table_args__ = (sa.UniqueConstraint("group_id", "open_key", name="uq_integration_alerts_open"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
