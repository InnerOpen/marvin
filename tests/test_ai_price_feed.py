"""The daily AI price feed (services/ai/price_feed.py): LiteLLM's format read for the vendors Marvin has providers
for, from a URL an admin can change, never trusted blindly (https, size cap, last good prices kept on failure), and
consulted after an admin's own price and the provider's table.

The case: gpt-6.1-sol — no price in the OpenAI plugin's table, $2 / $10 per 1M in LiteLLM's list."""

import json
from types import SimpleNamespace

import httpx
import pytest

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.ai import price_feed, price_overrides, pricing
from tests import test_event_connections as evc
from tests.test_event_connections import world  # noqa: F401 — the fixture

# Real entries from model_prices_and_context_window.json (2026-10-10), plus ones that must be left out.
FEED = {
    "sample_spec": {"litellm_provider": "openai", "input_cost_per_token": "price per token"},
    "gpt-6.1-sol": {"litellm_provider": "openai", "input_cost_per_token": 2e-06, "output_cost_per_token": 1e-05, "mode": "chat"},
    "azure/gpt-4o-mini": {"litellm_provider": "azure", "input_cost_per_token": 1.5e-07, "output_cost_per_token": 6e-07},
    "azure/eu/gpt-6.1-sol": {"litellm_provider": "azure", "input_cost_per_token": 2.2e-06, "output_cost_per_token": 1.1e-05},
    "claude-sonnet-5": {"litellm_provider": "anthropic", "input_cost_per_token": 2e-06, "output_cost_per_token": 1e-05},
    "gemini/gemini-2.5-flash": {"litellm_provider": "gemini", "input_cost_per_token": 3e-07, "output_cost_per_token": 2.5e-06},
    "gemini/gemini-embedding-001": {"litellm_provider": "gemini", "input_cost_per_token": 1.5e-07},
    "accounts/fireworks/models/x": {"litellm_provider": "fireworks_ai", "input_cost_per_token": 1e-06, "output_cost_per_token": 1e-06},
}


@pytest.fixture(autouse=True)
def clean(db_session):
    from marvin.services.platform_settings import PlatformSettingsService

    def reset():
        PlatformSettingsService(db_session).set(price_feed.SETTINGS_KEY, {})
        PlatformSettingsService(db_session).set(price_overrides.SETTINGS_KEY, {"prices": []})
        price_feed.clear_cache()
        price_overrides.clear_cache()

    reset()
    yield
    reset()


def _server(body=FEED, status=200):
    def handle(request):
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(status, content=content)

    return httpx.MockTransport(handle)


# ── reading LiteLLM's format ─────────────────────────────────────────────────


def test_it_keeps_marvins_vendors_strips_prefixes_and_prices_per_million():
    table = price_feed.parse(FEED)
    assert table == {
        "openai": {"gpt-6.1-sol": [2.0, 10.0]},
        "azure": {"gpt-4o-mini": [0.15, 0.6]},  # azure/eu/…: a regional route, not a model id
        "anthropic": {"claude-sonnet-5": [2.0, 10.0]},
        "google": {"gemini-2.5-flash": [0.3, 2.5], "gemini-embedding-001": [0.15, 0.0]},
    }


@pytest.mark.parametrize(
    "transport, message",
    [
        (_server(status=404), "answered 404"),
        (_server(body=b"not json"), "not valid JSON"),
        (_server(body={"x": {"litellm_provider": "bedrock", "input_cost_per_token": 1e-6}}), "no prices for OpenAI"),
        (_server(body=b"[" + b" " * (price_feed.MAX_BYTES + 10) + b"]"), "larger than"),
    ],
)
def test_a_bad_feed_is_refused_with_the_reason(transport, message):
    with pytest.raises(price_feed.FeedError, match=message):
        price_feed.fetch("https://feed.test/prices.json", transport)


def test_only_https_urls_and_empty_means_off(db_session):
    with pytest.raises(price_feed.FeedError, match="https"):
        price_feed.set_url(db_session, "http://feed.test/prices.json")
    price_feed.set_url(db_session, "")
    assert price_feed.effective_url(db_session) == ""
    price_feed.set_url(db_session, None)
    assert price_feed.effective_url(db_session) == price_feed.default_url()


# ── refreshing ───────────────────────────────────────────────────────────────


def test_a_failed_refresh_keeps_the_last_good_prices_and_says_why(db_session):
    price_feed.set_url(db_session, "https://feed.test/prices.json")
    price_feed.refresh(db_session, _server())
    with pytest.raises(price_feed.FeedError):
        price_feed.refresh(db_session, _server(status=503))

    state = price_feed.status(db_session)
    assert state["models"] == 5 and state["fetched_from"] == "https://feed.test/prices.json"
    assert "503" in state["error"]
    assert price_feed.feed_price_for("openai", "gpt-6.1-sol").input_per_1m == 2.0


# ── where it sits in the lookup ──────────────────────────────────────────────


def test_the_feed_prices_what_nothing_else_does_and_yields_to_your_price(db_session):
    price_feed.set_url(db_session, "https://feed.test/prices.json")
    price_feed.refresh(db_session, _server())

    assert pricing.estimate_cost("openai", "gpt-6.1-sol", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert pricing.estimate_cost("openai", "gpt-6.1-sol-2026-09-29", 1_000_000, 0) == pytest.approx(2.0)  # a dated snapshot
    price_overrides.save_overrides(db_session, [{"provider": "openai", "model": "gpt-6.1-sol", "input_per_1m": 1, "output_per_1m": 1}])
    assert pricing.estimate_cost("openai", "gpt-6.1-sol", 1_000_000, 1_000_000) == pytest.approx(2.0)


def test_a_providers_own_price_wins_over_the_feed(db_session, monkeypatch):
    from marvin_integration_sdk.ai import ModelPrice

    from marvin.services.ai import registry

    own = SimpleNamespace(estimate_cost=lambda model, p, c, cached=0, written=0: ModelPrice(9, 9).cost(p, c, cached, written), self_hosted=False, prices={"gpt-6.1-sol": ModelPrice(9, 9)})
    monkeypatch.setattr(registry, "find_class", lambda slug: own if slug == "openai" else None)
    price_feed.set_url(db_session, "https://feed.test/prices.json")
    price_feed.refresh(db_session, _server())
    assert pricing.estimate_cost("openai", "gpt-6.1-sol", 1_000_000, 0) == pytest.approx(9.0)


# ── the scheduled task and the API ───────────────────────────────────────────


def test_the_daily_task_refreshes_skips_when_off_and_fails_loudly(db_session, monkeypatch):
    from contextlib import contextmanager

    from marvin.services.scheduled_tasks.handlers import ai
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    @contextmanager
    def this_session():
        yield db_session

    monkeypatch.setattr(ai, "session_context", this_session)
    task = SimpleNamespace(group_id=None, task_config={})
    handler = ai.RefreshAIPriceFeedHandler()

    price_feed.set_url(db_session, "")
    assert handler.execute(task, None) is None  # off: nothing to log
    price_feed.set_url(db_session, "https://feed.test/prices.json")
    monkeypatch.setattr(price_feed, "fetch", lambda url, transport=None: price_feed.parse(FEED))
    assert handler.execute(task, None) == "Priced 5 models from https://feed.test/prices.json"

    def down(url, transport=None):
        raise price_feed.FeedError("feed.test answered 503")

    monkeypatch.setattr(price_feed, "fetch", down)
    with pytest.raises(price_feed.FeedError):
        handler.execute(task, None)
    assert any(d.task_type == "refresh_ai_price_feed" and d.enabled for d in SYSTEM_SCHEDULED_TASKS)


def test_the_admin_sets_the_url_and_sees_the_status(db_session, world, monkeypatch):  # noqa: F811
    from marvin.db.models.platform.event_log import EventLogModel

    client = evc._client(world, WorkspaceRole.OWNER, platform_role=PlatformRole.SUPER_ADMIN)
    assert client.put("/api/admin/ai-prices/feed", json={"url": "http://feed.test/x.json"}).status_code == 422

    ok = client.put("/api/admin/ai-prices/feed", json={"url": "https://feed.test/x.json"})
    assert ok.status_code == 200 and ok.json()["url"] == "https://feed.test/x.json" and ok.json()["customUrl"] == "https://feed.test/x.json"
    monkeypatch.setattr(price_feed, "fetch", lambda url, transport=None: price_feed.parse(FEED))
    refreshed = client.post("/api/admin/ai-prices/feed/refresh").json()
    assert refreshed["models"] == 5 and refreshed["error"] is None
    assert client.get("/api/admin/ai-prices").json()["feed"]["models"] == 5

    db_session.expire_all()
    mine = db_session.query(EventLogModel).filter(EventLogModel.event_type == "platform_settings_changed", EventLogModel.user_id == world.ua)
    try:
        assert any("price feed URL: https://feed.test/x.json" in (e.message_body or "") for e in mine.all())
    finally:
        mine.delete(synchronize_session=False)
        db_session.commit()


def test_cache_rates_ride_along_when_the_feed_has_them():
    """cache_read_input_token_cost / cache_creation_input_token_cost become the price's cache rates; a model without
    them keeps the two-value row (and costs the input rate for cached tokens)."""
    feed = {
        "claude-sonnet-5": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 1e-5,
            "cache_read_input_token_cost": 2e-7,
            "cache_creation_input_token_cost": 2.5e-6,
        },
        "gpt-6.1-sol": {
            "litellm_provider": "openai",
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 1e-5,
            "cache_read_input_token_cost": 2e-7,
        },
        "plain": {"litellm_provider": "openai", "input_cost_per_token": 1e-6, "output_cost_per_token": 1e-6},
    }
    table = price_feed.parse(feed)
    assert table["anthropic"]["claude-sonnet-5"] == [2.0, 10.0, 0.2, 2.5]
    assert table["openai"]["gpt-6.1-sol"] == [2.0, 10.0, 0.2]
    assert table["openai"]["plain"] == [1.0, 1.0]
    sonnet = price_feed._price(table["anthropic"]["claude-sonnet-5"])
    assert sonnet.cost(1_000_000, 0, cached_prompt_tokens=1_000_000) == 0.2
    assert price_feed._price(table["openai"]["plain"]).cost(1_000_000, 0, cached_prompt_tokens=1_000_000) == 1.0
