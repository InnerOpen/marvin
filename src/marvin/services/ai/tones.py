"""Tones — how a run delivers its work, separate from the persona (who the assistant is).

The persona is the workspace's **character**: who the assistant is and how it speaks. A tone is how a run
delivers — free-text instructions plus a persona rule that says how far the character reaches:

- ``frame``: the character frames the conversation (greetings, asides); work product follows the tone.
- ``everywhere``: the character applies to everything, work product included, alongside the tone.
- ``drop``: the character is withheld for the run. Withholding is the mechanism — asking a model to
  compartmentalise is advisory, and small models ignore it.

In the prompt the persona is labelled ``Character:`` and the tone ``Tone (<name>):``. When both apply, a
precedence rule follows: the tone wins on formality, length and mood; the character keeps its identity and
way of speaking. :func:`tone_parts` returns the section in those parts so the editor can show which line
came from the persona and which from the tone.

The built-ins ``auto`` / ``professional`` / ``playful`` are code, not rows: a workspace can hide them
from its pickers but not edit or delete them, and their exact wording is pinned by golden tests. Custom
tones live on the workspace AI settings row (``tones`` + ``hidden_tones``). A slug is fixed when the tone
is created, so renaming a tone never breaks an agent, a parked run or a workspace default that refers to it.

At run time an unknown slug (a tone deleted since, an imported agent) never fails a run: resolution falls
back caller → agent → workspace default → ``auto`` and logs a warning. On save an unknown slug is a 422.
"""

import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PERSONA_FRAME = "frame"
PERSONA_EVERYWHERE = "everywhere"
PERSONA_DROP = "drop"
PERSONA_MODES = (PERSONA_FRAME, PERSONA_EVERYWHERE, PERSONA_DROP)

AUTO = "auto"
PROFESSIONAL = "professional"
PLAYFUL = "playful"

MAX_CUSTOM_TONES = 20
MAX_NAME_CHARS = 60
MAX_INSTRUCTIONS_CHARS = 1500
MAX_DESCRIPTION_CHARS = 200
# workspace_agents.default_register is String(40); a longer slug would be rejected by Postgres.
MAX_SLUG_CHARS = 40
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# Rough prompt-cost estimate shown in the editor; a tone's clause rides on every agent step.
CHARS_PER_TOKEN = 4


class ToneError(ValueError):
    """A tone list that can't be saved; the message is fit to show the admin."""


@dataclass(frozen=True)
class ToneSpec:
    slug: str
    name: str
    instructions: str
    persona: str = PERSONA_FRAME
    description: str | None = None
    builtin: bool = False

    def to_json(self) -> dict:
        """The stored shape (custom tones only — built-ins are never stored)."""
        out = {"slug": self.slug, "name": self.name, "instructions": self.instructions, "persona": self.persona}
        if self.description:
            out["description"] = self.description
        return out


# The prompt wording. Changing a byte here changes every workspace's prompts — the golden tests in
# tests/test_tones.py pin the exact strings.
CHARACTER_LABEL = "Character: "
PRECEDENCE_RULE = (
    "Where the tone and the character disagree on formality, length or mood, follow the tone; "
    "keep the character's identity and way of speaking otherwise."
)
_DROP_PERSONA = "\n\nDo not adopt a persona, voice, or character."
_PROFESSIONAL_CLAUSE = (
    "\n\nWrite plainly, specifically and professionally. Do not adopt a persona, "
    "voice, or character; skip pleasantries and lead with the substance. Be concrete: "
    "name the field, section, or line you mean, and say what to change and why."
)
# `auto`: the character frames chat; work product is plain (auto has no instructions of its own).
_AUTO_SCOPE = (
    "\nThe character applies ONLY to how you address the user — greetings, framing, brief "
    "asides. Work product itself — reviews, critiques, findings, summaries, suggested "
    "copy — must be written plainly, specifically, and professionally. Never let the "
    "character soften, exaggerate, or obscure a finding, and never write generated "
    "content in the character's voice unless the user explicitly asks for it."
)
# A custom `frame` tone: the character frames, the tone (not "plain") governs the work product.
_FRAME_SCOPE = (
    "\nThe character applies ONLY to how you address the user — greetings, framing, brief "
    "asides. Work product itself — reviews, critiques, findings, summaries, suggested "
    "copy — follows the tone below, not the character. Never let the character soften, "
    "exaggerate, or obscure a finding."
)
# `playful` and custom `everywhere` tones.
_EVERYWHERE_SCOPE = "\nThe character applies to everything you write, work product included."

# The persona rule in plain words, as the tone editor's preview shows it.
_PERSONA_SUMMARY = {
    PERSONA_FRAME: "Frame only: the character talks, work product follows this tone.",
    PERSONA_EVERYWHERE: "Everywhere: the character and this tone apply to everything, work product included.",
    PERSONA_DROP: "Drop: no character, just this tone.",
}

BUILTIN_TONES: tuple[ToneSpec, ...] = (
    ToneSpec(
        slug=AUTO,
        name="Auto",
        instructions="",
        persona=PERSONA_FRAME,
        description="Character for chat, plain for work.",
        builtin=True,
    ),
    ToneSpec(
        slug=PROFESSIONAL,
        name="Professional",
        instructions="Write plainly, specifically and professionally. Skip pleasantries and lead with the substance.",
        persona=PERSONA_DROP,
        description="Plain everywhere, no character.",
        builtin=True,
    ),
    ToneSpec(
        slug=PLAYFUL,
        name="Playful",
        instructions="",
        persona=PERSONA_EVERYWHERE,
        description="The character applies to everything.",
        builtin=True,
    ),
)
BUILTIN_SLUGS = tuple(t.slug for t in BUILTIN_TONES)
_BUILTIN_BY_SLUG = {t.slug: t for t in BUILTIN_TONES}


@dataclass(frozen=True)
class ToneParts:
    """A tone's prompt section in its parts, in prompt order; ``text`` is exactly what is appended."""

    character: str = ""  # from the persona: the Character block ("" when the tone drops it, or there is none)
    scope: str = ""  # from the tone's persona rule: how far the character reaches
    tone: str = ""  # from the tone: its instructions (and a drop tone's "Do not adopt a persona…")
    rule: str = ""  # precedence, when a character and a tone's instructions both apply

    @property
    def text(self) -> str:
        return self.character + self.scope + self.tone + self.rule


def _builtin_parts(tone: ToneSpec, persona_prompt: str) -> ToneParts:
    if tone.slug == PROFESSIONAL:
        return ToneParts(tone=_PROFESSIONAL_CLAUSE)
    if not persona_prompt:
        return ToneParts()
    scope = _EVERYWHERE_SCOPE if tone.slug == PLAYFUL else _AUTO_SCOPE
    return ToneParts(character=f"\n\n{CHARACTER_LABEL}{persona_prompt}", scope=scope)


def tone_parts(tone: ToneSpec, persona_prompt: str) -> ToneParts:
    """The character/tone section of an agent's system prompt, in parts (see :class:`ToneParts`).

    Empty when there is nothing to say: a built-in that only places the character, with no persona set.
    """
    persona_prompt = (persona_prompt or "").strip()
    if tone.builtin:
        return _builtin_parts(tone, persona_prompt)

    tone_text = f"\n\nTone ({tone.name}): {tone.instructions}"
    if tone.persona == PERSONA_DROP:
        return ToneParts(tone=f"{_DROP_PERSONA}{tone_text}")
    if not persona_prompt:
        return ToneParts(tone=tone_text)
    scope = _EVERYWHERE_SCOPE if tone.persona == PERSONA_EVERYWHERE else _FRAME_SCOPE
    return ToneParts(character=f"\n\n{CHARACTER_LABEL}{persona_prompt}", scope=scope, tone=tone_text, rule=f"\n\n{PRECEDENCE_RULE}")


def tone_clause(tone: ToneSpec, persona_prompt: str) -> str:
    """The character/tone section appended (last) to an agent's system prompt; "" when there is nothing to say."""
    return tone_parts(tone, persona_prompt).text


def persona_summary(tone: ToneSpec) -> str:
    """The tone's persona rule in plain words (the built-ins say what they actually do)."""
    if tone.slug == AUTO:
        return "Frame only: the character talks, work product stays plain."
    if tone.slug == PLAYFUL:
        return "Everywhere: the character applies to everything, work product included."
    if tone.slug == PROFESSIONAL:
        return "Drop: no character, just plain and professional."
    return _PERSONA_SUMMARY[tone.persona]


def draft_voice(tone: ToneSpec, persona_prompt: str) -> str:
    """The voice a composed/revised draft is written in under `tone`, or "" for the plain default.

    A draft is work product, so the character joins it only under an `everywhere` tone; otherwise only a
    custom tone's instructions apply. The built-ins keep drafts as they were (plain) except `playful`, whose
    whole point is the character everywhere. Labelled like :func:`tone_clause`, with the same precedence
    rule when both apply. The entry type's own voice (recipe `enrichment.voice`) outranks this — the
    caller only asks when there is none.
    """
    persona_prompt = (persona_prompt or "").strip()
    parts = []
    if persona_prompt and tone.persona == PERSONA_EVERYWHERE:
        parts.append(f"{CHARACTER_LABEL}{persona_prompt}\nWrite the draft in this character.")
    if not tone.builtin and tone.instructions:
        parts.append(f"Tone ({tone.name}): {tone.instructions}")
    if len(parts) == 2:
        parts.append(PRECEDENCE_RULE)
    return "\n".join(parts)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text or "") / CHARS_PER_TOKEN)


# ── Validation ─────────────────────────────────────────────────────────────────


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return base[:MAX_SLUG_CHARS].strip("-") or "tone"


def _unique_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = f"{base[: MAX_SLUG_CHARS - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in taken:
            return candidate
        n += 1


def _clean(value, limit: int, label: str, *, required: bool) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ToneError(f"{label} is required.")
    if len(text) > limit:
        raise ToneError(f"{label} must be at most {limit} characters.")
    return text


def validate_tones(items: Iterable[dict], existing: Iterable[ToneSpec] = ()) -> list[ToneSpec]:
    """Normalise a submitted list of custom tones, or raise ToneError.

    An item with a slug keeps it (that is how a rename keeps its slug); an item without one gets a slug
    from its name. Built-in slugs and names are reserved so `/tone professional` is never ambiguous.
    `existing` is only consulted so a brand-new tone never reuses a slug the workspace already had.
    """
    items = list(items or [])
    if len(items) > MAX_CUSTOM_TONES:
        raise ToneError(f"A workspace can have at most {MAX_CUSTOM_TONES} custom tones.")

    taken_slugs = set(BUILTIN_SLUGS)
    names = {t.name.casefold() for t in BUILTIN_TONES}
    explicit = [str(i.get("slug") or "").strip().lower() for i in items if isinstance(i, dict)]
    reserved_for_new = {t.slug for t in existing} | {s for s in explicit if s}

    out: list[ToneSpec] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ToneError("Each tone must be an object.")
        name = _clean(raw.get("name"), MAX_NAME_CHARS, "A tone's name", required=True)
        label = f"Tone '{name}'"
        instructions = _clean(raw.get("instructions"), MAX_INSTRUCTIONS_CHARS, f"{label}: instructions", required=True)
        description = _clean(raw.get("description"), MAX_DESCRIPTION_CHARS, f"{label}: description", required=False) or None
        persona = str(raw.get("persona") or PERSONA_FRAME).strip().lower()
        if persona not in PERSONA_MODES:
            raise ToneError(f"{label}: persona must be one of {', '.join(PERSONA_MODES)}.")
        if name.casefold() in names:
            raise ToneError(f"{label}: another tone already has that name.")
        names.add(name.casefold())

        slug = str(raw.get("slug") or "").strip().lower()
        if slug:
            if slug in BUILTIN_SLUGS:
                raise ToneError(f"{label}: '{slug}' is a built-in tone.")
            if not SLUG_RE.match(slug):
                raise ToneError(f"{label}: slug must be 1-{MAX_SLUG_CHARS} chars of a-z, 0-9 and '-'.")
            if slug in taken_slugs:
                raise ToneError(f"{label}: slug '{slug}' is used twice.")
        else:
            slug = _unique_slug(slugify(name), taken_slugs | reserved_for_new)
        taken_slugs.add(slug)
        out.append(ToneSpec(slug=slug, name=name, instructions=instructions, persona=persona, description=description))
    return out


def validate_hidden(slugs: Iterable[str], tones: Iterable[ToneSpec]) -> list[str]:
    """The hidden list, de-duplicated; every slug must name a tone (built-in or custom)."""
    known = {t.slug for t in tones}
    out: list[str] = []
    for s in slugs or []:
        slug = str(s or "").strip().lower()
        if slug not in known:
            raise ToneError(f"Can't hide '{slug}': there is no such tone.")
        if slug not in out:
            out.append(slug)
    return out


def parse_stored(raw) -> tuple[ToneSpec, ...]:
    """Custom tones from the stored JSON. Lenient — a malformed item is skipped, never fatal at run time."""
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug, name = str(item.get("slug") or ""), str(item.get("name") or "")
        if not slug or not name or slug in BUILTIN_SLUGS:
            continue
        persona = item.get("persona") if item.get("persona") in PERSONA_MODES else PERSONA_FRAME
        out.append(
            ToneSpec(
                slug=slug,
                name=name,
                instructions=str(item.get("instructions") or ""),
                persona=persona,
                description=item.get("description") or None,
            )
        )
    return tuple(out)


# ── A workspace's tones + resolution ─────────────────────────────────────────


@dataclass(frozen=True)
class WorkspaceTones:
    custom: tuple[ToneSpec, ...] = ()
    hidden: frozenset[str] = field(default_factory=frozenset)
    default_slug: str = AUTO  # the stored workspace default (may name a tone that no longer exists)

    def all(self) -> tuple[ToneSpec, ...]:
        return BUILTIN_TONES + self.custom

    def get(self, slug: str | None) -> ToneSpec | None:
        key = (slug or "").strip().lower()
        if not key:
            return None
        return _BUILTIN_BY_SLUG.get(key) or next((t for t in self.custom if t.slug == key), None)

    def find(self, ref: str | None) -> ToneSpec | None:
        """A tone by slug or (case-insensitive) name — what `/tone <name|slug>` types."""
        key = (ref or "").strip()
        return self.get(key) or next((t for t in self.all() if t.name.casefold() == key.casefold()), None)

    def resolve(self, *candidates: str | None) -> ToneSpec:
        """The first candidate that names a tone, then the workspace default, then `auto`.

        An unknown (deleted/imported) slug is skipped with a warning rather than failing the run.
        """
        for slug in (*candidates, self.default_slug):
            if not slug:
                continue
            tone = self.get(slug)
            if tone is not None:
                return tone
            logger.warning("Unknown tone '%s'; falling back", slug)
        return _BUILTIN_BY_SLUG[AUTO]

    @property
    def default(self) -> ToneSpec:
        return self.resolve()


def workspace_tones(settings_row) -> WorkspaceTones:
    """The tones a workspace AI settings row defines (None → just the built-ins)."""
    if settings_row is None:
        return WorkspaceTones()
    hidden = getattr(settings_row, "hidden_tones", None)
    default = getattr(settings_row, "default_register", None)
    return WorkspaceTones(
        custom=parse_stored(getattr(settings_row, "tones", None)),
        hidden=frozenset(s for s in hidden if isinstance(s, str)) if isinstance(hidden, list) else frozenset(),
        default_slug=default if isinstance(default, str) and default else AUTO,
    )


def load_workspace_tones(session, group_id) -> WorkspaceTones:
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    return workspace_tones(session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first())
