"""The platform's installed plugins (admin), read-only.

Plugins are installed by the platform operator (container image / Helm init container), not through
the API — installing one runs its code — so this lists what is there and how widely it is used.
See services/plugins.py.
"""

from fastapi import APIRouter

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.plugins import PluginRead
from marvin.services.plugins import installed_plugins

router = APIRouter(prefix="/plugins")


@controller(router)
class AdminPluginsController(BaseAdminController):
    @router.get("", response_model=list[PluginRead], summary="Admin: List Installed Plugins")
    def list_plugins(self) -> list[PluginRead]:
        """Installed plugin packages, the providers each registers, and how many workspaces use them."""
        return installed_plugins(self.session)
