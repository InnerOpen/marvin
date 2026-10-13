"""
Slug resolver for {{SLUG}} references.

Resolution order (Secrets win on collision):
  1. Secret backend (encrypted, write-only)
  2. Workspace Variable (plain-text, readable)

Unresolved slugs:
  - Dev  (PRODUCTION=False): left as {{SLUG}} so misconfiguration is visible.
  - Prod (PRODUCTION=True):  replaced with UNRESOLVED_SENTINEL so the containing
    header is dropped by resolve_dict(), preventing leaked placeholder text.
"""

import re

from pydantic import UUID4

from marvin.core.root_logger import get_logger

from .factory import get_secret_backend

logger = get_logger(__name__)

SLUG_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

UNRESOLVED_SENTINEL = "__MARVIN_UNRESOLVED__"


def _get_variable(slug: str, group_id: UUID4 | None) -> str | None:
    """Look up a workspace variable by slug."""
    if group_id is None:
        return None
    try:
        from sqlalchemy import and_, select

        from marvin.db.db_setup import session_context
        from marvin.db.models.groups.variables import WorkspaceVariable

        with session_context() as session:
            result = session.execute(
                select(WorkspaceVariable.value).where(
                    and_(
                        WorkspaceVariable.slug == slug,
                        WorkspaceVariable.group_id == group_id,
                    )
                )
            ).scalar_one_or_none()
            return result
    except Exception as e:
        logger.debug(f"Variable lookup failed for '{slug}': {e}")
        return None


def resolve(
    value: str,
    group_id: UUID4 | None = None,
    allow_secrets: bool = True,
    context: dict | None = None,
) -> str:
    """
    Replace {{SLUG}} references with resolved values.

    Convention:
      {{UPPER_CASE}} — workspace Secrets / Variables (static, same for all sends)
      {{lower_case}} — per-send context (dynamic: user name, reset token, invite URL, etc.)

    Resolution order:
      1. Per-send context dict (lowercase variables passed at call time)
      2. Secrets backend (uppercase, encrypted — only when allow_secrets=True)
      3. Workspace Variables (uppercase, plain-text)

    Use allow_secrets=False for email template content (secrets should never
    appear in email bodies visible to recipients).

    In production an unresolved slug is replaced with UNRESOLVED_SENTINEL so
    resolve_dict() can drop the containing header. In dev the placeholder is
    kept for visibility.
    """
    if "{{" not in value:
        return value

    backend = get_secret_backend()

    def replacer(match: re.Match) -> str:
        slug = match.group(1)
        # 1. Per-send context (exact match, any case)
        if context and slug in context:
            return str(context[slug])
        # 2. Secrets (uppercase only, when permitted)
        if allow_secrets and slug == slug.upper():
            result = backend.get(slug, group_id)
            if result is not None:
                return result
        # 3. Workspace variables (uppercase only)
        if slug == slug.upper():
            result = _get_variable(slug, group_id)
            if result is not None:
                return result
        logger.warning(f"'{{{{ {slug} }}}}' not resolved for group {group_id}")
        # Only UPPER_CASE refs are secrets/variables, where leaking a placeholder into a header is
        # the risk the sentinel guards against. A lower_case ref is per-send template context: leave
        # it for the Jinja2 render that follows, which drops an undefined variable as empty text
        # instead of mailing "__MARVIN_UNRESOLVED__" to someone.
        if slug != slug.upper():
            return match.group(0)
        from marvin.core.config import get_app_settings

        if get_app_settings().PRODUCTION:
            return UNRESOLVED_SENTINEL
        return match.group(0)

    return SLUG_RE.sub(replacer, value)


def resolve_dict(
    data: dict[str, str],
    group_id: UUID4 | None = None,
    allow_secrets: bool = True,
    context: dict | None = None,
) -> dict[str, str]:
    """Resolve {{SLUG}} in all dict values (e.g. webhook headers).

    Any header whose resolved value contains UNRESOLVED_SENTINEL is silently
    dropped — this only occurs in production when a slug cannot be found.
    """
    result = {}
    for key, val in data.items():
        resolved = resolve(val, group_id, allow_secrets=allow_secrets, context=context)
        if UNRESOLVED_SENTINEL not in (resolved or ""):
            result[key] = resolved or val
    return result


def resolve_secret(slug: str, group_id: UUID4 | None = None) -> str | None:
    """
    Resolve a single slug as a Secret only — for infrastructure config
    (e.g. Gmail OAuth token, SMTP password) not template content.
    Returns None if not found.
    """
    return get_secret_backend().get(slug, group_id)
