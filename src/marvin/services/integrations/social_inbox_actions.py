"""What a person can do with one Social inbox item: reply, like, hide / unhide, delete, message the author, make a rule.

**The narrow approval path.** A workflow's ``social.reply`` / ``social.message`` / ``social.delete_comment`` needs an Approval
step, and the engine sends only under a published rule (``social_engagement._Network``). A person pressing a button in the
inbox is the human approval those decisions ask for, and this module is the one door for it, ``InboxActor.act``:

* the caller is an authenticated workspace member holding the role ``ACTION_ROLES`` names for the action — checked by the route
  before anything is looked up (EDITOR to like or hide, ADMIN to reply, delete or message), never here and never by a workflow;
* the capability is one of five (``HUMAN_CAPABILITIES``): comments, repost and everything else are unreachable;
* it acts on one stored item of that workspace, on that item's own integration — the ``comment_id`` and the integration come from
  the stored row, never from the request, so the inbox can't be pointed at another comment or network;
* the text is the person's, typed for that one item; nothing is templated or computed;
* ``approved_by`` (the user's id) is required: no id, no call. A reply is then written to ``social-reply-log`` under that user, so
  the engine never answers the comment again.

It is not a general bypass: no route takes a capability, an integration or a comment id from the caller.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.db.models.users.roles import WorkspaceRole

from . import social_inbox
from .social import (
    SOCIAL_COMMENTS,
    SOCIAL_DELETE_COMMENT,
    SOCIAL_HIDE,
    SOCIAL_LIKE,
    SOCIAL_MESSAGE,
    SOCIAL_REPLY,
    SocialPostError,
    engagement_args,
)
from .social_engagement import EngineCallError, PluginCaller, log_slug, write_reply_log
from .social_rules import KIND_MENTION, LOG_TYPE, PRIVATE, PUBLIC, RULE_TYPE, suggest_keywords

HUMAN_CAPABILITIES = frozenset({SOCIAL_REPLY, SOCIAL_LIKE, SOCIAL_HIDE, SOCIAL_DELETE_COMMENT, SOCIAL_MESSAGE})
"""The only capabilities a person's click can run. Reading comments and reposting have no way in."""

ACTION_ROLES: dict[str, WorkspaceRole] = {
    "list": WorkspaceRole.EDITOR,
    "seen": WorkspaceRole.EDITOR,
    "like": WorkspaceRole.EDITOR,
    "hide": WorkspaceRole.EDITOR,
    "rule": WorkspaceRole.EDITOR,
    "reply": WorkspaceRole.ADMIN,
    "delete": WorkspaceRole.ADMIN,
    "message": WorkspaceRole.ADMIN,
}
"""The role each action needs. Reading, marking seen, liking and hiding are EDITOR's (easily undone moderation, as in a
workflow, where like and hide need no Approval step); replying, deleting and messaging speak for the account or can't be undone,
so they are ADMIN's — the role the workflow engine already asks of integration actions. Making a rule only drafts an entry."""

REPLY, LIKE, HIDE, DELETE, MESSAGE = "reply", "like", "hide", "delete", "message"
_CAPABILITY_OF = {REPLY: SOCIAL_REPLY, LIKE: SOCIAL_LIKE, HIDE: SOCIAL_HIDE, DELETE: SOCIAL_DELETE_COMMENT, MESSAGE: SOCIAL_MESSAGE}
INBOX_RULE = "inbox"
"""What the reply log's ``rule`` says for a reply a person sent from the inbox."""


class InboxError(Exception):
    """An inbox action that can't be done. ``status`` is the HTTP status the route answers with; ``code`` is the plugin's own
    (``unsupported``, ``refused``…) when the network said no."""

    def __init__(self, message: str, status: int = 422, code: str | None = None):
        super().__init__(message)
        self.status, self.code = status, code


class InboxActor(PluginCaller):
    """One integration as a person's click reaches it. ``act`` is the only way the inbox reaches a plugin action."""

    alert_source = None  # the person sees the error at once; a failed click isn't a connection alert

    def declared(self, capability: str):
        """The plugin's action for the capability, whatever its approval flag: a person acting is the approval."""
        return next((a for a in getattr(self.provider, "actions", ()) or () if getattr(a, "capability", None) == capability), None)

    def act(self, capability: str, args: dict, *, approved_by) -> dict:
        if capability not in HUMAN_CAPABILITIES:
            raise EngineCallError(f"the Social inbox can't {capability}", "refused")
        if not approved_by:
            raise EngineCallError("a person has to act on this: no approver was named", "refused")
        action = self.declared(capability)
        if action is None:
            raise EngineCallError(f"'{self.row.slug}' has no way to {capability}", "unsupported")
        try:
            checked = engagement_args(capability, args, dry_run=False)
        except SocialPostError as e:
            raise EngineCallError(str(e), "refused") from e
        return self._run(action.key, checked)


# ── what an item offers ───────────────────────────────────────────────────────────────────────────────────────────


def reply_modes(provider) -> list[str]:
    """The reply modes the network's ``social.reply`` offers: both unless the action's ``private`` argument is an enum
    (``enum: [false]`` is public only). A mode a network then refuses at run time comes back as ``unsupported``."""
    action = next((a for a in getattr(provider, "actions", ()) or () if getattr(a, "capability", None) == SOCIAL_REPLY), None)
    wanted = ((getattr(action, "input_schema", None) or {}).get("properties") or {}).get("private", {}).get("enum")
    if isinstance(wanted, list) and wanted and all(isinstance(v, bool) for v in wanted):
        return [m for m, flag in ((PRIVATE, True), (PUBLIC, False)) if flag in wanted]
    return [PRIVATE, PUBLIC]


def offers(item: Item, provider) -> dict:
    """What can be done with this item on its network: ``actions`` (reply, like, hide, delete, message) and ``reply_modes``. Only what
    the plugin has: hide and delete answer comments under the account's own posts, so a mention isn't offered them, and a message
    needs someone to send it to."""
    if provider is None:
        return {"actions": [], "reply_modes": []}
    has = {name: any(getattr(a, "capability", None) == cap for a in getattr(provider, "actions", ()) or ()) for name, cap in _CAPABILITY_OF.items()}
    own_post = item.kind != KIND_MENTION
    actions = [
        name
        for name, ok in (
            (REPLY, has[REPLY]),
            (LIKE, has[LIKE]),
            (HIDE, has[HIDE] and own_post),
            (DELETE, has[DELETE] and own_post),
            (MESSAGE, has[MESSAGE] and bool(item.author_id or item.author_handle)),
        )
        if ok
    ]
    return {"actions": actions, "reply_modes": reply_modes(provider) if REPLY in actions else []}


def integration_of(session, group_id, item: Item) -> tuple[IntegrationModel | None, object | None]:
    """The item's integration row and its plugin: (None, None) when the connection is gone, off, or its plugin isn't installed
    (the item is then read-only)."""
    from marvin.services.integrations import get_provider

    row = session.get(IntegrationModel, item.integration_id)
    if row is None or row.group_id != group_id or not row.enabled:
        return None, None
    try:
        return row, get_provider(row.provider)
    except KeyError:
        return None, None


# ── the actions ───────────────────────────────────────────────────────────────────────────────────────────────────


def _actor(session, group_id, item: Item, action: str) -> InboxActor:
    row, provider = integration_of(session, group_id, item)
    if row is None:
        raise InboxError("this item's integration is switched off, removed, or its plugin isn't installed", 409)
    if action not in offers(item, provider)["actions"]:
        raise InboxError(f"'{row.slug}' ({item.network}) can't {action} this {item.kind}", 422, "unsupported")
    return InboxActor(session, group_id, row, provider)


def _call(actor: InboxActor, capability: str, args: dict, user_id) -> dict:
    try:
        return actor.act(capability, args, approved_by=user_id)
    except EngineCallError as e:
        refused = e.code in ("unsupported", "refused")
        raise InboxError(str(e), 422 if refused else 502, e.code) from e


def _event(item: Item, event: str) -> None:
    item.status = social_inbox.next_status(item.status, event, replied=social_inbox.has_live_reply(item))


def mark_seen(session, group_id, *, ids: list | None = None, integration: str | None = None) -> int:
    """New → seen for the given items, or for every new item of the workspace (optionally of one integration). Returns how many."""
    q = session.query(Item).filter(Item.group_id == group_id, Item.status == social_inbox.NEW)
    if ids is not None:
        q = q.filter(Item.id.in_(ids))
    if integration:
        q = q.filter(Item.integration_slug == integration)
    changed = q.update({Item.status: social_inbox.SEEN}, synchronize_session=False)
    session.commit()
    return changed


def reply(session, group_id, item: Item, *, text: str, private: bool, user_id, user_name: str | None = None) -> dict:
    """Send a reply to the item as ``user_id`` (their click is the approval) and record it: a ``social-reply-log`` entry (live, so
    the engine never answers this comment) and the item's status. ``{replied, private, reply_id, url, logged}``."""
    text = (text or "").strip()
    if not text:
        raise InboxError("say what to reply")
    actor = _actor(session, group_id, item, REPLY)
    mode = PRIVATE if private else PUBLIC
    if mode not in reply_modes(actor.provider):
        raise InboxError(f"{item.network} can't send a {mode} reply", 422, "unsupported")
    out = _call(actor, SOCIAL_REPLY, {"comment_id": item.item_id, "text": text, "private": private}, user_id)
    if out.get("replied") is False:
        raise InboxError(f"{item.network} did not send the reply", 502)
    outcome = {"reply_id": out.get("reply_id"), "url": out.get("url")}
    slug, written = _log(session, group_id, actor.row, item, text, mode, outcome, user_id, user_name)
    if not written:  # the log writer points the item at its entry; otherwise the item still has to learn of the reply
        social_inbox.mark_replied(
            session,
            actor.row,
            item.item_id,
            log_slug=slug,
            mode=mode,
            rehearsal=False,
            reply_id=outcome["reply_id"],
            when=datetime.now(UTC),
            by=user_id,
        )
    session.commit()
    session.refresh(item)
    return {"replied": True, "private": private, "reply_id": outcome["reply_id"], "url": outcome["url"], "logged": slug is not None}


def _log(session, group_id, row, item: Item, text: str, mode: str, outcome: dict, user_id, user_name: str | None) -> tuple[str | None, bool]:
    """``(log entry slug, whether this call wrote it)``. The entry is written unless there is none to write: the type isn't applied
    (slug None), or this comment already has a live entry (its slug; one entry per comment, and it already stops the engine)."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    type_id = session.query(EntryTypes.id).filter_by(group_id=group_id, slug=LOG_TYPE).scalar()
    if type_id is None:
        return None, False
    live = log_slug(row.slug, item.item_id, rehearsal=False)
    if session.query(Entries.id).filter(Entries.group_id == group_id, Entries.slug == live).first():
        return live, False
    slug = write_reply_log(
        session,
        group_id,
        type_id,
        row,
        _as_item(item),
        rule=INBOX_RULE,
        keyword="",
        reply=text,
        mode=mode,
        rehearsal=False,
        outcome=outcome,
        by=user_id,
        by_name=user_name,
    )
    return slug, True


def _as_item(item: Item) -> dict:
    """The stored item back in the plugin's shape (what the log writer takes)."""
    return {
        "id": item.item_id,
        "network": item.network,
        "post_id": item.post_id,
        "text": item.text,
        "url": item.url,
        "author": {"id": item.author_id, "handle": item.author_handle, "name": item.author_name},
    }


def like(session, group_id, item: Item, *, user_id) -> dict:
    actor = _actor(session, group_id, item, LIKE)
    out = _call(actor, SOCIAL_LIKE, {"comment_id": item.item_id}, user_id)
    if out.get("liked") is False:
        raise InboxError(f"{item.network} did not like it", 502)
    _event(item, social_inbox.EVENT_LIKED)
    session.commit()
    return {"liked": True}


def hide(session, group_id, item: Item, *, hidden: bool, user_id) -> dict:
    actor = _actor(session, group_id, item, HIDE)
    out = _call(actor, SOCIAL_HIDE, {"comment_id": item.item_id, "hidden": hidden}, user_id)
    if out.get("hidden") is not None and bool(out["hidden"]) != hidden:
        raise InboxError(f"{item.network} did not {'hide' if hidden else 'unhide'} it", 502)
    _event(item, social_inbox.EVENT_HIDDEN if hidden else social_inbox.EVENT_UNHIDDEN)
    session.commit()
    return {"hidden": hidden}


def delete(session, group_id, item: Item, *, user_id) -> dict:
    """Delete the comment on the network and drop the item (it no longer exists there)."""
    actor = _actor(session, group_id, item, DELETE)
    out = _call(actor, SOCIAL_DELETE_COMMENT, {"comment_id": item.item_id}, user_id)
    if out.get("deleted") is False:
        raise InboxError(f"{item.network} did not delete it", 502)
    session.delete(item)
    session.commit()
    return {"deleted": True}


def message(session, group_id, item: Item, *, text: str, user_id) -> dict:
    """A direct message to the item's author (not a reply to the comment; no log entry, no status change beyond seen)."""
    text = (text or "").strip()
    if not text:
        raise InboxError("say what to send")
    actor = _actor(session, group_id, item, MESSAGE)
    to = {k: v for k, v in (("id", item.author_id), ("handle", item.author_handle)) if v}
    out = _call(actor, SOCIAL_MESSAGE, {"to": to, "text": text}, user_id)
    if out.get("sent") is False:
        raise InboxError(f"{item.network} did not send the message", 502)
    _event(item, social_inbox.EVENT_SEEN)
    session.commit()
    return {"sent": True, "message_id": out.get("message_id")}


def make_rule(session, group_id, item: Item, *, reply_text: str = "", user_id=None) -> dict:
    """A draft ``social-auto-reply`` entry from this item: keywords suggested from its text, the item's network, private replies
    (the default), and ``reply_text`` as the reply when given. A draft never fires; publishing it is the approval. Returns the
    entry's ``id`` and ``slug``, the suggested ``keywords`` and the editor's path."""
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.entries.entry_service import EntryService

    type_id = session.query(EntryTypes.id).filter_by(group_id=group_id, slug=RULE_TYPE).scalar()
    if type_id is None:
        raise InboxError("apply the Social engagement set first (Settings → Integrations): the rule type isn't in this workspace", 409)
    keywords = suggest_keywords(item.text)
    data = {
        "keywords": ", ".join(keywords),
        "reply": (reply_text or "").strip(),
        "networks": item.network,
        "post": "",
        "reply_as": PRIVATE,
        "also_like": False,
        "kinds": "comment, reply",
    }
    slug = f"social-rule-{uuid.uuid4().hex[:8]}"
    fields = {
        "entry_type_id": type_id,
        "title": f"Rule: {keywords[0] if keywords else 'new'} ({item.network})",
        "slug": slug,
        "status": "draft",
        "data_json": data,
    }
    if user_id:
        fields["created_by"] = user_id
    entry = EntryService(session, group_id, integration_id="social_inbox", actor_id=user_id).create(fields)
    session.commit()
    return {"id": entry.id, "slug": slug, "keywords": keywords, "path": f"/workspace/entries/{entry.id}"}


def summary(session, group_id) -> dict:
    """The nav's view of the inbox: ``available`` when an enabled integration can read comments or items are kept, ``new`` the
    count still unseen, and the ``integrations`` (slug, name, network) the filter offers."""
    from marvin.services.integrations import get_provider

    rows = []
    for row in session.query(IntegrationModel).filter_by(group_id=group_id, enabled=True).order_by(IntegrationModel.slug):
        try:
            provider = get_provider(row.provider)
        except KeyError:
            continue
        if any(getattr(a, "capability", None) == SOCIAL_COMMENTS for a in getattr(provider, "actions", ()) or ()):
            rows.append({"slug": row.slug, "name": row.name, "network": row.provider})
    kept = bool(rows) or session.query(Item.id).filter(Item.group_id == group_id).first() is not None
    return {"available": kept, "new": social_inbox.new_count(session, group_id), "integrations": rows}


def engine_state(session, group_id) -> dict:
    """The scheduled task that fills the inbox, as the page explains it: ``missing`` (the Social engagement set isn't applied),
    ``disabled`` or ``enabled``, with whether replies are rehearsed and whether workflows are told of new comments."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    from .social_engagement import TASK_TYPE, Settings

    task = session.query(ScheduledTaskModel).filter_by(group_id=group_id, task_type=TASK_TYPE).order_by(ScheduledTaskModel.created_at).first()
    if task is None:
        return {"state": "missing", "task_id": None, "rehearsal": True, "announce": True}
    settings = Settings.from_config(task.task_config)
    return {"state": "enabled" if task.enabled else "disabled", "task_id": task.id, "rehearsal": settings.rehearsal, "announce": settings.announce}
