"""Links into the admin UI that leave the backend (tool results, agent answers, emails).

The API does not serve the UI, so it only knows the UI's public address when `FRONTEND_URL` is
configured. Configured → absolute link; left at the built-in default → a root-relative path, which
the admin UI (same origin as the chat) resolves correctly and no external client can misread as
"localhost".
"""

from __future__ import annotations

from marvin.core.config import get_app_settings

ENTRY_PATH = "/workspace/entries/{entry_id}"


def ui_base_url() -> str | None:
    """The configured public UI origin, or None when FRONTEND_URL is still the development default."""
    settings = get_app_settings()
    default = type(settings).model_fields["FRONTEND_URL"].default
    url = (settings.FRONTEND_URL or "").rstrip("/")
    return url if url and url != default.rstrip("/") else None


def ui_link(path: str) -> str:
    base = ui_base_url()
    return f"{base}{path}" if base else path


def entry_edit_url(entry_id) -> str:
    return ui_link(ENTRY_PATH.format(entry_id=entry_id))


def entry_review_link(entry_id, label: str = "Review the draft") -> str:
    """A finished markdown link for an agent to hand to the user verbatim (models copy strings; they guess hosts)."""
    return f"[{label}]({entry_edit_url(entry_id)})"
