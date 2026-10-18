"""The publishing API serves entries and the site; assets and resources come with their entries.

``/site`` therefore never hands a site an asset slug (there is no assets endpoint to resolve one with):
the logo, favicon and share image come back as public URLs, or null when the asset is in the Trash or gone.
``metadata.brand`` also holds colours and text, so there only a value that names an asset changes.
"""

from datetime import UTC, datetime

import pytest

from marvin.db.models.groups.preferences import GroupPreferencesModel
from marvin.db.models.platform import Assets
from marvin.services.storage.provider_factory import asset_public_url
from tests.test_publishing_expand import make_workspace, site  # noqa: F401 — publishing fixtures


@pytest.fixture
def workspace(db_session, make_workspace):  # noqa: F811
    ws = make_workspace(1)
    ws.group.name = "Pub"
    yield ws
    db_session.query(GroupPreferencesModel).filter_by(group_id=ws.group.id).delete()
    db_session.commit()


def _asset(db_session, ws, slug: str) -> Assets:
    return db_session.query(Assets).filter(Assets.group_id == ws.group.id, Assets.slug == slug).one()


def _prefs(db_session, ws, *, seo: dict | None = None, **columns) -> None:
    metadata = {"seo": seo} if seo is not None else None
    db_session.add(GroupPreferencesModel(session=db_session, group_id=ws.group.id, site_metadata_json=metadata, **columns))
    db_session.commit()


def _site(site, ws) -> dict:  # noqa: F811
    response = site(ws).get(f"/api/publish/{ws.group.slug}/site")
    assert response.status_code == 200, response.text
    return response.json()["site"]


def test_site_images_named_by_slug_come_back_as_public_urls(db_session, workspace, site):  # noqa: F811
    logo, favicon, share = (_asset(db_session, workspace, s) for s in ("hero-0", "gallery-0", "gallery-0"))
    _prefs(db_session, workspace, site_logo="hero-0", site_favicon="gallery-0", seo={"image": "gallery-0", "title": "T"})
    info = _site(site, workspace)
    assert info["logo"] == asset_public_url(logo) and info["favicon"] == asset_public_url(favicon)
    assert info["seo"]["image"] == asset_public_url(share) and info["seo"]["title"] == "T"
    assert info["metadataJson"]["seo"]["image"] == asset_public_url(share)  # the raw blob says the same
    assert "hero-0" not in (info["logo"], info["favicon"])


def test_an_asset_id_resolves_too_and_a_url_passes_through(db_session, workspace, site):  # noqa: F811
    hero = _asset(db_session, workspace, "hero-0")
    _prefs(db_session, workspace, site_logo=str(hero.id), site_favicon="https://cdn.example.test/fav.ico", seo={"image": "/img/share.png"})
    info = _site(site, workspace)
    assert info["logo"] == asset_public_url(hero)
    assert info["favicon"] == "https://cdn.example.test/fav.ico" and info["seo"]["image"] == "/img/share.png"


def test_a_trashed_or_missing_asset_is_null_never_a_slug(db_session, workspace, site):  # noqa: F811
    hero = _asset(db_session, workspace, "hero-0")
    hero.trashed_at = datetime.now(UTC)
    db_session.commit()
    _prefs(db_session, workspace, site_logo="hero-0", site_favicon="no-such-asset", seo={"image": str(hero.id)})
    info = _site(site, workspace)
    assert info["logo"] is None and info["favicon"] is None
    assert info["seo"]["image"] is None and info["metadataJson"]["seo"]["image"] is None


def test_brand_images_resolve_but_colours_and_text_pass_through(db_session, workspace, site):  # noqa: F811
    hero, gallery = _asset(db_session, workspace, "hero-0"), _asset(db_session, workspace, "gallery-0")
    gallery_url = asset_public_url(gallery)
    gallery.trashed_at = datetime.now(UTC)
    db_session.commit()
    metadata = {
        "brand": {
            "seal": "hero-0",
            "portrait": str(gallery.id),
            "portraitUrl": gallery_url,
            "mark": "https://cdn.example.test/m.svg",
            "colour": "#aa3322",
            "tagline": "Tagline text",
            "unknown": "nope",
            "n": 3,
        },
        "other": "kept",
    }
    db_session.add(GroupPreferencesModel(session=db_session, group_id=workspace.group.id, site_metadata_json=metadata))
    db_session.commit()
    brand = _site(site, workspace)["metadataJson"]["brand"]
    assert brand == {
        "seal": asset_public_url(hero),  # an asset by slug: its URL
        "portrait": None,  # a trashed asset by id, and a URL to its file
        "portraitUrl": None,
        "mark": "https://cdn.example.test/m.svg",
        "colour": "#aa3322",  # not an asset: as stored
        "tagline": "Tagline text",
        "unknown": "nope",
        "n": 3,
    }
    assert _site(site, workspace)["metadataJson"]["other"] == "kept"


def test_a_brand_value_naming_an_ask_file_is_not_resolved(db_session, workspace, site):  # noqa: F811
    hero = _asset(db_session, workspace, "hero-0")
    hero.scope = "ask"
    db_session.commit()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=workspace.group.id, site_metadata_json={"brand": {"seal": "hero-0"}}))
    db_session.commit()
    assert _site(site, workspace)["metadataJson"]["brand"]["seal"] != asset_public_url(hero)


def test_a_url_to_a_trashed_asset_is_null(db_session, workspace, site):  # noqa: F811
    hero = _asset(db_session, workspace, "hero-0")
    url = asset_public_url(hero)
    hero.trashed_at = datetime.now(UTC)
    db_session.commit()
    _prefs(db_session, workspace, site_logo=url)
    assert _site(site, workspace)["logo"] is None


def test_an_ask_file_is_never_a_site_image(db_session, workspace, site):  # noqa: F811
    hero = _asset(db_session, workspace, "hero-0")
    hero.scope = "ask"
    db_session.commit()
    _prefs(db_session, workspace, site_logo="hero-0")
    assert _site(site, workspace)["logo"] is None


def test_the_site_without_images_is_unchanged(db_session, workspace, site):  # noqa: F811
    info = _site(site, workspace)
    assert info["logo"] is None and info["favicon"] is None and info["seo"] is None


@pytest.mark.parametrize(
    "path", ["assets", "assets/hero-0", "assets/hero-0/file", "resources", "resources/waxed-canvas", "resources/waxed-canvas/entries"]
)
def test_the_asset_and_resource_endpoints_are_gone(workspace, site, path):  # noqa: F811
    assert site(workspace).get(f"/api/publish/{workspace.group.slug}/{path}").status_code == 404


def test_entries_still_carry_their_assets_and_resources(workspace, site):  # noqa: F811
    client, slug = site(workspace), workspace.group.slug
    entry = client.get(f"/api/publish/{slug}/entries/{workspace.slugs[0]}").json()
    assert entry["assets"] and entry["assets"][0]["asset"]["publicUrl"] and entry["resources"]
    item = client.get(f"/api/publish/{slug}/entries").json()["data"][0]
    assert item["assetSlugs"] and item["featuredAsset"]["publicUrl"]
