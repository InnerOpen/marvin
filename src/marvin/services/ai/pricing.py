"""
AI cost estimates: what a run's tokens cost, from the first source that prices its model.

1. an admin's own price (Admin → AI Pricing, services/ai/price_overrides.py);
2. the provider's own table (its plugin's ``AIProvider.prices``; a new model's price is a plugin release);
3. self-hosted providers (``self_hosted``: Ollama) cost nothing;
4. the daily price feed (services/ai/price_feed.py, LiteLLM's list from a configurable URL).

Core keeps no table of its own (AI provider plugins, slice 5): every provider is a plugin that ships its prices.
A model none of these price has no estimate — stored as unknown, shown as "—", counted as unpriced (never $0).
Per 1M tokens, input and output separately; used only for the estimates stored on executions.
"""

from marvin_integration_sdk.ai import ModelPrice

ModelPricing = ModelPrice
"""The SDK's ModelPrice (input_per_1m, output_per_1m), under its old name."""

# Providers whose runs cost nothing even when their plugin isn't installed any more (a stored run's provider).
_SELF_HOSTED = {"ollama", "custom"}


def estimate_cost(provider_type: str, model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimated USD cost for a completion; None when the model's price isn't known (shown as "—",
    never as a misleading "Free")."""
    from .price_feed import feed_price_for
    from .price_overrides import override_for
    from .registry import find_class

    if (mine := override_for(provider_type, model_id)) is not None:
        return mine.cost(prompt_tokens, completion_tokens)
    cls = find_class(provider_type)
    if cls is not None:
        cost = cls.estimate_cost(model_id, prompt_tokens, completion_tokens)
        if cost is not None:
            return cost
    if provider_type in _SELF_HOSTED or (cls is not None and getattr(cls, "self_hosted", False)):
        return 0.0
    feed = feed_price_for(provider_type, model_id)
    return feed.cost(prompt_tokens, completion_tokens) if feed is not None else None
