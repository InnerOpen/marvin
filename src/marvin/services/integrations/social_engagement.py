"""The social engagement engine: reads comments on every connected network and answers them under the workspace's published rules.

One run (the ``social_engagement`` scheduled task, every 5 minutes; Marvin makes and switches it on while a network reads
comments, ``social_setup.reconcile``) does this for each enabled integration whose plugin offers ``social.comments``:

1. **read** the items since the integration's stored cursor (``IntegrationModel.state["social"]``; the cursor is the plugin's own
   opaque string, passed back as ``since``), keep them for the Social inbox and announce each new one as a workflow event —
   whatever the network's auto-reply mode;
2. **reply**, when the network's auto-reply mode (``state["social"]["auto_reply"]``) is ``rehearsal`` or ``on``: drop the account's
   own comments, items older than 7 days and comments already answered, match the published rules (``social_rules``:
   ``social-auto-reply`` entries), reply in the rule's mode (private, public or both), like the comment too when the rule says
   so and the network can, and record the reply on the inbox item.

**Auto-reply is per network**: ``off`` (the default) reads and announces but never replies; ``rehearsal`` calls the plugin with
``dry_run: true`` (it sends nothing), records the dry run on the item (``reply_rehearsal``) and moves the rehearsal read cursor
instead of the live one — so switching to ``on`` still answers what is within the window, and a rehearsal never counts as
"answered"; ``on`` sends. At most ``max_replies`` (20) per run; what the cap holds back, and what failed for a reason worth
retrying, waits in ``state["social"]["pending"]`` for the next run (live only; at most 3 attempts).

**The item is the reply log.** A reply is written on the inbox item (``social_inbox.record_reply``: mode, rehearsal, reply id,
text, rule, when) — inserting the item first when the engine replies to one it hasn't stored — and a live reply on an item is what
"answered" means: one comment, one reply. The 30-day inbox prune keeps
items with a live reply for 180 days, and the answer window is at most 90 days, so a pruned item is always too old to answer again.

**The narrow approval path.** A workflow's ``social.reply`` needs an Approval step; a published rule *is* the approval of
its text, so the engine sends without one — through exactly one door, ``_Network.call``:

* only ``social.comments``, ``social.reply`` and ``social.like`` can pass through it (``ENGINE_CAPABILITIES``): message,
  repost and delete are unreachable from here;
* a ``social.reply`` is routed as approved only when ``_rule_approves`` says so: the call carries a ``SocialRule`` that is
  published (checked against the entry again at the moment of sending) and the text is that rule's reply, verbatim — never
  a templated or computed text;
* nothing outside this module can ask for it: a workflow step, the API and the plugins never reach ``_Network``.

The Social inbox has its own, separate door for a *person* acting on one item (``social_inbox_actions.py``): there the person's
click is the approval, and the engine's door stays exactly as narrow as above.

A plugin refusal (IntegrationError code ``unsupported``, or ``refused`` for bad arguments) skips that comment: no retry, nothing
recorded, noted in the run summary. Any other failure is that network's failure for the run: the other networks go on.
A plugin that rejects its cursor (``invalid_cursor``) has it dropped and is read again without one.

**Keeping the items.** Every network read the poll makes is also written to ``social_inbox_items``
(``social_inbox.persist_items``: one batch upsert per read, the account's own items skipped, older than 30 days never kept), so
the Social inbox can list them. It can't fail the poll.

**Announcing**: the same poll sends one ``social_comment_received`` event per new comment, reply or mention, so a workflow can
start on it. It is a second job of the same run, with its own state, so replying and announcing never change one another:

* its own cursor, ``state["social"]["events_cursor"]`` — rehearsal and live reply cursors move independently of it;
* ``events_started_at`` marks the first poll, which announces nothing (no backlog): it only records the newest cursor and
  the ids it saw. After that an item is announced only when it was written after that moment and is within the 7-day
  window, so a cursor that lags, is dropped, or restarts at the newest items never replays the past;
* ``events_seen`` (the last 500 ids) is claimed *before* each event is sent, so a crash or a re-read can lose at most the one
  event in flight and never sends one twice;
* the account's own items are never announced (the same check as replying), which is what stops a workflow's public reply
  from starting the workflow again;
* it needs only ``social.comments`` — no rule, no ``social.reply``. One read serves both jobs when the cursors agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from marvin.core.root_logger import get_logger

from . import social_inbox
from .social import SOCIAL_COMMENTS, SOCIAL_LIKE, SOCIAL_MESSAGE, SOCIAL_REPLY
from .social_rules import (
    BOTH,
    DEFAULT_MAX_AGE_DAYS,
    DIRECT_KINDS,
    ITEM_KINDS,
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
from .social_setup import OFF, REHEARSAL, get_mode

logger = get_logger(__name__)

ENGINE_CAPABILITIES = frozenset({SOCIAL_COMMENTS, SOCIAL_REPLY, SOCIAL_LIKE, SOCIAL_MESSAGE})
"""The only capabilities the engine calls. A message only answers a direct message a published rule matched, to its author
(``_rule_approves_message``); repost and delete have no way in."""
DEFAULT_MAX_REPLIES = 20
DEFAULT_LIMIT = 50
MAX_ATTEMPTS = 3
MAX_PENDING = 200
STATE_KEY = "social"
SOURCE_TAG = "social_engagement"
TASK_TYPE = "social_engagement"
"""The engine's scheduled task type (``scheduled_tasks/handlers/social.py``)."""
CODES_NO_RETRY = frozenset({"unsupported", "refused"})
"""Plugin refusals that skip a comment for good: the network can't do it, or the arguments are wrong."""
INVALID_CURSOR = "invalid_cursor"
MAX_NOTES = 5  # failures / refusals a run summary names
EVENT_SOURCE = "social_engagement"
MAX_SEEN = 500
"""Ids the events pass remembers having announced (or passed over): what a re-read of the same items is checked against."""
REASON_EVENT_OWN = "event_own"
REASON_EVENT_OLD = "event_too_old"
REASON_EVENT_BEFORE = "event_before_start"


@dataclass(frozen=True)
class Settings:
    """What a run does, from the task's ``task_config``. Whether a network replies, rehearses or stays quiet is the network's own
    setting (``social_setup.get_mode``), not the task's; an old ``rehearsal`` key here is mapped onto the networks once
    (``social_setup.map_legacy_rehearsal``)."""

    max_replies: int = DEFAULT_MAX_REPLIES
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    limit: int = DEFAULT_LIMIT

    @classmethod
    def from_config(cls, config: dict | None) -> Settings:
        config = config or {}

        def number(key: str, default: int, most: int | None = None) -> int:
            try:
                value = max(1, int(config.get(key) or default))
            except (TypeError, ValueError):
                return default
            return min(value, most) if most else value

        return cls(
            max_replies=number("max_replies", DEFAULT_MAX_REPLIES),
            # never longer than an answered item is kept (see the module docstring)
            max_age_days=number("max_age_days", DEFAULT_MAX_AGE_DAYS, social_inbox.MAX_ANSWER_WINDOW_DAYS),
            limit=number("limit", DEFAULT_LIMIT),
        )


@dataclass
class Report:
    """What a run did."""

    integrations: list[str] = field(default_factory=list)
    checked: int = 0
    matched: int = 0
    sent: int = 0
    """Replies sent (networks switched on)."""
    rehearsed: int = 0
    """Replies a rehearsing network would have sent (dry runs, recorded on the item)."""
    liked: int = 0
    announced: int = 0
    """``social_comment_received`` events sent."""
    skipped: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)
    """Failures and refusals, one line each."""
    failed: int = 0
    message: str | None = None
    """Why the run did nothing at all."""

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def worth_logging(self) -> bool:
        return bool(self.matched or self.failed or self.message or self.announced)

    def summary(self) -> str:
        if self.message:
            return f"Social engagement: {self.message}"
        head = f"Social engagement: {len(self.integrations)} network(s)"
        parts = [f"checked {self.checked}", f"matched {self.matched}", f"replied {self.sent}"]
        if self.rehearsed:
            parts.append(f"would reply {self.rehearsed}")
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


def _rule_approves_message(rule, args: dict) -> bool:
    """Whether a published rule approves this ``social.message``: the answer to a direct message (``_answer_direct``), to its
    author, with the rule's reply exactly."""
    to = args.get("to") if isinstance(args.get("to"), dict) else {}
    return (
        isinstance(rule, SocialRule)
        and rule.published
        and bool(rule.reply.strip())
        and args.get("text") == rule.reply
        and bool(to.get("id") or to.get("handle"))
        and bool(rule.kinds & set(DIRECT_KINDS))
    )


class PluginCaller:
    """One integration as a caller reaches it: the plugin's action for a capability, run with the connection's own config and
    secret. It is not a door by itself — the engine's is ``_Network.call`` and a person's is
    ``social_inbox_actions.InboxActor.act`` — each decides what may pass and what counts as approved before calling ``_run``.
    ``alert_source`` is where a failure's "needs attention" alert says it came from (None: no alert, the caller shows the
    error itself)."""

    alert_source: str | None = "scheduled_task"

    def __init__(self, session, group_id, row, provider):
        self.session, self.group_id, self.row, self.provider = session, group_id, row, provider
        self._ctx = None
        self._secret = None

    def has(self, capability: str) -> bool:
        """Whether the plugin declares an action for it (whatever its approval flag: the caller's own rules decide)."""
        from .alert_routing import capability_action

        return capability_action(self.provider, capability, {}, approved=True) is not None

    def _run(self, key: str, args: dict) -> dict:
        from marvin.services.integrations import IntegrationContext, build_http, errors
        from marvin.services.secrets.resolver import resolve_secret

        if self._ctx is None:
            self._secret = resolve_secret(self.row.secret_ref, self.group_id) if self.row.secret_ref else None
            self._ctx = IntegrationContext(config=self.row.config or {}, secret=self._secret, logger=logger, http=build_http())
        try:
            result = self.provider.run_action(key, args, self._ctx)
        except Exception as e:  # noqa: BLE001 — every plugin failure is the caller's to classify
            code = errors.error_code(e)
            detail = errors.redact(str(e) or type(e).__name__, errors.secret_values(self._secret))
            if self.alert_source and code not in CODES_NO_RETRY and code != INVALID_CURSOR:
                errors.connection_failed(
                    self.group_id, self.row.id, self.provider, key, e, source=self.alert_source, session=self.session, secrets=(self._secret,)
                )
            raise EngineCallError(f"{self.row.slug}.{key}: {detail}", code) from e
        errors.connection_succeeded(self.group_id, self.row.id, session=self.session)
        return result if isinstance(result, dict) else {}


class _Network(PluginCaller):
    """One integration as the engine calls it. ``call`` is the only way the engine reaches a plugin action."""

    def call(self, capability: str, args: dict, rule: SocialRule | None = None) -> dict:
        if capability not in ENGINE_CAPABILITIES:
            raise EngineCallError(f"the engagement engine can't {capability}", "refused")
        from .alert_routing import capability_action

        approved = (capability == SOCIAL_REPLY and _rule_approves(rule, args)) or (
            capability == SOCIAL_MESSAGE and _rule_approves_message(rule, args)
        )
        if capability == SOCIAL_MESSAGE and not approved:
            raise EngineCallError(f"'{self.row.slug}': the engine messages only to answer a direct message a published rule matched", "refused")
        found = capability_action(self.provider, capability, args, approved=approved)
        if found is None:
            raise EngineCallError(f"'{self.row.slug}' has no way to {capability} that a published rule approves", "unsupported")
        return self._run(*found)


# ── rules and the log ─────────────────────────────────────────────────────────────────────────────────────────────


def _rule_entries(session, group_id):
    """The workspace's published rule entries, oldest first."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    return (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.group_id == group_id, EntryTypes.slug == RULE_TYPE, Entries.status == "published")
        .order_by(Entries.created_at.asc(), Entries.id.asc())
    )


def load_rules(session, group_id) -> list[SocialRule]:
    """The published ``social-auto-reply`` rules, oldest first. Drafts never fire."""
    rules = []
    for entry in _rule_entries(session, group_id):
        rule = rule_from_data(entry.data_json or {}, id=entry.slug, order=len(rules))
        if rule is not None:
            rules.append(rule)
    return rules


def _answered(session, row, ids: list[str], rehearsal: bool) -> set[str]:
    """Which of these comment ids are already answered: a live reply on the inbox item (in rehearsal, a rehearsal's too, so a dry
    run isn't recorded every poll)."""
    return social_inbox.answered_ids(session, row, ids, rehearsal_counts=rehearsal) if ids else set()


# ── one integration ───────────────────────────────────────────────────────────────────────────────────────────────


def _state(row) -> dict:
    state = (row.state or {}).get(STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_state(session, row, state: dict) -> None:
    # The auto-reply mode is an admin's setting, written from another request while a run is in flight: keep the stored one
    # rather than the value this run read at its start.
    session.refresh(row, ["state"])
    stored = _state(row)
    if "auto_reply" in stored:
        state["auto_reply"] = stored["auto_reply"]
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


@dataclass
class _Run:
    """What one engine run shares across integrations."""

    session: object
    group_id: object
    settings: Settings
    rules: list[SocialRule]
    report: Report
    now: datetime
    event_bus: object = None
    replying: bool = True
    """Whether this run can answer comments: there is at least one published rule."""
    budget: int = 0


def poll_kinds(provider) -> list[str]:
    """What a read asks the plugin for: the comment kinds, and the direct-message kinds its `social.comments` action declares
    (its `kinds` enum) — a plugin refuses a kind it doesn't know, so only what it offers is asked for."""
    action = next((a for a in getattr(provider, "actions", ()) or () if getattr(a, "capability", None) == SOCIAL_COMMENTS), None)
    declared = ((((getattr(action, "input_schema", None) or {}).get("properties") or {}).get("kinds") or {}).get("items") or {}).get("enum")
    offered = set(declared) if isinstance(declared, list) else set()
    return [*ITEM_KINDS, *(k for k in DIRECT_KINDS if k in offered)]


def _read_once(run: _Run, net: _Network, row, cursor: str | None, kinds: list[str], cache: dict) -> tuple[list[dict], str | None, bool]:
    """``_read``, remembered for the rest of this integration's pass: the replying and announcing jobs read the network
    once when they stand at the same cursor and ask for the same kinds. Each network read is kept for the Social inbox."""
    key = (cursor, tuple(kinds))
    if key not in cache:
        cache[key] = _read(net, cursor, run.settings, kinds)
        handles, ids = own_identities(row.config)
        social_inbox.persist_items(run.session, row, cache[key][0], handles=handles, ids=ids, now=run.now)
    return cache[key]


def _engage(run: _Run, row, provider) -> None:
    """One integration's pass: announce its new items, then answer under the rules when the network's auto-reply is rehearsal or on
    (there are rules and the plugin can reply). An integration whose auto-reply is off is still read, for the inbox and the trigger."""
    report, session = run.report, run.session
    net = _Network(session, run.group_id, row, provider)
    state = _state(row)
    cache: dict = {}
    mode = get_mode(row)
    replying = run.replying and mode != OFF and net.has(SOCIAL_REPLY)
    report.integrations.append(row.slug)
    _announce(run, net, row, state, cache, count=not replying)
    if replying:
        _reply(run, net, row, state, cache, rehearsal=mode == REHEARSAL)


def _reply(run: _Run, net: _Network, row, state: dict, cache: dict, *, rehearsal: bool) -> None:
    report, settings, session = run.report, run.settings, run.session
    cursor_key = "rehearsal_cursor" if rehearsal else "cursor"
    # Every kind is read (the Social inbox keeps mentions and direct messages too); a rule's own ``kinds`` decide what it answers.
    items, cursor, dropped = _read_once(run, net, row, state.get(cursor_key), poll_kinds(net.provider), cache)
    pending = [] if rehearsal else [p for p in state.get("pending") or [] if isinstance(p, dict) and isinstance(p.get("item"), dict)]
    attempts = {str(p["item"]["id"]): int(p.get("attempts") or 0) for p in pending}
    fresh = {str(i["id"]) for i in items}
    candidates = [p["item"] for p in pending if str(p["item"]["id"]) not in fresh] + items
    candidates += _inbox_direct(run, row, {str(c["id"]) for c in candidates})
    report.checked += len(items)

    handles, ids = own_identities(row.config)
    names = {row.slug.lower(), row.provider.lower()}
    answered = _answered(session, row, [str(i["id"]) for i in candidates], rehearsal)
    trashed = social_inbox.trashed_ids(session, row, [str(i["id"]) for i in candidates])
    keep: list[dict] = []
    for item in candidates:
        cid = str(item["id"])
        if cid in answered:
            report.skipped[REASON_ALREADY_REPLIED] += 1
        elif cid in trashed:
            report.skipped["trashed"] += 1  # a person moved it to the Trash: leave it alone
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
            if _answer(run, net, row, item, *hit, rehearsal=rehearsal):
                tries = attempts.get(cid, 0) + 1
                if tries < MAX_ATTEMPTS:
                    keep.append({"item": item, "attempts": tries})
                else:
                    report.note(f"{row.slug}: gave up on comment {cid} after {tries} attempts")
    if not rehearsal:
        state["pending"] = keep[-MAX_PENDING:]
    if cursor or dropped:
        state[cursor_key] = cursor
    state["polled_at"] = run.now.isoformat()
    _save_state(session, row, state)


# ── announcing: one event per new item ────────────────────────────────────────────────────────────────────────────


def _announce(run: _Run, net: _Network, row, state: dict, cache: dict, *, count: bool) -> None:
    """Send ``social_comment_received`` for each item the integration's events cursor hasn't passed (see the module docstring)."""
    report, settings, session = run.report, run.settings, run.session
    items, cursor, dropped = _read_once(run, net, row, state.get("events_cursor"), poll_kinds(net.provider), cache)
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
        if str(item.get("kind") or "") in DIRECT_KINDS:
            continue  # a direct message is the inbox's, not a new comment: social_comment_received is for comments
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


def _inbox_direct(run: _Run, row, have: set[str]) -> list[dict]:
    """The direct messages a webhook brought (Instagram, Facebook) that no poll reads: unanswered inbox items of the kinds some
    rule answers, within the answer window — so a rule answers a DM however it arrived. None when no rule answers DMs."""
    kinds = {k for r in run.rules for k in r.kinds} & set(DIRECT_KINDS)
    if not kinds:
        return []
    since = run.now - timedelta(days=run.settings.max_age_days)
    return [i for i in social_inbox.unanswered_direct(run.session, row, kinds, since=since) if i["id"] not in have]


def _answer_direct(run: _Run, net: _Network, row, item: dict, rule: SocialRule, *, rehearsal: bool) -> bool:
    """Answer a direct message (a message, a story reply or mention) with a direct message to its author — the rule's reply, in the
    network's mode (a dry run when it is rehearsing). Networks allow it only for a while after the person's last message: a refusal
    skips it for good. True when it should be retried next run."""
    report = run.report
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    to = {k: v for k, v in (("id", author.get("id")), ("handle", author.get("handle"))) if v}
    if not to or not net.has(SOCIAL_MESSAGE):
        report.skipped["unsupported"] += 1
        return False
    try:
        out = net.call(SOCIAL_MESSAGE, {"to": to, "text": rule.reply, "dry_run": rehearsal}, rule)
    except EngineCallError as e:
        return _failed(report, row, item, [(True, e)], rehearsal)
    if not rehearsal and out.get("sent") is False:
        return _failed(report, row, item, [(True, EngineCallError(f"{row.slug}: the network did not send the message"))], rehearsal)
    social_inbox.record_reply(
        run.session, row, item, mode="message", rehearsal=rehearsal, reply_id=out.get("message_id"), text=rule.reply, rule=rule.id,
        when=datetime.now(UTC),
    )  # fmt: skip
    if rehearsal:
        report.rehearsed += 1
    else:
        report.sent += 1
    return False


def _answer(run: _Run, net: _Network, row, item: dict, rule: SocialRule, keyword: str, *, rehearsal: bool) -> bool:
    """Reply to one matched item in the rule's mode (a dry run when the network is rehearsing). True when it should be retried next run."""
    report = run.report
    if not rehearsal and not _still_published(run.session, run.group_id, rule):
        report.note(f"{row.slug}: rule '{rule.id}' is no longer published; comment {item['id']} left unanswered")
        return False
    if str(item.get("kind") or "") in DIRECT_KINDS:
        return _answer_direct(run, net, row, item, rule, rehearsal=rehearsal)
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
    social_inbox.record_reply(
        run.session,
        row,
        item,
        mode=mode,
        rehearsal=rehearsal,
        reply_id=outcome.get("reply_id"),
        text=rule.reply,
        rule=rule.id,
        note=outcome.get("error"),
        when=datetime.now(UTC),
    )
    if rehearsal:
        report.rehearsed += 1
    else:
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

    Every network that reads comments is read and announced; the ones whose auto-reply is rehearsal or on are also answered,
    when there are published rules (with none, nothing is read for replying, so no reply cursor moves past comments a later
    rule would answer). ``event_bus`` carries the announcements (the scheduler's own; a plain bus when none is given)."""
    settings = settings or Settings()
    report = Report()
    rules = load_rules(session, group_id)
    if event_bus is None:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)
    run = _Run(
        session,
        group_id,
        settings,
        rules,
        report,
        now or datetime.now(UTC),
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
