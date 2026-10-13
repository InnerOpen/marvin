"""Provider logos: core validates what a plugin ships before serving it from Marvin's origin, caches it,
and serves it with a locked-down CSP. Anything refused falls back to the provider's emoji."""

import uuid
from types import SimpleNamespace

import pytest

sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from fastapi.testclient import TestClient  # noqa: E402
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider  # noqa: E402

from marvin.app import app  # noqa: E402
from marvin.core.dependencies import get_current_user  # noqa: E402
from marvin.services.integrations import logos  # noqa: E402
from marvin.services.integrations.logos import MAX_LOGO_BYTES, PNG_MAGIC, LogoRejected, validate_logo  # noqa: E402

SVG_TYPE = "image/svg+xml"
CLEAN_SVG = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 24 24">'
    b"<title>Mark</title>"
    b'<defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/></linearGradient>'
    b'<path id="p" d="M0 0h24v24H0z"/></defs>'
    b"<style>.a{fill:url(#g)}</style>"
    b'<use href="#p" class="a"/><use xlink:href="#p" style="fill:url(\'#g\')"/>'
    b'<rect width="4" height="4" fill="url(#g)" opacity=".5"/>'
    b"</svg>"
)
CLEAN_PNG = PNG_MAGIC + b"\x00\x00\x00\rIHDR" + b"\x00" * 32


def _svg(inner: str, attrs: str = "") -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" {attrs}>{inner}</svg>'.encode()


# ---- validator ------------------------------------------------------------------------------------


def test_clean_svg_and_png_pass():
    validate_logo(CLEAN_SVG, SVG_TYPE)
    validate_logo(CLEAN_PNG, "image/png")


@pytest.mark.parametrize(
    ("data", "content_type", "reason"),
    [
        (b"<svg/>" + b" " * MAX_LOGO_BYTES, SVG_TYPE, "max"),
        (CLEAN_PNG + b"\x00" * MAX_LOGO_BYTES, "image/png", "max"),
        (b"GIF89a" + b"\x00" * 16, "image/png", "PNG signature"),
        (b"", "image/png", "empty"),
        (CLEAN_SVG, "image/gif", "unsupported"),
        (b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>', SVG_TYPE, "DOCTYPE"),
        (b'<!ENTITY lol "lol"><svg xmlns="http://www.w3.org/2000/svg"/>', SVG_TYPE, "ENTITY"),
        (_svg("<script>alert(1)</script>"), SVG_TYPE, "script"),
        (_svg('<svg:script xmlns:svg="http://www.w3.org/2000/svg">alert(1)</svg:script>'), SVG_TYPE, "script"),
        (_svg("<SCRIPT>alert(1)</SCRIPT>"), SVG_TYPE, "script"),
        (_svg("<foreignObject><div/></foreignObject>"), SVG_TYPE, "foreignObject"),
        (_svg('<rect width="1" height="1"/>', 'onload="alert(1)"'), SVG_TYPE, "event attribute"),
        (_svg('<rect ONCLICK="x()"/>'), SVG_TYPE, "event attribute"),
        (_svg('<a href="https://evil.example/"><rect/></a>'), SVG_TYPE, "href"),
        (_svg('<image xlink:href="https://evil.example/x.png"/>'), SVG_TYPE, "href"),
        (_svg('<image href="data:image/svg+xml;base64,PHN2Zy8+"/>'), SVG_TYPE, "href"),
        (_svg('<image xlink:href="&#104;ttps://evil.example/x.png"/>'), SVG_TYPE, "href"),  # decoded by the parser
        (_svg('<set attributeName="fill" to="javascript:alert(1)"/>'), SVG_TYPE, "javascript"),
        (_svg('<set attributeName="xlink:href" to="https://evil.example/"/>'), SVG_TYPE, "animates"),
        (_svg('<rect style="fill:url(https://evil.example/x)"/>'), SVG_TYPE, "url()"),
        (_svg("<rect fill=\"url(  '//evil.example/g' )\"/>"), SVG_TYPE, "url()"),
        (_svg('<rect style="fill:u&#114;l(https://evil.example/x)"/>'), SVG_TYPE, "url()"),  # only visible once parsed
        (_svg("<style>.a{background:url(http://evil.example/x)}</style>"), SVG_TYPE, "url()"),
        (_svg("<style>@import 'https://evil.example/x.css';</style>"), SVG_TYPE, "@import"),
        (_svg("<style>@import url(https://evil.example/x.css);</style>"), SVG_TYPE, "url()"),
        (_svg("<style>.a{fill:\\75rl(http://evil.example/x)}</style>"), SVG_TYPE, "CSS escapes"),
        (b'<?xml-stylesheet href="https://evil.example/x.css"?><svg xmlns="http://www.w3.org/2000/svg"/>', SVG_TYPE, "stylesheet"),
        (b'<html xmlns="http://www.w3.org/1999/xhtml"/>', SVG_TYPE, "root element"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><rect></svg>", SVG_TYPE, "parse"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'>\xff\xfe</svg>", SVG_TYPE, "UTF-8"),
    ],
)
def test_each_rejection_rule(data, content_type, reason):
    with pytest.raises(LogoRejected) as e:
        validate_logo(data, content_type)
    assert reason.lower() in str(e.value).lower()


# ---- cache + endpoint -------------------------------------------------------------------------------


class _WithLogo(IntegrationProvider):
    slug = "test_logo_ok"
    name = "With logo"
    icon = "🛰️"


class _BadLogo(IntegrationProvider):
    slug = "test_logo_bad"
    name = "Bad logo"
    icon = "💣"


class _NoLogo(IntegrationProvider):
    slug = "test_logo_none"
    name = "No logo"
    icon = "🙂"


_FILES = {
    _WithLogo.slug: (CLEAN_SVG, SVG_TYPE),
    _BadLogo.slug: (_svg("<script>alert(1)</script>"), SVG_TYPE),
}


@pytest.fixture
def providers(monkeypatch):
    for cls in (_WithLogo, _BadLogo, _NoLogo):
        monkeypatch.setitem(INTEGRATION_REGISTRY, cls.slug, cls())
    monkeypatch.setattr(sdk, "load_logo", lambda provider: _FILES.get(provider.slug), raising=False)
    logos.clear_cache()
    yield
    logos.clear_cache()


def test_logo_is_served_with_locked_down_headers_without_auth(providers):
    res = TestClient(app).get(f"/api/groups/integrations/providers/{_WithLogo.slug}/logo")
    assert res.status_code == 200
    assert res.content == CLEAN_SVG
    assert res.headers["content-type"] == SVG_TYPE
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    assert res.headers["etag"].startswith('"')
    assert "max-age" in res.headers["cache-control"]


def test_matching_etag_is_304(providers):
    client = TestClient(app)
    etag = client.get(f"/api/groups/integrations/providers/{_WithLogo.slug}/logo").headers["etag"]
    res = client.get(f"/api/groups/integrations/providers/{_WithLogo.slug}/logo", headers={"If-None-Match": etag})
    assert res.status_code == 304
    assert res.content == b""
    assert res.headers["etag"] == etag


@pytest.mark.parametrize("slug", [_NoLogo.slug, _BadLogo.slug, "not_installed"])
def test_no_logo_refused_logo_or_unknown_provider_is_404(providers, slug):
    assert TestClient(app).get(f"/api/groups/integrations/providers/{slug}/logo").status_code == 404


def test_png_logo_is_served_as_png(providers, monkeypatch):
    monkeypatch.setitem(_FILES, _NoLogo.slug, (CLEAN_PNG, "image/png"))
    logos.clear_cache()
    res = TestClient(app).get(f"/api/groups/integrations/providers/{_NoLogo.slug}/logo")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == CLEAN_PNG


def test_refused_logo_is_logged_and_cached_as_none(providers, monkeypatch):
    warnings = []
    monkeypatch.setattr(logos, "logger", SimpleNamespace(warning=warnings.append))
    assert logos.get_logo(_BadLogo.slug) is None
    assert logos.has_logo(_WithLogo.slug) is True
    assert len(warnings) == 1
    assert "refused the logo for 'test_logo_bad'" in warnings[0]


def test_prime_reads_every_provider_once(providers, monkeypatch):
    seen = []
    monkeypatch.setattr(sdk, "load_logo", lambda p: seen.append(p.slug) or _FILES.get(p.slug), raising=False)
    logos.prime(INTEGRATION_REGISTRY.values())
    logos.get_logo(_WithLogo.slug)
    logos.get_logo(_BadLogo.slug)
    assert seen.count(_WithLogo.slug) == 1
    assert seen.count(_BadLogo.slug) == 1


def test_sdk_without_load_logo_falls_back_to_emoji(providers, monkeypatch):
    monkeypatch.delattr(sdk, "load_logo", raising=False)
    logos.clear_cache()
    assert logos.get_logo(_WithLogo.slug) is None
    assert TestClient(app).get(f"/api/groups/integrations/providers/{_WithLogo.slug}/logo").status_code == 404


def test_a_load_logo_that_raises_is_treated_as_no_logo(providers, monkeypatch):
    def boom(_):
        raise RuntimeError("plugin bug")

    monkeypatch.setattr(sdk, "load_logo", boom, raising=False)
    logos.clear_cache()
    assert logos.get_logo(_WithLogo.slug) is None


@pytest.fixture
def signed_in(db_session):
    """Any signed-in caller — the catalog is workspace-scoped like the rest of the controller."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"logo-{gid.hex[:8]}", slug=f"logo-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), group_id=gid, active_group_id=gid, admin=False, is_superuser=False, full_name="LOGO", get_workspace_role=lambda _: None
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_catalog_has_logo_is_cores_verdict(providers, signed_in):
    catalog = {p["slug"]: p for p in TestClient(app).get("/api/groups/integrations/providers").json()}
    assert catalog[_WithLogo.slug]["hasLogo"] is True
    assert catalog[_BadLogo.slug]["hasLogo"] is False  # the SDK found a file; core refused it
    assert catalog[_BadLogo.slug]["icon"] == "💣"
    assert catalog[_NoLogo.slug]["hasLogo"] is False


def test_admin_plugins_rows_carry_icon_and_has_logo(providers, monkeypatch):
    from marvin.services import plugins

    read = plugins._provider_read(INTEGRATION_REGISTRY[_WithLogo.slug], {})
    assert read.icon == "🛰️"
    assert read.has_logo is True
    assert plugins._provider_read(INTEGRATION_REGISTRY[_BadLogo.slug], {}).has_logo is False
