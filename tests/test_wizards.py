"""Wizards: a package's guided setups, kept as data in its manifest.

The contract under test: a wizard definition is checked on its own (known step kinds, nothing referring to a context key no earlier step
set), installs as inert data (no row of any kind is made, so it can never turn into a stray entry type), is replaced by a reinstall of the
same package and refused when another package already brings the slug, and is readable by slug.
"""

import copy

import pytest

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.schemas.platform.blueprints import Blueprint
from marvin.schemas.platform.wizards import WizardRead
from marvin.services.blueprints import packages as service
from marvin.services.blueprints.apply import apply_blueprint
from marvin.services.blueprints.packages import PackageError
from marvin.services.blueprints.wizards import payload_problem
from tests._routes import api_routes
from tests.test_packages import _manifest, workspace  # noqa: F401  (the fixture)

WIZARD = {
    "title": "Narrate a story",
    "description": "World, story, script, characters.",
    "steps": [
        {"id": "world", "kind": "choose", "title": "World", "as": "world", "entry_type": "world", "create": {"fields": ["name"]}},
        {
            "id": "story",
            "kind": "choose",
            "title": "Story",
            "as": "story",
            "entry_type": "story",
            "scope": {"world": "${world}"},
            "create": {"fields": ["premise"], "data": {"world": "${world}", "status": "draft"}},
        },
        {
            "id": "how",
            "kind": "option",
            "title": "Start from",
            "as": "input",
            "options": [{"value": "script", "label": "A script"}, {"value": "none", "label": "Nothing yet"}],
        },
        {
            "id": "script",
            "kind": "upload",
            "title": "Upload the script",
            "entry": "story",
            "mode": "text",
            "field": "script",
            "accept": [".fountain", ".txt"],
            "when": {"ctx": "input", "op": "eq", "value": "script"},
        },
        {
            "id": "cut",
            "kind": "run",
            "title": "Cut the beats",
            "workflow": "kit-mark-sold",
            "inputs": {"story": "${story}", "mode": "refresh"},
            "button": "Cut the beats",
        },
        {
            "id": "cast",
            "kind": "list",
            "title": "Characters",
            "entry_type": "cast-member",
            "parent_field": "story",
            "parent": "story",
            "columns": ["role", "speaker"],
        },
        {"id": "form", "kind": "form", "title": "Details", "entry": "story", "fields": ["premise", "setting"]},
        {
            "id": "troupe",
            "kind": "gallery",
            "title": "Troupe",
            "entry_type": "actor",
            "parent": "world",
            "parent_field": "world",
            "picture": "general_view",
            "subtitle": "build",
            "badges": ["status"],
            "add": {"fields": ["age", "build"], "data": {"world": "${world}"}},
            "upload": {"field": "general_view"},
            "generate": {
                "workflow": "kit-mark-sold",
                "inputs": {"world": "${world}", "brief": "${brief}"},
                "button": "Make one",
                "prompt": {"name": "brief", "label": "Who"},
            },
        },
        {
            "id": "ready",
            "kind": "review",
            "title": "Ready?",
            "checks": [
                {
                    "label": "Has characters",
                    "query": {"entry_type": "cast-member", "fields": {"story": "${story}"}},  # noqa: E501
                    "op": "gte",
                    "value": 1,
                    "step": "cast",
                }
            ],
        },
    ],
}


def _wizard_blueprint(slug="narrate", payload=None) -> dict:
    return {"kind": "wizard", "slug": slug, "name": "Narrate a story", "payload": copy.deepcopy(payload or WIZARD)}


def _with_wizard(slug="story-kit", wizard_slug="narrate", payload=None) -> dict:
    manifest = _manifest(slug)
    manifest["blueprints"].append(_wizard_blueprint(wizard_slug, payload))
    return manifest


# --- the definition on its own ----------------------------------------------------------------------------------------------------------


def test_a_good_wizard_has_no_problem():
    assert payload_problem(WIZARD, "narrate") is None


def _bad(mutate) -> str | None:
    payload = copy.deepcopy(WIZARD)
    mutate(payload)
    return payload_problem(payload, "narrate")


@pytest.mark.parametrize(
    ("mutate", "words"),
    [
        (lambda p: p.pop("title"), "title"),
        (lambda p: p.update(steps=[]), "at least one step"),
        (lambda p: p.update(next=[{"text": "Go", "href": "https://elsewhere.example"}]), "path in the app"),
        (lambda p: p.update(next=[{"href": "/x"}]), "needs text"),
        (lambda p: p.update(open={"entry": "input", "label": "Open"}), "no choose step sets"),
        (lambda p: p.update(open={"entry": "story"}), "{entry, label, view?}"),
        (lambda p: p["steps"][0].update(kind="sparkle"), "kind"),
        (lambda p: p["steps"][1].update(id="world"), "used twice"),
        (lambda p: p["steps"][1].update(scope={"world": "${planet}"}), "planet"),
        (lambda p: p["steps"][0].update(when={"ctx": "story", "op": "set"}), "no earlier step sets"),
        (lambda p: p["steps"][3].update(entry="series"), "entry"),
        (lambda p: p["steps"][3].update(entry="input"), "an option, not an entry"),
        (lambda p: p["steps"][3].update(mode="blob"), "mode"),
        (lambda p: p["steps"][3].update(accept=["fountain"]), "extensions"),
        (lambda p: p["steps"][2].update(options=[{"value": "a", "label": "A"}]), "two options"),
        (lambda p: p["steps"][5].update(columns=[]), "columns"),
        (lambda p: p["steps"][4].update(workflow=""), "workflow"),
        (lambda p: p["steps"][4].update(inputs={"story": "${nope}"}), "nope"),
        (lambda p: p["steps"][4].update(inputs={"story": 3}), "inputs"),
        (lambda p: p["steps"][4].update(requires={"entry": "input", "field": "screenplay"}), "an option, not an entry"),
        (lambda p: p["steps"][4].update(requires={"entry": "story", "field": "no spaces"}), "requires"),
        (lambda p: p["steps"][3].update(entry=["x"]), "must name a context key"),
        (lambda p: p["steps"][3].update(when={"ctx": {}, "op": "set"}), "no earlier step sets"),
        (lambda p: p["steps"][2].update(**{"as": "step"}), "the page uses that name"),
        (lambda p: p["steps"][1].update(**{"as": "world"}), "already set by an earlier step"),
        (lambda p: p["steps"][8]["checks"][0].update(op="about"), "compares"),
        (lambda p: p["steps"][8]["checks"][0].update(step="nowhere"), "is not before it"),
        (lambda p: p["steps"][8]["checks"][0]["query"].update(fields={"story": "${nope}"}), "nope"),
        (lambda p: p["steps"][7].pop("parent_field"), "go together"),
        (lambda p: p["steps"][7].update(badges="status"), "badges"),
        (lambda p: p["steps"][7].update(upload={}), "upload needs"),
        (lambda p: p["steps"][7].update(audio="Voice Sample"), "audio must be a field key"),
        (lambda p: p["steps"][1].update(picture="Head Shot"), "picture must be a field key"),
        (lambda p: p["steps"][1].update(subtitle=["build", "bad key"]), "subtitle must be a field key"),
        (lambda p: p["steps"][1].update(subtitle=["a", "b", "c", "d"]), "up to three"),
        (lambda p: p["steps"][1].update(subtitle=[]), "subtitle must be a field key"),
        (lambda p: p["steps"][7]["upload"].update(accept=["audio/*"]), "upload.accept"),
        (lambda p: p["steps"][7]["upload"].update(accept="sounds please"), "upload.accept"),
        (lambda p: p["steps"][7]["upload"].update(accept="audio/*,"), "upload.accept"),
        (lambda p: p["steps"][7]["generate"].update(inputs={"x": "${nope}"}), "nope"),
        (lambda p: p["steps"][7]["generate"].update(prompt={"name": "Bad Name"}), "prompt needs"),
    ],
)
def test_a_wrong_wizard_says_what_is_wrong(mutate, words):
    problem = _bad(mutate)
    assert problem is not None and words in problem


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["steps"][7].update(audio="voice_sample"),
        lambda p: p["steps"][1].update(picture="general_view", subtitle="build"),  # a pick drawn as tiles
        lambda p: p["steps"][7]["upload"].update(accept="audio/*"),
        lambda p: p["steps"][7]["upload"].update(accept="image/png, .webp"),
        lambda p: p["steps"][7]["upload"].update(accept=".mp3,.wav,audio/x-m4a"),
    ],
)
def test_a_gallery_may_play_a_sound_and_take_an_upload_of_any_kind(mutate):
    assert _bad(mutate) is None


def test_a_wizard_is_a_blueprint_kind_that_takes_no_parameters():
    Blueprint.model_validate(_wizard_blueprint())
    with pytest.raises(ValueError, match="never required"):
        Blueprint.model_validate({**_wizard_blueprint(), "required": True})
    with pytest.raises(ValueError, match="title"):
        Blueprint.model_validate(_wizard_blueprint(payload={"steps": WIZARD["steps"]}))


def test_a_wizard_only_runs_a_workflow_its_own_package_brings():
    manifest = _with_wizard()
    wizard = next(b for b in manifest["blueprints"] if b["kind"] == "wizard")
    wizard["payload"]["steps"][4]["workflow"] = "kit-mark-sold"  # a workflow in this manifest
    service.parse_manifest(manifest)
    wizard["payload"]["steps"][4]["workflow"] = "someone-elses-workflow"
    with pytest.raises(PackageError, match="does not bring"):
        service.parse_manifest(manifest)


def test_the_package_file_accepts_a_wizard_that_uses_context_references():
    manifest = service.parse_manifest(_with_wizard())
    assert [b.kind for b in manifest.blueprints].count("wizard") == 1


# --- installing -------------------------------------------------------------------------------------------------------------------------


def test_installing_keeps_a_wizard_as_data_and_makes_no_row(db_session, workspace):  # noqa: F811
    manifest = service.parse_manifest(_with_wizard())
    before = db_session.query(EntryTypes).filter_by(group_id=workspace.id).count()

    result = service.install(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    db_session.commit()

    item = next(i for i in result.items if i.kind == "wizard")
    assert (item.status, item.summary) == ("created", "9 steps")
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id).count() == before + 1  # the manifest's beat type, not a wizard
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="narrate").count() == 0
    assert [w.slug for w in service.list_wizards(db_session, workspace.id)] == ["narrate"]
    assert [p.wizards for p in service.list_packages(db_session, workspace.id)] == [["narrate"]]


def test_a_preview_names_the_wizard_and_leaves_no_trace(db_session, workspace):  # noqa: F811
    result = service.preview(db_session, workspace.id, service.parse_manifest(_with_wizard()), actor_id=workspace.user_id)

    assert any(i.kind == "wizard" and i.status == "create" for i in result.items)
    assert service.list_wizards(db_session, workspace.id) == []


def test_installing_again_replaces_the_wizard_and_says_so(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_wizard()), actor_id=workspace.user_id)
    db_session.commit()
    shorter = copy.deepcopy(WIZARD)
    shorter["steps"] = shorter["steps"][:2]

    result = service.install(db_session, workspace.id, service.parse_manifest(_with_wizard(payload=shorter)), actor_id=workspace.user_id)
    db_session.commit()

    item = next(i for i in result.items if i.kind == "wizard")
    assert "replaces" in item.detail
    assert service.get_wizard(db_session, workspace.id, "narrate").steps == 2


def test_another_package_cannot_take_a_wizard_slug(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_wizard()), actor_id=workspace.user_id)
    db_session.commit()
    other = service.parse_manifest(_with_wizard(slug="other-kit"))

    previewed = service.preview(db_session, workspace.id, other, actor_id=workspace.user_id)
    assert any(i.kind == "wizard" and i.status == "blocked" for i in previewed.items)
    with pytest.raises(PackageError, match="already brought by"):
        service.install(db_session, workspace.id, other, actor_id=workspace.user_id)


def test_a_wizard_is_not_applied_on_its_own(db_session, workspace):  # noqa: F811
    result = apply_blueprint(db_session, workspace.id, Blueprint.model_validate(_wizard_blueprint()))

    assert result.created is False and "with its package" in result.detail
    assert db_session.query(EntryTypes).filter_by(group_id=workspace.id, slug="narrate").count() == 0


def test_a_wizard_is_read_by_slug_with_its_steps(db_session, workspace):  # noqa: F811
    service.install(db_session, workspace.id, service.parse_manifest(_with_wizard()), actor_id=workspace.user_id)
    db_session.commit()

    found = service.get_wizard(db_session, workspace.id, "narrate")

    assert isinstance(found, WizardRead) and found.package == "story-kit" and found.name == "Narrate a story"
    assert [s["id"] for s in found.definition["steps"]][:2] == ["world", "story"]
    assert service.get_wizard(db_session, workspace.id, "missing") is None


def test_the_wizard_routes_exist_and_need_a_login(client):
    from marvin.app import app

    paths = {(tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path) for r in api_routes(app) if "/groups/wizards" in r.path}
    assert (("GET",), "/api/groups/wizards") in paths and (("GET",), "/api/groups/wizards/{slug}") in paths
    assert client.get("/api/groups/wizards").status_code in (401, 403)


def test_a_choose_step_may_start_a_new_one_from_a_file_and_field_keys_may_be_camel_case():
    payload = copy.deepcopy(WIZARD)
    step = payload["steps"][1]
    assert step["kind"] == "choose"
    step["create"] = {"fields": ["sellOnline", "shippingFee"], "upload": {"field": "image", "accept": "image/*"}}
    step["picture"] = "image"
    assert payload_problem(payload, "narrate") is None


@pytest.mark.parametrize(
    "upload, words",
    [({"accept": "image/*"}, "asset field"), ({"field": "9bad"}, "asset field"), ({"field": "image", "accept": "pictures"}, "accept")],
)
def test_a_create_upload_needs_the_asset_field_and_a_real_accept(upload, words):
    problem = _bad(lambda p: p["steps"][1].update(create={"upload": upload}))
    assert words in (problem or "")


BUTTON = {"entry_type": "story-note", "label": "Narrate", "key": "story", "step": "how", "also": {"world": "world"}}


def test_a_wizard_may_put_a_button_on_an_entry_type():
    payload = copy.deepcopy(WIZARD)
    payload["button"] = copy.deepcopy(BUTTON)
    assert payload_problem(payload, "narrate") is None


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"label": " "}, "button is"),
        ({"entry_type": "Not A Slug"}, "entry type's slug"),
        ({"key": "nope"}, "not a key a choose step sets"),
        ({"step": "missing"}, "not a step"),
        ({"also": {"story": "story"}}, "button.also"),
        ({"also": {"nope": "story"}}, "button.also"),
        ({"also": {"world": "bad key"}}, "button.also"),
    ],
)
def test_a_wrong_button_says_what_is_wrong(change, words):
    payload = copy.deepcopy(WIZARD)
    payload["button"] = {**BUTTON, **change}
    assert words in (payload_problem(payload, "narrate") or "")


def test_the_wizards_of_an_entry_type_are_those_with_a_button_on_it(db_session, workspace):  # noqa: F811
    payload = copy.deepcopy(WIZARD)
    payload["button"] = copy.deepcopy(BUTTON)
    service.install(db_session, workspace.id, service.parse_manifest(_with_wizard(payload=payload)), actor_id=workspace.user_id)
    db_session.commit()

    here = service.list_wizards(db_session, workspace.id, "story-note")

    assert [w.slug for w in here] == ["narrate"] and here[0].button.key == "story" and here[0].button.also == {"world": "world"}
    assert service.list_wizards(db_session, workspace.id, "beat") == []
    assert [w.slug for w in service.list_wizards(db_session, workspace.id)] == ["narrate"]


def _takes_wizard(**gallery) -> dict:
    step = {
        "id": "takes",
        "kind": "gallery",
        "title": "Takes",
        "entry_type": "take",
        "parent_field": "line",
        "parent": "line",
        "audio": "audio",
        "upload": {"field": "audio", "accept": "audio/*", "seconds": "duration_seconds"},
        "layout": "list",
        "name": {"from": "line", "noun": "take"},
        "highlight": {"field": "status", "value": "in_use", "label": "In use"},
        "added": "Saved as the line's take.",
        "show": {"entry": "line", "fields": ["speaker", "text", "direction"]},
        **gallery,
    }
    return {
        "title": "Takes",
        "steps": [
            {"id": "line", "kind": "choose", "title": "Line", "as": "line", "entry_type": "speech-line"},
            step,
        ],
    }


def test_a_gallery_may_list_takes_name_them_after_a_line_and_measure_an_upload():
    assert payload_problem(_takes_wizard(), "takes") is None


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"layout": "grid"}, "layout"),
        ({"trash": "yes"}, "trash is"),
        ({"sort": "newest"}, "sort is"),
        ({"card_actions": []}, "card_actions"),
        ({"card_actions": [{"label": " ", "set": {"status": "x"}}]}, "needs a label"),
        ({"card_actions": [{"label": "x", "set": {}}]}, "set maps"),
        ({"card_actions": [{"label": "x", "set": {"status": [1]}}]}, "set maps"),
        ({"card_actions": [{"label": "x", "set": {"status": "x"}, "when": {"field": "status", "op": "gt", "value": "a"}}]}, "when is"),
        ({"name": {"from": "nope", "noun": "take"}}, "name is"),
        ({"name": {"from": "line", "noun": " "}}, "name is"),
        ({"name": {"from": "line", "noun": "take", "placeholder": " "}}, "name.placeholder"),
        ({"highlight": {"field": "status"}}, "highlight"),
        ({"added": " "}, "added"),
        ({"upload": {"field": "audio", "seconds": "bad key"}}, "seconds"),
        ({"show": {"entry": "nope", "fields": ["text"]}}, "show needs entry"),
        ({"show": {"entry": "line", "fields": []}}, "show.fields"),
        ({"show": {"entry": "line", "fields": [f"f{i}" for i in range(9)]}}, "show.fields"),
    ],
)
def test_a_wrong_takes_gallery_says_what_is_wrong(change, words):
    assert words in (payload_problem(_takes_wizard(**change), "takes") or "")


def _add_wizard(**add) -> dict:
    return _takes_wizard(
        add={
            "open": True,
            "title": "Add a take",
            "fields": ["spoken"],
            "prefill": {"spoken": "line.text"},
            "file": {"field": "audio", "accept": "audio/*", "seconds": "duration_seconds"},
            "buttons": [
                {"label": "Save my take", "file": "required", "data": {"source": "recorded"}},
                {"label": "Make one", "file": "none", "data": {"status": "queued"}},
            ],
            **add,
        },
        approve=["make-take", "remake-take"],
    )


def test_a_gallery_add_form_may_open_prefill_take_a_file_and_offer_buttons():
    assert payload_problem(_add_wizard(), "takes") is None


def test_an_add_forms_file_box_and_name_box_may_say_what_they_mean():
    wizard = _add_wizard(
        file={"field": "audio", "accept": "audio/*", "label": "Screen test", "help": "The actor dressed as the character.", "hint": "One picture."}
    )
    wizard["steps"][1]["name"] = {"from": "line", "noun": "casting", "placeholder": "Leave empty to name it after the role"}
    assert payload_problem(wizard, "takes") is None


def test_the_recorder_may_be_told_which_of_the_forms_fields_to_show_to_read_from():
    wizard = _add_wizard(fields=["spoken", "direction"], file={"field": "audio", "accept": "audio/*", "script": ["spoken", "direction"]})
    assert payload_problem(wizard, "takes") is None


@pytest.mark.parametrize(
    ("script", "words"),
    [
        ("spoken", "add.file.script is 1 to 3"),
        ([], "add.file.script is 1 to 3"),
        (["spoken", "spoken"], "add.file.script is 1 to 3"),
        (["a", "b", "c", "d"], "add.file.script is 1 to 3"),
        (["Bad Key"], "add.file.script is 1 to 3"),
        (["nope"], "which the form does not have"),
    ],
)
def test_a_wrong_script_says_what_is_wrong(script, words):
    wizard = _add_wizard(fields=["spoken", "direction", "a", "b", "c", "d"], file={"field": "audio", "script": script})
    assert words in (payload_problem(wizard, "takes") or "")


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"open": "yes"}, "add.open"),
        ({"title": " "}, "add.title"),
        ({"prefill": {"spoken": "nope.text"}}, "add.prefill"),
        ({"prefill": {"spoken": "text"}}, "add.prefill"),
        ({"prefill": {"spoken": "line.text|nope.text"}}, "add.prefill"),
        ({"prefill": {"bad key": "line.text"}}, "add.prefill"),
        ({"file": {"accept": "audio/*"}}, "add.file"),
        ({"file": {"field": "audio", "label": " "}}, "add.file.label"),
        ({"file": {"field": "audio", "help": "x" * 301}}, "add.file.help"),
        ({"file": {"field": "audio", "hint": 3}}, "add.file.hint"),
        ({"buttons": []}, "add.buttons"),
        ({"buttons": [{"label": ""}]}, "needs a label"),
        ({"buttons": [{"label": "x", "data": {"a": [1]}}]}, "data maps"),
        ({"buttons": [{"label": "x", "file": "maybe"}]}, "required or none"),
    ],
)
def test_a_wrong_add_form_says_what_is_wrong(change, words):
    assert words in (payload_problem(_add_wizard(**change), "takes") or "")


@pytest.mark.parametrize("approve", [[], "make-take", ["Not A Slug"], ["a", "b", "c", "d"]])
def test_approve_is_a_short_list_of_workflow_slugs(approve):
    payload = _add_wizard()
    payload["steps"][1]["approve"] = approve
    assert "approve is a list" in (payload_problem(payload, "takes") or "")


def test_a_wizard_only_shows_approvals_of_workflows_its_own_package_brings():
    manifest = _with_wizard()
    wizard = next(b for b in manifest["blueprints"] if b["kind"] == "wizard")
    wizard["payload"]["steps"][4]["approve"] = ["someone-elses-workflow"]
    with pytest.raises(PackageError, match="shows approvals of"):
        service.parse_manifest(manifest)


def test_a_gallery_may_offer_to_trash_what_it_lists():
    assert payload_problem(_takes_wizard(trash=True), "takes") is None


def test_a_choose_step_may_sort_naturally():
    payload = copy.deepcopy(WIZARD)
    payload["steps"][1]["sort"] = "natural"
    assert payload_problem(payload, "narrate") is None
    payload["steps"][1]["sort"] = "newest"
    assert "sort is natural" in (payload_problem(payload, "narrate") or "")


def test_a_gallery_card_may_carry_actions_that_set_fields_and_sorts_naturally():
    good = [{"label": "Use this one", "set": {"status": "in_use"}, "when": {"field": "status", "op": "neq", "value": "in_use"}}]
    assert payload_problem(_takes_wizard(card_actions=good, sort="natural"), "takes") is None


def test_an_option_step_may_be_optional_and_says_so_with_true_or_false():
    payload = copy.deepcopy(WIZARD)
    option = next(s for s in payload["steps"] if s["kind"] == "option")
    option["optional"] = True
    assert payload_problem(payload, "narrate") is None
    option["optional"] = "yes"
    assert "optional is true or false" in (payload_problem(payload, "narrate") or "")


@pytest.mark.parametrize("subtitle", ["build", ["text"], ["text", "status"], ["a", "b", "c"]])
def test_a_choose_or_gallery_step_may_show_one_field_or_up_to_three_under_each_title(subtitle):
    assert _bad(lambda p: p["steps"][1].update(subtitle=subtitle)) is None
    assert _bad(lambda p: p["steps"][7].update(subtitle=subtitle)) is None  # the gallery
