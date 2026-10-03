"""Pending static-site rebuilds, one row per workspace.

A rebuild request (the `request_site_rebuild` handler, usually from a workflow) records a row here
instead of firing the deploy hook. The scheduler sends one `webhook_triggered` per workspace once
requests have gone quiet (see marvin.services.site_rebuild), so a bulk edit that fires a workflow per
entry costs one site build, not one per entry. A row in the database rather than an in-process
timer so a pending rebuild survives a restart and only the scheduler leader sends it.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class SiteRebuildRequestModel(SqlAlchemyBase, BaseMixins):
    """A workspace's not-yet-sent rebuild. Deleted when the rebuild is dispatched."""

    __tablename__ = "site_rebuild_requests"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, unique=True)
    """At most one pending rebuild per workspace — the unique key is what makes concurrent requests join one row."""

    first_requested_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    """The oldest request still waiting — bounds how long a steady stream of requests can defer the build."""

    last_requested_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    """The newest request; the build goes out once this is old enough (requests have gone quiet)."""

    request_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default="1")
    """How many requests this one rebuild covers — for the log line and the toast's "N changes"."""

    reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The most recent request's reason."""

    changes: Mapped[list[dict] | None] = mapped_column(sa.JSON, nullable=True)
    """What this rebuild covers, newest last: one {label, event, entity_type, entity_id} per changed
    thing (a repeat edit moves it to the end), capped — `request_count` stays the exact total."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
