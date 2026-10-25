"""What a Social inbox item needs: its bucket (tasks/social-comment-buckets-plan.md).

Six fixed names, the same on every network (core decides; a plugin only hands over the item):

* ``keyword`` — it hit a published rule's keyword (the rule answers it);
* ``lead`` — describes a problem the business solves, asks price, availability or how to buy;
* ``question`` — a question others likely share;
* ``feedback`` — disagrees, complains, adds substance;
* ``support`` — praise, emoji, tags, thanks;
* ``noise`` — spam, pitches, bait, bots.

An item is sorted when it is first stored (``social_inbox.persist_items``), by what costs nothing: a rule's keyword, else
obvious support. The rest stay unsorted until AI sorting (opt-in, a later phase) or a person sorts them. A person's choice
(``SOURCE_PERSON``) always wins and is never overwritten.
"""

from __future__ import annotations

import re
import unicodedata

KEYWORD, LEAD, QUESTION, FEEDBACK, SUPPORT, NOISE = "keyword", "lead", "question", "feedback", "support", "noise"
BUCKETS = (KEYWORD, LEAD, QUESTION, FEEDBACK, SUPPORT, NOISE)
"""In the order a person works through them."""
SOURCE_RULE, SOURCE_HEURISTIC, SOURCE_AI, SOURCE_PERSON = "rule", "heuristic", "ai", "person"
SOURCES = (SOURCE_RULE, SOURCE_HEURISTIC, SOURCE_AI, SOURCE_PERSON)

SUPPORT_MAX_WORDS = 4
"""Longer than this, kind words usually carry something worth reading: left for AI or a person."""
SUPPORT_WORDS = frozenset(
    "thanks thank you thx ty love it this so much amazing awesome great nice cool wow beautiful gorgeous stunning lovely "
    "perfect yes yess yesss omg brilliant fantastic incredible fire cute sweet congrats congratulations well done "
    "good job the best".split()
)
"""Words that, with nothing else, are praise. Kept short on purpose: a miss stays unsorted, a wrong hit hides a real comment."""
_TAG = re.compile(r"[@#][\w.]+")
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def heuristic_bucket(text: str) -> str | None:
    """``support`` for text that is only emoji and tags (with any punctuation), or a few words of plain praise; else None."""
    rest = _TAG.sub(" ", text or "")
    words = [w.lower() for w in _WORD.findall(rest)]
    if not words:
        has_emoji = any(unicodedata.category(c).startswith("S") for c in rest)  # emoji are symbols; "..." or "?" alone is not praise
        return SUPPORT if has_emoji or _TAG.search(text or "") else None
    if len(words) <= SUPPORT_MAX_WORDS and all(w in SUPPORT_WORDS for w in words) and "?" not in rest:
        return SUPPORT
    return None


def bucket_for(item: dict, rules, names: set[str]) -> tuple[str, str] | None:
    """The bucket an item gets when it is first stored, and where it came from: ``keyword`` when a published rule's keyword hits
    (the same match the engine answers by), else obvious ``support``; None leaves it unsorted."""
    from .social_rules import match_item

    if rules and match_item(item, list(rules), names | {str(item.get("network") or "").lower()}) is not None:
        return KEYWORD, SOURCE_RULE
    if (bucket := heuristic_bucket(str(item.get("text") or ""))) is not None:
        return bucket, SOURCE_HEURISTIC
    return None
