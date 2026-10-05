"""One entry per person: a submittable type's `match_field` folds a repeat submission into the
submitter's existing entry (routes/publish/forms_controller.py::_submit_to_entry_type).

Driven through the real submit function against the test database. Submission protection's verdict is
pinned per test (clean or flagged) so platform settings other tests write can't change the outcome.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from pytest import fixture

from marvin.routes.publish import forms_controller
from marvin.schemas.platform.entry_type_rendering import SubmissionConfig
from marvin.services.entries.query import identity_value
from marvin.services.security.submission_protection import Verdict

SCHEMA = {
    "fields": [
        {"key": "email", "label": "Email", "type": "text"},
        {"key": "name", "label": "Name", "type": "text"},
        {"key": "member_id", "label": "Member id", "type": "text"},
    ]
}


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"dedupe-{marker}", slug=f"dedupe-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    etype = EntryTypes(
        session=db_session,
        group_id=gid,
        name="Newsletter",
        slug="newsletter",
        schema_json=SCHEMA,
        capabilities_json={"submittable": True, "publishable": False, "submission": {"matchField": "email"}},
    )
    db_session.add(etype)
    db_session.commit()
    yield SimpleNamespace(group=group, entry_type=etype)
    db_session.rollback()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture
def verdict(monkeypatch):
    """Pin submission protection's verdict: `verdict.flag = True` makes the next submissions suspicious."""
    state = SimpleNamespace(flag=False)
    monkeypatch.setattr(
        forms_controller,
        "evaluate",
        lambda policy, data, ip: Verdict(reasons=["blocked_domain:example.com"]) if state.flag else Verdict(),
    )
    return state


def _submit(db_session, ws, data: dict, cfg: SubmissionConfig | None = None):
    """Submit once; returns (response, [(event name, document data), …] in dispatch order)."""
    cfg = cfg or SubmissionConfig(success_message="Thanks!", redirect_url="/thanks", match_field="email")
    request = SimpleNamespace(headers={"user-agent": "pytest"}, client=SimpleNamespace(host="203.0.113.7"))
    bg = BackgroundTasks()
    response = asyncio.run(forms_controller._submit_to_entry_type(ws.entry_type, cfg, dict(data), request, ws.group, bg, db_session))
    events = [(t.kwargs["event"].event_type.name, t.kwargs["event"].document_data) for t in bg.tasks]
    return response, events


def _entries(db_session, ws):
    from marvin.db.models.platform import Entries

    db_session.expire_all()
    return db_session.query(Entries).filter(Entries.group_id == ws.group.id).order_by(Entries.created_at).all()


def _received(events):
    return next(doc for name, doc in events if name == "form_submission_received")


def _set_status(db_session, entry, status):
    entry.status = status
    db_session.commit()


def test_repeat_submission_updates_the_one_entry(db_session, workspace, verdict):
    first, _ = _submit(db_session, workspace, {"email": "ann@example.com", "name": "Ann"})
    (entry,) = _entries(db_session, workspace)
    received_at = entry.metadata_json["submission"]["received_at"]

    second, events = _submit(db_session, workspace, {"email": "ann@example.com", "name": "Ann"})

    (entry,) = _entries(db_session, workspace)
    sub = entry.metadata_json["submission"]
    assert entry.status == "inbox"
    assert sub["submission_count"] == 2
    assert sub["received_at"] == received_at  # the first one is kept
    assert sub["last_received_at"] >= received_at
    assert second.submission_id == first.submission_id == entry.id

    names = [name for name, _ in events]
    assert "entry_created" not in names
    assert names.index("entry_updated") < names.index("form_submission_received")  # workflows read the updated entry
    doc = _received(events)
    assert (doc.duplicate, doc.existing_entry_id, doc.previous_status, doc.status) == (True, entry.id, "inbox", "inbox")


def test_third_submission_counts_three(db_session, workspace, verdict):
    for _ in range(3):
        _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    assert entry.metadata_json["submission"]["submission_count"] == 3


def test_published_entry_stays_published(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    _set_status(db_session, entry, "published")

    _, events = _submit(db_session, workspace, {"email": "ann@example.com"})

    (entry,) = _entries(db_session, workspace)
    assert entry.status == "published"
    doc = _received(events)
    assert (doc.duplicate, doc.previous_status, doc.status) == (True, "published", "published")


def test_archived_entry_reopens_to_inbox(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    _set_status(db_session, entry, "archived")

    _, events = _submit(db_session, workspace, {"email": "ann@example.com"})

    (entry,) = _entries(db_session, workspace)
    assert entry.status == "inbox"
    names = [name for name, _ in events]
    assert names.index("entry_updated") < names.index("entry_restored") < names.index("form_submission_received")
    doc = _received(events)
    assert (doc.previous_status, doc.status) == ("archived", "inbox")


def test_needs_review_entry_keeps_its_status(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    _set_status(db_session, entry, "needs_review")
    _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    assert entry.status == "needs_review"


def test_case_and_whitespace_variants_of_an_email_match(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "Ann@Example.com"})
    _submit(db_session, workspace, {"email": "  ann@EXAMPLE.COM \t"})
    (entry,) = _entries(db_session, workspace)
    assert entry.data_json["email"] == "Ann@Example.com"  # the match field keeps its stored spelling
    assert entry.metadata_json["submission"]["submission_count"] == 2


def test_other_fields_are_trimmed_but_case_sensitive(db_session, workspace, verdict):
    cfg = SubmissionConfig(match_field="member_id")
    _submit(db_session, workspace, {"member_id": "A-12"}, cfg)
    _submit(db_session, workspace, {"member_id": "  A-12 "}, cfg)
    assert len(_entries(db_session, workspace)) == 1
    _submit(db_session, workspace, {"member_id": "a-12"}, cfg)
    assert len(_entries(db_session, workspace)) == 2


def test_different_email_creates_a_new_entry(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com"})
    _, events = _submit(db_session, workspace, {"email": "bob@example.com"})
    assert len(_entries(db_session, workspace)) == 2
    doc = _received(events)
    assert (doc.duplicate, doc.existing_entry_id, doc.previous_status) == (False, None, None)


def test_a_submission_without_the_match_value_creates_a_new_entry(db_session, workspace, verdict):
    cfg = SubmissionConfig(match_field="member_id")
    _submit(db_session, workspace, {"email": "ann@example.com", "member_id": ""}, cfg)
    _submit(db_session, workspace, {"email": "ann@example.com", "member_id": "  "}, cfg)
    assert len(_entries(db_session, workspace)) == 2  # an empty identity never matches another empty one


def test_new_non_empty_values_merge_and_other_metadata_survives(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com", "name": "Ann", "member_id": "A-12"})
    (entry,) = _entries(db_session, workspace)
    entry.metadata_json = {**entry.metadata_json, "buttondown_subscriber_id": "sub_123"}
    title = entry.title
    db_session.commit()

    _submit(db_session, workspace, {"email": "ANN@example.com", "name": "Ann Lee", "member_id": "  "})

    (entry,) = _entries(db_session, workspace)
    assert entry.data_json == {"email": "ann@example.com", "name": "Ann Lee", "member_id": "A-12"}
    assert entry.metadata_json["buttondown_subscriber_id"] == "sub_123"
    assert entry.title == title


def test_suspicious_repeat_creates_a_needs_review_entry_and_leaves_the_original(db_session, workspace, verdict):
    _submit(db_session, workspace, {"email": "ann@example.com", "name": "Ann"})
    (original,) = _entries(db_session, workspace)
    original_id, original_meta = original.id, dict(original.metadata_json)

    verdict.flag = True
    _, events = _submit(db_session, workspace, {"email": "ann@example.com", "name": "Spam"})

    entries = _entries(db_session, workspace)
    assert len(entries) == 2
    original = next(e for e in entries if e.id == original_id)
    flagged = next(e for e in entries if e.id != original_id)
    assert (original.data_json["name"], original.metadata_json, original.status) == ("Ann", original_meta, "inbox")
    assert flagged.status == "needs_review"
    reasons = flagged.metadata_json["submission"]["review_reasons"]
    assert reasons == ["blocked_domain:example.com", f"matches existing entry {original_id}"]
    assert "entry_created" in [name for name, _ in events]
    doc = _received(events)
    assert (doc.flagged, doc.duplicate, doc.existing_entry_id, doc.previous_status) == (True, False, original_id, "inbox")
    assert doc.review_reasons == reasons


def test_without_a_match_field_every_submission_is_a_new_entry(db_session, workspace, verdict):
    cfg = SubmissionConfig()
    _submit(db_session, workspace, {"email": "ann@example.com"}, cfg)
    _, events = _submit(db_session, workspace, {"email": "ann@example.com"}, cfg)

    entries = _entries(db_session, workspace)
    assert len(entries) == 2
    for entry in entries:
        assert set(entry.metadata_json["submission"]) == {"received_at", "ip_address", "user_agent", "referer"}
    assert "entry_created" in [name for name, _ in events]
    doc = _received(events)
    assert (doc.duplicate, doc.existing_entry_id, doc.previous_status) == (False, None, None)


def test_the_visitor_sees_the_same_response_new_or_repeat(db_session, workspace, verdict):
    new, _ = _submit(db_session, workspace, {"email": "ann@example.com"})
    repeat, _ = _submit(db_session, workspace, {"email": "ANN@example.com"})
    entry = _entries(db_session, workspace)[0]
    _set_status(db_session, entry, "published")
    confirmed, _ = _submit(db_session, workspace, {"email": "ann@example.com"})
    verdict.flag = True
    flagged, _ = _submit(db_session, workspace, {"email": "ann@example.com"})

    shapes = [r.model_dump(exclude={"submission_id"}) for r in (new, repeat, confirmed, flagged)]
    assert shapes == [{"success": True, "message": "Thanks!", "redirect_url": "/thanks"}] * 4
    assert all(r.submission_id for r in (new, repeat, confirmed, flagged))


def test_entries_of_another_type_or_workspace_never_match(db_session, workspace, verdict):
    from marvin.db.models.platform import Entries, EntryTypes

    other = EntryTypes(session=db_session, group_id=workspace.group.id, name="Contact", slug="contact", schema_json=SCHEMA)
    db_session.add(other)
    db_session.flush()
    db_session.add(
        Entries(
            session=db_session,
            group_id=workspace.group.id,
            entry_type_id=other.id,
            title="Ann",
            slug=f"ann-{uuid.uuid4().hex[:6]}",
            status="inbox",
            data_json={"email": "ann@example.com"},
        )
    )
    db_session.commit()
    _submit(db_session, workspace, {"email": "ann@example.com"})
    assert len(_entries(db_session, workspace)) == 2


# ── identity normalisation ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Ann@Example.COM ", ("ann@example.com", True)),
        (" A-12 ", ("A-12", False)),
        (42, ("42", False)),
        ("", None),
        ("   ", None),
        (None, None),
        (True, None),
        (["a@b.co"], None),
    ],
)
def test_identity_value(value, expected):
    assert identity_value(value) == expected


# ── match_field validation on save ─────────────────────────────────────────────────────────────────


def _repo(db_session, gid):
    from marvin.repos.repository_factory import AllRepositories

    return AllRepositories(db_session, group_id=gid).entry_types


def test_match_field_must_be_a_schema_field_on_create(db_session, workspace):
    repo = _repo(db_session, workspace.group.id)
    with pytest.raises(HTTPException) as exc:
        repo.create(
            {
                "name": "Signup",
                "slug": "signup",
                "schema_json": SCHEMA,
                "capabilities_json": {"submittable": True, "submission": {"matchField": "phone"}},
            }
        )
    assert exc.value.status_code == 400 and "phone" in exc.value.detail
    db_session.rollback()
    created = repo.create(
        {"name": "Signup", "slug": "signup", "schema_json": SCHEMA, "capabilities_json": {"submittable": True, "submission": {"matchField": "email"}}}
    )
    assert created.capabilities["submission"]["matchField"] == "email"


def test_match_field_is_checked_when_either_side_changes(db_session, workspace):
    repo = _repo(db_session, workspace.group.id)
    etype_id = workspace.entry_type.id
    # Dropping the match field from the schema while it's still the match field is refused.
    with pytest.raises(HTTPException):
        repo.update(etype_id, {"schema_json": {"fields": [SCHEMA["fields"][1]]}})
    db_session.rollback()
    # Pointing the match field at something that isn't a field is refused.
    with pytest.raises(HTTPException):
        repo.update(etype_id, {"capabilities_json": {"submittable": True, "submission": {"match_field": "phone"}}})
    db_session.rollback()
    # Turning it off, or naming a real field, saves.
    repo.update(etype_id, {"capabilities_json": {"submittable": True, "submission": {"matchField": None}}})
    repo.update(etype_id, {"capabilities_json": {"submittable": True, "submission": {"matchField": "member_id"}}})


def test_submission_config_reads_match_field_in_either_case():
    assert SubmissionConfig.model_validate({"matchField": "email"}).match_field == "email"
    assert SubmissionConfig.model_validate({"match_field": "email"}).match_field == "email"
    assert SubmissionConfig().match_field is None


def test_a_deleted_entry_never_matches(db_session, workspace, verdict):
    from marvin.db.models.platform import Entries

    first, _ = _submit(db_session, workspace, {"email": "ann@example.com"})
    db_session.query(Entries).filter(Entries.id == first.submission_id).delete()  # deleting removes the row
    db_session.commit()
    second, events = _submit(db_session, workspace, {"email": "ann@example.com"})
    (entry,) = _entries(db_session, workspace)
    assert entry.id == second.submission_id != first.submission_id
    assert _received(events).duplicate is False
