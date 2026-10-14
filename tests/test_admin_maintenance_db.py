"""Admin → Database & cleanup: the database size, the largest tables and what trims each one."""

from marvin.services.database_report import LOGS, TABLES, database_report


def test_the_report_lists_the_largest_tables_with_what_trims_them(db_session):
    from marvin.services.scheduled_tasks.system_tasks import seed_system_scheduled_tasks

    seed_system_scheduled_tasks(db_session)
    db_session.commit()
    report = database_report(db_session)

    assert report.size_bytes > 0 and report.tables
    assert all(t.size_bytes >= 0 and 0 <= t.share <= 1 for t in report.tables)
    sizes = [t.size_bytes for t in report.tables]
    assert sizes == sorted(sizes, reverse=True)
    for t in report.tables:
        _label, kept = TABLES.get(t.name, (None, None))
        if kept is None:
            assert t.kept_by is None  # nothing trims it: the page says so
            assert t.kind == ("log" if t.name in LOGS else "content")
        else:
            assert t.kept_by is not None and t.kept_by.slug == kept.task and t.kept_by.retention
    assert {c.slug for c in report.other_cleanup} <= {"cleanup_temp_files", "optimize_database"}


def test_event_log_retention_reads_the_setting_unless_the_task_overrides_it(db_session):
    from marvin.services.database_report import Kept, _days

    class Task:
        task_config = {}

    assert _days(Kept("prune_event_logs", setting="EVENT_LOG_RETENTION_DAYS"), Task()) == "older than 90 days"
    Task.task_config = {"retention_days": 30}
    assert _days(Kept("prune_event_logs", setting="EVENT_LOG_RETENTION_DAYS"), Task()) == "older than 30 days"
    Task.task_config = {"retention_days": 0}
    assert _days(Kept("prune_event_logs", setting="EVENT_LOG_RETENTION_DAYS"), Task()) == "kept forever (retention off)"
    assert _days(Kept("prune_revoked_tokens", rule="revoked over 30 days ago"), None) == "revoked over 30 days ago"
