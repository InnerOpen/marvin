"""Entry routes."""

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import UUID4

from marvin.db.models.platform import Entries, EntryCollections, EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import (
    editable_entry,
    require_can_create_entry,
    require_can_edit_entry,
    require_playbook_rules,
    require_workspace_admin,
    require_workspace_role,
)
from marvin.routes._base.paging import paged
from marvin.schemas.platform import (
    CollectionRead,
    EntriesApplyTemplateRequest,
    EntriesFromTemplateRequest,
    EntryBulkDeleteJob,
    EntryBulkDeletePreview,
    EntryBulkDeleteRequest,
    EntryCreate,
    EntryQueryRequest,
    EntryQueryResult,
    EntryRead,
    EntryTemplateResult,
    EntryUpdate,
)
from marvin.services.entries import EntryService, trash
from marvin.services.entries.entry_service import TRASHED, count_by_status, count_by_type, restore_status
from marvin.services.entry_listing import only_listed
from marvin.services.entry_privacy import can_see_full_ip, entries_for, entry_for, keep_recorded_ip
from marvin.services.entry_urls import entry_url, site_base_url

router = APIRouter(prefix="/entries")


# One page of a structured search at most (the Entries page asks for this many).
QUERY_MAX_ROWS = 500


def with_read_relations(session, rows: list) -> list:
    """``rows`` (entry rows loaded bare, as the query engine loads them) with what ``EntryRead`` reads loaded onto them up
    front: a few queries for the whole page instead of several per entry."""
    if rows:
        session.query(Entries).filter(Entries.id.in_([r.id for r in rows])).options(*EntryRead.loader_options()).all()
    return rows


@controller(router)
class EntriesController(BaseUserController):
    """Authenticated CRUD routes for entries. Entry mutation + its events live in EntryService;
    this controller owns the HTTP concerns (auth, 404s, response shape).

    Any member reads. Writes follow the content roles: EDITORs and above change any entry; an AUTHOR
    creates entries and changes their own until they are approved or published (see
    `require_can_edit_entry`); a VIEWER gets a 403.

    Delete moves an entry to the Trash (reversible); only a trashed entry can be deleted forever, and
    only an ADMIN/OWNER empties the whole Trash (services/entries/trash.py). Trashed entries are left
    out of the list; fetching one by id still works and shows its status.

    A form submission's IP address (`metadataJson.submission.ip_address`) is whole for an ADMIN and above and masked for everyone
    else, on every entry this controller returns (services/entry_privacy.py); saving an entry never overwrites the stored address
    with a masked one."""

    def _full_ip(self) -> bool:
        return can_see_full_ip(self.user, self.group_id)

    def _seen(self, entry):
        """An entry as this caller may see it (the submitter's IP masked below ADMIN)."""
        return entry_for(entry, self._full_ip())

    def _entries(self) -> EntryService:
        """The entry domain service, wired with this request's actor + event bus."""
        return EntryService(
            self.session,
            self.group_id,
            event_bus=self.event_bus,
            actor_id=self.user.id if self.user else None,
        )

    @router.get("", response_model=list[EntryRead], summary="List Entries")
    def list_entries(
        self,
        response: Response,
        limit: int | None = Query(None, ge=1, description="At most this many (default: all of them)"),
        offset: int = Query(0, ge=0, description="Skip this many first (with `limit`, one page)"),
        entry_type_id: UUID4 | None = Query(None, description="Only entries of this type"),
    ) -> list[EntryRead]:
        """Every entry but those in the Trash (the Trash collection lists those) and those of an internal entry type
        (`capabilities.listed: false`, e.g. the Social auto-reply rules: their pages list them; fetch one by id, or name
        the type in `entry_type_id`), newest first. `limit`/`offset` page it and `entry_type_id` narrows it; the
        `X-Total-Count` header says how many there are in all. For conditions, other orders and the total in the body,
        use `POST /entries/query`."""
        query = self.session.query(Entries).filter(Entries.group_id == self.group_id, Entries.status != TRASHED)
        # Naming a type lists it, internal or not (as the entry query does: the pages that own an internal type reach it so).
        query = query.filter(Entries.entry_type_id == entry_type_id) if entry_type_id is not None else only_listed(self.session, self.group_id, query)
        page = paged(query.order_by(Entries.created_at.desc(), Entries.id.desc()), response, limit, offset)
        rows = page.options(*EntryRead.loader_options()).all()
        return entries_for([EntryRead.model_validate(e) for e in rows], self._full_ip())

    @router.post("", response_model=EntryRead, status_code=status.HTTP_201_CREATED, summary="Create Entry")
    def create_entry(self, data: EntryCreate) -> EntryRead:
        require_can_create_entry(self.user, self.group_id, data.status, data.publish_at)
        require_playbook_rules(self.session, self.user, self.group_id, data.entry_type_id, None, data.status, data.publish_at)
        data_dict = data.model_dump()
        data_dict["created_by"] = self.user.id  # inject the authenticated author
        return self._seen(self._entries().create(data_dict))

    @router.post("/query", response_model=EntryQueryResult, summary="Search entries by conditions")
    def query_entries(self, body: EntryQueryRequest) -> EntryQueryResult:
        """A structured search: the conditions in `spec`, all ANDed, through the same engine the assistants'
        find_entries uses (so the Entries page and the AI find the same entries). Read-only; the Trash is left out
        unless `status` asks for it. Declared before `/{item_id}`."""
        from marvin.services.entries.query import run as run_entry_query

        limit = max(1, min(body.limit, QUERY_MAX_ROWS))
        result = run_entry_query(self.session, self.group_id, body.spec, limit=limit, offset=max(0, body.offset))
        if result.note:
            return EntryQueryResult(entries=[], total=0, note=result.note, unknown_ops=list(result.unknown_ops or []))
        rows = with_read_relations(self.session, result.rows)
        return EntryQueryResult(entries=entries_for([EntryRead.model_validate(e) for e in rows], self._full_ip()), total=result.total)

    def _rank(self) -> int:
        """The caller's workspace rank (WORKSPACE_ROLE_HIERARCHY; a role-bypassing platform admin counts as OWNER)."""
        from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
        from marvin.routes._base.checks import _bypasses_workspace_roles

        return 5 if _bypasses_workspace_roles(self.user) else WORKSPACE_ROLE_HIERARCHY.get(self.user.get_workspace_role(self.group_id), 0)

    def _bulk_checked(self, spec: dict, mode: str) -> dict:
        """403 when the caller may not delete what `spec` selects in `mode`; 400 for a spec a bulk delete refuses. Returns
        the preview."""
        from marvin.services.entries import bulk_delete

        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)  # below that, nothing more to ask
        try:
            refused = bulk_delete.refusal(self.session, self.group_id, spec, mode, role=self._rank(), user_id=self.user.id)
            if refused:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refused)
            return bulk_delete.preview(self.session, self.group_id, spec, mode=mode)
        except bulk_delete.BulkDeleteError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @router.post("/bulk-delete/preview", response_model=EntryBulkDeletePreview, summary="Preview a bulk delete")
    def preview_bulk_delete(self, body: EntryBulkDeleteRequest) -> dict:
        """What a bulk delete of the entries `spec` selects would remove now, counted by entry type. Changes nothing. Run it
        first: the delete takes its `total` back as `confirmTotal`. 403 when the caller could not do the delete (permanent:
        ADMIN/OWNER; trash: whoever may delete those entries one by one). Declared before `/{item_id}`."""
        return self._bulk_checked(body.spec, body.mode)

    @router.post("/bulk-delete", response_model=EntryBulkDeleteJob, status_code=status.HTTP_202_ACCEPTED, summary="Delete entries in bulk")
    def bulk_delete_entries(self, body: EntryBulkDeleteRequest) -> dict:
        """Move the entries `spec` selects to the Trash (`mode` trash: restorable; each slug is moved aside so new entries
        can use it, and a restore gives it back while it is still free) or delete them for good (`mode` permanent,
        ADMIN/OWNER). Assets and resources are never deleted. `confirmTotal` must be the preview's `total`: when the
        selection no longer counts that many it is a 409 with the fresh preview in `detail`, and nothing is done.

        It runs in the background, 500 entries per transaction, and answers at once with the job; `GET
        /entries/bulk-delete` says how far it is. One at a time per workspace (409 while one runs). The entries send no
        `entry_trashed` / `entry_deleted` each: one `entries_bulk_deleted` says what went. Declared before `/{item_id}`."""
        from marvin.services.entries import bulk_delete

        found = self._bulk_checked(body.spec, body.mode)
        if body.confirm_total is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmTotal is required: the total the preview counted.")
        if body.confirm_total != found["total"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": str(bulk_delete.BulkDeleteMismatch(body.confirm_total, found)), "preview": found},
            )
        if not found["total"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The selection is empty: there is nothing to delete.")
        job = bulk_delete.start_job(
            self.group_id, body.spec, mode=body.mode, total=found["total"], actor_id=self.user.id, description=body.description
        )
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A bulk delete is already running in this workspace: wait for it to finish."
            )
        return job

    @router.get("/bulk-delete", response_model=EntryBulkDeleteJob | None, summary="Where a bulk delete stands")
    def bulk_delete_status(self) -> dict | None:
        """The workspace's bulk delete in progress (`done` of `total`), or its last one since the server started; null
        when there was none. A restart forgets this, never what was deleted: the `entries_bulk_deleted` event is the
        record. Declared before `/{item_id}`."""
        from marvin.services.entries import bulk_delete

        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        return bulk_delete.job_status(self.group_id)

    def _template_done(self, plan, preview: bool) -> dict:
        """Check the caller may do what `plan` says (as for one entry: AUTHOR makes entries in the template's status and fills
        their own drafts; EDITOR fills any), then answer the preview or do it. 400 for a row with an error."""
        from marvin.services.entries import templates

        if not preview:
            if any(r.action == "create" for r in plan.rows):
                require_can_create_entry(self.user, self.group_id, plan.template.status)
            for r in plan.rows:
                if r.action == "fill":
                    require_can_edit_entry(self.user, self.group_id, r.entry)
        if preview:
            return templates.describe(plan)
        try:
            return templates.execute(self.session, self.group_id, plan, actor_id=self.user.id, event_bus=self.event_bus)
        except templates.TemplateError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @router.post("/from-template", response_model=EntryTemplateResult, summary="Make entries from pictures with a template")
    def entries_from_template(self, body: EntriesFromTemplateRequest) -> dict:
        """One entry per picture, from one of the entry type's templates (its settings list them). `preview` (the default)
        answers one row per picture and changes nothing: the title, the values that would be set and the picture. With
        `preview: false` the entries are made, in the template's status (Inbox by default), each with the picture in the
        template's asset field and attached with its role at position 0. A picture an entry of this type already has fills
        that entry instead (only empty values, unless `replace`). Nothing is made while any row has an `error`. At most
        200 pictures; no `entry_created` each: one `entry_template_applied`. A template with a picture preset gives each
        entry the treated picture (in its treated role and asset field; the original is kept as its source): the one made
        before, or the original until the treated one is made in the background (`treatment_job`). `mark_unnamed` tags
        an entry titled only by its file name (IMG_4491) "Needs a name". Declared before `/{item_id}`."""
        from marvin.services.entries import templates

        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        try:
            plan = templates.plan_from_assets(
                self.session,
                self.group_id,
                body.entry_type,
                body.template,
                body.assets,
                replace=body.replace,
                mark_unnamed=body.mark_unnamed,
                titles=body.titles,
            )
        except templates.TemplateNotFound as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        except templates.TemplateError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        return self._template_done(plan, body.preview)

    @router.post("/apply-template", response_model=EntryTemplateResult, summary="Fill entries with a template")
    def apply_template(self, body: EntriesApplyTemplateRequest) -> dict:
        """Fill existing entries of the template's type with it: only what is empty unless `replace` (tags and collections
        are added; the status is never changed). `preview` (the default) answers one row per entry and changes nothing.
        Approved, published and archived entries and those in the Trash are left alone. An AUTHOR fills only their own
        drafts. At most 200 entries; no `entry_updated` each: one `entry_template_applied`. Declared before `/{item_id}`."""
        from marvin.services.entries import templates

        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        try:
            plan = templates.plan_for_entries(self.session, self.group_id, body.entry_type, body.template, body.entries, replace=body.replace)
        except templates.TemplateNotFound as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        except templates.TemplateError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        return self._template_done(plan, body.preview)

    @router.get("/counts", summary="Entry counts by status")
    def entry_counts(self) -> dict[str, int]:
        """`{inbox, draft, …, total}` for this workspace — what the sidebar badge reads (entries of an internal type are
        not counted). Declared before `/{item_id}`."""
        return count_by_status(self.session, self.group_id)

    @router.get("/counts/by-type", summary="Entry counts by entry type")
    def entry_counts_by_type(self) -> dict[str, int]:
        """`{entry_type_id: n}`: how many entries each type has, counted as the list counts them (not those in the Trash,
        nor those of an internal type); a type with none is left out. Declared before `/{item_id}`."""
        return count_by_type(self.session, self.group_id)

    @router.get("/trash", summary="Trash summary")
    def trash_summary(self) -> dict:
        """How many entries are in the Trash and how long it keeps them (`effective_days`, 0 = until
        emptied; the platform default and this workspace's override beside it). Declared before `/{item_id}`."""
        return {
            "count": len(trash.trashed_ids(self.session, self.group_id)),
            **trash.auto_empty_status(self.session, self.group_id),
        }

    @router.post("/trash/empty", summary="Empty the Trash")
    def empty_trash(self) -> dict:
        """Delete every entry in the Trash forever (ADMIN/OWNER). Each goes through the normal delete, so
        `entry_deleted` fires per entry. Returns `{deleted: n}`."""
        require_workspace_admin(self.user, self.group_id)
        deleted = trash.empty_trash(self.session, self.group_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "deleted": deleted}

    @router.get("/{item_id}", response_model=EntryRead, summary="Get Entry")
    def get_entry(self, item_id: UUID4) -> EntryRead:
        entry = self.repos.entries.get_one(item_id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        entry.page_url = entry_url(
            entry,
            absolute=True,
            site_url=site_base_url(self.session, self.group_id),
            entry_type=self.session.get(EntryTypes, entry.entry_type_id),
        )
        return entry_for(entry, can_see_full_ip(self.user, self.group_id))

    @router.post("/{item_id}/apply-suggestion", response_model=EntryRead, summary="Apply AI Suggestion")
    def apply_suggestion(self, item_id: UUID4) -> EntryRead:
        """Apply the entry's staged AI suggestion (suggestion_json) and clear it.

        This is the human-approval half of write-back: an AI op stages proposed changes under
        suggestion_json (when approval_mode doesn't auto-apply); this endpoint commits them.
        """
        editable_entry(self.user, self.group_id, self.repos, item_id)
        return self._seen(self._entries().apply_suggestion(item_id))

    @router.post("/{item_id}/reject-suggestion", response_model=EntryRead, summary="Reject AI Suggestion")
    def reject_suggestion(self, item_id: UUID4) -> EntryRead:
        """Discard the entry's staged AI suggestion without applying it."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        return self._seen(self.repos.entries.clear_suggestion(item_id))

    @router.post("/{item_id}/suggested-assets/{asset_id}/approve", response_model=EntryRead, summary="Approve Suggested Asset")
    def approve_suggested_asset(self, item_id: UUID4, asset_id: UUID4) -> EntryRead:
        """Approve a pending AI-generated asset: clear the `suggested` flag on the entry↔asset link
        so it becomes a normal confirmed asset (and reaches published output)."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        entry = self._entries().approve_suggested_asset(item_id, asset_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No suggested asset found for this entry.")
        return self._seen(entry)

    @router.post("/{item_id}/suggested-assets/{asset_id}/reject", response_model=EntryRead, summary="Reject Suggested Asset")
    def reject_suggested_asset(self, item_id: UUID4, asset_id: UUID4) -> EntryRead:
        """Reject a pending AI-generated asset: unlink it, and delete the asset if it's now orphaned."""
        editable_entry(self.user, self.group_id, self.repos, item_id)
        entry = self._entries().reject_suggested_asset(item_id, asset_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No suggested asset found for this entry.")
        return self._seen(entry)

    @router.patch("/{item_id}", response_model=EntryRead, summary="Update Entry")
    def update_entry(self, item_id: UUID4, data: EntryUpdate) -> EntryRead:
        # The service emits entry_updated + any status-transition events (published/unpublished/
        # archived/restored), in that order.
        current = editable_entry(self.user, self.group_id, self.repos, item_id, data.status, data.publish_at)
        if data.entry_type_id is not None and data.entry_type_id != current.entry_type_id:  # moved into the Playbook type and published at once
            require_playbook_rules(self.session, self.user, self.group_id, data.entry_type_id, None, data.status, data.publish_at)
        # The Trash has its own doors: DELETE puts an entry in, POST /restore takes it out. A trashed
        # entry is read-only until restored.
        if current.status == TRASHED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This entry is in the Trash. Restore it before editing it.")
        if data.status == TRASHED:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Move an entry to the Trash with DELETE /entries/{id}.")
        if data.metadata_json is not None and not self._full_ip():
            data.metadata_json = keep_recorded_ip(current.metadata_json, data.metadata_json)  # what they read was masked
        entry = self._entries().update(item_id, data)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return self._seen(entry)

    @router.delete("/{item_id}", summary="Move Entry to Trash (or delete a trashed entry forever)")
    def delete_entry(self, item_id: UUID4, permanent: bool = False) -> dict:
        """Move the entry to the Trash (`entry_trashed`; restorable). With `permanent=true`, delete an entry
        that is already in the Trash forever (`entry_deleted`); any other entry gets a 409."""
        entry = editable_entry(self.user, self.group_id, self.repos, item_id)
        if permanent:
            if entry.status != TRASHED:
                detail = "Only an entry in the Trash can be deleted forever. Move it to the Trash first."
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
            if not trash.delete_forever(self.session, self.group_id, [item_id], actor_id=self.user.id, event_bus=self.event_bus):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
            return {"status": "ok", "message": "Entry deleted forever", "deleted": True}
        if self._entries().trash(item_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return {"status": "ok", "message": "Entry moved to the Trash", "trashed": True}

    @router.post("/{item_id}/restore", response_model=EntryRead, summary="Restore Entry from Trash")
    def restore_entry(self, item_id: UUID4) -> EntryRead:
        """Take an entry out of the Trash, back to the status it had — a published entry comes back as a
        draft, so a restore never puts anything on the site by itself. Emits `entry_restored`."""
        entry = editable_entry(self.user, self.group_id, self.repos, item_id)
        if entry.status != TRASHED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This entry is not in the Trash.")
        require_can_edit_entry(self.user, self.group_id, entry, restore_status(entry))  # e.g. an AUTHOR restoring to Approved
        restored = self._entries().restore_from_trash(item_id)
        if restored is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
        return self._seen(restored)

    @router.get("/{entry_id}/collections", response_model=list[CollectionRead], summary="List Entry Collections")
    def list_entry_collections(self, entry_id: UUID4) -> list[CollectionRead]:
        """Get all collections this entry belongs to."""
        entry = self.repos.entries.get_one(entry_id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")

        # Query collections via junction table
        collection_ids = self.session.query(EntryCollections.collection_id).filter(EntryCollections.entry_id == entry_id).all()
        collection_ids = [cid[0] for cid in collection_ids]

        if not collection_ids:
            return []

        return [collection for collection in self.repos.collections.get_all() if collection.id in collection_ids]

    @router.post("/{entry_id}/collections/{collection_id}", status_code=status.HTTP_201_CREATED, summary="Add Entry to Collection")
    def add_entry_to_collection(self, entry_id: UUID4, collection_id: UUID4) -> dict:
        """Add an entry to a collection (via EntryService — emits `entry_added_to_collection`). Gated as
        an edit of the entry: an entry PATCH can set its collections too."""
        editable_entry(self.user, self.group_id, self.repos, entry_id)
        result = self._entries().add_to_collection(entry_id, collection_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry or collection not found in this workspace.")
        if result == "exists":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is already in this collection.")
        return {"message": "Entry added to collection successfully"}

    @router.delete("/{entry_id}/collections/{collection_id}", summary="Remove Entry from Collection")
    def remove_entry_from_collection(self, entry_id: UUID4, collection_id: UUID4) -> dict:
        """Remove an entry from a collection (via EntryService — emits `entry_removed_from_collection`)."""
        editable_entry(self.user, self.group_id, self.repos, entry_id)
        result = self._entries().remove_from_collection(entry_id, collection_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry or collection not found in this workspace.")
        if result == "absent":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry is not in this collection.")
        return {"status": "ok", "message": "Entry removed from collection successfully"}
