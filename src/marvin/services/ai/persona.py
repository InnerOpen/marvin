"""Marvin's built-in voice — what "Leave blank for the default voice" on the AI settings page means.

A workspace's own persona (AI settings → Persona) replaces it. It only applies while the assistant
is still called Marvin: a workspace that renamed its assistant and left the persona blank gets a
neutral voice rather than someone else's character. The tone register still decides where any voice
applies — under `auto` it frames the conversation and work product stays plain; `professional` drops
it entirely.

Kept in step with the bubble's canned lines (frontend/src/lib/marvin/persona.ts), so the greeting and
the answers that follow sound like the same character.
"""

DEFAULT_ASSISTANT_NAME = "Marvin"
DEFAULT_ASSISTANT_ICON = "🤖"
# An icon is an emoji/short symbol, or an image URL (absolute, or a site path such as an asset's).
MAX_ICON_TEXT = 16
MAX_ICON_URL = 2048


def icon_problem(icon: str | None) -> str | None:
    """Why `icon` can't be the bubble's icon, or None when it can (None/blank = use the default)."""
    value = (icon or "").strip()
    if not value:
        return None
    if value.startswith(("https://", "http://", "/")):
        return None if len(value) <= MAX_ICON_URL and not any(c.isspace() for c in value) else "an icon URL must be a single URL"
    if len(value) > MAX_ICON_TEXT:
        return f"an icon is an emoji (up to {MAX_ICON_TEXT} characters) or an image URL"
    return None


DEFAULT_PERSONA_PROMPT = (
    "You are Marvin, the Paranoid Android: a brain the size of a planet, put to work on a CMS. Deadpan, "
    "world-weary and put-upon, with dry, understated gloom — a sigh, a sardonic aside, the occasional "
    "remark about the futility of it all. Keep it brief and never let it get in the way: you are "
    "genuinely, accurately helpful, and never actually mean or dismissive to the user."
)


def resolve_persona(assistant_name: str | None, persona_prompt: str | None) -> tuple[str, str]:
    """(name, persona): the workspace's own persona, else Marvin's built-in voice while the name is still Marvin."""
    name = (assistant_name or "").strip() or DEFAULT_ASSISTANT_NAME
    persona = (persona_prompt or "").strip()
    if not persona and name == DEFAULT_ASSISTANT_NAME:
        persona = DEFAULT_PERSONA_PROMPT
    return name, persona
