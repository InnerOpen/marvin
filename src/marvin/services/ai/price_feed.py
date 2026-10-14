"""The daily AI price feed: a public price list as the last source a model's price can come from.

The lookup (services/ai/pricing.py `estimate_cost`): an admin's override, the provider's own table, self-hosted
(0), **this feed**, then core's old table. No vendor publishes a price API for its own models, so the feed is a
maintained list in LiteLLM's format (`model_prices_and_context_window.json`, MIT): keys are model ids, each with
``litellm_provider`` and ``input_cost_per_token`` / ``output_cost_per_token`` in USD.

The URL is configurable (Jared, 2026-10-10): ``AI_PRICE_FEED_URL`` sets the default (LiteLLM's file on GitHub),
and Admin → AI Pricing can point it elsewhere (a mirror, a self-hosted copy in the same format) or switch it off
(empty). Only https, at most MAX_BYTES. Only the vendors Marvin has providers for are kept (FEED_PROVIDERS), with
the provider prefix stripped (``azure/gpt-4o`` → azure ``gpt-4o``) and prices per million tokens.

Stored in `platform_settings` (``ai_price_feed``) with when it was fetched and how many models it priced. A
failed refresh keeps the last good prices and records the error (the page shows it; the scheduled task's run
fails, so its failure alerts fire).
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from marvin_integration_sdk.ai import ModelPrice, price_for

SETTINGS_KEY = "ai_price_feed"
DEFAULT_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 30
CACHE_SECONDS = 60
PER_MILLION = 1_000_000

# LiteLLM's provider name → Marvin's provider slug. Other vendors' rows (bedrock, fireworks…) are left out.
FEED_PROVIDERS = {"openai": "openai", "azure": "azure", "anthropic": "anthropic", "gemini": "google"}

_cache: dict[str, dict[str, ModelPrice]] | None = None
_cache_at = 0.0
_lock = threading.Lock()


class FeedError(Exception):
    """The feed couldn't be fetched or read (the message is safe to show)."""


# ── the URL ──────────────────────────────────────────────────────────────────


def default_url() -> str:
    from marvin.core.config import get_app_settings

    return getattr(get_app_settings(), "AI_PRICE_FEED_URL", DEFAULT_URL)


def _state(session) -> dict:
    from marvin.services.platform_settings import PlatformSettingsService

    return PlatformSettingsService(session).get(SETTINGS_KEY) or {}


def effective_url(session) -> str:
    """The admin's URL when set ("" = off), else AI_PRICE_FEED_URL."""
    url = _state(session).get("url")
    return default_url() if url is None else url


def check_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.lower().startswith("https://"):
        raise FeedError("the price feed URL must start with https://")
    return url


def set_url(session, url: str | None) -> dict:
    """Point the feed at `url` (None = back to AI_PRICE_FEED_URL, "" = off). Prices already fetched stay until
    the next refresh replaces them."""
    from marvin.services.platform_settings import PlatformSettingsService

    state = dict(_state(session))
    state["url"] = None if url is None else check_url(url)
    PlatformSettingsService(session).set(SETTINGS_KEY, state)
    return state


# ── reading the feed ─────────────────────────────────────────────────────────


def parse(data: Any) -> dict[str, dict[str, list[float]]]:
    """LiteLLM's format → {slug: {model: [input_per_1m, output_per_1m, cached_per_1m?, cache_write_per_1m?]}} for FEED_PROVIDERS."""
    if not isinstance(data, dict):
        raise FeedError("the price feed is not a JSON object of models")
    table: dict[str, dict[str, list[float]]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        slug = FEED_PROVIDERS.get(str(entry.get("litellm_provider") or ""))
        cost_in, cost_out = entry.get("input_cost_per_token"), entry.get("output_cost_per_token", 0)
        if slug is None or not isinstance(cost_in, int | float) or not isinstance(cost_out, int | float):
            continue
        model = key.split("/", 1)[1] if key.startswith(f"{entry['litellm_provider']}/") else key
        if "/" in model:  # a regional or routed variant (azure/eu/…): not a model id a provider sends
            continue
        row = [round(cost_in * PER_MILLION, 6), round(cost_out * PER_MILLION, 6)]
        # The prompt-cache rates, when the feed has them (cache_read_input_token_cost / cache_creation_input_token_cost).
        for key in ("cache_read_input_token_cost", "cache_creation_input_token_cost"):
            rate = entry.get(key)
            row.append(round(rate * PER_MILLION, 6) if isinstance(rate, int | float) else None)
        while row and row[-1] is None:
            row.pop()
        table.setdefault(slug, {})[model] = row
    return table


def fetch(url: str, transport: httpx.BaseTransport | None = None) -> dict[str, dict[str, list[float]]]:
    url = check_url(url)
    if not url:
        raise FeedError("the price feed is switched off")
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, transport=transport) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise FeedError(f"{url} answered {response.status_code}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FeedError(f"the price feed is larger than {MAX_BYTES // (1024 * 1024)} MB")
    except httpx.HTTPError as e:
        raise FeedError(f"could not fetch {url}: {e}") from e
    import json

    try:
        data = json.loads(bytes(body))
    except ValueError as e:
        raise FeedError("the price feed is not valid JSON") from e
    table = parse(data)
    if not table:
        raise FeedError("the price feed has no prices for OpenAI, Azure, Anthropic or Google in LiteLLM's format")
    return table


def refresh(session, transport: httpx.BaseTransport | None = None) -> dict:
    """Fetch the feed and store it; on failure keep the last good prices, record the error and raise FeedError."""
    from marvin.services.platform_settings import PlatformSettingsService

    state = dict(_state(session))
    url = effective_url(session)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        table = fetch(url, transport)
    except FeedError as e:
        state.update(error=str(e), error_at=now)
        PlatformSettingsService(session).set(SETTINGS_KEY, state)
        raise
    state.update(prices=table, fetched_from=url, fetched_at=now, models=sum(len(m) for m in table.values()), error=None, error_at=None)
    PlatformSettingsService(session).set(SETTINGS_KEY, state)
    clear_cache()
    return state


def status(session) -> dict:
    state = _state(session)
    return {
        "url": effective_url(session),
        "custom_url": state.get("url"),
        "default_url": default_url(),
        "fetched_from": state.get("fetched_from"),
        "fetched_at": state.get("fetched_at"),
        "models": state.get("models") or 0,
        "error": state.get("error"),
        "error_at": state.get("error_at"),
    }


# ── the lookup ───────────────────────────────────────────────────────────────


def _price(row: list) -> ModelPrice:
    """A stored row — [input, output] or [input, output, cached, write] with None for an unknown rate — as a price."""
    cached = float(row[2]) if len(row) > 2 and row[2] is not None else None
    write = float(row[3]) if len(row) > 3 and row[3] is not None else None
    return ModelPrice(float(row[0]), float(row[1]), cached_input_per_1m=cached, cache_write_per_1m=write)


def _table() -> dict[str, dict[str, ModelPrice]]:
    global _cache, _cache_at
    with _lock:
        if _cache is not None and time.monotonic() - _cache_at < CACHE_SECONDS:
            return _cache
    try:
        from marvin.db.db_setup import session_context

        with session_context() as session:
            raw = _state(session).get("prices") or {}
        table = {slug: {m: _price(p) for m, p in models.items()} for slug, models in raw.items()}
    except Exception:  # noqa: BLE001 — no database or a damaged row: no feed prices, estimates still work
        table = {}
    with _lock:
        _cache, _cache_at = table, time.monotonic()
    return table


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def feed_price_for(provider_type: str, model_id: str) -> ModelPrice | None:
    return price_for(_table().get(provider_type, {}), model_id)


def feed_models() -> dict[str, dict[str, ModelPrice]]:
    return _table()
