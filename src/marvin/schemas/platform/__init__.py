"""Platform schemas."""

from .api_clients import (
    APIClientCreate,
    APIClientRead,
    APIClientSummary,
    APIClientUpdate,
    APIClientWithToken,
)
from .assets import (
    AssetCreate,
    AssetCreateInternal,
    AssetPlacement,
    AssetRead,
    AssetSummary,
    AssetUpdate,
    AssetUploadRequest,
    EntryAssetRead,
)
from .collections import (
    CollectionCreate,
    CollectionRead,
    CollectionSummary,
    CollectionUpdate,
    EntryCollectionRead,
    SmartRulesPreview,
    SmartRulesPreviewRequest,
    UpdateEntryCollectionRequest,
)
from .entries import (
    AssetAttachment,
    CollectionAttachment,
    EntryCreate,
    EntryRead,
    EntrySummary,
    EntryUpdate,
    ResourceAttachment,
)
from .entry_types import (
    EntryTypeCreate,
    EntryTypeRead,
    EntryTypeSummary,
    EntryTypeUpdate,
)
from .event_log import EventLogRead, EventLogSummary
from .resources import (
    EntryResourceRead,
    ResourceCreate,
    ResourcePlacement,
    ResourceRead,
    ResourceSummary,
    ResourceUpdate,
)
from .scheduled_tasks import (
    ScheduledTaskCreate,
    ScheduledTaskExecutionLogRead,
    ScheduledTaskRead,
    ScheduledTaskSummary,
    ScheduledTaskUpdate,
)
from .tags import (
    TagCreate,
    TagRead,
    TagSummary,
    TagUpdate,
)

# isort: split
# CODE_GEN_ID: PLATFORM_SCHEMA_IMPORTS
# END: PLATFORM_SCHEMA_IMPORTS

__all__ = [
    "APIClientCreate",
    "APIClientRead",
    "APIClientSummary",
    "APIClientUpdate",
    "APIClientWithToken",
    "AssetCreate",
    "AssetCreateInternal",
    "AssetPlacement",
    "AssetRead",
    "AssetSummary",
    "AssetUpdate",
    "AssetUploadRequest",
    "CollectionAttachment",
    "CollectionCreate",
    "CollectionRead",
    "CollectionSummary",
    "CollectionUpdate",
    "EntryCollectionRead",
    "SmartRulesPreview",
    "SmartRulesPreviewRequest",
    "UpdateEntryCollectionRequest",
    "AssetAttachment",
    "EntryAssetRead",
    "EntryCreate",
    "EntryRead",
    "EntrySummary",
    "EntryTypeCreate",
    "EntryTypeRead",
    "EntryTypeSummary",
    "EntryTypeUpdate",
    "EntryUpdate",
    "EventLogRead",
    "EventLogSummary",
    "EntryResourceRead",
    "ResourceAttachment",
    "ResourceCreate",
    "ResourcePlacement",
    "ResourceRead",
    "ResourceSummary",
    "ResourceUpdate",
    "ScheduledTaskCreate",
    "ScheduledTaskExecutionLogRead",
    "ScheduledTaskRead",
    "ScheduledTaskSummary",
    "ScheduledTaskUpdate",
    "TagCreate",
    "TagRead",
    "TagSummary",
    "TagUpdate",
    # CODE_GEN_ID: PLATFORM_SCHEMA_ALL
    # END: PLATFORM_SCHEMA_ALL
    # Legacy aliases for backward compatibility
    "SiteClientCreate",
    "SiteClientRead",
    "SiteClientUpdate",
]

# Legacy aliases for backward compatibility with frontend
SiteClientCreate = APIClientCreate
SiteClientRead = APIClientRead
SiteClientUpdate = APIClientUpdate

# Rebuild models to resolve forward references after all schemas are imported
EntryRead.model_rebuild()
EntrySummary.model_rebuild()
