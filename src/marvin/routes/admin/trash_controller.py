"""Platform-wide Trash default (admin): how long a deleted entry stays in the Trash before it is deleted
forever. Workspaces inherit it unless they set their own (preferences `trash_auto_empty_days`); see
`services/entries/trash.py`."""

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from marvin.routes._base import BaseAdminController, controller
from marvin.services.entries.trash import AUTO_EMPTY_CHOICES, platform_auto_empty_days, set_platform_auto_empty_days

router = APIRouter(prefix="/trash")


class TrashSettings(BaseModel):
    auto_empty_days: int
    """Days an entry stays in the Trash (0 = never emptied automatically)."""

    @field_validator("auto_empty_days")
    @classmethod
    def _choice(cls, value: int) -> int:
        if value not in AUTO_EMPTY_CHOICES:
            raise ValueError(f"auto_empty_days must be one of {', '.join(map(str, AUTO_EMPTY_CHOICES))} (0 = never)")
        return value


@controller(router)
class AdminTrashController(BaseAdminController):
    @router.get("", response_model=TrashSettings, summary="Get Platform Trash Default")
    def get_settings(self) -> TrashSettings:
        return TrashSettings(auto_empty_days=platform_auto_empty_days(self.session))

    @router.put("", response_model=TrashSettings, summary="Set Platform Trash Default")
    def update_settings(self, data: TrashSettings) -> TrashSettings:
        set_platform_auto_empty_days(self.session, data.auto_empty_days)
        self.logger.info(f"Platform Trash auto-empty default set to {data.auto_empty_days} days")
        return data
