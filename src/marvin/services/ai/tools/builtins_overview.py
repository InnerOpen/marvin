"""
Workspace overview tool — what the workspace contains, in numbers.

Semantic search answers "find me X"; it cannot answer "what is in here at all?" — the question users
ask as "summarise the RAG / what do you know?". This read-only tool answers that corpus-level
question: entries by type and status, collections, assets, resources, tags, and how much of it the
embedding index actually covers.
"""

from __future__ import annotations

import json

from sqlalchemy import func

from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform import EntryCollections
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.resources import Resources
from marvin.db.models.platform.tags import Tags
from marvin.services.ai.operations.base import ROLE_VIEWER

from .base import ToolContext, register_tool


@register_tool(
    name="workspace_overview",
    description=(
        "Summarise what this workspace CONTAINS: entries by type and status, collections with sizes, assets, "
        "resources, tags, and how much of it the semantic index (the 'RAG' / knowledge base) covers. Call this "
        "first when the user asks what is in the workspace, what you know, or for a summary of the RAG/index; "
        "then use search_content or the list tools for specifics."
    ),
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_VIEWER,
    read_only=True,
)
def workspace_overview(ctx: ToolContext, _args: dict) -> str:
    s, g = ctx.session, ctx.group_id
    group = s.query(Groups).filter(Groups.id == g).first()

    by_type: dict[str, dict] = {}
    for slug, name, status, n in (
        s.query(EntryTypes.slug, EntryTypes.name, Entries.status, func.count(Entries.id))
        .join(Entries, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.group_id == g)
        .group_by(EntryTypes.slug, EntryTypes.name, Entries.status)
        .all()
    ):
        t = by_type.setdefault(slug, {"slug": slug, "name": name, "total": 0, "byStatus": {}})
        t["total"] += n
        t["byStatus"][status] = n
    entries_total = sum(t["total"] for t in by_type.values())

    collections = [
        {"slug": slug, "name": name, "entries": n}
        for slug, name, n in (
            s.query(Collections.slug, Collections.name, func.count(EntryCollections.id))
            .outerjoin(EntryCollections, EntryCollections.collection_id == Collections.id)
            .filter(Collections.group_id == g)
            .group_by(Collections.id, Collections.slug, Collections.name)
            .order_by(Collections.name)
            .all()
        )
    ]
    assets = dict(s.query(Assets.asset_type, func.count(Assets.id)).filter(Assets.group_id == g).group_by(Assets.asset_type).all())
    resources = dict(
        s.query(Resources.resource_type, func.count(Resources.id)).filter(Resources.group_id == g).group_by(Resources.resource_type).all()
    )
    tags = s.query(func.count(Tags.id)).filter(Tags.group_id == g).scalar() or 0

    totals = {"entry": entries_total, "asset": sum(assets.values()), "resource": sum(resources.values())}
    index = {}
    for entity_type, indexed, chunks in (
        s.query(AIEmbeddingModel.entity_type, func.count(func.distinct(AIEmbeddingModel.entity_id)), func.count(AIEmbeddingModel.id))
        .filter(AIEmbeddingModel.group_id == g)
        .group_by(AIEmbeddingModel.entity_type)
        .all()
    ):
        index[entity_type] = {"indexed": indexed, "total": totals.get(entity_type), "chunks": chunks}
    for entity_type, total in totals.items():
        index.setdefault(entity_type, {"indexed": 0, "total": total, "chunks": 0})

    return json.dumps(
        {
            "workspace": {"name": getattr(group, "name", None), "slug": getattr(group, "slug", None)},
            "entries": {"total": entries_total, "byType": sorted(by_type.values(), key=lambda t: -t["total"])},
            "collections": collections,
            "assets": {"total": totals["asset"], "byType": assets},
            "resources": {"total": totals["resource"], "byType": resources},
            "tags": tags,
            "index": index,
            "note": "index = what semantic search (search_content) can see; unindexed items are only reachable by the list/get tools.",
        }
    )
