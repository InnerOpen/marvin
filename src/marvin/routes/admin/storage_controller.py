"""Asset storage (admin): which provider new uploads go to, and how many files live on each.

Switching is safe at any time and in either direction: it only decides where new uploads are stored.
Existing files keep serving from the provider their row names until `scripts/storage_migrate.py`
moves them. See services/storage/admin.py.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.storage import StorageSettingsRead, StorageSettingsUpdate
from marvin.services.event_bus_service.event_types import EventOperation, EventStorageProviderChangedData, EventTypes
from marvin.services.storage.admin import UnavailableProviderError, set_upload_provider, storage_status

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

    def _announce(self, previous: str | None, chosen: str | None, effective: str) -> None:
        """storage_provider_changed (platform scope, always audited)."""
        workspace_id = self.user.active_group_id or self.user.group_id  # stored with it, shown only to super admins
        name = getattr(self.user, "full_name", None) or self.user.username
        self.logger.info(f"Storage: new uploads now go to {effective!r} (choice {previous!r} -> {chosen!r}, by {name})")
        if not workspace_id:
            return
        self.event_bus.dispatch(
            integration_id="storage_settings",
            group_id=workspace_id,
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
