"""
Authenticated platform routes.

All routes are mounted under /api/platform/ prefix:
- /api/platform/entry-types - Entry type definitions
- /api/platform/entries - Content entries
- /api/platform/collections - Content collections
- /api/platform/api-clients - API client credentials
- /api/platform/resources - Platform resources
- /api/platform/assets - File assets
- /api/platform/workspace - Workspace export/import
- /api/platform/workspaces/{id}/members - Workspace member management
- /api/platform/scheduled-tasks - Scheduled task automation
- /api/platform/site/rebuild - Request a site rebuild / read its status
- /api/platform/media-embeds - Media-embed providers and link resolution (editor previews)
"""

from marvin.routes._base.routers import UserAPIRouter

from . import (
    api_clients_controller,
    assets_controller,
    collections_controller,
    email_controller,
    entries_controller,
    entry_types_controller,
    events_controller,
    forms_controller,
    media_embeds_controller,
    # CODE_GEN_ID: PLATFORM_ROUTE_IMPORTS
    # END: PLATFORM_ROUTE_IMPORTS
    resources_controller,
    scheduled_tasks_controller,
    site_controller,
    stats_controller,
    tags_controller,
    workspace_controller,
    workspace_members_controller,
)

router = UserAPIRouter()

router.include_router(entry_types_controller.router, tags=["Platform: Entry Types"])
router.include_router(entries_controller.router, tags=["Platform: Entries"])
router.include_router(collections_controller.router, tags=["Platform: Collections"])
router.include_router(tags_controller.router, tags=["Platform: Tags"])
router.include_router(api_clients_controller.router, tags=["Platform: API Clients"])
router.include_router(resources_controller.router, tags=["Platform: Resources"])
router.include_router(assets_controller.router, tags=["Platform: Assets"])
router.include_router(forms_controller.router, tags=["Platform: Forms"])
router.include_router(workspace_controller.router, tags=["Platform: Workspace"])
router.include_router(workspace_members_controller.router, tags=["Platform: Workspace Members"])
router.include_router(events_controller.router, tags=["Platform: Events"])
router.include_router(scheduled_tasks_controller.router, tags=["Platform: Scheduled Tasks"])
router.include_router(stats_controller.router, tags=["Platform: Stats"])
router.include_router(email_controller.router, tags=["Platform: Email"])
router.include_router(site_controller.router, tags=["Platform: Site"])
router.include_router(media_embeds_controller.router, tags=["Platform: Media Embeds"])

# CODE_GEN_ID: PLATFORM_ROUTE_INCLUDES
# END: PLATFORM_ROUTE_INCLUDES
