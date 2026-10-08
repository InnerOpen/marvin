from . import (
    builtins,  # registers all built-in tools on import  # noqa: F401
    builtins_actions,  # registers write/action tools (attach/detach resource)  # noqa: F401
    builtins_agents,  # registers list_agents / run_agent (external interop with workspace agents)  # noqa: F401
    builtins_archive,  # registers archive_entries (retire an entry, keeping it)  # noqa: F401
    builtins_authoring,  # registers authoring tools (compose_entry / revise_entry)  # noqa: F401
    builtins_docs,  # registers search_docs / read_doc (Marvin's own user manual)  # noqa: F401
    builtins_insights,  # registers insights tools (executions/events/tasks)  # noqa: F401
    builtins_media,  # registers add_embed (staged) / preview_embed (media players)  # noqa: F401
    builtins_overview,  # registers workspace_overview (what the workspace contains + index coverage)  # noqa: F401
    builtins_trash,  # registers trash_entries (Delete: to the Trash, restorable; never emptied by AI)  # noqa: F401
    builtins_vision,  # registers view_image (read-only look at an image asset)  # noqa: F401
    builtins_workflows,  # registers workflow_authoring_guide / get_workflow / draft_workflow / update_workflow_draft  # noqa: F401
)
from .base import (
    TOOL_REGISTRY,
    ToolContext,
    ToolSpec,
    get_tool,
    list_tools,
    register_tool,
)

__all__ = [
    "TOOL_REGISTRY",
    "ToolContext",
    "ToolSpec",
    "get_tool",
    "list_tools",
    "register_tool",
]
