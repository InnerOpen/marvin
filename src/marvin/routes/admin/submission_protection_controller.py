"""Platform-wide submission protection defaults (admin). Workspaces override per field via their
preferences (`submission_protection_json`); see `services/security/submission_protection.py`."""

from fastapi import APIRouter

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.platform.submission_protection import SubmissionProtectionSettings
from marvin.services.platform_settings import SUBMISSION_PROTECTION_KEY, PlatformSettingsService
from marvin.services.security.email_domain_presets import DISPOSABLE_DOMAINS, PERSONAL_DOMAINS

router = APIRouter(prefix="/submission-protection")


@controller(router)
class AdminSubmissionProtectionController(BaseAdminController):
    @router.get("", response_model=SubmissionProtectionSettings, summary="Get Platform Submission Protection Defaults")
    def get_settings(self) -> SubmissionProtectionSettings:
        stored = PlatformSettingsService(self.session).get(SUBMISSION_PROTECTION_KEY)
        return SubmissionProtectionSettings.model_validate(stored or {})

    @router.put("", response_model=SubmissionProtectionSettings, summary="Replace Platform Submission Protection Defaults")
    def update_settings(self, data: SubmissionProtectionSettings) -> SubmissionProtectionSettings:
        PlatformSettingsService(self.session).set(SUBMISSION_PROTECTION_KEY, data.model_dump())
        self.logger.info("Platform submission protection defaults updated")
        return data

    @router.get("/presets", summary="List Bundled Email Domain Presets")
    def get_presets(self) -> dict[str, list[str]]:
        return {"disposable": sorted(DISPOSABLE_DOMAINS), "personal": sorted(PERSONAL_DOMAINS)}
