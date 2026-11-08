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
            "id": "ready",
            "kind": "review",
            "title": "Ready?",
            "checks": [{"label": "Has characters", "query": {"entry_type": "cast-member", "fields": {"story": "${story}"}}, "op": "gte", "value": 1}],
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
        (lambda p: p["steps"][7]["checks"][0].update(op="about"), "compares"),
        (lambda p: p["steps"][7]["checks"][0]["query"].update(fields={"story": "${nope}"}), "nope"),
    ],
)
def test_a_wrong_wizard_says_what_is_wrong(mutate, words):
    problem = _bad(mutate)
    assert problem is not None and words in problem


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
    assert (item.status, item.summary) == ("created", "8 steps")
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
