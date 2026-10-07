from fastapi import APIRouter

from . import mcp_servers_controller, models_controller, operations_controller, provider_types_controller, providers_controller

router = APIRouter()
router.include_router(providers_controller.router, tags=["AI: Providers"])
router.include_router(provider_types_controller.router, tags=["AI: Providers"])
router.include_router(models_controller.router, tags=["AI: Models"])
router.include_router(operations_controller.router, tags=["AI: Operations"])
router.include_router(mcp_servers_controller.router, tags=["AI: MCP Servers"])
