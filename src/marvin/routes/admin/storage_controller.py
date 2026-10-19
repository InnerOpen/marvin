"""Asset storage (admin): which provider new uploads go to, how many files live on each, and each
workspace's key prefix and own public domain for remote files.

Switching is safe at any time and in either direction: it only decides where new uploads are stored.
Existing files keep serving from the provider their row names until `scripts/storage_migrate.py`
moves them. See services/storage/admin.py.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.storage import StorageCheckResult, StorageSettingsRead, StorageSettingsUpdate, StorageWorkspaceUpdate
from marvin.schemas.admin.workspace_deletion import DeletedWorkspaceStorageList, DeletedWorkspaceStorageRead
from marvin.schemas.group.storage_settings import WorkspaceBucketRead, WorkspaceStoragePolicyRead, WorkspaceStoragePolicyUpdate
from marvin.services.event_bus_service.event_types import (
    EventOperation,
    EventPlatformSettingsChangedData,
    EventStorageProviderChangedData,
    EventStoragePublicDomainChangedData,
    EventTypes,
)
from marvin.services.storage.admin import (
    InvalidPublicBaseURLError,
    UnavailableProviderError,
    set_upload_provider,
    set_workspace_public_base_url,
    storage_status,
    test_provider,
)

router = APIRouter(prefix="/storage")


@controller(router)
class AdminStorageController(BaseAdminController):
    def _read(self) -> StorageSettingsRead:
        status_ = storage_status(self.session)
        target = status_.target
        warning = None
        if target.error:
            warning = (
                f"New uploads should go to '{target.chosen}', but it is unavailable ({target.error}). "
                f"They go to '{target.effective}' (STORAGE_PROVIDER) until it is fixed or another provider is chosen."
            )
        return StorageSettingsRead(
            env_default=target.env_default,
            upload_provider=target.chosen,
            effective_provider=target.effective,
            warning=warning,
            providers=[asdict(p) for p in status_.providers],
            workspaces=[asdict(w) for w in status_.workspaces],
            workspace_settings=[asdict(w) for w in status_.workspace_settings],
            remote_public_base_url=status_.remote_public_base_url,
            backup_targets=[asdict(t) for t in status_.backup_targets],
        )

    @router.get("", response_model=StorageSettingsRead, summary="Admin: Get Asset Storage Settings")
    def get_storage(self) -> StorageSettingsRead:
        """Where new uploads go, the providers that could take them, and the files stored on each."""
        return self._read()

    @router.put("", response_model=StorageSettingsRead, summary="Admin: Choose Where New Uploads Are Stored")
    def update_storage(self, data: StorageSettingsUpdate) -> StorageSettingsRead:
        """Choose the provider for new uploads (null: follow STORAGE_PROVIDER). Only an installed,
        configured provider is accepted (422 otherwise). Existing files are not moved."""
        try:
            previous, chosen = set_upload_provider(self.session, data.upload_provider)
        except UnavailableProviderError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Can't store uploads there: {e}") from None
        result = self._read()
        if previous != chosen:
            self._announce(previous, chosen, result.effective_provider)
        return result

    @router.put("/workspaces/{workspace_id}", response_model=StorageSettingsRead, summary="Admin: Set a Workspace's Public Asset Domain")
    def update_workspace_storage(self, workspace_id: UUID4, data: StorageWorkspaceUpdate) -> StorageSettingsRead:
        """Serve a workspace's files on a remote provider (s3) from its own domain (null: the platform's,
        STORAGE_REMOTE_PUBLIC_URL). The domain must serve the same bucket (DNS work: see the "Assets on R2"
        runbook). Files on local disk keep the API host. 422 for a URL that isn't https://host[/path]."""
        try:
            name, previous, url = set_workspace_public_base_url(
                self.session, workspace_id, data.asset_public_base_url, allow_http=not self.settings.PRODUCTION
            )
        except LookupError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found") from None
        except InvalidPublicBaseURLError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Public asset domain {e}") from None
        self.session.commit()
        if previous != url:
            self._announce_domain(workspace_id, name, previous, url)
        return self._read()

    @router.get("/workspace-buckets", response_model=list[WorkspaceBucketRead], summary="Admin: List Workspaces' Own Buckets")
    def list_workspace_buckets(self) -> list[WorkspaceBucketRead]:
        """Every bucket a workspace connected for its own files: its status and last check, whether uploads go there,
        how many files are in it, and whether the workspace's bundles include them. These buckets aren't in the
        platform's asset backups."""
        from marvin.services.storage.workspace_admin import all_workspace_buckets

        return [WorkspaceBucketRead.model_validate(b) for b in all_workspace_buckets(self.session)]

    @router.get("/workspace-policy", response_model=WorkspaceStoragePolicyRead, summary="Admin: Get the Workspace Storage Policy")
    def get_workspace_policy(self) -> WorkspaceStoragePolicyRead:
        """Whether workspaces may keep their files in their own bucket, and which endpoints they may use."""
        from marvin.services.storage.workspace import policy

        pol = policy(self.session)
        return WorkspaceStoragePolicyRead(allowed=pol.allowed, endpoint_policy=pol.endpoint_policy)

    @router.put("/workspace-policy", response_model=WorkspaceStoragePolicyRead, summary="Admin: Set the Workspace Storage Policy")
    def update_workspace_policy(self, data: WorkspaceStoragePolicyUpdate) -> WorkspaceStoragePolicyRead:
        """Allow (or stop) workspaces keeping their files in their own bucket; `endpoint_policy` is `known` (R2, AWS
        S3, Backblaze B2), `public` (any public address) or `any`. Turned off, workspaces that opted in can't upload
        until it is back on or they switch to the platform's storage; their files keep serving."""
        from marvin.services.storage.workspace_admin import WorkspaceStorageError, save_policy

        try:
            stored, changes = save_policy(self.session, allowed=data.allowed, endpoint_policy=data.endpoint_policy)
        except WorkspaceStorageError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        if changes:
            name = getattr(self.user, "full_name", None) or self.user.username
            self.event_bus.dispatch(
                integration_id="storage_settings",
                group_id=None,  # a platform setting: no workspace
                event_type=EventTypes.platform_settings_changed,
                document_data=EventPlatformSettingsChangedData(
                    operation=EventOperation.update, setting="workspace_storage", changes=changes, changed_by_name=name
                ),
                message="; ".join(changes),
                user_id=self.user.id,
                entity_type="storage",
            )
        return WorkspaceStoragePolicyRead(allowed=stored["allowed"], endpoint_policy=stored["endpoint_policy"])

    # ── files of deleted workspaces ──────────────────────────────────────────

    def _deleted_row(self, row_id: UUID4):
        from marvin.db.models.platform.deleted_workspace_storage import DeletedWorkspaceStorageModel

        row = self.session.get(DeletedWorkspaceStorageModel, row_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such deleted-workspace storage record.")
        return row

    @staticmethod
    def _deleted_read(row) -> DeletedWorkspaceStorageRead:
        from marvin.services.storage import deleted_workspaces

        snapshot = row.connection
        reachable = True
        if row.location.startswith("ws:"):
            reachable = bool(snapshot) and not snapshot.get("keys_missing")
        return DeletedWorkspaceStorageRead(
            id=row.id,
            workspace_id=row.workspace_id,
            workspace_name=row.workspace_name,
            workspace_slug=row.workspace_slug,
            location=row.location,
            label=row.label,
            object_count=row.object_count,
            total_bytes=row.total_bytes,
            deleted_at=row.deleted_at,
            purge_after=deleted_workspaces.due_at(row),
            state=row.state,
            purged_objects=row.purged_objects,
            can_purge=reachable,
            last_error=row.last_error,
        )

    def _announce_deleted(self, row, what: str) -> None:
        name = getattr(self.user, "full_name", None) or self.user.username
        self.event_bus.dispatch(
            integration_id="storage_settings",
            group_id=None,  # a platform action: the workspace is gone
            event_type=EventTypes.platform_settings_changed,
            document_data=EventPlatformSettingsChangedData(
                operation=EventOperation.update,
                setting="deleted_workspace_storage",
                changes=[f"{what} the files of deleted workspace '{row.workspace_name}' on {row.label or row.location}"],
                changed_by_name=name,
            ),
            message=f"{what} the files of deleted workspace '{row.workspace_name}'",
            user_id=self.user.id,
            entity_type="storage",
        )

    @router.get("/deleted-workspaces", response_model=DeletedWorkspaceStorageList, summary="Admin: Files of Deleted Workspaces Awaiting a Purge")
    def list_deleted_workspaces(self) -> DeletedWorkspaceStorageList:
        """Where the files of deleted workspaces are: each is purged 30 days after the delete by the daily task, unless
        kept. Purged records are not listed."""
        from sqlalchemy import select

        from marvin.db.models.platform.deleted_workspace_storage import STATE_PURGED, DeletedWorkspaceStorageModel
        from marvin.services.storage import deleted_workspaces

        rows = self.session.execute(
            select(DeletedWorkspaceStorageModel)
            .where(DeletedWorkspaceStorageModel.state != STATE_PURGED)
            .order_by(DeletedWorkspaceStorageModel.deleted_at, DeletedWorkspaceStorageModel.workspace_name)
        ).scalars()
        return DeletedWorkspaceStorageList(items=[self._deleted_read(r) for r in rows], grace_days=deleted_workspaces.GRACE.days)

    @router.post(
        "/deleted-workspaces/{record_id}/purge", response_model=DeletedWorkspaceStorageRead, summary="Admin: Purge a Deleted Workspace's Files Now"
    )
    def purge_deleted_workspace(self, record_id: UUID4) -> DeletedWorkspaceStorageRead:
        """Delete the recorded files now, without waiting out the grace period. They can't be recovered."""
        from marvin.services.storage import deleted_workspaces

        row = self._deleted_row(record_id)
        if row.state == "kept":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="These files were kept. They are not purged.")
        try:
            deleted_workspaces.purge(self.session, row)
        except deleted_workspaces.PurgeError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(e)) from None
        self._announce_deleted(row, "Purged")
        return self._deleted_read(row)

    @router.post(
        "/deleted-workspaces/{record_id}/keep", response_model=DeletedWorkspaceStorageRead, summary="Admin: Keep a Deleted Workspace's Files"
    )
    def keep_deleted_workspace(self, record_id: UUID4) -> DeletedWorkspaceStorageRead:
        """Never purge these files: the daily task skips them, and they stay in storage as they are."""
        from marvin.services.storage import deleted_workspaces

        row = self._deleted_row(record_id)
        if row.state == "purged":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="These files were already purged.")
        deleted_workspaces.keep(self.session, row)
        self._announce_deleted(row, "Kept")
        return self._deleted_read(row)

    @router.post("/providers/{slug}/test", response_model=StorageCheckResult, summary="Admin: Test a Storage Provider's Connection")
    def test_provider_connection(self, slug: str) -> StorageCheckResult:
        """Test connection: list, put, get and delete a tiny object under `_marvin-healthcheck/` through the
        provider as this backend builds it (its settings come from the backend's environment), timing each
        step. The object is deleted whatever happens. Errors come back as plain messages (a revoked key, a
        bucket the key can't reach, a missing bucket, DNS or timeouts), never as a failed request. 404 for a
        provider that isn't installed. Backup targets can't be tested from here (the backend doesn't have
        their credentials): run `python -m marvin.scripts.backup test` as a Job (offsite-backup runbook)."""
        try:
            result = test_provider(slug)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from None
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"Storage: connection test of {slug!r} by {name}: {'ok' if result.ok else 'FAILED'} " + "; ".join(result.lines()))
        return StorageCheckResult(provider=slug, **result.as_dict())

    def _announce_domain(self, workspace_id, workspace: str, previous: str | None, url: str | None) -> None:
        """storage_public_domain_changed (platform scope, always audited), under the workspace it serves."""
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(
            f"Storage: workspace {workspace!r} assets now served from {url or 'STORAGE_REMOTE_PUBLIC_URL'} (was {previous!r}, by {name})"
        )
        self.event_bus.dispatch(
            integration_id="storage_settings",
            group_id=workspace_id,
            event_type=EventTypes.storage_public_domain_changed,
            document_data=EventStoragePublicDomainChangedData(
                operation=EventOperation.update,
                previous_url=previous,
                url=url,
                changed_by_name=name,
            ),
            message=f"{workspace}: remote assets now served from {url or 'the platform default'} (was {previous or 'the platform default'})",
            user_id=self.user.id,
            entity_type="storage",
        )

    def _announce(self, previous: str | None, chosen: str | None, effective: str) -> None:
        """storage_provider_changed (platform scope, always audited). No workspace: a platform setting."""
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"Storage: new uploads now go to {effective!r} (choice {previous!r} -> {chosen!r}, by {name})")
        self.event_bus.dispatch(
            integration_id="storage_settings",
            group_id=None,
            event_type=EventTypes.storage_provider_changed,
            document_data=EventStorageProviderChangedData(
                operation=EventOperation.update,
                previous_provider=previous,
                provider=chosen,
                effective_provider=effective,
                changed_by_name=name,
            ),
            message=f"New uploads now go to {effective}" + ("" if chosen else " (STORAGE_PROVIDER)") + f" (was {previous or 'STORAGE_PROVIDER'})",
            user_id=self.user.id,
            entity_type="storage",
        )
