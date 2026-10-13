"""Entry domain service — the one place that owns entry mutations *and* their events."""

from .entry_service import EntryService

__all__ = ["EntryService"]
