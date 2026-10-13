"""Share to Marvin goes through the normal creates (frontend pages/share.astro, lib/share.ts).

The Share page adds nothing of its own on the server: "Add to assets" is the asset upload, "New entry with
these" the uploads and then the entry create, "Add as resource (link)" the resource create — called with the
shapes lib/share.ts builds. So the same roles (a viewer can't add), the same checks on a file (the upload
settings' size and type limits, enforced on the detected type) and the same storage apply. These pin that down
with exactly those requests.
"""

import io
import uuid

import pytest

from marvin.core.config import get_app_settings
from marvin.db.models.platform import Assets, EntryAssets
from marvin.db.models.users.roles import WorkspaceRole
from tests.test_trash_assets_resources import http, storage  # noqa: F401 — the committed workspace and its storage

A, E, R = "/api/platform/assets", "/api/platform/entries", "/api/platform/resources"


@pytest.fixture(autouse=True)
def _uploads_to_the_test_store(storage, monkeypatch):  # noqa: F811
    """The upload route names the provider directly: point it at the test's storage too."""
    monkeypatch.setattr("marvin.routes.platform.assets_controller.get_storage_provider", lambda *a, **k: storage)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _upload(client, name: str, data: bytes, mime: str, suffix: str = "ab12cd"):
    """The Share page's upload: the file, a slug from its name plus a random suffix, its name without the extension."""
    stem = name.rsplit(".", 1)[0]
    return client.post(f"{A}/upload", files={"file": (name, io.BytesIO(data), mime)}, data={"slug": f"{stem.lower()}-{suffix}", "name": stem})


def _entry_type(db_session, gid, fields):
    from marvin.db.models.platform.entry_types import EntryTypes

    et = EntryTypes(session=db_session, group_id=gid, name="Post", slug=f"post-{uuid.uuid4().hex[:6]}", schema_json={"fields": fields})
    db_session.add(et)
    db_session.commit()
    return et.id


def test_add_to_assets_is_the_asset_upload_for_authors_only(http):  # noqa: F811
    viewer = http.sign_in(WorkspaceRole.VIEWER)
    assert _upload(viewer, "beach.png", PNG, "image/png").status_code == 403

    author = http.sign_in(WorkspaceRole.AUTHOR)
    first, second = _upload(author, "beach.png", PNG, "image/png", "aa11"), _upload(author, "IMG_2041.png", PNG, "image/png", "bb22")
    assert first.status_code == second.status_code == 201
    body = first.json()
    assert body["name"] == "beach" and body["slug"] == "beach-aa11" and body["mimeType"] == "image/png"
    assert http.store.exists(http.key_of(uuid.UUID(body["id"])))  # stored by the workspace's provider
    assert _upload(author, "beach.png", PNG, "image/png", "aa11").status_code >= 400  # a slug is unique per workspace


def test_uploads_keep_to_the_servers_size_and_type_limits(http, monkeypatch, db_session):  # noqa: F811
    settings = get_app_settings()
    author = http.sign_in(WorkspaceRole.AUTHOR)
    monkeypatch.setattr(settings, "ASSET_MAX_FILE_SIZE", 32)
    res = _upload(author, "big.png", PNG, "image/png")
    assert res.status_code == 413 and "limited to" in res.json()["detail"]
    monkeypatch.setattr(settings, "ASSET_MAX_FILE_SIZE", 100 * 1024 * 1024)
    monkeypatch.setattr(settings, "ASSET_ALLOWED_MIME_TYPES", ["image/*"])
    res = _upload(author, "menu.pdf", PDF, "image/png")  # declared an image; the detected type decides
    assert res.status_code == 415
    assert _upload(author, "ok.png", PNG, "image/png").status_code == 201
    db_session.expire_all()
    assert {a.slug for a in db_session.query(Assets).filter(Assets.group_id == http.gid)} >= {"ok-ab12cd"}
    assert not db_session.query(Assets).filter(Assets.group_id == http.gid, Assets.slug.in_(["big-ab12cd", "menu-ab12cd"])).count()


def test_new_entry_with_these_is_a_draft_of_the_type_with_the_uploads_attached(http, db_session):  # noqa: F811
    type_id = _entry_type(
        db_session, http.gid, [{"key": "title", "type": "text", "label": "Title"}, {"key": "body", "type": "markdown", "label": "Body"}]
    )
    author = http.sign_in(WorkspaceRole.AUTHOR)
    asset_id = _upload(author, "trip.png", PNG, "image/png").json()["id"]
    draft = {"entryTypeId": str(type_id), "title": "Trip", "status": "draft", "dataJson": {"body": "Notes\n\nhttps://e.com/"}, "assetIds": [asset_id]}

    assert http.sign_in(WorkspaceRole.VIEWER).post(E, json=draft).status_code == 403
    res = http.sign_in(WorkspaceRole.AUTHOR).post(E, json=draft)
    assert res.status_code == 201, res.text
    entry = res.json()
    assert entry["status"] == "draft" and entry["title"] == "Trip" and entry["dataJson"]["body"] == "Notes\n\nhttps://e.com/"
    db_session.expire_all()
    linked = db_session.query(EntryAssets.asset_id).filter(EntryAssets.entry_id == uuid.UUID(entry["id"])).all()
    assert [str(r[0]) for r in linked] == [asset_id]


def test_add_as_resource_is_the_resource_create_for_editors(http):  # noqa: F811
    link = {"name": "Docs", "slug": "docs-ab12", "resourceType": "link", "url": "https://docs.example/", "description": "read this"}
    assert http.sign_in(WorkspaceRole.AUTHOR).post(R, json=link).status_code == 403  # resources are an editor's (the page says so)
    res = http.sign_in(WorkspaceRole.EDITOR).post(R, json=link)
    assert res.status_code == 201, res.text
    assert (res.json()["url"], res.json()["resourceType"]) == ("https://docs.example/", "link")
