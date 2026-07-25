"""Only one process may run a scheduler tick.

Every API process starts the scheduler in its lifespan, and values-production asks for two
replicas, so both ran the minutely callbacks: `post_group_webhooks` delivered each webhook twice
and `check_scheduled_tasks` triggered each due task twice. Leadership is now a lease on a single
row, claimed with a conditional UPDATE so the database picks the winner.

These tests stand in for separate processes by swapping the module-level INSTANCE_ID, which is the
only thing distinguishing one process from another.
"""

from datetime import UTC, datetime, timedelta

from pytest import fixture
from sqlalchemy import delete, select

from marvin.db.models.platform.scheduler_lock import SCHEDULER_LOCK_ID, SchedulerLockModel
from marvin.services.scheduler import leader


@fixture(autouse=True)
def clean_lock(db_session):
    """Each test starts with no lease, and leaves none behind."""
    db_session.execute(delete(SchedulerLockModel))
    db_session.commit()
    yield
    db_session.execute(delete(SchedulerLockModel))
    db_session.commit()


def _as(monkeypatch, instance_id: str):
    """Run the next call as if from a different process."""
    monkeypatch.setattr(leader, "INSTANCE_ID", instance_id)


def test_first_process_becomes_leader(db_session, monkeypatch):
    _as(monkeypatch, "pod-a")

    assert leader.acquire_or_renew(db_session) is True
    assert leader.current_holder(db_session) == "pod-a"


def test_second_process_is_refused_while_the_lease_is_live(db_session, monkeypatch):
    """The whole point: a second replica must not run the same tick."""
    _as(monkeypatch, "pod-a")
    assert leader.acquire_or_renew(db_session) is True

    _as(monkeypatch, "pod-b")
    assert leader.acquire_or_renew(db_session) is False

    assert leader.current_holder(db_session) == "pod-a"


def test_only_one_of_many_contenders_wins_a_free_lease(db_session, monkeypatch):
    """Ten processes starting at once still yield exactly one leader."""
    winners = []
    for i in range(10):
        _as(monkeypatch, f"pod-{i}")
        if leader.acquire_or_renew(db_session):
            winners.append(f"pod-{i}")

    assert winners == ["pod-0"]


def test_leader_keeps_leadership_across_ticks(db_session, monkeypatch):
    _as(monkeypatch, "pod-a")

    assert leader.acquire_or_renew(db_session) is True
    assert leader.acquire_or_renew(db_session) is True
    assert leader.acquire_or_renew(db_session) is True


def test_renewal_pushes_the_expiry_forward(db_session, monkeypatch):
    _as(monkeypatch, "pod-a")
    leader.acquire_or_renew(db_session, ttl_seconds=60)
    first = db_session.execute(select(SchedulerLockModel.expires_at)).scalar_one()

    leader.acquire_or_renew(db_session, ttl_seconds=600)
    second = db_session.execute(select(SchedulerLockModel.expires_at)).scalar_one()

    assert second > first


def test_a_dead_leader_is_replaced_once_the_lease_lapses(db_session, monkeypatch):
    """Recovery without intervention: no heartbeat, so the lease expires and a peer takes over."""
    _as(monkeypatch, "pod-a")
    assert leader.acquire_or_renew(db_session) is True

    # pod-a stops renewing — simulate by expiring its lease.
    db_session.execute(
        SchedulerLockModel.__table__.update()
        .where(SchedulerLockModel.id == SCHEDULER_LOCK_ID)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()

    assert leader.current_holder(db_session) is None

    _as(monkeypatch, "pod-b")
    assert leader.acquire_or_renew(db_session) is True
    assert leader.current_holder(db_session) == "pod-b"


def test_acquired_at_marks_handover_not_renewal(db_session, monkeypatch):
    _as(monkeypatch, "pod-a")
    leader.acquire_or_renew(db_session)
    first = db_session.execute(select(SchedulerLockModel.acquired_at)).scalar_one()

    leader.acquire_or_renew(db_session)
    after_renew = db_session.execute(select(SchedulerLockModel.acquired_at)).scalar_one()

    assert after_renew == first, "renewing must not restamp acquired_at"


def test_release_hands_leadership_over_immediately(db_session, monkeypatch):
    _as(monkeypatch, "pod-a")
    leader.acquire_or_renew(db_session)

    leader.release(db_session)
    assert leader.current_holder(db_session) is None

    _as(monkeypatch, "pod-b")
    assert leader.acquire_or_renew(db_session) is True


def test_a_non_holder_cannot_release_the_current_leader(db_session, monkeypatch):
    """A process that already lost leadership must not evict the live holder on shutdown."""
    _as(monkeypatch, "pod-a")
    leader.acquire_or_renew(db_session)

    _as(monkeypatch, "pod-b")
    leader.release(db_session)

    assert leader.current_holder(db_session) == "pod-a"


def test_tick_is_skipped_when_another_process_holds_the_lease(db_session, monkeypatch):
    """The gate the callbacks actually sit behind."""
    from marvin.services.scheduler import scheduler_service

    _as(monkeypatch, "pod-a")
    assert leader.acquire_or_renew(db_session) is True

    _as(monkeypatch, "pod-b")
    assert scheduler_service._is_leader() is False


def test_election_failure_is_treated_as_not_leader(monkeypatch):
    """A database that cannot be reached must not let every replica assume leadership."""
    from marvin.services.scheduler import scheduler_service

    def boom(*_args, **_kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(scheduler_service, "acquire_or_renew", boom)

    assert scheduler_service._is_leader() is False


def test_concurrent_contenders_yield_exactly_one_leader(db_session):
    """The sequential tests above simulate processes in turn; this races them for real.

    Threads each carry their own instance id — the module global is shared inside one interpreter,
    so mutating it would have every thread claim whatever the last writer set. SQLite serialises
    writers with a database-level lock and reports spurious "database is locked" under this
    pattern, so the race only runs where production runs.
    """
    import threading

    from sqlalchemy.orm import sessionmaker

    bind = db_session.get_bind()
    if bind.dialect.name != "postgresql":
        import pytest

        pytest.skip("contention test needs a server that supports concurrent writers")

    db_session.execute(delete(SchedulerLockModel))
    db_session.commit()

    contenders = 16
    Session = sessionmaker(bind=bind)
    start = threading.Barrier(contenders)
    wins: list[str] = []
    guard = threading.Lock()

    def contend(i: int) -> None:
        session = Session()
        try:
            start.wait(timeout=10)
            if leader.acquire_or_renew(session, instance_id=f"pod-{i}"):
                with guard:
                    wins.append(f"pod-{i}")
        finally:
            session.close()

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(contenders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(wins) == 1, f"expected one leader, got {wins}"


def test_lease_ttl_is_configurable_with_a_safe_floor():
    """The lease TTL is a setting, guarded so it can't drop below the renew cadence's margin."""
    import pytest
    from pydantic import ValidationError

    from marvin.core.settings.settings import AppSettings

    assert AppSettings(SECRET="x").SCHEDULER_LEASE_TTL_SECONDS == 150
    assert AppSettings(SECRET="x", SCHEDULER_LEASE_TTL_SECONDS=600).SCHEDULER_LEASE_TTL_SECONDS == 600
    assert AppSettings(SECRET="x", SCHEDULER_LEASE_TTL_SECONDS=90).SCHEDULER_LEASE_TTL_SECONDS == 90

    # Below the floor the scheduler would renew every ~60s against a shorter lease and flap.
    with pytest.raises(ValidationError):
        AppSettings(SECRET="x", SCHEDULER_LEASE_TTL_SECONDS=60)


def test_is_leader_uses_the_configured_ttl(db_session, monkeypatch):
    """The tick gate passes the setting's TTL through to the lease, not a hardcoded 150."""
    from marvin.services.scheduler import scheduler_service

    captured = {}
    real = scheduler_service.acquire_or_renew

    def spy(session, ttl_seconds=None, instance_id=None):
        captured["ttl"] = ttl_seconds
        return real(session, ttl_seconds=ttl_seconds, instance_id=instance_id)

    monkeypatch.setattr(scheduler_service, "acquire_or_renew", spy)
    # session_context inside _is_leader opens its own session; the assertion is on the TTL passed.
    scheduler_service._is_leader()

    assert captured["ttl"] == scheduler_service.get_app_settings().SCHEDULER_LEASE_TTL_SECONDS
