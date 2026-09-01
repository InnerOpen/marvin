"""Entry type rendering and capabilities definition models."""

from marvin.schemas._marvin import _MarvinModel

KNOWN_CORE_RENDERERS: set[str] = {"page", "article", "faq", "navigation"}


class RenderingDefinition(_MarvinModel):
    """Describes how entries of this type should be rendered on the frontend."""

    renderer: str | None = None
    package: str | None = None
    version: str | None = None
    config: dict | None = None


class SubmissionConfig(_MarvinModel):
    """Public-submission behavior for a submittable entry type (i.e. a "form").

    Carries the form-level concerns that used to live in ``Forms.settings_json`` so a submittable
    entry type is self-describing. The CAPTCHA secret is a ``{{SLUG}}`` reference resolved from the
    workspace secret store at submit time — never a plaintext secret on the entry type.
    """

    success_message: str | None = None
    redirect_url: str | None = None
    enable_honeypot: bool = False
    honeypot_field: str = "_website"
    enable_captcha: bool = False
    captcha_provider: str | None = None
    captcha_secret_ref: str | None = None
    rate_limit_max: int | None = None
    rate_limit_window_seconds: int | None = None
    notify: bool = True
    # Jinja title for the created entry (e.g. "Contact from {{ name }}"); falls back to the first
    # non-empty text field, then the type name + timestamp.
    title_template: str | None = None


class CapabilitiesDefinition(_MarvinModel):
    """Describes behavioral capabilities for entries of this type."""

    publishable: bool = True
    submittable: bool = False
    routable: bool = True
    # Present only on submittable types; describes how public submissions are handled.
    submission: SubmissionConfig | None = None
