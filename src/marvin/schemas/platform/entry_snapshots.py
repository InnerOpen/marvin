"""Entry snapshots (services/snapshots.py): a kept version of an entry, and what putting it back changes."""

from typing import Any, Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel

SnapshotPart = Literal["content", "collections", "assets", "status"]


class EntrySnapshotCreate(_MarvinModel):
    label: str = Field(default="", max_length=100)
    """What to call it ("before the refresh")."""


class EntrySnapshotRead(_MarvinModel):
    id: UUID4
    entry_id: UUID4
    label: str
    source: str
    """workflow | api."""
    created_at: str | None = None
    title: str | None = None
    status: str | None = None
    fields: int
    """How many data fields it holds."""
    collections: list[str]
    assets: int
    created: bool | None = None
    """On a capture: False when the entry's latest snapshot was already this content and was returned instead."""


class EntrySnapshotRestore(_MarvinModel):
    parts: list[SnapshotPart] | None = None
    """What to put back; default content, collections and assets. `status` only when listed."""


class EntrySnapshotDiff(_MarvinModel):
    snapshot_id: UUID4
    entry_id: UUID4
    parts: list[str]
    changed: bool
    restored: bool | None = None
    """Only on a restore: whether anything was written."""
    content: dict[str, Any] | None = None
    """{field: {before, after}} for what differs (long values are cut)."""
    status: dict[str, Any] | None = None
    collections: dict[str, list[str]] | None = None
    assets: dict[str, list[str]] | None = None
