"""Admin routes for platform collections, entries, resources, assets, and site clients."""

from marvin.routes._base.routers import AdminAPIRouter

from . import (
    assets_controller,
    collections_controller,
    entries_controller,
    resources_controller,
    site_clients_controller,
)

router = AdminAPIRouter(prefix="/platform")

router.include_router(collections_controller.router, tags=["Admin: Collections"])
router.include_router(entries_controller.router, tags=["Admin: Entries"])
router.include_router(resources_controller.router, tags=["Admin: Resources"])
router.include_router(assets_controller.router, tags=["Admin: Assets"])
router.include_router(site_clients_controller.router, tags=["Admin: Site Clients"])
