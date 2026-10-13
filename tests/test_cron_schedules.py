"""Cron schedules run: a cron scheduled task or workflow schedule gets a real next_run_at in its time zone
(the scheduler polls next_run_at; before, cron left it None and the task never ran), and one that can't run is
refused on save instead of being kept and never firing."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from marvin.repos.platform.scheduled_tasks import ScheduledTasksRepository
from marvin.schemas.group.automation_definition import ScheduleTrigger
from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate, ScheduledTaskUpdate
from marvin.services import cron

MONDAY_9_NY = {"cron_expression": "0 9 * * 1", "timezone": "America/New_York"}


def test_next_run_is_the_next_match_in_its_zone_across_dst():
    assert cron.next_run("0 9 * * 1", "America/New_York", datetime(2026, 10, 8, 12, tzinfo=UTC)) == datetime(2026, 10, 12, 13, tzinfo=UTC)
    # Clocks went back on 1 Nov: 09:00 New York is now 14:00 UTC.
    assert cron.next_run("0 9 * * 1", "America/New_York", datetime(2026, 11, 3, tzinfo=UTC)) == datetime(2026, 11, 9, 14, tzinfo=UTC)
    assert cron.next_run("0 3 1 * *", None, datetime(2026, 10, 8, 12, tzinfo=UTC)) == datetime(2026, 11, 1, 3, tzinfo=UTC)


def test_a_cron_task_gets_a_next_run_the_scheduler_will_pick_up():
    nxt = ScheduledTasksRepository._compute_next_run("cron", MONDAY_9_NY)
    assert nxt is not None and nxt > datetime.now(UTC)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert (local.weekday(), local.hour, local.minute) == (0, 9, 0)


@pytest.mark.parametrize(
    ("config", "says"),
    [
        ({}, "needs `cron_expression`"),
        ({"cron": "0 3 * * *"}, "needs `cron_expression`"),  # the wrong key used to be kept and never run
        ({"cron_expression": "0 9 * * MON"}, "use numbers, not names"),
        ({"cron_expression": "0 9 * *"}, "expected 5 fields"),
        ({"cron_expression": "61 9 * * 1"}, "can't read"),
        ({"cron_expression": "0 9 * * 1", "timezone": "Mars/Base"}, "unknown time zone"),
    ],
)
def test_a_cron_schedule_that_cant_run_is_refused(config, says):
    for build in (
        lambda: ScheduledTaskCreate(name="T", schedule_type="cron", schedule_config=config, task_type="publish"),
        lambda: ScheduledTaskUpdate(schedule_type="cron", schedule_config=config),
        lambda: ScheduleTrigger(type="schedule", schedule_type="cron", schedule_config=config),
    ):
        with pytest.raises(ValidationError, match=says):
            build()


def test_valid_cron_and_other_schedule_types_are_accepted():
    ScheduledTaskCreate(name="T", schedule_type="cron", schedule_config=MONDAY_9_NY, task_type="publish")
    ScheduledTaskCreate(name="T", schedule_type="cron", schedule_config={"cron_expression": "@daily"}, task_type="publish")
    ScheduledTaskCreate(name="T", schedule_type="interval", schedule_config={"interval_seconds": 60}, task_type="publish")
    ScheduledTaskUpdate(schedule_config={"cron_expression": "nonsense"})  # no type in the update: the stored one decides
    ScheduleTrigger(type="schedule", schedule_type="interval", schedule_config={"interval_seconds": 3600})


def test_existing_cron_tasks_with_no_next_run_are_scheduled_on_the_next_tick(db_session):
    """Saved before cron worked: next_run_at None, so never due. The scheduler's tick fills it in; one whose stored
    cron can't run (the old wrong key) stays unscheduled."""
    import uuid

    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.repos.repository_factory import AllRepositories

    def task(config, enabled=True):
        row = ScheduledTaskModel(
            session=db_session, group_id=None, name="Old cron", slug=f"old-cron-{uuid.uuid4().hex[:6]}", enabled=enabled,
            schedule_type="cron", schedule_config=config, task_type="publish", task_config={},
        )  # fmt: skip
        db_session.add(row)
        return row

    stuck, broken, off = task(MONDAY_9_NY), task({"cron": "0 3 * * *"}), task(MONDAY_9_NY, enabled=False)
    db_session.commit()
    try:
        assert AllRepositories(db_session, group_id=None).scheduled_tasks.schedule_unscheduled_cron() == 1
        db_session.expire_all()
        assert stuck.next_run_at is not None and broken.next_run_at is None and off.next_run_at is None
        assert AllRepositories(db_session, group_id=None).scheduled_tasks.schedule_unscheduled_cron() == 0
    finally:
        for row in (stuck, broken, off):
            db_session.delete(row)
        db_session.commit()
