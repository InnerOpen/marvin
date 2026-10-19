"""Unit tests for AIOperationsController._resolve_entity_id.

Ops accept a UUID or a slug for entity_id (MCP/CLI callers work in slugs); this resolver
normalizes a UUID and resolves a slug → the entity's id for entry/asset/resource.
"""

import uuid
from unittest.mock import MagicMock

from marvin.routes.ai.operations_controller import AIOperationsController
from tests.test_remote_mcp_oauth import ws  # noqa: F401 — the fixture


def _ctrl(row=None):
    fake = MagicMock()
    fake.session.query.return_value.filter_by.return_value.first.return_value = row
    return fake


def test_none_passes_through():
    assert AIOperationsController._resolve_entity_id(_ctrl(), "resource", None) is None


def test_uuid_is_normalized_and_returned():
    u = str(uuid.uuid4())
    result = AIOperationsController._resolve_entity_id(_ctrl(), "resource", u)
    assert str(result) == u
    assert isinstance(result, uuid.UUID)


def test_unknown_entity_type_returns_input_unchanged():
    assert AIOperationsController._resolve_entity_id(_ctrl(), "widget", "some-slug") == "some-slug"


def test_slug_resolves_to_entity_id():
    row = MagicMock()
    row.id = "resolved-id"
    assert AIOperationsController._resolve_entity_id(_ctrl(row), "resource", "merino-wool") == "resolved-id"


def test_unresolvable_slug_returns_input():
    # no matching row → return the input so downstream loaders 404 as before
    assert AIOperationsController._resolve_entity_id(_ctrl(None), "entry", "ghost-slug") == "ghost-slug"


def test_a_slug_that_parses_as_a_uuid_still_resolves(db_session, ws):  # noqa: F811 — the fixture
    """An Instagram import slugs assets by a 32-digit media id, which uuid.UUID() accepts: it isn't an id here, so the
    slug lookup must still run (every by-slug tool call failed for those assets before)."""
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.entity_resolve import resolve_entity_id

    owner = ws()
    slug = "17915046677254758672811514388894"
    asset = Assets(
        session=db_session, group_id=owner.gid, slug=slug, name="Post", original_filename="p.jpg", filename="p", extension="jpg",
        file_size=1, mime_type="image/jpeg", asset_type="image", checksum=uuid.uuid4().hex, storage_provider="local",
        storage_key=f"lib/{owner.gid.hex}", uploaded_by=owner.uid,
    )  # fmt: skip
    db_session.add(asset)
    db_session.commit()
    try:
        assert resolve_entity_id(db_session, owner.gid, "asset", slug) == asset.id
        assert resolve_entity_id(db_session, owner.gid, "asset", str(asset.id)) == asset.id
        unknown = uuid.uuid4()
        assert resolve_entity_id(db_session, owner.gid, "asset", str(unknown)) == unknown  # still a UUID: loaders 404 as before
    finally:
        db_session.query(Assets).filter(Assets.group_id == owner.gid).delete()
        db_session.commit()
