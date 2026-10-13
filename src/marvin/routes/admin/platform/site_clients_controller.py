"""Admin site clients controller."""

from functools import cached_property

from fastapi import APIRouter
from pydantic import UUID4

from marvin.repos.platform import APIClientsRepository
from marvin.routes._base import BaseAdminController, controller
from marvin.routes._base.mixins import HttpRepo
from marvin.schemas.platform import APIClientCreate, APIClientRead, APIClientUpdate, APIClientWithToken

router = APIRouter(prefix="/site-clients")


@controller(router)
class AdminSiteClientsRoutes(BaseAdminController):
    """Controller for managing site clients (API clients)."""

    @cached_property
    def repo(self) -> APIClientsRepository:
        """Get API clients repository for current group."""
        if not self.user or not self.user.group_id:
            raise ValueError("User must have a group assigned")
        return APIClientsRepository(self.session, self.user.group_id)

    @property
    def mixins(self) -> HttpRepo[APIClientCreate, APIClientRead, APIClientUpdate]:
        """Mixin for CRUD operations."""
        return HttpRepo[APIClientCreate, APIClientRead, APIClientUpdate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=list[APIClientRead], summary="List Site Clients")
    def get_all(self) -> list[APIClientRead]:
        """Get all site clients in the user's group."""
        clients = self.repo.get_all()
        return [self.repo.schema.from_orm(c) for c in clients]

    @router.post("", response_model=APIClientWithToken, summary="Create Site Client")
    def create(self, schema: APIClientCreate) -> APIClientWithToken:
        """Create a new site client and return with token (shown once)."""
        return self.repo.create(schema)

    @router.get("/{client_id}", response_model=APIClientRead, summary="Get Site Client")
    def get_one(self, client_id: UUID4) -> APIClientRead:
        """Get a specific site client."""
        return self.mixins.get_one(client_id)

    @router.put("/{client_id}", response_model=APIClientRead, summary="Update Site Client")
    def update(self, client_id: UUID4, schema: APIClientUpdate) -> APIClientRead:
        """Update a site client."""
        return self.mixins.update_one(client_id, schema)

    @router.post("/{client_id}/rotate-token", response_model=APIClientWithToken, summary="Rotate API Token")
    def rotate_token(self, client_id: UUID4) -> APIClientWithToken:
        """Generate a new token for this site client. Old token becomes invalid."""
        return self.repo.rotate_token(client_id)

    @router.delete("/{client_id}", response_model=APIClientRead, summary="Delete Site Client")
    def delete(self, client_id: UUID4) -> APIClientRead:
        """Delete a site client."""
        return self.mixins.delete_one(client_id)
