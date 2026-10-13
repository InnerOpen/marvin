from collections.abc import Callable

from fastapi import APIRouter

from marvin.core.config import get_app_plugins, get_app_settings
from marvin.core.root_logger import get_logger

from . import admin, ai, app, auth, automations, events, groups, hooks, platform, publish, users

settings = get_app_settings()
logger = get_logger()

# load Core api Routes
router = APIRouter(prefix="/api")
router.include_router(app.router)
router.include_router(auth.router)
router.include_router(groups.router)
router.include_router(users.router)
router.include_router(events.router)
router.include_router(admin.router)
router.include_router(ai.router)
router.include_router(automations.router)
router.include_router(hooks.router)
router.include_router(platform.router, prefix="/platform")
router.include_router(publish.router)


# Load Plugins. Plugins dir takes precendent the lib plugins
def load_routes():
    """Load Plugins from plugins"""
    for plugin_name, plugin in plugins.LOADED_PLUGINS.items():
        if "routers" in plugin.__dir__():
            if isinstance(plugin.routers, Callable):
                logger.info(f"Loaded Routers - name: {plugin_name} -- version: {plugin.__meta__['version']}")
                routers = plugin.routers()
                router.include_router(routers)


if settings.PLUGIN_ENABLED:
    logger.info("-------Plugins Enabled-------")
    plugins = get_app_plugins(settings.PLUGIN_PREFIX)
    load_routes()
