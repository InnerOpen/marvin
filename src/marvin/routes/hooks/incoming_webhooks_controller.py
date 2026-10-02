"""Admin CRUD + token management for incoming (ingress) webhooks.

ADMIN/OWNER-managed: an incoming webhook is a public ingress that can drive automations unattended,
so creating one and minting its token is a trust decision. The public receiver lives separately in
`hooks_controller` (no auth); this controller is the authenticated management surface.
"""

import re
import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.core.config import get_app_settings
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.incoming_webhook import (
    IncomingWebhookCreate,
    IncomingWebhookRead,
    IncomingWebhookUpdate,
)

router = APIRouter(prefix="/incoming-webhooks", route_class=MarvinCrudRoute)


_require_admin = require_workspace_admin


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "webhook"


def _mint_token() -> str:
    return secrets.token_urlsafe(get_app_settings().SECURITY_TOKEN_RANDOM_BYTES)


@controller(router)
class IncomingWebhooksController(BaseUserController):
    """Manage the workspace's incoming webhooks (ADMIN/OWNER only)."""

    def _get_or_404(self, webhook_id: UUID4) -> WorkspaceIncomingWebhookModel:
        row = self.session.get(WorkspaceIncomingWebhookModel, webhook_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incoming webhook not found.")
        return row

    @router.get("", response_model=list[IncomingWebhookRead], summary="List Incoming Webhooks")
    def list_webhooks(self) -> list[IncomingWebhookRead]:
        _require_admin(self.user, self.group_id)
        rows = self.session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=self.group_id).order_by(WorkspaceIncomingWebhookModel.name).all()
        return [IncomingWebhookRead.model_validate(r) for r in rows]

    @router.post("", response_model=IncomingWebhookRead, status_code=status.HTTP_201_CREATED, summary="Create Incoming Webhook")
    def create_webhook(self, data: IncomingWebhookCreate) -> IncomingWebhookRead:
        _require_admin(self.user, self.group_id)
        slug = data.slug or _slugify(data.name)
        if self.session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=self.group_id, slug=slug).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Incoming webhook slug '{slug}' already exists.")

        payload = data.model_dump()
        payload["slug"] = slug
        row = WorkspaceIncomingWebhookModel(session=self.session, group_id=self.group_id, **payload)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return IncomingWebhookRead.model_validate(row)

    @router.get("/{webhook_id}", response_model=IncomingWebhookRead, summary="Get Incoming Webhook")
    def get_webhook(self, webhook_id: UUID4) -> IncomingWebhookRead:
        _require_admin(self.user, self.group_id)
        return IncomingWebhookRead.model_validate(self._get_or_404(webhook_id))

    @router.patch("/{webhook_id}", response_model=IncomingWebhookRead, summary="Update Incoming Webhook")
    def update_webhook(self, webhook_id: UUID4, data: IncomingWebhookUpdate) -> IncomingWebhookRead:
        _require_admin(self.user, self.group_id)
        row = self._get_or_404(webhook_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        self.session.commit()
        self.session.refresh(row)
        return IncomingWebhookRead.model_validate(row)

    @router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Incoming Webhook")
    def delete_webhook(self, webhook_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        row = self._get_or_404(webhook_id)
        self.session.delete(row)
        self.session.commit()

    @router.post("/{webhook_id}/token", response_model=IncomingWebhookRead, summary="Mint or rotate the webhook token")
    def mint_token(self, webhook_id: UUID4) -> IncomingWebhookRead:
        """Generate a fresh secret token (rotating any existing one — the old URL stops working)."""
        _require_admin(self.user, self.group_id)
        row = self._get_or_404(webhook_id)
        row.token = _mint_token()
        self.session.commit()
        self.session.refresh(row)
        return IncomingWebhookRead.model_validate(row)

    @router.delete("/{webhook_id}/token", response_model=IncomingWebhookRead, summary="Revoke the webhook token")
    def revoke_token(self, webhook_id: UUID4) -> IncomingWebhookRead:
        """Clear the token so the receiver rejects all further requests to this webhook."""
        _require_admin(self.user, self.group_id)
        row = self._get_or_404(webhook_id)
        row.token = None
        self.session.commit()
        self.session.refresh(row)
        return IncomingWebhookRead.model_validate(row)
