"""Views: a package's ways of looking at an entry (a story's timeline), kept as data in its manifest.

The contract under test: a view definition is checked on its own (a known kind, a spine, lanes that are either `in` a spine item or `placed`
by it, buttons naming a wizard or workflow of the same package), installs as inert data (no row of any kind is made), is replaced by a
reinstall of the same package and refused when another package already brings the slug, and is readable by slug and by entry type. A
wizard's end button may open the entry in a view, as long as the same package brings that view.
"""

import copy

import pytest

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.schemas.platform.blueprints import Blueprint
from marvin.schemas.platform.views import ViewRead
from marvin.services.blueprints import packages as service
from marvin.services.blueprints.apply import apply_blueprint
from marvin.services.blueprints.packages import PackageError
from marvin.services.blueprints.views import payload_problem
from tests._routes import api_routes
from tests.test_packages import _manifest, workspace  # noqa: F401  (the fixture)
from tests.test_wizards import WIZARD, _wizard_blueprint

TIMELINE = {
    "kind": "timeline",
    "title": "Timeline",
    "entry_type": "story",
    "spine": {
        "entry_type": "beat",
        "of": "story",
        "order": "number",
        "group": {"entry_type": "chapter", "field": "chapter", "order": "number"},
        "picture": "still",
        "text": "picture",
        "status": "status",
        "seconds": {
            "hold": "hold_seconds",
            "lead": "lead_seconds",
            "gap": "gap_seconds",
            "tail": "tail_seconds",
            "defaults": {"hold": 4, "lead": 0.3, "gap": 0.25, "tail": 0.35},
        },
    },
    "lanes": [
        {
            "id": "lines",
            "title": "Lines",
            "entry_type": "speech-line",
            "of": "story",
            "in": "beat",
            "order": "number",
            "text": "text",
            "who": "speaker",
            "audio": "audio",
            "seconds": "duration_seconds",
            "estimate_from": "text",
            "status": "status",
        },
        {
            "id": "sounds",
            "title": "Sounds",
            "entry_type": "sound",
            "of": "story",
            "placed": {"field": "sounds", "ref": "sound", "at": "at"},
            "audio": "audio",
            "seconds": "duration_seconds",
            "status": "status",
        },
    ],
    "actions": [{"label": "Guided setup", "wizard": "narrate"}, {"label": "Cut the beats", "workflow": "kit-mark-sold"}],
}


def _view_blueprint(slug="story-timeline", payload=None) -> dict:
    return {"kind": "view", "slug": slug, "name": "Timeline", "payload": copy.deepcopy(payload or TIMELINE)}


def _with_view(slug="story-kit", view_slug="story-timeline", payload=None, wizard=True) -> dict:
    manifest = _manifest(slug)
    if wizard:
        manifest["blueprints"].append(_wizard_blueprint())
    manifest["blueprints"].append(_view_blueprint(view_slug, payload))
    return manifest


# --- the definition on its own ----------------------------------------------------------------------------------------------------------


def test_a_good_view_has_no_problem():
    assert payload_problem(TIMELINE, "story-timeline") is None


def _bad(mutate) -> str | None:
    payload = copy.deepcopy(TIMELINE)
    mutate(payload)
    return payload_problem(payload, "story-timeline")


@pytest.mark.parametrize(
    ("mutate", "words"),
    [
        (lambda p: p.update(kind="gantt"), "kind"),
        (lambda p: p.pop("title"), "title"),
        (lambda p: p.pop("entry_type"), "entry_type"),
        (lambda p: p.pop("spine"), "needs a spine"),
        (lambda p: p["spine"].pop("of"), "needs of"),
        (lambda p: p["spine"].update(picture="Still Image"), "picture must be a field key"),
        (lambda p: p["spine"].update(group={"entry_type": "chapter"}), "group needs field"),
        (lambda p: p["spine"]["seconds"].update(hold=3), "hold must be a field key"),
        (lambda p: p["spine"]["seconds"].update(defaults={"hold": -1}), "0 or more"),
        (lambda p: p["spine"]["seconds"].update(defaults={"pause": 1}), "defaults holds numbers"),
        (lambda p: p["lanes"][0].update(placed={"field": "x", "ref": "y", "at": "z"}), "one of the two"),
        (lambda p: p["lanes"][0].pop("in"), "one of the two"),
        (lambda p: p["lanes"][1].update(placed={"field": "sounds"}), "placed needs ref"),
        (lambda p: p["lanes"][1].update(id="lines"), "used twice"),
        (lambda p: p["lanes"][1].pop("title"), "needs a title"),
        (lambda p: p["lanes"][0].update(estimate_from=["text"]), "estimate_from must be a field key"),
        (lambda p: p.update(lanes=p["lanes"] * 3), "at most 4"),
        (lambda p: p["actions"].append({"label": "Both", "wizard": "a", "workflow": "b"}), "either a wizard or a workflow"),
        (lambda p: p["actions"].append({"wizard": "a"}), "needs a label"),
    ],
)
def test_a_wrong_view_says_what_is_wrong(mutate, words):
    problem = _bad(mutate)
    assert problem is not None and words in problem


def test_a_view_without_lanes_or_actions_is_fine():
    assert payload_problem({"kind": "timeline", "title": "T", "entry_type": "story", "spine": {"entry_type": "beat", "of": "story"}}, "t") is None


def test_a_view_is_a_blueprint_kind_that_takes_no_parameters():
    Blueprint.model_validate(_view_blueprint())
    with pytest.raises(ValueError, match="never required"):
        Blueprint.model_validate({**_view_blueprint(), "required": True})
    with pytest.raises(ValueError, match="spine"):
        Blueprint.model_validate(_view_blueprint(payload={"kind": "timeline", "title": "T", "entry_type": "story"}))


def test_a_view_only_names_a_wizard_or_workflow_its_own_package_brings():
    service.parse_manifest(_with_view())
    stray = _with_view()
    next(b for b in stray["blueprints"] if b["kind"] == "view")["payload"]["actions"][0]["wizard"] = "someone-elses"
    with pytest.raises(PackageError, match="does not bring"):
        service.parse_manifest(stray)
    stray = _with_view()
    next(b for b in stray["blueprints"] if b["kind"] == "view")["payload"]["actions"][1]["workflow"] = "someone-elses"
    with pytest.raises(PackageError, match="does not bring"):
        service.parse_manifest(stray)


def test_a_wizard_opens_its_entry_in_a_view_the_same_package_brings():
    manifest = _with_view()
    wizard = next(b for b in manifest["blueprints"] if b["kind"] == "wizard")
    wizard["payload"]["open"] = {"entry": "story", "label": "Open the story", "view": "story-timeline"}
    service.parse_manifest(manifest)
    wizard["payload"]["open"]["view"] = "someone-elses-view"
    with pytest.raises(PackageError, match="does not bring"):
        service.parse_manifest(manifest)
    wizard["payload"]["open"]["view"] = "Not A Slug"
    with pytest.raises(PackageError, match="slug of a view"):
        service.parse_manifest(manifest)
    assert "view" not in WIZARD.get("open", {})  # the shared fixture was copied, not changed


# --- installing -------------------------------------------------------------------------------------------------------------------------


def test_installing_keeps_a_view_as_data_and_makes_no_row(db_session, workspace):  # noqa: F811
    manifest = service.parse_manifest(_with_view())
    before = db_session.query(EntryTypes).filter_by(group_id=workspace.id).count()

    result = service.install(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    db_session.commit()

    item = next(i for i in result.items if i.kind == "view")
    assert (item.status, item.summary) == ("created", "timeline of a story")
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id).count() == before + 1  # the manifest's beat type, not a view
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="story-timeline").count() == 0
    assert [v.slug for v in service.list_views(db_session, workspace.id)] == ["story-timeline"]
    assert [p.views for p in service.list_packages(db_session, workspace.id)] == [["story-timeline"]]


def test_a_preview_names_the_view_and_leaves_no_trace(db_session, workspace):  # noqa: F811
    result = service.preview(db_session, workspace.id, service.parse_manifest(_with_view()), actor_id=workspace.user_id)

    assert any(i.kind == "view" and i.status == "create" for i in result.items)
    assert service.list_views(db_session, workspace.id) == []


def test_installing_again_replaces_the_view_and_says_so(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_view()), actor_id=workspace.user_id)
    db_session.commit()
    renamed = copy.deepcopy(TIMELINE)
    renamed["title"] = "Story as time"

    result = service.install(db_session, workspace.id, service.parse_manifest(_with_view(payload=renamed)), actor_id=workspace.user_id)
    db_session.commit()

    item = next(i for i in result.items if i.kind == "view")
    assert "replaces" in item.detail
    assert service.get_view(db_session, workspace.id, "story-timeline").name == "Story as time"


def test_another_package_cannot_take_a_view_slug(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_view()), actor_id=workspace.user_id)
    db_session.commit()
    other = service.parse_manifest(_with_view(slug="other-kit", wizard=False, payload={**copy.deepcopy(TIMELINE), "actions": []}))

    previewed = service.preview(db_session, workspace.id, other, actor_id=workspace.user_id)
    assert any(i.kind == "view" and i.status == "blocked" for i in previewed.items)
    with pytest.raises(PackageError, match="a view with slug 'story-timeline' is already brought by"):
        service.install(db_session, workspace.id, other, actor_id=workspace.user_id)


def test_a_view_is_not_applied_on_its_own(db_session, workspace):  # noqa: F811
    result = apply_blueprint(db_session, workspace.id, Blueprint.model_validate(_view_blueprint()))

    assert result.created is False and "with its package" in result.detail
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="story-timeline").count() == 0


def test_a_view_is_read_by_slug_and_by_entry_type(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_view()), actor_id=workspace.user_id)
    db_session.commit()

    found = service.get_view(db_session, workspace.id, "story-timeline")

    assert isinstance(found, ViewRead) and (found.package, found.kind, found.entry_type) == ("story-kit", "timeline", "story")
    assert [lane["id"] for lane in found.definition["lanes"]] == ["lines", "sounds"]
    assert service.get_view(db_session, workspace.id, "missing") is None
    assert [v.slug for v in service.list_views(db_session, workspace.id, entry_type="story")] == ["story-timeline"]
    assert service.list_views(db_session, workspace.id, entry_type="beat") == []


def test_the_view_routes_exist_and_need_a_login(client):
    from marvin.app import app

    paths = {(tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path) for r in api_routes(app) if "/groups/views" in r.path}
    assert (("GET",), "/api/groups/views") in paths and (("GET",), "/api/groups/views/{slug}") in paths
    assert client.get("/api/groups/views").status_code in (401, 403)
