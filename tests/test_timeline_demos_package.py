"""The Timeline Demos example package (docs/examples): four timeline views that are not sound, two laid in order (minutes, days) and two placed
by date with a row per person (days, hours).

The contract under test: the file parses as a package, each view passes the view validator in its unit, every entry type and collection
installs into a workspace without a block (so the validators of those kinds accept them too), the types nobody makes by hand stay out of the New
menu, every field a view names exists on the type it reads (a date where it places by date, a reference where it draws a row per value), and
the version-1 views are as they were.
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
    assert (manifest.slug, manifest.version) == ("timeline-demos", "2")
    views = _views(_manifest())
    units = {slug: view["unit"] for slug, view in views.items()}
    assert units == {"event-agenda": "minutes", "content-plan": "days", "team-calendar": "days", "shift-roster": "hours"}
    for slug, view in views.items():
        assert payload_problem(view, slug) is None
        assert view["sidebar"] and view["picker"]


def test_every_type_is_prefixed_demo_and_the_ones_nobody_makes_by_hand_stay_out_of_the_new_menu():
    manifest = _manifest()
    types = {b["slug"]: b["payload"] for b in manifest["blueprints"] if b["kind"] == "entry_type"}
    assert all(slug.startswith("demo-") for slug in types)
    hidden = {slug for slug, t in types.items() if (t.get("capabilities_json") or {}).get("offer_in_new") is False}
    assert hidden == {"demo-block", "demo-day", "demo-roster-day"}


def _field_types(manifest: dict) -> dict[str, dict[str, dict]]:
    types = (b for b in manifest["blueprints"] if b["kind"] == "entry_type")
    return {b["slug"]: {f["key"]: f for f in b["payload"]["schema_json"]["fields"]} for b in types}


def test_every_field_a_view_names_is_on_the_type_it_reads():
    manifest = _manifest()
    fields = _types(manifest)
    for view in _views(manifest).values():
        spine = view["spine"]
        own = ("of", "order", "picture", "status", "text", "start")
        named = {spine["entry_type"]: {spine["seconds"]["hold"], *(spine.get(k) for k in own)}}
        if group := spine.get("group"):
            named[spine["entry_type"]].add(group["field"])
            named[group["entry_type"]] = {group["order"]}
        picker = view["picker"]
        subtitle = [s if isinstance(s, str) else s["field"] for s in picker.get("subtitle", [])]
        named.setdefault(view["entry_type"], set()).update(
            subtitle, picker.get("badges", []), {picker.get("picture")}, view.get("range", {}).values()
        )
        for lane in view["lanes"]:
            keys = {lane.get(k) for k in ("of", "in", "start", "order", "who", "seconds", "status", "per")}
            named.setdefault(lane["entry_type"], set()).update(keys)
            if placed := lane.get("placed"):
                named[spine["entry_type"]].add(placed["field"])
        for type_slug, keys in named.items():
            assert keys - {None} <= fields[type_slug], (type_slug, (keys - {None}) - fields[type_slug])


def test_a_view_placed_by_date_reads_date_fields_and_draws_its_rows_per_a_reference():
    manifest = _manifest()
    types = _field_types(manifest)
    dated = {slug: view for slug, view in _views(manifest).items() if view["spine"].get("start")}
    assert set(dated) == {"team-calendar", "shift-roster"}
    for view in dated.values():
        assert types[view["spine"]["entry_type"]][view["spine"]["start"]]["type"] == "date"
        assert {types[view["entry_type"]][key]["type"] for key in view["range"].values()} == {"date"}
        for lane in view["lanes"]:
            assert types[lane["entry_type"]][lane["start"]]["type"] in ("date", "datetime")
            person = types[lane["entry_type"]][lane["per"]]["ref"]
            assert lane["per_order"] in types[person], "per_order is a field of the entry the row is of"
    assert types["demo-shift"]["start"]["type"] == "datetime", "the roster places shifts by date and time"


def test_the_version_one_views_and_their_types_are_as_they_were():
    blueprints = {b["slug"]: b for b in _manifest()["blueprints"]}
    agenda, plan = blueprints["event-agenda"]["payload"], blueprints["content-plan"]["payload"]
    assert (agenda["unit"], agenda["spine"]["entry_type"], [lane["id"] for lane in agenda["lanes"]]) == (
        "minutes",
        "demo-session",
        ["people", "cues"],
    )
    assert (plan["unit"], plan["spine"]["entry_type"], [lane["id"] for lane in plan["lanes"]]) == ("days", "demo-day", ["posts"])
    assert not any(view["spine"].get("start") or any(lane.get("per") for lane in view["lanes"]) for view in (agenda, plan))


def test_the_package_installs_with_nothing_blocked(db_session, workspace):  # noqa: F811
    manifest = service.parse_manifest(PACKAGE.read_text())

    preview = service.preview(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    assert preview.blocked == 0, [(i.slug, i.detail) for i in preview.items if i.status == "blocked"]
    result = service.install(db_session, workspace.id, manifest, actor_id=workspace.user_id)
    db_session.commit()

    assert result.blocked == 0, [(i.slug, i.detail) for i in result.items if i.status == "blocked"]
    made = {t.slug for t in db_session.query(EntryTypes).filter_by(group_id=workspace.id) if t.slug.startswith("demo-")}
    assert made == set(_types(_manifest()))
