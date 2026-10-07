"""
Approximate AI provider pricing for cost estimation.

Prices live with the provider (``AIProvider.prices`` / ``self_hosted``, see the plugin SDK): an installed
provider plugin ships its own table, so a new model's price is a plugin release. This table is core's
fallback while the built-in providers are still in core — consulted when the provider has no price for
a model. Per 1M tokens (input/output separately); used only for estimates stored on executions.
"""

from marvin_integration_sdk.ai import ModelPrice, price_for

ModelPricing = ModelPrice
"""The SDK's ModelPrice (input_per_1m, output_per_1m), under its old name."""


# provider_type → model_id → pricing
PRICING: dict[str, dict[str, ModelPricing]] = {
    "openai": {
        # GPT-5 family — standard tier, from developers.openai.com/api/docs/pricing (2026-10-01).
        "gpt-5.6-sol": ModelPricing(input_per_1m=4.00, output_per_1m=20.00),
        "gpt-5.6-terra": ModelPricing(input_per_1m=2.00, output_per_1m=12.00),
        "gpt-5.6-luna": ModelPricing(input_per_1m=0.20, output_per_1m=1.20),
        "gpt-5.5": ModelPricing(input_per_1m=5.00, output_per_1m=30.00),
        "gpt-5.4": ModelPricing(input_per_1m=2.50, output_per_1m=15.00),
        "gpt-5.4-mini": ModelPricing(input_per_1m=0.75, output_per_1m=4.50),
        "gpt-5.4-nano": ModelPricing(input_per_1m=0.20, output_per_1m=1.25),
        "gpt-5.2": ModelPricing(input_per_1m=1.75, output_per_1m=14.00),
        "gpt-5.1": ModelPricing(input_per_1m=1.25, output_per_1m=10.00),
        "gpt-5": ModelPricing(input_per_1m=1.25, output_per_1m=10.00),
        "gpt-5-mini": ModelPricing(input_per_1m=0.25, output_per_1m=2.00),
        "gpt-5-nano": ModelPricing(input_per_1m=0.05, output_per_1m=0.40),
        "gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00),
        "gpt-4o-mini": ModelPricing(input_per_1m=0.15, output_per_1m=0.60),
        "gpt-4.1": ModelPricing(input_per_1m=2.00, output_per_1m=8.00),
        "gpt-4.1-mini": ModelPricing(input_per_1m=0.40, output_per_1m=1.60),
        "gpt-4-turbo": ModelPricing(input_per_1m=10.00, output_per_1m=30.00),
        "o3": ModelPricing(input_per_1m=10.00, output_per_1m=40.00),
        "o4-mini": ModelPricing(input_per_1m=1.10, output_per_1m=4.40),
        # Image models — priced by the token usage the images API returns (input text, output image).
        "gpt-image-1": ModelPricing(input_per_1m=5.00, output_per_1m=40.00),
        "gpt-image-1-mini": ModelPricing(input_per_1m=2.00, output_per_1m=8.00),
    },
    "anthropic": {
        "claude-opus-4-8": ModelPricing(input_per_1m=15.00, output_per_1m=75.00),
        "claude-sonnet-5": ModelPricing(input_per_1m=3.00, output_per_1m=15.00),
        "claude-haiku-4-5-20251001": ModelPricing(input_per_1m=0.80, output_per_1m=4.00),
    },
    "google": {
        "gemini-1.5-pro": ModelPricing(input_per_1m=1.25, output_per_1m=5.00),
        "gemini-1.5-flash": ModelPricing(input_per_1m=0.075, output_per_1m=0.30),
        "gemini-2.0-flash": ModelPricing(input_per_1m=0.10, output_per_1m=0.40),
    },
    "azure": {
        # Azure mirrors OpenAI pricing; use the same rates
        "gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00),
        "gpt-4.1": ModelPricing(input_per_1m=2.00, output_per_1m=8.00),
    },
    # Ollama is self-hosted — no cost
    "ollama": {},
    "custom": {},
}

# Self-hosted providers cost nothing per token; every other provider's unpriced model is unknown.
_SELF_HOSTED = {"ollama", "custom"}


def _pricing_for(provider_type: str, model_id: str) -> ModelPricing | None:
    """Core's fallback price: exact model id first, then the longest known id it extends with a "-"
    (dated snapshots like `gpt-4o-2024-08-06`). `gpt-5.6-luna` does not fall back to `gpt-5`."""
    return price_for(PRICING.get(provider_type, {}), model_id)


def estimate_cost(provider_type: str, model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimated USD cost for a completion; None when the model's price isn't known (shown as "—",
    never as a misleading "Free").

    The provider's own price first (self-hosted → 0), then core's fallback table."""
    from .registry import find_class

    cls = find_class(provider_type)
    if cls is not None:
        cost = cls.estimate_cost(model_id, prompt_tokens, completion_tokens)
        if cost is not None:
            return cost
    if provider_type in _SELF_HOSTED:
        return 0.0
    pricing = _pricing_for(provider_type, model_id)
    return pricing.cost(prompt_tokens, completion_tokens) if pricing else None
