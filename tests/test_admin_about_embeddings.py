"""GET /api/admin/about carries the embeddings status (services/ai/embeddings.py embeddings_status): settings, package
versions, vector size and the models the indexes were built with, all without loading the model."""

import importlib.metadata as md
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.core.config import get_app_settings
from marvin.db.models.users.roles import PlatformRole

ABOUT_URL = "/api/admin/about"


@pytest.fixture
def admin_client(monkeypatch):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    user = SimpleNamespace(platform_role=PlatformRole.SUPER_ADMIN, is_superuser=False, admin=True, username="root", email="root@t.test")
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("marvin.routes.admin.about_controller.get_latest_version", lambda _url: "0.0.0")  # stay offline
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def never_loads_the_model(monkeypatch):
    """Fail if anything instantiates fastembed's TextEmbedding or loads the built-in embedder."""
    import fastembed

    from marvin.services.ai.embeddings import BuiltinEmbedder

    def boom(*_a, **_k):
        pytest.fail("the model must not be loaded to report its status")

    monkeypatch.setattr(fastembed.TextEmbedding, "__init__", boom)
    monkeypatch.setattr(BuiltinEmbedder, "_load", boom)


@pytest.fixture
def stored_vectors(db_session):
    """Chunks under a made-up old model and the built-in one, in a throwaway workspace."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.services.ai.embeddings import BUILTIN_EMBEDDING_MODEL

    marker = uuid.uuid4().hex[:8]
    group = Groups(session=db_session, name=f"Emb {marker}", slug=f"emb-{marker}")
    db_session.add(group)
    db_session.flush()
    old = f"old-model-{marker}"
    entity = uuid.uuid4()
    for i, model in enumerate([old, old, old, BUILTIN_EMBEDDING_MODEL]):
        db_session.add(
            AIEmbeddingModel(
                session=db_session,
                group_id=group.id,
                entity_type="entry",
                entity_id=entity,
                chunk_index=i if model == old else 0,
                chunk_text="x",
                embedding=[0.0, 1.0],
                model_id=model,
                dimensions=2,
            )
        )
    db_session.commit()
    yield old
    db_session.rollback()
    db_session.query(AIEmbeddingModel).filter(AIEmbeddingModel.group_id == group.id).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id == group.id).delete(synchronize_session=False)
    db_session.commit()


def test_about_reports_the_builtin_engine_without_loading_the_model(admin_client, never_loads_the_model, stored_vectors, monkeypatch):
    from marvin.services.ai.embeddings import BUILTIN_EMBEDDING_MODEL

    monkeypatch.setattr(get_app_settings(), "EMBEDDINGS_BUILTIN_ENABLED", True)  # the test environment turns it off

    res = admin_client.get(ABOUT_URL)
    assert res.status_code == 200, res.text
    emb = res.json()["embeddings"]

    assert emb["builtinEnabled"] is True and emb["builtinAvailable"] is True
    assert emb["model"] == BUILTIN_EMBEDDING_MODEL
    assert emb["dimensions"] == 384
    assert emb["engine"] == "fastembed"
    assert emb["engineVersion"] == md.version("fastembed")
    assert emb["onnxruntimeVersion"] == md.version("onnxruntime")
    counts = {m["modelId"]: m["chunks"] for m in emb["indexedModels"]}
    assert counts[stored_vectors] == 3 and counts[BUILTIN_EMBEDDING_MODEL] >= 1
    assert set(emb) == {"builtinEnabled", "builtinAvailable", "model", "dimensions", "engine", "engineVersion", "onnxruntimeVersion", "indexedModels"}
    # Most chunks first.
    chunks = [m["chunks"] for m in emb["indexedModels"]]
    assert chunks == sorted(chunks, reverse=True)


def test_about_says_so_when_the_builtin_model_is_switched_off(admin_client, never_loads_the_model, monkeypatch):
    monkeypatch.setattr(get_app_settings(), "EMBEDDINGS_BUILTIN_ENABLED", False)
    emb = admin_client.get(ABOUT_URL).json()["embeddings"]
    assert emb["builtinEnabled"] is False and emb["builtinAvailable"] is False
    assert emb["model"] is None and emb["dimensions"] is None
    assert emb["engineVersion"] == md.version("fastembed")  # still installed, just not used


def test_about_reports_missing_packages_as_none(admin_client, monkeypatch):
    import marvin.services.ai.embeddings as embeddings

    def not_installed(name):
        raise md.PackageNotFoundError(name)

    monkeypatch.setattr(md, "version", not_installed)
    monkeypatch.setattr(embeddings, "builtin_embeddings_available", lambda: False)
    emb = admin_client.get(ABOUT_URL).json()["embeddings"]
    assert emb["engineVersion"] is None and emb["onnxruntimeVersion"] is None
