"""
Service for bootstrapping new workspaces with default content.
"""

from pydantic import UUID4

from marvin.db.models.groups import Groups
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.repos.repository_factory import AllRepositories


class WorkspaceBootstrapService:
    """
    Static service for bootstrapping newly created workspaces.

    Creates default entry types, collections, and workspace memberships
    to make a workspace immediately usable.
    """

    # Default entry types to create
    DEFAULT_ENTRY_TYPES = [
        {
            "slug": "page",
            "name": "Page",
            "icon": "📄",
            "color": "#2563EB",
            "description": "A standard content page with markdown body content.",
            "sort_order": 100,
            "is_system": True,
            "is_rendered": True,
            "rendering_json": {"renderer": "page", "package": "@inneropen/marvin-renderers-core"},
            "schema_json": {
                "fields": [
                    {
                        "key": "body",
                        "label": "Body",
                        "type": "markdown",
                        "required": True,
                        "placeholder": "Write page content...",
                    }
                ]
            },
        },
        {
            "slug": "article",
            "name": "Article",
            "icon": "📝",
            "color": "#7C3AED",
            "description": "A publishable article, note, or long-form post.",
            "sort_order": 200,
            "is_system": True,
            "is_rendered": True,
            "rendering_json": {"renderer": "article", "package": "@inneropen/marvin-renderers-core"},
            "schema_json": {
                "fields": [
                    {
                        "key": "body",
                        "label": "Body",
                        "type": "markdown",
                        "required": True,
                    },
                    {
                        "key": "heroImage",
                        "label": "Hero Image",
                        "type": "asset",
                        "required": False,
                    },
                ]
            },
        },
        {
            "slug": "project",
            "name": "Project",
            "icon": "🛠️",
            "color": "#D97706",
            "description": "A documented project, build, case study, or body of work.",
            "sort_order": 300,
            "is_system": True,
            "schema_json": {
                "fields": [
                    {
                        "key": "overview",
                        "label": "Overview",
                        "type": "markdown",
                        "required": True,
                    },
                    {
                        "key": "status",
                        "label": "Project Status",
                        "type": "select",
                        "options": ["planned", "active", "paused", "completed", "archived"],
                        "defaultValue": "active",
                    },
                    {
                        "key": "startedAt",
                        "label": "Started At",
                        "type": "date",
                    },
                    {
                        "key": "completedAt",
                        "label": "Completed At",
                        "type": "date",
                    },
                    {
                        "key": "gallery",
                        "label": "Gallery",
                        "type": "asset-list",
                    },
                    {
                        "key": "relatedResources",
                        "label": "Related Resources",
                        "type": "resource-list",
                    },
                ]
            },
        },
        {
            "slug": "reference",
            "name": "Reference",
            "icon": "📚",
            "color": "#059669",
            "description": "Evergreen reference material, documentation, or guides.",
            "sort_order": 400,
            "is_system": True,
            "schema_json": {
                "fields": [
                    {
                        "key": "body",
                        "label": "Reference Content",
                        "type": "markdown",
                        "required": True,
                    },
                    {
                        "key": "category",
                        "label": "Category",
                        "type": "text",
                    },
                    {
                        "key": "relatedEntries",
                        "label": "Related Entries",
                        "type": "resource-list",
                    },
                ]
            },
        },
        {
            "slug": "navigation-item",
            "name": "Navigation Item",
            "icon": "🔗",
            "color": "#0F766E",
            "description": "A generic navigation or menu link.",
            "sort_order": 500,
            "is_system": True,
            "is_rendered": True,
            "rendering_json": {"renderer": "navigation", "package": "@inneropen/marvin-renderers-core"},
            "schema_json": {
                "fields": [
                    {
                        "key": "href",
                        "label": "Destination",
                        "type": "text",
                        "required": True,
                        "placeholder": "/about",
                    },
                    {
                        "key": "openInNewTab",
                        "label": "Open in New Tab",
                        "type": "boolean",
                        "defaultValue": False,
                    },
                ]
            },
        },
        {
            "slug": "resource",
            "name": "Resource",
            "icon": "📦",
            "color": "#6B7280",
            "description": "A reusable object, material, supplier, tool, link, or reference.",
            "sort_order": 600,
            "is_system": True,
            "schema_json": {
                "fields": [
                    {
                        "key": "resourceType",
                        "label": "Resource Type",
                        "type": "text",
                        "placeholder": "material, supplier, tool, book, link...",
                    },
                    {
                        "key": "body",
                        "label": "Notes",
                        "type": "markdown",
                    },
                    {
                        "key": "url",
                        "label": "URL",
                        "type": "text",
                    },
                    {
                        "key": "assets",
                        "label": "Assets",
                        "type": "asset-list",
                    },
                ]
            },
        },
        {
            "slug": "faq",
            "name": "FAQ",
            "icon": "❓",
            "color": "#9333EA",
            "description": "A question and answer entry.",
            "sort_order": 700,
            "is_system": True,
            "is_rendered": True,
            "rendering_json": {"renderer": "faq", "package": "@inneropen/marvin-renderers-core"},
            "schema_json": {
                "fields": [
                    {
                        "key": "question",
                        "label": "Question",
                        "type": "text",
                        "required": True,
                    },
                    {
                        "key": "answer",
                        "label": "Answer",
                        "type": "markdown",
                        "required": True,
                    },
                    {
                        "key": "category",
                        "label": "Category",
                        "type": "text",
                    },
                ]
            },
        },
    ]

    # Default collections to create
    DEFAULT_COLLECTIONS = [
        {
            "slug": "featured",
            "name": "Featured",
            "description": "Featured content",
            "sort_order": 1,
        },
        {
            # Smart, not manual: "Recent" was shipping as an empty box nobody could keep filled.
            # The rolling window is reconciled by the nightly resync_smart_collections task.
            "slug": "recent",
            "name": "Recent",
            "description": "Published in the last 30 days",
            "sort_order": 2,
            "is_smart": True,
            "smart_rules": {"statuses": ["published"], "published_within_days": 30, "match": "all"},
        },
    ]

    @staticmethod
    def bootstrap(repos: AllRepositories, workspace: Groups, creator_id: UUID4) -> None:
        """
        Bootstrap a newly created workspace with default content.

        Creates:
        1. Default entry types (page, post, project)
        2. Default collections (featured, recent)
        3. Workspace memberships (creator as OWNER, all admins as ADMIN)

        Args:
            repos: Repository factory for database access
            workspace: The newly created workspace
            creator_id: The user ID of the workspace creator
        """
        # 1. Create default entry types
        from marvin.db.models.platform.entry_types import EntryTypes

        for entry_type_data in WorkspaceBootstrapService.DEFAULT_ENTRY_TYPES:
            entry_type = EntryTypes(
                session=repos.session,
                group_id=workspace.id,
                **entry_type_data,
            )
            repos.session.add(entry_type)

        # 2. Create default collections
        from marvin.db.models.platform.collections import Collections

        for collection_data in WorkspaceBootstrapService.DEFAULT_COLLECTIONS:
            collection = Collections(
                session=repos.session,
                group_id=workspace.id,
                **collection_data,
            )
            repos.session.add(collection)

        # System workflow collections (Inbox/Drafts/Needs Review/Approved) — smart, locked,
        # internal. Idempotent; membership materializes as entries are created.
        from marvin.services.collections.system_collections import seed_system_workflow_collections

        seed_system_workflow_collections(repos.session, workspace.id)

        # 3. Add creator as OWNER
        repos.workspace_members.add_member(
            user_id=creator_id,
            workspace_id=workspace.id,
            role=WorkspaceRole.OWNER,
        )

        # 4. Add all SUPER_ADMIN users as ADMIN (for convenience)
        from sqlalchemy import select

        from marvin.db.models.users.users import Users

        stmt = select(Users).where(Users.platform_role == PlatformRole.SUPER_ADMIN)
        super_admins = repos.session.execute(stmt).scalars().all()

        for admin_user in super_admins:
            # Skip if this is the creator (already added as OWNER)
            if admin_user.id == creator_id:
                continue

            try:
                repos.workspace_members.add_member(
                    user_id=admin_user.id,
                    workspace_id=workspace.id,
                    role=WorkspaceRole.ADMIN,
                )
            except Exception:
                # Skip if already a member (shouldn't happen, but be defensive)
                repos.session.rollback()
                continue

        # Flush changes but don't commit (caller will commit)
        repos.session.flush()
