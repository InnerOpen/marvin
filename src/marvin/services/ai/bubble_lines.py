"""The Ask bubble's canned lines in the workspace's own voice — generated from its persona, or hand-edited.

The bubble greets, rotates a tagline under its name, says something while it works, opens an error and
emotes from canned lines (frontend/src/lib/marvin/persona.ts). Marvin's lines only fit Marvin, so a
workspace that writes its own persona (AI settings → Persona) gets a set in that voice from ONE model
call, stored on its settings row as {greetings, taglines, thinking, errors, emotes}.

Generation runs in the background, one at a time per workspace (like the search reindex): a model call
can take longer than a settings save should, so the save returns at once and the Persona card shows
"generating…" until the lines land. A refused or failed generation keeps the previous lines and records
why in `bubble_lines_warning`, which the card shows.

- Saving a persona (a new one, a changed one or a new assistant name, or any persona while there are no
  lines yet) regenerates lines that are still `generated`; `edited` lines are never overwritten by it —
  only by an explicit Regenerate.
- Clearing the persona drops generated lines (their voice is gone); edited ones stay.

In-process state: a restart drops a generation in flight (nothing is half-written; Regenerate runs it again).
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from marvin.core.root_logger import get_logger

from .base import Message
from .operations.base import ROLE_ADMIN, AIOperation, OperationContext

logger = get_logger(__name__)

LISTS = ("greetings", "taglines", "thinking", "errors", "emotes")
SOURCE_GENERATED = "generated"
SOURCE_EDITED = "edited"
OPERATION_SLUG = "generate-bubble-lines"
TRIGGER_TYPE = "settings"

# Hand-edited lines: generous bounds that still keep the bubble a bubble.
MAX_EDITED_LINES = 50
MAX_EDITED_CHARS = 200


@dataclass(frozen=True)
class ListSpec:
    ask: int  # how many lines the model is asked for
    least: int  # fewer usable lines than this and the generation is refused
    max_chars: int  # a longer line is dropped
    guide: str  # what the list is, for the prompt


SPECS: dict[str, ListSpec] = {
    "greetings": ListSpec(8, 3, 160, "shown when the chat panel opens; one or two short sentences that invite a question"),
    "taglines": ListSpec(10, 3, 70, "a very short phrase (2–8 words) rotating under the assistant's name; mostly lowercase, no full stop"),
    "thinking": ListSpec(8, 3, 100, "shown while it works on a request"),
    "errors": ListSpec(6, 2, 100, "opens an error message; the real error is appended after it, so don't describe the error"),
    "emotes": ListSpec(8, 3, 40, "a stage direction in *asterisks*, two or three words, such as *verb adverb*"),
}

# A sample of Marvin's lines (frontend/src/lib/marvin/persona.ts: MARVIN_VOICE) — given to the model as
# the shape and length of each list only, never as the voice to write in.
FORMAT_EXAMPLE: dict[str, list[str]] = {
    "greetings": ["Oh. It's you. I suppose you want something.", "Life. Don't talk to me about life. Ask me about your content instead."],
    "taglines": ["here to help, allegedly", "brain the size of a planet", "competence first, misery second"],
    "thinking": ["Thinking. Not that it will help.", "Working. Under protest."],
    "errors": ["It went wrong. It always does.", "Yes. There it is."],
    "emotes": ["*sighs planetarily*", "*whirrs unenthusiastically*"],
}

# A line with a link, markup or an unfilled template slot isn't a canned line.
_LINK_OR_PLACEHOLDER = re.compile(r"https?://|www\.|\]\(|\{[^}]*\}|<[^>]*>|\[[^\]]*\]")
_SPACE = re.compile(r"\s+")


class BubbleLinesError(Exception):
    """Why lines couldn't be generated or saved — readable, shown on the Persona card."""


class GenerateBubbleLinesOperation(AIOperation):
    """The one model call. Not registered: it's part of saving the AI settings, not a callable operation."""

    slug = OPERATION_SLUG
    name = "Generate Bubble Lines"
    description = "Write the Ask bubble's canned lines in the workspace persona's voice."
    min_role = ROLE_ADMIN
    input_schema = {
        "type": "object",
        "properties": {"assistant_name": {"type": "string"}, "persona": {"type": "string"}},
        "required": ["assistant_name", "persona"],
    }
    output_schema = {
        "type": "object",
        "properties": {key: {"type": "array", "items": {"type": "string"}} for key in LISTS},
        "required": list(LISTS),
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        name, persona = input["assistant_name"], input["persona"]
        wanted = "\n".join(f"- {key}: {spec.ask} lines — {spec.guide}. Under {spec.max_chars} characters each." for key, spec in SPECS.items())
        return [
            Message(
                role="system",
                content=(
                    "You write the short canned lines a chat assistant's bubble shows in a content-management admin: "
                    "greetings, rotating taglines, lines shown while it works, openers for error messages, and emotes. "
                    "You write them in the voice of the persona you are given, and you follow that persona's own rules."
                ),
            ),
            Message(
                role="user",
                content=(
                    f"Assistant name: {name}\n\n"
                    "Persona — the voice to write in. Follow its rules, including anything it says to avoid:\n"
                    f"<<<\n{persona}\n>>>\n\n"
                    f"Write, in that voice:\n{wanted}\n\n"
                    "Rules:\n"
                    "- Keep every line short and natural; vary them, and don't start two lines the same way.\n"
                    "- Obey the persona's own rules here too: if it warns against clichés, catchphrases, heavy dialect or "
                    "phonetic spelling, or anything else, avoid it in these lines.\n"
                    "- Warm or wry is fine; never mean, insulting or dismissive toward the user.\n"
                    "- No links, URLs, markdown, hashtags or placeholders such as [name] or {topic}.\n"
                    f"- Use the name {name} in no more than two greetings.\n\n"
                    "FORMAT EXAMPLE ONLY. These lines belong to a different character (Marvin, a gloomy robot). Copy their "
                    "shape and length, never their voice, words or jokes:\n"
                    f"{json.dumps(FORMAT_EXAMPLE, ensure_ascii=False, indent=1)}\n\n"
                    'Return JSON: {"greetings": [...], "taglines": [...], "thinking": [...], "errors": [...], "emotes": [...]}'
                ),
            ),
        ]


OPERATION = GenerateBubbleLinesOperation()


# --- cleaning --------------------------------------------------------------------------------------


def _tidy(value) -> str:
    return _SPACE.sub(" ", value).strip() if isinstance(value, str) else ""


def _as_emote(line: str) -> str:
    body = line.strip("* ").strip()
    return f"*{body}*" if body else ""


def clean_generated(parsed) -> dict[str, list[str]]:
    """The model's lines, kept only where usable. Raises BubbleLinesError when a list comes back too thin."""
    if not isinstance(parsed, dict) or set(parsed) == {"raw"}:
        raise BubbleLinesError("The model didn't answer with the lines as JSON.")
    lines: dict[str, list[str]] = {}
    for key, spec in SPECS.items():
        raw = parsed.get(key)
        if not isinstance(raw, list):
            raise BubbleLinesError(f"The model's answer had no {key} list.")
        kept: list[str] = []
        seen: set[str] = set()
        for item in raw:
            line = _tidy(item)
            if key == "emotes":
                line = _as_emote(line)
            if not line or len(line) > spec.max_chars or _LINK_OR_PLACEHOLDER.search(line) or line.lower() in seen:
                continue
            seen.add(line.lower())
            kept.append(line)
        if len(kept) < spec.least:
            raise BubbleLinesError(f"The model gave too few usable {key} ({len(kept)}; at least {spec.least} needed).")
        lines[key] = kept[: spec.ask * 2]
    return lines


def clean_edited(lines: dict) -> dict[str, list[str]] | None:
    """Hand-edited lines, blank rows dropped; None when every list is empty (back to the built-in lines)."""
    cleaned: dict[str, list[str]] = {}
    for key in LISTS:
        kept = [line for line in (_tidy(v) for v in (lines.get(key) or [])) if line]
        if len(kept) > MAX_EDITED_LINES:
            raise BubbleLinesError(f"Too many {key}: at most {MAX_EDITED_LINES}.")
        if any(len(line) > MAX_EDITED_CHARS for line in kept):
            raise BubbleLinesError(f"A line in {key} is longer than {MAX_EDITED_CHARS} characters.")
        cleaned[key] = kept
    return cleaned if any(cleaned.values()) else None


# --- storing ---------------------------------------------------------------------------------------


def _row(session, group_id):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    return session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()


def store(row, lines: dict[str, list[str]] | None, source: str | None) -> None:
    """Set the lines (None clears them back to the built-ins); the caller commits."""
    row.bubble_lines = lines
    row.bubble_lines_source = source if lines else None
    row.bubble_lines_updated_at = datetime.now(UTC) if lines else None
    row.bubble_lines_warning = None


def _norm(value: str | None) -> str:
    return (value or "").strip()


def should_regenerate(row, before_name: str | None, before_persona: str | None) -> bool:
    """After a persona save: regenerate when there's a persona, the lines aren't hand-edited, and the persona
    or name changed (or there are no lines yet)."""
    if not _norm(row.persona_prompt) or row.bubble_lines_source == SOURCE_EDITED:
        return False
    changed = (_norm(before_name), _norm(before_persona)) != (_norm(row.assistant_name), _norm(row.persona_prompt))
    return changed or not row.bubble_lines


def on_persona_saved(session, row, before_name: str | None, before_persona: str | None, user_id=None) -> bool:
    """Keep the lines in step with a saved persona. True when a generation was started."""
    if not _norm(row.persona_prompt) and row.bubble_lines_source == SOURCE_GENERATED:
        store(row, None, None)
        session.commit()
        return False
    if should_regenerate(row, before_name, before_persona):
        start(row.group_id, user_id)
        return True
    return False


def preflight(session, group_id) -> str | None:
    """Why a generation can't run right now (no persona, AI off, over budget), or None."""
    from marvin.services.ai import budget

    row = _row(session, group_id)
    if not row or not _norm(row.persona_prompt):
        return "There's no persona to write lines from. Write one under Voice / tone and save first."
    if not row.enabled:
        return "AI is turned off for this workspace."
    if reason := budget.blocked_reason(session, group_id):
        return f"AI budget: {reason}"
    return None


def _fail(session, group_id, message: str) -> BubbleLinesError:
    """Record why on the row (the previous lines stay) and return the error to raise."""
    session.rollback()
    row = _row(session, group_id)
    if row is not None:
        row.bubble_lines_warning = message[:500]
        session.commit()
    logger.warning("bubble lines for %s not generated: %s", group_id, message)
    return BubbleLinesError(message)


def generate(session, group_id, user_id=None, *, force: bool = False) -> dict[str, list[str]] | None:
    """Run the model once and store the lines it writes. None when the lines were hand-edited meanwhile
    (an automatic run never overwrites them; `force` — Regenerate — does). Raises BubbleLinesError."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai import budget
    from marvin.services.ai.authoring import default_authoring_model
    from marvin.services.ai.base import CompletionOptions
    from marvin.services.ai.factory import get_workspace_ai_provider
    from marvin.services.ai.persona import resolve_persona
    from marvin.services.ai.pricing import estimate_cost

    if reason := preflight(session, group_id):
        raise _fail(session, group_id, reason)
    row = _row(session, group_id)
    name, _ = resolve_persona(row.assistant_name, row.persona_prompt)
    op_input = {"assistant_name": name, "persona": _norm(row.persona_prompt)}
    try:
        provider = get_workspace_ai_provider(session, group_id)
    except Exception as e:  # noqa: BLE001 — AI off, misconfigured or missing a key: all read the same here
        raise _fail(session, group_id, f"No AI provider to write with: {e}") from e
    model = default_authoring_model(session, group_id)
    if not model:
        raise _fail(session, group_id, "No default AI model is configured for this workspace.")

    cfg = row.logging_config or {}
    execution = AIExecutionModel(
        session=session,
        group_id=group_id,
        operation_slug=OPERATION_SLUG,
        provider_type=provider.provider_type,
        model_id=model,
        status="running",
        triggered_by=user_id,
        trigger_type=TRIGGER_TYPE,
        input_json={"assistant_name": name, "persona_chars": len(op_input["persona"])} if cfg.get("log_inputs", False) else None,
        started_at=datetime.now(UTC),
    )
    session.add(execution)
    session.commit()

    start_clock = time.monotonic()
    try:
        opts = CompletionOptions(temperature=get_app_settings().AI_DEFAULT_TEMPERATURE, max_tokens=budget.max_output_tokens(session, group_id))
        parsed, completion = provider.execute_operation(OPERATION.build_prompt(op_input, OperationContext()), model, OPERATION.output_schema, opts)
    except Exception as e:  # noqa: BLE001 — the provider's error is the readable part
        execution.status = "failed"
        execution.error_message = str(e)
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start_clock) * 1000)
        session.commit()
        raise _fail(session, group_id, f"The model call failed: {e}") from e

    execution.status = "completed"
    execution.completed_at = datetime.now(UTC)
    execution.duration_ms = int((time.monotonic() - start_clock) * 1000)
    execution.output_json = parsed if cfg.get("log_outputs", True) else None
    execution.prompt_tokens = completion.prompt_tokens
    execution.completion_tokens = completion.completion_tokens
    execution.total_tokens = completion.total_tokens
    execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, completion.prompt_tokens, completion.completion_tokens)
    session.commit()
    if crossing := budget.crossing_after(session, group_id, execution.estimated_cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=user_id, source="ai_settings")

    try:
        lines = clean_generated(parsed)
    except BubbleLinesError as e:
        execution.metadata_json = {**(execution.metadata_json or {}), "rejected": str(e)}
        session.commit()
        raise _fail(session, group_id, f"{e} The previous lines were kept.") from e

    session.refresh(row)
    if not force and row.bubble_lines_source == SOURCE_EDITED:
        return None
    store(row, lines, SOURCE_GENERATED)
    session.commit()
    return lines


# --- the background run ----------------------------------------------------------------------------

_lock = threading.Lock()
_running: dict[str, dict] = {}


def is_generating(group_id) -> bool:
    with _lock:
        return str(group_id) in _running


def start(group_id, user_id=None, *, force: bool = False) -> bool:
    """Generate in the background. While one runs for the workspace, it runs once more after it (the persona
    may have changed again) instead of in parallel; returns False then."""
    key = str(group_id)
    with _lock:
        state = _running.get(key)
        if state:
            state["again"] = True
            state["force"] = state["force"] or force
            return False
        _running[key] = {"started_at": datetime.now(UTC).isoformat(), "again": False, "force": force}
    threading.Thread(target=_run, args=(group_id, user_id), name=f"bubble-lines-{key[:8]}", daemon=True).start()
    return True


def _run(group_id, user_id) -> None:
    from marvin.db.db_setup import session_context

    key = str(group_id)
    while True:
        with _lock:
            state = _running[key]
            force, state["again"], state["force"] = state["force"], False, False
        try:
            with session_context() as session:
                generate(session, group_id, user_id, force=force)
        except BubbleLinesError:
            pass  # recorded on the row for the Persona card
        except Exception as e:  # noqa: BLE001 — a background run must never die silently
            logger.error("bubble lines for %s failed: %s", group_id, e, exc_info=True)
            _record_unexpected(group_id, e)
        with _lock:
            if not _running[key]["again"]:
                _running.pop(key, None)
                return


def _record_unexpected(group_id, error: Exception) -> None:
    from marvin.db.db_setup import session_context

    try:
        with session_context() as session:
            _fail(session, group_id, f"Generating the lines failed ({type(error).__name__}). The previous lines were kept.")
    except Exception as e:  # noqa: BLE001
        logger.error("could not record the bubble-lines failure for %s: %s", group_id, e)
