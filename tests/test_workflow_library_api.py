"""The Workflow Library over HTTP: `GET /api/automations/library` (every recipe, with what this workspace lacks to use
it, and the names the setup pickers offer) and `POST /api/automations/library/{id}/configure` (a recipe filled in for
the workflow editor — never saved). Workspace admins only, like the rest of /api/automations.

The agent's `draft_workflow(recipe=…)` goes through the same `recipes.configure_for` (tests/test_workflow_library.py)."""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

LIBRARY = "/api/automations/library"


def _configure(recipe_id: str) -> str:
    return f"{LIBRARY}/{recipe_id}/configure"


@fixture
def ws(db_session):
    """A workspace with a campaign entry type (two UTM fields), a newsletter type and a Featured collection; no
    integrations and AI off until a test adds them. The caller is signed in as a workspace ADMIN."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.collections import Collections

    gid = uuid.uuid4()
    slug = f"library-api-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for type_slug, fields in (("campaign", ["utm_source", "utm_medium"]), ("newsletter-issue", ["body", "preview"])):
        schema = {"fields": [{"key": key, "label": key, "type": "text"} for key in fields]}
        db_session.add(EntryTypes(session=db_session, group_id=gid, name=type_slug.title(), slug=type_slug, schema_json=schema))
    db_session.add(Collections(session=db_session, group_id=gid, name="Featured", slug="featured"))
    db_session.commit()
    _sign_in(gid, WorkspaceRole.ADMIN)
    yield SimpleNamespace(gid=gid, session=db_session)

    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.group.group_purge import purge_group_dependents

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(gid, role: WorkspaceRole | None) -> None:
    members = [SimpleNamespace(group_id=gid, workspace_role=role)] if role else []
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(),
        group_id=gid,
        active_group_id=gid,
        admin=False,
        is_superuser=False,
        platform_role=PlatformRole.NONE,
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(gid) else None,
    )


def _connect(ws, provider: str, slug: str, *, enabled: bool = True) -> None:
    from marvin.db.models.groups.integrations import IntegrationModel

    ws.session.add(IntegrationModel(session=ws.session, group_id=ws.gid, provider=provider, name=slug, slug=slug, enabled=enabled, config={}))
    ws.session.commit()


def _library() -> dict:
    res = TestClient(app).get(LIBRARY)
    assert res.status_code == 200, res.text
    return res.json()


def _recipe(library: dict, recipe_id: str) -> dict:
    return next(r for r in library["recipes"] if r["id"] == recipe_id)


# ── Who may ask ────────────────────────────────────────────────────────────────


def test_library_and_configure_are_for_workspace_admins(ws):
    _sign_in(ws.gid, WorkspaceRole.EDITOR)
    client = TestClient(app)

    assert client.get(LIBRARY).status_code == 403
    assert client.post(_configure("utm-librarian"), json={"vars": {}}).status_code == 403


# ── The library ────────────────────────────────────────────────────────────────


def test_library_lists_every_recipe_with_the_pickers_names(ws):
    from marvin.services.automation import recipes

    library = _library()

    assert [r["id"] for r in library["recipes"]] == [r["id"] for r in recipes.entries()]
    utm = _recipe(library, "utm-librarian")
    assert (utm["shape"], utm["status"], utm["categorySlug"]) == ("workflow", "verified-current", "social")
    assert [v["type"] for v in utm["setupVariables"]] == ["entry_type_slug", "field_key", "field_key"]
    assert utm["missing"] == []
    refs = library["refs"]
    assert {"slug": "campaign", "name": "Campaign", "fields": ["utm_source", "utm_medium"]} in refs["entryTypes"]
    assert {"slug": "featured", "name": "Featured"}.items() <= refs["collections"][0].items()
    assert "approved" in refs["statuses"] and "trashed" not in refs["statuses"]


def test_an_idea_says_which_capability_it_waits_on(ws):
    library = _library()

    idea = next(r for r in library["recipes"] if r["shape"] == "idea")
    gap = idea["dependencies"][0]["capability"]
    assert library["capabilities"][gap]["name"]


def test_missing_names_the_unconnected_provider_until_it_is_connected(ws):
    assert _recipe(_library(), "newsletter-delivery")["missing"] == ["needs a connected buttondown integration"]

    _connect(ws, "buttondown", "newsletter", enabled=False)
    assert _recipe(_library(), "newsletter-delivery")["missing"] == ["needs a connected buttondown integration"]

    _connect(ws, "buttondown", "newsletter-live")
    newsletter = _recipe(_library(), "newsletter-delivery")
    assert newsletter["missing"] == []
    assert newsletter["providers"] == ["buttondown"]


def test_a_recipe_needing_ai_operations_is_missing_them_while_ai_is_off(ws):
    assert _recipe(_library(), "seo-assistant")["missing"] == ["needs AI operations, which can't run from workflows here"]


# ── Configure ──────────────────────────────────────────────────────────────────


def test_configure_fills_in_typed_values_and_saves_nothing(ws):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    res = TestClient(app).post(_configure("hourly-site-rebuild"), json={"vars": {"interval_seconds": 7200}})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Every hour, rebuild the site"
    assert body["definition"]["trigger"]["schedule_config"]["interval_seconds"] == 7200  # an integer stays an integer
    assert body["issues"] == []
    assert ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid).count() == 0


def test_configure_reports_what_the_builder_would_flag_without_refusing(ws):
    missing_hook = str(uuid.uuid4())

    values = {"entry_type": "campaign", "announcement_webhook_id": missing_hook}

    res = TestClient(app).post(_configure("publication-announcement"), json={"vars": values})

    assert res.status_code == 200, res.text
    body = res.json()
    assert "{{" not in str(body["definition"])
    assert [i["path"] for i in body["issues"]] == ["actions[0].webhook_id"], body["issues"]
    assert missing_hook in body["issues"][0]["message"]


def test_configure_names_a_bad_variable(ws):
    client = TestClient(app)

    wrong_type = client.post(_configure("hourly-site-rebuild"), json={"vars": {"interval_seconds": "hourly"}})
    missing = client.post(_configure("hourly-site-rebuild"), json={"vars": {}})

    assert wrong_type.status_code == 422 and "interval_seconds" in wrong_type.json()["detail"]
    assert missing.status_code == 422 and "interval_seconds" in missing.json()["detail"]


def test_configure_refuses_what_this_workspace_cannot_use(ws):
    from marvin.services.automation import recipes

    client = TestClient(app)
    idea = next(r["id"] for r in recipes.entries() if r["shape"] == "idea")
    configuration = next(r["id"] for r in recipes.entries() if r["shape"] == "configuration")

    assert client.post(_configure("no-such-recipe"), json={"vars": {}}).status_code == 404
    for recipe_id in (idea, configuration):
        res = client.post(_configure(recipe_id), json={"vars": {}})
        assert res.status_code == 409 and "not runnable" in res.json()["detail"], res.text
    unconnected = client.post(_configure("newsletter-delivery"), json={"vars": {}})
    assert unconnected.status_code == 409 and "buttondown" in unconnected.json()["detail"]
