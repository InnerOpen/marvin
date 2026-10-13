"""Admin → AI pricing (routes/admin/ai_prices_controller.py)."""

from marvin.schemas._marvin import _MarvinModel


class AIPriceOverride(_MarvinModel):
    provider: str
    model: str
    input_per_1m: float
    """USD per million input (prompt) tokens."""
    output_per_1m: float
    """USD per million output (completion) tokens."""
    updated_at: str | None = None


class AIPriceRow(_MarvinModel):
    provider: str
    model: str
    source: str
    """Where the price comes from: override | provider | self_hosted | feed | none."""
    input_per_1m: float | None = None
    output_per_1m: float | None = None
    overridden: bool = False
    runs: int = 0
    """Runs of this model in the last 90 days (every workspace)."""
    unpriced_runs: int = 0
    """Of those, completed runs that used tokens and have no cost."""


class AIPriceFeedStatus(_MarvinModel):
    url: str
    """The URL fetched: the admin's (custom_url) or the default; "" = the feed is off."""
    custom_url: str | None = None
    """The admin's URL; None = the default (AI_PRICE_FEED_URL)."""
    default_url: str
    fetched_from: str | None = None
    fetched_at: str | None = None
    models: int = 0
    error: str | None = None
    """The last refresh's error (the last good prices stay)."""
    error_at: str | None = None


class AIPriceFeedUpdate(_MarvinModel):
    url: str | None = None
    """https URL in LiteLLM's format; None = back to the default; "" = switch the feed off."""


class AIPriceList(_MarvinModel):
    prices: list[AIPriceRow] = []
    overrides: list[AIPriceOverride] = []
    feed: AIPriceFeedStatus | None = None


class AIPriceOverridesUpdate(_MarvinModel):
    prices: list[AIPriceOverride] = []


class AIPriceBackfill(_MarvinModel):
    provider: str
    model: str


class AIPriceBackfillResult(_MarvinModel):
    provider: str
    model: str
    updated: int
