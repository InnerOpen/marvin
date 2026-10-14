"""Admin → AI pricing (services/ai/price_overrides.py, routes/admin/ai_prices_controller.py): an admin's price wins
over every other source, a model with no price shows as such, and Backfill gives its past runs a cost.

The case: gpt-6.1-sol ran in Mash & Burn with no price in the OpenAI plugin's table; its runs counted as $0."""

from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.ai import price_overrides, pricing
from tests import test_event_connections as evc
from tests.test_event_connections import world  # noqa: F401 — the fixture

NEW_MODEL = "test-unpriced-model-x"


@pytest.fixture(autouse=True)
def clean_overrides(db_session):
    from marvin.services.platform_settings import PlatformSettingsService

    def reset():
        PlatformSettingsService(db_session).set(price_overrides.SETTINGS_KEY, {"prices": []})
        price_overrides.clear_cache()

    reset()
    yield
    reset()


def _run(db_session, gid, *, model=NEW_MODEL, provider="openai", cost=None, status="completed", tokens=(1_000_000, 500_000), days_ago=1):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    row = AIExecutionModel(
        session=db_session,
        group_id=gid,
        operation_slug="generate-summary",
        provider_type=provider,
        model_id=model,
        status=status,
        trigger_type="api",
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        total_tokens=sum(tokens),
        estimated_cost_usd=cost,
    )
    row.created_at = datetime.now(UTC) - timedelta(days=days_ago)
    db_session.add(row)
    db_session.commit()
    return row


def _set(db_session, *rows):
    keys = ("provider", "model", "input_per_1m", "output_per_1m")
    return price_overrides.save_overrides(db_session, [dict(zip(keys, r, strict=True)) for r in rows])


# ── the lookup ────────────────────────────────────────────────────────────────


def test_an_override_prices_a_model_nothing_else_does_and_its_dated_snapshots(db_session):
    assert pricing.estimate_cost("openai", NEW_MODEL, 1_000_000, 1_000_000) is None
    _set(db_session, ("openai", NEW_MODEL, 2.0, 8.0))
    assert pricing.estimate_cost("openai", NEW_MODEL, 1_000_000, 1_000_000) == pytest.approx(10.0)
    assert pricing.estimate_cost("openai", f"{NEW_MODEL}-2026-10-01", 1_000_000, 0) == pytest.approx(2.0)


def test_an_override_wins_over_the_providers_own_price(db_session, monkeypatch):
    from types import SimpleNamespace

    from marvin_integration_sdk.ai import ModelPrice

    from marvin.services.ai import registry

    own = ModelPrice(3.0, 15.0)
    vendor = SimpleNamespace(estimate_cost=lambda model, p, c, cached=0, written=0: own.cost(p, c, cached, written), self_hosted=False, prices={"claude-x": own})
    monkeypatch.setattr(registry, "find_class", lambda slug: vendor if slug == "anthropic" else None)

    assert pricing.estimate_cost("anthropic", "claude-x", 1_000_000, 0) == pytest.approx(3.0)
    _set(db_session, ("anthropic", "claude-x", 0.5, 0.5))
    assert pricing.estimate_cost("anthropic", "claude-x", 1_000_000, 0) == pytest.approx(0.5)


@pytest.mark.parametrize(
    "row, message",
    [
        ({"provider": "openai", "model": "", "input_per_1m": 1, "output_per_1m": 1}, "required"),
        ({"provider": "openai", "model": "m", "input_per_1m": -1, "output_per_1m": 1}, "between 0"),
        ({"provider": "openai", "model": "m", "input_per_1m": 1, "output_per_1m": 1e9}, "between 0"),
        ({"provider": "openai", "model": "m", "input_per_1m": "lots", "output_per_1m": 1}, "must be a number"),
    ],
)
def test_bad_prices_are_refused(row, message):
    with pytest.raises(price_overrides.PriceError, match=message):
        price_overrides.validate([row])


def test_saving_says_what_changed_for_the_audit(db_session):
    _, first = _set(db_session, ("openai", "a", 1, 2), ("openai", "b", 3, 4))
    _, second = _set(db_session, ("openai", "a", 1, 2), ("openai", "c", 5, 6), ("openai", "b", 3, 9))

    assert first == ["openai a: set to $1 in / $2 out per 1M", "openai b: set to $3 in / $4 out per 1M"]
    assert "openai b: $3 in / $9 out per 1M (was $3 / $4)" in second and "openai c: set to $5 in / $6 out per 1M" in second
    assert not any(line.startswith("openai a") for line in second)  # unchanged: nothing to audit
    _, third = _set(db_session, ("openai", "c", 5, 6))
    assert sorted(third) == ["openai a: override removed", "openai b: override removed"]


# ── backfill and the list ─────────────────────────────────────────────────────


def test_backfill_prices_the_runs_that_went_unpriced(db_session, world):  # noqa: F811
    done = _run(db_session, world.a)
    failed = _run(db_session, world.a, status="failed")
    assert price_overrides.backfill(db_session, "openai", NEW_MODEL) == 0  # still no price: nothing changes
    _set(db_session, ("openai", NEW_MODEL, 2.0, 8.0))

    assert price_overrides.backfill(db_session, "openai", NEW_MODEL) == 1
    db_session.refresh(done), db_session.refresh(failed)
    assert done.estimated_cost_usd == pytest.approx(2.0 + 4.0) and failed.estimated_cost_usd is None


def test_the_list_shows_unpriced_models_in_use_and_where_each_price_comes_from(db_session, world):  # noqa: F811
    _run(db_session, world.a)
    _run(db_session, world.a)
    _run(db_session, world.a, days_ago=200)  # past the log's window: not "in use"
    _run(db_session, world.a, provider="ollama", model="llama-local", cost=0.0)
    rows = {(r["provider"], r["model"]): r for r in price_overrides.price_list(db_session)}

    mine = rows[("openai", NEW_MODEL)]
    assert (mine["source"], mine["runs"], mine["unpriced_runs"], mine["input_per_1m"]) == ("none", 2, 2, None)
    assert rows[("ollama", "llama-local")]["source"] == "self_hosted"  # free is a price: not flagged

    _set(db_session, ("openai", NEW_MODEL, 2.0, 8.0))
    mine = {(r["provider"], r["model"]): r for r in price_overrides.price_list(db_session)}[("openai", NEW_MODEL)]
    assert (mine["source"], mine["overridden"], mine["input_per_1m"]) == ("override", True, 2.0)


# ── the admin API ─────────────────────────────────────────────────────────────


def _admin(world):  # noqa: F811
    return evc._client(world, WorkspaceRole.OWNER, platform_role=PlatformRole.SUPER_ADMIN)


def test_only_a_platform_admin_reads_or_sets_prices(db_session, world):  # noqa: F811
    assert evc._client(world, WorkspaceRole.OWNER).get("/api/admin/ai-prices").status_code == 403
    assert _admin(world).get("/api/admin/ai-prices").status_code == 200


def test_setting_prices_through_the_api_is_validated_and_audited(db_session, world):  # noqa: F811
    from marvin.db.models.platform.event_log import EventLogModel

    client = _admin(world)
    bad = client.put("/api/admin/ai-prices/overrides", json={"prices": [{"provider": "openai", "model": "m", "inputPer1m": -1, "outputPer1m": 1}]})
    assert bad.status_code == 422 and "between 0" in bad.text

    ok = client.put(
        "/api/admin/ai-prices/overrides", json={"prices": [{"provider": "openai", "model": NEW_MODEL, "inputPer1m": 2, "outputPer1m": 8}]}
    )
    assert ok.status_code == 200, ok.text
    assert any(r["model"] == NEW_MODEL and r["source"] == "override" for r in ok.json()["prices"])

    db_session.expire_all()
    mine = db_session.query(EventLogModel).filter(EventLogModel.event_type == "platform_settings_changed", EventLogModel.user_id == world.ua)
    try:
        assert any(NEW_MODEL in (e.message_body or "") for e in mine.all())
    finally:
        mine.delete(synchronize_session=False)  # a platform event holds the test user: drop it before the world is purged
        db_session.commit()

    _run(db_session, world.a)
    filled = client.post("/api/admin/ai-prices/backfill", json={"provider": "openai", "model": NEW_MODEL})
    assert filled.json()["updated"] >= 1


def test_cached_and_written_prompt_tokens_cost_the_cache_rates():
    """A plugin's price carries the vendor's cache rates; an admin override has none, so there a cached token costs the
    input rate (never cheaper than reality)."""
    from marvin.services.ai import pricing

    full = pricing.estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 0)
    cached = pricing.estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 0, cached_prompt_tokens=1_000_000)
    written = pricing.estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 0, cache_write_tokens=1_000_000)
    assert full == pytest.approx(2.0) and cached == pytest.approx(0.2) and written == pytest.approx(2.5)
    assert pricing.estimate_cost("openai", "gpt-5.4-mini", 1_000_000, 0, cached_prompt_tokens=1_000_000) == pytest.approx(0.075)

    class Usage:
        prompt_tokens, completion_tokens, cached_prompt_tokens, cache_write_tokens = 1_000_000, 0, 500_000, 0

    assert pricing.cost_of("anthropic", "claude-sonnet-5", Usage()) == pytest.approx(1.0 + 0.1)
