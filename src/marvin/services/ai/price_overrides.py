"""Admin → AI pricing: a platform admin's own price per provider/model, and the price list it is set against.

The lookup (services/ai/pricing.py `estimate_cost`) is: an admin override here, then the provider's own table
(its plugin's `prices`; self-hosted → 0), then core's fallback table. An override fixes what nothing else
prices (a model newer than its plugin's table) or what a table gets wrong, without waiting for a release.

Overrides live in `platform_settings` (`ai_price_overrides`). `estimate_cost` runs without a session, often
many times a request, so it reads them through a short cache that a save in this process clears at once
(another replica sees the change within CACHE_SECONDS).

`backfill` gives the runs that went unpriced (stored with no cost, so the monthly limit couldn't see them) the
cost the model's price now gives them.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from marvin_integration_sdk.ai import ModelPrice, price_for

SETTINGS_KEY = "ai_price_overrides"
CACHE_SECONDS = 60
MAX_PRICE_PER_1M = 10_000.0  # USD per million tokens: anything higher is a typo, not a model
RECENT_DAYS = 90  # the execution log's default retention: "models in use"

_cache: dict[str, dict[str, ModelPrice]] | None = None
_cache_at = 0.0
_lock = threading.Lock()


class PriceError(ValueError):
    """An override that can't be stored (the message says why)."""


def _rows(value: dict | None) -> list[dict]:
    return list((value or {}).get("prices") or [])


def _to_table(rows: list[dict]) -> dict[str, dict[str, ModelPrice]]:
    table: dict[str, dict[str, ModelPrice]] = {}
    for row in rows:
        try:
            table.setdefault(row["provider"], {})[row["model"]] = ModelPrice(float(row["input_per_1m"]), float(row["output_per_1m"]))
        except (KeyError, TypeError, ValueError):
            continue  # a hand-edited row that doesn't parse prices nothing, never breaks estimates
    return table


def overrides() -> dict[str, dict[str, ModelPrice]]:
    """provider → model → price, from platform settings (cached)."""
    global _cache, _cache_at
    with _lock:
        if _cache is not None and time.monotonic() - _cache_at < CACHE_SECONDS:
            return _cache
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.platform_settings import PlatformSettingsService

        with session_context() as session:
            table = _to_table(_rows(PlatformSettingsService(session).get(SETTINGS_KEY)))
    except Exception:  # noqa: BLE001 — no database (a script, a test): no overrides, estimates still work
        table = {}
    with _lock:
        _cache, _cache_at = table, time.monotonic()
    return table


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def override_for(provider_type: str, model_id: str) -> ModelPrice | None:
    """The admin's price for this model (exact id, or a dated snapshot of one), or None."""
    return price_for(overrides().get(provider_type, {}), model_id)


def list_overrides(session) -> list[dict]:
    from marvin.services.platform_settings import PlatformSettingsService

    return _rows(PlatformSettingsService(session).get(SETTINGS_KEY))


def validate(rows: list[dict]) -> list[dict]:
    """The rows as stored: provider, model, input_per_1m, output_per_1m, updated_at. Raises PriceError."""
    seen: set[tuple[str, str]] = set()
    clean = []
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for i, row in enumerate(rows, 1):
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        if not provider or not model:
            raise PriceError(f"row {i}: provider and model are required")
        if (provider, model) in seen:
            raise PriceError(f"row {i}: {provider} {model} is listed twice")
        seen.add((provider, model))
        prices = []
        for key in ("input_per_1m", "output_per_1m"):
            try:
                value = float(row[key])
            except (KeyError, TypeError, ValueError):
                raise PriceError(f"row {i}: {key} must be a number (USD per million tokens)") from None
            if not 0 <= value <= MAX_PRICE_PER_1M:
                raise PriceError(f"row {i}: {key} must be between 0 and {MAX_PRICE_PER_1M:g} USD per million tokens")
            prices.append(value)
        clean.append(
            {"provider": provider, "model": model, "input_per_1m": prices[0], "output_per_1m": prices[1], "updated_at": row.get("updated_at") or now}
        )
    return clean


def save_overrides(session, rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Replace the overrides; returns (stored rows, what changed — one line each, for the audit event)."""
    from marvin.services.platform_settings import PlatformSettingsService

    before = {(r["provider"], r["model"]): r for r in list_overrides(session)}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    clean = validate(rows)
    changes = []
    for row in clean:
        key = (row["provider"], row["model"])
        old = before.pop(key, None)
        if old is None:
            changes.append(f"{key[0]} {key[1]}: set to ${row['input_per_1m']:g} in / ${row['output_per_1m']:g} out per 1M")
            row["updated_at"] = now
        elif (old.get("input_per_1m"), old.get("output_per_1m")) != (row["input_per_1m"], row["output_per_1m"]):
            was = f"was ${old.get('input_per_1m'):g} / ${old.get('output_per_1m'):g}"
            changes.append(f"{key[0]} {key[1]}: ${row['input_per_1m']:g} in / ${row['output_per_1m']:g} out per 1M ({was})")
            row["updated_at"] = now
        else:
            row["updated_at"] = old.get("updated_at") or now
    changes += [f"{p} {m}: override removed" for p, m in before]
    PlatformSettingsService(session).set(SETTINGS_KEY, {"prices": clean})
    clear_cache()
    return clean, changes


def backfill(session, provider_type: str, model_id: str) -> int:
    """Price the runs of this model that have no cost (completed, used tokens) with its price now. Returns how
    many were updated; 0 when the model still has no price."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    from .pricing import estimate_cost

    runs = (
        session.query(Run)
        .filter(Run.provider_type == provider_type, Run.model_id == model_id, Run.status == "completed")
        .filter(Run.estimated_cost_usd.is_(None), Run.total_tokens > 0)
        .all()
    )
    updated = 0
    for run in runs:
        cost = estimate_cost(
            provider_type, model_id, run.prompt_tokens or 0, run.completion_tokens or 0, run.cached_prompt_tokens or 0, run.cache_write_tokens or 0
        )
        if cost is None:
            return 0
        run.estimated_cost_usd = cost
        updated += 1
    session.commit()
    return updated


def price_list(session, now: datetime | None = None) -> list[dict]:
    """Every model Marvin knows a price for or has seen run lately, per provider: its effective price and
    where it comes from (override | provider | self_hosted | feed | none), with the last RECENT_DAYS of runs
    and how many of those have no cost."""
    from datetime import timedelta

    from sqlalchemy import case, func

    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    from . import registry

    since = (now or datetime.now(UTC)) - timedelta(days=RECENT_DAYS)
    unpriced = case((Run.estimated_cost_usd.is_(None) & (Run.total_tokens > 0) & (Run.status == "completed"), 1), else_=0)
    usage = {
        (p, m): (int(n), int(u or 0))
        for p, m, n, u in session.query(Run.provider_type, Run.model_id, func.count(Run.id), func.sum(unpriced))
        .filter(Run.created_at >= since)
        .group_by(Run.provider_type, Run.model_id)
        .all()
    }
    mine = overrides()
    models: set[tuple[str, str]] = set(usage)
    for provider, table in mine.items():
        models |= {(provider, m) for m in table}
    for slug in registry.plugins():
        cls = registry.find_class(slug)
        models |= {(slug, m) for m in (getattr(cls, "prices", None) or {})}

    out = []
    for provider, model in sorted(models):
        price, source = _effective(provider, model, mine)
        runs, no_cost = usage.get((provider, model), (0, 0))
        out.append(
            {
                "provider": provider,
                "model": model,
                "source": source,
                "input_per_1m": price.input_per_1m if price else None,
                "output_per_1m": price.output_per_1m if price else None,
                "overridden": price_for(mine.get(provider, {}), model) is not None,
                "runs": runs,
                "unpriced_runs": no_cost,
            }
        )
    return out


def _effective(provider: str, model: str, mine) -> tuple[ModelPrice | None, str]:
    from . import pricing, registry

    if (price := price_for(mine.get(provider, {}), model)) is not None:
        return price, "override"
    cls = registry.find_class(provider)
    if cls is not None and (price := price_for(getattr(cls, "prices", None) or {}, model)) is not None:
        return price, "provider"
    if (cls is not None and getattr(cls, "self_hosted", False)) or provider in pricing._SELF_HOSTED:
        return ModelPrice(0.0, 0.0), "self_hosted"
    from .price_feed import feed_price_for

    if (price := feed_price_for(provider, model)) is not None:
        return price, "feed"
    return None, "none"
