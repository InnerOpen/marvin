"""
The Audience API (``/groups/audience``): what Audience › Submissions and Subscribers show. A form whose ``submission.destination`` is ``audience``
(the default) sends what people write to it here instead of to the workspace's content (services/audience.py); this lists those
submissions, newest first, with the submission protection's verdict and where each came from, and lets a person act on one.

Roles: reading and acting (mark handled, not spam / reopen, delete) are EDITOR and above, checked before anything is looked up. The
submitter's whole IP address is shown to ADMIN and above; an EDITOR sees it with its host part hidden.

An action is an ordinary status change of the submission's entry (``entry_updated`` and the status events fire as for any change in
the entry editor): handled is ``archived``, not spam / reopen is ``inbox``, delete is the Trash (restorable from the Trash page).

Subscribers (``/subscribers``) are the entries of the signup forms (``submission.kind: signup``), listed with the mailing list's word
for their status: pending, confirmed, unsubscribed, problem (services/audience.py). The same roles and IP rule apply. There is no
subscribe or unsubscribe here: those stay with the mailing-list integration's workflows and webhook; a person can open the entry or
delete it (to the Trash).
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID4

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_role
from marvin.schemas.group.audience import (
    AudienceCan,
    AudienceSubmission,
    AudienceSubmissionList,
    AudienceSubmissionResult,
    AudienceSubscriber,
    AudienceSubscriberCounts,
    AudienceSubscriberDetail,
    AudienceSubscriberList,
    AudienceSubscriberResult,
    AudienceSummary,
    SubscriberStatus,
)
from marvin.services import audience
from marvin.services.entries import EntryService

router = APIRouter(prefix="/groups/audience")


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


@controller(router)
class AudienceController(BaseUserController):
    def _may(self, role: WorkspaceRole) -> bool:
        try:
            require_workspace_role(self.user, self.group_id, role)
        except HTTPException:
            return False
        return True

    def _gate(self) -> bool:
        """EDITOR and above (before any lookup); returns whether the caller sees whole IP addresses (ADMIN and above)."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        return self._may(WorkspaceRole.ADMIN)

    def _entries(self) -> EntryService:
        return EntryService(self.session, self.group_id, event_bus=self.event_bus, actor_id=self.user.id if self.user else None)

    def _one(self, submission_id: UUID4):
        found = audience.get(self.session, self.group_id, submission_id)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such submission.")
        return found

    def _result(self, submission_id: UUID4, full_ip: bool) -> AudienceSubmissionResult:
        entry, entry_type = self._one(submission_id)
        self.session.refresh(entry)
        return AudienceSubmissionResult(submission=AudienceSubmission(**audience.read(entry, entry_type, full_ip=full_ip)))

    @router.get("/summary", response_model=AudienceSummary, summary="What Audience needs to show: the forms with their new counts")
    def summary(self):
        """The Audience message forms (`submissions.forms`: name, icon, and `new` = inbox plus needs review), their total, and
        the signup forms with a count per subscriber status (`signups`: pending, confirmed, unsubscribed, problem, and `waiting` =
        pending + problem). Each part has `show` false until something feeds it, so the sidebar draws only what exists. EDITOR and
        above (a lower role gets 403 and no group)."""
        full_ip = self._gate()
        return AudienceSummary(**audience.summary(self.session, self.group_id), can=AudienceCan(act=True, full_ip=full_ip))

    @router.get("/submissions", response_model=AudienceSubmissionList, summary="List Audience submissions, newest first")
    def list_submissions(
        self,
        form: str | None = Query(None, description="One form, by its entry type's slug."),
        submission_state: list[Literal["new", "suspicious", "handled"]] | None = Query(
            None, alias="status", description="One or more of new (inbox), suspicious (needs review), handled (everything else but the Trash)."
        ),
        q: str | None = Query(None, max_length=200, description="Text to find in the title or any submitted value."),
        since: datetime | None = Query(None, description="Arrived at or after this time."),
        until: datetime | None = Query(None, description="Arrived at or before this time."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """The submissions of the message forms that send them to the Audience: every field with the form's labels, the
        protection's verdict (`verdict.flagged`, `reasons`) and the source (`source.ip` whole for ADMIN and above, masked for an
        EDITOR; user agent, referrer, repeats). `new` counts what is waiting for the form (or every form), whatever the other
        filters. EDITOR and above."""
        full_ip = self._gate()
        rows, total = audience.query(
            self.session,
            self.group_id,
            form=form,
            states=submission_state,
            text=q,
            since=_naive_utc(since),
            until=_naive_utc(until),
            limit=limit,
            offset=offset,
        )
        counts = audience.summary(self.session, self.group_id)["submissions"]
        waiting = {f["slug"]: f["new"] for f in counts["forms"]}
        return AudienceSubmissionList(
            items=[AudienceSubmission(**audience.read(e, t, full_ip=full_ip, new=waiting.get(t.slug, 0))) for e, t in rows],
            total=total,
            limit=limit,
            offset=offset,
            new=waiting.get(form, 0) if form is not None else counts["new"],
        )

    @router.get("/submissions/{submission_id}", response_model=AudienceSubmissionResult, summary="Get one Audience submission")
    def get_submission(self, submission_id: UUID4):
        """One submission, as the list returns it. 404 for an entry that isn't one of the Audience message forms'. EDITOR and above."""
        full_ip = self._gate()
        return self._result(submission_id, full_ip)

    @router.post("/submissions/{submission_id}/handled", response_model=AudienceSubmissionResult, summary="Mark a submission handled")
    def mark_handled(self, submission_id: UUID4):
        """Archive the submission's entry: it leaves New and Suspicious and shows as Handled. EDITOR and above."""
        full_ip = self._gate()
        entry, _ = self._one(submission_id)
        if entry.status != "archived":
            self._entries().set_status(entry.id, "archived")
        return self._result(submission_id, full_ip)

    @router.post("/submissions/{submission_id}/reopen", response_model=AudienceSubmissionResult, summary="Not spam / reopen")
    def reopen(self, submission_id: UUID4):
        """Put the submission back in the inbox: a suspicious one is cleared (not spam), a handled one is open again. EDITOR and above."""
        full_ip = self._gate()
        entry, _ = self._one(submission_id)
        if entry.status != "inbox":
            self._entries().set_status(entry.id, "inbox")
        return self._result(submission_id, full_ip)

    @router.delete("/submissions/{submission_id}", response_model=AudienceSubmissionResult, summary="Delete a submission (to the Trash)")
    def delete_submission(self, submission_id: UUID4):
        """Move the submission's entry to the Trash, where it can be restored or deleted forever. EDITOR and above."""
        self._gate()
        entry, _ = self._one(submission_id)
        self._entries().trash(entry.id)
        return AudienceSubmissionResult(submission=None)

    # ── Subscribers ──────────────────────────────────────────────────────────────────────────────────────────────────

    def _subscriber(self, subscriber_id: UUID4):
        found = audience.get_subscriber(self.session, self.group_id, subscriber_id)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such subscriber.")
        return found

    @router.get("/subscribers", response_model=AudienceSubscriberList, summary="List subscribers (newsletter signups), newest first")
    def list_subscribers(
        self,
        form: str | None = Query(None, description="One signup form, by its entry type's slug (when there are several)."),
        subscriber_status: list[SubscriberStatus] | None = Query(
            None,
            alias="status",
            description="One or more of pending (inbox), confirmed (published), unsubscribed (archived), problem (needs review).",
        ),
        q: str | None = Query(None, max_length=200, description="Text to find in the email, the name or the title."),
        since: datetime | None = Query(None, description="Signed up at or after this time."),
        until: datetime | None = Query(None, description="Signed up at or before this time."),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """The entries of the signup forms (`submission.kind: signup`), newest first: email, name when the form has one, when they
        signed up, the status as the mailing list says it, and the review reason of a problem. `counts` is per status for the form (or
        every form), whatever the other filters. `integrations` lists the enabled integrations that act on the signups (subscribing
        and unsubscribing are theirs). EDITOR and above."""
        full_ip = self._gate()
        rows, total = audience.query_subscribers(
            self.session,
            self.group_id,
            form=form,
            statuses=subscriber_status,
            text=q,
            since=_naive_utc(since),
            until=_naive_utc(until),
            limit=limit,
            offset=offset,
        )
        overview = audience.signups_summary(self.session, self.group_id, with_integrations=True)
        waiting = {f["slug"]: f["new"] for f in overview["forms"]}
        if form is not None:
            totals, _ = audience.subscriber_counts(
                self.session, self.group_id, [t.id for t in audience.signup_forms(self.session, self.group_id) if t.slug == form]
            )
        else:
            totals = {k: overview[k] for k in audience.SUBSCRIBER_STATUSES}
        by_hand = audience.archived_in_marvin(self.session, self.group_id, [e.id for e, _ in rows if e.status == "archived"])
        return AudienceSubscriberList(
            items=[AudienceSubscriber(**audience.subscriber_row(e, t, waiting.get(t.slug, 0), by_hand=e.id in by_hand)) for e, t in rows],
            total=total,
            limit=limit,
            offset=offset,
            counts=AudienceSubscriberCounts(**totals),
            forms=overview["forms"],
            integrations=overview["integrations"],
            can=AudienceCan(act=True, full_ip=full_ip),
        )

    @router.get("/subscribers/{subscriber_id}", response_model=AudienceSubscriberResult, summary="Get one subscriber")
    def get_subscriber(self, subscriber_id: UUID4):
        """One subscriber in full: every submitted field, where the signup came from (the IP whole for ADMIN and above, masked for an
        EDITOR) and its status history. 404 for an entry that isn't a signup form's. EDITOR and above."""
        full_ip = self._gate()
        entry, entry_type = self._subscriber(subscriber_id)
        return AudienceSubscriberResult(
            subscriber=AudienceSubscriberDetail(**audience.subscriber_detail(self.session, entry, entry_type, full_ip=full_ip))
        )

    @router.delete("/subscribers/{subscriber_id}", response_model=AudienceSubscriberResult, summary="Delete a subscriber (to the Trash)")
    def delete_subscriber(self, subscriber_id: UUID4):
        """Move the signup's entry to the Trash, where it can be restored or deleted forever. It does not unsubscribe the reader from
        the mailing list: that stays the integration's. EDITOR and above."""
        self._gate()
        entry, _ = self._subscriber(subscriber_id)
        self._entries().trash(entry.id)
        return AudienceSubscriberResult(subscriber=None)
