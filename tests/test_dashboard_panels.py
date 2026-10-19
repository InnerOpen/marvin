"""The dashboard's panels beyond counts (services/dashboard.py): approvals a member may decide, parked runs, how
old the oldest draft is, the next week's publishes / resumes / tasks in order, the health strip's numbers and
workflow runs by day for the sparkline — one row per day, oldest first."""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
import uuid
from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.automation_executions import AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services import dashboard
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures

NOW = datetime.now(UTC).replace(microsecond=0)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


def _entry(ws, title, status="draft", **cols):
    entry = Entries(
        session=ws.session, group_id=ws.gid, entry_type_id=uuid.UUID(ws.et["id"]), title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}", status=status, data_json={}, metadata_json={}, **cols,
    )  # fmt: skip
    ws.session.add(entry)
    return entry


def _workflow(ws, name="Nightly digest"):
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name=name, slug=f"wf-{uuid.uuid4().hex[:6]}", enabled=True,
        definition={"trigger": {"type": "manual"}, "actions": [{"kind": "entry", "op": "publish"}]},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.flush()
    return row


def _run(ws, automation, status, started_at):
    row = AutomationExecutionModel(
        session=ws.session, group_id=ws.gid, automation_id=automation.id, automation_slug=automation.slug,
        trigger_type="manual", status=status, started_at=started_at,
    )  # fmt: skip
    ws.session.add(row)
    return row


def test_upcoming_lists_the_weeks_publishes_resumes_and_tasks_soonest_first(ws):
    wf = _workflow(ws)
    _entry(ws, "Tomorrow post", publish_at=(NOW + DAY).replace(tzinfo=None))
    _entry(ws, "Far post", publish_at=(NOW + 10 * DAY).replace(tzinfo=None))  # past the week
    _entry(ws, "Already out", status="published", publish_at=(NOW + DAY).replace(tzinfo=None))  # never fires
    ws.session.add(
        WorkflowWaitModel(
            session=ws.session,
            group_id=ws.gid,
            automation_id=wf.id,
            step_index=1,
            resume_at=(NOW + 2 * HOUR).replace(tzinfo=None),
            status="waiting",
            note="give it a day",
        )  # fmt: skip
    )
    ws.session.add(
        WorkflowWaitModel(
            session=ws.session, group_id=ws.gid, automation_id=wf.id, step_index=1, resume_at=(NOW + HOUR).replace(tzinfo=None), status="resumed"
        )
    )
    for name, enabled, at in (("Weekly roundup", True, NOW + 3 * DAY), ("Paused job", False, NOW + 3 * DAY)):
        ws.session.add(
            ScheduledTaskModel(
                session=ws.session,
                group_id=ws.gid,
                name=name,
                slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
                enabled=enabled,
                schedule_type="cron",
                schedule_config={"cron": "0 9 * * 1"},
                task_type="publish",
                task_config={},
                next_run_at=at,
            )  # fmt: skip
        )
    ws.session.commit()

    items = dashboard.upcoming(ws.session, ws.gid, NOW)

    assert [(i.kind, i.title) for i in items] == [
        ("resume", "Nightly digest resumes — give it a day"),
        ("publish", "Tomorrow post"),
        ("task", "Weekly roundup"),
    ]
    assert all(i.at.tzinfo is not None for i in items) and items[0].automation_id == str(wf.id)


def test_runs_by_day_has_a_row_per_day_with_ok_and_failed_counts(ws):
    wf = _workflow(ws)
    for status, when in (
        ("success", NOW),
        ("success", NOW),
        ("failed", NOW),
        ("partial", NOW),
        ("waiting", NOW),
        ("success", NOW - DAY),
        ("failed", NOW - 20 * DAY),
    ):
        _run(ws, wf, status, when)
    ws.session.commit()

    days = dashboard.runs_by_day(ws.session, ws.gid, NOW)

    assert len(days) == dashboard.SPARKLINE_DAYS and days[0].day < days[-1].day
    assert (days[-1].day, days[-1].ok, days[-1].failed) == (NOW.date(), 2, 2)  # a partial run counts as failed; a waiting one as neither
    assert (days[-2].ok, days[-2].failed) == (1, 0)
    assert sum(d.failed for d in days) == 2  # the 20-day-old failure is off the chart


def test_parked_runs_and_the_age_of_the_oldest_draft(ws):
    wf = _workflow(ws)
    _run(ws, wf, "waiting", NOW - HOUR)
    _run(ws, wf, "waiting", NOW - DAY)
    _run(ws, wf, "success", NOW)
    _entry(ws, "Old draft", created_at=(NOW - 10 * DAY).replace(tzinfo=None))
    _entry(ws, "New draft")
    ws.session.commit()

    assert dashboard.parked_runs(ws.session, ws.gid) == 2
    assert dashboard.oldest_entry_days(ws.session, ws.gid, "draft", NOW) == 10
    assert dashboard.oldest_entry_days(ws.session, ws.gid, "inbox", NOW) is None


def test_approvals_waiting_shows_the_oldest_few_a_member_may_decide(ws):
    wf = _workflow(ws, name="Publish gate")
    post = _entry(ws, "The post")
    ws.session.flush()
    for i in range(4):
        ws.session.add(
            WorkflowApprovalModel(
                session=ws.session,
                group_id=ws.gid,
                automation_id=wf.id,
                step_index=0,
                message=f"ok #{i}?",
                min_role=2,
                expires_at=(NOW + DAY).replace(tzinfo=None),
                created_at=(NOW - (4 - i) * HOUR).replace(tzinfo=None),
                entry_id=post.id if i == 0 else None,
                choices=["Now", "Later"] if i == 0 else None,
            )  # fmt: skip
        )
    ws.session.add(
        WorkflowApprovalModel(
            session=ws.session,
            group_id=ws.gid,
            automation_id=wf.id,
            step_index=0,
            message="done",
            min_role=2,
            status="approved",
            expires_at=NOW.replace(tzinfo=None),
        )
    )
    ws.session.commit()

    count, briefs = dashboard.approvals_waiting(ws.session, ws.gid, role=2)
    assert count == 4 and [b.message for b in briefs] == ["ok #0?", "ok #1?", "ok #2?"]
    assert (briefs[0].automation_name, briefs[0].entry_title, briefs[0].choices) == ("Publish gate", "The post", ["Now", "Later"])
    assert dashboard.approvals_waiting(ws.session, ws.gid, role=1) == (0, [])  # below the step's minimum role


def test_health_counts_failing_integrations_and_recent_failures_only(ws):
    before = dashboard.health(ws.session, ws.gid, NOW, sees_backups=False)  # the fixture workspace has integrations of its own
    wf = _workflow(ws)
    for slug, status in (("ig", "error"), ("mail", "ok")):
        ws.session.add(
            IntegrationModel(
                session=ws.session,
                group_id=ws.gid,
                provider="fake",
                name=slug,
                slug=slug,
                enabled=True,
                config={},
                secret_ref=f"X_{slug}",
                status=status,
            )
        )
    ws.session.add(
        IntegrationModel(
            session=ws.session, group_id=ws.gid, provider="fake", name="off", slug="off", enabled=False, config={}, secret_ref="X_off", status="error"
        )
    )
    hook = GroupWebhooksModel(session=ws.session, group_id=ws.gid, name="Hook", enabled=True, url="https://example.com/h")
    ws.session.add(hook)
    ws.session.flush()
    for status, when in (("failed", NOW - HOUR), ("failed", NOW - 3 * DAY), ("success", NOW)):
        ws.session.add(WebhookExecutionLogModel(session=ws.session, webhook_id=hook.id, group_id=ws.gid, executed_at=when, status=status))
    _run(ws, wf, "failed", NOW - 2 * DAY)
    _run(ws, wf, "failed", NOW - 10 * DAY)
    ws.session.commit()

    strip = dashboard.health(ws.session, ws.gid, NOW, sees_backups=False)

    added = (strip.integrations_total - before.integrations_total, strip.integrations_failing - before.integrations_failing)
    assert added == (2, 1)  # a disabled integration isn't counted
    assert (strip.webhook_failures_24h, strip.workflow_failures_7d) == (1, 1)
    assert strip.backup_state is None  # backups are platform-wide: only a platform admin gets the dot


def test_published_by_week_has_a_row_per_week_with_counts_by_type(ws):
    this_monday = NOW.date() - timedelta(days=NOW.weekday())
    _entry(ws, "This week A", status="published", published_at=datetime.combine(this_monday, datetime.min.time()) + HOUR)
    _entry(ws, "This week B", status="published", published_at=(NOW - timedelta(minutes=5)).replace(tzinfo=None))
    _entry(ws, "Last week", status="published", published_at=datetime.combine(this_monday - timedelta(days=3), datetime.min.time()))
    _entry(ws, "Long ago", status="published", published_at=(NOW - timedelta(weeks=30)).replace(tzinfo=None))
    _entry(ws, "Still a draft", published_at=(NOW - HOUR).replace(tzinfo=None))  # a date alone doesn't count
    ws.session.commit()

    pulse = dashboard.published_by_week(ws.session, ws.gid, NOW)

    slug = ws.et["slug"]
    assert len(pulse.weeks) == dashboard.PUBLISHING_WEEKS and pulse.weeks[-1].week == this_monday
    assert (pulse.weeks[-1].by_type.get(slug), pulse.weeks[-2].by_type.get(slug)) == (2, 1)
    assert pulse.total == 3 and [t.slug for t in pulse.types] == [slug]


def test_recent_for_you_lists_the_entries_this_member_touched_newest_first(ws):
    first, second, binned = _entry(ws, "Older edit"), _entry(ws, "Newer edit"), _entry(ws, "Binned", status="trashed")
    theirs = _entry(ws, "Someone else's")
    ws.session.flush()
    for entry, who, when in ((first, ws.uid, NOW - DAY), (second, ws.uid, NOW - HOUR), (binned, ws.uid, NOW), (theirs, uuid.uuid4(), NOW)):
        ws.session.add(
            EventLogModel(
                event_id=uuid.uuid4(),
                event_type="entry_updated",
                occurred_at=when,
                workspace_id=ws.gid,
                user_id=who if who == ws.uid else None,
                entity_id=entry.id,
                entity_type="entry",
                integration_id="test",
                event_data={},
                message_title=entry.title,
            )  # fmt: skip
        )
    ws.session.commit()

    recent = dashboard.recent_for_you(ws.session, ws.gid, ws.uid, NOW)

    assert [r.title for r in recent] == ["Newer edit", "Older edit"]  # the binned one and other people's are left out
    assert recent[0].type_slug == ws.et["slug"] and recent[0].touched_at.tzinfo is not None


def test_by_type_status_counts_each_types_pipeline(ws):
    for status in ("inbox", "draft", "draft", "published", "trashed"):
        _entry(ws, f"{status} one", status=status)
    ws.session.commit()

    row = next(r for r in dashboard.by_type_status(ws.session, ws.gid) if r.slug == ws.et["slug"])

    assert (row.inbox, row.draft, row.needs_review, row.approved, row.published) == (1, 2, 0, 0, 1)  # trashed isn't a stage
