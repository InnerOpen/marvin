"""Integration tests for asset upload and storage subsystem."""

import io
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from marvin.app import app
from marvin.core.settings import get_app_settings
from marvin.db.db_setup import Base, generate_session
from marvin.db.models.groups import Groups
from marvin.db.models.platform import Assets
from marvin.db.models.users import Users
from marvin.repos.platform.assets import AssetsRepository


@pytest.fixture(scope="function")
def test_db():
    """Create a test database for each test."""
    # Use in-memory SQLite for tests
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_generate_session():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[generate_session] = override_generate_session

    yield TestSessionLocal()

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def test_workspace(test_db: Session):
    """Create a test workspace."""
    workspace = Groups(slug="test-workspace", name="Test Workspace", email="test@example.com")
    test_db.add(workspace)
    test_db.commit()
    test_db.refresh(workspace)
    return workspace


@pytest.fixture
def test_user(test_db: Session, test_workspace: Groups):
    """Create a test user."""
    user = Users(email="test@example.com", username="testuser", hashed_password="fake_hash", group_id=test_workspace.id)
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture
def test_image():
    """Create a test PNG image in memory."""
    # Create a simple 100x100 red image
    img = Image.new("RGB", (100, 100), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_upload_image_local_storage(client: TestClient, test_workspace: Groups, test_user: Users, test_image: io.BytesIO):
    """Test uploading an image using local storage provider."""
    # Configure local storage
    settings = get_app_settings()
    original_provider = settings.STORAGE_PROVIDER
    settings.STORAGE_PROVIDER = "local"

    try:
        # Upload image
        response = client.post(
            "/api/platform/assets/upload",
            files={"file": ("test.png", test_image, "image/png")},
            data={"slug": "test-image", "name": "Test Image", "alt_text": "A test image"},
            headers={"X-User-Id": str(test_user.id)},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response has generated fields
        assert data["slug"] == "test-image"
        assert data["name"] == "Test Image"
        assert data["alt_text"] == "A test image"
        assert data["mime_type"] == "image/png"
        assert data["asset_type"] == "image"
        assert data["width"] == 100
        assert data["height"] == 100
        assert data["file_size"] > 0
        assert "checksum" in data
        assert data["storage_provider"] == "local"
        assert "storage_key" in data
        assert "public_url" in data

        # Verify file exists in storage
        storage_key = data["storage_key"]
        storage_root = settings.STORAGE_LOCAL_ROOT or Path(settings.DATA_DIR) / "uploads"
        file_path = storage_root / storage_key
        assert file_path.exists()

    finally:
        settings.STORAGE_PROVIDER = original_provider


def test_upload_rejects_readonly_fields(client: TestClient, test_workspace: Groups, test_user: Users, test_image: io.BytesIO):
    """Upload request should reject client-supplied technical metadata."""
    response = client.post(
        "/api/platform/assets/upload",
        files={"file": ("test.png", test_image, "image/png")},
        data={
            "slug": "test-image",
            "name": "Test Image",
            "mime_type": "image/jpeg",  # Client shouldn't be able to override
            "checksum": "fake_checksum",  # Client shouldn't be able to override
        },
        headers={"X-User-Id": str(test_user.id)},
    )

    # Should succeed but ignore readonly fields
    assert response.status_code == 200
    data = response.json()

    # Server should have determined mime_type correctly
    assert data["mime_type"] == "image/png"  # Not the client-supplied jpeg
    assert data["checksum"] != "fake_checksum"  # Server-generated checksum


def test_asset_update_editable_only(client: TestClient, test_workspace: Groups, test_user: Users, test_image: io.BytesIO, test_db: Session):
    """Update should only modify editorial fields."""
    # First upload an asset
    upload_response = client.post(
        "/api/platform/assets/upload",
        files={"file": ("test.png", test_image, "image/png")},
        data={"slug": "test-update", "name": "Original Name", "alt_text": "Original alt"},
        headers={"X-User-Id": str(test_user.id)},
    )
    assert upload_response.status_code == 200
    asset_id = upload_response.json()["id"]
    original_checksum = upload_response.json()["checksum"]

    # Update with editorial + technical fields
    update_response = client.patch(
        f"/api/platform/assets/{asset_id}",
        json={
            "alt_text": "Updated alt",
            "mime_type": "image/jpeg",  # Try to change readonly field
            "checksum": "fake_checksum",  # Try to change readonly field
        },
        headers={"X-User-Id": str(test_user.id)},
    )

    assert update_response.status_code == 200
    data = update_response.json()

    # Editorial field should be updated
    assert data["alt_text"] == "Updated alt"

    # Technical fields should be unchanged
    assert data["mime_type"] == "image/png"
    assert data["checksum"] == original_checksum


def test_asset_list_workspace_scoped(client: TestClient, test_db: Session, test_image: io.BytesIO):
    """Assets should be scoped to workspace/group."""
    # Create two workspaces
    workspace1 = Groups(slug="workspace-1", name="Workspace 1", email="w1@test.com")
    workspace2 = Groups(slug="workspace-2", name="Workspace 2", email="w2@test.com")
    test_db.add(workspace1)
    test_db.add(workspace2)
    test_db.commit()
    test_db.refresh(workspace1)
    test_db.refresh(workspace2)

    # Create users for each workspace
    user1 = Users(email="user1@test.com", username="user1", hashed_password="hash", group_id=workspace1.id)
    user2 = Users(email="user2@test.com", username="user2", hashed_password="hash", group_id=workspace2.id)
    test_db.add(user1)
    test_db.add(user2)
    test_db.commit()

    # Upload asset to workspace 1
    test_image.seek(0)
    client.post(
        "/api/platform/assets/upload",
        files={"file": ("w1.png", test_image, "image/png")},
        data={"slug": "w1-asset", "name": "W1 Asset"},
        headers={"X-User-Id": str(user1.id)},
    )

    # Upload asset to workspace 2
    test_image.seek(0)
    client.post(
        "/api/platform/assets/upload",
        files={"file": ("w2.png", test_image, "image/png")},
        data={"slug": "w2-asset", "name": "W2 Asset"},
        headers={"X-User-Id": str(user2.id)},
    )

    # List assets for workspace 1
    response1 = client.get("/api/platform/assets", headers={"X-User-Id": str(user1.id)})
    assert response1.status_code == 200
    assets1 = response1.json()

    # Should only see workspace 1 asset
    assert len(assets1) == 1
    assert assets1[0]["slug"] == "w1-asset"


def test_publishing_api_readonly(client: TestClient, test_workspace: Groups, test_user: Users, test_image: io.BytesIO):
    """Publishing API should return read-only asset metadata."""
    # Upload an asset
    upload_response = client.post(
        "/api/platform/assets/upload",
        files={"file": ("pub.png", test_image, "image/png")},
        data={"slug": "pub-asset", "name": "Published Asset", "alt_text": "Public asset"},
        headers={"X-User-Id": str(test_user.id)},
    )
    assert upload_response.status_code == 200

    # Fetch from Publishing API
    pub_response = client.get(f"/api/publish/{test_workspace.slug}/assets")

    assert pub_response.status_code == 200
    assets = pub_response.json()
    assert len(assets) == 1
    asset = assets[0]

    # Should include core fields
    assert asset["slug"] == "pub-asset"
    assert asset["name"] == "Published Asset"
    assert asset["mime_type"] == "image/png"

    # Should exclude internal fields (AssetSummary excludes these)
    # Note: AssetSummary includes id, slug, name, mime_type, alt_text only
    assert "storage_key" not in asset
    assert "checksum" not in asset
    assert "uploaded_by" not in asset


def test_storage_provider_configuration(test_db: Session, test_workspace: Groups):
    """Storage provider should be swappable via configuration."""
    settings = get_app_settings()

    # Test local provider
    settings.STORAGE_PROVIDER = "local"
    from marvin.services.storage.provider_factory import get_storage_provider

    provider = get_storage_provider()
    assert provider.__class__.__name__ == "LocalStorageProvider"

    # Test S3 provider configuration
    settings.STORAGE_PROVIDER = "s3"
    settings.STORAGE_S3_BUCKET = "test-bucket"
    settings.STORAGE_S3_REGION = "us-east-1"
    provider = get_storage_provider()
    assert provider.__class__.__name__ == "S3StorageProvider"


def test_metadata_extraction_dimensions(test_db: Session, test_workspace: Groups):
    """Metadata extractor should accurately detect image dimensions."""
    from marvin.services.assets.metadata_extractor import AssetMetadataExtractor

    # Create images of different sizes
    sizes = [(100, 100), (200, 150), (300, 400)]

    for width, height in sizes:
        img = Image.new("RGB", (width, height), color="blue")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes.getvalue())
            tmp_path = tmp.name

        try:
            extractor = AssetMetadataExtractor()
            metadata = extractor.extract_metadata(Path(tmp_path), "test.png")

            assert metadata.width == width
            assert metadata.height == height
            assert metadata.mime_type == "image/png"
            assert metadata.asset_type == "image"
        finally:
            Path(tmp_path).unlink()


def test_asset_delete_cleanup(client: TestClient, test_workspace: Groups, test_user: Users, test_image: io.BytesIO, test_db: Session):
    """Delete should clean up both file and database record."""
    settings = get_app_settings()

    # Upload asset
    upload_response = client.post(
        "/api/platform/assets/upload",
        files={"file": ("delete.png", test_image, "image/png")},
        data={"slug": "delete-test", "name": "Delete Test"},
        headers={"X-User-Id": str(test_user.id)},
    )
    assert upload_response.status_code == 200
    asset_id = upload_response.json()["id"]
    storage_key = upload_response.json()["storage_key"]

    # Verify file exists
    storage_root = settings.STORAGE_LOCAL_ROOT or Path(settings.DATA_DIR) / "uploads"
    file_path = storage_root / storage_key
    assert file_path.exists()

    # Delete asset
    delete_response = client.delete(f"/api/platform/assets/{asset_id}", headers={"X-User-Id": str(test_user.id)})
    assert delete_response.status_code == 200

    # Verify database record deleted
    asset = test_db.query(Assets).filter(Assets.id == asset_id).first()
    assert asset is None

    # Verify file deleted from storage
    assert not file_path.exists()


def test_checksum_calculation(test_db: Session):
    """Asset metadata should include SHA-256 checksum for integrity."""
    from marvin.services.assets.metadata_extractor import AssetMetadataExtractor

    # Create identical images
    img = Image.new("RGB", (50, 50), color="green")

    checksums = []
    for i in range(2):
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes.getvalue())
            tmp_path = tmp.name

        try:
            extractor = AssetMetadataExtractor()
            metadata = extractor.extract_metadata(Path(tmp_path), f"test{i}.png")
            checksums.append(metadata.checksum)
        finally:
            Path(tmp_path).unlink()

    # Identical images should have identical checksums
    assert checksums[0] == checksums[1]
    assert len(checksums[0]) == 64  # SHA-256 hex digest length
