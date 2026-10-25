"""Check a caption before it is posted, for every network it is going to (tasks/caption-linter-plan.md).

The checks are core's and the same everywhere; each network's numbers are its plugin's (``post_limits``, Integration SDK
0.19.0: ``max``, ``unit``, ``visible``, ``hashtags_max``, ``links``). Pure: nothing is sent anywhere, no AI.

What it says, per network: the length against the limit (characters or graphemes), what the feed shows before "… more"
(``visible``), and the issues — over the limit, the first sentence cut off by "… more", an opening greeting or hashtag, a
link where links don't work, too many hashtags, stock phrases that read as filler. Idea from ``caption.py`` in Jake
Schincariol's instagram-agent-skill (MIT).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

ERROR, WARN = "error", "warn"
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<![\w&])#\w+")
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)|\n")
GREETINGS = ("hey guys", "hi guys", "hey everyone", "hi everyone", "hello everyone", "good morning", "hey", "hi", "hello", "welcome")
"""Openers that spend the visible line on nothing."""
STOCK_PHRASES = (
    "in today's fast-paced world", "game-changer", "game changer", "dive into", "deep dive", "unlock the secrets", "elevate your",
    "look no further", "without further ado", "it's no secret", "take it to the next level", "the ultimate guide",
    "you won't believe", "stay tuned", "link in bio below",
)  # fmt: skip
"""A short list of caption filler (the humanize lexicon's idea): each one is a warning, never an error."""


@dataclass
class Issue:
    code: str
    message: str
    severity: str = WARN


@dataclass
class CaptionCheck:
    network: str
    integration: str = ""
    name: str = ""
    unit: str = "characters"
    length: int = 0
    max: int = 0
    over: bool = False
    visible_text: str | None = None
    """What the feed shows before "… more"; None when the whole post shows."""
    cut: bool = False
    """Whether "… more" hides part of it."""
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def count(text: str, unit: str) -> int:
    """The length a network counts: characters, or graphemes (what a person sees as one: an emoji with a skin tone is one)."""
    if unit != "graphemes":
        return len(text)
    try:
        import regex

        return len(regex.findall(r"\X", text))
    except ImportError:
        return _graphemes(text)


def _graphemes(text: str) -> int:
    """Graphemes without the ``regex`` package: a character joins the one before it when it is a combining mark, a variation
    selector, a skin-tone modifier, a zero-width joiner or what follows one, or the second of a pair of flag letters. Close enough
    to count a caption; ``regex`` (there with the Bluesky plugin) is exact."""
    total, after_joiner, flag_half = 0, False, False
    for c in text:
        o = ord(c)
        joins = unicodedata.combining(c) or c in "\u200d\ufe0e\ufe0f" or 0x1F3FB <= o <= 0x1F3FF or after_joiner
        is_flag_letter = 0x1F1E6 <= o <= 0x1F1FF
        if is_flag_letter and flag_half:
            joins, flag_half = True, False
        elif is_flag_letter:
            flag_half = True
        else:
            flag_half = False
        after_joiner = c == "\u200d"
        total += 0 if joins else 1
    return total


def visible_window(text: str, visible: int | None) -> tuple[str | None, bool]:
    """What shows before "… more" (cut on a word boundary) and whether anything is hidden; (None, False) when all of it shows."""
    if not visible:
        return None, False
    first_lines = text.strip()
    if len(first_lines) <= visible:
        return first_lines, False
    head = first_lines[:visible]
    if " " in head[visible // 2 :]:
        head = head[: head.rfind(" ")]
    return head.rstrip(), True


def check(text: str, limits: dict, *, link: str | None = None, network: str = "", integration: str = "", name: str = "") -> CaptionCheck:
    """One network's verdict on a caption (``limits``: a plugin's ``post_limits`` read by ``post_limits_of``)."""
    text = text or ""
    unit = limits.get("unit", "characters")
    result = CaptionCheck(network=network, integration=integration, name=name, unit=unit, length=count(text, unit), max=int(limits["max"]))
    issues = result.issues
    if not text.strip():
        issues.append(Issue("empty", "There's no text to post.", ERROR))
        return result
    if result.length > result.max:
        result.over = True
        issues.append(Issue("too_long", f"{result.length} {unit} — the limit is {result.max}; {result.length - result.max} too many.", ERROR))
    result.visible_text, result.cut = visible_window(text, limits.get("visible"))
    if result.cut and not _first_sentence_fits(text, limits["visible"]):
        issues.append(Issue("hook_cut", f"The first sentence runs past what the feed shows ({limits['visible']} characters): put the point first."))
    opening = text.strip().lower()
    if opening[:1] in "#@":
        issues.append(Issue("opens_with_tag", "It opens with a hashtag or a mention: start with the point and put tags at the end."))
    elif any(opening == g or re.match(rf"{re.escape(g)}\b", opening) for g in GREETINGS):
        issues.append(Issue("opens_with_greeting", "It opens with a greeting: the first words are the only ones everyone sees."))
    if limits.get("links") == "not_clickable" and (_URL.search(text) or link):
        issues.append(
            Issue(
                "link_not_clickable",
                f"Links aren't clickable in {name or network or 'this network'}'s captions: say where to find it (\"link in bio\").",
            )
        )
    tags = len(_HASHTAG.findall(text))
    if limits.get("hashtags_max") and tags > limits["hashtags_max"]:
        issues.append(Issue("too_many_hashtags", f"{tags} hashtags — the limit is {limits['hashtags_max']}.", ERROR))
    stock = [p for p in STOCK_PHRASES if p in opening]
    if stock:
        issues.append(Issue("stock_phrase", f"Reads as filler: {', '.join(repr(p) for p in stock[:3])}. Say the specific thing instead."))
    return result


def _first_sentence_fits(text: str, visible: int) -> bool:
    end = _SENTENCE_END.search(text.strip())
    return end is not None and end.end() <= visible


def check_for_networks(session, group_id, text: str, *, link: str | None = None, integrations: list[str] | None = None) -> list[dict]:
    """The caption checked for each enabled integration that posts (offers ``social.post``) and declares ``post_limits`` — or only
    the named ones (slugs). A network that posts but declares no limits is listed with no verdict (``unknown``)."""
    from marvin_integration_sdk import post_limits_of

    from .social import SOCIAL_POST
    from .social_setup import social_networks

    wanted = {s.lower() for s in integrations or []}
    out = []
    for net in social_networks(session, group_id):
        if SOCIAL_POST not in net.capabilities or (wanted and net.row.slug.lower() not in wanted):
            continue
        limits = post_limits_of(net.provider)
        if limits is None:
            out.append({"network": net.row.provider, "integration": net.row.slug, "name": net.row.name, "unknown": True, "issues": []})
            continue
        out.append(check(text, limits, link=link, network=net.row.provider, integration=net.row.slug, name=net.row.name).to_dict())
    return out
