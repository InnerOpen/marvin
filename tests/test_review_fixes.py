"""Bugs the 2026-10-02 manual review found in code (the docs describe what the code does)."""

from types import SimpleNamespace


def test_apply_many_applies_with_the_chosen_connection(monkeypatch):
    # POST /apply?integration_id= used to be ignored when applying several, so a workspace with two
    # connections of the same provider got the wrong (or no) connection.
    from marvin.services.blueprints import apply as apply_mod

    seen = []
    monkeypatch.setattr(apply_mod, "apply_blueprint", lambda s, g, b, p, integration_id=None, actor_id=None: seen.append(integration_id) or b.slug)
    blueprints = [SimpleNamespace(slug="wf", kind="workflow"), SimpleNamespace(slug="hook", kind="incoming_webhook")]

    apply_mod.apply_many(None, "G", blueprints, integration_id="INTEG-2")

    assert seen == ["INTEG-2", "INTEG-2"]


def test_a_workflow_run_from_chat_is_recorded(monkeypatch):
    # run_workflow (the agent / MCP 'Chat' trigger) ran without a recorder, so it never showed in Runs.
    import json

    from marvin.services.ai.tools import builtins
    from marvin.services.automation import engine
    from marvin.services.automation.recorder import ExecutionRecorder

    auto = SimpleNamespace(slug="tidy", enabled=True, id="A1", name="Tidy")
    monkeypatch.setattr(builtins, "_find_workflow", lambda s, g, ref: auto)
    captured = {}
    monkeypatch.setattr(engine, "run_automation_now", lambda *a, **k: captured.update(k) or {"ok": True, "result": None})

    out = json.loads(builtins.run_workflow(SimpleNamespace(session=object(), group_id="G", user=None, logger=None), {"workflow": "tidy"}))

    assert out["ok"] is True and isinstance(captured.get("recorder"), ExecutionRecorder)
