"""The AI provider contract — it lives in the plugin SDK (``marvin_integration_sdk.ai``).

Re-exported here so the many ``from marvin.services.ai.base import …`` imports keep working. Providers,
built in or installed as ``marvin.ai_providers`` plugins, implement the same ``AIProvider``; see
registry.py for how one is chosen.
"""

from marvin_integration_sdk.ai import (
    AIConfigError,
    AIProvider,
    AIProviderPlugin,
    CompletionOptions,
    CompletionResult,
    Credential,
    ImagePart,
    Message,
    ModelPrice,
    ToolCall,
    ToolDefinition,
    deserialize_messages,
    serialize_messages,
)

__all__ = [
    "AIConfigError",
    "AIProvider",
    "AIProviderPlugin",
    "CompletionOptions",
    "CompletionResult",
    "Credential",
    "ImagePart",
    "Message",
    "ModelPrice",
    "ToolCall",
    "ToolDefinition",
    "deserialize_messages",
    "serialize_messages",
]
