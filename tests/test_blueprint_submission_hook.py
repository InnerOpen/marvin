"""The blueprint hook on a form's submission settings: an `entry_fields` blueprint may carry `payload.submission` — `destination`
and/or `kind` and nothing else — which is set on the (submittable) type for the keys it doesn't already store. Driven by the Buttondown
plugin, whose signup type becomes `kind: signup, destination: audience`.
"""

import pytest
from pydantic import ValidationError

from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.schemas.platform.blueprints import Blueprint
from marvin.services.blueprints import already_applied, apply_blueprint
from marvin.services.entry_listing import is_listed_type, submission_destination, submission_kind
from tests.test_blueprint_kinds import workspace  # noqa: F401  (the `workspace` fixture)

PARAM = [{"key": "signup_type", "label": "Which type", "kind": "entry_type", "default": "newsletter"}]
EMAIL = {"key": "email", "label": "Email", "type": "text", "required": True}


def _hook(submission=None, fields=(), **over):
    return Blueprint(
        kind="entry_fields",
        slug="list-signup-settings",
        name="Signup settings",
        source="listco",
        parameters=PARAM,
        payload={"entry_type": "{{signup_type}}", "fields": list(fields), "submission": submission or {"kind": "signup", "destination": "audience"}},
        **over,
    )


def _type(db_session, workspace, slug="newsletter", caps=None, fields=()):  # noqa: F811
    row = EntryTypes(session=db_session, group_id=workspace.id, name=slug, slug=slug, schema_json={"fields": list(fields)}, capabilities_json=caps)
    db_session.add(row)
    db_session.commit()
    return row


def _reload(db_session, type_id):
    db_session.expire_all()
    return db_session.get(EntryTypes, type_id)


# ── the declaration ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_blueprint_may_declare_only_destination_and_kind():
    assert _hook().payload["submission"] == {"kind": "signup", "destination": "audience"}
    assert _hook({"kind": "signup"}, fields=[EMAIL])  # fields beside it are fine
    for bad in ({"honeypot_field": "x"}, {"kind": "signup", "notify": False}, {"kind": "newsletter"}, {"destination": "inbox"}, "signup"):
        with pytest.raises(ValidationError):
            _hook(bad)
    with pytest.raises(ValidationError):  # an empty hook says nothing
        Blueprint(kind="entry_fields", slug="x", name="x", payload={"entry_type": "newsletter", "fields": [EMAIL], "submission": {}})
    with pytest.raises(ValidationError):  # neither fields nor a submission
        Blueprint(kind="entry_fields", slug="x", name="x", payload={"entry_type": "newsletter", "fields": []})
    with pytest.raises(ValidationError):  # still needs the type
        Blueprint(kind="entry_fields", slug="x", name="x", payload={"fields": [], "submission": {"kind": "signup"}})


# ── applying ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_applying_makes_the_type_an_audience_signup_form(db_session, workspace):  # noqa: F811
    row = _type(db_session, workspace, caps={"publishable": True, "submittable": True, "listed": False, "submission": {"notify": False}})
    assert submission_kind(row) == "message"
    bp = _hook()
    assert already_applied(db_session, workspace.id, bp) is False
    result = apply_blueprint(db_session, workspace.id, bp)
    assert result.created and "kind signup" in result.detail and "destination audience" in result.detail
    row = _reload(db_session, row.id)
    assert (submission_kind(row), submission_destination(row)) == ("signup", "audience") and is_listed_type(row) is False
    assert row.capabilities_json["submission"] == {"notify": False, "kind": "signup", "destination": "audience"}  # the other settings are kept
    assert row.capabilities_json["publishable"] is True
    assert already_applied(db_session, workspace.id, bp) is True
    again = apply_blueprint(db_session, workspace.id, bp)
    assert not again.created and "already has every field and setting" in again.detail


def test_a_setting_the_workspace_stored_is_kept_and_only_the_missing_key_is_set(db_session, workspace):  # noqa: F811
    row = _type(db_session, workspace, caps={"submittable": True, "listed": True, "submission": {"destination": "entries"}})
    result = apply_blueprint(db_session, workspace.id, _hook())
    row = _reload(db_session, row.id)
    assert result.created and result.detail.startswith("set kind signup")
    assert (submission_kind(row), submission_destination(row)) == ("signup", "entries") and is_listed_type(row) is True  # their destination stands
    chosen = _type(db_session, workspace, "chosen", caps={"submittable": True, "submission": {"kind": "message", "destination": "entries"}})
    kept = apply_blueprint(db_session, workspace.id, _hook(), {"signup_type": "chosen"})
    assert not kept.created and _reload(db_session, chosen.id).capabilities_json["submission"] == {"kind": "message", "destination": "entries"}
    assert already_applied(db_session, workspace.id, _hook(), {"signup_type": "chosen"}) is True  # their choice counts as done


def test_a_type_with_no_submission_block_gets_one(db_session, workspace):  # noqa: F811
    row = _type(db_session, workspace, caps={"submittable": True})
    apply_blueprint(db_session, workspace.id, _hook({"kind": "signup"}))
    row = _reload(db_session, row.id)
    assert row.capabilities_json == {"submittable": True, "submission": {"kind": "signup"}}


def test_a_type_that_is_not_a_form_is_refused_with_the_reason(db_session, workspace):  # noqa: F811
    row = _type(db_session, workspace, caps={"publishable": True})
    result = apply_blueprint(db_session, workspace.id, _hook())
    assert not result.created and "not a form" in result.detail
    assert _reload(db_session, row.id).capabilities_json == {"publishable": True}
    missing = apply_blueprint(db_session, workspace.id, _hook(), {"signup_type": "nope"})
    assert not missing.created and "nope" in missing.detail


def test_fields_and_settings_apply_together_and_each_alone_is_still_work_to_do(db_session, workspace):  # noqa: F811
    row = _type(db_session, workspace, caps={"submittable": True, "listed": False})
    bp = _hook(fields=[EMAIL])
    result = apply_blueprint(db_session, workspace.id, bp)
    row = _reload(db_session, row.id)
    assert "added email" in result.detail and "kind signup" in result.detail
    assert [f["key"] for f in row.schema_json["fields"]] == ["email"] and submission_kind(row) == "signup"
    # a type that has the field but not the setting, and the reverse
    only_field = _type(db_session, workspace, "has-email", caps={"submittable": True}, fields=[EMAIL])
    assert already_applied(db_session, workspace.id, bp, {"signup_type": "has-email"}) is False
    only_setting = _type(db_session, workspace, "marked", caps={"submittable": True, "submission": {"kind": "signup", "destination": "audience"}})
    assert already_applied(db_session, workspace.id, bp, {"signup_type": "marked"}) is False
    apply_blueprint(db_session, workspace.id, bp, {"signup_type": "has-email"})
    assert submission_kind(_reload(db_session, only_field.id)) == "signup" and len(_reload(db_session, only_field.id).schema_json["fields"]) == 1
    apply_blueprint(db_session, workspace.id, bp, {"signup_type": "marked"})
    assert [f["key"] for f in _reload(db_session, only_setting.id).schema_json["fields"]] == ["email"]


def test_choosing_a_destination_sets_listed_and_the_entries_follow(db_session, workspace):  # noqa: F811
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.services.collections.smart_collections import sync_collection

    row = _type(db_session, workspace, "form", caps={"submittable": True, "listed": False})  # an Audience form by default
    entry = Entries(session=db_session, group_id=workspace.id, entry_type_id=row.id, title="x", slug="x", status="inbox", data_json={})
    db_session.add(entry)
    inbox = Collections(
        session=db_session, group_id=workspace.id, slug="inbox-x", name="Inbox X", is_smart=True, smart_rules={"statuses": ["inbox"], "match": "all"}
    )
    db_session.add(inbox)
    db_session.commit()
    sync_collection(db_session, workspace.id, inbox)
    db_session.commit()
    assert db_session.query(EntryCollections).filter_by(collection_id=inbox.id).count() == 0  # internal: not in the Inbox
    apply_blueprint(db_session, workspace.id, _hook({"destination": "entries"}), {"signup_type": "form"})
    row = _reload(db_session, row.id)
    assert submission_destination(row) == "entries" and is_listed_type(row) is True
    assert db_session.query(EntryCollections).filter_by(collection_id=inbox.id).count() == 1  # its entry follows into the Inbox
