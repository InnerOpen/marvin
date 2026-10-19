"""A workspace's email branding (Settings → Email → Branding; services/email/branding.py)."""

from marvin.schemas._marvin import _MarvinModel


class EmailBrandValues(_MarvinModel):
    product_name: str = ""
    footer_text: str = ""
    accent_color: str = ""


class WorkspaceEmailBrandingUpdate(EmailBrandValues):
    """The workspace's own values; a blank one falls back."""


class WorkspaceEmailBrandingRead(EmailBrandValues):
    """The workspace's own values (blank where unset) and what its emails show with them."""

    effective: EmailBrandValues
