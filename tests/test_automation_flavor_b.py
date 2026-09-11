"""Unit tests for Flavor B — user-configurable orchestration (event → conditions → actions).

Covers the three pure/near-pure pieces of the engine:
 - the matcher (condition ops + $event/$previous interpolation),
 - the AutomationReactionListener trigger gate (incl. the loop-guard),
 - the engine's orchestration (trigger match, conditions, pipeline threading, skips) with a fake
   session + injected action runner, so no AI provider or real DB rows are needed.

The migration + model registration are exercised implicitly: conftest builds the whole schema by
running Alembic to head, so a broken workspace_automations migration would fail collection.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from marvin.services.automation import engine, matcher
from marvin.services.automation.runner import AutomationActionError
from marvin.services.event_bus_service.event_bus_listener import AutomationReactionListener
from marvin.services.event_bus_service.event_types import EventTypes


# ── Matcher: interpolation ────────────────────────────────────────────────────
class TestInterpolate:
    def test_whole_string_event_template_resolves_raw_value(self):
        ctx = {"event": {"entry_id": "abc"}, "previous": {}}
        assert matcher.interpolate("$event.entry_id", ctx) == "abc"

    def test_previous_template_resolves(self):
        ctx = {"event": {}, "previous": {"summary": "a tidy summary"}}
        assert matcher.interpolate("$previous.summary", ctx) == "a tidy summary"

    def test_non_template_string_passes_through(self):
        assert matcher.interpolate("literal", {"event": {}}) == "literal"

    def test_unknown_reference_is_none(self):
        assert matcher.interpolate("$event.missing", {"event": {}}) is None

    def test_nested_dict_and_list_are_recursed(self):
        ctx = {"event": {"entry_id": "e1"}, "previous": {"tags": ["x"]}}
        out = matcher.interpolate({"id": "$event.entry_id", "keep": [1, "$previous.tags"]}, ctx)
        assert out == {"id": "e1", "keep": [1, ["x"]]}


# ── Matcher: conditions ───────────────────────────────────────────────────────
class TestMatches:
    def _ctx(self, entry_type="recipe", status="published"):
        return {"event": {"event_type": "entry_published"}, "entry": {"entry_type": entry_type, "status": status}, "previous": {}}

    def test_no_conditions_always_match(self):
        assert matcher.matches(None, self._ctx()) is True
        assert matcher.matches([], self._ctx()) is True

    def test_eq_matches_and_misses(self):
        conds = [{"field": "entry.entry_type", "op": "eq", "value": "recipe"}]
        assert matcher.matches(conds, self._ctx(entry_type="recipe")) is True
        assert matcher.matches(conds, self._ctx(entry_type="article")) is False

    def test_neq(self):
        conds = [{"field": "entry.status", "op": "neq", "value": "draft"}]
        assert matcher.matches(conds, self._ctx(status="published")) is True
        assert matcher.matches(conds, self._ctx(status="draft")) is False

    def test_contains(self):
        ctx = {"entry": {"title": "Waxed Canvas Care"}}
        assert matcher.matches([{"field": "entry.title", "op": "contains", "value": "Canvas"}], ctx) is True
        assert matcher.matches([{"field": "entry.title", "op": "contains", "value": "Leather"}], ctx) is False

    def test_exists(self):
        ctx = {"entry": {"entry_type": "recipe"}}
        assert matcher.matches([{"field": "entry.entry_type", "op": "exists"}], ctx) is True
        assert matcher.matches([{"field": "entry.missing", "op": "exists"}], ctx) is False
        # `value: false` inverts to must-not-exist
        assert matcher.matches([{"field": "entry.missing", "op": "exists", "value": False}], ctx) is True

    def test_all_conditions_are_anded(self):
        conds = [
            {"field": "entry.entry_type", "op": "eq", "value": "recipe"},
            {"field": "entry.status", "op": "eq", "value": "published"},
        ]
        assert matcher.matches(conds, self._ctx("recipe", "published")) is True
        assert matcher.matches(conds, self._ctx("recipe", "draft")) is False

    def test_unknown_operator_fails_closed(self):
        assert matcher.matches([{"field": "entry.entry_type", "op": "regex", "value": ".*"}], self._ctx()) is False


# ── H3: expression ergonomics ─────────────────────────────────────────────────
class TestEmbeddedInterpolation:
    _ctx = {"event": {"count": 5}, "previous": {"summary": "tidy"}, "steps": {"0": {"output": {"tags": ["leather"]}}, "tagger": {"output": {"n": 3}}}}

    def test_embedded_braces_stringify(self):
        assert matcher.interpolate("Summary: ${previous.summary}!", self._ctx) == "Summary: tidy!"

    def test_whole_braced_preserves_type(self):
        assert matcher.interpolate("${event.count}", self._ctx) == 5  # int, not "5"

    def test_step_output_by_index_and_id(self):
        assert matcher.interpolate("${steps.0.output.tags}", self._ctx) == ["leather"]
        assert matcher.interpolate("${steps.tagger.output.n}", self._ctx) == 3

    def test_unknown_embedded_ref_is_empty(self):
        assert matcher.interpolate("x=${event.missing}", self._ctx) == "x="

    def test_bare_dollar_still_works(self):
        assert matcher.interpolate("$previous.summary", self._ctx) == "tidy"


class TestOperators:
    _ctx = {
        "entry": {"status": "published", "title": "Waxed Canvas"},
        "event": {"changed_fields": ["status"], "before": {"status": "draft"}, "after": {"status": "published"}},
    }

    def test_in_list_and_csv(self):
        assert matcher.matches([{"field": "entry.status", "op": "in", "value": ["draft", "published"]}], self._ctx)
        assert matcher.matches([{"field": "entry.status", "op": "in", "value": "draft, published"}], self._ctx)
        assert not matcher.matches([{"field": "entry.status", "op": "in", "value": "draft, needs_review"}], self._ctx)

    def test_starts_with(self):
        assert matcher.matches([{"field": "entry.title", "op": "starts_with", "value": "Waxed"}], self._ctx)
        assert not matcher.matches([{"field": "entry.title", "op": "starts_with", "value": "Oiled"}], self._ctx)

    def test_changed_family(self):
        assert matcher.matches([{"field": "entry.status", "op": "changed"}], self._ctx)
        assert matcher.matches([{"field": "entry.status", "op": "changed_to", "value": "published"}], self._ctx)
        assert matcher.matches([{"field": "entry.status", "op": "changed_from", "value": "draft"}], self._ctx)
        assert not matcher.matches([{"field": "entry.title", "op": "changed"}], self._ctx)  # title didn't change


class TestConditionGroups:
    def _ctx(self, status="published", etype="recipe"):
        return {"entry": {"status": status, "entry_type": etype}}

    def test_any_or(self):
        c = {"any": [{"field": "entry.status", "op": "eq", "value": "draft"}, {"field": "entry.status", "op": "eq", "value": "published"}]}
        assert matcher.matches(c, self._ctx("published"))
        assert not matcher.matches(c, self._ctx("archived"))

    def test_not(self):
        c = {"not": {"field": "entry.status", "op": "eq", "value": "draft"}}
        assert matcher.matches(c, self._ctx("published"))
        assert not matcher.matches(c, self._ctx("draft"))

    def test_nested_all_any(self):
        c = {
            "all": [
                {"field": "entry.entry_type", "op": "eq", "value": "recipe"},
                {
                    "any": [
                        {"field": "entry.status", "op": "eq", "value": "published"},
                        {"field": "entry.status", "op": "eq", "value": "needs_review"},
                    ]
                },
            ]
        }
        assert matcher.matches(c, self._ctx("needs_review", "recipe"))
        assert not matcher.matches(c, self._ctx("draft", "recipe"))
        assert not matcher.matches(c, self._ctx("published", "article"))


# ── Listener: trigger gate + loop-guard ───────────────────────────────────────
class TestListenerGate:
    def _listener(self):
        return AutomationReactionListener(group_id=uuid4())

    def test_entry_lifecycle_events_trigger(self):
        for et in (EventTypes.entry_created, EventTypes.entry_updated, EventTypes.entry_published, EventTypes.entry_deleted):
            event = SimpleNamespace(event_type=et, reaction_depth=0)
            assert self._listener().get_subscribers(event) == ["automation"]

    def test_non_lifecycle_events_do_not_trigger(self):
        for et in (EventTypes.webhook_triggered, EventTypes.scheduled_task_created):
            event = SimpleNamespace(event_type=et, reaction_depth=0)
            assert self._listener().get_subscribers(event) == []

    def test_loop_guard_stops_deep_chains(self):
        # An automation's emit_event/write-back re-dispatches at reaction_depth+1; once a chain is
        # deep enough the listener refuses to react, so chains stay finite.
        from marvin.services.automation.engine import MAX_REACTION_DEPTH

        deep = SimpleNamespace(event_type=EventTypes.entry_published, reaction_depth=MAX_REACTION_DEPTH)
        assert self._listener().get_subscribers(deep) == []
        shallow = SimpleNamespace(event_type=EventTypes.entry_published, reaction_depth=0)
        assert self._listener().get_subscribers(shallow) == ["automation"]


# ── Engine: orchestration with a fake session + injected runner ───────────────
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **kw):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal stand-in: query() returns the automations; get() returns the entry."""

    def __init__(self, automations, entry=None):
        self._automations = automations
        self._entry = entry

    def query(self, _model):
        return _FakeQuery(self._automations)

    def get(self, _model, _id):
        return self._entry


def _automation(slug="auto", trigger="entry_published", conditions=None, actions=None):
    return SimpleNamespace(
        slug=slug,
        enabled=True,
        group_id=uuid4(),
        definition={"trigger": {"event": trigger}, "conditions": conditions or [], "actions": actions or []},
    )


def _entry(entry_type="recipe", status="published"):
    return SimpleNamespace(id=uuid4(), group_id="G", status=status, title="T", slug="t", entry_type=SimpleNamespace(slug=entry_type))


def _recording_runner():
    calls = []

    def run(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
        calls.append({"action": action, "previous": dict(context.get("previous", {}))})
        return {"summary": "generated"}

    run.calls = calls
    return run


class TestEngine:
    def _run(self, session, event_type="entry_published", run_action=None):
        gid = "G"
        # _entry_context checks entry.group_id == group_id; align the fake entry's group.
        if session._entry is not None:
            session._entry.group_id = gid
        ctx = {"event_type": event_type, "entry_id": uuid4(), "user_id": None}
        return engine.run_automations_for_event(session, gid, ctx, run_action=run_action)

    def test_matching_automation_runs_its_action(self):
        auto = _automation(actions=[{"kind": "operation", "op": "generate-summary", "write_back": True}])
        runner = _recording_runner()
        ran = self._run(_FakeSession([auto], entry=_entry("recipe")), run_action=runner)
        assert ran == 1
        assert len(runner.calls) == 1
        assert runner.calls[0]["action"]["op"] == "generate-summary"

    def test_trigger_mismatch_skips(self):
        auto = _automation(trigger="entry_published", actions=[{"kind": "operation", "op": "generate-summary"}])
        runner = _recording_runner()
        ran = self._run(_FakeSession([auto], entry=_entry()), event_type="entry_updated", run_action=runner)
        assert ran == 0
        assert runner.calls == []

    def test_condition_gates_the_automation(self):
        auto = _automation(
            conditions=[{"field": "entry.entry_type", "op": "eq", "value": "recipe"}],
            actions=[{"kind": "operation", "op": "generate-summary"}],
        )
        runner = _recording_runner()
        # entry is an article → condition fails → no run
        ran = self._run(_FakeSession([auto], entry=_entry(entry_type="article")), run_action=runner)
        assert ran == 0
        assert runner.calls == []

    def test_pipeline_threads_previous_between_steps(self):
        auto = _automation(
            actions=[
                {"kind": "operation", "op": "generate-summary"},
                {"kind": "operation", "op": "generate-tags", "input": {"hint": "$previous.summary"}},
            ]
        )
        runner = _recording_runner()
        self._run(_FakeSession([auto], entry=_entry()), run_action=runner)
        # First step sees empty previous; second sees the first step's output.
        assert runner.calls[0]["previous"] == {}
        assert runner.calls[1]["previous"] == {"summary": "generated"}

    def test_named_step_outputs_addressable(self):
        # A later step can reach an earlier one by position ($steps.0) AND by id ($steps.<id>),
        # not just the immediately-previous one — so reordering doesn't silently break a pipeline.
        auto = _automation(
            actions=[
                {"kind": "operation", "op": "a", "id": "first"},
                {"kind": "operation", "op": "b"},
            ]
        )
        seen = []

        def runner(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
            seen.append({k: dict(v) for k, v in context.get("steps", {}).items()})
            return {"val": action["op"]}

        self._run(_FakeSession([auto], entry=_entry()), run_action=runner)
        assert seen[0] == {}  # first step: nothing recorded yet
        assert seen[1]["0"]["output"] == {"val": "a"}  # by position
        assert seen[1]["first"]["output"] == {"val": "a"}  # by id

    def test_all_actions_dispatch_in_order(self):
        # The engine no longer filters by kind — every action is handed to the dispatcher in order;
        # routing by kind is the registry's job.
        auto = _automation(actions=[{"kind": "webhook", "url": "x"}, {"kind": "operation", "op": "generate-summary"}])
        runner = _recording_runner()
        ran = self._run(_FakeSession([auto], entry=_entry()), run_action=runner)
        assert ran == 1
        assert [c["action"].get("kind") for c in runner.calls] == ["webhook", "operation"]

    def test_action_error_stops_the_pipeline(self):
        auto = _automation(
            actions=[
                {"kind": "operation", "op": "boom"},
                {"kind": "operation", "op": "never-runs"},
            ]
        )
        calls = []

        def failing(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
            calls.append(action["op"])
            raise AutomationActionError("nope")

        ran = self._run(_FakeSession([auto], entry=_entry()), run_action=failing)
        assert ran == 1  # the automation was matched + attempted
        assert calls == ["boom"]  # pipeline broke after the failing step


# ── Action-executor registry ──────────────────────────────────────────────────
class TestActionRegistry:
    def test_all_kinds_registered(self):
        from marvin.services.automation.actions import available_kinds

        assert set(available_kinds()) == {"operation", "emit_event", "handler", "webhook", "entry"}

    def test_unknown_kind_raises(self):
        from marvin.services.automation.actions import run_action

        with pytest.raises(AutomationActionError):
            run_action(None, "G", {"kind": "does-not-exist"}, {"previous": {}})


# ── handler action allowlist (security) ───────────────────────────────────────
class TestHandlerAllowlist:
    def _run(self, task, config=None):
        from marvin.services.automation.actions.handler import run_handler

        return run_handler(None, "G", {"kind": "handler", "task": task, "config": config or {}}, {"event": {}, "depth": 0})

    def test_allowlisted_handler_runs(self, monkeypatch):
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        seen = {}

        class _Fake:
            def execute(self, task, _bus):
                seen["cfg"] = task.task_config
                return "ok"

        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: _Fake()))
        out = self._run("request_site_rebuild", {"x": 1})
        assert out == {"result": "ok"} and seen["cfg"] == {"x": 1}

    def test_maintenance_and_meta_handlers_are_blocked(self):
        import marvin.services.scheduled_tasks.handlers.automation  # noqa: F401
        import marvin.services.scheduled_tasks.handlers.maintenance  # noqa: F401 — ensure registration

        for task in (
            "remove_orphaned_assets",
            "prune_event_logs",
            "prune_ai_executions",
            "prune_expired_sessions",
            "cleanup_temp_files",
            "run_automation",
        ):
            with pytest.raises(AutomationActionError):
                self._run(task)  # never runs a destructive/meta job from an automation

    def test_forbidden_registered_task_names_the_allowlist(self):
        import marvin.services.scheduled_tasks.handlers.maintenance  # noqa: F401

        with pytest.raises(AutomationActionError) as e:
            self._run("remove_orphaned_assets")
        assert "allowlist" in str(e.value).lower()

    def test_unknown_task_still_reported_as_unknown(self):
        with pytest.raises(AutomationActionError) as e:
            self._run("totally_made_up_task")
        assert "unknown" in str(e.value).lower()


# ── Per-user authorization at execution (definer's rights) ────────────────────
class _RoleSession:
    """A session whose get(Users, id) returns a preset fake user (for authz resolution)."""

    def __init__(self, user=None):
        self._user = user

    def get(self, _model, _id):
        return self._user


def _fake_user(*, admin=False, role_value=None, group_id="G"):
    role = SimpleNamespace(value=role_value) if role_value is not None else None
    return SimpleNamespace(admin=admin, get_workspace_role=lambda gid: role if str(gid) == str(group_id) else None)


class TestResolveAuthorizerRole:
    def test_none_author_is_owner_backcompat(self):
        from marvin.services.automation.authz import ROLE_OWNER, resolve_authorizer_role

        # Legacy/system automations with no created_by → OWNER (only an admin could have made one).
        assert resolve_authorizer_role(_RoleSession(), "G", None) == ROLE_OWNER

    def test_removed_author_fails_closed_to_zero(self):
        from marvin.services.automation.authz import resolve_authorizer_role

        # created_by set but the user no longer exists → role 0 (fail closed).
        assert resolve_authorizer_role(_RoleSession(user=None), "G", uuid4()) == 0

    def test_platform_admin_is_owner(self):
        from marvin.services.automation.authz import ROLE_OWNER, resolve_authorizer_role

        s = _RoleSession(user=_fake_user(admin=True))
        assert resolve_authorizer_role(s, "G", uuid4()) == ROLE_OWNER

    def test_member_gets_their_role_value(self):
        from marvin.services.automation.authz import ROLE_AUTHOR, resolve_authorizer_role

        s = _RoleSession(user=_fake_user(role_value=ROLE_AUTHOR))
        assert resolve_authorizer_role(s, "G", uuid4()) == ROLE_AUTHOR

    def test_non_member_author_fails_closed(self):
        from marvin.services.automation.authz import resolve_authorizer_role

        # A real user, but not a member of THIS workspace → 0.
        s = _RoleSession(user=_fake_user(role_value=None))
        assert resolve_authorizer_role(s, "G", uuid4()) == 0


class TestActionRoleGates:
    """Each action kind refuses to run when the automation's author lacks its required role."""

    def test_handler_below_admin_is_rejected(self):
        from marvin.services.automation.actions.handler import run_handler
        from marvin.services.automation.authz import ROLE_AUTHOR

        with pytest.raises(AutomationActionError) as e:
            run_handler(None, "G", {"kind": "handler", "task": "request_site_rebuild"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_AUTHOR)
        assert "role" in str(e.value).lower()  # gate fired before the allowlist/registry

    def test_webhook_below_admin_is_rejected(self):
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_EDITOR

        with pytest.raises(AutomationActionError) as e:
            run_webhook(None, "G", {"kind": "webhook", "url": "https://example.test"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_EDITOR)
        assert "role" in str(e.value).lower()

    def test_entry_below_author_is_rejected(self):
        from marvin.services.automation.actions.entry import run_entry_action
        from marvin.services.automation.authz import ROLE_VIEWER

        with pytest.raises(AutomationActionError) as e:
            run_entry_action(None, "G", {"kind": "entry", "op": "publish"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_VIEWER)
        assert "role" in str(e.value).lower()

    def test_sufficient_role_passes_the_gate(self, monkeypatch):
        # An ADMIN author clears the handler gate — it then runs the real (allowlisted) handler.
        from marvin.services.automation.actions.handler import run_handler
        from marvin.services.automation.authz import ROLE_ADMIN
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        class _Fake:
            def execute(self, task, _bus):
                return "ran"

        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: _Fake()))
        out = run_handler(None, "G", {"kind": "handler", "task": "request_site_rebuild"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)
        assert out == {"result": "ran"}

    def test_default_no_authz_is_owner_for_direct_callers(self, monkeypatch):
        # A direct caller that doesn't thread authz (tests/tools) is treated as OWNER — no regression.
        from marvin.services.automation.actions.handler import run_handler
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        class _Fake:
            def execute(self, task, _bus):
                return "ran"

        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: _Fake()))
        assert run_handler(None, "G", {"kind": "handler", "task": "request_site_rebuild"}, {"event": {}, "depth": 0}) == {"result": "ran"}

    def test_engine_gates_privileged_action_by_authors_role(self, monkeypatch):
        # End-to-end: an automation whose author resolves to a low role never executes its handler.
        from marvin.services.automation import engine
        from marvin.services.automation.authz import ROLE_VIEWER
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        monkeypatch.setattr(engine, "resolve_authorizer_role", lambda *a, **k: ROLE_VIEWER)
        executed = []
        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: SimpleNamespace(execute=lambda *a: executed.append(1))))

        auto = SimpleNamespace(
            slug="a",
            created_by=uuid4(),
            definition={
                "trigger": {"type": "manual"},
                "actions": [{"kind": "handler", "task": "request_site_rebuild"}],
            },
        )
        res = engine.run_automation_now(_FakeSession([]), "G", auto)
        assert res["ok"] is False and res["ran"] == 1  # attempted, but the gate stopped it
        assert executed == []  # the privileged handler never ran


# ── Definition schema: the one structural source of truth ─────────────────────
class TestDefinitionSchema:
    def _valid(self):
        return {
            "trigger": {"type": "event", "event": "entry_published"},
            "target": {"entity": "entry", "query": {"status": "draft"}},
            "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "recipe"}],
            "actions": [
                {"kind": "operation", "op": "generate-summary", "write_back": True, "id": "s1"},
                {"kind": "entry", "op": "publish"},
            ],
        }

    def test_full_definition_validates(self):
        from marvin.services.automation.validation import structural_issues

        assert structural_issues(self._valid()) == []

    def test_empty_definition_is_valid(self):
        from marvin.services.automation.validation import structural_issues

        assert structural_issues({}) == []
        assert structural_issues(None) == []

    def test_unknown_action_kind_is_a_structural_error(self):
        from marvin.services.automation.validation import structural_issues

        issues = structural_issues({"actions": [{"kind": "delete_everything"}]})
        assert issues and issues[0]["level"] == "error" and issues[0]["where"] == "action" and issues[0]["index"] == 0

    def test_missing_required_field_is_an_error(self):
        from marvin.services.automation.validation import structural_issues

        assert any("op" in i["message"] for i in structural_issues({"actions": [{"kind": "operation"}]}))

    def test_bad_entry_op_literal_is_an_error(self):
        from marvin.services.automation.validation import structural_issues

        assert structural_issues({"actions": [{"kind": "entry", "op": "nuke"}]})

    def test_collection_ops_are_valid_entry_ops(self):
        from marvin.services.automation.validation import structural_issues

        for op in ("add_to_collection", "remove_from_collection"):
            assert structural_issues({"actions": [{"kind": "entry", "op": op, "collection_slug": "featured"}]}) == []

    def test_entry_model_ops_match_the_executor(self):
        # Drift guard: the EntryAction op literal must list exactly the executor's ops.
        from typing import get_args, get_type_hints

        from marvin.schemas.group.automation_definition import EntryAction
        from marvin.services.automation.actions.entry import ALL_OPS

        literal = get_args(get_type_hints(EntryAction)["op"])
        assert set(literal) == set(ALL_OPS)

    def test_unknown_trigger_type_is_an_error(self):
        from marvin.services.automation.validation import structural_issues

        issues = structural_issues({"trigger": {"type": "telepathy"}, "actions": []})
        assert issues and issues[0]["where"] == "trigger"

    def test_extra_keys_are_allowed(self):
        # Lenient on unknown keys (forward-compat) — a typo/extra doesn't block a save.
        from marvin.services.automation.validation import structural_issues

        assert structural_issues({"actions": [{"kind": "handler", "task": "x", "future_flag": True}]}) == []

    def test_trigger_without_type_defaults_to_event(self):
        from marvin.schemas.group.automation_definition import AutomationDefinition

        d = AutomationDefinition.model_validate({"trigger": {"event": "entry_updated"}, "actions": []})
        assert d.trigger.type == "event" and d.trigger.event == "entry_updated"

    def test_condition_group_with_not(self):
        from marvin.services.automation.validation import structural_issues

        assert structural_issues({"conditions": {"not": {"field": "entry.status", "op": "eq", "value": "draft"}}, "actions": []}) == []

    def test_json_schema_generates(self):
        from marvin.schemas.group.automation_definition import definition_json_schema

        s = definition_json_schema()
        assert "$defs" in s and "properties" in s

    # ── Drift guards: the models must stay in lockstep with the registries ──────
    def test_action_models_match_executor_registry(self):
        from marvin.schemas.group.automation_definition import ACTION_MODELS
        from marvin.services.automation.actions import available_kinds

        assert set(ACTION_MODELS) == set(available_kinds()), "an action executor exists without a matching definition model (or vice versa)"

    def test_trigger_models_match_validation_catalog(self):
        from marvin.schemas.group.automation_definition import TRIGGER_MODELS
        from marvin.services.automation.validation import _TRIGGER_CONTEXT

        assert set(TRIGGER_MODELS) == set(_TRIGGER_CONTEXT), "a trigger type is modeled without a validation context (or vice versa)"


# ── Dry run: resolve inputs, execute nothing ──────────────────────────────────
class TestDryRun:
    def test_handler_dry_run_previews_without_executing(self, monkeypatch):
        from marvin.services.automation.actions.handler import run_handler
        from marvin.services.automation.authz import ROLE_ADMIN
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        executed = []
        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: SimpleNamespace(execute=lambda *a: executed.append(1))))
        out = run_handler(
            None,
            "G",
            {"kind": "handler", "task": "request_site_rebuild", "config": {"n": "$event.count"}},
            {"event": {"count": 3}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
            dry_run=True,
        )
        assert out == {"dry_run": True, "kind": "handler", "task": "request_site_rebuild", "config": {"n": 3}}
        assert executed == []  # the job never ran

    def test_entry_dry_run_previews_without_mutating(self, monkeypatch):
        import marvin.services.entries as entries_mod
        from marvin.services.automation.actions.entry import run_entry_action
        from marvin.services.automation.authz import ROLE_AUTHOR

        def _boom(*a, **k):
            raise AssertionError("EntryService must not be constructed during a dry run")

        monkeypatch.setattr(entries_mod, "EntryService", _boom)
        eid = uuid4()
        out = run_entry_action(
            None, "G", {"kind": "entry", "op": "publish"}, {"event": {"entry_id": str(eid)}, "depth": 0}, authorizer_role=ROLE_AUTHOR, dry_run=True
        )
        assert out == {"dry_run": True, "kind": "entry", "op": "publish", "entity_id": str(eid), "would_set_status": "published"}

    def test_webhook_dry_run_does_not_post(self, monkeypatch):
        import httpx

        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        monkeypatch.setattr(httpx, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no POST in dry run")))
        out = run_webhook(
            None,
            "G",
            {"kind": "webhook", "url": "https://example.test/hook", "body": {"id": "$event.entry_id"}},
            {"event": {"entry_id": "e1"}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
            dry_run=True,
        )
        assert out["dry_run"] is True and out["method"] == "POST" and out["url"] == "https://example.test/hook"
        assert out["body"] == {"id": "e1"} and out["authorized"] is False

    def test_webhook_secret_defaults_to_bearer_scheme(self, monkeypatch):
        import httpx

        import marvin.services.secrets.resolver as resolver
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        seen = {}
        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: "s3cret" if ref == "HOOK_KEY" else None)

        def _capture(method, url, **k):
            seen.update(headers=k["headers"])
            return SimpleNamespace(status_code=201, is_success=True)

        monkeypatch.setattr(httpx, "request", _capture)
        out = run_webhook(
            None,
            "G",
            {"kind": "webhook", "url": "https://example.test/hook", "secret_ref": "{{HOOK_KEY}}"},
            {"event": {}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
        )
        assert out["ok"] is True and seen["headers"]["Authorization"] == "Bearer s3cret"

    def test_webhook_auth_scheme_token(self, monkeypatch):
        """Buttondown-style APIs want `Authorization: Token <key>`; `auth_scheme` selects it."""
        import httpx

        import marvin.services.secrets.resolver as resolver
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        seen = {}
        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: "s3cret")

        def _capture(method, url, **k):
            seen.update(headers=k["headers"])
            return SimpleNamespace(status_code=201, is_success=True)

        monkeypatch.setattr(httpx, "request", _capture)
        run_webhook(
            None,
            "G",
            {"kind": "webhook", "url": "https://example.test/hook", "secret_ref": "{{HOOK_KEY}}", "auth_scheme": "Token"},
            {"event": {}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
        )
        assert seen["headers"]["Authorization"] == "Token s3cret"

    def test_webhook_dry_run_reports_auth_scheme_without_resolving(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        monkeypatch.setattr(resolver, "resolve_secret", lambda *a: (_ for _ in ()).throw(AssertionError("must not resolve in dry run")))
        out = run_webhook(
            None,
            "G",
            {"kind": "webhook", "url": "https://example.test/hook", "secret_ref": "{{HOOK_KEY}}", "auth_scheme": "Token"},
            {"event": {}, "depth": 0},
            authorizer_role=ROLE_ADMIN,
            dry_run=True,
        )
        assert out["authorized"] is True and out["auth_scheme"] == "Token"

    def test_emit_event_dry_run_does_not_dispatch(self):
        from marvin.services.automation.actions.emit_event import run_emit_event
        from marvin.services.automation.authz import ROLE_ADMIN

        eid = uuid4()
        out = run_emit_event(
            None,
            "G",
            {"kind": "emit_event", "event": "entry_published", "entity_id": str(eid)},
            {"event": {}, "entry": {}, "depth": 1},
            authorizer_role=ROLE_ADMIN,
            dry_run=True,
        )
        assert out == {"dry_run": True, "kind": "emit_event", "event": "entry_published", "entity_id": str(eid), "reaction_depth": 2}

    def test_operation_dry_run_skips_provider(self, monkeypatch):
        from marvin.services.automation import runner
        from marvin.services.automation.authz import ROLE_OWNER

        monkeypatch.setattr(runner, "_gate_source", lambda *a, **k: None)
        monkeypatch.setattr(runner, "get_operation", lambda slug: SimpleNamespace(slug=slug, min_role=2, invocation_sources=("automation",)))

        def _no_provider(*a, **k):
            raise AssertionError("provider must not be fetched during a dry run")

        monkeypatch.setattr(runner, "get_workspace_ai_provider", _no_provider, raising=False)
        eid = uuid4()
        out = runner.run_operation_action(
            None,
            "G",
            {"kind": "operation", "op": "generate-summary", "input": {"tone": "$event.tone"}, "write_back": True},
            {"event": {"entry_id": str(eid), "tone": "warm"}, "depth": 0},
            authorizer_role=ROLE_OWNER,
            dry_run=True,
        )
        assert out == {
            "dry_run": True,
            "kind": "operation",
            "op": "generate-summary",
            "entity_type": "entry",
            "entity_id": str(eid),
            "input": {"tone": "warm"},
            "would_write_back": True,
        }

    def test_engine_dry_run_returns_plan_and_records_nothing(self, monkeypatch):
        from marvin.services.automation import engine
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        executed = []
        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", staticmethod(lambda _t: SimpleNamespace(execute=lambda *a: executed.append(1))))
        auto = SimpleNamespace(
            slug="a",
            created_by=None,
            definition={
                "trigger": {"type": "manual"},
                "actions": [{"kind": "handler", "task": "request_site_rebuild", "config": {"x": 1}}],
            },
        )
        res = engine.run_automation_now(_FakeSession([]), "G", auto, dry_run=True)
        assert res["dry_run"] is True and res["ok"] is True and res["ran"] == 1
        assert len(res["plan"]) == 1
        step = res["plan"][0]
        assert step["kind"] == "handler" and step["status"] == "success"
        assert step["resolved"] == {"dry_run": True, "kind": "handler", "task": "request_site_rebuild", "config": {"x": 1}}
        assert executed == []  # nothing actually ran


# ── Trigger matching: event / chained / on-error (T3) ─────────────────────────
class TestTriggerMatching:
    def _m(self, trig, ev):
        from marvin.services.automation.engine import _trigger_matches

        return _trigger_matches(trig, ev)

    def test_event_trigger(self):
        assert self._m({"type": "event", "event": "entry_published"}, {"event_type": "entry_published"})
        assert not self._m({"type": "event", "event": "entry_published"}, {"event_type": "entry_updated"})

    def test_chained_any_and_targeted(self):
        ev = {"event_type": "automation_ran", "automation_slug": "src", "automation_id": "id1"}
        assert self._m({"type": "chained"}, ev)  # any
        assert self._m({"type": "chained", "automation": "any"}, ev)  # explicit any
        assert self._m({"type": "chained", "automation": "src"}, ev)  # by slug
        assert self._m({"type": "chained", "automation": "id1"}, ev)  # by id
        assert not self._m({"type": "chained", "automation": "other"}, ev)
        assert not self._m({"type": "chained"}, {"event_type": "automation_failed"})  # wrong lifecycle event

    def test_on_error(self):
        assert self._m({"type": "on_error"}, {"event_type": "automation_failed"})
        assert not self._m({"type": "on_error"}, {"event_type": "automation_ran"})

    def test_manual_and_schedule_never_fire_on_events(self):
        assert not self._m({"type": "manual"}, {"event_type": "entry_published"})
        assert not self._m({"type": "schedule"}, {"event_type": "automation_ran"})

    def test_listener_subscribes_to_automation_lifecycle_events(self):
        from marvin.services.event_bus_service.event_types import EventTypes

        listener = AutomationReactionListener(group_id=uuid4())
        for et in (EventTypes.automation_ran, EventTypes.automation_failed):
            ev = SimpleNamespace(event_type=et, reaction_depth=0)
            assert listener.get_subscribers(ev) == ["automation"]


# ── Incoming-webhook trigger (T5) ─────────────────────────────────────────────
class TestIncomingWebhookTrigger:
    def _m(self, trig, ev):
        from marvin.services.automation.engine import _trigger_matches

        return _trigger_matches(trig, ev)

    def test_listener_subscribes_to_incoming_webhook(self):
        listener = AutomationReactionListener(group_id=uuid4())
        ev = SimpleNamespace(event_type=EventTypes.incoming_webhook, reaction_depth=0)
        assert listener.get_subscribers(ev) == ["automation"]

    def test_targeted_slug_matches_only_that_webhook(self):
        trig = {"type": "incoming_webhook", "webhook": "stripe"}
        assert self._m(trig, {"event_type": "incoming_webhook", "webhook_slug": "stripe"})
        assert not self._m(trig, {"event_type": "incoming_webhook", "webhook_slug": "github"})

    def test_any_webhook_and_wrong_event(self):
        assert self._m({"type": "incoming_webhook"}, {"event_type": "incoming_webhook", "webhook_slug": "x"})
        assert self._m({"type": "incoming_webhook", "webhook": "any"}, {"event_type": "incoming_webhook", "webhook_slug": "x"})
        # a non-webhook event never fires an incoming_webhook trigger
        assert not self._m({"type": "incoming_webhook", "webhook": "x"}, {"event_type": "entry_published"})

    def test_engine_runs_webhook_automation_with_payload_condition(self):
        # An incoming_webhook automation gated on a nested payload field, run through the engine.
        auto = SimpleNamespace(
            slug="on-paid",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "incoming_webhook", "webhook": "stripe"},
                "conditions": [{"field": "event.payload.type", "op": "eq", "value": "payment.succeeded"}],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            },
        )
        runner = _recording_runner()
        ctx = {"event_type": "incoming_webhook", "webhook_slug": "stripe", "payload": {"type": "payment.succeeded", "amount": 999}, "user_id": None}
        ran = engine.run_automations_for_event(_FakeSession([auto]), "G", ctx, run_action=runner)
        assert ran == 1
        assert len(runner.calls) == 1

    def test_engine_skips_when_payload_condition_fails(self):
        auto = SimpleNamespace(
            slug="on-paid",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "incoming_webhook", "webhook": "stripe"},
                "conditions": [{"field": "event.payload.type", "op": "eq", "value": "payment.succeeded"}],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            },
        )
        runner = _recording_runner()
        ctx = {"event_type": "incoming_webhook", "webhook_slug": "stripe", "payload": {"type": "payment.refunded"}, "user_id": None}
        ran = engine.run_automations_for_event(_FakeSession([auto]), "G", ctx, run_action=runner)
        assert ran == 0
        assert runner.calls == []

    def test_fan_out_two_automations_same_webhook(self):
        mk = lambda slug: SimpleNamespace(  # noqa: E731
            slug=slug,
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "incoming_webhook", "webhook": "stripe"},
                "conditions": [],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            },
        )
        runner = _recording_runner()
        ctx = {"event_type": "incoming_webhook", "webhook_slug": "stripe", "payload": {}, "user_id": None}
        ran = engine.run_automations_for_event(_FakeSession([mk("a"), mk("b")]), "G", ctx, run_action=runner)
        assert ran == 2
        assert len(runner.calls) == 2


# ── Definition validation: catch the silent-no-op footgun ─────────────────────
class TestValidateDefinition:
    def _v(self, definition):
        from marvin.services.automation.validation import validate_definition

        return validate_definition(definition)

    def test_entry_condition_under_webhook_trigger_warns(self):
        # The exact real-world bug: an entry.* condition paired with a webhook trigger never matches.
        issues = self._v(
            {
                "trigger": {"type": "incoming_webhook", "webhook": "x"},
                "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "page"}],
                "actions": [{"kind": "operation", "op": "generate-tags"}],
            }
        )
        msgs = " ".join(i["message"] for i in issues)
        assert "entry.entry_type" in msgs and "no entry" in msgs  # condition flagged
        assert any(i["where"] == "condition" for i in issues)
        assert any(i["where"] == "action" for i in issues)  # entry-shaped action flagged too

    def test_entry_condition_under_entry_trigger_is_clean(self):
        assert (
            self._v(
                {
                    "trigger": {"type": "event", "event": "entry_published"},
                    "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "recipe"}],
                    "actions": [{"kind": "operation", "op": "generate-summary"}],
                }
            )
            == []
        )

    def test_entity_slug_clears_the_entry_action_warning(self):
        # Targeting an entry by slug from the payload makes an entry-shaped step valid on a webhook.
        issues = self._v(
            {
                "trigger": {"type": "incoming_webhook", "webhook": "x"},
                "conditions": [],
                "actions": [{"kind": "operation", "op": "generate-tags", "entity_slug": "$event.payload.entry_slug"}],
            }
        )
        assert issues == []

    def test_webhook_payload_condition_is_clean(self):
        assert (
            self._v(
                {
                    "trigger": {"type": "incoming_webhook", "webhook": "x"},
                    "conditions": [{"field": "event.payload.type", "op": "eq", "value": "paid"}],
                    "actions": [{"kind": "emit_event", "event": "noted"}],
                }
            )
            == []
        )

    def test_previous_in_condition_warns(self):
        issues = self._v(
            {
                "trigger": {"type": "event", "event": "entry_published"},
                "conditions": [{"field": "previous.summary", "op": "exists"}],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            }
        )
        assert any("step outputs aren't available" in i["message"] for i in issues)

    def test_no_actions_warns(self):
        issues = self._v({"trigger": {"type": "manual"}, "conditions": [], "actions": []})
        assert any(i["where"] == "action" and "no steps" in i["message"] for i in issues)

    def test_unknown_operator_warns(self):
        issues = self._v(
            {
                "trigger": {"type": "event", "event": "entry_published"},
                "conditions": [{"field": "entry.status", "op": "regex", "value": ".*"}],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            }
        )
        assert any("operator" in i["message"] for i in issues)

    def test_catalog_covers_all_trigger_types(self):
        from marvin.services.automation.validation import condition_field_catalog

        cat = condition_field_catalog()
        for t in ("event", "incoming_webhook", "chained", "on_error", "manual", "schedule", "mcp"):
            assert t in cat and cat[t]
        # entry trigger offers entry fields; webhook offers a payload prefix
        assert any(f["field"].startswith("entry.") for f in cat["event"])
        assert any(f["field"].startswith("event.payload") for f in cat["incoming_webhook"])

    def test_target_makes_entry_conditions_and_actions_valid(self):
        # A target selector hydrates entry.* per matched row, so entry conditions/actions are fine
        # even under a webhook trigger that has no inherent entry.
        issues = self._v(
            {
                "trigger": {"type": "incoming_webhook", "webhook": "x"},
                "target": {"entity": "entry", "query": {"status": "draft"}},
                "conditions": [{"field": "entry.status", "op": "eq", "value": "draft"}],
                "actions": [{"kind": "operation", "op": "generate-tags"}],
            }
        )
        assert issues == []


# ── Generalized triggers: any curated event, flattened $event.* ───────────────
class TestGeneralizedTriggers:
    def test_listener_reacts_to_non_entry_families(self):
        listener = AutomationReactionListener(group_id=uuid4())
        for et in (
            EventTypes.asset_uploaded,
            EventTypes.resource_created,
            EventTypes.form_published,
            EventTypes.collection_updated,
            EventTypes.entry_type_created,
        ):
            ev = SimpleNamespace(event_type=et, reaction_depth=0)
            assert listener.get_subscribers(ev) == ["automation"]

    def test_listener_ignores_internal_noise(self):
        listener = AutomationReactionListener(group_id=uuid4())
        for et in (
            EventTypes.ai_operation_executed,
            EventTypes.ai_embeddings_reindexed,
            EventTypes.scheduled_task_completed,
            EventTypes.webhook_task,
        ):
            ev = SimpleNamespace(event_type=et, reaction_depth=0)
            assert listener.get_subscribers(ev) == []

    def test_listener_flattens_document_data_into_event(self, monkeypatch):
        import contextlib

        from marvin.services.event_bus_service.event_types import (
            Event,
            EventAssetData,
            EventBusMessage,
            EventOperation,
        )
        from marvin.services.event_bus_service.event_types import (
            EventTypes as ET,
        )

        captured = {}

        def _fake_run(session, group_id, event_ctx, **kw):
            captured.update(event_ctx)
            return 0

        monkeypatch.setattr("marvin.services.automation.engine.run_automations_for_event", _fake_run)
        listener = AutomationReactionListener(group_id=uuid4())
        monkeypatch.setattr(listener, "ensure_session", lambda: contextlib.nullcontext(None))

        dd = EventAssetData(
            operation=EventOperation.info,
            asset_id=uuid4(),
            slug="hero",
            name="Hero",
            mime_type="image/png",
            asset_type="image",
            storage_key="k",
            workspace_id=uuid4(),
        )
        ev = Event(message=EventBusMessage.from_type(ET.asset_uploaded), event_type=ET.asset_uploaded, integration_id="test", document_data=dd)
        listener.publish_to_subscribers(ev, ["automation"])
        # $event.asset_type is reachable → an asset trigger can condition on it
        assert captured.get("asset_type") == "image"
        assert captured.get("mime_type") == "image/png"
        assert captured.get("event_type") == "asset_uploaded"

    def test_condition_on_flattened_field_matches(self):
        auto = _automation(
            trigger="asset_uploaded",
            conditions=[{"field": "event.asset_type", "op": "eq", "value": "image"}],
            actions=[{"kind": "emit_event", "event": "noted"}],
        )
        runner = _recording_runner()
        ctx = {"event_type": "asset_uploaded", "asset_type": "image", "user_id": None}
        assert engine.run_automations_for_event(_FakeSession([auto]), "G", ctx, run_action=runner) == 1

    def test_entry_context_carries_summary_and_data(self):
        from marvin.services.automation import engine

        entry = SimpleNamespace(
            id="e1",
            group_id="G",
            entry_type=SimpleNamespace(slug="newsletter-issue"),
            status="published",
            title="Welcome",
            slug="welcome",
            summary="Hello",
            data_json={"body": "# Hi", "preview": "p"},
        )
        session = SimpleNamespace(get=lambda model, eid: entry)
        ctx = engine._entry_context(session, "G", "e1")
        assert ctx["summary"] == "Hello" and ctx["data"] == {"body": "# Hi", "preview": "p"}

    def test_entry_context_null_data_is_empty_dict(self):
        from marvin.services.automation import engine

        entry = SimpleNamespace(id="e1", group_id="G", entry_type=None, status="draft", title="T", slug="t", summary=None, data_json=None)
        ctx = engine._entry_context(SimpleNamespace(get=lambda m, e: entry), "G", "e1")
        assert ctx["data"] == {} and ctx["entry_type"] is None

    def test_curated_catalog_excludes_noise(self):
        from marvin.services.automation.triggers import TRIGGER_EVENT_NAMES_SET

        assert "asset_uploaded" in TRIGGER_EVENT_NAMES_SET
        assert "entry_published" in TRIGGER_EVENT_NAMES_SET
        # A site's signup/contact forms are the most common thing to react to.
        assert "form_submission_received" in TRIGGER_EVENT_NAMES_SET
        for noise in ("ai_operation_executed", "ai_embeddings_reindexed", "webhook_task", "scheduled_task_completed", "automation_ran"):
            assert noise not in TRIGGER_EVENT_NAMES_SET


# ── Entry actions (publish/unpublish/archive/restore) ─────────────────────────
class TestEntryAction:
    def _spy_service(self, monkeypatch):
        calls = {"set_status": [], "add_to_collection": [], "remove_from_collection": []}

        class SpySvc:
            def __init__(self, *a, **k):
                pass

            def set_status(self, eid, status, *, reaction_depth=0):
                calls["set_status"].append((str(eid), status, reaction_depth))
                return object()  # non-None = found

            def add_to_collection(self, eid, ref, *, reaction_depth=0):
                calls["add_to_collection"].append((str(eid), ref, reaction_depth))
                return "added"

            def remove_from_collection(self, eid, ref, *, reaction_depth=0):
                calls["remove_from_collection"].append((str(eid), ref, reaction_depth))
                return "removed"

        import marvin.services.entries as entries_mod

        monkeypatch.setattr(entries_mod, "EntryService", SpySvc)
        return calls

    def test_publish_sets_status_at_depth_plus_one(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        calls = self._spy_service(monkeypatch)
        eid = uuid4()
        out = run_entry_action(None, "G", {"kind": "entry", "op": "publish"}, {"event": {"entry_id": str(eid)}, "depth": 0})
        assert calls["set_status"] == [(str(eid), "published", 1)]  # depth+1 for the loop-guard
        assert out == {"entry_id": str(eid), "op": "publish", "status": "published"}

    def test_each_op_maps_to_its_status(self, monkeypatch):
        from marvin.services.automation.actions.entry import ENTRY_OPS, run_entry_action

        for op, st in ENTRY_OPS.items():
            calls = self._spy_service(monkeypatch)
            eid = uuid4()
            run_entry_action(None, "G", {"kind": "entry", "op": op}, {"event": {"entry_id": str(eid)}, "depth": 0})
            assert calls["set_status"][0][1] == st

    def test_targets_entry_by_slug(self, monkeypatch):
        from marvin.services.automation.actions import entry as entry_action

        calls = self._spy_service(monkeypatch)
        target = uuid4()
        monkeypatch.setattr(entry_action, "_resolve_target", lambda *a, **k: target)
        run_entry_action = entry_action.run_entry_action
        run_entry_action(
            None, "G", {"kind": "entry", "op": "archive", "entity_slug": "$event.payload.slug"}, {"event": {"payload": {"slug": "x"}}, "depth": 0}
        )
        assert calls["set_status"][0][0] == str(target)

    def test_unknown_op_raises(self):
        from marvin.services.automation.actions.entry import run_entry_action

        with pytest.raises(AutomationActionError):
            run_entry_action(None, "G", {"kind": "entry", "op": "nuke"}, {"event": {}, "depth": 0})

    def test_no_target_entry_raises(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        self._spy_service(monkeypatch)
        with pytest.raises(AutomationActionError):
            run_entry_action(None, "G", {"kind": "entry", "op": "publish"}, {"event": {}, "depth": 0})

    def test_registered_as_an_action_kind(self):
        from marvin.services.automation.actions import available_kinds

        assert "entry" in available_kinds()

    # ── Collection membership ops ───────────────────────────────────────────────
    def test_add_to_collection_calls_service_with_ref_at_depth_plus_one(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        calls = self._spy_service(monkeypatch)
        eid = uuid4()
        out = run_entry_action(
            None, "G", {"kind": "entry", "op": "add_to_collection", "collection_slug": "featured"}, {"event": {"entry_id": str(eid)}, "depth": 0}
        )
        assert calls["add_to_collection"] == [(str(eid), "featured", 1)]
        assert out == {"entry_id": str(eid), "op": "add_to_collection", "collection": "featured", "result": "added"}

    def test_remove_from_collection_calls_service(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        calls = self._spy_service(monkeypatch)
        eid = uuid4()
        run_entry_action(
            None, "G", {"kind": "entry", "op": "remove_from_collection", "collection_slug": "featured"}, {"event": {"entry_id": str(eid)}, "depth": 0}
        )
        assert calls["remove_from_collection"] and calls["remove_from_collection"][0][1] == "featured"

    def test_collection_ref_is_interpolated_from_event(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        calls = self._spy_service(monkeypatch)
        eid = uuid4()
        run_entry_action(
            None,
            "G",
            {"kind": "entry", "op": "add_to_collection", "collection_slug": "$event.payload.coll"},
            {"event": {"entry_id": str(eid), "payload": {"coll": "specials"}}, "depth": 0},
        )
        assert calls["add_to_collection"][0][1] == "specials"  # resolved from the payload

    def test_collection_op_without_collection_raises(self, monkeypatch):
        from marvin.services.automation.actions.entry import run_entry_action

        self._spy_service(monkeypatch)
        with pytest.raises(AutomationActionError):
            run_entry_action(None, "G", {"kind": "entry", "op": "add_to_collection"}, {"event": {"entry_id": str(uuid4())}, "depth": 0})

    def test_collection_dry_run_previews_without_calling_service(self, monkeypatch):
        import marvin.services.entries as entries_mod
        from marvin.services.automation.actions.entry import run_entry_action

        monkeypatch.setattr(entries_mod, "EntryService", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no service in dry run")))
        eid = uuid4()
        out = run_entry_action(
            None,
            "G",
            {"kind": "entry", "op": "add_to_collection", "collection_slug": "featured"},
            {"event": {"entry_id": str(eid)}, "depth": 0},
            dry_run=True,
        )
        assert out == {"dry_run": True, "kind": "entry", "op": "add_to_collection", "entity_id": str(eid), "collection": "featured"}


# ── Change detection: conditions on what an update changed ────────────────────
class TestChangedFieldConditions:
    def _run(self, conditions, event_ctx):
        auto = _automation(trigger="entry_updated", conditions=conditions, actions=[{"kind": "emit_event", "event": "noted"}])
        runner = _recording_runner()
        ran = engine.run_automations_for_event(_FakeSession([auto]), "G", event_ctx, run_action=runner)
        return ran

    def test_status_changed_to_review_matches(self):
        # The headline automation: "when status changes to review". before/after carry only changed
        # fields, so event.after.status == review means exactly that.
        ctx = {
            "event_type": "entry_updated",
            "entry_id": uuid4(),
            "user_id": None,
            "changed_fields": ["status"],
            "before": {"status": "draft"},
            "after": {"status": "needs_review"},
        }
        assert self._run([{"field": "event.after.status", "op": "eq", "value": "needs_review"}], ctx) == 1

    def test_status_unchanged_does_not_match(self):
        ctx = {
            "event_type": "entry_updated",
            "entry_id": uuid4(),
            "user_id": None,
            "changed_fields": ["title"],
            "before": {"title": "A"},
            "after": {"title": "B"},
        }
        # after.status is absent (only title changed) → never matches "changed to review"
        assert self._run([{"field": "event.after.status", "op": "eq", "value": "needs_review"}], ctx) == 0

    def test_changed_from_and_changed_fields_contains(self):
        ctx = {
            "event_type": "entry_updated",
            "entry_id": uuid4(),
            "user_id": None,
            "changed_fields": ["status"],
            "before": {"status": "draft"},
            "after": {"status": "needs_review"},
        }
        assert self._run([{"field": "event.before.status", "op": "eq", "value": "draft"}], ctx) == 1
        assert self._run([{"field": "event.changed_fields", "op": "contains", "value": "status"}], ctx) == 1


# ── Target selector: the FROM clause (set-based fan-out) ───────────────────────
class TestTargetSelector:
    def _entities(self):
        return [
            SimpleNamespace(id=uuid4(), entry_type=SimpleNamespace(slug="recipe"), status="draft", title="A", slug="a"),
            SimpleNamespace(id=uuid4(), entry_type=SimpleNamespace(slug="recipe"), status="draft", title="B", slug="b"),
        ]

    def _auto(self, conditions=None):
        return SimpleNamespace(
            slug="tag-all",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "manual"},
                "target": {"entity": "entry", "query": {"entry_type": "recipe", "status": "draft"}},
                "conditions": conditions or [],
                "actions": [{"kind": "operation", "op": "generate-tags"}],
            },
        )

    def test_action_runs_once_per_matched_entity(self, monkeypatch):
        from marvin.services.automation import engine, selector

        ents = self._entities()
        monkeypatch.setattr(selector, "resolve_target_entities", lambda *a, **k: (ents, 2))
        seen = []

        def runner(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
            seen.append(context.get("entry", {}).get("slug"))  # per-entity context is bound
            return {}

        res = engine.run_automation_now(_FakeSession([]), "G", self._auto(), run_action=runner)
        assert res["ran"] == 2
        assert set(seen) == {"a", "b"}

    def test_target_conditions_are_a_where_over_the_set(self, monkeypatch):
        # Even a MANUAL run applies conditions when there's a target (they're the WHERE clause).
        from marvin.services.automation import engine, selector

        ents = self._entities()
        ents[1].status = "published"  # only "a" is draft
        monkeypatch.setattr(selector, "resolve_target_entities", lambda *a, **k: (ents, 2))
        seen = []

        def runner(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False):
            seen.append(context.get("entry", {}).get("slug"))
            return {}

        auto = self._auto(conditions=[{"field": "entry.status", "op": "eq", "value": "draft"}])
        res = engine.run_automation_now(_FakeSession([]), "G", auto, run_action=runner)
        assert res["ran"] == 1 and seen == ["a"]


# ── Execution recording (observability) ───────────────────────────────────────
class _SpyRecorder:
    def __init__(self):
        self.started, self.actions, self.finished = [], [], []

    def start(self, automation, trigger_type, **kw):
        self.started.append({"slug": automation.slug, "trigger": trigger_type, **kw})
        return "EXEC-1"

    def action(self, exec_id, **kw):
        self.actions.append(kw)

    def finish(self, exec_id, **kw):
        self.finished.append(kw)


class TestExecutionRecording:
    def test_records_run_and_a_step_per_target(self, monkeypatch):
        from marvin.services.automation import engine, selector

        ents = [
            SimpleNamespace(id=uuid4(), entry_type=SimpleNamespace(slug="recipe"), status="draft", title="A", slug="a"),
            SimpleNamespace(id=uuid4(), entry_type=SimpleNamespace(slug="recipe"), status="draft", title="B", slug="b"),
        ]
        monkeypatch.setattr(selector, "resolve_target_entities", lambda *a, **k: (ents, 5))  # 5 matched, 2 returned (cap)
        auto = SimpleNamespace(
            slug="tag-all",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "manual"},
                "target": {"entity": "entry", "query": {"status": "draft"}},
                "conditions": [],
                "actions": [{"kind": "operation", "op": "generate-tags"}],
            },
        )
        spy = _SpyRecorder()
        engine.run_automation_now(_FakeSession([]), "G", auto, run_action=lambda *a, **k: {}, recorder=spy)

        assert len(spy.started) == 1
        assert spy.started[0]["targets_matched"] == 5 and spy.started[0]["capped"] is True
        assert len(spy.actions) == 2  # one step per matched target
        assert {a["target_index"] for a in spy.actions} == {0, 1}
        assert all(a["status"] == "success" for a in spy.actions)
        assert spy.finished[0]["status"] == "success" and spy.finished[0]["targets_run"] == 2
        assert spy.finished[0]["steps_ok"] == 2 and spy.finished[0]["steps_failed"] == 0

    def test_failed_step_marks_run_failed(self):
        from marvin.services.automation import engine
        from marvin.services.automation.runner import AutomationActionError

        auto = SimpleNamespace(
            slug="boom",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "manual"},
                "conditions": [],
                "actions": [{"kind": "operation", "op": "boom"}],
            },
        )

        def failing(*a, **k):
            raise AutomationActionError("nope")

        spy = _SpyRecorder()
        engine.run_automation_now(_FakeSession([]), "G", auto, run_action=failing, recorder=spy)
        assert spy.actions[0]["status"] == "failed" and spy.actions[0]["error"] == "nope"
        assert spy.finished[0]["status"] == "failed" and spy.finished[0]["steps_failed"] == 1

    def test_no_target_manual_run_records_once(self):
        from marvin.services.automation import engine

        auto = SimpleNamespace(
            slug="simple",
            enabled=True,
            group_id="G",
            definition={
                "trigger": {"type": "manual"},
                "conditions": [],
                "actions": [{"kind": "emit_event", "event": "noted"}],
            },
        )
        spy = _SpyRecorder()
        engine.run_automation_now(_FakeSession([]), "G", auto, run_action=lambda *a, **k: {}, recorder=spy)
        assert len(spy.started) == 1 and spy.started[0]["targets_matched"] == 1
        assert len(spy.actions) == 1 and spy.finished[0]["targets_run"] == 1


# ── Correlation id: one chain, one id ─────────────────────────────────────────
class TestCorrelationId:
    def test_scope_mints_inherits_and_overrides(self):
        from marvin.services.event_bus_service.correlation import correlation_scope, current_correlation_id

        assert current_correlation_id.get() is None
        with correlation_scope() as outer:  # no ambient → mint
            assert outer and current_correlation_id.get() == outer
            with correlation_scope() as inner:  # ambient set → inherit
                assert inner == outer
            with correlation_scope("fixed") as forced:  # explicit → use it
                assert forced == "fixed"
            assert current_correlation_id.get() == outer  # restored after inner scopes
        assert current_correlation_id.get() is None  # fully reset

    def test_engine_threads_the_events_correlation_to_the_execution(self):
        # The execution row is stamped with the TRIGGERING event's chain id (not a fresh one).
        auto = _automation(actions=[{"kind": "operation", "op": "generate-summary"}])
        spy = _SpyRecorder()
        ctx = {"event_type": "entry_published", "entry_id": None, "user_id": None, "correlation_id": "chain-42"}
        engine.run_automations_for_event(_FakeSession([auto], entry=_entry()), "G", ctx, run_action=lambda *a, **k: {}, recorder=spy)
        assert spy.started and spy.started[0]["correlation_id"] == "chain-42"

    def test_manual_run_mints_a_correlation_id(self):
        auto = SimpleNamespace(
            slug="m",
            created_by=None,
            enabled=True,
            group_id="G",
            definition={"trigger": {"type": "manual"}, "actions": [{"kind": "handler", "task": "x"}]},
        )
        spy = _SpyRecorder()
        engine.run_automation_now(_FakeSession([]), "G", auto, run_action=lambda *a, **k: {}, recorder=spy)
        assert spy.started and spy.started[0]["correlation_id"]  # a fresh, non-empty id

    def test_reemitted_events_inside_a_run_inherit_the_chain(self):
        # A real emit_event executor dispatched inside the engine's scope must carry the run's id.
        from marvin.services.event_bus_service.correlation import current_correlation_id

        seen = {}

        def fake_run(session, group_id, action, context, **_):
            seen["cid"] = current_correlation_id.get()  # what a dispatch inside here would resolve to
            return {}

        auto = _automation(actions=[{"kind": "emit_event", "event": "noted"}])
        ctx = {"event_type": "entry_published", "entry_id": None, "user_id": None, "correlation_id": "chain-9"}
        engine.run_automations_for_event(_FakeSession([auto], entry=_entry()), "G", ctx, run_action=fake_run)
        assert seen["cid"] == "chain-9"  # the executor (and its dispatches) see the chain id
