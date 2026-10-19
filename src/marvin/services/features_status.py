"""What Admin → Site Settings → Features Status shows: each feature as it is IN FORCE, and where that comes from.

The raw settings dump (`/admin/about/startup-info`) only has what the environment says. Some features an admin can
change in the UI (remote MCP's switch, the platform SMTP server's fields), and those rows live in `platform_settings`.
Reading the dump alone reported "Mcp Remote: Disabled" on an install where an admin had switched it on, so the card
reads this list instead, which asks the same functions the running code asks (`platform_policy.remote_mcp()`,
`platform_smtp.effective()`).

``source`` is where the value in force comes from: ``admin`` (set in the Admin UI), ``environment`` (an env var or the
settings file set it) or ``default`` (nothing set it: the built-in default). ``reason`` says why a feature is off or
can't run, when there is something to say.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

ADMIN, ENVIRONMENT, DEFAULT = "admin", "environment", "default"

REMOTE_MCP_PATH = "/admin/site-settings#remote-mcp"
EMAIL_PATH = "/admin/email-settings"


@dataclass(frozen=True)
class FeatureStatus:
    key: str
    label: str
    enabled: bool
    source: str
    reason: str | None = None
    manage_path: str | None = None
    """The Admin page where it can be changed; None when only the environment can."""


def _env_source(settings, *names: str) -> str:
    """``environment`` when any of these settings was provided (env var, .env file), else ``default``."""
    return ENVIRONMENT if any(n in settings.model_fields_set for n in names) else DEFAULT


def _flag(settings, key: str, label: str, name: str, off_reason: str) -> FeatureStatus:
    enabled = bool(getattr(settings, name))
    return FeatureStatus(key, label, enabled, _env_source(settings, name), None if enabled else off_reason)


def remote_mcp_status(settings) -> FeatureStatus:
    from marvin.services import platform_policy as pp

    stored = pp._stored(pp.REMOTE_MCP_KEY).get("enabled")
    policy = pp.remote_mcp()
    if stored is not None:
        switch, source = bool(stored), ADMIN
    else:
        switch, source = bool(settings.MCP_REMOTE_ENABLED), _env_source(settings, "MCP_REMOTE_ENABLED")
    reason = None
    if not policy.enabled:
        if switch:
            reason = pp._mcp_unavailable_reason()
        else:
            reason = "Switched off in Admin." if source == ADMIN else "Not switched on (MCP_REMOTE_ENABLED is false)."
    return FeatureStatus("mcp_remote", "Remote MCP", policy.enabled, source, reason, REMOTE_MCP_PATH)


def smtp_status() -> FeatureStatus:
    from marvin.services import platform_smtp

    smtp = platform_smtp.effective()
    source = {"admin": ADMIN, "env": ENVIRONMENT}.get(smtp.source or "", DEFAULT)
    return FeatureStatus("smtp", "Email (SMTP)", smtp.ready, source, smtp.problem, EMAIL_PATH)


def features_status(settings) -> list[FeatureStatus]:
    from marvin.services.ai.embeddings import builtin_embeddings_available

    available = builtin_embeddings_available()
    if available:
        embeddings_reason = None
    elif settings.EMBEDDINGS_BUILTIN_ENABLED:
        embeddings_reason = "The fastembed package is not installed."
    else:
        embeddings_reason = "EMBEDDINGS_BUILTIN_ENABLED is false."
    embeddings = FeatureStatus(
        "embeddings_builtin", "Built-in embeddings", available, _env_source(settings, "EMBEDDINGS_BUILTIN_ENABLED"), embeddings_reason
    )
    ldap, oidc, openai = settings.LDAP_FEATURE, settings.OIDC_FEATURE, settings.OPENAI_FEATURE
    return [
        smtp_status(),
        remote_mcp_status(settings),
        FeatureStatus(
            "ldap",
            "LDAP sign-in",
            settings.LDAP_ENABLED,
            _env_source(settings, "LDAP_AUTH_ENABLED"),
            None if settings.LDAP_ENABLED else ldap.description,
        ),
        FeatureStatus(
            "oidc", "OIDC sign-in", settings.OIDC_READY, _env_source(settings, "OIDC_AUTH_ENABLED"), None if settings.OIDC_READY else oidc.description
        ),
        _flag(settings, "oidc_signup", "OIDC sign-up", "OIDC_SIGNUP_ENABLED", "OIDC_SIGNUP_ENABLED is false."),
        FeatureStatus(
            "openai",
            "OpenAI",
            settings.OPENAI_ENABLED,
            _env_source(settings, "OPENAI_API_KEY"),
            None if settings.OPENAI_ENABLED else openai.description,
        ),
        FeatureStatus(
            "web_push",
            "Web Push",
            settings.WEB_PUSH_ENABLED,
            _env_source(settings, "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"),
            None if settings.WEB_PUSH_ENABLED else "VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT (mailto: or https:) are not all set.",
        ),
        _flag(settings, "scheduler", "Scheduler", "SCHEDULER_ENABLED", "SCHEDULER_ENABLED is false."),
        _flag(settings, "media_embeds_fetch", "Media embed fetching", "MEDIA_EMBEDS_FETCH_ENABLED", "MEDIA_EMBEDS_FETCH_ENABLED is false."),
        embeddings,
    ]


def features_status_view(settings) -> list[dict]:
    return [asdict(f) for f in features_status(settings)]
