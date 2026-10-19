"""Metric observations: a `metric` step records a number against a metric, variant and window — idempotent per key, the
window read in the workspace's time zone — and a read lists them back, observations not conclusions. Plus the Metrics
API (filters, roles, isolation)."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from marvin.db.models.groups.metric_contributions import MetricContributionModel
from marvin.db.models.groups.metric_observations import MetricObservationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.automation_definition import MetricAction
from marvin.services import metrics
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.metric import run_metric_action
from marvin.services.automation.authoring import draft_issues
from tests import test_content_role_gates as gates
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures

NY = ZoneInfo("America/New_York")
UTC_ = ZoneInfo("UTC")
P = gates.P


@pytest.fixture(autouse=True)
def observations_cleared(ws):
    yield
    ws.session.rollback()
    ws.session.query(MetricContributionModel).delete(synchronize_session=False)
    ws.session.query(MetricObservationModel).delete(synchronize_session=False)
    ws.session.commit()


def _rows(ws, **filters):
    ws.session.expire_all()
    return ws.session.query(MetricObservationModel).filter_by(group_id=ws.gid, **filters).order_by(MetricObservationModel.window_start).all()


def _step(ws, dry_run=False, context=None, **fields):
    return run_metric_action(ws.session, ws.gid, {"kind": "metric", **fields}, context or {"steps": {}, "previous": {}}, dry_run=dry_run)


def _zone(ws, name: str):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=ws.session, group_id=ws.gid)
        ws.session.add(prefs)
    prefs.site_timezone = name
    ws.session.commit()


# ── Windows ───────────────────────────────────────────────────────────────────
def test_a_window_is_a_day_a_week_or_a_month_and_labels_round_trip():
    for label, granularity, start in (
        ("2026-10-18", "day", date(2026, 10, 18)),
        ("2026-W42", "week", date(2026, 10, 12)),  # an ISO week starts on its Monday
        ("2026-10", "month", date(2026, 10, 1)),
    ):
        w = metrics.parse_window(label)
        assert (w.granularity, w.start, w.label) == (granularity, start, label)


@pytest.mark.parametrize("bad", ["", "tomorrow", "2026-13", "2026-02-30", "2026-W54", "2026-W00", "26-10-18", "2026-10-18T10:00"])
def test_a_window_that_isnt_one_is_refused(bad):
    with pytest.raises(metrics.MetricError):
        metrics.parse_window(bad)


def test_the_window_a_run_falls_in_is_read_in_the_workspace_zone_across_a_clock_change():
    def day(at, zone=NY, spec="day"):
        return metrics.window_for(spec, zone, at=at).label

    # Clocks go back on 2026-11-01 (EDT → EST), forward on 2026-03-08 (EST → EDT).
    assert day("2026-11-02T04:30:00Z") == "2026-11-01"  # 23:30 EST on the 1st; UTC already says the 2nd
    assert day("2026-11-02T05:30:00Z") == "2026-11-02"  # 00:30 EST
    assert day("2026-11-01T05:30:00Z") == "2026-11-01"  # 01:30 EDT, the repeated hour's first pass
    assert day("2026-11-01T06:30:00Z") == "2026-11-01"  # 01:30 EST, its second
    assert day("2026-03-09T03:30:00Z") == "2026-03-08"  # 23:30 EDT on the 8th
    assert day("2026-03-09T04:30:00Z") == "2026-03-09"  # 00:30 EDT
    assert day("2026-03-09T03:30:00Z", UTC_) == "2026-03-09"  # the same instant in UTC: another day
    # The month and the week follow the local day, not UTC's.
    assert day("2026-11-01T03:59:00Z", NY, "month") == "2026-10"  # 23:59 EDT on Oct 31
    assert day("2026-11-01T04:00:00Z", NY, "month") == "2026-11"


def test_a_week_is_monday_to_sunday_and_follows_the_iso_year():
    assert metrics.window_for("week", NY, at="2026-10-19T03:59:00Z").label == "2026-W42"  # Sunday 23:59 EDT the 18th
    assert metrics.window_for("week", NY, at="2026-10-19T04:00:00Z").label == "2026-W43"  # Monday 00:00 EDT the 19th
    assert metrics.window_for("week", UTC_, at="2026-10-19T03:59:00Z").label == "2026-W43"  # UTC has already turned over
    # 2026-W01 starts on Monday 2025-12-29: late December can be a week of the next year, early January of the last.
    assert metrics.window_for("week", NY, at="2025-12-31").label == "2026-W01"
    assert metrics.window_for("week", NY, at="2027-01-01").label == "2026-W53"
    assert metrics.window_for("week", NY, at="2026-01-01").start == date(2025, 12, 29)


def test_a_local_time_without_a_zone_is_already_local_and_a_date_is_a_date():
    assert metrics.local_day("2026-11-01T23:30:00", NY) == date(2026, 11, 1)
    assert metrics.local_day("2026-11-01", Zone := NY) == date(2026, 11, 1) and Zone
    assert metrics.local_day(datetime(2026, 11, 2, 4, 30, tzinfo=UTC), NY) == date(2026, 11, 1)
    assert metrics.local_day(None, NY, now=datetime(2026, 11, 2, 4, 30, tzinfo=UTC)) == date(2026, 11, 1)
    for bad in ("soon", "2026-02-30"):
        with pytest.raises(metrics.MetricError):
            metrics.local_day(bad, NY)


def test_an_explicit_window_ignores_the_run_time():
    assert metrics.window_for("2026-W42", NY, at="2020-01-01").label == "2026-W42"
    assert metrics.window_for(None, NY, at="2026-10-18").label == "2026-10-18"  # day is the default


def test_values_and_names_are_cleaned():
    assert metrics.clean_value("1,250.5") == 1250.5 and metrics.clean_value(3) == 3.0 and metrics.clean_value(" 7 ") == 7.0
    for bad in ("many", "", None, True, float("nan"), float("inf"), "inf"):
        with pytest.raises(metrics.MetricError):
            metrics.clean_value(bad)
    assert metrics.clean_metric(" clicks-per_day2 ") == "clicks-per_day2"
    for bad in ("", "Clicks", "-x", "has space", "x" * 65, None):
        with pytest.raises(metrics.MetricError):
            metrics.clean_metric(bad)
    with pytest.raises(metrics.MetricError):
        metrics.clean_label("x" * 101, "variant")


# ── The step: record ──────────────────────────────────────────────────────────
def test_recording_writes_one_observation_and_says_what_it_did(ws):
    out = _step(ws, metric="clicks", value=12, variant="a", window="2026-W42", subject="spring-post")
    assert out["recorded"] and out["created"] and out["changed"] and out["previous_value"] is None
    assert (out["window"], out["granularity"], out["value"]) == ("2026-W42", "week", 12.0)
    (row,) = _rows(ws)
    assert (row.metric, row.variant, row.subject, row.window_label, row.value, row.window_start) == (
        "clicks", "a", "spring-post", "2026-W42", 12.0, date(2026, 10, 12),
    )  # fmt: skip


def test_recording_the_same_key_again_replaces_the_value_and_never_double_counts(ws):
    first = _step(ws, metric="clicks", value=12, variant="a", window="2026-10-18")
    again = _step(ws, metric="clicks", value=12, variant="a", window="2026-10-18")
    assert first["created"] and not again["created"] and not again["changed"]  # a rerun with the same number: nothing to save
    (row,) = _rows(ws)
    updated = row.update_at
    revised = _step(ws, metric="clicks", value=15, variant="a", window="2026-10-18")
    assert revised["changed"] and not revised["created"] and revised["previous_value"] == 12.0
    (row,) = _rows(ws)
    assert row.value == 15.0 and row.update_at >= updated  # replaced, not added: still one row, 15 not 27


def test_each_variant_subject_window_and_metric_is_its_own_observation(ws):
    for variant in ("a", "b", ""):
        _step(ws, metric="clicks", value=1, variant=variant, window="2026-10-18")
    _step(ws, metric="clicks", value=1, variant="a", window="2026-10-19")
    _step(ws, metric="clicks", value=1, variant="a", window="2026-10-18", subject="other")
    _step(ws, metric="opens", value=1, variant="a", window="2026-10-18")
    _step(ws, metric="clicks", value=1, variant="a", window="2026-W42")  # a week and a day never merge
    assert len(_rows(ws)) == 7


def test_a_template_gives_the_value_the_variant_and_the_window(ws):
    ctx = {
        "steps": {},
        "previous": {},
        "input": {"clicks": "1,204", "which": "b"},
        "entry": {"slug": "spring", "published_at": "2026-11-02T04:30:00Z"},
    }
    out = _step(
        ws,
        context=ctx,
        metric="clicks",
        value="${input.clicks}",
        variant="${input.which}",
        subject="${entry.slug}",
        window="week",
        at="${entry.published_at}",
    )
    assert (out["value"], out["variant"], out["subject"], out["window"]) == (1204.0, "b", "spring", "2026-W44")  # 23:30 Sun Nov 1 in New York


def test_a_run_with_no_window_named_uses_the_day_it_runs_in_the_workspace_zone(ws):
    _zone(ws, "Pacific/Auckland")  # a day ahead of New York for most of the year
    out = _step(ws, metric="clicks", value=1)
    assert out["window"] == datetime.now(UTC).astimezone(ZoneInfo("Pacific/Auckland")).date().isoformat()


def test_the_workspace_zone_decides_the_window(ws):
    _zone(ws, "America/New_York")
    assert _step(ws, metric="m", value=1, window="day", at="2026-11-02T04:30:00Z")["window"] == "2026-11-01"
    _zone(ws, "UTC")
    assert _step(ws, metric="m", value=1, window="day", at="2026-11-02T04:30:00Z")["window"] == "2026-11-02"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"metric": "Bad Name", "value": 1}, "metric 'Bad Name'"),
        ({"metric": "clicks", "value": "lots"}, "isn't a number"),
        ({"metric": "clicks", "value": 1, "window": "yesterday"}, "window 'yesterday'"),
        ({"metric": "clicks", "value": 1, "window": "2026-02-30"}, "isn't a real"),
        ({"metric": "clicks", "value": 1, "at": "soon"}, "isn't a date"),
        ({"metric": "clicks", "value": 1, "at": "${entry.nothing}"}, "at resolved to empty"),
        ({"metric": "clicks", "value": 1, "variant": "x" * 101}, "variant is longer"),
        ({"metric": "${input.none}", "value": 1}, "metric ''"),
    ],
)
def test_what_cant_be_recorded_fails_the_step_with_the_reason(ws, fields, message):
    with pytest.raises(AutomationActionError, match=message):
        _step(ws, **fields)
    assert _rows(ws) == []


def test_an_empty_value_fails_a_real_run(ws):
    with pytest.raises(AutomationActionError, match="isn't a number"):
        _step(ws, metric="clicks", value="${input.clicks}", context={"steps": {}, "previous": {}, "input": {}})


def test_a_workspace_stops_recording_new_windows_at_the_cap_but_keeps_updating_old_ones(ws, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_PER_WORKSPACE", 2)
    _step(ws, metric="m", value=1, window="2026-10-01")
    _step(ws, metric="m", value=1, window="2026-10-02")
    with pytest.raises(AutomationActionError, match="the most it keeps"):
        _step(ws, metric="m", value=1, window="2026-10-03")
    assert _step(ws, metric="m", value=9, window="2026-10-02")["changed"]


def test_two_runs_recording_the_same_new_key_at_once_leave_one_row(ws, monkeypatch):
    """The second writer loses the race for the insert, then updates what the first one wrote."""
    window = metrics.parse_window("2026-10-18")
    real = metrics.existing
    calls = {"n": 0}

    def late(*a, **k):  # the first lookup (before the insert) sees nothing, as if the other run hadn't committed yet
        calls["n"] += 1
        if calls["n"] == 1:
            metrics.record(ws.session, ws.gid, metric="m", value=1, variant="", subject="", window=window)
            return None
        return real(*a, **k)

    monkeypatch.setattr(metrics, "existing", late)
    _, previous, changed = metrics.record(ws.session, ws.gid, metric="m", value=2, variant="", subject="", window=window)
    assert (previous, changed) == (1.0, True)
    assert [r.value for r in _rows(ws)] == [2.0]


# ── Dry run ───────────────────────────────────────────────────────────────────
def test_a_dry_run_previews_and_writes_nothing(ws):
    new = _step(ws, dry_run=True, metric="clicks", value=12, variant="a", window="2026-10-18")
    assert new["dry_run"] and new["would"] == "create" and new["value"] == 12.0 and new["previous_value"] is None
    assert _rows(ws) == []
    _step(ws, metric="clicks", value=12, variant="a", window="2026-10-18")
    assert _step(ws, dry_run=True, metric="clicks", value=12, variant="a", window="2026-10-18")["would"] == "leave"
    assert _step(ws, dry_run=True, metric="clicks", value=20, variant="a", window="2026-10-18")["would"] == "change"
    assert [r.value for r in _rows(ws)] == [12.0]


def test_a_dry_run_with_no_number_yet_previews_instead_of_failing(ws):
    for value in ("‹AI answer: clicks›", "", None):
        out = _step(ws, dry_run=True, metric="clicks", value=value, window="2026-10-18")
        assert out["dry_run"] and out["value"] is None and out["window"] == "2026-10-18", value
    with pytest.raises(AutomationActionError):
        _step(ws, dry_run=True, metric="clicks", value="lots")  # a number that is wrong is still wrong


# ── The step: add ─────────────────────────────────────────────────────────────
def _event(correlation="evt-1", index=0, step_id=None):
    return {
        "event": {"event_type": "member_added", "correlation_id": correlation},
        "steps": {},
        "previous": {},
        "_step": {"workflow": "wf-1", "index": index, "target": 0, "on_failure": False, "step_id": step_id},
    }


def _add(ws, correlation="evt-1", **fields):
    fields.setdefault("metric", "signups")
    fields.setdefault("window", "2026-10-18")
    return _step(ws, op="add", context=_event(correlation), **fields)


def _claims(ws):
    ws.session.expire_all()
    return ws.session.query(MetricContributionModel).filter_by(group_id=ws.gid).all()


def test_add_raises_the_windows_number_and_says_what_it_did(ws):
    first = _add(ws, "e1", value=5)
    assert first["recorded"] and first["counted"] and first["created"] and first["changed"]
    assert (first["value"], first["previous_value"], first["added"], first["window"]) == (5.0, 0.0, 5.0, "2026-10-18")
    second = _add(ws, "e2", value=2.5)
    assert not second["created"] and (second["value"], second["previous_value"], second["added"]) == (7.5, 5.0, 2.5)
    assert [r.value for r in _rows(ws)] == [7.5]


def test_add_counts_one_when_no_value_is_given(ws):
    assert _add(ws, "e1")["value"] == 1.0
    assert _add(ws, "e2", value="")["value"] == 2.0
    assert _add(ws, "e3", value=None)["added"] == 1.0
    assert [r.value for r in _rows(ws)] == [3.0]


def test_add_takes_a_negative_value_to_count_down_and_zero_changes_nothing(ws):
    _add(ws, "e1", value=3)
    down = _add(ws, "e2", value=-1)
    assert (down["value"], down["previous_value"], down["added"], down["changed"]) == (2.0, 3.0, -1.0, True)
    assert _add(ws, "e3", value="-0.5")["value"] == 1.5  # a number as text works, as it does for record
    zero = _add(ws, "e4", value=0)
    assert zero["value"] == 1.5 and zero["changed"] is False
    assert _add(ws, "e5", value=-4, window="2026-10-19")["value"] == -4.0  # a count can start below nothing


@pytest.mark.parametrize("bad", ["many", True, "${input.n}", "inf"])
def test_add_refuses_a_value_that_isnt_a_number_and_claims_nothing(ws, bad):
    with pytest.raises(AutomationActionError, match="number|finite"):
        _add(ws, "e1", value=bad)
    assert _rows(ws) == [] and _claims(ws) == []


def test_the_same_event_delivered_twice_adds_once_and_another_event_adds_again(ws):
    first = _add(ws, "evt-1", value=1)
    again = _add(ws, "evt-1", value=1)  # re-delivery, a retry, the same trigger run again
    assert first["counted"] and not again["counted"] and again["skipped"] and again["added"] == 0.0 and again["changed"] is False
    assert (again["value"], again["previous_value"]) == (1.0, 1.0)
    assert [r.value for r in _rows(ws)] == [1.0]
    assert _add(ws, "evt-2", value=1)["value"] == 2.0  # a distinct event counts
    assert _add(ws, "evt-1", value=1)["counted"] is False  # and the first is still counted
    assert [c.contribution_key for c in _claims(ws)].count("wf-1:0:evt-1:0:0") == 1


def test_a_claim_is_per_step_and_per_workflow_not_just_per_event(ws):
    assert _step(ws, op="add", metric="m", window="2026-10-18", context=_event("e", index=0))["counted"]
    assert _step(ws, op="add", metric="m", window="2026-10-18", context=_event("e", index=1))["counted"]  # another step
    other = _event("e")
    other["_step"]["workflow"] = "wf-2"
    assert _step(ws, op="add", metric="m", window="2026-10-18", context=other)["counted"]  # another workflow
    assert [r.value for r in _rows(ws)] == [3.0]


def test_a_run_with_no_event_identity_adds_every_time(ws):
    for _ in range(2):
        out = _step(ws, op="add", metric="m", window="2026-10-18", context={"steps": {}, "previous": {}, "event": {}})
        assert out["counted"]
    assert [r.value for r in _rows(ws)] == [2.0] and _claims(ws) == []


def _deliver_together(ws, keys, *, metric):
    """One session per key, all adding 1 to the same window at the same moment: their results (and any errors)."""
    import threading

    from sqlalchemy.orm import Session

    window, engine = metrics.parse_window("2026-10-18"), ws.session.get_bind()
    barrier, results, errors = threading.Barrier(len(keys)), [], []

    def deliver(key):
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                results.append(metrics.add(session, ws.gid, metric=metric, amount=1.0, variant="", subject="", window=window, key=key))
            except Exception as e:  # noqa: BLE001 — reported by the caller
                errors.append(e)

    threads = [threading.Thread(target=deliver, args=(key,)) for key in keys]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    assert errors == []
    return results


def test_two_sessions_delivering_the_same_event_at_once_add_it_once(ws):
    for round_ in range(5):
        results = _deliver_together(ws, [f"wf:0:race-{round_}:0:0"] * 2, metric="race")
        assert sorted(r.counted for r in results) == [False, True], round_
    (row,) = _rows(ws, metric="race")
    assert row.value == 5.0 and len(_claims(ws)) == 5  # five events, each once


def test_sessions_adding_different_events_to_one_new_window_lose_nothing(ws):
    _deliver_together(ws, [f"wf:0:busy-{n}:0:0" for n in range(4)], metric="busy")
    (row,) = _rows(ws, metric="busy")
    assert row.value == 4.0


def test_an_add_never_overwrites_a_number_another_session_just_raised(ws):
    """The new number is computed by the database (`value = value + :amount`), not read into Python and written back:
    a session holding a stale copy of the row still adds onto what is there. (SELECT ... FOR UPDATE, which SQLite ignores,
    was what protected this before.)"""
    from sqlalchemy.orm import Session

    window, engine = metrics.parse_window("2026-10-18"), ws.session.get_bind()

    def add(session, key):
        return metrics.add(session, ws.gid, metric="stale", amount=1.0, variant="", subject="", window=window, key=key)

    with Session(engine) as first, Session(engine) as second:
        add(first, "wf:0:stale-1:0:0")
        seen = metrics.existing(first, ws.gid, metric="stale", variant="", subject="", window=window)
        assert seen.value == 1.0  # `first` now holds the row at 1.0
        add(second, "wf:0:stale-2:0:0")  # another session takes it to 2.0
        out = add(first, "wf:0:stale-3:0:0")  # ...which `first` must add onto, not onto its copy
    assert (out.value, out.previous) == (3.0, 2.0)
    (row,) = _rows(ws, metric="stale")
    assert row.value == 3.0


def test_a_failed_write_releases_the_claim_so_a_retry_still_counts(ws, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_PER_WORKSPACE", 0)
    with pytest.raises(AutomationActionError, match="the most it keeps"):
        _add(ws, "evt-1", value=1)
    assert _claims(ws) == [] and _rows(ws) == []  # no claim left behind
    monkeypatch.undo()
    assert _add(ws, "evt-1", value=1)["counted"]  # the retry of the same event counts
    assert [r.value for r in _rows(ws)] == [1.0] and len(_claims(ws)) == 1


def test_a_failure_after_the_claim_is_taken_leaves_neither_claim_nor_number(ws, monkeypatch):
    real = ws.session.commit

    def boom():
        raise RuntimeError("database went away")

    monkeypatch.setattr(ws.session, "commit", boom)
    with pytest.raises(RuntimeError):
        _add(ws, "evt-1", value=1)
    monkeypatch.setattr(ws.session, "commit", real)
    assert _claims(ws) == [] and _rows(ws) == []
    assert _add(ws, "evt-1", value=1)["counted"]


def test_a_workspace_at_the_cap_still_adds_to_a_window_it_has(ws, monkeypatch):
    _add(ws, "e1", value=1)
    monkeypatch.setattr(metrics, "MAX_PER_WORKSPACE", 1)
    assert _add(ws, "e2", value=1)["value"] == 2.0
    with pytest.raises(AutomationActionError, match="the most it keeps"):
        _add(ws, "e3", value=1, window="2026-10-19")


def test_add_buckets_into_windows_like_record_does(ws):
    _add(ws, "e1", window="week", at="2026-10-14")  # a Wednesday
    _add(ws, "e2", window="week", at="2026-10-18")  # the Sunday of the same week
    _add(ws, "e3", window="week", at="2026-10-19")  # the next Monday
    _add(ws, "e4", window="month", at="2026-10-31")
    _add(ws, "e5", window="2026-W42", variant="b", subject="spring")
    got = {(r.window_label, r.variant, r.subject): r.value for r in _rows(ws)}
    assert got == {("2026-W42", "", ""): 2.0, ("2026-W43", "", ""): 1.0, ("2026-10", "", ""): 1.0, ("2026-W42", "b", "spring"): 1.0}
    _zone(ws, "America/New_York")
    out = _add(ws, "e6", window="day", at="2026-11-02T04:30:00Z")  # 23:30 on the 1st in New York
    assert out["window"] == "2026-11-01"


def test_add_and_record_share_a_window_record_replaces_what_add_counted(ws):
    _add(ws, "e1", value=4)
    assert _step(ws, metric="signups", value=10, window="2026-10-18")["previous_value"] == 4.0
    assert _add(ws, "e2", value=1)["value"] == 11.0


def test_add_in_a_dry_run_previews_and_writes_and_claims_nothing(ws):
    new = _step(ws, dry_run=True, op="add", metric="signups", window="2026-10-18", context=_event("e1"))
    assert new["dry_run"] and new["would"] == "add"
    assert (new["previous_value"], new["added"], new["value"]) == (0.0, 1.0, 1.0)
    assert _rows(ws) == [] and _claims(ws) == []
    _add(ws, "e1", value=5)
    more = _step(ws, dry_run=True, op="add", metric="signups", value=-2, window="2026-10-18", context=_event("e2"))
    assert more["would"] == "add" and (more["previous_value"], more["added"], more["value"]) == (5.0, -2.0, 3.0)
    again = _step(ws, dry_run=True, op="add", metric="signups", value=-2, window="2026-10-18", context=_event("e1"))
    assert again["would"] == "leave" and again["already_counted"] and again["value"] == 5.0  # this event is already in
    assert [r.value for r in _rows(ws)] == [5.0] and len(_claims(ws)) == 1


def test_add_in_a_dry_run_with_no_number_yet_previews_but_a_wrong_one_still_fails(ws):
    for value in ("‹AI answer: n›", "${input.n}"):
        out = _step(ws, dry_run=True, op="add", metric="signups", value=value, window="2026-10-18", context={**_event(), "input": {}})
        assert out["would"] == "add" and out["value"] is None, value
    with pytest.raises(AutomationActionError):
        _step(ws, dry_run=True, op="add", metric="signups", value="lots")


def test_clearing_a_window_starts_its_count_over(ws):
    _add(ws, "e1", value=3)
    (row,) = _rows(ws)
    assert metrics.remove(ws.session, ws.gid, row.id)
    assert _claims(ws) == []
    assert _add(ws, "e1", value=1)["value"] == 1.0


def test_the_model_reads_an_add_step_with_or_without_a_value():
    assert MetricAction.model_validate({"kind": "metric", "op": "add", "metric": "signups"}).op == "add"
    step = MetricAction.model_validate({"kind": "metric", "op": "add", "metric": "signups", "value": -2, "window": "week", "variant": "a"})
    assert step.value == -2


def test_the_editor_and_validator_refuse_an_add_step_that_cant_work(ws):
    steps = [
        {"kind": "metric", "op": "add", "metric": "Not A Slug"},
        {"kind": "metric", "op": "add", "metric": "signups", "value": "lots"},
        {"kind": "metric", "op": "add", "metric": "signups", "window": "yesterday"},
        {"kind": "metric", "op": "add", "metric": "signups", "limit": 5},
        {"kind": "metric", "op": "add", "metric": "signups", "window_from": "2026-W40"},
        {"kind": "metric", "op": "read", "metric": "signups", "value": 1},  # a read has no value
        {"kind": "metric", "op": "add", "metric": "signups"},  # fine: counts 1
        {"kind": "metric", "op": "add", "metric": "signups", "value": -1, "window": "week", "at": "${entry.published_at}"},  # fine
        {"kind": "metric", "op": "add", "metric": "signups", "value": "${input.n}", "variant": "${input.v}"},  # fine: templates
        {"kind": "metric", "op": "record", "metric": "signups", "value": ""},  # a record still needs its value
    ]
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": steps})
    paths = [str(i.get("path", "")) for i in issues]
    for index in (0, 1, 2, 3, 4, 5, 9):
        assert any(p.startswith(f"actions[{index}]") for p in paths), (index, issues)
    assert not any(p.startswith(("actions[6]", "actions[7]", "actions[8]")) for p in paths), issues


# ── The step: read ────────────────────────────────────────────────────────────
def _seed(ws):
    for window, variant, value in (("2026-W41", "a", 10), ("2026-W41", "b", 8), ("2026-W42", "a", 12), ("2026-W42", "b", 15.5), ("2026-W43", "a", 9)):
        _step(ws, metric="clicks", value=value, variant=variant, window=window, subject="spring")
    _step(ws, metric="clicks", value=3, variant="a", window="2026-W42", subject="winter")
    _step(ws, metric="opens", value=40, window="2026-W42")


def test_a_read_lists_observations_newest_first_without_drawing_conclusions(ws):
    _seed(ws)
    out = _step(ws, op="read", metric="clicks", subject="spring")
    assert (out["count"], out["total"]) == (5, 5)
    assert [(r["window"], r["variant"]) for r in out["rows"]] == [
        ("2026-W43", "a"),
        ("2026-W42", "a"),
        ("2026-W42", "b"),
        ("2026-W41", "a"),
        ("2026-W41", "b"),
    ]
    lines = out["text"].splitlines()
    assert lines[0] == "Observations, not conclusions:"
    assert "- 2026-W42 clicks (variant b · spring): 15.5" in lines and "- 2026-W43 clicks (variant a · spring): 9" in lines
    assert not any(word in out["text"].lower() for word in ("winner", "better", "significant", "because"))


def test_a_read_filters_by_variant_window_range_and_limit(ws):
    _seed(ws)
    assert [r["value"] for r in _step(ws, op="read", metric="clicks", subject="spring", variant="b")["rows"]] == [15.5, 8.0]
    ranged = _step(ws, op="read", metric="clicks", subject="spring", window_from="2026-W42", window_to="2026-W42")
    assert {r["window"] for r in ranged["rows"]} == {"2026-W42"} and ranged["count"] == 2
    day_bounds = _step(ws, op="read", metric="clicks", subject="spring", window_from="2026-10-13", window_to="2026-10-20")
    assert {r["window"] for r in day_bounds["rows"]} == {"2026-W43"}  # a week counts when it starts inside the range (W42 began the 12th)
    limited = _step(ws, op="read", metric="clicks", limit=2)
    assert (limited["count"], limited["total"]) == (2, 6)
    assert _step(ws, op="read", metric="nothing-yet") == {"metric": "nothing-yet", "count": 0, "total": 0, "rows": [], "text": "No observations."}


def test_a_read_filter_that_resolves_to_nothing_is_refused_rather_than_widened(ws):
    _seed(ws)
    with pytest.raises(AutomationActionError, match="subject resolved to empty"):
        _step(ws, op="read", metric="clicks", subject="${entry.slug}")  # no entry: don't report on every subject


def test_a_read_runs_in_a_dry_run_too(ws):
    _seed(ws)
    assert _step(ws, dry_run=True, op="read", metric="opens")["count"] == 1


# ── The definition ────────────────────────────────────────────────────────────
def test_the_model_reads_a_record_step_and_a_read_step():
    record = MetricAction.model_validate({"kind": "metric", "metric": "clicks", "value": "${input.n}", "variant": "a", "window": "week"})
    assert (record.op, record.window, record.limit) == ("record", "week", 50)
    read = MetricAction.model_validate({"kind": "metric", "op": "read", "metric": "clicks", "window_from": "2026-W40", "limit": 10})
    assert read.op == "read" and read.limit == 10


def test_the_editor_and_validator_refuse_a_metric_step_that_cant_work(ws):
    steps = [
        {"kind": "metric", "metric": "Not A Slug", "value": 1},
        {"kind": "metric", "metric": "clicks"},  # no value
        {"kind": "metric", "metric": "clicks", "value": "lots"},
        {"kind": "metric", "metric": "clicks", "value": 1, "window": "yesterday"},
        {"kind": "metric", "metric": "clicks", "op": "read", "value": 3},
        {"kind": "metric", "metric": "clicks", "op": "read", "window_from": "soon"},
        {"kind": "metric", "metric": "clicks", "value": 1, "limit": 5},
        {"kind": "metric", "metric": "clicks", "value": "${input.n}", "window": "${input.w}", "variant": "a"},  # fine: templates
        {"kind": "metric", "metric": "clicks", "value": "3", "window": "2026-W42"},  # fine
        {"kind": "metric", "metric": "clicks", "op": "read", "window_from": "2026-W40", "window_to": "${input.to}"},  # fine
    ]
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": steps})
    paths = [str(i.get("path", "")) for i in issues]
    for index in range(7):
        assert any(p.startswith(f"actions[{index}]") for p in paths), (index, issues)
    assert not any(p.startswith(("actions[7]", "actions[8]", "actions[9]")) for p in paths), issues


def test_a_metric_step_can_sit_inside_a_repeat(ws):
    step = {"kind": "metric", "metric": "clicks", "value": "${each.number}", "variant": "${each.number}"}
    definition = {
        "trigger": {"type": "manual"},
        "actions": [{"kind": "repeat", "for_each": "x, y", "as": "item", "steps": [step]}],
    }
    assert draft_issues(ws.session, ws.gid, definition) == []


# ── In a run ──────────────────────────────────────────────────────────────────
def _workflow(ws, actions, inputs=None):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    wf = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name="Scoreboard",
        slug=f"scoreboard-{uuid.uuid4().hex[:8]}",
        enabled=True,
        definition={"trigger": {"type": "manual", "inputs": inputs or []}, "actions": actions},
    )
    ws.session.add(wf)
    ws.session.commit()

    def run(*, dry_run=False, **given):
        return run_automation_now(
            ws.session, ws.gid, wf, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), dry_run=dry_run, inputs=given
        )

    return wf, run


def test_a_workflow_records_twice_for_the_same_window_without_double_counting_and_a_dry_run_writes_nothing(ws):
    wf, run = _workflow(
        ws,
        [
            {"kind": "metric", "id": "a", "metric": "clicks", "value": "${input.a}", "variant": "a", "window": "2026-W42"},
            {"kind": "metric", "id": "b", "metric": "clicks", "value": "${input.b}", "variant": "b", "window": "2026-W42"},
            {"kind": "metric", "id": "report", "op": "read", "metric": "clicks", "window_from": "2026-W42"},
        ],
        inputs=[{"name": "a", "type": "number"}, {"name": "b", "type": "number"}],
    )
    preview = run(dry_run=True, a=10, b=8)
    assert preview["ok"] and [p["resolved"].get("would") for p in preview["plan"][:2]] == ["create", "create"]
    assert _rows(ws) == []  # nothing written
    assert preview["plan"][2]["resolved"]["count"] == 0

    first = run(a=10, b=8)
    assert first["ok"] and sorted(r.value for r in _rows(ws)) == [8.0, 10.0]
    assert first["result"]["count"] == 2 and first["result"]["text"].startswith("Observations, not conclusions:")
    assert all(r.automation_id == wf.id for r in _rows(ws))  # the workflow is remembered as the source

    second = run(a=10, b=8)  # the same run again: the same two numbers
    assert second["ok"] and sorted(r.value for r in _rows(ws)) == [8.0, 10.0]
    assert [p["resolved"].get("would") for p in run(dry_run=True, a=10, b=9)["plan"][:2]] == ["leave", "change"]

    third = run(a=11, b=8)  # a new reading of the same window replaces it
    assert third["ok"] and sorted(r.value for r in _rows(ws)) == [8.0, 11.0]


def test_deleting_the_workflow_keeps_what_it_recorded(ws):
    wf, run = _workflow(ws, [{"kind": "metric", "metric": "clicks", "value": 1, "window": "2026-W42"}])
    assert run()["ok"]
    ws.session.delete(wf)
    ws.session.commit()
    (row,) = _rows(ws)
    assert row.automation_id is None and row.value == 1.0


# ── The API ───────────────────────────────────────────────────────────────────
def _client(ws, role):
    return gates._sign_in(ws.workspace, role)


def _api_seed(ws):
    _seed(ws)


def test_the_api_lists_observations_with_filters_newest_first_and_says_what_they_are(ws):
    _api_seed(ws)
    client = _client(ws, WorkspaceRole.EDITOR)
    body = client.get("/api/groups/metrics/observations", params={"metric": "clicks", "subject": "spring", "variant": "a"}).json()
    assert body["total"] == 3 and [i["window"] for i in body["items"]] == ["2026-W43", "2026-W42", "2026-W41"]
    assert "not conclusions" in body["note"]
    item = body["items"][0]
    assert (item["metric"], item["variant"], item["subject"], item["granularity"], item["windowStart"], item["value"]) == (
        "clicks", "a", "spring", "week", "2026-10-19", 9.0,
    )  # fmt: skip

    ranged = client.get("/api/groups/metrics/observations", params={"metric": "clicks", "window_from": "2026-W42", "window_to": "2026-W42"}).json()
    assert ranged["total"] == 3 and {i["window"] for i in ranged["items"]} == {"2026-W42"}
    assert client.get("/api/groups/metrics/observations", params={"variant": ""}).json()["total"] == 1  # only the one with no variant
    paged = client.get("/api/groups/metrics/observations", params={"limit": 2, "offset": 2}).json()
    assert paged["total"] == 7 and len(paged["items"]) == 2 and paged["offset"] == 2
    assert client.get("/api/groups/metrics/observations", params={"window_from": "someday"}).status_code == 422


def test_the_api_names_the_metrics_recorded(ws):
    _api_seed(ws)
    names = _client(ws, WorkspaceRole.EDITOR).get("/api/groups/metrics").json()
    assert [(m["metric"], m["count"], m["firstWindow"], m["lastWindow"]) for m in names] == [
        ("clicks", 6, "2026-10-05", "2026-10-19"),
        ("opens", 1, "2026-10-12", "2026-10-12"),
    ]


def test_the_api_names_the_workflow_that_recorded_an_observation(ws):
    wf, run = _workflow(ws, [{"kind": "metric", "metric": "clicks", "value": 1, "window": "2026-W42"}])
    assert run()["ok"]
    (item,) = _client(ws, WorkspaceRole.EDITOR).get("/api/groups/metrics/observations").json()["items"]
    assert (item["workflowName"], item["workflowSlug"]) == ("Scoreboard", wf.slug)


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, None])
def test_below_editor_cannot_read_observations(ws, role):
    _api_seed(ws)
    client = _client(ws, role)
    refused = 409 if role is None else 403  # a non-member is in no workspace at all: 409 no_workspace
    assert client.get("/api/groups/metrics").status_code == refused
    assert client.get("/api/groups/metrics/observations").status_code == refused


def test_only_an_admin_removes_an_observation(ws):
    _step(ws, metric="clicks", value=1, window="2026-10-18")
    (row,) = _rows(ws)
    path = f"/api/groups/metrics/observations/{row.id}"
    assert _client(ws, WorkspaceRole.EDITOR).delete(path).status_code == 403
    assert len(_rows(ws)) == 1
    admin = _client(ws, WorkspaceRole.ADMIN)
    assert admin.delete(path).status_code == 204 and _rows(ws) == []
    assert admin.delete(path).status_code == 404
    assert _step(ws, metric="clicks", value=1, window="2026-10-18")["created"]  # recorded afresh


def test_another_workspaces_observations_are_invisible_and_cant_be_removed(ws):
    from marvin.db.models.groups import Groups

    other = Groups(session=ws.session, name=f"other-{uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:6]}")
    ws.session.add(other)
    ws.session.commit()
    try:
        window = metrics.parse_window("2026-10-18")
        row, _, _ = metrics.record(ws.session, other.id, metric="secret", value=1, variant="", subject="", window=window)
        _step(ws, metric="mine", value=2, window="2026-10-18")
        admin = _client(ws, WorkspaceRole.ADMIN)
        assert [m["metric"] for m in admin.get("/api/groups/metrics").json()] == ["mine"]
        assert [i["metric"] for i in admin.get("/api/groups/metrics/observations").json()["items"]] == ["mine"]
        assert admin.delete(f"/api/groups/metrics/observations/{row.id}").status_code == 404
        # The same key in two workspaces is two observations.
        metrics.record(ws.session, other.id, metric="mine", value=5, variant="", subject="", window=window)
        assert [r.value for r in _rows(ws, metric="mine")] == [2.0]
    finally:
        ws.session.rollback()
        ws.session.query(MetricObservationModel).filter_by(group_id=other.id).delete()
        ws.session.delete(other)
        ws.session.commit()
