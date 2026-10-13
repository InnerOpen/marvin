"""Unit tests for the integration provider registry (services/integrations).

Integrations are an optional, plugin-only feature: the provider contract lives in the standalone
``marvin_integration_sdk`` package, which Marvin core does not depend on. These tests exercise the
core mechanics Marvin owns — entry-point discovery, the orphaned-row read path, the event-listener
action dispatcher, and capability handler ordering. They require the SDK to construct fixtures, so
the whole module skips cleanly when no integration package is installed.

Provider-specific behaviour (rss parsing, vercel check logic) lives with each provider's own repo
and is tested there, not here.
"""

import logging
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")


_LOG = logging.getLogger("test")


def test_orphaned_row_reads_as_unavailable():
    # A row whose provider package isn't installed must surface as unavailable, not a stale status.
    from marvin.routes.groups.integrations_controller import _to_read

    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider="ghost_provider",
        name="Ghost",
        slug="ghost",
        enabled=True,
        config=None,
        secret_ref=None,
        status="ok",
        last_checked_at=None,
        last_error=None,
        error_overrides=None,
    )
    read = _to_read(row)
    assert read.status == "unavailable"
    assert "not installed" in (read.last_error or "")


def test_entry_point_discovery_is_resilient(monkeypatch):
    # A good plugin registers (with its distribution version); a broken one is reported failed and
    # skipped — it must not take down discovery of the others.
    from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider

    import marvin.services.integrations.loader as loader

    class _GoodProvider(IntegrationProvider):
        slug = "test_good"
        name = "Test Good"

    def _boom():
        raise RuntimeError("boom")

    class _EP:
        def __init__(self, name, fn, dist):
            self.name, self._fn, self.dist = name, fn, dist

        def load(self):
            return self._fn()

    class _Dist:
        def __init__(self, name, version):
            self.name, self.version = name, version

    eps = [
        _EP("good", lambda: _GoodProvider, _Dist("marvin-integration-good", "1.2.3")),
        _EP("bad", _boom, _Dist("marvin-integration-bad", "0.1")),
    ]
    monkeypatch.setattr(loader.importlib_metadata, "entry_points", lambda group=None: eps)
    try:
        reports = {r.name: r for r in loader._load_entry_points()}
        assert reports["good"].ok
        assert reports["good"].slugs == ["test_good"]
        assert reports["good"].version == "1.2.3"
        assert not reports["bad"].ok
        assert "boom" in (reports["bad"].error or "")
        assert "test_good" in INTEGRATION_REGISTRY
    finally:
        INTEGRATION_REGISTRY.pop("test_good", None)


def test_event_listener_runs_action_with_templated_args():
    # The core "consume integration via events" mechanism: a connected action fires when its event
    # does, with {{field}} placeholders filled from the event.
    from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction, register_provider

    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener

    calls: list = []

    class _RecorderProvider(IntegrationProvider):
        slug = "recorder"
        name = "Recorder"
        actions = (ProviderAction(key="do", label="Do"),)

        def run_action(self, key, args, ctx):
            calls.append((key, args))
            return {"ok": True}

    register_provider(_RecorderProvider)

    class _EvType:
        name = "entry-published"

    class _Event:
        event_type = _EvType()
        document_data = {"title": "Hello World", "slug": "hello"}
        entity_id = uuid.uuid4()
        entity_type = "entry"
        message = "published"

    try:
        listener = IntegrationEventListener(group_id=uuid.uuid4())
        sub = {
            "name": "My Slack",
            "provider": "recorder",
            "config": {},
            "secret_ref": None,
            "action": "do",
            "args": {"text": "New: {{title}} ({{entity_type}})"},
        }
        listener.publish_to_subscribers(_Event(), [sub])
        assert calls == [("do", {"text": "New: Hello World (entry)"})]
    finally:
        INTEGRATION_REGISTRY.pop("recorder", None)


def test_event_listener_skips_uninstalled_provider():
    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener

    class _EvType:
        name = "entry-published"

    class _Event:
        event_type = _EvType()
        document_data = {}
        entity_id = None
        entity_type = None
        message = ""

    listener = IntegrationEventListener(group_id=uuid.uuid4())
    # No exception even though provider isn't installed — just logged and skipped.
    listener.publish_to_subscribers(_Event(), [{"name": "Gone", "provider": "ghost", "config": {}, "secret_ref": None, "action": "x", "args": {}}])


def test_template_substitution():
    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener

    out = IntegrationEventListener._template(
        {"text": "Hi {{name}}", "nested": {"k": "{{missing}}"}, "list": ["{{name}}"]},
        {"name": "Sam"},
    )
    assert out == {"text": "Hi Sam", "nested": {"k": "{{missing}}"}, "list": ["Sam"]}


def test_provider_action_advertises_capability_in_info():
    from marvin_integration_sdk import IntegrationProvider, ProviderAction

    class _CapProvider(IntegrationProvider):
        slug = "capx"
        name = "CapX"
        actions = (ProviderAction(key="g", label="Generate", capability="image.generate", priority=3, cost_hint="paid", requires_approval=True),)

    action = _CapProvider().info()["actions"][0]
    assert action["capability"] == "image.generate"
    assert action["priority"] == 3
    assert action["cost_hint"] == "paid"
    assert action["requires_approval"] is True


def test_capability_handlers_sort_by_priority_and_invoke():
    from marvin_integration_sdk import IntegrationProvider, ProviderAction

    from marvin.services.integrations.capability import _build_handlers, _Snapshot

    calls: list = []

    class _Gen(IntegrationProvider):
        slug = "imggen"
        name = "Img Gen"
        actions = (ProviderAction(key="gen", label="Gen", capability="image.generate", priority=5),)

        def run_action(self, key, args, ctx):
            calls.append((key, args))
            return {"images": [{"image_b64": "abc"}]}

    provider = _Gen()

    def snap(priority: int, name: str) -> _Snapshot:
        return _Snapshot(
            provider=provider,
            action_key="gen",
            capability="image.generate",
            priority=priority,
            cost_hint=None,
            requires_approval=False,
            config={},
            secret_ref=None,
            integration_id=uuid.uuid4(),
            integration_name=name,
            group_id=uuid.uuid4(),
            model=None,
        )

    handlers = _build_handlers([snap(1, "low"), snap(9, "high"), snap(5, "mid")], uuid.uuid4(), lambda ref, gid: None)
    # highest-priority first — the resolver takes the top that succeeds
    assert [h.integration_name for h in handlers] == ["high", "mid", "low"]
    # uniform invoke → canonical outputs; metadata surfaced for the resolver
    out = handlers[0].invoke({"prompt": "a cat"})
    assert out == {"images": [{"image_b64": "abc"}]}
    assert calls == [("gen", {"prompt": "a cat"})]
    assert handlers[0].capability == "image.generate"
    assert handlers[0].requires_approval is False


def test_installed_provider_reads_normally():
    # A registered provider is required for a non-"unavailable" read; register a stub for the slug.
    from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, register_provider

    from marvin.routes.groups.integrations_controller import _to_read

    class _StubProvider(IntegrationProvider):
        slug = "stub_feed"
        name = "Stub Feed"

    register_provider(_StubProvider)
    try:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            provider="stub_feed",
            name="My feed",
            slug="my_feed",
            enabled=True,
            config={"feed_url": "https://x/feed"},
            secret_ref=None,
            status="ok",
            last_checked_at=None,
            last_error=None,
            error_overrides=None,
        )
        read = _to_read(row)
        assert read.status == "ok"
        assert read.last_error is None
    finally:
        INTEGRATION_REGISTRY.pop("stub_feed", None)
