"""Storage provider system for asset management.

The contract (``StorageProvider``, ``BackupTarget``, ``StoragePlugin``…) is the plugin SDK's
(``marvin_integration_sdk.storage``), re-exported here so core imports keep working. Core ships the
built-in ``local`` provider; installed storage plugins add theirs (see ``registry``).
"""

from marvin_integration_sdk.storage import BackupTarget, Setting, StorageConfigError, StoragePlugin, TargetObject

from .base_provider import BaseStorageProvider, StorageMetadata, StorageProvider
from .local_provider import LocalStorageProvider
from .provider_factory import get_storage_provider, provider_for, validate_storage_config

__all__ = [
    "BackupTarget",
    "BaseStorageProvider",
    "LocalStorageProvider",
    "Setting",
    "StorageConfigError",
    "StorageMetadata",
    "StoragePlugin",
    "StorageProvider",
    "TargetObject",
    "get_storage_provider",
    "provider_for",
    "validate_storage_config",
]
