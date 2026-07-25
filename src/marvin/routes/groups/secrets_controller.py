"""
Workspace Secrets API.

Provides CRUD for workspace-scoped secrets. Values are encrypted at rest
by the configured backend and never returned in list/read responses.
Reference secrets in webhook headers with {{SLUG}} syntax.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.core.config import get_app_settings
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.group.secret import (
    WorkspaceSecretCreate,
    WorkspaceSecretRead,
    WorkspaceSecretUpdate,
    WorkspaceSecretWithValue,
)
from marvin.services.event_bus_service.event_types import EventOperation, EventSecretData, EventTypes
from marvin.services.secrets import get_secret_backend

router = APIRouter(prefix="/groups/secrets")


def _store_encrypted(secret: WorkspaceSecret, value: str) -> None:
    """Update the encrypted_value on the model if using the database backend."""
    if get_app_settings().SECRET_BACKEND == "database":
        from marvin.services.secrets.backends.database import _get_fernet

        secret.encrypted_value = _get_fernet().encrypt(value.encode()).decode()
    else:
        secret.encrypted_value = "_backend_managed_"


def _get_secret_or_404(session, secret_id: UUID4, group_id: UUID4) -> WorkspaceSecret:
    secret = session.get(WorkspaceSecret, secret_id)
    if not secret or secret.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found.")
    return secret


@controller(router)
class SecretsController(BaseUserController):
    """Workspace secrets management."""

    def _emit(self, event_type: EventTypes, operation: EventOperation, *, slug: str, name: str | None, secret_id: UUID4) -> None:
        """Dispatch a secret_* event. The value is NEVER included — refs only."""
        self.event_bus.dispatch(
            integration_id="secret_management",
            group_id=self.group_id,
            event_type=event_type,
            document_data=EventSecretData(
                operation=operation,
                slug=slug,
                name=name,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Secret {slug} {operation.value}d",
            user_id=self.user.id if self.user else None,
            entity_id=secret_id,
            entity_type="secret",
        )

    @router.get("", response_model=list[WorkspaceSecretRead])
    def list_secrets(self):
        """List all secrets (slugs + metadata only — no values)."""
        return self.repos.workspace_secrets().get_all(order_by="name")

    @router.get("/slugs", response_model=list[str])
    def list_slugs(self):
        """Return secret slugs for {{SLUG}} autocomplete in webhook header builder."""
        return get_secret_backend().list_slugs(self.group_id)

    @router.post("", response_model=WorkspaceSecretRead, status_code=status.HTTP_201_CREATED)
    def create_secret(self, data: WorkspaceSecretCreate):
        """Create a workspace secret. Value is encrypted on write."""
        existing = self.repos.workspace_secrets().get_all()
        if any(s.slug == data.slug for s in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Secret slug '{data.slug}' already exists in this workspace.",
            )

        # Build the DB row first (encrypted value set by _store_encrypted)
        secret = WorkspaceSecret(
            session=self.session,
            group_id=self.group_id,
            name=data.name,
            slug=data.slug,
            description=data.description,
            encrypted_value="_backend_managed_",
        )
        _store_encrypted(secret, data.value)
        self.session.add(secret)
        self.session.commit()
        self.session.refresh(secret)

        # For external backends (vault, bitwarden, disk, env) also write there.
        # The database backend is already handled above — don't call set() again.
        if get_app_settings().SECRET_BACKEND != "database":
            get_secret_backend().set(data.slug, data.value, self.group_id)

        self._emit(EventTypes.secret_created, EventOperation.create, slug=secret.slug, name=secret.name, secret_id=secret.id)
        return WorkspaceSecretRead.model_validate(secret)

    @router.patch("/{secret_id}", response_model=WorkspaceSecretRead)
    def update_secret(self, secret_id: UUID4, data: WorkspaceSecretUpdate):
        """Update a secret's name, description, or value."""
        secret = _get_secret_or_404(self.session, secret_id, self.group_id)

        if data.name is not None:
            secret.name = data.name
        if data.description is not None:
            secret.description = data.description
        if data.value is not None:
            _store_encrypted(secret, data.value)
            if get_app_settings().SECRET_BACKEND != "database":
                get_secret_backend().set(secret.slug, data.value, self.group_id)

        self.session.commit()
        self.session.refresh(secret)
        self._emit(EventTypes.secret_updated, EventOperation.update, slug=secret.slug, name=secret.name, secret_id=secret.id)
        return WorkspaceSecretRead.model_validate(secret)

    @router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_secret(self, secret_id: UUID4):
        """Delete a secret from the backend and metadata store."""
        secret = self.session.get(WorkspaceSecret, secret_id)
        if not secret or secret.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found.")
        # Snapshot identity before the row is gone — the event carries the slug/name, never the value.
        slug, name = secret.slug, secret.name
        if get_app_settings().SECRET_BACKEND != "database":
            get_secret_backend().delete(secret.slug, self.group_id)
        self.session.delete(secret)
        self.session.commit()
        self._emit(EventTypes.secret_deleted, EventOperation.delete, slug=slug, name=name, secret_id=secret_id)

    @router.post("/{secret_id}/reveal", response_model=WorkspaceSecretWithValue)
    def reveal_secret(self, secret_id: UUID4):
        """Return decrypted value. Workspace admins only."""
        if not self.user.admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")

        secret = _get_secret_or_404(self.session, secret_id, self.group_id)
        value = get_secret_backend().get(secret.slug, self.group_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Secret value unavailable from backend.")

        return WorkspaceSecretWithValue(
            id=secret.id,
            group_id=secret.group_id,
            name=secret.name,
            slug=secret.slug,
            description=secret.description,
            value=value,
        )
