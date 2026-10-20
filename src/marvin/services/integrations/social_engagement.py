"""The social engagement engine: answers comments on every connected network under the workspace's published rules.

One run (the ``social_engagement`` scheduled task, every 5 minutes) does this for each enabled integration whose plugin offers
``social.comments`` and ``social.reply``:

1. read the items since the integration's stored cursor (``IntegrationModel.state["social"]``; the cursor is the plugin's
   own opaque string, passed back as ``since``);
2. drop the account's own comments, items older than 7 days, and comments already answered (the ``social-reply-log`` — and
   Instagram's old ``ig-reply-log`` — never answer a comment twice);
3. match the published rules (``social_rules``): ``social-auto-reply`` entries, and Instagram's ``ig-auto-reply`` entries read as
   rules for network instagram;
4. reply in the rule's mode (private, public or both), like the comment too when the rule says so and the network can,
   and write a ``social-reply-log`` entry.

**Rehearsal** is the default: the plugin is called with ``dry_run: true`` (it sends nothing), the log entry says
``rehearsal: true``, and the rehearsal read cursor moves instead of the live one — so switching rehearsal off still answers
what is within the window, and a rehearsal entry never counts as "answered". At most ``max_replies`` (20) per run; what
the cap holds back, and what failed for a reason worth retrying, waits in ``state["social"]["pending"]`` for the next run
(live only; at most 3 attempts).

**The narrow approval path.** A workflow's ``social.reply`` needs an Approval step; a published rule *is* the approval of
its text, so the engine sends without one — through exactly one door, ``_Network.call``:

* only ``social.comments``, ``social.reply`` and ``social.like`` can pass through it (``ENGINE_CAPABILITIES``): message,
  repost and delete are unreachable from here;
* a ``social.reply`` is routed as approved only when ``_rule_approves`` says so: the call carries a ``SocialRule`` that is
  published (checked against the entry again at the moment of sending) and the text is that rule's reply, verbatim — never
  a templated or computed text;
* nothing outside this module can ask for it: a workflow step, the API and the plugins never reach ``_Network``.

A plugin refusal (IntegrationError code ``unsupported``, or ``refused`` for bad arguments) skips that comment: no retry, no
log entry, noted in the run summary. Any other failure is that network's failure for the run: the other networks go on.
A plugin that rejects its cursor (``invalid_cursor``) has it dropped and is read again without one.

Instagram: while the plugin's own ``auto_reply`` scheduled task is enabled for an integration the engine leaves that
integration alone (two senders would answer twice); switch the plugin's task off to hand it over.

**Announcing** (``announce``, on by default): the same poll also sends one ``social_comment_received`` event per new
comment, reply or mention, so a workflow can start on it. It is a second job of the same run, with its own state, so replying
and announcing never change one another:

* its own cursor, ``state["social"]["events_cursor"]`` — rehearsal and live reply cursors move independently of it, and it
  moves in rehearsal and live alike (announcing is not sending);
* ``events_started_at`` marks the first poll, which announces nothing (no backlog): it only records the newest cursor and
  the ids it saw. After that an item is announced only when it was written after that moment and is within the 7-day
  window, so a cursor that lags, is dropped, or restarts at the newest items never replays the past;
* ``events_seen`` (the last 500 ids) is claimed *before* each event is sent, so a crash or a re-read can lose at most the one
  event in flight and never sends one twice;
* the account's own items are never announced (the same check as replying), which is what stops a workflow's public reply
  from starting the workflow again;
* it does not need a rule, a log type, or the integration's ``social.reply``: ``social.comments`` is enough. Instagram's
  plugin-task skip applies to replying only; announcing still reads the network (one read serves both when the cursors agree).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from marvin.core.root_logger import get_logger

from .social import SOCIAL_COMMENTS, SOCIAL_LIKE, SOCIAL_REPLY
from .social_rules import (
    BOTH,
    DEFAULT_MAX_AGE_DAYS,
    IG_LOG_TYPE,
    IG_NETWORK,
    IG_RULE_TYPE,
    ITEM_KINDS,
    LOG_TYPE,
    PRIVATE,
    PUBLIC,
    REASON_ALREADY_REPLIED,
    REASON_NO_MATCH,
    REASON_OWN_COMMENT,
    REASON_TOO_OLD,
    RULE_TYPE,
    SocialRule,
    is_own,
    match_item,
    own_identities,
    parse_time,
    rule_from_data,
    too_old,
)

logger = get_logger(__name__)

ENGINE_CAPABILITIES = frozenset({SOCIAL_COMMENTS, SOCIAL_REPLY, SOCIAL_LIKE})
"""The only capabilities the engine calls. Message, repost and delete have no way in."""
DEFAULT_MAX_REPLIES = 20
DEFAULT_LIMIT = 50
MAX_ATTEMPTS = 3
MAX_PENDING = 200
STATE_KEY = "social"
SOURCE_TAG = "social_engagement"
CODES_NO_RETRY = frozenset({"unsupported", "refused"})
"""Plugin refusals that skip a comment for good: the network can't do it, or the arguments are wrong."""
INVALID_CURSOR = "invalid_cursor"
PLUGIN_TASK_ACTION = "auto_reply"
REASON_PLUGIN_TASK = "plugin_task_enabled"
IG_REPLY_SLUG_PREFIX = "ig-reply-"
MAX_NOTES = 5  # failures / refusals a run summary names
EVENT_SOURCE = "social_engagement"
MAX_SEEN = 500
"""Ids the events pass remembers having announced (or passed over): what a re-read of the same items is checked against."""
REASON_EVENT_OWN = "event_own"
REASON_EVENT_OLD = "event_too_old"
REASON_EVENT_BEFORE = "event_before_start"


def _truthy(value, *, default: bool) -> bool:
    if value is None:
        return default
    return value is not False and str(value).lower() not in ("false", "0", "no", "off")


@dataclass(frozen=True)
class Settings:
    """What a run does, from the task's ``task_config``. ``rehearsal`` defaults to ON: nothing is sent until it is
    explicitly ``false``."""

    rehearsal: bool = True
    max_replies: int = DEFAULT_MAX_REPLIES
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    limit: int = DEFAULT_LIMIT
    announce: bool = True
    """Send ``social_comment_received`` for each new item (on unless the task says ``announce: false``)."""

    @classmethod
    def from_config(cls, config: dict | None) -> Settings:
        config = config or {}

        def number(key: str, default: int) -> int:
            try:
                return max(1, int(config.get(key) or default))
            except (TypeError, ValueError):
                return default

        return cls(
            rehearsal=config.get("rehearsal") is not False and str(config.get("rehearsal")).lower() not in ("false", "0", "no", "off"),
            max_replies=number("max_replies", DEFAULT_MAX_REPLIES),
            max_age_days=number("max_age_days", DEFAULT_MAX_AGE_DAYS),
            limit=number("limit", DEFAULT_LIMIT),
            announce=_truthy(config.get("announce"), default=True),
        )


@dataclass
class Report:
    """What a run did."""

    rehearsal: bool = True
    integrations: list[str] = field(default_factory=list)
    checked: int = 0
    matched: int = 0
    sent: int = 0
    """Replies sent (live) or logged as would-send (rehearsal)."""
    liked: int = 0
    announced: int = 0
    """``social_comment_received`` events sent."""
    skipped: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)
    """Failures and refusals, one line each."""
    failed: int = 0
    message: str | None = None
    """Why the run did nothing at all (no log type, no rules…)."""

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def worth_logging(self) -> bool:
        return bool(self.matched or self.failed or self.message or self.announced)

    def summary(self) -> str:
        if self.message:
            return f"Social engagement: {self.message}"
        head = f"Social engagement{' (rehearsal)' if self.rehearsal else ''}: {len(self.integrations)} network(s)"
        parts = [f"checked {self.checked}", f"matched {self.matched}", f"{'would reply' if self.rehearsal else 'replied'} {self.sent}"]
        if self.liked:
            parts.append(f"liked {self.liked}")
        if self.announced:
            parts.append(f"announced {self.announced}")
        if self.skipped:
            parts.append("skipped " + ", ".join(f"{k} {v}" for k, v in sorted(self.skipped.items())))
        shown = "; ".join(self.notes[:MAX_NOTES]) + (f"; and {len(self.notes) - MAX_NOTES} more" if len(self.notes) > MAX_NOTES else "")
        return f"{head}, {', '.join(parts)}" + (f" — {shown}" if shown else "")


class EngineCallError(Exception):
    """A plugin call the engine made failed: ``code`` is the plugin's own (``unsupported``, ``invalid_cursor``…) or "unknown"."""

    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.code = code


# ── the one door to a plugin ──────────────────────────────────────────────────────────────────────────────────────


def _rule_approves(rule, args: dict) -> bool:
    """Whether a published rule approves this ``social.reply``: the rule is a SocialRule that is published and the text is its
    reply exactly. This is the only thing that makes the engine's reply count as approved."""
    return (
        isinstance(rule, SocialRule)
        and rule.published
        and bool(rule.reply.strip())
        and args.get("text") == rule.reply
        and bool(args.get("comment_id"))
    )


class _Network:
    """One integration as the engine calls it. ``call`` is the only way the engine reaches a plugin action."""

    def __init__(self, session, group_id, row, provider):
        self.session, self.group_id, self.row, self.provider = session, group_id, row, provider
        self._ctx = None
        self._secret = None

    def has(self, capability: str) -> bool:
        """Whether the plugin declares an action for it (whatever its approval flag: the engine's own rules decide)."""
        from .alert_routing import capability_action

        return capability_action(self.provider, capability, {}, approved=True) is not None

    def call(self, capability: str, args: dict, rule: SocialRule | None = None) -> dict:
        if capability not in ENGINE_CAPABILITIES:
            raise EngineCallError(f"the engagement engine can't {capability}", "refused")
        from .alert_routing import capability_action

        approved = capability == SOCIAL_REPLY and _rule_approves(rule, args)
        found = capability_action(self.provider, capability, args, approved=approved)
        if found is None:
            raise EngineCallError(f"'{self.row.slug}' has no way to {capability} that a published rule approves", "unsupported")
        return self._run(*found)

    def _run(self, key: str, args: dict) -> dict:
        from marvin.services.integrations import IntegrationContext, build_http, errors
        from marvin.services.secrets.resolver import resolve_secret

        if self._ctx is None:
            self._secret = resolve_secret(self.row.secret_ref, self.group_id) if self.row.secret_ref else None
            self._ctx = IntegrationContext(config=self.row.config or {}, secret=self._secret, logger=logger, http=build_http())
        try:
            result = self.provider.run_action(key, args, self._ctx)
        except Exception as e:  # noqa: BLE001 — every plugin failure is the engine's to classify
            code = errors.error_code(e)
            detail = errors.redact(str(e) or type(e).__name__, errors.secret_values(self._secret))
            if code not in CODES_NO_RETRY and code != INVALID_CURSOR:
                errors.connection_failed(
                    self.group_id, self.row.id, self.provider, key, e, source="scheduled_task", session=self.session, secrets=(self._secret,)
                )
            raise EngineCallError(f"{self.row.slug}.{key}: {detail}", code) from e
        errors.connection_succeeded(self.group_id, self.row.id, session=self.session)
        return result if isinstance(result, dict) else {}


# ── rules and the log ─────────────────────────────────────────────────────────────────────────────────────────────


def _entries(session, group_id, type_slugs, *, published: bool):
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    q = (
        session.query(Entries, EntryTypes.slug)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.group_id == group_id, EntryTypes.slug.in_(list(type_slugs)))
    )
    if published:
        q = q.filter(Entries.status == "published")
    return q.order_by(Entries.created_at.asc(), Entries.id.asc())


def load_rules(session, group_id) -> list[SocialRule]:
    """The published rules, oldest first: ``social-auto-reply`` entries and Instagram's ``ig-auto-reply`` entries (read as
    shared rules for network instagram). Drafts never fire."""
    rules = []
    for entry, type_slug in _entries(session, group_id, (RULE_TYPE, IG_RULE_TYPE), published=True):
        rule = rule_from_data(entry.data_json or {}, id=entry.slug, legacy=type_slug == IG_RULE_TYPE, order=len(rules))
        if rule is not None:
            rules.append(rule)
    return rules


def log_slug(integration: str, comment_id: str, *, rehearsal: bool) -> str:
    """The log entry's slug — also the dedupe key: one per (integration, comment, live or rehearsal)."""
    digest = hashlib.sha1(f"{integration}\0{comment_id}".encode(), usedforsecurity=False).hexdigest()[:20]
    return f"social-{'rehearsal' if rehearsal else 'reply'}-{digest}"


def _answered(session, group_id, row, ids: list[str], rehearsal: bool, legacy: set[str] | None) -> set[str]:
    """Which of these comment ids are already answered: a live ``social-reply-log`` entry (in rehearsal, a rehearsal entry
    too — so it isn't logged every run), or, for Instagram, an ``ig-reply-log`` entry."""
    from marvin.db.models.platform.entries import Entries

    if not ids:
        return set()
    by_slug = {log_slug(row.slug, i, rehearsal=False): i for i in ids}
    if rehearsal:
        by_slug.update({log_slug(row.slug, i, rehearsal=True): i for i in ids})
    found = {r[0] for r in session.query(Entries.slug).filter(Entries.group_id == group_id, Entries.slug.in_(list(by_slug)))}
    done = {by_slug[s] for s in found}
    if legacy:
        done |= {i for i in ids if i in legacy}
    return done


def _legacy_answered(session, group_id) -> set[str]:
    """Every comment id Instagram's own task has already answered (``ig-reply-log`` entries' ``comment_id``)."""
    return {
        str(e.data_json["comment_id"])
        for e, _ in _entries(session, group_id, (IG_LOG_TYPE,), published=False)
        if (e.data_json or {}).get("comment_id")
    }


def _log_type_id(session, group_id):
    from marvin.db.models.platform.entry_types import EntryTypes

    row = session.query(EntryTypes.id).filter_by(group_id=group_id, slug=LOG_TYPE).first()
    return row[0] if row else None


def _write_log(session, group_id, type_id, row, item: dict, rule: SocialRule, keyword: str, *, mode: str, rehearsal: bool, outcome: dict) -> None:
    """One ``social-reply-log`` entry (committed at once: it is the dedupe)."""
    from marvin.services.entries.entry_service import EntryService

    author = item.get("author") or {}
    who = author.get("handle") or author.get("name") or author.get("id") or "someone"
    data = {
        "network": item.get("network") or row.provider,
        "integration": row.slug,
        "comment_id": str(item["id"]),
        "rule": rule.id,
        "mode": mode,
        "rehearsal": rehearsal,
        "reply_id": outcome.get("reply_id"),
        "when": datetime.now(UTC).isoformat(),
        "post_id": item.get("post_id"),
        "author": who,
        "keyword": keyword,
        "comment": item.get("text"),
        "reply": rule.reply,
        "url": outcome.get("url") or item.get("url"),
        "liked": outcome.get("liked", False),
        "public_reply_id": outcome.get("public_reply_id"),
        "error": outcome.get("error"),
    }
    data = {k: v for k, v in data.items() if v is not None}
    slug = log_slug(row.slug, str(item["id"]), rehearsal=rehearsal)
    title = f"{'(rehearsal) ' if rehearsal else ''}{keyword} → {who} on {data['network']}"
    EntryService(session, group_id, integration_id=SOURCE_TAG).create(
        {"entry_type_id": type_id, "title": title, "slug": slug, "status": "published", "data_json": data}
    )
    session.commit()


# ── one integration ───────────────────────────────────────────────────────────────────────────────────────────────


def _plugin_task_enabled(session, group_id, slug: str) -> bool:
    """Whether an enabled scheduled task of the integration's own ``auto_reply`` action (Instagram's plugin task) is running for it."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    tasks = session.query(ScheduledTaskModel).filter_by(group_id=group_id, task_type="run_integration_action", enabled=True)
    return any((t.task_config or {}).get("integration") == slug and (t.task_config or {}).get("action") == PLUGIN_TASK_ACTION for t in tasks)


def _state(row) -> dict:
    state = (row.state or {}).get(STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_state(session, row, state: dict) -> None:
    row.state = {**(row.state or {}), STATE_KEY: state}
    session.commit()


def _read(net: _Network, cursor: str | None, settings: Settings, kinds: list[str]) -> tuple[list[dict], str | None, bool]:
    """(items, new cursor, whether a bad cursor was dropped). A plugin that rejects the cursor is read again without one: it
    returns the newest ``limit`` items, and the window and the log stop double replies."""
    args = {"limit": settings.limit, "kinds": kinds}
    dropped = False
    try:
        out = net.call(SOCIAL_COMMENTS, {**args, **({"since": cursor} if cursor else {})})
    except EngineCallError as e:
        if e.code != INVALID_CURSOR or not cursor:
            raise
        dropped = True
        out = net.call(SOCIAL_COMMENTS, args)
    items = [i for i in (out.get("items") or []) if isinstance(i, dict) and i.get("id") not in (None, "")]
    return items, (str(out["cursor"]) if out.get("cursor") else None), dropped


def _needed_kinds(rules: list[SocialRule]) -> list[str]:
    from .social_rules import ITEM_KINDS

    wanted = set().union(*(r.kinds for r in rules)) if rules else set()
    return [k for k in ITEM_KINDS if k in wanted]


@dataclass
class _Run:
    """What one engine run shares across integrations."""

    session: object
    group_id: object
    settings: Settings
    rules: list[SocialRule]
    report: Report
    now: datetime
    log_type_id: object
    event_bus: object = None
    replying: bool = True
    """Whether this run answers comments: there is a log type and at least one published rule."""
    legacy: set[str] | None = None
    budget: int = 0

    def legacy_answered(self) -> set[str]:
        if self.legacy is None:
            self.legacy = _legacy_answered(self.session, self.group_id)
        return self.legacy


def _read_once(net: _Network, cursor: str | None, settings: Settings, kinds: list[str], cache: dict) -> tuple[list[dict], str | None, bool]:
    """``_read``, remembered for the rest of this integration's pass: the replying and announcing jobs read the network
    once when they stand at the same cursor and ask for the same kinds."""
    key = (cursor, tuple(kinds))
    if key not in cache:
        cache[key] = _read(net, cursor, settings, kinds)
    return cache[key]


def _engage(run: _Run, row, provider) -> None:
    """One integration's pass: announce its new items (when asked to), then answer under the rules (when there are any and the
    plugin can reply)."""
    report, settings, session = run.report, run.settings, run.session
    net = _Network(session, run.group_id, row, provider)
    state = _state(row)
    cache: dict = {}
    replying = run.replying and net.has(SOCIAL_REPLY)
    if replying and _plugin_task_enabled(session, run.group_id, row.slug):
        report.skipped[REASON_PLUGIN_TASK] += 1
        report.note(f"{row.slug}: left to the plugin's own auto-reply task (switch it off to use the shared engine)")
        replying = False
    if not replying and not settings.announce:
        return
    report.integrations.append(row.slug)
    if settings.announce:
        _announce(run, net, row, state, cache, count=not replying)
    if replying:
        _reply(run, net, row, state, cache)


def _reply(run: _Run, net: _Network, row, state: dict, cache: dict) -> None:
    report, settings, session = run.report, run.settings, run.session
    cursor_key = "rehearsal_cursor" if settings.rehearsal else "cursor"
    kinds = list(ITEM_KINDS) if settings.announce else _needed_kinds(run.rules)  # the rules' own kinds filter what matches
    items, cursor, dropped = _read_once(net, state.get(cursor_key), settings, kinds, cache)
    pending = [] if settings.rehearsal else [p for p in state.get("pending") or [] if isinstance(p, dict) and isinstance(p.get("item"), dict)]
    attempts = {str(p["item"]["id"]): int(p.get("attempts") or 0) for p in pending}
    fresh = {str(i["id"]) for i in items}
    candidates = [p["item"] for p in pending if str(p["item"]["id"]) not in fresh] + items
    report.checked += len(items)

    handles, ids = own_identities(row.config)
    names = {row.slug.lower(), row.provider.lower()}
    answered = _answered(
        session,
        run.group_id,
        row,
        [str(i["id"]) for i in candidates],
        settings.rehearsal,
        run.legacy_answered() if row.provider == IG_NETWORK else None,
    )
    keep: list[dict] = []
    for item in candidates:
        cid = str(item["id"])
        if cid in answered:
            report.skipped[REASON_ALREADY_REPLIED] += 1
        elif is_own(item, handles, ids):
            report.skipped[REASON_OWN_COMMENT] += 1
        elif too_old(item, run.now, settings.max_age_days):
            report.skipped[REASON_TOO_OLD] += 1
        elif (hit := match_item(item, run.rules, names | {str(item.get("network") or "").lower()})) is None:
            report.skipped[REASON_NO_MATCH] += 1
        else:
            report.matched += 1
            if run.budget <= 0:
                keep.append({"item": item, "attempts": attempts.get(cid, 0)})  # the cap held it back: next run
                continue
            run.budget -= 1
            if _answer(run, net, row, item, *hit):
                tries = attempts.get(cid, 0) + 1
                if tries < MAX_ATTEMPTS:
                    keep.append({"item": item, "attempts": tries})
                else:
                    report.note(f"{row.slug}: gave up on comment {cid} after {tries} attempts")
    if not settings.rehearsal:
        state["pending"] = keep[-MAX_PENDING:]
    if cursor or dropped:
        state[cursor_key] = cursor
    state["polled_at"] = run.now.isoformat()
    _save_state(session, row, state)


# ── announcing: one event per new item ────────────────────────────────────────────────────────────────────────────


def _announce(run: _Run, net: _Network, row, state: dict, cache: dict, *, count: bool) -> None:
    """Send ``social_comment_received`` for each item the integration's events cursor hasn't passed (see the module docstring)."""
    report, settings, session = run.report, run.settings, run.session
    items, cursor, dropped = _read_once(net, state.get("events_cursor"), settings, list(ITEM_KINDS), cache)
    if count:
        report.checked += len(items)
    seen = [str(i) for i in state.get("events_seen") or []]
    started = parse_time(state.get("events_started_at"))
    if started is None:  # the first poll: what is already there is the backlog, not news
        state["events_started_at"] = run.now.isoformat()
        state["events_seen"] = (seen + [str(i["id"]) for i in items])[-MAX_SEEN:]
        if cursor:
            state["events_cursor"] = cursor
        _save_state(session, row, state)
        return
    known = set(seen)
    handles, ids = own_identities(row.config)
    for item in items:  # oldest first
        cid = str(item["id"])
        if cid in known:
            continue
        known.add(cid)
        seen.append(cid)
        created = parse_time(item.get("created_at"))
        if is_own(item, handles, ids):
            report.skipped[REASON_EVENT_OWN] += 1
        elif created is not None and created < started:
            report.skipped[REASON_EVENT_BEFORE] += 1
        elif too_old(item, run.now, settings.max_age_days):
            report.skipped[REASON_EVENT_OLD] += 1
        else:
            state["events_seen"] = seen[-MAX_SEEN:]
            _save_state(session, row, state)  # claimed before it is sent: never twice
            _send_event(run, row, item)
    state["events_seen"] = seen[-MAX_SEEN:]
    if cursor or dropped:
        state["events_cursor"] = cursor
    _save_state(session, row, state)


def _text(value) -> str | None:
    return None if value in (None, "") else str(value)


def _send_event(run: _Run, row, item: dict) -> None:
    """Dispatch one ``social_comment_received``. A failure is this item's alone: it is noted and the run goes on."""
    from marvin.services.event_bus_service.event_types import EventSocialAuthor, EventSocialCommentData, EventTypes

    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    try:
        data = EventSocialCommentData(
            id=str(item["id"]),
            kind=str(item.get("kind") or "comment"),
            post_id=_text(item.get("post_id")),
            post_url=_text(item.get("post_url")),
            author=EventSocialAuthor(id=_text(author.get("id")), handle=_text(author.get("handle")), name=_text(author.get("name"))),
            text=str(item.get("text") or ""),
            created_at=_text(item.get("created_at")),
            url=_text(item.get("url")),
            network=str(item.get("network") or row.provider),
            integration=row.slug,
            integration_id=row.id,
        )
        who = data.author.handle or data.author.name or "someone"
        run.event_bus.dispatch(
            integration_id=EVENT_SOURCE,
            group_id=run.group_id,
            event_type=EventTypes.social_comment_received,
            document_data=data,
            message=f"New {data.kind} from {who} on {data.network}",
            entity_id=row.id,
            entity_type="integration",
        )
    except Exception as e:  # noqa: BLE001 — one item's event failing never stops the others, or the replies
        run.session.rollback()
        run.report.failed += 1
        run.report.note(f"{row.slug}: could not announce comment {item.get('id')}: {e}")
        logger.warning("social engagement: announcing %s on %s failed: %s", item.get("id"), row.slug, e)
        return
    run.report.announced += 1


def _answer(run: _Run, net: _Network, row, item: dict, rule: SocialRule, keyword: str) -> bool:
    """Reply to one matched item in the rule's mode. True when it should be retried next run."""
    report, rehearsal = run.report, run.settings.rehearsal
    if not rehearsal and not _still_published(run.session, run.group_id, rule):
        report.note(f"{row.slug}: rule '{rule.id}' is no longer published; comment {item['id']} left unanswered")
        return False
    modes = {PRIVATE: [True], PUBLIC: [False], BOTH: [True, False]}[rule.reply_as]
    done: dict[bool, dict] = {}
    errors: list[tuple[bool, EngineCallError]] = []
    for private in modes:
        args = {"comment_id": item["id"], "text": rule.reply, "private": private, "dry_run": rehearsal}
        try:
            out = net.call(SOCIAL_REPLY, args, rule)
        except EngineCallError as e:
            errors.append((private, e))
            continue
        if not rehearsal and out.get("replied") is False:
            errors.append((private, EngineCallError(f"{row.slug}: the network did not send the reply")))
            continue
        done[private] = out
    if not done:
        return _failed(report, row, item, errors, rehearsal)
    outcome = _outcome(done, errors, row, report)
    mode = BOTH if len(done) == 2 else PRIVATE if True in done else PUBLIC
    if rule.also_like and net.has(SOCIAL_LIKE):
        _like(net, row, item, outcome, rehearsal, report)
    _write_log(run.session, run.group_id, run.log_type_id, row, item, rule, keyword, mode=mode, rehearsal=rehearsal, outcome=outcome)
    report.sent += 1
    return False


def _outcome(done: dict[bool, dict], errors, row, report: Report) -> dict:
    first = done.get(True) or done[False]
    outcome = {"reply_id": first.get("reply_id"), "url": first.get("url")}
    if True in done and False in done:
        outcome["public_reply_id"] = done[False].get("reply_id")
        outcome["url"] = done[False].get("url") or outcome["url"]
    for _, e in errors:  # one half of "both" worked: logged as answered, the other half's reason kept
        outcome["error"] = str(e)
        report.note(str(e))
    return outcome


def _like(net: _Network, row, item: dict, outcome: dict, rehearsal: bool, report: Report) -> None:
    """Like the comment as part of the rule. A rehearsal doesn't like (there is no dry run for it): it only says it would."""
    if rehearsal:
        outcome["would_like"] = True
        return
    try:
        out = net.call(SOCIAL_LIKE, {"comment_id": item["id"]})
    except EngineCallError as e:
        report.note(f"{e} (the reply was sent)")
        return
    outcome["liked"] = bool(out.get("liked", True))
    report.liked += int(outcome["liked"])


def _failed(report: Report, row, item: dict, errors: list[tuple[bool, EngineCallError]], rehearsal: bool) -> bool:
    """Count and name a comment that couldn't be answered. A refusal skips it for good (nothing is logged); other failures are
    this network's failure, retried next run (live) up to MAX_ATTEMPTS."""
    if all(e.code in CODES_NO_RETRY for _, e in errors):
        report.skipped[errors[0][1].code] += 1
        report.note(f"{row.slug}: comment {item['id']} skipped — {errors[0][1]}")
        return False
    report.failed += 1
    report.note(str(next(e for _, e in errors if e.code not in CODES_NO_RETRY)))
    return not rehearsal


def _still_published(session, group_id, rule: SocialRule) -> bool:
    """The rule's entry is still published right now (the last check before anything is sent)."""
    from marvin.db.models.platform.entries import Entries

    status = session.query(Entries.status).filter_by(group_id=group_id, slug=rule.id).scalar()
    return status == "published"


# ── a run ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def run_engagement(session, group_id, settings: Settings | None = None, *, now: datetime | None = None, event_bus=None) -> Report:
    """One engine run for a workspace (see the module docstring). One integration failing never stops the others.

    The poll runs when there is something to do with it: published rules to answer under, or ``settings.announce`` (workflows
    waiting for ``social_comment_received``). With neither it reads nothing, so no cursor moves past comments a later rule would
    answer. ``event_bus`` carries the announcements (the scheduler's own; a plain bus when none is given)."""
    settings = settings or Settings()
    report = Report(rehearsal=settings.rehearsal)
    type_id = _log_type_id(session, group_id)
    rules = load_rules(session, group_id) if type_id is not None else []
    if type_id is None and not settings.announce:
        report.message = f"the '{LOG_TYPE}' entry type is missing — apply the Social engagement set (Settings → Integrations)"
        return report
    if type_id is None:
        report.note(f"replies are off: the '{LOG_TYPE}' entry type is missing — apply the Social engagement set (Settings → Integrations)")
    if not rules and not settings.announce:
        return report  # nothing to answer with: read nothing, so no cursor moves past comments a later rule would answer
    if event_bus is None and settings.announce:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)
    run = _Run(
        session,
        group_id,
        settings,
        rules,
        report,
        now or datetime.now(UTC),
        type_id,
        event_bus=event_bus,
        replying=bool(rules),
        budget=settings.max_replies,
    )

    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE, get_provider

    if not INTEGRATIONS_AVAILABLE:
        report.message = "integrations are not available on this install (SDK not installed)"
        return report
    for row in session.query(IntegrationModel).filter_by(group_id=group_id, enabled=True).order_by(IntegrationModel.slug).all():
        try:
            provider = get_provider(row.provider)
        except KeyError:
            continue
        net = _Network(session, group_id, row, provider)
        if not net.has(SOCIAL_COMMENTS):
            continue
        try:
            _engage(run, row, provider)
        except Exception as e:  # noqa: BLE001 — one network failing never stops the others
            session.rollback()
            report.failed += 1
            report.note(str(e) or f"{row.slug}: {type(e).__name__}")
            logger.warning("social engagement: %s failed: %s", row.slug, e)
    return report
