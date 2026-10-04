"""`POST /api/groups/integrations/{id}/options` — the choices for an action input, from the read action its
`x-marvin-options` hint names. Only hinted actions can run this way, with the hint's own args."""

import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from fastapi.testclient import TestClient  # noqa: E402
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.app import app  # noqa: E402
from marvin.core.dependencies import get_current_user  # noqa: E402
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole  # noqa: E402

BASE = "/api/groups/integrations"


def _hint(action: str, value: str = "path", label: str | None = "name", **extra) -> dict:
    hint = {"action": action, "value": value, **extra}
    if label is not None:
        hint["label"] = label
    return {"type": "string", "x-marvin-options": hint}


class _Picker(IntegrationProvider):
    slug = "test_picker"
    name = "Picker"
    actions = (
        ProviderAction(
            key="trigger",
            label="Trigger",
            input_schema={
                "type": "object",
                "properties": {
                    "path": _hint("list_workflows", args={"active": True}),
                    "item": _hint("list_items", value="id", label=None),
                    "many": _hint("list_many", value="id", label="title"),
                    "flaky": _hint("list_broken"),
                    "crashy": _hint("list_crash"),
                    "shapeless": _hint("list_shapeless"),
                    "ghost": _hint("not_an_action"),
                    "gated": _hint("generate_things"),
                    "malformed": {"type": "string", "x-marvin-options": {"action": "list_items"}},
                    "plain": {"type": "string"},
                },
            },
        ),
        ProviderAction(key="list_workflows", label="List workflows"),
        ProviderAction(key="list_items", label="List items"),
        ProviderAction(key="list_many", label="List many"),
        ProviderAction(key="list_broken", label="Broken"),
        ProviderAction(key="list_crash", label="Crash"),
        ProviderAction(key="list_shapeless", label="Shapeless"),
        ProviderAction(key="delete_everything", label="Delete everything"),
        ProviderAction(key="generate_things", label="Generate", requires_approval=True),
    )

    calls: list = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, args))
        if key == "list_workflows":
            return [
                {"path": "marvin/inquiry", "name": "Inquiry"},
                {"path": "marvin/digest", "name": ""},  # empty label → the value
                {"name": "no path"},  # no value → skipped
                {"path": "marvin/inquiry", "name": "Duplicate"},  # repeated value → skipped
                "loose",  # a bare value is its own label
            ]
        if key == "list_items":
            return {"items": [{"id": 7, "name": "Seven"}, {"id": 8}], "next": None}
        if key == "list_many":
            return {"items": [{"id": i, "title": f"Item {i}"} for i in range(800)]}
        if key == "list_broken":
            raise ValueError("n8n said 401: API key rejected")
        if key == "list_crash":
            raise RuntimeError("Traceback (most recent call last): secret internals")
        if key == "list_shapeless":
            return {"workflows": []}
        if key == "delete_everything":
            raise AssertionError("must never run through the option endpoint")
        return {}


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    monkeypatch.setitem(INTEGRATION_REGISTRY, _Picker.slug, _Picker())
    _Picker.calls = []


def _make_workspace(db_session, marker: str):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    group = Groups(session=db_session, name=f"opt-{marker}", slug=f"opt-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"opt-{marker}",
            email=f"opt-{marker}@t.test",
            full_name="OPT",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    return gid, uid


def _make_integration(db_session, gid, *, enabled: bool = True, provider: str = _Picker.slug) -> uuid.UUID:
    from marvin.db.models.groups.integrations import IntegrationModel

    row = IntegrationModel(session=db_session, group_id=gid, provider=provider, name="Picker", slug=f"picker_{uuid.uuid4().hex[:6]}", status="ok")
    row.enabled = enabled
    db_session.add(row)
    db_session.flush()
    return row.id


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    marker = uuid.uuid4().hex[:8]
    gid, uid = _make_workspace(db_session, marker)
    other_gid, other_uid = _make_workspace(db_session, f"{marker}x")
    ws = SimpleNamespace(
        gid=gid,
        uid=uid,
        integration=_make_integration(db_session, gid),
        disabled=_make_integration(db_session, gid, enabled=False),
        orphan=_make_integration(db_session, gid, provider="ghost_provider"),
        foreign=_make_integration(db_session, other_gid),
    )
    db_session.commit()
    yield ws
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    for g, u in ((gid, uid), (other_gid, other_uid)):
        db_session.query(IntegrationModel).filter(IntegrationModel.group_id == g).delete()
        purge_group_dependents(db_session, g)
        db_session.query(Users).filter(Users.id == u).delete()
        db_session.query(Groups).filter(Groups.id == g).delete()
    db_session.commit()


def _client(ws) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ws.uid,
        group_id=ws.gid,
        active_group_id=ws.gid,
        admin=False,
        is_superuser=False,
        full_name="OPT",
        platform_role=PlatformRole.NONE,
        get_workspace_role=lambda group_id: WorkspaceRole.ADMIN if str(group_id) == str(ws.gid) else None,
    )
    return TestClient(app)


def _options(ws, input_key: str, integration_id=None, action_key: str = "trigger"):
    return _client(ws).post(f"{BASE}/{integration_id or ws.integration}/options", json={"action_key": action_key, "input": input_key})


def test_hint_resolves_to_value_label_pairs_with_the_hints_static_args(workspace):
    res = _options(workspace, "path")
    assert res.status_code == 200, res.text
    assert res.json() == [
        {"value": "marvin/inquiry", "label": "Inquiry"},
        {"value": "marvin/digest", "label": "marvin/digest"},
        {"value": "loose", "label": "loose"},
    ]
    assert _Picker.calls == [("list_workflows", {"active": True})]


def test_items_shape_and_label_defaulting_to_value_field(workspace):
    res = _client(workspace).post(f"{BASE}/{workspace.integration}/options", json={"actionKey": "trigger", "input": "item"})
    assert res.status_code == 200, res.text
    assert res.json() == [{"value": 7, "label": "7"}, {"value": 8, "label": "8"}]


def test_options_are_capped_at_500(workspace):
    res = _options(workspace, "many")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 500
    assert body[0] == {"value": 0, "label": "Item 0"}


@pytest.mark.parametrize("input_key", ["plain", "missing_input"])
def test_input_without_a_hint_is_refused_and_runs_nothing(workspace, input_key):
    res = _options(workspace, input_key)
    assert res.status_code == 422
    assert "no option source" in res.json()["detail"]
    assert _Picker.calls == []


def test_an_unhinted_action_cannot_be_reached(workspace):
    # Naming the read/destructive action itself as the action_key gets nothing: it has no hinted inputs.
    for action_key in ("delete_everything", "list_workflows"):
        res = _options(workspace, "path", action_key=action_key)
        assert res.status_code == 422, res.text
    assert _Picker.calls == []


def test_a_hint_naming_another_providers_or_no_action_is_refused(workspace):
    res = _options(workspace, "ghost")
    assert res.status_code == 422
    assert "not an action of this provider" in res.json()["detail"]


def test_a_hint_naming_an_action_that_needs_approval_is_refused(workspace):
    res = _options(workspace, "gated")
    assert res.status_code == 422
    assert "needs approval" in res.json()["detail"]
    assert _Picker.calls == []


def test_a_malformed_hint_is_refused(workspace):
    res = _options(workspace, "malformed")
    assert res.status_code == 422
    assert "malformed" in res.json()["detail"]


def test_unknown_action_is_404(workspace):
    assert _options(workspace, "path", action_key="nope").status_code == 404


def test_provider_error_is_a_clean_4xx(workspace):
    res = _options(workspace, "flaky")
    assert res.status_code == 422
    assert res.json()["detail"] == "Couldn't load the options: n8n said 401: API key rejected"


def test_provider_crash_does_not_leak_internals(workspace):
    res = _options(workspace, "crashy")
    assert res.status_code == 422
    assert res.json()["detail"] == "Couldn't load the options: the integration failed."


def test_a_result_that_is_not_a_list_is_a_clean_4xx(workspace):
    res = _options(workspace, "shapeless")
    assert res.status_code == 422
    assert "no list" in res.json()["detail"]


def test_disabled_and_orphaned_connections_are_refused(workspace):
    assert _options(workspace, "path", integration_id=workspace.disabled).status_code == 409
    assert _options(workspace, "path", integration_id=workspace.orphan).status_code == 409


def test_another_workspaces_connection_is_not_found(workspace):
    res = _options(workspace, "path", integration_id=workspace.foreign)
    assert res.status_code == 404
    assert _Picker.calls == []
