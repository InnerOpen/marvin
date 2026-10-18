# ruff: noqa: F811, F401 — fixtures are imported, then named as parameters
"""Remote MCP: photo upload links (`upload_link` / `check_upload`, the page and endpoints at /mcp/upload).

A chat can't pass a photo's bytes to a tool, so a connection asks for a link, the user uploads in a browser, and the
assistant polls. The link is a bearer capability: these tests hold it to 15 minutes, one use, the connection's own
user and workspace, and a secret that never reaches a log or a query string.
"""

import io
import logging
import re
import threading
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from PIL import Image

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import platform_policy
from marvin.services.mcp_remote import limits, uploads
from tests.test_opaque_storage_keys import platform
from tests.test_remote_mcp_oauth import _connect, _open_session, client, on, ws
from tests.test_remote_mcp_server import _call, _tool, _tools
from tests.test_storage_providers import entry_points


def png(size=(40, 30), color="teal") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(out, format="JPEG")
    return out.getvalue()


class Rig:
    """A write connection for one workspace, and what to do with its upload links."""

    def __init__(self, client, owner, token, session):
        self.client, self.owner, self.token, self.session = client, owner, token, session

    def link(self, **args) -> dict:
        is_error, out = _tool(self.client, self.token, self.session, "upload_link", args)
        assert not is_error, out
        return out

    def secret(self, out: dict) -> str:
        return urlsplit(out["url"]).fragment

    def check(self, link_id: str) -> dict:
        is_error, out = _tool(self.client, self.token, self.session, "check_upload", {"link_id": link_id})
        return out

    def send(self, secret: str, data: bytes | None = None, filename="coat.png", **extra):
        files = {"file": (filename, data if data is not None else png(), "image/png")}
        return self.client.post("/mcp/upload", data={"token": secret, **extra}, files=files)


@pytest.fixture
def rig(client, on, ws, platform, db_session):
    owner = ws()
    _reg, tokens = _connect(client, owner, access="write")
    token = tokens["access_token"]
    yield Rig(client, owner, token, _open_session(client, token))
    _drop_assets(db_session, owner.gid)


def _drop_assets(db_session, gid):
    """Assets reference their uploader, so they go before the `ws` fixture deletes its users."""
    from marvin.db.models.platform.assets import Assets

    db_session.rollback()
    db_session.query(Assets).filter(Assets.group_id == gid).delete(synchronize_session=False)
    db_session.commit()


def _row(db_session, link_id):
    from marvin.db.models.platform.oauth import McpUploadLinkModel

    db_session.expire_all()
    return db_session.get(McpUploadLinkModel, uuid.UUID(link_id))


def _assets(db_session, gid):
    from marvin.db.models.platform.assets import Assets

    db_session.expire_all()
    return db_session.query(Assets).filter(Assets.group_id == gid).all()


# ── the tools ────────────────────────────────────────────────────────────────


def test_the_tools_need_a_write_connection(client, on, ws, platform):
    owner = ws()
    _reg, tokens = _connect(client, owner, access="read")
    token = tokens["access_token"]
    session = _open_session(client, token)
    assert not {"upload_link", "check_upload"} & {t["name"] for t in _tools(client, token, session)}
    is_error, out = _tool(client, token, session, "upload_link")
    assert is_error and "read-only" in out["error"]


def test_a_write_connection_is_offered_both_tools(rig):
    names = {t["name"]: t for t in _tools(rig.client, rig.token, rig.session)}
    assert {"upload_link", "check_upload"} <= set(names)
    assert names["check_upload"]["annotations"]["readOnlyHint"] is True and names["upload_link"]["annotations"]["readOnlyHint"] is False


def test_a_link_is_a_fragment_url_with_an_id_and_a_short_life(rig, db_session):
    out = rig.link(name="Chore coat", alt_text="A navy chore coat")
    parts = urlsplit(out["url"])
    assert parts.path == "/mcp/upload" and not parts.query  # nothing secret in a path or query: servers log those
    assert parts.fragment.startswith("marvin_ul_") and len(parts.fragment) > 40
    assert out["expiresInMinutes"] == 15 and uuid.UUID(out["linkId"])
    row = _row(db_session, out["linkId"])
    assert row.token_lookup != parts.fragment and parts.fragment not in repr(row.__dict__)  # only the hash is kept
    assert row.user_id == rig.owner.uid and row.group_id == rig.owner.gid
    assert timedelta(minutes=14) < row.expires_at.replace(tzinfo=None) - uploads._now().replace(tzinfo=None) <= timedelta(minutes=15)


def test_a_connection_holds_only_a_few_unused_links(rig):
    for _ in range(uploads.MAX_LIVE_PER_CONNECTION):
        rig.link()
    is_error, out = _tool(rig.client, rig.token, rig.session, "upload_link")
    assert is_error and "unused upload links" in out["error"]


# ── the page ─────────────────────────────────────────────────────────────────


def test_the_page_is_locked_down_and_holds_no_secret(client, on):
    res = client.get("/mcp/upload")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    csp = res.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([\w-]+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in res.text and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert "unsafe-inline" not in csp and "default-src 'none'" in csp
    assert res.headers["cache-control"] == "no-store" and res.headers["referrer-policy"] == "no-referrer" and res.headers["x-frame-options"] == "DENY"
    assert "marvin_ul_" not in res.text and "location.hash" in res.text  # the secret arrives in the fragment, client-side only
    assert client.get("/mcp/upload").text != res.text  # a fresh nonce each time


def test_the_page_and_endpoints_are_404_while_the_switch_is_off(client, monkeypatch):
    off = platform_policy.RemoteMcpPolicy(False, 60, 30, 180, (), True)
    monkeypatch.setattr(platform_policy, "remote_mcp", lambda: off)
    assert client.get("/mcp/upload").status_code == 404
    assert client.post("/mcp/upload/check", json={"token": "x"}).status_code == 404
    assert client.post("/mcp/upload", data={"token": "x"}, files={"file": ("a.png", png())}).status_code == 404


def test_check_says_where_the_photo_will_go_and_consumes_nothing(rig):
    secret = rig.secret(rig.link(name="Coat"))
    for _ in range(2):  # reading it twice is harmless
        res = rig.client.post("/mcp/upload/check", json={"token": secret})
        assert res.status_code == 200
        info = res.json()
        assert info["workspace"].startswith("Mcp ") and info["app"] == "Test Claude" and info["name"] == "Coat" and info["maxBytes"] > 0
    assert rig.client.post("/mcp/upload/check", json={"token": "marvin_ul_nope"}).status_code == 404
    assert rig.client.post("/mcp/upload/check", content=b"not json").status_code == 404


# ── uploading ────────────────────────────────────────────────────────────────


def test_a_photo_becomes_a_library_asset_in_the_connections_workspace(rig, db_session, on):
    from marvin.services.event_bus_service.event_types import EventTypes

    out = rig.link(name="Chore coat", alt_text="A navy chore coat")
    assert rig.check(out["linkId"])["status"] == "waiting"

    res = rig.send(rig.secret(out), png((64, 48)), filename="IMG_0001.png")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Chore coat" and body["mimeType"] == "image/png" and (body["width"], body["height"]) == (64, 48)

    [asset] = _assets(db_session, rig.owner.gid)
    assert str(asset.id) == body["assetId"] and asset.scope == "library" and asset.uploaded_by == rig.owner.uid
    assert asset.alt_text == "A navy chore coat" and asset.asset_type == "image" and asset.trashed_at is None
    assert [e["event_type"] for e in on.events if e["event_type"] == EventTypes.asset_uploaded] == [EventTypes.asset_uploaded]

    polled = rig.check(out["linkId"])
    assert polled["status"] == "uploaded" and polled["asset"]["id"] == body["assetId"] and polled["asset"]["slug"] == asset.slug
    assert polled["asset"]["url"].endswith(f"/workspace/assets/{asset.id}")


def test_a_link_works_once(rig, db_session):
    out = rig.link()
    secret = rig.secret(out)
    assert rig.send(secret).status_code == 201
    again = rig.send(secret)
    assert again.status_code == 410 and "already used" in again.json()["error"]
    assert rig.client.post("/mcp/upload/check", json={"token": secret}).status_code == 410
    assert len(_assets(db_session, rig.owner.gid)) == 1


def test_two_uploads_at_once_make_one_asset(rig, db_session):
    from marvin.db.db_setup import session_context

    secret = rig.secret(rig.link())
    results, gate = [], threading.Barrier(2)

    def go():
        gate.wait()
        try:
            with session_context() as session:
                results.append(uploads.store(session, secret, filename="a.png", file=io.BytesIO(png())))
        except uploads.UploadError as e:
            results.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(type(r).__name__ for r in results) == ["UploadError", "dict"]
    assert len(_assets(db_session, rig.owner.gid)) == 1


def test_an_expired_link_is_refused(rig, db_session):
    out = rig.link()
    row = _row(db_session, out["linkId"])
    row.expires_at = uploads._now() - timedelta(seconds=1)
    db_session.commit()
    res = rig.send(rig.secret(out))
    assert res.status_code == 410 and "expired" in res.json()["error"]
    assert rig.client.post("/mcp/upload/check", json={"token": rig.secret(out)}).status_code == 410
    assert rig.check(out["linkId"])["status"] == "expired" and not _assets(db_session, rig.owner.gid)


def test_the_secret_is_not_enough_without_the_connection_being_good(rig, db_session):
    from marvin.db.models.platform.oauth import OAuthGrantModel

    out = rig.link()
    db_session.query(OAuthGrantModel).filter_by(user_id=rig.owner.uid).update({"revoked_at": uploads._now(), "revoked_reason": "user"})
    db_session.commit()
    res = rig.send(rig.secret(out))
    assert res.status_code == 403 and "ended" in res.json()["error"]
    assert not _assets(db_session, rig.owner.gid)


def test_losing_membership_or_the_role_ends_a_link(rig, db_session):
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    out = rig.link()
    db_session.query(WorkspaceMembers).filter_by(user_id=rig.owner.uid).update({"workspace_role": WorkspaceRole.VIEWER})
    db_session.commit()
    res = rig.send(rig.secret(out))
    assert res.status_code == 403 and "Editor" in res.json()["error"]
    db_session.query(WorkspaceMembers).filter_by(user_id=rig.owner.uid).delete()
    db_session.commit()
    assert rig.send(rig.secret(out)).status_code == 403 and not _assets(db_session, rig.owner.gid)


def test_a_workspace_that_turned_mcp_off_takes_the_link_back(rig, db_session):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    out = rig.link()
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=rig.owner.gid, invocation_sources={"mcp": False}))
    db_session.commit()
    try:
        assert rig.send(rig.secret(out)).status_code == 403
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=rig.owner.gid).delete()
        db_session.commit()


def test_the_form_can_not_aim_the_photo_elsewhere(rig, db_session, ws):
    other = ws("Elsewhere")
    out = rig.link()
    res = rig.send(rig.secret(out), group_id=str(other.gid), workspace=str(other.gid), user_id=str(other.uid))
    assert res.status_code == 201
    assert len(_assets(db_session, rig.owner.gid)) == 1 and not _assets(db_session, other.gid)


def test_another_connection_can_not_poll_a_link_it_did_not_ask_for(client, rig, ws):
    out = rig.link()
    stranger = ws("Other")
    _reg, tokens = _connect(client, stranger, access="write")
    token = tokens["access_token"]
    session = _open_session(client, token)
    is_error, answer = _tool(client, token, session, "check_upload", {"link_id": out["linkId"]})
    assert is_error and "no such upload link" in answer["error"]
    assert _tool(client, token, session, "check_upload", {"link_id": "nonsense"})[0]


# ── what is accepted ─────────────────────────────────────────────────────────


def test_only_real_photos_are_taken_whatever_they_are_called(rig, db_session):
    out = rig.link()
    secret = rig.secret(out)
    page = rig.send(secret, b"<html><script>alert(1)</script></html>", filename="holiday.jpg")  # a name that lies
    assert page.status_code == 415 and "isn't a photo" in page.json()["error"]
    svg = rig.send(secret, b"<svg xmlns='http://www.w3.org/2000/svg'/>", filename="icon.svg")
    assert svg.status_code == 415
    assert not _assets(db_session, rig.owner.gid)
    # a refusal gives the link back: the same link takes a real photo, named by what the bytes are
    ok = rig.send(secret, jpeg(), filename="no-extension")
    assert ok.status_code == 201 and ok.json()["mimeType"] == "image/jpeg"
    assert _assets(db_session, rig.owner.gid)[0].extension == "jpg"


def test_a_png_called_text_is_stored_as_a_png(rig):
    res = rig.send(rig.secret(rig.link()), png(), filename="notes.txt")
    assert res.status_code == 201 and res.json()["mimeType"] == "image/png"


def test_a_link_is_spent_after_a_few_refusals(rig, db_session):
    out = rig.link()
    secret = rig.secret(out)
    for _ in range(uploads.MAX_ATTEMPTS):
        assert rig.send(secret, b"not a picture").status_code == 415
    assert rig.send(secret, png()).status_code == 410
    assert rig.check(out["linkId"])["status"] == "failed" and not _assets(db_session, rig.owner.gid)


def test_the_platforms_type_list_still_applies(rig, db_session, monkeypatch):
    from marvin.core.config import get_app_settings

    monkeypatch.setattr(get_app_settings(), "ASSET_ALLOWED_MIME_TYPES", ["image/jpeg"])
    secret = rig.secret(rig.link())
    res = rig.send(secret, png())
    assert res.status_code == 415 and "image/png" in res.json()["error"]
    assert rig.send(secret, jpeg(), filename="a.jpg").status_code == 201  # the refusal did not spend the link


def test_the_size_cap_is_checked_before_the_body_is_read_and_keeps_the_link(rig, db_session, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_BYTES", 2000)
    monkeypatch.setattr(uploads, "MULTIPART_OVERHEAD", 500)
    secret = rig.secret(rig.link())
    big = png((400, 400), "white") + b"0" * 5000
    res = rig.send(secret, big)
    assert res.status_code == 413 and "MB" in res.json()["error"]
    assert not _assets(db_session, rig.owner.gid)
    assert rig.send(secret, png((8, 8))).status_code == 201  # refused before the link was touched


def test_the_cap_holds_even_when_the_length_header_under_reports(rig, db_session, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_BYTES", 2000)
    monkeypatch.setattr(uploads, "MULTIPART_OVERHEAD", 10_000_000)  # let the header check pass: the read itself must stop
    secret = rig.secret(rig.link())
    res = rig.send(secret, png((400, 400), "white") + b"0" * 5000)
    assert res.status_code == 413 and not _assets(db_session, rig.owner.gid)


def test_a_workspaces_own_storage_that_is_down_is_a_503_and_keeps_the_link(rig, db_session, monkeypatch):
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.workspace import WorkspaceStorageUnavailable

    secret = rig.secret(rig.link())
    real = AssetStorageService.for_workspace

    def down(repos):
        raise WorkspaceStorageUnavailable("This workspace's storage can't take uploads right now.")

    monkeypatch.setattr(AssetStorageService, "for_workspace", classmethod(lambda cls, repos: down(repos)))
    res = rig.send(secret)
    assert res.status_code == 503 and "storage" in res.json()["error"]
    monkeypatch.setattr(AssetStorageService, "for_workspace", real)
    assert rig.send(secret).status_code == 201


def test_a_workspaces_own_bucket_takes_the_file(rig, db_session, monkeypatch):
    """The upload goes through the workspace's write target (its own bucket when it keeps one), not around it."""
    from marvin_integration_sdk.storage.memory import MemoryStorageProvider

    from marvin.services.storage import workspace as ws_storage

    bucket = MemoryStorageProvider()
    monkeypatch.setattr(ws_storage, "write_target", lambda session, group_id: ws_storage.WriteTarget(location=None, provider=bucket))
    res = rig.send(rig.secret(rig.link()))
    assert res.status_code == 201
    [asset] = _assets(db_session, rig.owner.gid)
    assert bucket.get(asset.storage_key).read() == png()


# ── the secret stays secret ──────────────────────────────────────────────────


def test_no_request_path_query_log_or_error_carries_the_secret(rig, db_session, caplog):
    caplog.set_level(logging.DEBUG)
    out = rig.link()
    secret = rig.secret(out)
    rig.client.post("/mcp/upload/check", json={"token": secret})
    rig.send(secret, b"nope")  # a refusal logs
    rig.send(secret, png())
    rig.send(secret, png())  # a reuse logs
    rig.client.post("/mcp/upload/check", json={"token": secret + "x"})
    assert secret not in caplog.text and secret[len("marvin_ul_") :] not in caplog.text
    assert secret not in str(rig.client.get("/mcp/upload").headers)


def test_nothing_ambient_authenticates_an_upload(rig, db_session):
    """No cookie or Authorization is read: a request with the user's own session but without the link's secret gets
    nothing (so a cross-site form post has nothing to ride on)."""
    res = rig.client.post(
        "/mcp/upload",
        files={"file": ("a.png", png(), "image/png")},
        headers={"Authorization": f"Bearer {rig.owner.jwt}"},
        cookies={"marvin.token": rig.owner.jwt},
    )
    assert res.status_code == 400 and not _assets(db_session, rig.owner.gid)
    assert "set-cookie" not in rig.client.get("/mcp/upload").headers and "set-cookie" not in res.headers
    wrong = rig.client.post("/mcp/upload", data={"token": rig.token}, files={"file": ("a.png", png(), "image/png")})  # an MCP bearer is not a link
    assert wrong.status_code == 404


def test_the_page_endpoints_are_rate_limited(client, on):
    limits.reset()
    codes = [client.post("/mcp/upload/check", json={"token": "marvin_ul_x"}).status_code for _ in range(limits.LIMITS["upload_try"][0] + 3)]
    assert codes[0] == 404 and codes[-1] == 429


# ── housekeeping ─────────────────────────────────────────────────────────────


def test_the_purge_takes_links_a_day_past_expiry(rig, db_session):
    from datetime import UTC, datetime

    from marvin.db.models.platform.oauth import McpUploadLinkModel
    from marvin.services.scheduled_tasks.handlers.oauth import purge_oauth_records

    old, recent, live = rig.link(), rig.link(), rig.link()
    _row(db_session, old["linkId"]).expires_at = uploads._now() - timedelta(days=2)
    db_session.commit()
    _row(db_session, recent["linkId"]).expires_at = uploads._now() - timedelta(hours=1)
    db_session.commit()
    counts = purge_oauth_records(datetime.now(UTC))
    assert counts["upload link(s)"] == 1
    db_session.expire_all()
    assert db_session.get(McpUploadLinkModel, uuid.UUID(old["linkId"])) is None
    assert db_session.get(McpUploadLinkModel, uuid.UUID(recent["linkId"])) is not None
    assert db_session.get(McpUploadLinkModel, uuid.UUID(live["linkId"])) is not None


def test_revoking_the_connection_deletes_its_links_with_it(rig, db_session):
    from marvin.db.models.platform.oauth import McpUploadLinkModel, OAuthGrantModel

    out = rig.link()
    db_session.query(OAuthGrantModel).filter_by(user_id=rig.owner.uid).delete()
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(McpUploadLinkModel, uuid.UUID(out["linkId"])) is None  # ON DELETE CASCADE
