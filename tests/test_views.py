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
        "cards": {
            "intro": {"title": "intro_title", "seconds": "intro_seconds", "default_seconds": 2.5, "label": "Title card"},
            "outro": {"title": "outro_title", "seconds": "outro_seconds", "default_seconds": 3},
        },
        "scene_break": {"field": "scene", "seconds": "scene_break_seconds"},
        "bands": [{"entry_type": "scene", "field": "scene", "title": "Scene"}],
        "run": {"workflow": "kit-mark-sold", "entry": "story", "item": "beats", "field": "number", "label": "Draft", "inputs": {"quality": "draft"}},
        "review": {"ready": ["made"], "keep": "approved", "redo": "redo"},
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
            "off": "leave_out",
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
            "placed": {"field": "sounds", "ref": "sound", "at": "at", "volume": "volume", "filter": {"kind": "effect"}},
            "audio": "audio",
            "seconds": "duration_seconds",
            "volume": "volume",
            "status": "status",
        },
        {
            "id": "ambience",
            "title": "Ambience",
            "entry_type": "sound",
            "bed": {
                "via": "scene",
                "entry_type": "scene",
                "field": "ambience",
                "volume": "ambience_volume",
                "item_volume": "ambience_volume",
                "item_field": "ambience",
                "entry_field": "ambience",
                "entry_volume": "ambience_volume",
                "entry_item_volume": "story_ambience_volume",
                "entry_via_volume": "story_ambience_volume",
                "entry_via_muffled": "story_ambience_muffled",
            },
            "audio": "audio",
            "seconds": "duration_seconds",
            "loop": "loop",
            "volume": "volume",
        },
        {
            "id": "music",
            "title": "Music",
            "entry_type": "sound",
            "bed": {
                "field": "music",
                "item_volume": "music_volume",
                "default_volume": 0.12,
                "fade_in": "fade_in",
                "fade_out": "fade_out",
                "default_fade_out": 2,
                "ramp": 0.5,
                "item_ramp_in": "music_fade_in",
                "item_ramp_out": "music_fade_out",
                "end_fade": "end_fade_seconds",
            },
            "audio": "audio",
            "loop": "loop",
            "volume": "volume",
        },
        {
            "id": "overlay",
            "title": "Overlay",
            "entry_type": "beat",
            "cover": {
                "field": "overlay",
                "blend": "overlay_blend",
                "opacity": "overlay_opacity",
                "via": "scene",
                "entry_type": "scene",
                "card": {"title": "info_title", "text": "info_text", "delay": "overlay_delay", "default_delay": 0.6, "name": "Info card"},
            },
        },
        {
            "id": "camera",
            "title": "Camera",
            "entry_type": "beat",
            "marks": {
                "field": "camera",
                "via": "scene",
                "entry_type": "scene",
                "labels": {"push-in": "Push in"},
                "icons": {"push-in": "⤢"},
                "other": {"field": "move", "label": "Custom move"},
                "merge": ["push-in"],
            },
        },
    ],
    "actions": [
        {"label": "Guided setup", "wizard": "narrate"},
        {"label": "Cut the beats", "workflow": "kit-mark-sold", "run": {"entry": "story", "inputs": {"quality": "draft"}}},
    ],
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
        (lambda p: p["lanes"][0].update(placed={"field": "x", "ref": "y", "at": "z"}), "one of `in`"),
        (lambda p: p["lanes"][0].pop("in"), "one of `in`"),
        (lambda p: p["lanes"][0].pop("of"), "needs of"),
        (lambda p: p["lanes"][1].update(placed={"field": "sounds"}), "placed needs ref"),
        (lambda p: p["lanes"][2]["bed"].pop("entry_type"), "go together"),
        (lambda p: p["lanes"][2]["bed"].pop("field"), "bed needs field"),
        (lambda p: p["lanes"][3].update(bed="music"), "bed is"),
        (lambda p: p["lanes"][3].update(loop=["loop"]), "loop must be a field key"),
        (lambda p: p["lanes"][1].update(id="lines"), "used twice"),
        (lambda p: p["lanes"][1].pop("title"), "needs a title"),
        (lambda p: p["lanes"][0].update(estimate_from=["text"]), "estimate_from must be a field key"),
        (lambda p: p["lanes"][3]["bed"].update(default_volume=1.5), "default_volume must be a number from 0 to 1"),
        (lambda p: p["lanes"][3]["bed"].update(default_fade_out=-1), "default_fade_out must be a number of seconds"),
        (lambda p: p["lanes"][3]["bed"].update(default_fade_in="slow"), "default_fade_in must be a number of seconds"),
        (lambda p: p["lanes"][3]["bed"].update(ramp=-1), "ramp must be a number of seconds"),
        (lambda p: p["lanes"][3]["bed"].update(ramp="slow"), "ramp must be a number of seconds"),
        (lambda p: p["lanes"][3]["bed"].update(item_ramp_in="Slow!"), "item_ramp_in must be a field key"),
        (lambda p: p["lanes"][3]["bed"].update(end_fade="End Fade"), "end_fade must be a field key"),
        (lambda p: p["lanes"][3]["bed"].update(duck="Music Ducking"), "duck must be a field key"),
        (lambda p: p["lanes"][3]["bed"].update(default_volume="loud"), "default_volume must be a number from 0 to 1"),
        (lambda p: p["spine"].update(scene_break="scene"), "scene_break is"),
        (lambda p: p["spine"].update(scene_break={"field": "scene"}), "needs seconds"),
        (lambda p: p["spine"].update(scene_break={"field": "Scene", "seconds": "scene_break_seconds"}), "field must be a field key"),
        (lambda p: p["spine"].update(cards="intro"), "cards is {intro?"),
        (lambda p: p["spine"].update(cards={"middle": {"title": "t"}}), "cards is {intro?"),
        (lambda p: p["spine"].update(cards={"intro": {"seconds": "intro_seconds"}}), "needs title"),
        (lambda p: p["spine"].update(cards={"intro": {"title": "Intro Title"}}), "title must be a field key"),
        (lambda p: p["spine"].update(cards={"intro": {"title": "t", "default_seconds": 0}}), "default_seconds must be"),
        (lambda p: p["spine"].update(cards={"outro": {"title": "t", "label": " "}}), "label is a short text"),
        (lambda p: p["spine"].update(bands="scene"), "bands is a list"),
        (lambda p: p["spine"].update(bands=[{"entry_type": "scene"}]), "needs field"),
        (lambda p: p["spine"].update(bands=[{"entry_type": "Scene", "field": "scene"}]), "entry_type"),
        (lambda p: p["spine"].update(bands=[{"entry_type": "scene", "field": "scene", "title": " "}]), "band title"),
        (lambda p: p["spine"].update(bands=[{"entry_type": "scene", "field": "scene"}, {"entry_type": "place", "field": "scene"}]), "used twice"),
        (
            lambda p: p["spine"].update(
                bands=[{"entry_type": "a", "field": "a"}, {"entry_type": "b", "field": "b"}, {"entry_type": "c", "field": "c"}]
            ),
            "at most 2",
        ),
        (lambda p: p["lanes"][2]["bed"].update(item_field="Own Sound"), "item_field must be a field key"),
        (lambda p: p["lanes"][2]["bed"].update(start_fade="Start Fade"), "start_fade must be a field key"),
        (lambda p: p["lanes"][2]["bed"].update(entry_fade_in=1), "entry_fade_in must be a field key"),
        (lambda p: p["lanes"][2]["bed"].update(item_fade_out="Item Out"), "item_fade_out must be a field key"),
        (lambda p: p["lanes"][2]["bed"].update(entry_field=3), "entry_field must be a field key"),
        (lambda p: p["spine"].update(run="draft"), "run is {workflow"),
        (lambda p: p["spine"].update(run={"workflow": "Draft It", "entry": "story", "item": "beats", "field": "number"}), "run.workflow is"),
        (lambda p: p["spine"].update(run={"workflow": "kit-mark-sold", "entry": "story", "item": "beats"}), "run is {workflow"),
        (
            lambda p: p["spine"].update(run={"workflow": "kit-mark-sold", "entry": "Story", "item": "beats", "field": "number"}),
            "entry must be a field key",
        ),
        (
            lambda p: p["spine"].update(run={"workflow": "kit-mark-sold", "entry": "story", "item": "beats", "field": "number", "label": " "}),
            "run.label",
        ),
        (
            lambda p: p["spine"].update(
                run={"workflow": "kit-mark-sold", "entry": "story", "item": "beats", "field": "number", "inputs": {"q": ["x"]}}
            ),
            "run.inputs is",
        ),
        (lambda p: p["lanes"][1]["placed"].update(filter="effect"), "placed.filter is"),
        (lambda p: p["lanes"][1]["placed"].update(filter={}), "placed.filter is"),
        (lambda p: p["lanes"][1]["placed"].update(filter={"Kind": "effect"}), "placed.filter is"),
        (lambda p: p["lanes"][1]["placed"].update(filter={"kind": 3}), "placed.filter is"),
        (lambda p: p["lanes"][4]["cover"].pop("field"), "cover needs field"),
        (lambda p: p["lanes"][4]["cover"].pop("entry_type"), "cover.via"),
        (lambda p: p["lanes"][4]["cover"].update(blend="Screen!"), "blend must be a field key"),
        (lambda p: p["lanes"][4].update(cover="overlay"), "cover is"),
        (lambda p: p["lanes"][4]["cover"]["card"].pop("title"), "cover.card needs title"),
        (lambda p: p["lanes"][4]["cover"]["card"].update(delay="Late!"), "delay must be a field key"),
        (lambda p: p["lanes"][4]["cover"]["card"].update(default_delay=-1), "default_delay"),
        (lambda p: p["lanes"][4]["cover"]["card"].update(name=""), "cover.card.name"),
        (lambda p: p["lanes"][4]["cover"].update(card="info"), "cover.card is"),
        (lambda p: p["lanes"][4].update(bed={"field": "music"}), "one of `in`"),
        (lambda p: p["lanes"][0].update(off="Leave Out"), "off must be a field key"),
        (lambda p: p["lanes"][5]["marks"].pop("field"), "marks needs field"),
        (lambda p: p["lanes"][5]["marks"].update(field="Camera Move"), "field must be a field key"),
        (lambda p: p["lanes"][5]["marks"].pop("entry_type"), "marks.via"),
        (lambda p: p["lanes"][5]["marks"].pop("via"), "marks.via"),
        (lambda p: p["lanes"][5]["marks"].update(labels={}), "marks.labels is"),
        (lambda p: p["lanes"][5]["marks"].update(labels={"push-in": ""}), "marks.labels is"),
        (lambda p: p["lanes"][5]["marks"].update(icons={"push-in": "x" * 41}), "marks.icons is"),
        (lambda p: p["lanes"][5]["marks"].update(labels={f"v{i}": "x" for i in range(41)}), "marks.labels is"),
        (lambda p: p["lanes"][5]["marks"].update(other={"field": "move"}), "marks.other is"),
        (lambda p: p["lanes"][5]["marks"].update(merge="rocking"), "marks.merge is"),
        (lambda p: p["lanes"][5]["marks"].update(merge=[]), "marks.merge is"),
        (lambda p: p["lanes"][5]["marks"].update(merge=["ok", ""]), "marks.merge is"),
        (lambda p: p["lanes"][5]["marks"].update(other={"label": "Custom"}), "marks.other needs field"),
        (lambda p: p["lanes"][5].update(marks="camera"), "marks is"),
        (lambda p: p["lanes"][5].update(bed={"field": "music"}), "one of `in`"),
        (lambda p: p.update(lanes=p["lanes"] * 2), "at most 6"),
        (lambda p: p["actions"].append({"label": "Both", "wizard": "a", "workflow": "b"}), "either a wizard or a workflow"),
        (lambda p: p["actions"].append({"wizard": "a"}), "needs a label"),
        (lambda p: p["actions"].append({"label": "Go", "wizard": "a", "run": {"entry": "story"}}), "runs a workflow"),
        (lambda p: p["actions"].append({"label": "Go", "workflow": "kit-mark-sold", "run": "now"}), "run is {entry, inputs?}"),
        (lambda p: p["actions"].append({"label": "Go", "workflow": "kit-mark-sold", "run": {"inputs": {}}}), "run is {entry, inputs?}"),
        (
            lambda p: p["actions"].append({"label": "Go", "workflow": "kit-mark-sold", "run": {"entry": "story", "inputs": {"Quality": "draft"}}}),
            "run.inputs is",
        ),
        (
            lambda p: p["actions"].append({"label": "Go", "workflow": "kit-mark-sold", "run": {"entry": "story", "inputs": {"q": ["draft"]}}}),
            "run.inputs is",
        ),
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
    assert [lane["id"] for lane in found.definition["lanes"]] == ["lines", "sounds", "ambience", "music", "overlay", "camera"]
    assert service.get_view(db_session, workspace.id, "missing") is None
    assert [v.slug for v in service.list_views(db_session, workspace.id, entry_type="story")] == ["story-timeline"]
    assert service.list_views(db_session, workspace.id, entry_type="beat") == []
    # The list carries no definition unless asked: by spine type (an entry of that type needs the lanes) or explicitly.
    assert service.list_views(db_session, workspace.id)[0].definition == {}
    by_spine = service.list_views(db_session, workspace.id, spine_type="beat")
    assert [v.slug for v in by_spine] == ["story-timeline"] and by_spine[0].definition["spine"]["entry_type"] == "beat"
    assert service.list_views(db_session, workspace.id, spine_type="story") == []
    assert service.list_views(db_session, workspace.id, with_definition=True)[0].definition["kind"] == "timeline"


def test_the_view_routes_exist_and_need_a_login(client):
    from marvin.app import app

    paths = {(tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path) for r in api_routes(app) if "/groups/views" in r.path}
    assert (("GET",), "/api/groups/views") in paths and (("GET",), "/api/groups/views/{slug}") in paths
    assert client.get("/api/groups/views").status_code in (401, 403)


def test_a_lane_may_open_a_guided_setup_instead_of_the_piece_page():
    payload = copy.deepcopy(TIMELINE)
    payload["lanes"][0]["open"] = {"wizard": "narrate"}
    assert payload_problem(payload, "story-timeline") is None


@pytest.mark.parametrize(("opens", "words"), [("narrate", "open is"), ({"wizard": "Not A Slug"}, "open"), ({}, "open")])
def test_a_wrong_lane_open_says_what_is_wrong(opens, words):
    payload = copy.deepcopy(TIMELINE)
    payload["lanes"][0]["open"] = opens
    assert words in (payload_problem(payload, "story-timeline") or "")


def test_a_lane_only_opens_a_setup_its_own_package_brings():
    manifest = _with_view()
    view = next(b for b in manifest["blueprints"] if b["kind"] == "view")
    view["payload"]["lanes"][0]["open"] = {"wizard": "narrate"}  # the wizard of this manifest
    service.parse_manifest(manifest)
    view["payload"]["lanes"][0]["open"] = {"wizard": "someone-elses"}
    with pytest.raises(PackageError, match="does not bring"):
        service.parse_manifest(manifest)


def test_a_view_may_name_the_field_that_holds_the_shape_of_the_picture_and_it_must_be_a_field_key():
    good = copy.deepcopy(TIMELINE)
    good["aspect"] = "format"
    assert payload_problem(good, "story-timeline") is None
    for bad in ("bad key", 3, ""):
        good["aspect"] = bad
        assert "aspect must be a field key" in (payload_problem(good, "story-timeline") or "")


@pytest.mark.parametrize(
    "review, words",
    [
        ("keep", "review is {ready"),
        ({"ready": [], "keep": "approved", "redo": "redo"}, "one to six statuses"),
        ({"ready": ["Made"], "keep": "approved", "redo": "redo"}, "one to six statuses"),
        ({"ready": ["a", "b", "c", "d", "e", "f", "g"], "keep": "approved", "redo": "redo"}, "one to six statuses"),
        ({"ready": ["made"], "redo": "redo"}, "review.keep"),
        ({"ready": ["made"], "keep": "approved", "redo": 3}, "review.redo"),
    ],
)
def test_a_wrong_review_says_what_is_wrong(review, words):
    payload = copy.deepcopy(TIMELINE)
    payload["spine"]["review"] = review
    assert words in (payload_problem(payload, "story-timeline") or "")


def test_a_review_needs_the_field_that_holds_the_status():
    payload = copy.deepcopy(TIMELINE)
    del payload["spine"]["status"]
    assert "spine needs `status`" in payload_problem(payload, "story-timeline")


@pytest.mark.parametrize("key", ["entry_item_volume", "entry_via_volume", "entry_via_muffled"])
def test_a_wrong_story_bed_field_says_which_key(key):
    payload = copy.deepcopy(TIMELINE)
    ambience = next(lane for lane in payload["lanes"] if lane.get("bed", {}).get("entry_field"))
    ambience["bed"][key] = "Bad Key"
    assert key in (payload_problem(payload, "story-timeline") or "")


def test_a_wrong_cue_level_key_says_which_key():
    payload = copy.deepcopy(TIMELINE)
    lane = next(lane for lane in payload["lanes"] if lane.get("placed"))
    lane["placed"]["volume"] = "Bad Key"
    assert "placed: volume must be a field key" in (payload_problem(payload, "story-timeline") or "")


def test_a_lane_may_name_the_field_holding_a_recordings_peaks_for_its_waveform():
    assert _bad(lambda p: p["lanes"][0].update(waveform="waveform")) is None
    assert "waveform" in (_bad(lambda p: p["lanes"][0].update(waveform="not a field")) or "")  # a field name, like audio
