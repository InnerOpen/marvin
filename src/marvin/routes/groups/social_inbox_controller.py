"""
The Social API (``/groups/social-inbox``): the comments, replies and mentions the social engagement poll kept for this workspace,
what was replied (rehearsal or sent; recorded on the item), what a person can do with each one, and a network's auto-reply rules
and mode. Social isn't an integration: it appears when an enabled integration offers a ``social.*`` capability (``/summary``).

Roles (``social_inbox_actions.ACTION_ROLES``): reading, marking seen, like, hide / unhide, listing, making and publishing rules are
EDITOR and above; reply, delete, message and switching a network's auto-reply are ADMIN and above. A person pressing one of
these is the human approval a workflow's Approval step stands for, and the one door that lets it through is
``InboxActor.act`` — it takes the item's own integration and comment id from the stored row, never from the request. Each
route checks the role before it looks anything up.

Only included when the integrations SDK is installed (as the integrations routes are).
"""

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID4

from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import editable_entry, require_workspace_role
from marvin.schemas.group.social_inbox import (
    SocialAutoReplyResult,
    SocialAutoReplyUpdate,
    SocialInboxActionResult,
    SocialInboxHeldRead,
    SocialInboxHide,
    SocialInboxItemRead,
    SocialInboxList,
    SocialInboxMessageCreate,
    SocialInboxReplyCreate,
    SocialInboxReplyRead,
    SocialInboxReplyResult,
    SocialInboxRuleCreate,
    SocialInboxRuleResult,
    SocialInboxSeen,
    SocialInboxSeenResult,
    SocialInboxSummary,
    SocialInboxTrash,
    SocialRuleList,
    SocialRuleNew,
    SocialRulePublish,
    SocialRuleRead,
)
from marvin.schemas.platform import EntryUpdate
from marvin.services.entries import EntryService
from marvin.services.integrations import social_inbox, social_rule_entries, social_setup
from marvin.services.integrations import social_inbox_actions as actions
from marvin.services.integrations.social_inbox_actions import ACTION_ROLES, InboxError

router = APIRouter(prefix="/groups/social-inbox")


def _slugs_to_entry_ids(session, group_id, slugs: set[str]) -> dict:
    from marvin.db.models.platform.entries import Entries

    if not slugs:
        return {}
    return {slug: eid for eid, slug in session.query(Entries.id, Entries.slug).filter(Entries.group_id == group_id, Entries.slug.in_(slugs))}


def _names(session, ids: set) -> dict:
    from marvin.db.models.users.users import Users

    if not ids:
        return {}
    return {u.id: (u.full_name or u.username or u.email) for u in session.query(Users).filter(Users.id.in_(ids))}


def _held(held: dict | None, rules: dict) -> SocialInboxHeldRead | None:
    """Why a matching rule didn't answer the item (``social_inbox.hold``); None when nothing held it back or the record is unreadable."""
    if not held or not held.get("reason"):
        return None
    return SocialInboxHeldRead(**{k: held.get(k) for k in ("reason", "rule", "until", "note", "at")}, rule_entry_id=rules.get(held.get("rule")))


def _reads(session, group_id, rows: list[Item]) -> list[SocialInboxItemRead]:
    """The items as the API returns them: what each one's network offers, and the reply recorded on it."""
    offered: dict = {}
    rule_slugs = {r.reply_rule for r in rows if r.reply_rule} | {r.held["rule"] for r in rows if r.held and r.held.get("rule")}
    rules = _slugs_to_entry_ids(session, group_id, rule_slugs)
    people = _names(session, {r.replied_by for r in rows if r.replied_by})
    out = []
    for r in rows:
        if r.integration_id not in offered:
            offered[r.integration_id] = actions.integration_of(session, group_id, r)[1]
        can = actions.offers(r, offered[r.integration_id])
        reply = None
        if r.replied_at is not None:
            reply = SocialInboxReplyRead(
                mode=r.reply_mode,
                rehearsal=r.reply_rehearsal,
                reply_id=r.reply_id,
                text=r.reply_text,
                rule=r.reply_rule,
                rule_entry_id=rules.get(r.reply_rule),
                note=r.reply_note,
                at=r.replied_at,
                by=r.replied_by,
                by_name=people.get(r.replied_by),
            )
        out.append(
            SocialInboxItemRead(
                id=r.id,
                integration=r.integration_slug,
                network=r.network,
                kind=r.kind,
                post_id=r.post_id,
                post_url=r.post_url,
                author={"id": r.author_id, "handle": r.author_handle, "name": r.author_name},
                text=r.text,
                attachments=r.attachments,
                trashed_at=r.trashed_at,
                created_at=r.posted_at,
                first_seen_at=r.first_seen_at,
                url=r.url,
                status=r.status,
                reply=reply,
                held=_held(r.held, rules),
                actions=can["actions"],
                reply_modes=can["reply_modes"],
            )
        )
    return out


def _refuse(e: InboxError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@controller(router)
class SocialInboxController(BaseUserController):
    def _item(self, item_id: UUID4) -> Item:
        item = social_inbox.get_item(self.session, self.group_id, item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such inbox item.")
        return item

    def _done(self, item: Item, **extra) -> SocialInboxActionResult:
        self.session.refresh(item)
        return SocialInboxActionResult(item=_reads(self.session, self.group_id, [item])[0], **extra)

    @router.get("/summary", response_model=SocialInboxSummary, summary="What Social needs to show: is it available, new count, the networks")
    def summary(
        self, visit: bool = Query(False, description="A visit to a Social page: make sure the workspace's Social plumbing is in place first.")
    ):
        """Whether this workspace has Social at all (`show`: an enabled integration offers a `social.*` capability; it is hidden
        otherwise), the new-item count, each connected network with its auto-reply mode (off | rehearsal | on), its capabilities
        and its own new count, and what the caller's role may do. `visit=true` (the Social pages) first creates what is missing —
        the rule type, and the engine's task while a network reads comments. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["list"])
        if visit:
            social_setup.reconcile(self.session, self.group_id)
        found = social_setup.summary(self.session, self.group_id)
        can = {name: self._may(role) for name, role in ACTION_ROLES.items() if name != "list"}
        return SocialInboxSummary(**found, can=can)

    def _may(self, role) -> bool:
        try:
            require_workspace_role(self.user, self.group_id, role)
        except HTTPException:
            return False
        return True

    @router.get("", response_model=SocialInboxList, summary="List the Social inbox, newest first")
    def list_items(
        self,
        integration: str | None = Query(None, description="One integration, by slug."),
        network: str | None = Query(None, description="One network (instagram, mastodon…)."),
        kind: Literal["comment", "reply", "mention", "message", "story_reply", "story_mention", "reaction", "live_comment"] | None = Query(None),
        item_status: list[Literal["new", "seen", "replied", "hidden", "liked"]] | None = Query(
            None, alias="status", description="One or more statuses (repeat the parameter)."
        ),
        q: str | None = Query(None, max_length=200, description="Text to find in the item or its author's handle or name."),
        since: datetime | None = Query(None, description="Written at or after this time."),
        until: datetime | None = Query(None, description="Written at or before this time."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        trashed: bool = Query(False, description="The Trash: items a person moved out of the inbox (restorable)."),
    ):
        """Items the social engagement poll kept (30 days), newest first, with what each one's network offers (`actions`,
        `reply_modes`) and how it was answered (`reply`: rehearsal or sent, with its log entry). EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["list"])
        rows, total = social_inbox.query(
            self.session,
            self.group_id,
            integration=integration,
            network=network,
            kind=kind,
            status=item_status,
            text=q,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            trashed=trashed,
        )
        return SocialInboxList(
            items=_reads(self.session, self.group_id, rows),
            total=total,
            limit=limit,
            offset=offset,
            new=social_inbox.new_count(self.session, self.group_id),
        )

    @router.get("/replies", response_model=SocialInboxList, summary="List the replies, latest first")
    def list_replies(
        self,
        integration: str | None = Query(None, description="One integration, by slug."),
        rehearsal: bool | None = Query(None, description="true: only rehearsals (dry runs); false: only real replies."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """The Replies view: the items that have a reply recorded on them (an auto-reply rule's, live or rehearsal, or a person's
        from the inbox), the latest reply first. Each item carries its `reply`: mode, text, the rule, when, and who. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["list"])
        rows, total = social_inbox.query(
            self.session, self.group_id, integration=integration, replied=True, rehearsal=rehearsal, limit=limit, offset=offset
        )
        return SocialInboxList(
            items=_reads(self.session, self.group_id, rows),
            total=total,
            limit=limit,
            offset=offset,
            new=social_inbox.new_count(self.session, self.group_id),
        )

    def _network(self, slug: str):
        net = next((n for n in social_setup.social_networks(self.session, self.group_id) if n.row.slug == slug), None)
        if net is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such connected social network.")
        return net

    @router.put("/integrations/{slug}/auto-reply", response_model=SocialAutoReplyResult, summary="Switch a network's auto-reply")
    def set_auto_reply(self, slug: str, data: SocialAutoReplyUpdate):
        """off (the default: the network is still read for the inbox and the new-comment trigger, but never answered), rehearsal
        (dry runs: the plugin is asked what it would send and the item records it) or on (live: published rules send).
        409 when the network can't reply and the mode isn't off. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["auto_reply"])
        net = self._network(slug)
        if data.mode != social_setup.OFF and not net.can_reply:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{net.row.name} has no way to reply, so auto-reply can only be off.")
        social_setup.set_mode(self.session, net.row, data.mode)
        return SocialAutoReplyResult(integration=slug, auto_reply=data.mode)

    @router.get("/rules", response_model=SocialRuleList, summary="List auto-reply rules (a network's, plus the all-network ones)")
    def list_rules(
        self,
        integration: str | None = Query(
            None, description="An integration's slug: its rules plus the rules for every network. Empty lists every rule."
        ),
    ):
        """The rules (the internal `social-auto-reply` entries) that apply to the
        network — those naming it and those naming no network (`all_networks`) — oldest first. Edit one with the entry editor at
        its `path`. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["rules"])
        row = self._network(integration).row if integration else None
        return SocialRuleList(
            rules=[
                SocialRuleRead(**asdict(r), published=r.published, all_networks=r.all_networks)
                for r in social_rule_entries.list_rules(self.session, self.group_id, integration=row)
            ]
        )

    @router.post("/rules", response_model=SocialRuleRead, status_code=status.HTTP_201_CREATED, summary="Start a new auto-reply rule")
    def create_rule(self, data: SocialRuleNew | None = None):
        """A new blank rule as a draft (it never fires), for the named network — its slug goes in `networks` — or for every
        network when none is named. Write it with the entry editor at `path` and publish it. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["rule"])
        row = self._network(data.integration).row if data and data.integration else None
        made = social_rule_entries.create_rule(self.session, self.group_id, integration=row, user_id=self.user.id)
        return SocialRuleRead(**asdict(made), published=made.published, all_networks=made.all_networks)

    @router.put("/rules/{rule_id}/published", response_model=SocialRuleRead, summary="Publish or unpublish a rule")
    def publish_rule(self, rule_id: UUID4, data: SocialRulePublish):
        """Publish the rule (it then answers; publishing is the approval of its reply text, and needs its keywords and reply) or
        take it back to a draft. The rule's own entry rules apply: the entry editor does the same. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["publish"])
        if not social_rule_entries.is_rule_entry(self.session, self.group_id, rule_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule.")
        new_status = "published" if data.published else "draft"
        editable_entry(self.user, self.group_id, self.repos, rule_id, new_status)
        service = EntryService(self.session, self.group_id, event_bus=self.event_bus, actor_id=self.user.id)
        service.update(rule_id, EntryUpdate(status=new_status))
        found = next((r for r in social_rule_entries.list_rules(self.session, self.group_id) if r.id == rule_id), None)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule.")
        return SocialRuleRead(**asdict(found), published=found.published, all_networks=found.all_networks)

    @router.post("/seen", response_model=SocialInboxSeenResult, summary="Mark items seen")
    def mark_seen(self, data: SocialInboxSeen):
        """New → seen for the named items (`ids`), or for every new item (`all`, optionally of one `integration`). Items already
        seen, replied, liked or hidden keep their status. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["seen"])
        if not data.ids and not data.all:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the items (`ids`) or set `all`.")
        changed = actions.mark_seen(
            self.session, self.group_id, ids=None if data.all else data.ids, integration=data.integration if data.all else None
        )
        return SocialInboxSeenResult(changed=changed)

    @router.post("/{item_id}/reply", response_model=SocialInboxReplyResult, summary="Reply to an item (a person's approval)")
    def reply(self, item_id: UUID4, data: SocialInboxReplyCreate):
        """Send a reply as the caller: private (to the commenter; the default) or public (in the thread), only when the item's
        network offers it. The caller pressing Reply is the approval a workflow's Approval step would give. It is recorded on the item
        (live, by the caller), so the poll never answers this comment, and the item becomes `replied`.
        A network that refuses the mode or the text answers 422; a failure on the network 502. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["reply"])
        item = self._item(item_id)
        try:
            out = actions.reply(
                self.session,
                self.group_id,
                item,
                text=data.text,
                private=data.private,
                user_id=self.user.id,
                user_name=getattr(self.user, "full_name", None) or getattr(self.user, "email", None),
            )
        except InboxError as e:
            raise _refuse(e) from e
        return SocialInboxReplyResult(**out, item=_reads(self.session, self.group_id, [item])[0])

    @router.post("/{item_id}/like", response_model=SocialInboxActionResult, summary="Like an item")
    def like(self, item_id: UUID4):
        """Like the comment, reply or mention on its network (new or seen items become `liked`). 422 when the network has no
        like. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["like"])
        item = self._item(item_id)
        try:
            actions.like(self.session, self.group_id, item, user_id=self.user.id)
        except InboxError as e:
            raise _refuse(e) from e
        return self._done(item)

    @router.post("/{item_id}/hide", response_model=SocialInboxActionResult, summary="Hide or unhide an item")
    def hide(self, item_id: UUID4, data: SocialInboxHide | None = None):
        """Hide the comment under your post (`hidden: true`, the default) or unhide it. 422 for a network with no hide, and for
        a mention (hiding is for comments under your own posts). EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["hide"])
        item = self._item(item_id)
        try:
            actions.hide(self.session, self.group_id, item, hidden=True if data is None else data.hidden, user_id=self.user.id)
        except InboxError as e:
            raise _refuse(e) from e
        return self._done(item)

    @router.post("/{item_id}/trash", response_model=SocialInboxActionResult, summary="Move an item to the inbox's Trash, or restore it")
    def trash(self, item_id: UUID4, data: SocialInboxTrash | None = None):
        """Move the item to the inbox's Trash (`trashed: true`, the default) or restore it. Marvin only: nothing on the network
        changes (that is Delete), and a trashed item is never answered by a rule. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["trash"])
        item = self._item(item_id)
        actions.trash(self.session, self.group_id, item, trashed=True if data is None else data.trashed)
        return self._done(item)

    @router.delete("/{item_id}", response_model=SocialInboxActionResult, summary="Delete the comment on its network")
    def delete(self, item_id: UUID4):
        """Delete the comment on its network (it can't be undone) and drop the item from the inbox. 422 for a network with no
        delete, and for a mention. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["delete"])
        item = self._item(item_id)
        try:
            actions.delete(self.session, self.group_id, item, user_id=self.user.id)
        except InboxError as e:
            raise _refuse(e) from e
        return SocialInboxActionResult(item=None)

    @router.post("/{item_id}/message", response_model=SocialInboxActionResult, summary="Message the item's author")
    def message(self, item_id: UUID4, data: SocialInboxMessageCreate):
        """Send the author a direct message (not a reply to the comment), for a network that has `social.message` and an
        author to send it to. ADMIN and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["message"])
        item = self._item(item_id)
        try:
            out = actions.message(self.session, self.group_id, item, text=data.text, user_id=self.user.id)
        except InboxError as e:
            raise _refuse(e) from e
        return self._done(item, message_id=out.get("message_id"))

    @router.post("/{item_id}/rule", response_model=SocialInboxRuleResult, summary="Make an auto-reply rule from an item")
    def make_rule(self, item_id: UUID4, data: SocialInboxRuleCreate | None = None):
        """Create a draft `social-auto-reply` entry from the item: keywords suggested from its text, its integration (its slug in
        `networks`), private replies and the given reply text. A draft never fires; the entry editor (`path`) is where to adjust
        and publish it. (The rule type is made on first need.) EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["rule"])
        item = self._item(item_id)
        try:
            return SocialInboxRuleResult(
                **actions.make_rule(self.session, self.group_id, item, reply_text=data.reply if data else "", user_id=self.user.id)
            )
        except InboxError as e:
            raise _refuse(e) from e
