"""Workspace → Storage: keep the workspace's files in its own bucket ("bring your own storage").

Reads are for workspace OWNERs and ADMINs; changes for OWNERs (and platform super admins), since the bucket decides
where every file goes. Keys are workspace secrets, referenced by slug. See services/storage/workspace_admin.py.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin, require_workspace_role
from marvin.routes._base.controller import controller
from marvin.schemas.group.storage_settings import (
    WorkspaceStorageConnectionCheck,
    WorkspaceStorageConnectionCreate,
    WorkspaceStorageConnectionRead,
    WorkspaceStorageConnectionUpdate,
    WorkspaceStorageModeUpdate,
    WorkspaceStorageRead,
)
from marvin.services.event_bus_service.event_types import (
    EventOperation,
    EventStorageProviderChangedData,
    EventTypes,
    EventWorkspaceSettingsData,
)
from marvin.services.storage import workspace_admin as admin

router = APIRouter(prefix="/groups/storage-settings", route_class=MarvinCrudRoute)


@controller(router)
class StorageSettingsController(BaseUserController):
    def _require_owner(self) -> None:
        require_workspace_role(self.user, self.group_id, WorkspaceRole.OWNER)

    def _can_edit(self) -> bool:
        try:
            self._require_owner()
        except HTTPException:
            return False
        return True

    def _name(self) -> str:
        return getattr(self.user, "full_name", None) or self.user.username

    def _read(self) -> WorkspaceStorageRead:
        return WorkspaceStorageRead.model_validate({**admin.view(self.session, self.group_id), "can_edit": self._can_edit()})

    def _connection(self, connection_id: str):
        try:
            return admin.get_connection(self.session, self.group_id, connection_id)
        except (LookupError, ValueError):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found") from None

    def _announce(self, message: str) -> None:
        """workspace_settings_changed with `storage`: what changed, by name and status — never a key."""
        self.event_bus.dispatch(
            integration_id="workspace_storage",
            group_id=self.group_id,
            event_type=EventTypes.workspace_settings_changed,
            document_data=EventWorkspaceSettingsData(operation=EventOperation.update, workspace_id=self.group_id, changed_fields=["storage"]),
            message=f"Storage: {message}"[:1000],
            user_id=self.user.id,
            entity_id=self.group_id,
            entity_type="workspace",
        )

    @router.get("", response_model=WorkspaceStorageRead, summary="Get the Workspace's Storage")
    def get_storage(self) -> WorkspaceStorageRead:
        """Where new uploads go, the workspace's bucket connections (keys as secret slugs only) and the files on each."""
        require_workspace_admin(self.user, self.group_id)
        return self._read()

    @router.post(
        "/connections", response_model=WorkspaceStorageConnectionRead, status_code=status.HTTP_201_CREATED, summary="Add a Bucket Connection"
    )
    def create_connection(self, data: WorkspaceStorageConnectionCreate) -> WorkspaceStorageConnectionRead:
        """Add a bucket (unverified until checked). Keys are workspace secret slugs. 422 for a setting the provider
        doesn't declare, a missing required one, an unknown secret or an endpoint the platform's policy refuses."""
        self._require_owner()
        try:
            conn = admin.create_connection(
                self.session,
                self.group_id,
                self.user.id,
                plugin_slug=data.plugin_slug,
                label=data.label,
                settings=data.settings,
                secret_refs=data.secret_refs,
            )
        except admin.WorkspaceStorageError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        self._announce(f"connection {conn.label or conn.id} added by {self._name()}")
        return WorkspaceStorageConnectionRead.model_validate(admin.connection_view(conn))

    @router.patch("/connections/{connection_id}", response_model=WorkspaceStorageConnectionRead, summary="Change a Bucket Connection")
    def update_connection(self, connection_id: str, data: WorkspaceStorageConnectionUpdate) -> WorkspaceStorageConnectionRead:
        """Change the label, the keys (secret slugs) or the public URL. The bucket, endpoint and prefix can't change
        (422): another bucket is a new connection. Any change makes it unverified until checked again."""
        self._require_owner()
        self._connection(connection_id)
        try:
            conn = admin.update_connection(
                self.session, self.group_id, connection_id, label=data.label, settings=data.settings, secret_refs=data.secret_refs
            )
        except admin.WorkspaceStorageError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        self._announce(f"connection {conn.label or conn.id} changed by {self._name()} ({conn.status})")
        return WorkspaceStorageConnectionRead.model_validate(admin.connection_view(conn))

    @router.post("/connections/{connection_id}/check", response_model=WorkspaceStorageConnectionCheck, summary="Check a Bucket Connection")
    def check_connection(self, connection_id: str) -> WorkspaceStorageConnectionCheck:
        """List, put, get and delete a tiny object under `_marvin-healthcheck/`, then fetch one from the public URL.
        Every step's outcome comes back as a plain message, never as a failed request. Success verifies the connection."""
        self._require_owner()
        conn = self._connection(connection_id)
        result = admin.check_connection(self.session, self.group_id, conn.id)
        self.logger.info(f"Workspace storage: check of {conn.id} by {self._name()}: {'ok' if result['ok'] else 'FAILED'}")
        return WorkspaceStorageConnectionCheck.model_validate(result)

    @router.post("/connections/{connection_id}/retire", response_model=WorkspaceStorageConnectionRead, summary="Retire a Bucket Connection")
    def retire_connection(self, connection_id: str) -> WorkspaceStorageConnectionRead:
        """No new uploads through it; files already in it keep serving. 422 while the workspace uploads through it."""
        self._require_owner()
        self._connection(connection_id)
        try:
            conn = admin.retire_connection(self.session, self.group_id, connection_id)
        except admin.WorkspaceStorageError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        self._announce(f"connection {conn.label or conn.id} retired by {self._name()}")
        return WorkspaceStorageConnectionRead.model_validate(admin.connection_view(conn))

    @router.put("/mode", response_model=WorkspaceStorageRead, summary="Choose Where the Workspace's Uploads Go")
    def set_mode(self, data: WorkspaceStorageModeUpdate) -> WorkspaceStorageRead:
        """`platform`, or `workspace` with a verified `connection_id`. Only new uploads change place: nothing moves.
        422 when the platform doesn't allow workspace storage or the connection isn't verified."""
        self._require_owner()
        try:
            previous, location = admin.set_mode(self.session, self.group_id, self.user.id, mode=data.mode, connection_id=data.connection_id)
        except (admin.WorkspaceStorageError, LookupError, ValueError) as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None
        if previous != location:
            self.event_bus.dispatch(
                integration_id="workspace_storage",
                group_id=self.group_id,
                event_type=EventTypes.storage_provider_changed,
                document_data=EventStorageProviderChangedData(
                    operation=EventOperation.update,
                    previous_provider=previous,
                    provider=location,
                    effective_provider=location or "platform",
                    changed_by_name=self._name(),
                ),
                message=f"New uploads in this workspace now go to {'its own bucket' if location else 'the platform storage'} (by {self._name()})",
                user_id=self.user.id,
                entity_type="storage",
            )
        return self._read()
