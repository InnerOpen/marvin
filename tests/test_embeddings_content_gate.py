"""The content gate keeps thin objects out of the semantic index.

A bare icon/logo asset (name + tags only) embeds to near-nothing but its tag and hijacks
tag-adjacent searches. The `content_ok` predicate — honored by both the reactive listener and the
full reindex — excludes it. Its tags stay discoverable via list_tags / structured filters, not RAG.
"""

from types import SimpleNamespace

from marvin.services.ai.embeddings_registry import REGISTRY, _asset_content_ok


def _asset(description=None, alt_text=None):
    return SimpleNamespace(name="Envelope", description=description, alt_text=alt_text)


def test_thin_asset_excluded_rich_asset_kept():
    assert _asset_content_ok(_asset()) is False  # name + tags only → thin
    assert _asset_content_ok(_asset(description="  ")) is False  # whitespace doesn't count
    assert _asset_content_ok(_asset(description="A waxed canvas tote")) is True
    assert _asset_content_ok(_asset(alt_text="Envelope icon, line art")) is True


def test_asset_descriptor_wires_the_gate():
    # assets carry the content gate; entries are searchable only while published; resources always index;
    # an asset or resource in the Trash never does
    from datetime import UTC, datetime
    from types import SimpleNamespace

    rich = SimpleNamespace(name="Tote", description="A waxed canvas tote", alt_text=None, trashed_at=None)
    assert REGISTRY["asset"].content_ok(rich) is True
    assert REGISTRY["asset"].content_ok(_asset()) is False
    assert REGISTRY["entry"].content_ok(SimpleNamespace(status="published")) is True
    assert REGISTRY["entry"].content_ok(SimpleNamespace(status="draft")) is False
    assert REGISTRY["resource"].content_ok(_asset()) is True
    trashed = SimpleNamespace(**{**vars(rich), "trashed_at": datetime.now(UTC)})
    assert REGISTRY["asset"].content_ok(trashed) is False
    assert REGISTRY["resource"].content_ok(trashed) is False
