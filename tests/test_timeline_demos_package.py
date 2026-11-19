"""The Timeline Demos example package (docs/examples): two timeline views that are not sound, one in minutes and one in days.

The contract under test: the file parses as a package, each view passes the view validator in its unit, every entry type and collection
installs into a workspace without a block (so the validators of those kinds accept them too), the types nobody makes by hand stay out of the New
menu, and every field a view names exists on the type it reads.
"""

import json
from pathlib import Path

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.services.blueprints import packages as service
from marvin.services.blueprints.views import payload_problem
from tests.test_packages import workspace  # noqa: F401  (the fixture)

PACKAGE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "timeline-demos.marvin-package.json"


def _manifest() -> dict:
    return json.loads(PACKAGE.read_text())


def _types(manifest: dict) -> dict[str, set[str]]:
    return {b["slug"]: {f["key"] for f in b["payload"]["schema_json"]["fields"]} for b in manifest["blueprints"] if b["kind"] == "entry_type"}


def _views(manifest: dict) -> dict[str, dict]:
    return {b["slug"]: b["payload"] for b in manifest["blueprints"] if b["kind"] == "view"}


def test_the_package_parses_and_its_views_pass_in_their_units():
    manifest = service.parse_manifest(PACKAGE.read_text())
    assert (manifest.slug, manifest.version) == ("timeline-demos", "1")
    views = _views(_manifest())
    assert {slug: view["unit"] for slug, view in views.items()} == {"event-agenda": "minutes", "content-plan": "days"}
    for slug, view in views.items():
        assert payload_problem(view, slug) is None
        assert view["sidebar"] and view["picker"]


def test_every_type_is_prefixed_demo_and_the_ones_nobody_makes_by_hand_stay_out_of_the_new_menu():
    manifest = _manifest()
    types = {b["slug"]: b["payload"] for b in manifest["blueprints"] if b["kind"] == "entry_type"}
    assert all(slug.startswith("demo-") for slug in types)
    hidden = {slug for slug, t in types.items() if (t.get("capabilities_json") or {}).get("offer_in_new") is False}
    assert hidden == {"demo-block", "demo-day"}


def test_every_field_a_view_names_is_on_the_type_it_reads():
    manifest = _manifest()
    fields = _types(manifest)
    for view in _views(manifest).values():
        spine = view["spine"]
        named = {spine["entry_type"]: {spine["of"], spine["order"], spine.get("picture"), spine.get("status"), spine["seconds"]["hold"]}}
        if group := spine.get("group"):
            named[spine["entry_type"]].add(group["field"])
            named[group["entry_type"]] = {group["order"]}
        picker = view["picker"]
        named.setdefault(view["entry_type"], set()).update(picker.get("subtitle", []), picker.get("badges", []), {picker["picture"]})
        for lane in view["lanes"]:
            keys = {lane.get(k) for k in ("of", "in", "order", "who", "seconds", "status")}
            named.setdefault(lane["entry_type"], set()).update(keys)
            if placed := lane.get("placed"):
                named[spine["entry_type"]].add(placed["field"])
        for type_slug, keys in named.items():
            assert keys - {None} <= fields[type_slug], (type_slug, (keys - {None}) - fields[type_slug])


def test_the_package_installs_with_nothing_blocked(db_session, workspace):  # noqa: F811
    manifest = service.parse_manifest(PACKAGE.read_text())

    preview = service.preview(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    assert preview.blocked == 0, [(i.slug, i.detail) for i in preview.items if i.status == "blocked"]
    result = service.install(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    db_session.commit()

    assert result.blocked == 0, [(i.slug, i.detail) for i in result.items if i.status == "blocked"]
    made = {t.slug for t in db_session.query(EntryTypes).filter_by(group_id=workspace.id) if t.slug.startswith("demo-")}
    assert made == set(_types(_manifest()))
