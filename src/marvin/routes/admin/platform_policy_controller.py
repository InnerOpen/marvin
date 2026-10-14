"""Admin: the security policy and email branding, editable in the UI (services/platform_policy.py)."""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas._marvin import _MarvinModel
from marvin.services.platform_policy import PolicyError, email_branding, save_email_branding, save_security, security_view

router = APIRouter(prefix="/platform-policy")


class SecuritySettingRead(_MarvinModel):
    key: str
    label: str
    help: str
    unit: str
    min: int
    max: int
    default: int
    """The environment's value, used when no admin value is set."""
    value: int
    """The value in force."""
    overridden: bool


class SecurityUpdate(_MarvinModel):
    values: dict[str, int | None]
    """Setting name → a whole number, or null to go back to the environment's value."""


class EmailBranding(_MarvinModel):
    product_name: str = ""
    footer_text: str = ""
    accent_color: str = ""


@controller(router)
class AdminPlatformPolicyController(BaseAdminController):
    @router.get("/security", response_model=list[SecuritySettingRead], summary="Security policy")
    def get_security(self) -> list[SecuritySettingRead]:
        return [SecuritySettingRead(**r) for r in security_view(self.session)]

    @router.put("/security", response_model=list[SecuritySettingRead], summary="Set the security policy")
    def put_security(self, data: SecurityUpdate) -> list[SecuritySettingRead]:
        try:
            rows = save_security(self.session, data.values)
        except PolicyError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        self.logger.info("Security policy updated: %s", ", ".join(sorted(data.values)))
        return [SecuritySettingRead(**r) for r in rows]

    @router.get("/email-branding", response_model=EmailBranding, summary="Email branding")
    def get_branding(self) -> EmailBranding:
        return EmailBranding(**email_branding())

    @router.put("/email-branding", response_model=EmailBranding, summary="Set the email branding")
    def put_branding(self, data: EmailBranding) -> EmailBranding:
        try:
            return EmailBranding(**save_email_branding(self.session, data.model_dump()))
        except PolicyError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
