"""The Social Battery: a mood meter each character keeps about the person it talks to (tasks/social-battery-plan.md;
Brain: "Marvin Agent Social Battery"). Red Dead Redemption's honour system for a CMS assistant.

It changes **flavour only**: one line in the prompt between the Character and the tone (``prompt_line``), the bubble's
greetings and taglines by band, and its idle state. Never the help. The guardrails, in order of importance:

1. Only rudeness aimed at the assistant drains the meter (``_insulted``); frustration with the *problem* — "this is broken",
   "useless feature" — never does. Frustrated people need help most.
2. Help quality never changes: the prompt line says so in as many words, and nothing here touches tools or limits.
3. It is visible (the character's ``meter`` choice can hide the number, not the behaviour) and resettable
   ("Reset our relationship", ``reset``), and the bubble explains it as a game.
4. Off until a workspace switches it on (``workspace_ai_settings.mood_enabled``).

The rules (``score``) run on the person's message — no model call — with the character's ``MoodSettings``
(``effective_settings``: the agent's own when it has any, else the workspace's; unset choices take the defaults):

* charges: thanks (+6), praise or "that worked" (+6; both +10);
* drains: an insult aimed at the assistant (−12); the same message again (−4); rapid fire, the 5th+ message within two
  minutes (−3); a very long session, the 25th+ message within 90 minutes (−2); and, when the character's ``drains`` is
  ``use`` (Marvin's social battery), every message (−2) on top;
* drift toward 50 between messages: ``daily`` memory starts each UTC day at 50; ``weeks`` memory closes 10% of the distance
  per day;
* a long absence (3+ days) first: ``recharges`` +15, ``cools`` −10, ``neutral`` nothing.

The level is clamped to 0–100; the bands are low (≤ 30), neutral and high (≥ 70). One row per (workspace, person, agent)
(``AIMoodMeterModel``); a person's meter for one agent says nothing about their meter for another.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.ai_mood import MOOD_START, AIMoodMeterModel

LOW, NEUTRAL, HIGH = "low", "neutral", "high"
LOW_MAX, HIGH_MIN = 30, 70
DEFAULTS = {"drains": "treatment", "meter": "visible", "memory": "weeks", "absence": "neutral"}

CHARGE_THANKS, CHARGE_PRAISE, CHARGE_BOTH = 6, 6, 10
DRAIN_INSULT, DRAIN_REPEAT, DRAIN_RAPID, DRAIN_LONG, DRAIN_USE = 12, 4, 3, 2, 2
RAPID_COUNT, RAPID_WINDOW = 5, timedelta(minutes=2)
LONG_COUNT, LONG_WINDOW = 25, timedelta(minutes=90)
ABSENCE_AFTER = timedelta(days=3)
ABSENCE_RECHARGE, ABSENCE_COOL = 15, 10
DRIFT_PER_DAY = 0.10
MESSAGES_KEPT, TEXTS_KEPT, SIGNALS_KEPT = 30, 6, 12
REPEAT_MIN_CHARS = 12
"""A short message said twice ("yes", "thanks") is conversation, not the same correction again."""

_THANKS = re.compile(r"\b(thanks|thank you|thankyou|thx|ty|cheers|appreciated?|much obliged)\b")
_PRAISE = re.compile(
    r"\b(perfect|brilliant|awesome|excellent|wonderful|fantastic|nice (one|work)|well done|good (job|work|bot)|"
    r"love (it|that|this)|that worked|works now|that did it|nailed it|spot on|you(?:'re| are) (the best|a star|great|amazing))\b"
)
# Rudeness aimed at the assistant: an insult with the assistant as its target ("you", or its name). "This is useless"
# and "stupid bug" have no target here: that is frustration with the problem, and never drains.
# Only words that are insults whatever they're said about: "trash" and "garbage" are ordinary nouns in a CMS ("can you trash these
# drafts?"), so they are not here.
_INSULT_WORDS = r"(useless|stupid|idiot(ic)?|dumb|pathetic|worthless|moron(ic)?|incompetent|braindead|hopeless)"
_FILLERS = r"(?:(?:being|so|such|really|just|totally|completely|utterly|pretty|a|an|the)\s+)*"
# The insult has to be *about* the assistant: it follows "you are" / "you're" / "you" (the vocative, "you idiot") directly,
# or the assistant's name, with only filler words between. "You" with an insult somewhere later in the sentence is not
# enough: "can you delete the useless drafts?" is a request, and "this is useless" / "stupid bug" are about the problem.
_AT_YOU = re.compile(r"\b(?:you(?:'re|re| are| r)|u r|ur|you)\s+" + _FILLERS + _INSULT_WORDS + r"\b")
_BOT_INSULT = re.compile(r"\b" + _INSULT_WORDS + r" (bot|assistant|ai|robot)\b")
_TELL_OFF = re.compile(r"\b(shut up|screw you|piss off|get lost|f+u+c*k+ (you|off)|fuck off)\b")
_TAG = re.compile(r"[@#]\w+")


@dataclass(frozen=True)
class MoodState:
    """A meter as the run and the bubble see it."""

    level: int
    band: str
    visible: bool
    drains: str
    crossed: bool = False
    """The level just entered a new band (the first message there gets a milestone aside)."""

    def public(self) -> dict:
        """What the API says: the number only when the character shows its meter."""
        return {"level": self.level if self.visible else None, "band": self.band, "visible": self.visible}


def effective_settings(workspace_mood: dict | None, agent_mood: dict | None) -> dict:
    """The MoodSettings a character runs with: the agent's own when it has any, else the workspace's; each unset choice
    takes its default. ``low`` / ``high`` are the band's lines (``{greetings, taglines}``), empty when none."""
    source = agent_mood if isinstance(agent_mood, dict) and agent_mood else (workspace_mood if isinstance(workspace_mood, dict) else {})
    out = {key: (source.get(key) if source.get(key) in _CHOICES[key] else default) for key, default in DEFAULTS.items()}
    for band in (LOW, HIGH):
        lines = source.get(band) if isinstance(source.get(band), dict) else {}
        out[band] = {k: [str(x) for x in lines.get(k) or []] for k in ("greetings", "taglines")}
    return out


_CHOICES = {
    "drains": ("use", "treatment"),
    "meter": ("visible", "hidden"),
    "memory": ("daily", "weeks"),
    "absence": ("recharges", "cools", "neutral"),
}


def band_of(level: int) -> str:
    return LOW if level <= LOW_MAX else HIGH if level >= HIGH_MIN else NEUTRAL


def _clamp(level: float) -> int:
    return int(max(0, min(100, round(level))))


def _naive(when: datetime) -> datetime:
    return when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when


def _normal(text: str) -> str:
    return " ".join(_TAG.sub(" ", (text or "").lower()).split())


def _fingerprint(text: str) -> str:
    """The same words again count as the same message: punctuation, case and spacing don't make it new."""
    words = re.findall(r"[^\W_]+", _normal(text))
    return hashlib.sha1(" ".join(words).encode()).hexdigest()[:12]


def _insulted(text: str, names: tuple[str, ...]) -> bool:
    """Whether the message insults the assistant itself (never the problem)."""
    low = _normal(text)
    if _AT_YOU.search(low) or _BOT_INSULT.search(low) or _TELL_OFF.search(low):
        return True
    for name in names:
        n = _normal(name)
        if n and re.search(rf"\b{re.escape(n)}\s+(?:(?:is|are|'s)\s+)?{_FILLERS}{_INSULT_WORDS}\b", low):
            return True
    return False


def drifted(level: int, last_seen: datetime | None, now: datetime, settings: dict) -> tuple[int, list[tuple[str, int]]]:
    """The level as time alone left it since ``last_seen``: the memory's drift toward 50, then a long absence's effect.
    Returns the new level and the signals that explain it."""
    if last_seen is None:
        return level, []
    gap = _naive(now) - _naive(last_seen)
    signals: list[tuple[str, int]] = []
    value = float(level)
    if settings["memory"] == "daily":
        if _naive(now).date() != _naive(last_seen).date() and value != MOOD_START:
            signals.append(("new_day", MOOD_START - int(value)))
            value = MOOD_START
    elif gap > timedelta(0):
        days = gap.total_seconds() / 86400
        toward = (MOOD_START - value) * (1 - (1 - DRIFT_PER_DAY) ** days)
        if abs(toward) >= 1:
            signals.append(("drift", int(round(toward))))
            value += toward
    if gap >= ABSENCE_AFTER and settings["absence"] != "neutral":
        delta = ABSENCE_RECHARGE if settings["absence"] == "recharges" else -ABSENCE_COOL
        signals.append(("absence", delta))
        value += delta
    return _clamp(value), signals


def message_signals(text: str, state: dict, now: datetime, settings: dict, names: tuple[str, ...]) -> list[tuple[str, int]]:
    """What this one message does to the meter, by the rules in the module docstring (``state`` is the meter's recent past)."""
    low = _normal(text)
    signals: list[tuple[str, int]] = []
    thanked, praised = bool(_THANKS.search(low)), bool(_PRAISE.search(low))
    if thanked and praised:
        signals.append(("thanks_and_praise", CHARGE_BOTH))
    elif thanked:
        signals.append(("thanks", CHARGE_THANKS))
    elif praised:
        signals.append(("praise", CHARGE_PRAISE))
    if _insulted(text, names):
        signals.append(("insult", -DRAIN_INSULT))
    if not (thanked or praised) and len(low) >= REPEAT_MIN_CHARS and _fingerprint(text) in (state.get("texts") or []):
        signals.append(("repeat", -DRAIN_REPEAT))
    stamps = [datetime.fromisoformat(s) for s in state.get("messages") or [] if isinstance(s, str)]
    at = _naive(now)
    if sum(1 for s in stamps if at - s <= RAPID_WINDOW) + 1 >= RAPID_COUNT:
        signals.append(("rapid_fire", -DRAIN_RAPID))
    if sum(1 for s in stamps if at - s <= LONG_WINDOW) + 1 >= LONG_COUNT:
        signals.append(("long_session", -DRAIN_LONG))
    if settings["drains"] == "use":
        signals.append(("use", -DRAIN_USE))
    return signals


def _row(session, group_id, user_id, agent_slug: str) -> AIMoodMeterModel | None:
    return session.query(AIMoodMeterModel).filter_by(group_id=group_id, user_id=user_id, agent_slug=agent_slug).first()


def current(session, group_id, user_id, agent_slug: str, settings: dict, *, now: datetime | None = None) -> MoodState:
    """The meter as of now, drift included, without writing anything (the bubble asks when it opens)."""
    now = now or datetime.now(UTC)
    row = _row(session, group_id, user_id, agent_slug)
    level = MOOD_START if row is None else drifted(row.level, row.last_seen_at, now, settings)[0]
    return MoodState(level=level, band=band_of(level), visible=settings["meter"] != "hidden", drains=settings["drains"])


def score(
    session, group_id, user_id, agent_slug: str, settings: dict, text: str, *, names: tuple[str, ...] = (), now: datetime | None = None
) -> MoodState:
    """Apply one message the person sent this agent: time's drift and any absence first, then the message's own signals.
    Writes and commits the meter (a reply that then fails still happened to the character). Never raises past the
    caller's session: a failure here is the meter's alone (the caller catches and goes on without a mood)."""
    now = now or datetime.now(UTC)
    at = _naive(now)
    row = _row(session, group_id, user_id, agent_slug)
    if row is None:
        row = AIMoodMeterModel(session=session, group_id=group_id, user_id=user_id, agent_slug=agent_slug, level=MOOD_START)
        session.add(row)
    before = band_of(row.level)
    level, signals = drifted(row.level, row.last_seen_at, now, settings)
    state = dict(row.state or {})
    own = message_signals(text, state, now, settings, names)
    level = _clamp(level + sum(delta for _, delta in own))
    signals += own
    band = band_of(level)
    crossed = band != NEUTRAL and band != before
    row.level = level
    row.last_seen_at = at
    if band != (row.band_since or {}).get("band"):
        row.band_since = {"band": band, "at": at.isoformat()}
    row.state = {
        "messages": ((state.get("messages") or []) + [at.isoformat()])[-MESSAGES_KEPT:],
        "texts": ((state.get("texts") or []) + [_fingerprint(text)])[-TEXTS_KEPT:],
        "signals": ((state.get("signals") or []) + [{"kind": k, "delta": d, "at": at.isoformat()} for k, d in signals if d])[-SIGNALS_KEPT:],
    }
    session.commit()
    return MoodState(level=level, band=band, visible=settings["meter"] != "hidden", drains=settings["drains"], crossed=crossed)


def reset(session, group_id, user_id, agent_slug: str, *, now: datetime | None = None) -> None:
    """ "Reset our relationship": back to 50 with no past, and commits. A meter that never existed stays that way."""
    row = _row(session, group_id, user_id, agent_slug)
    if row is None:
        return
    row.level, row.band_since, row.state = MOOD_START, None, None
    row.last_seen_at = None
    row.reset_at = _naive(now or datetime.now(UTC))
    session.commit()


# ── the prompt line ──────────────────────────────────────────────────────────────────────────────────────────────

MOOD_LABEL = "Mood: "
_LINES = {
    (LOW, "use"): "drained — they've asked a lot lately and your social battery is low; a weary aside is fair.",
    (LOW, "treatment"): "cool — things have been curt between you lately; a dry, guarded aside is fair.",
    (HIGH, "use"): "rested — they've given you room to breathe; a touch of good cheer (however unsettling) is fair.",
    (HIGH, "treatment"): "warm — things have gone well between you; a little warmth, or a dry compliment, is fair.",
}
FLAVOUR_RULE = (
    " This changes flavour only — a greeting, an aside — never the help: stay as thorough and as willing, never refuse, "
    "never guilt-trip, and don't mention the meter unless asked."
)
MILESTONE = " It's the first time in a while they've brought you here: one short aside acknowledging it is fine."


def prompt_line(state: MoodState | None) -> str:
    """The one line a run gets between its Character and its tone; "" in a neutral mood (or with no meter)."""
    if state is None or state.band == NEUTRAL:
        return ""
    return MOOD_LABEL + _LINES[(state.band, state.drains)] + FLAVOUR_RULE + (MILESTONE if state.crossed else "")
