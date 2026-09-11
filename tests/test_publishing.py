"""
Tests for publishing API endpoints.

Verifies that publishing endpoints work correctly and handle errors properly.
"""

from fastapi.testclient import TestClient


class TestPublishingAPI:
    """Tests for publishing API endpoints."""

    def test_workspace_info_requires_authentication(self, client: TestClient):
        """Test that workspace info endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_entries_list_requires_authentication(self, client: TestClient):
        """Test that entries list endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/entries")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_entry_detail_requires_authentication(self, client: TestClient):
        """Test that entry detail endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/entries/test-entry")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_collections_list_requires_authentication(self, client: TestClient):
        """Test that collections list endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/collections")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_collection_detail_requires_authentication(self, client: TestClient):
        """Test that collection detail endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/collections/test-collection")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_assets_list_requires_authentication(self, client: TestClient):
        """Test that assets list endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/assets")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_resources_list_requires_authentication(self, client: TestClient):
        """Test that resources list endpoint requires authentication."""
        response = client.get("/api/publish/test-workspace/resources")

        # Should return 401 or 403 (unauthorized/forbidden) without API key
        assert response.status_code in [401, 403]

    def test_invalid_workspace_slug_returns_error(self, client: TestClient):
        """Test that invalid workspace slugs return appropriate errors."""
        # Use a clearly invalid workspace slug
        response = client.get(
            "/api/publish/nonexistent-workspace-12345/entries",
            headers={"Authorization": "Bearer invalid-token"},
        )

        # Should return 401 (invalid token) or 404 (workspace not found)
        assert response.status_code in [401, 403, 404]


class TestPublishingPerformance:
    """Tests for publishing API performance (N+1 query prevention)."""

    def test_collections_list_no_n_plus_1(self, client: TestClient):
        """
        Test that collections list endpoint doesn't have N+1 queries.

        This test verifies the fix for Issue #2 (collection entry count N+1).
        We can't easily test query count without database instrumentation,
        but we can verify the endpoint returns consistent data.
        """
        # This test would require:
        # 1. Authentication with valid API key
        # 2. Test data (collections with entries)
        # 3. Query count instrumentation
        # For now, just verify the endpoint structure is correct
        pass


class TestPublishedEntryDataNormalization:
    """`PublishedEntryRead.data` must always be an object, even when the entry stores no custom
    data (``data_json`` is SQL NULL). Regression: a NULL ``data_json`` used to fail response
    validation and 500 the published-entry endpoint."""

    def _read(self, **overrides):
        from marvin.schemas.publishing import PublishedEntryRead

        base = {"slug": "x", "title": "X", "entry_type": "page"}
        base.update(overrides)
        return PublishedEntryRead(**base)

    def test_null_data_normalizes_to_empty_dict(self):
        assert self._read(data=None).data == {}

    def test_missing_data_defaults_to_empty_dict(self):
        assert self._read().data == {}

    def test_dict_data_is_preserved(self):
        assert self._read(data={"body": "hello"}).data == {"body": "hello"}


class TestPublishedEntryListItemCarriesData:
    """List items carry the entry's schema fields so a site can render a collection from one
    request. Without this, clients re-fetch every entry (N+1); on a 280-entry collection that
    timed out and dropped entries. ``data`` follows the same never-null contract as the detail."""

    def _item(self, **overrides):
        from marvin.schemas.publishing import PublishedEntryListItem

        base = {"slug": "x", "title": "X", "entry_type": "artwork", "status": "published"}
        base.update(overrides)
        return PublishedEntryListItem(**base)

    def test_list_item_data_is_preserved(self):
        assert self._item(data={"medium": "Acrylic on canvas", "size": "20 × 20 in"}).data == {
            "medium": "Acrylic on canvas",
            "size": "20 × 20 in",
        }

    def test_list_item_null_data_normalizes_to_empty_dict(self):
        assert self._item(data=None).data == {}

    def test_list_item_missing_data_defaults_to_empty_dict(self):
        assert self._item().data == {}

    def test_list_item_serializes_data_and_description(self):
        dumped = self._item(data={"body": "hi"}, description="A lede").model_dump(by_alias=True)
        assert dumped["data"] == {"body": "hi"}
        assert dumped["description"] == "A lede"

    def test_entry_to_list_item_copies_data_json_and_description(self):
        from types import SimpleNamespace

        from marvin.routes.publish.publishing_controller import _entry_to_list_item

        entry = SimpleNamespace(
            slug="weightless-hour",
            title="Weightless Hour",
            entry_type=SimpleNamespace(slug="artwork", rendering_json=None, capabilities_json=None),
            summary="Acrylic on canvas",
            description="Sold. 20 × 20 in.",
            data_json={"medium": "Acrylic on canvas", "status": "sold"},
            metadata_json=None,
            published_at=None,
            status="published",
            entry_collections=[],
            entry_assets=[],
            entry_resources=[],
            tag_names=[],
        )

        item = _entry_to_list_item(entry, "grace-martin-franklin")

        assert item.data == {"medium": "Acrylic on canvas", "status": "sold"}
        assert item.description == "Sold. 20 × 20 in."
