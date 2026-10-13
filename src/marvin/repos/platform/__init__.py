"""Platform repositories."""

from .api_clients import APIClientsRepository
from .assets import AssetsRepository
from .collections import CollectionsRepository
from .entries import EntriesRepository
from .entry_types import EntryTypesRepository
from .event_log import EventLogRepository
from .form_submissions import FormSubmissionsRepository
from .forms import FormsRepository
from .resources import ResourcesRepository
from .scheduled_tasks import ScheduledTaskExecutionLogRepository, ScheduledTasksRepository
from .tags import TagsRepository

# isort: split
# CODE_GEN_ID: PLATFORM_REPO_IMPORTS
# END: PLATFORM_REPO_IMPORTS

__all__ = [
    "APIClientsRepository",
    "AssetsRepository",
    "CollectionsRepository",
    "EntriesRepository",
    "EntryTypesRepository",
    "EventLogRepository",
    "FormsRepository",
    "FormSubmissionsRepository",
    "ResourcesRepository",
    "ScheduledTaskExecutionLogRepository",
    "ScheduledTasksRepository",
    "TagsRepository",
    # CODE_GEN_ID: PLATFORM_REPO_ALL
    # END: PLATFORM_REPO_ALL
]
