"""Platform models."""

from .api_clients import APIClients
from .asset_tags import AssetTags
from .assets import Assets
from .collection_assets import CollectionAssets
from .collection_resources import CollectionResources
from .collections import Collections
from .entries import Entries
from .entry_assets import EntryAssets
from .entry_collections import EntryCollections
from .entry_resources import EntryResources
from .entry_tags import EntryTags
from .entry_types import EntryTypes
from .event_log import EventLogModel
from .resource_tags import ResourceTags
from .resources import Resources
from .scheduled_tasks import ScheduledTaskExecutionLogModel, ScheduledTaskModel
from .scheduler_lock import SCHEDULER_LOCK_ID, SchedulerLockModel
from .submission_rate_limits import SubmissionRateLimits
from .tags import Tags

# isort: split
# CODE_GEN_ID: PLATFORM_MODEL_IMPORTS
# END: PLATFORM_MODEL_IMPORTS

__all__ = [
    "APIClients",
    "AssetTags",
    "Assets",
    "CollectionAssets",
    "CollectionResources",
    "Collections",
    "Entries",
    "EntryAssets",
    "EntryCollections",
    "EntryResources",
    "EntryTags",
    "EntryTypes",
    "EventLogModel",
    "ResourceTags",
    "Resources",
    "SCHEDULER_LOCK_ID",
    "ScheduledTaskExecutionLogModel",
    "ScheduledTaskModel",
    "SchedulerLockModel",
    "SubmissionRateLimits",
    "Tags",
    # CODE_GEN_ID: PLATFORM_MODEL_ALL
    # END: PLATFORM_MODEL_ALL
]
