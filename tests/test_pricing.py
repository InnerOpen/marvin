"""AI cost estimates: known models are priced, unknown ones are unknown — not "Free"."""

from marvin.services.ai.pricing import estimate_cost


def test_estimate_cost_gpt54_mini_uses_its_listed_rates():
    # 1M in at $0.75 + 1M out at $4.50
    assert estimate_cost("openai", "gpt-5.4-mini", 1_000_000, 1_000_000) == 5.25


def test_estimate_cost_dated_snapshot_uses_base_model_price():
    assert estimate_cost("openai", "gpt-4o-2024-08-06", 1_000_000, 0) == estimate_cost("openai", "gpt-4o", 1_000_000, 0)


def test_estimate_cost_prefers_longest_known_prefix():
    assert estimate_cost("openai", "gpt-4o-mini-2024-07-18", 1_000_000, 0) == 0.15


def test_estimate_cost_unknown_paid_model_is_none():
    assert estimate_cost("openai", "gpt-9-imaginary", 1000, 1000) is None


def test_estimate_cost_sibling_family_does_not_borrow_a_shorter_id():
    assert estimate_cost("openai", "gpt-5.7", 1000, 1000) is None


def test_estimate_cost_self_hosted_is_free():
    assert estimate_cost("ollama", "llama3", 1000, 1000) == 0.0
