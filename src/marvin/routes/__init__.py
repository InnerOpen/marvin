from fastapi import APIRouter

from . import admin, ai, app, auth, automations, events, groups, hooks, platform, publish, users

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
