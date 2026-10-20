"""
Entry snapshots: keep a version of an entry and put it back.

AUTHOR and above, on entries the caller may change (an AUTHOR: their own, until approved or published — the same rule as
editing). A snapshot holds the entry's content, so there is no read-only door. Capturing never changes the entry; restoring
goes through the entry service, so the normal events fire. `status` is restored only when asked for, and never into or out
of the Trash. An entry keeps its latest 20 snapshots (services/snapshots.py).
"""

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import UUID4

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import editable_entry
from marvin.schemas.platform.entry_snapshots import EntrySnapshotCreate, EntrySnapshotDiff, EntrySnapshotRead, EntrySnapshotRestore
from marvin.services import snapshots
from marvin.services.entry_privacy import can_see_full_ip

router = APIRouter(prefix="/entries/{entry_id}/snapshots")


@controller(router)
class EntrySnapshotsController(BaseUserController):
    def _entry(self, entry_id: UUID4, new_status: str | None = None):
        return editable_entry(self.user, self.group_id, self.repos, entry_id, new_status)

    def _snapshot(self, entry_id: UUID4, snapshot_id: UUID4):
        row = snapshots.get(self.session, self.group_id, snapshot_id, entry_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found.")
        return row

    @router.get("", response_model=list[EntrySnapshotRead], summary="List an entry's snapshots")
    def list_snapshots(self, entry_id: UUID4):
        """The entry's snapshots, newest first (what each holds in brief). AUTHOR and above."""
        self._entry(entry_id)
        return [EntrySnapshotRead(**snapshots.describe(r)) for r in snapshots.list_for(self.session, self.group_id, entry_id)]

    @router.post("", response_model=EntrySnapshotRead, status_code=status.HTTP_201_CREATED, summary="Keep a snapshot of an entry")
    def capture_snapshot(self, entry_id: UUID4, body: EntrySnapshotCreate | None = None):
        """Keep the entry as it is now. When its latest snapshot is already identical, that one is returned
        (`created: false`). The oldest beyond 20 are dropped."""
        self._entry(entry_id)
        try:
            row, created = snapshots.capture(
                self.session, self.group_id, entry_id, label=(body.label if body else ""), user_id=self.user.id, source="api"
            )
        except snapshots.SnapshotError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        return EntrySnapshotRead(**snapshots.describe(row), created=created)

    @router.get("/{snapshot_id}/diff", response_model=EntrySnapshotDiff, summary="What restoring a snapshot would change")
    def diff_snapshot(self, entry_id: UUID4, snapshot_id: UUID4, parts: list[str] | None = Query(None)):
        """The change a restore of these parts (default content, collections, assets) would make — nothing is written."""
        self._entry(entry_id)
        row = self._snapshot(entry_id, snapshot_id)
        try:
            return EntrySnapshotDiff(
                **snapshots.public(
                    snapshots.plan(self.session, self.group_id, row, snapshots.clean_parts(parts), can_see_full_ip(self.user, self.group_id))
                )
            )
        except snapshots.SnapshotError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    @router.post("/{snapshot_id}/restore", response_model=EntrySnapshotDiff, summary="Put a snapshot back")
    def restore_snapshot(self, entry_id: UUID4, snapshot_id: UUID4, body: EntrySnapshotRestore | None = None):
        """Put these parts of the snapshot back on the entry (default content, collections, assets; `status` only when
        listed, and through the publish gate). Fires the normal events. 409 for an entry in the Trash, 422 when the entry's
        type or the publish gate refuses what the snapshot holds."""
        row = self._snapshot(entry_id, snapshot_id)
        parts = snapshots.clean_parts(body.parts if body else None)
        self._entry(entry_id, (row.snapshot_json or {}).get("status") if "status" in parts else None)
        try:
            done = snapshots.restore(
                self.session, self.group_id, row, parts, actor_id=self.user.id, full_ip=can_see_full_ip(self.user, self.group_id)
            )
        except snapshots.SnapshotError as e:
            code = status.HTTP_409_CONFLICT if "Trash" in str(e) else status.HTTP_422_UNPROCESSABLE_ENTITY
            raise HTTPException(status_code=code, detail=str(e)) from e
        return EntrySnapshotDiff(**done)

    @router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a snapshot")
    def delete_snapshot(self, entry_id: UUID4, snapshot_id: UUID4):
        """Remove one snapshot. The entry itself is untouched."""
        self._entry(entry_id)
        if not snapshots.remove(self.session, self.group_id, entry_id, snapshot_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
