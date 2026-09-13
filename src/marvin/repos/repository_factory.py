"""
This module defines the `AllRepositories` class, which acts as a centralized
factory and access point for all data repositories within the Marvin application.

It uses `cached_property` to instantiate individual repositories on demand,
ensuring that they are created only when first accessed and then reused.
This pattern helps in managing database sessions and repository dependencies
efficiently.
"""

from functools import cached_property
from typing import TYPE_CHECKING

from pydantic import UUID4
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from .users.long_live_tokens import LongLiveTokensRepository

# Import all necessary DB models
from marvin.db.models.events import EventNotifierOptionsModel
from marvin.db.models.groups import (
    GroupEventNotifierModel,
    # GroupEventNotifierOptionsModel, # This seems unused directly here, group_event_notifier uses it
    GroupInviteToken,
    GroupPreferencesModel,
    Groups,
    GroupWebhooksModel,
    ReportEntryModel,
    ReportModel,
)
from marvin.db.models.groups.agents import WorkspaceAgentModel
from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.notification_execution_logs import NotificationExecutionLogModel
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.groups.variables import WorkspaceVariable
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.users import LongLiveToken, Users
from marvin.db.models.users.password_reset import PasswordResetModel

# Import all necessary Pydantic schemas for repository typing
from marvin.schemas.event.event import EventNotifierOptionsRead
from marvin.schemas.group import GroupRead
from marvin.schemas.group.agent import AgentRead
from marvin.schemas.group.ai_settings import WorkspaceAISettingsRead
from marvin.schemas.group.email_event_subscription import EmailEventSubscriptionRead
from marvin.schemas.group.event import (
    GroupEventNotifierRead,
    NotificationExecutionLogRead,
    # GroupEventNotifierOptionsRead, # Also seems unused directly
)
from marvin.schemas.group.integration import IntegrationEventSubscriptionRead, IntegrationRead
from marvin.schemas.group.invite_token import InviteTokenRead
from marvin.schemas.group.preferences import GroupPreferencesRead
from marvin.schemas.group.report import ReportEntryRead, ReportRead
from marvin.schemas.group.secret import WorkspaceSecretRead
from marvin.schemas.group.variable import WorkspaceVariableRead
from marvin.schemas.group.webhook import WebhookExecutionLogRead, WebhookRead
from marvin.schemas.user import LongLiveTokenRead, PrivateUser
from marvin.schemas.user.password import PrivatePasswordResetToken

# Import base repository types and specialized repositories
from ._utils import NOT_SET, NotSet  # Sentinel for optional group_id
from .groups import RepositoryGroup  # Specialized group repository
from .platform import (
    APIClientsRepository,
    AssetsRepository,
    CollectionsRepository,
    EntriesRepository,
    EntryTypesRepository,
    EventLogRepository,
    FormsRepository,
    FormSubmissionsRepository,
    # CODE_GEN_ID: FACTORY_REPO_IMPORTS
    # END: FACTORY_REPO_IMPORTS
    ResourcesRepository,
    ScheduledTaskExecutionLogRepository,
    ScheduledTasksRepository,
    TagsRepository,
)
from .repository_generic import GroupRepositoryGeneric, RepositoryGeneric  # Base generic repositories
from .users import RepositoryUsers  # Specialized user repository
from .workspace_members import RepositoryWorkspaceMembers  # Workspace member management

# Constants for primary key / lookup key names used in repositories
PK_ID = "id"  # Standard primary key
PK_SLUG = "slug"  # Slug identifier, often used for user-friendly URLs
PK_TOKEN = "token"  # Token string, used for invite tokens or password reset tokens
PK_GROUP_ID = "group_id"  # Foreign key for group association


class AllRepositories:
    """
    Centralized access layer for all database repositories in Marvin.

    This class uses composition to provide access to various specialized and
    generic repositories. Each repository is instantiated as a `cached_property`,
    meaning it's created only when first accessed and then cached for subsequent
    calls within the same `AllRepositories` instance.

    The `group_id` parameter allows scoping of most repositories to a specific
    group context if provided.
    """

    def __init__(
        self,
        session: Session,
        *,
        group_id: UUID4 | None | NotSet = NOT_SET,
    ) -> None:
        """
        Initializes the AllRepositories factory.

        Args:
            session (Session): The SQLAlchemy session to be used by all instantiated
                               repositories.
            group_id (UUID4 | None | NotSet, optional): The ID of the group to
                scope the repositories to. This is a keyword-only argument.
                - If a `UUID4` (group ID) is provided, repositories that are group-specific
                  (like `GroupRepositoryGeneric` instances) will be scoped to this group.
                - If `None` is provided, these repositories may operate without a specific
                  group scope or handle this case as per their implementation (e.g.,
                  for system-wide admin access where group context might be irrelevant or different).
                - If `NOT_SET` (the default), the `group_id` is considered not explicitly
                  provided. Repositories will then adhere to their default scoping logic,
                  which might mean no group scope or a system-defined default. This is
                  semantically different from explicitly passing `None`.
                Defaults to `NOT_SET`.
        """
        self.session = session
        self.group_id = group_id

    # ==============================================================================================================
    # User-related repositories
    # ==============================================================================================================

    @cached_property
    def users(self) -> RepositoryUsers:
        """
        Provides access to the specialized repository for `Users` entities.
        Manages `Users` models and uses `PrivateUser` schema for output.
        """
        return RepositoryUsers(self.session, PK_ID, Users, PrivateUser, group_id=self.group_id)

    @cached_property
    def api_tokens(self) -> "LongLiveTokensRepository":
        """
        Provides access to the specialized repository for `LongLiveToken` entities (user API tokens).

        Uses LongLiveTokensRepository which provides secure token management:
        - Bcrypt-hashed token storage
        - Token rotation support
        - Soft deletion (revocation)
        - Usage tracking
        """
        from .users.long_live_tokens import LongLiveTokensRepository

        return LongLiveTokensRepository(self.session, PK_ID, LongLiveToken, LongLiveTokenRead)

    @cached_property
    def tokens_pw_reset(self) -> GroupRepositoryGeneric[PrivatePasswordResetToken, PasswordResetModel]:
        """
        Provides access to the repository for `PasswordResetModel` entities.
        Scoped by `group_id` (though password resets are user-specific, the generic
        group scoping might apply if users are tightly coupled to groups for all actions).
        Uses `PK_TOKEN` as the match key for some operations.
        """
        # Password resets are typically user-specific, not group-specific.
        # If group_id is NOT_SET or None, this repo will operate without group filtering.
        return GroupRepositoryGeneric(self.session, PK_TOKEN, PasswordResetModel, PrivatePasswordResetToken, group_id=self.group_id)

    # ==============================================================================================================
    # Group-related repositories
    # ==============================================================================================================

    @cached_property
    def groups(self) -> RepositoryGroup:
        """
        Provides access to the specialized repository for `Groups` entities.
        This repository is not typically scoped by `group_id` itself, as it manages groups.
        """
        # RepositoryGroup typically doesn't take group_id for its own operations
        return RepositoryGroup(self.session, PK_ID, Groups, GroupRead)

    @cached_property
    def workspace_ai_settings(self) -> GroupRepositoryGeneric[WorkspaceAISettingsRead, WorkspaceAISettingsModel]:
        """Provides access to workspace AI workflow policy settings."""
        return GroupRepositoryGeneric(self.session, PK_GROUP_ID, WorkspaceAISettingsModel, WorkspaceAISettingsRead, group_id=self.group_id)

    @cached_property
    def group_preferences(self) -> GroupRepositoryGeneric[GroupPreferencesRead, GroupPreferencesModel]:
        """
        Provides access to the repository for `GroupPreferencesModel` entities.
        Scoped by `group_id`. Uses `PK_GROUP_ID` as the match key, implying preferences
        are fetched directly using the group's ID.
        """
        return GroupRepositoryGeneric(self.session, PK_GROUP_ID, GroupPreferencesModel, GroupPreferencesRead, group_id=self.group_id)

    @cached_property
    def group_reports(self) -> GroupRepositoryGeneric[ReportRead, ReportModel]:
        """
        Provides access to the repository for `ReportModel` entities (group reports).
        Scoped by `group_id`.
        """
        return GroupRepositoryGeneric(self.session, PK_ID, ReportModel, ReportRead, group_id=self.group_id)

    @cached_property
    def group_report_entries(self) -> GroupRepositoryGeneric[ReportEntryRead, ReportEntryModel]:
        """
        Provides access to the repository for `ReportEntryModel` entities (entries within group reports).
        Scoped by `group_id` (implicitly via the report it belongs to).
        """
        return GroupRepositoryGeneric(self.session, PK_ID, ReportEntryModel, ReportEntryRead, group_id=self.group_id)

    @cached_property
    def group_invite_tokens(self) -> GroupRepositoryGeneric[InviteTokenRead, GroupInviteToken]:
        """
        Provides access to the repository for `GroupInviteToken` entities.
        Scoped by `group_id`. Uses `PK_TOKEN` as the match key for some operations.
        """
        return GroupRepositoryGeneric(
            self.session,
            PK_TOKEN,  # Match key for operations like get_one by token string
            GroupInviteToken,
            InviteTokenRead,
            group_id=self.group_id,
        )

    # ==============================================================================================================
    # Events and Webhooks related repositories
    # ==============================================================================================================

    @cached_property
    def group_event_notifier(self) -> GroupRepositoryGeneric[GroupEventNotifierRead, GroupEventNotifierModel]:
        """
        Provides access to the repository for `GroupEventNotifierModel` entities.
        These are specific notifier configurations for a group. Scoped by `group_id`.
        """
        return GroupRepositoryGeneric(
            self.session,
            PK_ID,
            GroupEventNotifierModel,
            GroupEventNotifierRead,
            group_id=self.group_id,
        )

    @cached_property
    def event_notifier_options(self) -> RepositoryGeneric[EventNotifierOptionsRead, EventNotifierOptionsModel]:
        """
        Provides access to the repository for global `EventNotifierOptionsModel` entities.
        These are system-wide notification event definitions and are not group-scoped.
        """
        # This is a global repository, so group_id is not passed.
        return RepositoryGeneric(
            self.session,
            PK_ID,
            EventNotifierOptionsModel,
            EventNotifierOptionsRead,
        )

    @cached_property
    def webhooks(self) -> GroupRepositoryGeneric[WebhookRead, GroupWebhooksModel]:
        """
        Provides access to the repository for `GroupWebhooksModel` entities (group-specific webhooks).
        Scoped by `group_id`.
        """
        return GroupRepositoryGeneric(self.session, PK_ID, GroupWebhooksModel, WebhookRead, group_id=self.group_id)

    @cached_property
    def agents(self) -> GroupRepositoryGeneric[AgentRead, WorkspaceAgentModel]:
        """Workspace-defined AI agents (system agents are code, not rows), scoped by group."""
        return GroupRepositoryGeneric(self.session, PK_ID, WorkspaceAgentModel, AgentRead, group_id=self.group_id)

    @cached_property
    def email_event_subscriptions(self) -> GroupRepositoryGeneric[EmailEventSubscriptionRead, EmailEventSubscriptionModel]:
        """Provides access to email event subscription records scoped by group."""
        return GroupRepositoryGeneric(self.session, PK_ID, EmailEventSubscriptionModel, EmailEventSubscriptionRead, group_id=self.group_id)

    def workspace_variables(self) -> GroupRepositoryGeneric[WorkspaceVariableRead, WorkspaceVariable]:
        """Provides access to workspace-scoped plain-text variables."""
        return GroupRepositoryGeneric(self.session, PK_ID, WorkspaceVariable, WorkspaceVariableRead, group_id=self.group_id)

    def workspace_secrets(self) -> GroupRepositoryGeneric[WorkspaceSecretRead, WorkspaceSecret]:
        """Provides access to workspace-scoped secrets (metadata only — no values)."""
        return GroupRepositoryGeneric(self.session, PK_ID, WorkspaceSecret, WorkspaceSecretRead, group_id=self.group_id)

    def integrations(self) -> GroupRepositoryGeneric[IntegrationRead, IntegrationModel]:
        """Provides access to workspace-scoped external service integrations."""
        return GroupRepositoryGeneric(self.session, PK_ID, IntegrationModel, IntegrationRead, group_id=self.group_id)

    def integration_event_subscriptions(
        self,
    ) -> GroupRepositoryGeneric[IntegrationEventSubscriptionRead, IntegrationEventSubscriptionModel]:
        """Integration actions wired to event types."""
        return GroupRepositoryGeneric(
            self.session, PK_ID, IntegrationEventSubscriptionModel, IntegrationEventSubscriptionRead, group_id=self.group_id
        )

    def webhook_logs(self) -> GroupRepositoryGeneric[WebhookExecutionLogRead, WebhookExecutionLogModel]:
        """Provides access to webhook execution logs scoped by group."""
        return GroupRepositoryGeneric(self.session, PK_ID, WebhookExecutionLogModel, WebhookExecutionLogRead, group_id=self.group_id)

    def notification_logs(self) -> GroupRepositoryGeneric[NotificationExecutionLogRead, NotificationExecutionLogModel]:
        """Provides access to notification execution logs scoped by group."""
        return GroupRepositoryGeneric(self.session, PK_ID, NotificationExecutionLogModel, NotificationExecutionLogRead, group_id=self.group_id)

    @cached_property
    def entry_types(self) -> EntryTypesRepository:
        """Provides access to workspace-scoped entry type records."""
        return EntryTypesRepository(self.session, self.group_id)

    @cached_property
    def entries(self) -> EntriesRepository:
        """Provides access to workspace-scoped entry records."""
        return EntriesRepository(self.session, self.group_id)

    @cached_property
    def collections(self) -> CollectionsRepository:
        """Provides access to workspace-scoped collection records."""
        return CollectionsRepository(self.session, self.group_id)

    @cached_property
    def tags(self) -> TagsRepository:
        """Provides access to the workspace's shared tag vocabulary."""
        return TagsRepository(self.session, self.group_id)

    @cached_property
    def api_clients(self) -> APIClientsRepository:
        """Provides access to workspace-scoped API client records."""
        return APIClientsRepository(self.session, self.group_id)

    @cached_property
    def resources(self) -> ResourcesRepository:
        """Provides access to workspace-scoped resource records."""
        return ResourcesRepository(self.session, self.group_id)

    @cached_property
    def assets(self) -> AssetsRepository:
        """Provides access to workspace-scoped asset records."""
        return AssetsRepository(self.session, self.group_id)

    @cached_property
    def workspace_members(self) -> RepositoryWorkspaceMembers:
        """
        Provides access to the repository for workspace member management.

        Note: This repository is NOT group-scoped as it manages memberships
        across all workspaces. Individual methods handle workspace-specific
        filtering via workspace_id parameters.
        """
        from marvin.db.models.users.workspace_members import WorkspaceMembers as WorkspaceMembersModel
        from marvin.schemas.user.user import WorkspaceMembershipRead

        return RepositoryWorkspaceMembers(
            self.session,
            PK_ID,
            WorkspaceMembersModel,
            WorkspaceMembershipRead,
        )

    @cached_property
    def event_log(self) -> EventLogRepository:
        """Provides access to workspace-scoped event log records."""
        return EventLogRepository(self.session, self.group_id)

    @cached_property
    def scheduled_tasks(self) -> ScheduledTasksRepository:
        """Provides access to workspace-scoped scheduled task records."""
        return ScheduledTasksRepository(self.session, self.group_id)

    @cached_property
    def scheduled_task_executions(self) -> ScheduledTaskExecutionLogRepository:
        """Provides access to workspace-scoped scheduled task execution logs."""
        return ScheduledTaskExecutionLogRepository(self.session, self.group_id)

    # CODE_GEN_ID: FACTORY_REPO_PROPERTIES
    # END: FACTORY_REPO_PROPERTIES

    @cached_property
    def forms(self) -> FormsRepository:
        """Provides access to workspace-scoped forms."""
        return FormsRepository(self.session, self.group_id)

    @cached_property
    def form_submissions(self) -> FormSubmissionsRepository:
        """Provides access to workspace-scoped form submissions."""
        return FormSubmissionsRepository(self.session, self.group_id)
