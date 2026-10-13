"""No API response may carry a user's password hash, or any other credential.

`UserRead` — the response model of every endpoint that returns a user — used to extend `UserCreate`,
which declares `password`. Routes return the repository's `PrivateUser` (which holds the stored bcrypt
hash) under `response_model=UserRead`, so the hash went out with every create, list, get, update,
registration and `/api/self` response. `UserRead` now builds on a credential-free base; these tests
pin both the live responses and the OpenAPI response schemas, so a new route can't reintroduce it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core import security
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole
from marvin.repos.all_repositories import get_repositories

# A key is a credential if its name contains any of these (case-insensitive, `_` ignored).
SECRET_KEY_PARTS = ("password", "hash", "secret", "token")
# OpenAPI response schemas legitimately return freshly issued tokens (login, PATs, reset tokens) and
# `has*` flags, so the schema-wide guard only looks for stored credentials.
STORED_CREDENTIAL_KEY_PARTS = ("password", "hash")
ALLOWED_RESPONSE_KEYS = {"haspassword"}


def _secret_keys(node, parts=SECRET_KEY_PARTS, path="$") -> list[str]:
    """Every key, at any depth, whose name looks like a credential."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if any(part in key.lower().replace("_", "") for part in parts):
                found.append(here)
            found += _secret_keys(value, parts, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found += _secret_keys(item, parts, f"{path}[{i}]")
    return found


@fixture
def world(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, admin_id = uuid.uuid4(), uuid.uuid4()
    slug = f"pwhash-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    password_hash = security.hash_password("correct horse battery staple")
    db_session.execute(
        Users.__table__.insert().values(
            id=admin_id,
            group_id=gid,
            username=f"{slug}-admin",
            email=f"{slug}-admin@t.test",
            full_name="Admin Person",
            password=password_hash,
            is_superuser=False,
            platform_role=PlatformRole.SUPER_ADMIN.value,
            auth_method="MARVIN",
        )
    )
    db_session.commit()

    # The real PrivateUser, exactly as get_current_user loads it: hash and all.
    admin = get_repositories(db_session, group_id=None).users.get_one(admin_id, "id", any_case=False)
    assert admin.password == password_hash
    app.dependency_overrides[get_current_user] = lambda: admin
    yield type("World", (), {"group": slug, "admin_id": admin_id, "password_hash": password_hash})

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(Users).filter(Users.group_id == gid).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id == gid).delete(synchronize_session=False)
    db_session.commit()


def _create(client: TestClient, world):
    return client.post(
        "/api/admin/users",
        json={
            "email": f"{world.group}-new@t.test",
            "username": f"{world.group}-new",
            "fullName": "New Person",
            "group": world.group,
            "password": "another secret pw",
        },
    )


ENDPOINTS = {
    "admin create": _create,
    "admin list": lambda client, world: client.get("/api/admin/users", params={"perPage": -1}),
    "admin get": lambda client, world: client.get(f"/api/admin/users/{world.admin_id}"),
    "admin update": lambda client, world: client.put(f"/api/admin/users/{world.admin_id}", json={"fullName": "Renamed Admin"}),
    "self": lambda client, world: client.get("/api/self"),
}


@pytest.mark.parametrize("call", ENDPOINTS.values(), ids=ENDPOINTS.keys())
def test_user_responses_carry_no_credentials(world, call):
    res = call(TestClient(app), world)

    assert res.status_code in (200, 201), res.text
    body = res.json()
    assert _secret_keys(body) == []
    leaked = world.password_hash in res.text  # not asserted directly, so a failure doesn't print the hash
    assert not leaked
    # Not vacuous: the response really is the user(s).
    users = body["items"] if "items" in body else [body]
    assert any(u["id"] == str(world.admin_id) or u["email"].endswith("-new@t.test") for u in users)


def _resolve(spec: dict, schema: dict, seen: set[str]) -> list[dict]:
    """The schema and every schema reachable from it, following $refs once each."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return []
        seen.add(name)
        schema = spec["components"]["schemas"][name]
    out = [schema]
    for key in ("properties", "$defs"):
        for sub in schema.get(key, {}).values():
            out += _resolve(spec, sub, seen)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            out += _resolve(spec, schema[key], seen)
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            out += _resolve(spec, sub, seen)
    return out


def test_no_response_schema_declares_a_stored_credential():
    """Structural guard over every route, including ones the live test doesn't call (e.g. registration)."""
    spec = app.openapi()
    leaks = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status_code, response in operation.get("responses", {}).items():
                for media in response.get("content", {}).values():
                    for schema in _resolve(spec, media.get("schema", {}), set()):
                        for key in schema.get("properties", {}):
                            if key.lower() not in ALLOWED_RESPONSE_KEYS and _secret_keys({key: None}, STORED_CREDENTIAL_KEY_PARTS):
                                leaks.append(f"{method.upper()} {path} {status_code}: {key}")
    assert leaks == []
