"""Admin: the security policy, email branding and remote MCP switch, editable in the UI (services/platform_policy.py)."""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas._marvin import _MarvinModel
from marvin.services.platform_policy import (
    PolicyError,
    email_branding,
    remote_mcp_view,
    save_email_branding,
    save_remote_mcp,
    save_security,
    security_view,
)

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


class RemoteMcpRead(_MarvinModel):
    enabled: bool
    """Switched on (the admin's choice, else MCP_REMOTE_ENABLED)."""
    enabled_default: bool
    """MCP_REMOTE_ENABLED: what the switch is when no admin value is set."""
    unavailable_reason: str | None = None
    """Why it can't run here even when switched on (no PUBLIC_API_URL in production)."""
    issuer: str | None = None
    """PUBLIC_API_URL: the OAuth issuer the metadata names."""
    resource: str | None = None
    """The MCP server address clients connect to (issuer + /mcp)."""
    fields: list[SecuritySettingRead]
    """The token lifetimes."""
    extra_redirect_uris: list[str]
    allow_dynamic_registration: bool


class RemoteMcpUpdate(_MarvinModel):
    enabled: bool | None = None
    values: dict[str, int | None] = {}
    """Lifetime name → a whole number, or null to go back to the environment's value."""
    extra_redirect_uris: list[str] | None = None
    """Exact https redirect URIs, or prefixes ending in *, allowed besides the built-in clients'."""
    allow_dynamic_registration: bool | None = None


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

    @router.get("/remote-mcp", response_model=RemoteMcpRead, summary="Remote MCP policy")
    def get_remote_mcp(self) -> RemoteMcpRead:
        return RemoteMcpRead(**remote_mcp_view(self.session))

    @router.put("/remote-mcp", response_model=RemoteMcpRead, summary="Set the remote MCP policy")
    def put_remote_mcp(self, data: RemoteMcpUpdate) -> RemoteMcpRead:
        changes: dict = dict(data.values)
        for key in ("enabled", "extra_redirect_uris", "allow_dynamic_registration"):
            if key in data.model_fields_set:
                changes[key] = getattr(data, key)
        try:
            view = remote_mcp_view(self.session) if not changes else save_remote_mcp(self.session, changes)
        except PolicyError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        self.logger.info("Remote MCP policy updated: %s", ", ".join(sorted(changes)) or "nothing")
        return RemoteMcpRead(**view)
