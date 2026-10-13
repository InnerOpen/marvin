"""Admin → AI pricing: the price Marvin uses for each provider/model, and the admin's own overrides.

A model with no price anywhere is stored with no cost, so the monthly cost limit can't see it (the workspace's
usage card says so). An override prices it now; Backfill gives its past runs that price. Saving is audited as
``platform_settings_changed``. See services/ai/price_overrides.py.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.ai_prices import (
    AIPriceBackfill,
    AIPriceBackfillResult,
    AIPriceFeedStatus,
    AIPriceFeedUpdate,
    AIPriceList,
    AIPriceOverridesUpdate,
)
from marvin.services.ai import price_feed, price_overrides
from marvin.services.event_bus_service.event_types import EventOperation, EventPlatformSettingsChangedData, EventTypes

router = APIRouter(prefix="/ai-prices")


@controller(router)
class AdminAIPricesController(BaseAdminController):
    @router.get("", response_model=AIPriceList, summary="AI price list")
    def get_prices(self) -> AIPriceList:
        """Every model with a price or recent runs, per provider: the price used, where it comes from (override,
        provider, core, self_hosted, none), the last 90 days' runs and how many have no cost; and the overrides."""
        return self._read()

    @router.put("/overrides", response_model=AIPriceList, summary="Set AI price overrides")
    def set_overrides(self, data: AIPriceOverridesUpdate) -> AIPriceList:
        """Replace the overrides (USD per million tokens, input and output). An override wins over every other
        price for that model; remove it to fall back."""
        try:
            _, changes = price_overrides.save_overrides(self.session, [p.model_dump() for p in data.prices])
        except price_overrides.PriceError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        if changes:
            self._announce(changes)
        return self._read()

    @router.post("/backfill", response_model=AIPriceBackfillResult, summary="Price a model's past unpriced runs")
    def backfill(self, data: AIPriceBackfill) -> AIPriceBackfillResult:
        """Give this model's completed runs that have no cost the cost its price now gives them (all retained runs,
        every workspace). 0 when the model still has no price."""
        updated = price_overrides.backfill(self.session, data.provider, data.model)
        self.logger.info(f"AI pricing: backfilled {updated} run(s) of {data.provider} {data.model}")
        return AIPriceBackfillResult(provider=data.provider, model=data.model, updated=updated)

    @router.put("/feed", response_model=AIPriceFeedStatus, summary="Set the AI price feed URL")
    def set_feed(self, data: AIPriceFeedUpdate) -> AIPriceFeedStatus:
        """Where the daily price feed is fetched from (LiteLLM's format, https): null = the default
        (AI_PRICE_FEED_URL), "" = off. Takes effect at the next refresh."""
        before = price_feed.effective_url(self.session)
        try:
            price_feed.set_url(self.session, data.url)
        except price_feed.FeedError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        after = price_feed.effective_url(self.session)
        if after != before:
            self._announce([f"price feed URL: {after or 'off'} (was {before or 'off'})"], setting=price_feed.SETTINGS_KEY)
        return AIPriceFeedStatus.model_validate(price_feed.status(self.session))

    @router.post("/feed/refresh", response_model=AIPriceFeedStatus, summary="Refresh the AI price feed now")
    def refresh_feed(self) -> AIPriceFeedStatus:
        """Fetch the price feed now. A failure keeps the last good prices; the error is in the status."""
        try:
            price_feed.refresh(self.session)
        except price_feed.FeedError as e:
            self.logger.warning(f"AI price feed refresh failed: {e}")
        return AIPriceFeedStatus.model_validate(price_feed.status(self.session))

    def _read(self) -> AIPriceList:
        return AIPriceList.model_validate(
            {
                "prices": price_overrides.price_list(self.session),
                "overrides": price_overrides.list_overrides(self.session),
                "feed": price_feed.status(self.session),
            }
        )

    def _announce(self, changes: list[str], setting: str = price_overrides.SETTINGS_KEY) -> None:
        """platform_settings_changed (platform scope, always audited)."""
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"AI price overrides changed by {name}: {'; '.join(changes)}")
        self.event_bus.dispatch(
            integration_id="platform_settings",
            group_id=None,
            event_type=EventTypes.platform_settings_changed,
            document_data=EventPlatformSettingsChangedData(operation=EventOperation.update, setting=setting, changes=changes, changed_by_name=name),
            message=("AI pricing: " + "; ".join(changes))[:1000],
            user_id=self.user.id,
            entity_type="platform_settings",
        )
