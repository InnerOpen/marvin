"""SMTP passwords route through the secret backend, not a bespoke column.

The profile stores only `secret_ref`; a literal password lives in an auto-managed secret
(`SMTP_<id>`), and the field also accepts a reference to an existing secret (`{{SLUG}}` or a bare
uppercase `SLUG`). The reference path must never let a profile own — and later delete — a secret the
user pointed at.
"""

import uuid

from pytest import fixture

from marvin.db.models.groups import Groups
from marvin.db.models.groups.smtp_profiles import smtp_secret_ref
from marvin.routes.groups.smtp_controller import _password_reference
from marvin.services.secrets import get_secret_backend


@fixture
def group(db_session):
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"smtp-{gid.hex[:8]}", slug=f"smtp-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    yield gid
    from marvin.db.models.groups.secrets import WorkspaceSecret

    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_secret_ref_is_deterministic_and_slug_safe():
    pid = uuid.UUID("38794b23-9e75-4af5-8355-8da5bec2d67e")
    ref = smtp_secret_ref(pid)
    assert ref == "SMTP_38794B239E754AF583558DA5BEC2D67E"
    # Stable across UUID vs string forms (controller passes a UUID, the migration a row value).
    assert smtp_secret_ref(str(pid)) == ref
    # Uppercase alnum/underscore only — a valid {{SLUG}} identifier.
    assert ref.replace("_", "").isalnum() and ref.isupper()


def test_braced_reference_is_recognised(group):
    assert _password_reference("{{ MY_SMTP_PW }}", group) == "MY_SMTP_PW"
    assert _password_reference("{{SIMPLE}}", group) == "SIMPLE"


def test_bare_slug_is_a_reference_only_when_it_exists(group):
    get_secret_backend().set("SHARED_PW", "sekret", group)

    assert _password_reference("SHARED_PW", group) == "SHARED_PW"  # exists → reference
    assert _password_reference("MISSING_PW", group) is None  # unknown uppercase token → literal


def test_literal_passwords_are_not_treated_as_references(group):
    # A real password, even an uppercase-looking one, is a literal unless it names an existing secret.
    assert _password_reference("hunter2!", group) is None
    assert _password_reference("s3cr3t p@ss", group) is None
    assert _password_reference("lowercase_ref", group) is None  # lowercase never a secret slug
