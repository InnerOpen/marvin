"""Decide which process runs the scheduled callbacks.

The scheduler starts in every API process's lifespan. With more than one replica — the production
chart values ask for two — every replica ran the minutely callbacks, so `post_group_webhooks`
delivered each webhook once per replica and `check_scheduled_tasks` triggered each due task once
per replica.

Leadership is a lease on a single database row. A process may run a tick only while it holds an
unexpired lease, and the holder extends it on every tick. If the holder dies, the lease lapses and
another process claims it on its next tick, so leadership recovers on its own within
``LEASE_TTL_SECONDS``.

The claim is a conditional UPDATE, so the database decides the winner: two processes racing on the
same row both issue an UPDATE guarded by the same predicate, and only one reports a row changed.
No advisory locks, which keeps this working on SQLite as well as Postgres.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.core import root_logger
from marvin.db.models.platform.scheduler_lock import SCHEDULER_LOCK_ID, SchedulerLockModel

logger = root_logger.get_logger("scheduler")

# Default lease lifetime. Long enough that a leader busy with a slow tick does not lose the lease to
# a peer, short enough that a dead leader is replaced promptly. The minutely tick renews it every
# 60s. The running value comes from the SCHEDULER_LEASE_TTL_SECONDS setting (passed in by the tick
# gate); this constant is the fallback for direct calls and tests.
LEASE_TTL_SECONDS = 150

# Identifies this process for the lifetime of the process. The pid is only there to make logs
# readable; the uuid is what makes it unique, since pids repeat across pods.
INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    SQLite hands back naive datetimes even for DateTime(timezone=True) columns, so comparing a
    stored expiry against an aware `now` would raise. Postgres returns aware values and passes
    through untouched.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ensure_row(session: Session, now: datetime) -> None:
    """Create the singleton row if this is the first process to ever look.

    Written as already-expired and held by nobody, so the INSERT itself grants no leadership and
    the normal claim path below decides the winner. Two processes inserting concurrently is fine:
    the primary key rejects the loser, which then proceeds to claim.
    """
    exists = session.execute(select(SchedulerLockModel.id).where(SchedulerLockModel.id == SCHEDULER_LOCK_ID)).first()
    if exists:
        return

    try:
        session.add(
            SchedulerLockModel(
                id=SCHEDULER_LOCK_ID,
                holder_id="",
                expires_at=now - timedelta(seconds=1),
                acquired_at=now,
            )
        )
        session.commit()
    except IntegrityError:
        session.rollback()


def acquire_or_renew(session: Session, ttl_seconds: int = LEASE_TTL_SECONDS, instance_id: str | None = None) -> bool:
    """Claim leadership, or extend it if this process already holds it.

    Returns True when this process may run the tick. `instance_id` defaults to this process's
    identity and is a parameter so contention can be exercised without mutating module state,
    which threads in one interpreter would otherwise share.
    """
    instance_id = instance_id or INSTANCE_ID
    now = _now()
    _ensure_row(session, now)

    prior_holder = session.execute(select(SchedulerLockModel.holder_id).where(SchedulerLockModel.id == SCHEDULER_LOCK_ID)).scalar_one_or_none()

    # The predicate is the whole mechanism: renew what is already ours, or take a lease that has
    # lapsed. A live lease held by someone else matches nothing, so the UPDATE touches no rows.
    result = session.execute(
        update(SchedulerLockModel)
        .where(
            SchedulerLockModel.id == SCHEDULER_LOCK_ID,
            (SchedulerLockModel.holder_id == instance_id) | (SchedulerLockModel.expires_at <= now),
        )
        .values(holder_id=instance_id, expires_at=now + timedelta(seconds=ttl_seconds))
    )
    won = result.rowcount == 1

    if won and prior_holder != instance_id:
        # Only stamp acquired_at when leadership actually changes hands, so it keeps meaning
        # "leader since" rather than "last renewed".
        session.execute(update(SchedulerLockModel).where(SchedulerLockModel.id == SCHEDULER_LOCK_ID).values(acquired_at=now))
        logger.info(f"scheduler leadership acquired by {instance_id}")

    session.commit()
    return won


def release(session: Session, instance_id: str | None = None) -> None:
    """Give up leadership on shutdown so a peer takes over immediately rather than after the TTL.

    Only clears the lease if this process still holds it — a process that already lost leadership
    must not evict the current holder on its way out.
    """
    instance_id = instance_id or INSTANCE_ID
    session.execute(
        update(SchedulerLockModel)
        .where(SchedulerLockModel.id == SCHEDULER_LOCK_ID, SchedulerLockModel.holder_id == instance_id)
        .values(holder_id="", expires_at=_now() - timedelta(seconds=1))
    )
    session.commit()


def current_holder(session: Session) -> str | None:
    """The instance id currently holding an unexpired lease, if any. For diagnostics."""
    row = session.execute(
        select(SchedulerLockModel.holder_id, SchedulerLockModel.expires_at).where(SchedulerLockModel.id == SCHEDULER_LOCK_ID)
    ).first()
    if not row or not row.holder_id:
        return None
    return row.holder_id if _as_aware(row.expires_at) > _now() else None
