"""Keyword rules for the social engagement engine — pure: no database, no HTTP, no provider.

Moved from the Instagram plugin's ``matching.py`` and kept as it behaved, now over the shared comment item
(``social.comments``: ``{id, kind, post_id, post_url, author: {id, handle, name}, text, created_at, url, network}``):

* a keyword is matched case-insensitively as a whole word — "price" hits "What's the price?" but not "priceless" — and
  a multi-word keyword ("how much") works; keywords may be a list or a comma-separated string, lowered and stripped;
* a rule needs at least one keyword and a reply, else it is unusable and ignored;
* one reply per comment: a comment that matches several rules takes the first — rules for that comment's post before the
  catch-all ones, then in the order the caller hands them over (Marvin hands them oldest first, so the rule written first
  wins);
* a comment is skipped when it was already answered, is older than ``max_age_days`` (default 7), or is the account's own.

Beyond Instagram's, a rule says which networks it covers (``networks``: empty is any; else integration slugs or network
names), how to answer (``reply_as``: private, public or both), whether to like the comment too (``also_like``) and which
kinds of item it answers (``kinds``, default "comment, reply": answers on your own posts). A ``mention`` — someone
tagging the account elsewhere — is answered only by a rule that lists it, so a keyword rule never replies to strangers
unasked. (Networks differ: Instagram yields comment and reply, Mastodon reply and mention — never "comment".)

A rule's source is either the shared ``social-auto-reply`` entry or, for Instagram's old ``ig-auto-reply`` entry (``post_id``,
``keywords``, ``reply``), the same rule read as one for network "instagram" that replies privately — see ``rule_from_entry``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

ALL_POSTS = "*"
DEFAULT_MAX_AGE_DAYS = 7

RULE_TYPE = "social-auto-reply"
LOG_TYPE = "social-reply-log"
IG_RULE_TYPE = "ig-auto-reply"
IG_LOG_TYPE = "ig-reply-log"
IG_NETWORK = "instagram"

PRIVATE, PUBLIC, BOTH = "private", "public", "both"
REPLY_MODES = (PRIVATE, PUBLIC, BOTH)
KIND_COMMENT, KIND_REPLY, KIND_MENTION = "comment", "reply", "mention"
ITEM_KINDS = (KIND_COMMENT, KIND_REPLY, KIND_MENTION)
DEFAULT_KINDS = frozenset({KIND_COMMENT, KIND_REPLY})

REASON_ALREADY_REPLIED = "already_replied"
REASON_TOO_OLD = "too_old"
REASON_OWN_COMMENT = "own_comment"
REASON_NO_MATCH = "no_match"


@dataclass(frozen=True)
class SocialRule:
    """One keyword rule, normalised from an entry."""

    id: str
    """The rule entry's slug — what the log's ``rule`` names."""
    keywords: tuple[str, ...]
    reply: str
    networks: frozenset[str] = frozenset()
    """Lowercased integration slugs / network names; empty is any network."""
    post: str = ""
    """A post id or URL; empty is any post."""
    reply_as: str = PRIVATE
    also_like: bool = False
    kinds: frozenset[str] = DEFAULT_KINDS
    """Which item kinds the rule answers (comment, reply, mention)."""
    published: bool = True
    """False for a draft: never fires. The engine only loads published entries, and re-checks this before it sends."""
    legacy: bool = False
    """Read from an Instagram ``ig-auto-reply`` entry."""
    order: int = field(default=0, compare=False)


def _words(value) -> list[str]:
    """A list of strings, or a comma-separated string, as cleaned non-empty strings."""
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else value if isinstance(value, list | tuple | set | frozenset) else []
    return [str(i).strip() for i in items if str(i).strip()]


def rule_from_data(data: dict, *, id: str, published: bool = True, legacy: bool = False, order: int = 0) -> SocialRule | None:
    """A rule from an entry's data (``social-auto-reply`` fields, or Instagram's ``ig-auto-reply``: ``post_id`` for ``post``,
    and always network instagram, private). None when it has no usable keywords or reply."""
    if not isinstance(data, dict):
        return None
    keywords = tuple(k.lower() for k in _words(data.get("keywords")))
    reply = str(data.get("reply") or "").strip()
    if not keywords or not reply:
        return None
    post = str(data.get("post_id" if legacy else "post") or "").strip()
    if post == ALL_POSTS:
        post = ""
    if legacy:
        networks, reply_as, also_like, kinds = frozenset({IG_NETWORK}), PRIVATE, False, DEFAULT_KINDS
    else:
        networks = frozenset(n.lower().lstrip("@") for n in _words(data.get("networks")))
        mode = str(data.get("reply_as") or PRIVATE).strip().lower()
        reply_as = mode if mode in REPLY_MODES else PRIVATE
        also_like = data.get("also_like") in (True, "true", "True", 1, "1", "yes")
        kinds = frozenset(k.lower() for k in _words(data.get("kinds")) if k.lower() in ITEM_KINDS) or DEFAULT_KINDS
    return SocialRule(
        id=id,
        keywords=keywords,
        reply=reply,
        networks=networks,
        post=post,
        reply_as=reply_as,
        also_like=also_like,
        kinds=kinds,
        published=published,
        legacy=legacy,
        order=order,
    )


_STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be because been before being but by can could did do does doing for from
    get got had has have he her here hers him his how i if in into is it its just me more most my no nor not of on once only or our
    out over own she should so some such than that the their them then there these they this those to too under until up us very was
    we were what when where which while who whom why will with would you your yours""".split()
)
_NOISE = re.compile(r"https?://\S+|[@#]\w+")
_WORD = re.compile(r"[^\W\d_][\w'’-]*")


def suggest_keywords(text: str, limit: int = 3) -> list[str]:
    """A few keywords for a rule that would answer comments like ``text``: its distinctive words (no links, @mentions, hashtags,
    stop words or words under three letters), lowercased, first mentioned first. "What is the price?" gives ["price"]. A
    suggestion to edit, not a classification."""
    found: list[str] = []
    for word in _WORD.findall(_NOISE.sub(" ", text or "").lower()):
        word = word.strip("'’-")
        if len(word) >= 3 and word not in _STOPWORDS and word not in found:
            found.append(word)
        if len(found) == limit:
            break
    return found


def keyword_hit(text: str, keywords) -> str | None:
    """The first keyword found as a whole word (case-insensitive) in ``text``; multi-word keywords work."""
    for kw in keywords:
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text or "", re.IGNORECASE):
            return kw
    return None


def _same_post(rule_post: str, item: dict) -> bool:
    """Whether a rule's post (an id or a URL) names the item's post."""

    def clean(value) -> str:
        return str(value or "").strip().rstrip("/")

    want = clean(rule_post)
    return bool(want) and want in (clean(item.get("post_id")), clean(item.get("post_url")))


def covers(rule: SocialRule, item: dict, names: set[str]) -> bool:
    """Whether the rule applies to this item's network (``names``: the integration's slug, its provider and the item's
    ``network``, lowercased), kind and post."""
    if rule.networks and not (rule.networks & names):
        return False
    if str(item.get("kind") or KIND_COMMENT).lower() not in rule.kinds:
        return False
    return not rule.post or _same_post(rule.post, item)


def match_item(item: dict, rules: list[SocialRule], names: set[str]) -> tuple[SocialRule, str] | None:
    """The rule (and the keyword that hit) that answers this item, or None. Rules for the item's own post go before the
    catch-all ones; within each, the caller's order — one reply per comment, so the first hit wins."""
    applicable = [r for r in rules if r.published and covers(r, item, names)]
    for rule in [r for r in applicable if r.post] + [r for r in applicable if not r.post]:
        if kw := keyword_hit(item.get("text") or "", rule.keywords):
            return rule, kw
    return None


def parse_time(value) -> datetime | None:
    """An item's ``created_at`` (ISO 8601, UTC) as an aware datetime; None when absent or unreadable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def too_old(item: dict, now: datetime, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> bool:
    """Older than the reply window (an item with no readable time counts as fresh, as it did on Instagram)."""
    created = parse_time(item.get("created_at"))
    return created is not None and created < now - timedelta(days=max_age_days)


# What an integration's own config calls its account: where a comment's author is compared to find the account's own
# comments. Handles are compared case-insensitively without a leading "@"; ids as given.
OWN_HANDLE_KEYS = ("own_username", "own_handle", "handle", "username")
OWN_ID_KEYS = ("own_user_id", "ig_user_id", "page_id", "did", "user_id", "account_id")


def own_identities(config: dict | None) -> tuple[set[str], set[str]]:
    """(handles, ids) of the account an integration is connected as, from its config."""
    config = config or {}
    handles = {str(config[k]).strip().lower().lstrip("@") for k in OWN_HANDLE_KEYS if config.get(k)}
    ids = {str(config[k]).strip() for k in OWN_ID_KEYS if config.get(k)}
    return handles, ids


def is_own(item: dict, handles: set[str], ids: set[str]) -> bool:
    author = item.get("author") or {}
    handle = str(author.get("handle") or "").strip().lower().lstrip("@")
    return bool((handle and handle in handles) or (author.get("id") and str(author["id"]).strip() in ids))
