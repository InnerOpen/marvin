from marvin.routes._base.routers import AdminAPIRouter

from . import (
    about_controller,
    ai_prices_controller,
    alerts_controller,
    backup_health_controller,
    backups_controller,
    character_packs_controller,
    email_controller,
    event_connections_controller,
    events_controller,
    group_controller,
    maintenance_controller,
    overview_controller,
    platform_policy_controller,
    plugins_controller,
    scheduled_tasks_controller,
    storage_controller,
    submission_protection_controller,
    system_playbooks_controller,
    trash_controller,
    user_controller,
    workspace_members_controller,
)

router = AdminAPIRouter(prefix="/admin")

router.include_router(about_controller.router, tags=["Admin: About"])
router.include_router(platform_policy_controller.router, tags=["Admin: Platform Policy"])
router.include_router(system_playbooks_controller.router, tags=["Admin: System Playbooks"])
router.include_router(overview_controller.router, tags=["Admin: Overview"])
router.include_router(ai_prices_controller.router, tags=["Admin: AI Pricing"])
router.include_router(alerts_controller.router, tags=["Admin: Platform Alerts"])
router.include_router(backup_health_controller.router, tags=["Admin: Backup Health"])
router.include_router(backups_controller.router, tags=["Admin: Backups"])
router.include_router(character_packs_controller.router, tags=["Admin: Character Library"])
router.include_router(email_controller.router, tags=["Admin: Email"])
router.include_router(events_controller.router, tags=["Admin: Events"])
router.include_router(event_connections_controller.router, tags=["Admin: Events"])
router.include_router(user_controller.router, tags=["Admin: Users"])
router.include_router(group_controller.router, tags=["Admin: Groups"])
router.include_router(maintenance_controller.router, tags=["Admin: Maintenance"])
router.include_router(plugins_controller.router, tags=["Admin: Plugins"])
router.include_router(workspace_members_controller.router)
router.include_router(scheduled_tasks_controller.router, tags=["Admin: Scheduled Tasks"])
router.include_router(storage_controller.router, tags=["Admin: Storage"])
router.include_router(submission_protection_controller.router, tags=["Admin: Submission Protection"])
router.include_router(trash_controller.router, tags=["Admin: Trash"])
