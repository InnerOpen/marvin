"""Site Settings -> Privacy & cookies: the typed ``SitePrivacy`` block under ``site_metadata_json['privacy']``,
served as ``site.privacy`` on the publishing API (disclosure only; no consent banner).

Mirrors how ``seo`` is stored and read: the admin saves camelCase keys, the publishing read validates them,
a malformed stored block is ignored, and a bad one is refused on save (422).
"""

import asyncio
import uuid

import pytest
from pydantic import ValidationError
from pytest import fixture

from marvin.schemas.group.preferences import GroupPreferencesUpdate
from marvin.schemas.publishing import SitePrivacy

CONTROLLER = {"legalName": "Acme Ltd", "contactEmail": "privacy@acme.test"}


def _block(**over):
    return {"controller": CONTROLLER, **over}


def _cookie(category):
    return {"name": "c", "provider": "p", "purpose": "x", "category": category}


# --------------------------------------------------------------------------------------------------
# Schema rules


def test_banner_required_is_derived_from_cookie_categories():
    assert SitePrivacy.model_validate(_block()).banner_required is False  # no cookies
    assert SitePrivacy.model_validate(_block(cookies=[_cookie("necessary")])).banner_required is False
    for cat in ("preferences", "analytics", "marketing"):
        assert SitePrivacy.model_validate(_block(cookies=[_cookie("necessary"), _cookie(cat)])).banner_required is True
    # derived, not stored: a stored value is ignored, and it is part of the served shape
    forced = SitePrivacy.model_validate(_block(bannerRequired=True))
    assert forced.banner_required is False
    assert forced.model_dump(by_alias=True)["bannerRequired"] is False


def test_unknown_cookie_category_is_rejected():
    with pytest.raises(ValidationError):
        SitePrivacy.model_validate(_block(cookies=[_cookie("tracking")]))


@pytest.mark.parametrize("region", ["EU", "EEA", "Germany", "de", " France "])
def test_eu_eea_processor_needs_no_transfer_basis(region):
    proc = {"name": "Mail", "purpose": "email", "dataCategories": ["email"], "region": region}
    assert SitePrivacy.model_validate(_block(processors=[proc])).processors[0].transfer_basis is None


def test_processor_without_a_region_is_not_checked():
    SitePrivacy.model_validate(_block(processors=[{"name": "Mail", "purpose": "email"}]))


@pytest.mark.parametrize("region", ["US", "United States", "India"])
def test_non_eu_processor_requires_a_transfer_basis(region):
    proc = {"name": "Analytics", "purpose": "stats", "region": region}
    for basis in (None, "  "):
        with pytest.raises(ValidationError, match="transfer_basis"):
            SitePrivacy.model_validate(_block(processors=[{**proc, "transferBasis": basis}]))
    ok = SitePrivacy.model_validate(_block(processors=[{**proc, "transferBasis": "SCCs"}]))
    assert ok.processors[0].transfer_basis == "SCCs"


def test_save_rejects_a_bad_privacy_block_and_leaves_other_metadata_free_form():
    GroupPreferencesUpdate(site_metadata_json={"analytics": {"id": "x"}, "privacy": _block()})
    GroupPreferencesUpdate(site_metadata_json={"seo": {"title": "t"}})  # no privacy key
    for bad in (
        {"controller": CONTROLLER, "cookies": [_cookie("nope")]},
        {"controller": CONTROLLER, "processors": [{"name": "A", "purpose": "x", "region": "US"}]},
        {"cookies": []},  # no controller
    ):
        with pytest.raises(ValidationError):
            GroupPreferencesUpdate(site_metadata_json={"privacy": bad})


# --------------------------------------------------------------------------------------------------
# Publishing API round trip


class _AllowAll:
    def require_permission(self, *_):
        return None

    def require_any_permission(self, *_):
        return None

    def has_permission(self, *_):
        return False


@fixture
def site(db_session):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    slug = f"privacy-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield group

    from marvin.db.models.groups import GroupPreferencesModel

    db_session.rollback()
    db_session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _site_json(db_session, group, metadata):
    from marvin.db.models.groups import GroupPreferencesModel
    from marvin.routes.publish import publishing_controller as pub

    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=group.id).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=db_session, group_id=group.id)
        db_session.add(prefs)
    prefs.site_metadata_json = metadata
    db_session.commit()
    info = asyncio.run(pub.get_site_configuration(context=(None, group, _AllowAll()), session=db_session))
    return info.model_dump(by_alias=True)["site"]


def test_privacy_round_trips_through_the_publishing_site(db_session, site):
    # keys exactly as the admin form saves them (camelCase), nested like the typed model
    stored = {
        "privacy": {
            "controller": {**CONTROLLER, "dpoEmail": "dpo@acme.test"},
            "processors": [{"name": "Plausible", "purpose": "Analytics", "dataCategories": ["page views"], "region": "EU"}],
            "cookies": [{"name": "plausible_ignore", "provider": "Plausible", "purpose": "Opt-out", "duration": "session", "category": "analytics"}],
            "consent": {"policyEntrySlug": "privacy", "lastReviewed": "2026-10-01"},
        }
    }
    got = _site_json(db_session, site, stored)["privacy"]
    assert got["controller"] == {
        "legalName": "Acme Ltd",
        "contactEmail": "privacy@acme.test",
        "address": None,
        "euRepresentative": None,
        "dpoEmail": "dpo@acme.test",
    }
    assert got["processors"][0]["dataCategories"] == ["page views"]
    assert got["cookies"][0]["category"] == "analytics"
    assert got["consent"]["policyEntrySlug"] == "privacy" and str(got["consent"]["lastReviewed"]) == "2026-10-01"
    assert got["bannerRequired"] is True


def test_no_privacy_block_is_null_and_a_malformed_one_is_ignored(db_session, site):
    assert _site_json(db_session, site, {"seo": {"title": "t"}})["privacy"] is None
    for bad in (
        {"controller": CONTROLLER, "cookies": [_cookie("nope")]},
        {"controller": CONTROLLER, "processors": [{"name": "A", "purpose": "x", "region": "US"}]},
        "not-a-dict",
        {},
    ):
        # the read itself still works; the raw blob is served as before
        out = _site_json(db_session, site, {"privacy": bad})
        assert out["privacy"] is None and out["metadataJson"] == {"privacy": bad}
