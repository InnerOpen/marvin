from marvin.routes._base.routers import AdminAPIRouter

from . import (
    about_controller,
    backups_controller,
    character_packs_controller,
    email_controller,
    events_controller,
    group_controller,
    maintenance_controller,
    plugins_controller,
    scheduled_tasks_controller,
    submission_protection_controller,
    user_controller,
    workspace_members_controller,
)

router = AdminAPIRouter(prefix="/admin")

router.include_router(about_controller.router, tags=["Admin: About"])
router.include_router(backups_controller.router, tags=["Admin: Backups"])
router.include_router(character_packs_controller.router, tags=["Admin: Character Library"])
router.include_router(email_controller.router, tags=["Admin: Email"])
router.include_router(events_controller.router, tags=["Admin: Events"])
router.include_router(user_controller.router, tags=["Admin: Users"])
router.include_router(group_controller.router, tags=["Admin: Groups"])
router.include_router(maintenance_controller.router, tags=["Admin: Maintenance"])
router.include_router(plugins_controller.router, tags=["Admin: Plugins"])
router.include_router(workspace_members_controller.router)
router.include_router(scheduled_tasks_controller.router, tags=["Admin: Scheduled Tasks"])
router.include_router(submission_protection_controller.router, tags=["Admin: Submission Protection"])
