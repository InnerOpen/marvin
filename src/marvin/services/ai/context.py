"""
ContextBuilder — assembles structured context from Marvin objects before prompt construction.

Usage:
    ctx = (
        ContextBuilder(session, group_id)
        .with_site_settings()
        .with_variables()
        .with_entry(entry_id)
        .with_assets(entry_id)
        .inject("current_date", "2026-07-17")
        .build()
    )
"""

from datetime import UTC, datetime

from pydantic import UUID4
from sqlalchemy.orm import Session

from .operations.base import OperationContext


class ContextBuilder:
    def __init__(self, session: Session, group_id: UUID4) -> None:
        self._session = session
        self._group_id = group_id
        self._ctx = OperationContext()
        self._runtime: dict = {}

    # ── Fluent builders ────────────────────────────────────────────────

    def with_site_settings(self) -> "ContextBuilder":
        """Load workspace name and site preferences."""
        from marvin.db.models.groups.groups import Groups
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        group = self._session.get(Groups, self._group_id)
        if group:
            self._ctx.workspace_name = group.name

        prefs = self._session.query(GroupPreferencesModel).filter_by(group_id=self._group_id).first()
        if prefs:
            self._ctx.site_title = prefs.site_title or ""
            self._ctx.site_locale = prefs.site_locale or "en-US"
            # Pull ai-specific config from site_metadata_json.ai
            ai_cfg = (prefs.site_metadata_json or {}).get("ai", {})
            for key, val in ai_cfg.items():
                self._ctx.variables[f"AI_{key.upper()}"] = str(val)

        return self

    def with_variables(self, slugs: list[str] | None = None) -> "ContextBuilder":
        """Load workspace variables (and secrets slugs) into context for {{SLUG}} resolution."""
        from marvin.db.models.groups.variables import WorkspaceVariable

        q = self._session.query(WorkspaceVariable).filter_by(group_id=self._group_id)
        if slugs:
            q = q.filter(WorkspaceVariable.slug.in_(slugs))
        for var in q.all():
            self._ctx.variables[var.slug] = var.value
        return self

    def with_entry(self, entry_id: UUID4) -> "ContextBuilder":
        """Load a single entry as the primary context object."""
        from marvin.db.models.platform.entries import Entries
        from marvin.db.models.platform.entry_types import EntryTypes

        entry = self._session.get(Entries, entry_id)
        # Scope to the caller's workspace, exactly as with_asset/with_resource do. Without this
        # a caller-supplied UUID from another workspace would be loaded into the AI context.
        if not entry or entry.group_id != self._group_id:
            return self
        entry_type = self._session.get(EntryTypes, entry.entry_type_id) if entry.entry_type_id else None
        self._ctx.entry = {
            "id": str(entry.id),
            "title": entry.title or "",
            "summary": entry.summary or "",
            "description": entry.description or "",
            "status": entry.status or "",
            "content": str(entry.data_json or ""),
            "entry_type": entry_type.name if entry_type else "",
        }
        # Inject entry fields as runtime variables for {{SLUG}} resolution
        self._runtime["entry_title"] = entry.title or ""
        self._runtime["entry_type"] = entry_type.name if entry_type else ""
        return self

    def with_related_entries(self, entry_id: UUID4, limit: int = 5) -> "ContextBuilder":
        """Load entries that share a collection with the given entry."""
        from sqlalchemy import and_, select

        from marvin.db.models.platform.entries import Entries
        from marvin.db.models.platform.entry_collections import EntryCollections

        collection_ids = self._session.execute(select(EntryCollections.collection_id).where(EntryCollections.entry_id == entry_id)).scalars().all()

        if not collection_ids:
            return self

        related = (
            self._session.execute(
                select(Entries)
                .join(EntryCollections, Entries.id == EntryCollections.entry_id)
                .where(
                    and_(
                        EntryCollections.collection_id.in_(collection_ids),
                        Entries.id != entry_id,
                        Entries.group_id == self._group_id,
                    )
                )
                .limit(limit)
            )
            .scalars()
            .all()
        )

        self._ctx.variables["related_entries"] = "; ".join(e.title or "" for e in related)
        return self

    def _asset_dict(self, a) -> dict:
        return {
            "id": str(a.id),
            "name": a.name,
            "mime_type": a.mime_type,
            "storage_key": a.storage_key,
            "storage_provider": a.storage_provider,
            "width": a.width,
            "height": a.height,
            "alt_text": a.alt_text or "",
            "description": a.description or "",
        }

    def with_asset(self, asset_id: UUID4) -> "ContextBuilder":
        """Load a single asset directly as the primary asset (e.g. for vision operations)."""
        from marvin.db.models.platform.assets import Assets

        a = self._session.get(Assets, asset_id)
        if a and a.group_id == self._group_id:
            self._ctx.assets = [self._asset_dict(a)]
        return self

    def with_assets(self, entry_id: UUID4 | None = None) -> "ContextBuilder":
        """Load assets — entry-linked, or all workspace assets when entry_id is None."""
        from marvin.db.models.platform.assets import Assets

        if entry_id:
            from sqlalchemy import select

            from marvin.db.models.platform.entry_assets import EntryAssets

            asset_ids = self._session.execute(select(EntryAssets.asset_id).where(EntryAssets.entry_id == entry_id)).scalars().all()
            assets = [self._session.get(Assets, aid) for aid in asset_ids]
            assets = [a for a in assets if a]
        else:
            assets = self._session.query(Assets).filter_by(group_id=self._group_id).limit(10).all()

        self._ctx.assets = [self._asset_dict(a) for a in assets]
        return self

    def with_asset_images(self, limit: int = 4) -> "ContextBuilder":
        """Base64-encode raw bytes for image assets already in context (for vision ops)."""
        import base64

        from marvin.services.storage.provider_factory import get_storage_provider

        loaded = 0
        for asset in self._ctx.assets:
            if loaded >= limit:
                break
            mime = asset.get("mime_type") or ""
            if not mime.startswith("image/") or not asset.get("storage_key"):
                continue
            try:
                fh = get_storage_provider().get(asset["storage_key"])
                asset["image_data"] = base64.b64encode(fh.read()).decode("ascii")
                loaded += 1
            except Exception:
                continue  # skip unreadable assets rather than failing the whole operation
        return self

    def with_resources(self, entry_id: UUID4 | None = None) -> "ContextBuilder":
        """Load resources linked to an entry, or all workspace resources."""
        from marvin.db.models.platform.resources import Resources

        if entry_id:
            from sqlalchemy import select

            from marvin.db.models.platform.entry_resources import EntryResources

            resource_ids = self._session.execute(select(EntryResources.resource_id).where(EntryResources.entry_id == entry_id)).scalars().all()
            resources = [self._session.get(Resources, rid) for rid in resource_ids]
            resources = [r for r in resources if r]
        else:
            resources = self._session.query(Resources).filter_by(group_id=self._group_id).limit(10).all()

        self._ctx.resources = [{"id": str(r.id), "name": r.name, "type": r.resource_type, "description": r.description or ""} for r in resources]
        return self

    def with_resource(self, resource_id: UUID4) -> "ContextBuilder":
        """Load a single resource directly as the primary resource (e.g. for enrichment)."""
        from marvin.db.models.platform.resources import Resources

        r = self._session.get(Resources, resource_id)
        if r and r.group_id == self._group_id:
            self._ctx.resources = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "type": r.resource_type,
                    "description": r.description or "",
                    "url": r.url or "",
                    "metadata": r.metadata_json or {},
                }
            ]
        return self

    def with_form_submission(self, submission_id: UUID4) -> "ContextBuilder":
        from marvin.db.models.platform.form_submissions import FormSubmissions

        sub = self._session.get(FormSubmissions, submission_id)
        if sub:
            self._ctx.form_submission = {
                "id": str(sub.id),
                "data": sub.data_json or {},
                "status": sub.status or "",
                "submitted_at": str(sub.submitted_at or ""),
            }
        return self

    def with_semantic_search(self, query: str, provider, model: str, limit: int = 5, entity_types: list[str] | None = None) -> "ContextBuilder":
        """Embed `query` via `provider` and load the top-`limit` similar workspace chunks (RAG)."""
        if not query or not model:
            return self
        from marvin.services.ai.embeddings import search_embeddings

        try:
            qvec = provider.embed([query], model)[0]
        except Exception:
            return self  # embedding unavailable — proceed without retrieval
        self._ctx.retrieved = search_embeddings(self._session, self._group_id, qvec, limit, entity_types)
        return self

    def inject(self, key: str, value: str) -> "ContextBuilder":
        """Inject a runtime variable (e.g. current_date) for {{SLUG}} resolution."""
        self._runtime[key] = value
        return self

    def build(self) -> OperationContext:
        """Finalise context with runtime injections."""
        self._runtime.setdefault("current_date", datetime.now(UTC).strftime("%Y-%m-%d"))
        self._runtime.setdefault("workspace_name", self._ctx.workspace_name)
        self._runtime.setdefault("site_title", self._ctx.site_title)
        # Make runtime values available as variables for resolve()
        self._ctx.variables.update(self._runtime)
        return self._ctx


def resolve_prompt_messages(messages, group_id: UUID4, runtime: dict | None = None) -> list:
    """
    Run resolve() over every message's string content to interpolate {{SLUG}} references.
    Secrets, workspace variables, and runtime context all resolve in one pass.
    """
    from marvin.services.secrets.resolver import resolve

    resolved = []
    for msg in messages:
        if isinstance(msg.content, str):
            content = resolve(msg.content, group_id=group_id, context=runtime or {})
        else:
            content = msg.content  # multimodal list — skip interpolation
        from marvin.services.ai.base import Message

        resolved.append(Message(role=msg.role, content=content))
    return resolved
