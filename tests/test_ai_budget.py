"""A workspace's AI limits: one set of numbers for the gate, the warnings and the usage card.

Regressions: the monthly cost limit could only be set through the API (the settings form had no field,
and saving the form dropped it); workflow AI steps skipped the limits and the warnings entirely; and
nothing showed how close a workspace was to a limit.
"""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.services.ai import budget
from marvin.services.ai.agents import operation_label

NOW = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"bud-{gid.hex[:8]}", slug=f"bud-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    yield gid
    db_session.query(AIExecutionModel).filter_by(group_id=gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _limits(db_session, gid, **cfg):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, budget_config=cfg))
    db_session.commit()


def _run(db_session, gid, *, op="generate-summary", cost=0.0, tokens=0, status="completed", at=NOW):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    row = AIExecutionModel(
        session=db_session,
        group_id=gid,
        operation_slug=op,
        provider_type="openai",
        model_id="m",
        status=status,
        trigger_type="api",
        estimated_cost_usd=cost,
        total_tokens=tokens,
    )
    row.created_at = at
    db_session.add(row)
    db_session.commit()
    return row


# --- limits and levels ------------------------------------------------------------------------------


def test_missing_bad_or_non_positive_limits_mean_no_limit():
    assert budget.limits_for({"max_cost_per_month_usd": "abc", "max_requests_per_day": 0, "max_tokens_per_request": -5}) == budget.Limits()
    assert budget.limits_for({"max_cost_per_month_usd": "12.5", "max_requests_per_day": "100"}) == budget.Limits(12.5, 100, None)


@pytest.mark.parametrize(
    ("spent", "runs", "level"),
    [(1.0, 0, budget.LEVEL_OK), (8.0, 0, budget.LEVEL_WARN), (10.0, 0, budget.LEVEL_OVER), (0.0, 50, budget.LEVEL_OVER)],
)
def test_the_level_is_the_worst_of_the_two_limits(spent, runs, level):
    usage = budget.Usage(limits=budget.Limits(month_usd=10.0, per_day=50), warning_percent=80.0, month_cost_usd=spent, today_runs=runs)

    assert usage.level == level


def test_without_limits_the_level_is_ok_and_there_is_no_percent():
    usage = budget.Usage(limits=budget.Limits(), warning_percent=80.0, month_cost_usd=999.0)

    assert usage.level == budget.LEVEL_OK and usage.month_percent is None


# --- the gate ---------------------------------------------------------------------------------------


def test_a_run_is_refused_once_the_month_is_spent(db_session, workspace):
    _limits(db_session, workspace, max_cost_per_month_usd=1.0)
    _run(db_session, workspace, cost=0.6, at=NOW)
    _run(db_session, workspace, cost=5.0, at=datetime(2026, 9, 30, tzinfo=UTC))  # last month doesn't count
    _run(db_session, workspace, cost=5.0, status="failed", at=NOW)  # nor a failed run
    assert budget.blocked_reason(db_session, workspace, NOW) is None

    _run(db_session, workspace, cost=0.4, at=NOW)

    assert budget.blocked_reason(db_session, workspace, NOW) == "Monthly cost limit ($1.00) reached."


def test_a_run_is_refused_once_the_day_is_used_up(db_session, workspace):
    _limits(db_session, workspace, max_requests_per_day=2)
    _run(db_session, workspace, status="failed", at=NOW)
    _run(db_session, workspace, at=NOW)

    assert budget.blocked_reason(db_session, workspace, NOW) == "Daily request limit (2) reached."


def test_the_token_cap_falls_back_to_the_app_default(db_session, workspace, monkeypatch):
    monkeypatch.setattr("marvin.core.config.get_app_settings", lambda: SimpleNamespace(AI_DEFAULT_MAX_TOKENS=999))
    assert budget.max_output_tokens(db_session, workspace) == 999

    _limits(db_session, workspace, max_tokens_per_request=256)

    assert budget.max_output_tokens(db_session, workspace) == 256


# --- warnings ---------------------------------------------------------------------------------------


def test_the_run_that_crosses_the_warning_line_announces_it_once(db_session, workspace):
    _limits(db_session, workspace, max_cost_per_month_usd=10.0)
    _run(db_session, workspace, cost=7.0, at=datetime.now(UTC))
    crossing_run = _run(db_session, workspace, cost=1.5, at=datetime.now(UTC))

    crossing = budget.crossing_after(db_session, workspace, crossing_run.estimated_cost_usd)
    assert crossing is not None and not crossing.exceeded and crossing.percent == 85.0

    later = _run(db_session, workspace, cost=0.5, at=datetime.now(UTC))
    assert budget.crossing_after(db_session, workspace, later.estimated_cost_usd) is None


def test_the_run_that_reaches_the_limit_says_so(db_session, workspace):
    _limits(db_session, workspace, max_cost_per_month_usd=10.0)
    _run(db_session, workspace, cost=9.0, at=datetime.now(UTC))
    last = _run(db_session, workspace, cost=2.0, at=datetime.now(UTC))

    crossing = budget.crossing_after(db_session, workspace, last.estimated_cost_usd)

    assert crossing.exceeded and crossing.detail == "Monthly AI cost limit of $10.00 reached (spent $11.00)"


# --- the usage card ---------------------------------------------------------------------------------


def test_usage_ranks_operations_by_cost_and_merges_the_old_bare_agent_slug(db_session, workspace):
    _limits(db_session, workspace, max_cost_per_month_usd=10.0, max_requests_per_day=100)
    _run(db_session, workspace, op="agent", cost=0.2, tokens=1000)
    _run(db_session, workspace, op="agent:marvin", cost=0.3, tokens=2000)
    _run(db_session, workspace, op="generate-summary", cost=0.1, tokens=500)

    u = budget.usage(db_session, workspace, NOW)

    assert [(o["operation"], o["runs"], o["tokens"]) for o in u.by_operation] == [("agent:marvin", 2, 3000), ("generate-summary", 1, 500)]
    assert (u.month_runs, u.month_tokens, u.today_runs, u.month_percent, u.day_percent) == (3, 3500, 3, 6.0, 3.0)
    assert u.resets_on == date(2026, 11, 1)


def test_december_resets_on_the_first_of_january():
    assert budget._next_month(datetime(2026, 12, 31, tzinfo=UTC)) == date(2027, 1, 1)


# --- workflows spend from the same budget -----------------------------------------------------------


def test_a_workflow_ai_step_is_refused_over_budget(monkeypatch):
    from marvin.services.automation import runner
    from marvin.services.automation.authz import ROLE_OWNER
    from marvin.services.automation.runner import AutomationActionError

    monkeypatch.setattr(runner, "_gate_source", lambda *a, **k: None)
    monkeypatch.setattr(runner, "get_operation", lambda slug: SimpleNamespace(slug=slug, min_role=2, invocation_sources=("automation",)))
    monkeypatch.setattr(budget, "blocked_reason", lambda s, g: "Monthly cost limit ($1.00) reached.")

    with pytest.raises(AutomationActionError, match=r"AI budget: Monthly cost limit \(\$1.00\) reached."):
        runner.run_operation_action(
            None,
            "G",
            {"kind": "operation", "op": "generate-summary"},
            {"event": {"entry_id": str(uuid.uuid4())}, "depth": 0},
            authorizer_role=ROLE_OWNER,
        )


# --- the agent's name in history ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "label"),
    [
        ("agent", "agent:Sunny"),  # the bubble's old bare slug is the main agent
        ("agent:marvin", "agent:Sunny"),
        ("agent:shop-assistant", "agent:Shop Assistant"),
        ("agent:gone", "agent:gone"),  # a deleted agent keeps its slug
        ("generate-summary", "generate-summary"),
    ],
)
def test_an_agent_run_reads_as_the_agents_current_name(slug, label):
    assert operation_label(slug, {"marvin": "Sunny", "shop-assistant": "Shop Assistant"}) == label
