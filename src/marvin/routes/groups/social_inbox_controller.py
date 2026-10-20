"""
The Social inbox API: the comments, replies and mentions the social engagement poll kept for this workspace, what was
replied (rehearsal or sent), and what a person can do with each one.

Roles (``social_inbox_actions.ACTION_ROLES``): reading, marking seen, like, hide / unhide and making a rule are EDITOR and
above; reply, delete and message are ADMIN and above. A person pressing one of these is the human approval a workflow's Approval
step stands for, and the one door that lets it through is ``InboxActor.act`` — it takes the item's own integration and comment
id from the stored row, never from the request. Each route checks the role before it looks anything up.

Only included when the integrations SDK is installed (as the integrations routes are).
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID4

from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_role
from marvin.schemas.group.social_inbox import (
    SocialInboxActionResult,
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
)
from marvin.services.integrations import social_inbox
from marvin.services.integrations import social_inbox_actions as actions
from marvin.services.integrations.social_inbox_actions import ACTION_ROLES, InboxError

router = APIRouter(prefix="/groups/social-inbox")


def _slugs_to_entry_ids(session, group_id, slugs: set[str]) -> dict:
    from marvin.db.models.platform.entries import Entries

    if not slugs:
        return {}
    return {slug: eid for eid, slug in session.query(Entries.id, Entries.slug).filter(Entries.group_id == group_id, Entries.slug.in_(slugs))}


def _reads(session, group_id, rows: list[Item]) -> list[SocialInboxItemRead]:
    """The items as the API returns them: what each one's network offers, and its reply's log entry."""
    offered: dict = {}
    entries = _slugs_to_entry_ids(session, group_id, {r.reply_log_slug for r in rows if r.reply_log_slug})
    out = []
    for r in rows:
        if r.integration_id not in offered:
            offered[r.integration_id] = actions.integration_of(session, group_id, r)[1]
        can = actions.offers(r, offered[r.integration_id])
        reply = None
        if r.replied_at is not None or r.reply_log_slug:
            reply = SocialInboxReplyRead(
                log_slug=r.reply_log_slug,
                log_entry_id=entries.get(r.reply_log_slug),
                mode=r.reply_mode,
                rehearsal=r.reply_rehearsal,
                reply_id=r.reply_id,
                at=r.replied_at,
                by=r.replied_by,
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
                created_at=r.posted_at,
                first_seen_at=r.first_seen_at,
                url=r.url,
                status=r.status,
                reply=reply,
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

    @router.get("/summary", response_model=SocialInboxSummary, summary="What the Social inbox needs to show: new count, integrations, the task")
    def summary(self):
        """Whether this workspace has an inbox (an integration that reads comments, or items kept), how many items are new, the
        integrations the filter offers, the Social engagement task's state (it fills the inbox), and what the caller's role may do.
        EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["list"])
        found = actions.summary(self.session, self.group_id)
        can = {name: self._may(role) for name, role in ACTION_ROLES.items() if name != "list"}
        return SocialInboxSummary(**found, engine=actions.engine_state(self.session, self.group_id), can=can)

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
        kind: Literal["comment", "reply", "mention"] | None = Query(None),
        item_status: list[Literal["new", "seen", "replied", "hidden", "liked"]] | None = Query(
            None, alias="status", description="One or more statuses (repeat the parameter)."
        ),
        q: str | None = Query(None, max_length=200, description="Text to find in the item or its author's handle or name."),
        since: datetime | None = Query(None, description="Written at or after this time."),
        until: datetime | None = Query(None, description="Written at or before this time."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
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
        )
        return SocialInboxList(
            items=_reads(self.session, self.group_id, rows),
            total=total,
            limit=limit,
            offset=offset,
            new=social_inbox.new_count(self.session, self.group_id),
        )

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
        network offers it. The caller pressing Reply is the approval a workflow's Approval step would give. It is written to
        the `social-reply-log` (live, by the caller), so the poll never answers this comment, and the item becomes `replied`.
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
        """Create a draft `social-auto-reply` entry from the item: keywords suggested from its text, its network, private replies
        and the given reply text. A draft never fires; the entry editor (`path`) is where to adjust and publish it. 409 when
        the Social engagement set isn't applied. EDITOR and above."""
        require_workspace_role(self.user, self.group_id, ACTION_ROLES["rule"])
        item = self._item(item_id)
        try:
            return SocialInboxRuleResult(
                **actions.make_rule(self.session, self.group_id, item, reply_text=data.reply if data else "", user_id=self.user.id)
            )
        except InboxError as e:
            raise _refuse(e) from e
