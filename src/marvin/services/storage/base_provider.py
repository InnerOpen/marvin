"""The storage provider contract, re-exported from the plugin SDK.

The contract lives in ``marvin_integration_sdk.storage`` so storage plugins depend on the SDK, not on
Marvin core. ``BaseStorageProvider`` is the name core always used for it.
"""

from marvin_integration_sdk.storage import StorageMetadata, StorageProvider

BaseStorageProvider = StorageProvider

__all__ = ["BaseStorageProvider", "StorageMetadata", "StorageProvider"]
