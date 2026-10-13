"""
This module defines the FastAPI controller for administrative management of user groups
within the Marvin application.

It provides RESTful endpoints for administrators to perform CRUD (Create, Read,
Update, Delete) operations on groups, including managing group preferences.
"""

from functools import cached_property  # For lazy-loading properties

from fastapi import APIRouter, Depends, HTTPException, status  # Core FastAPI components
from pydantic import UUID4  # For UUID type validation

# Marvin specific schemas and services
from marvin.schemas.group import GroupCreate, GroupPagination, GroupRead
from marvin.schemas.group.group import GroupAdminUpdate  # Schema for updating group by admin
from marvin.schemas.mapper import mapper  # Utility for mapping data between objects
from marvin.schemas.response.pagination import PaginationQuery  # For handling pagination parameters
from marvin.schemas.response.responses import ErrorResponse  # Standardized error response
from marvin.services.group.group_purge import purge_group_dependents  # Clears non-cascading workspace rows
from marvin.services.group.group_service import GroupService  # Service layer for group operations
from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, is_platform_workspace, platform_workspace
from marvin.services.group.workspace_rename import WorkspaceRenameError, rename_workspace

# Base controller and mixin for CRUD helpers
from .._base import BaseAdminController, controller
from .._base.mixins import HttpRepo

# APIRouter for admin group management, prefixed with /groups
# All routes here will be under /admin/groups.
router = APIRouter(prefix="/groups")


@controller(router)
class AdminGroupManagementRoutes(BaseAdminController):
    """
    Controller for administrative CRUD operations on user groups.

    Provides endpoints for creating, retrieving, updating, and deleting groups.
    Includes logic for handling group preferences and ensuring data integrity,
    such as preventing deletion of groups with active users.
    All operations require administrator privileges.
    """

    @cached_property
    def repo(self):  # Type hint could be RepositoryGroup if available and imported
        """
        Provides a cached instance of the groups repository (`self.repos.groups`).

        Ensures that a user is logged in before accessing the repository.
        The repository instance is specific to group management.

        Raises:
            Exception: If no user is logged in (should be caught by BaseAdminController).

        Returns:
            The groups repository instance.
        """
        if not self.user:  # Should be handled by BaseAdminController dependency
            raise Exception("No user is logged in. This should be caught by admin dependency.")
        return self.repos.groups

    # =======================================================================
    # CRUD Operations via HttpRepo Mixin and Custom Methods
    # =======================================================================

    @property
    def mixins(self) -> HttpRepo[GroupCreate, GroupRead, GroupAdminUpdate]:
        """
        Provides a cached instance of `HttpRepo` configured for Group CRUD operations.

        This property initializes `HttpRepo` with the group repository, logger,
        and registered exception messages, streamlining common CRUD HTTP responses
        and error handling.
        """
        # The type variables for HttpRepo:
        # C (CreateSchema) = GroupCreate
        # R (ReadSchema)   = GroupRead
        # U (UpdateSchema) = GroupAdminUpdate
        return HttpRepo[GroupCreate, GroupRead, GroupAdminUpdate](
            self.repo,  # The groups repository from the cached_property above
            self.logger,
            self.registered_exceptions,  # Method from BaseUserController to get error messages
        )

    @router.get("", response_model=GroupPagination, summary="Get All Groups (Paginated)")
    def get_all(self, q: PaginationQuery = Depends(PaginationQuery)) -> GroupPagination:
        """
        Retrieves a paginated list of all groups.

        Administrators can use this endpoint to view all groups in the system.
        Supports standard pagination query parameters.

        Args:
            q (PaginationQuery): FastAPI dependency for pagination query parameters
                                 (page, per_page, order_by, etc.).

        Returns:
            GroupPagination: A Pydantic model containing the list of groups for the
                             current page and pagination metadata.
        """
        # Use the repository's page_all method for pagination
        paginated_response = self.repo.page_all(
            pagination=q,
            override_schema=GroupRead,  # Ensure response items are serialized as GroupRead
        )
        # Set HATEOAS pagination guide URLs for client navigation
        paginated_response.set_pagination_guides(router.url_path_for("get_all"), q.model_dump())
        return paginated_response

    @router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED, summary="Create a New Group")
    def create_one(self, data: GroupCreate) -> GroupRead:
        """
        Creates a new group with default content.

        This endpoint creates a workspace and bootstraps it with:
        - Default entry types (page, post, project)
        - Default collections (featured, recent)
        - Creator as OWNER
        - All SUPER_ADMIN users as ADMIN

        Accessible only by administrators.

        Args:
            data (GroupCreate): Pydantic schema containing the data for the new group
                                (e.g., name).

        Returns:
            GroupRead: The Pydantic schema of the newly created group.
        """
        from marvin.services.event_bus_service.event_types import (
            EventTypes,
            EventWorkspaceCreatedData,
        )
        from marvin.services.workspace.workspace_bootstrap_service import (
            WorkspaceBootstrapService,
        )

        # Create the workspace
        group = GroupService.create_group(self.repos, data)

        # Get the underlying model instance for bootstrap
        from sqlalchemy import select

        from marvin.db.models.groups import Groups

        group_model = self.repos.session.execute(select(Groups).where(Groups.id == group.id)).scalar_one()

        # Bootstrap with default content and memberships
        WorkspaceBootstrapService.bootstrap(
            repos=self.repos,
            workspace=group_model,
            creator_id=self.user.id,
        )

        # Dispatch workspace.created event
        self.event_bus.dispatch(
            integration_id="workspace_management",
            group_id=group.id,
            event_type=EventTypes.workspace_created,
            document_data=EventWorkspaceCreatedData(
                workspace_id=group.id,
                workspace_name=group.name,
                creator_id=self.user.id,
                creator_name=self.user.full_name or self.user.username,
            ),
            message=f"Workspace '{group.name}' created by {self.user.username}",
        )

        # Commit transaction
        self.repos.session.commit()

        return group

    @router.get("/platform", response_model=GroupRead, summary="Get the Platform Workspace")
    def get_platform(self) -> GroupRead:
        """
        The platform (admin's) workspace — platform alerts and shared services run from it.

        Found by its marker, whatever it is called. Rename it with ``PUT /api/admin/groups/{id}``.

        Raises:
            HTTPException (404 Not Found): The database has no platform workspace yet.
        """
        try:
            return self.repo.schema.model_validate(platform_workspace(self.session))
        except PlatformWorkspaceMissing as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    @router.get("/{item_id}", response_model=GroupRead, summary="Get a Specific Group by ID")
    def get_one(self, item_id: UUID4) -> GroupRead:
        """
        Retrieves a specific group by its unique ID.

        Accessible only by administrators.

        Args:
            item_id (UUID4): The unique identifier of the group to retrieve.

        Returns:
            GroupRead: The Pydantic schema of the requested group.

        Raises:
            HTTPException (404 Not Found): If no group with the given ID exists.
        """
        # Uses the get_one method from the HttpRepo mixin for standardized fetching and error handling
        return self.mixins.get_one(item_id)

    @router.put("/{item_id}", response_model=GroupRead, summary="Update a Group")
    def update_one(self, item_id: UUID4, data: GroupAdminUpdate) -> GroupRead:
        """
        Updates an existing group's details, including its name and preferences.

        If `data.preferences` is provided, the group's preferences are updated.
        If `data.name` differs from the current name, or `data.slug` from the current slug, the
        workspace is renamed (slug derived from the name unless given); the old slug keeps resolving.
        Accessible only by administrators.

        Args:
            item_id (UUID4): The ID of the group to update.
            data (GroupAdminUpdate): Pydantic schema containing the update data.
                                     Fields not provided will not be changed (partial update).

        Returns:
            GroupRead: The Pydantic schema of the updated group.

        Raises:
            HTTPException (404 Not Found): If the group or its preferences are not found.
            HTTPException (409 Conflict): The name or slug is taken (or was another workspace's slug).
        """
        from marvin.db.models.groups.groups import Groups
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        # Retrieve the existing group ORM model instance
        group_model_instance = self.session.get(Groups, item_id)
        if not group_model_instance:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Group not found.")

        # Update group preferences if provided in the request data
        if data.preferences:
            # Fetch existing preferences for the group
            preferences_model = self.session.query(GroupPreferencesModel).filter_by(group_id=item_id).first()
            if not preferences_model:
                # This case might indicate data inconsistency or preferences are not yet created.
                # Depending on design, could create preferences here or raise error.
                # For now, assume preferences should exist if group exists and are being updated.
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Group preferences not found for this group.")

            # Map incoming preference data to the existing preferences model
            updated_preferences_data = mapper(data.preferences, preferences_model)
            # Update preferences in the database
            self.repos.group_preferences.update(preferences_model.id, updated_preferences_data)  # Update by preference ID

        # Rename: a new name, a new slug, or both. Without an explicit slug a name change derives it
        # from the new name. A changed slug stays resolvable as an alias (services.group.workspace_rename),
        # so Publishing API URLs, CLI arguments and backup names using the old one keep working. The
        # platform workspace is renamed the same way; its marker isn't part of this schema.
        new_name = data.name.strip() if data.name and data.name.strip() else group_model_instance.name
        if new_name != group_model_instance.name or (data.slug and data.slug.strip() and data.slug != group_model_instance.slug):
            try:
                rename_workspace(self.session, group_model_instance, name=new_name, slug=data.slug)
            except WorkspaceRenameError as e:
                self.session.rollback()
                raise HTTPException(status.HTTP_409_CONFLICT, detail=ErrorResponse.respond(message=str(e))) from e
            self.session.commit()

        # After all updates, refresh the ORM instance to capture name/slug and
        # relationship (preferences) changes, then convert to the response schema.
        self.session.refresh(group_model_instance)  # Refresh to capture potential relationship updates

        result = self.repo.schema.model_validate(group_model_instance)

        # Dispatch workspace_updated event
        from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventWorkspaceData

        self.event_bus.dispatch(
            integration_id="workspace_management_admin",
            group_id=item_id,
            event_type=EventTypes.workspace_updated,
            document_data=EventWorkspaceData(
                operation=EventOperation.update,
                workspace_id=item_id,
                workspace_name=result.name,
                workspace_slug=result.slug,
            ),
            message=f"Workspace '{result.name}' updated",
            user_id=None,  # Admin endpoints don't have current_user in this method
            entity_id=item_id,
            entity_type="workspace",
        )

        return result

    @router.delete("/{item_id}", summary="Delete a Group")
    def delete_one(self, item_id: UUID4, force: bool = False) -> dict:
        """
        Deletes a workspace by its unique ID.

        Safety checks:
        - Never the platform (admin's) workspace (409), force or not
        - Cannot delete if workspace has users with it as their primary group_id
        - Cannot delete if workspace has workspace members (unless force=True)
        - Cannot delete if workspace has entries, collections, or assets (unless force=True)

        Accessible only by administrators.

        Args:
            item_id (UUID4): The ID of the workspace to delete.
            force (bool): If True, cascade delete all related content. Defaults to False.

        Raises:
            HTTPException (404 Not Found): If the workspace doesn't exist.
            HTTPException (400 Bad Request): If workspace has content and force=False.
        """
        from marvin.services.event_bus_service.event_types import EventTypes

        # Retrieve the group to check for associated users
        group_to_delete = self.repo.get_one(item_id)
        if not group_to_delete:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

        # The platform (admin's) workspace runs platform alerts and shared services: never deletable.
        if is_platform_workspace(self.session, item_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse.respond(message="The platform workspace can't be deleted. You can rename it."),
            )

        # Check for users with this as their primary group (always block this)
        user_count_in_group = self.repos.users.count_all(match_key="group_id", match_value=item_id)
        if user_count_in_group > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorResponse.respond(
                    message=f"Cannot delete workspace: {user_count_in_group} users still have this as their primary workspace. Reassign them first."
                ),
            )

        # Check for workspace content (if not force mode)
        if not force:
            # Check for workspace members
            member_count = len(self.repos.workspace_members.get_members_by_workspace(item_id))
            if member_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ErrorResponse.respond(message=f"Workspace has {member_count} members. Use force=true to delete anyway."),
                )

            # Check for entries
            from sqlalchemy import func, select

            from marvin.db.models.entries import Entries

            entry_count = self.repos.session.execute(select(func.count(Entries.id)).where(Entries.group_id == item_id)).scalar()
            if entry_count and entry_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ErrorResponse.respond(message=f"Workspace has {entry_count} entries. Use force=true to delete anyway."),
                )

        # Dispatch workspace.deleted event before deletion
        self.event_bus.dispatch(
            integration_id="workspace_management",
            group_id=item_id,
            event_type=EventTypes.workspace_deleted,
            document_data=None,
            message=f"Workspace '{group_to_delete.name}' deleted by {self.user.username}",
        )

        # `force` previously only skipped the checks above; the delete then hit a foreign key from
        # the workspace-scoped tables that don't cascade on their own, so it could never succeed.
        # Clear those first. Users are untouched — the primary-group check above still guards them.
        purge_group_dependents(self.repos.session, item_id)

        # Proceed with deletion
        self.mixins.delete_one(item_id)
        self.repos.session.commit()
        return {"status": "ok", "message": "Workspace deleted successfully"}
