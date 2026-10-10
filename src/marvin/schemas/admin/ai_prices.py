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
    """Where the price comes from: override | provider | core | self_hosted | none."""
    input_per_1m: float | None = None
    output_per_1m: float | None = None
    overridden: bool = False
    runs: int = 0
    """Runs of this model in the last 90 days (every workspace)."""
    unpriced_runs: int = 0
    """Of those, completed runs that used tokens and have no cost."""


class AIPriceList(_MarvinModel):
    prices: list[AIPriceRow] = []
    overrides: list[AIPriceOverride] = []


class AIPriceOverridesUpdate(_MarvinModel):
    prices: list[AIPriceOverride] = []


class AIPriceBackfill(_MarvinModel):
    provider: str
    model: str


class AIPriceBackfillResult(_MarvinModel):
    provider: str
    model: str
    updated: int
