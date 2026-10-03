"""
Docs tools — Marvin's own user manual, searchable and readable by agents (category `docs_read`).

Asked "how do I bulk-update entries?", an agent without these guesses at screens and labels. The
manual bundled with this install (services/docs.py) is the answer that matches the running version,
so agents search it, read the section, and cite the published page.

Docs are not workspace data: the handlers ignore the workspace and never touch the database. They
are projected to MarvinMCP like every registry tool (`marvin_search_docs`, `marvin_read_doc`).
"""

from __future__ import annotations

import json

from marvin.services.ai.operations.base import ROLE_VIEWER
from marvin.services.docs import DEFAULT_SEARCH_LIMIT, DOCS_UNAVAILABLE, MAX_SEARCH_LIMIT, clamp_limit, get_docs

from .base import ToolContext, register_tool


def _unavailable() -> str:
    return json.dumps({"available": False, "error": DOCS_UNAVAILABLE})


@register_tool(
    name="search_docs",
    description=(
        "Search Marvin's own user manual — how Marvin works: settings, workflows, agents, integrations, collections, "
        "webhooks, scheduled tasks, the admin screens and their labels. Returns the best-matching sections, each with "
        "its page, heading, anchor, a snippet and the published `url`. Use it for how-to questions about Marvin itself "
        "('how do I…', 'what does … do'), then read_doc for the full section; cite the url. It does not search this "
        "workspace's content (use search_content for that)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords or a question, e.g. 'bulk update entries' or 'monthly cost limit'."},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SEARCH_LIMIT,
                "description": f"How many sections to return (default {DEFAULT_SEARCH_LIMIT}).",
            },
        },
        "required": ["query"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def search_docs(_ctx: ToolContext, args: dict) -> str:
    docs = get_docs()
    if not docs.available:
        return _unavailable()
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    results = docs.search(query, clamp_limit(args.get("limit", DEFAULT_SEARCH_LIMIT)))
    note = (
        "Read a section in full with read_doc(path=page, section=anchor) before giving steps; cite its url."
        if results
        else "No section of the manual matches. Try other words, or say the manual does not cover it — do not guess."
    )
    return json.dumps({"query": query, "results": results, "note": note})


@register_tool(
    name="read_doc",
    description=(
        "Read a page of Marvin's user manual as markdown, or one section of it. `path` is a page path from "
        "search_docs (e.g. 'whats-new/workflows.md'; the published URL also works); `section` is an anchor or heading "
        "from search_docs (e.g. 'run-on-a-query-of-entries'). Without a section you get the whole page plus its outline."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Page path, e.g. 'whats-new/workflows.md'."},
            "section": {"type": "string", "description": "Optional anchor or heading text of one section."},
        },
        "required": ["path"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def read_doc(_ctx: ToolContext, args: dict) -> str:
    docs = get_docs()
    if not docs.available:
        return _unavailable()
    path = str(args.get("path") or "").strip()
    section = str(args.get("section") or "").strip() or None
    found = docs.read_page(path, section)
    if found is None:
        return json.dumps({"error": f"No manual page '{path}'.", "pages": docs.list_pages()})
    return json.dumps(found)
