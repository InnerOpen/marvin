"""Where the app sidebar shows a package: `collections` (the default), `section` or `hidden`, kept on the package's row.

The choice is the workspace's: an update or a re-install keeps it, removing the package forgets it. Owners and admins change it
(`PATCH /api/groups/packages/{slug}`); everyone in the workspace reads it (`GET /api/groups/packages/sidebar`), since every page's
sidebar follows it.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.groups import Groups
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.blueprints import packages as service

URL = "/api/groups/packages"


def _manifest(slug="story-kit", version="1") -> dict:
    return {
        "format": 1,
        "slug": slug,
        "name": "Story kit",
        "version": version,
        "blueprints": [
            {"kind": "collection", "slug": f"{slug}-cast", "name": "Story kit: Cast", "payload": {"name": "Story kit: Cast", "slug": f"{slug}-cast"}},
        ],
    }


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    slug = f"pk-side-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield SimpleNamespace(id=gid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _install(db_session, workspace, version="1", slug="story-kit"):
    service.install(db_session, workspace.id, service.parse_manifest(_manifest(slug, version)))
    db_session.commit()


def _place(db_session, workspace, slug="story-kit") -> str:
    db_session.expire_all()
    return next(p.sidebar for p in service.sidebar_places(db_session, workspace.id) if p.slug == slug)


def _sign_in(workspace, role: WorkspaceRole) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(),
        group_id=workspace.id,
        active_group_id=workspace.id,
        admin=False,
        is_superuser=False,
        full_name="Pat",
        email=f"{workspace.slug}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=workspace.id, workspace_role=role)],
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.id) else None,
    )
    return TestClient(app)


# --- the choice and what keeps it -----------------------------------------------------------------------------------------------------------


def test_a_package_is_placed_under_collections_until_someone_chooses(db_session, workspace):
    _install(db_session, workspace)

    assert _place(db_session, workspace) == "collections"
    assert service.list_packages(db_session, workspace.id)[0].sidebar == "collections"


def test_the_choice_is_kept_on_the_package(db_session, workspace):
    _install(db_session, workspace)

    read = service.set_sidebar(db_session, workspace.id, "story-kit", "section")
    db_session.commit()

    assert read.sidebar == "section"
    assert _place(db_session, workspace) == "section"


def test_an_update_and_a_reinstall_keep_the_choice(db_session, workspace):
    _install(db_session, workspace)
    service.set_sidebar(db_session, workspace.id, "story-kit", "hidden")
    db_session.commit()

    service.update(db_session, workspace.id, service.parse_manifest(_manifest(version="2")))
    db_session.commit()
    assert _place(db_session, workspace) == "hidden"

    _install(db_session, workspace, version="2")
    assert _place(db_session, workspace) == "hidden"


def test_removing_the_package_forgets_the_choice(db_session, workspace):
    _install(db_session, workspace)
    service.set_sidebar(db_session, workspace.id, "story-kit", "section")
    service.remove(db_session, workspace.id, "story-kit")
    db_session.commit()

    assert service.sidebar_places(db_session, workspace.id) == []
    _install(db_session, workspace)
    assert _place(db_session, workspace) == "collections"


def test_choosing_for_a_package_that_is_not_installed_says_so(db_session, workspace):
    with pytest.raises(LookupError, match="No package 'nope'"):
        service.set_sidebar(db_session, workspace.id, "nope", "section")


def test_the_places_name_every_installed_package_and_nothing_it_holds(db_session, workspace):
    _install(db_session, workspace)
    _install(db_session, workspace, slug="film-kit")

    places = service.sidebar_places(db_session, workspace.id)

    assert sorted(p.slug for p in places) == ["film-kit", "story-kit"]
    assert set(places[0].model_dump()) == {"slug", "name", "sidebar"}


# --- the API ----------------------------------------------------------------------------------------------------------------------------


def test_an_admin_changes_it_and_the_answer_is_the_package(db_session, workspace):
    _install(db_session, workspace)

    response = _sign_in(workspace, WorkspaceRole.ADMIN).patch(f"{URL}/story-kit", json={"sidebar": "section"})

    assert response.status_code == 200
    assert (response.json()["slug"], response.json()["sidebar"]) == ("story-kit", "section")
    assert _place(db_session, workspace) == "section"


@pytest.mark.parametrize("body", [{"sidebar": "sideways"}, {"sidebar": ""}, {}])
def test_an_unknown_place_is_refused_and_the_message_names_the_three(db_session, workspace, body):
    _install(db_session, workspace)

    response = _sign_in(workspace, WorkspaceRole.ADMIN).patch(f"{URL}/story-kit", json=body)

    assert response.status_code == 422
    if body:
        assert "'collections', 'section' or 'hidden'" in response.text
    assert _place(db_session, workspace) == "collections"


def test_an_admin_choosing_for_a_missing_package_gets_404(workspace):
    assert _sign_in(workspace, WorkspaceRole.ADMIN).patch(f"{URL}/nope", json={"sidebar": "hidden"}).status_code == 404


def test_a_member_reads_the_places_but_cannot_change_them(db_session, workspace):
    _install(db_session, workspace)
    client = _sign_in(workspace, WorkspaceRole.EDITOR)

    assert client.get(f"{URL}/sidebar").json() == [{"slug": "story-kit", "name": "Story kit", "sidebar": "collections"}]
    assert client.patch(f"{URL}/story-kit", json={"sidebar": "hidden"}).status_code == 403
    assert client.get(URL).status_code == 403
    assert _place(db_session, workspace) == "collections"


def test_the_routes_need_a_login(client):
    assert client.get(f"{URL}/sidebar").status_code in (401, 403)
    assert client.patch(f"{URL}/story-kit", json={"sidebar": "hidden"}).status_code in (401, 403)
