"""The publish gate rejects placeholder links — `[text](#)`, `[text]()`, `href="#"`, `href=""` — in
markdown/richtext fields and the summary/description (services/entries/completeness.py). Real in-page
anchors (`#section`) and real URLs pass."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.services.entries.completeness import evaluate_completeness, linkable_text_fields, placeholder_link_texts

SCHEMA = {
    "fields": [
        {"key": "body", "label": "Body", "type": "markdown"},
        {"key": "notes", "label": "Notes", "type": "richtext"},
        {"key": "caption", "label": "Caption", "type": "text"},
    ]
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("See [Blue Heron](#) and [Gone]().", ["Blue Heron", "Gone"]),
        ("[Spaced]( # )", ["Spaced"]),
        ('<a href="#">Blue Heron</a>', ["Blue Heron"]),
        ("<a class='x' href=''><b>Gone</b></a>", ["Gone"]),
        ("[](#)", ["(no text)"]),
    ],
)
def test_placeholder_link_texts_finds_placeholders(text, expected):
    assert placeholder_link_texts(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Jump to [prices](#prices).",
        '<a href="#prices">prices</a>',
        "[Blue Heron](https://gallery.example.com/works/blue-heron)",
        "[Blue Heron](/works/blue-heron)",
        "Plain text with a # hash and (parens).",
        None,
    ],
)
def test_placeholder_link_texts_allows_real_links_and_anchors(text):
    assert placeholder_link_texts(text) == []


def test_linkable_text_fields_picks_markdown_and_richtext():
    assert linkable_text_fields(SCHEMA) == [("body", "Body"), ("notes", "Notes")]


def _evaluate(data, **kwargs):
    return evaluate_completeness(schema=None, recipe=None, data_json=data, title="Newsletter", link_fields=linkable_text_fields(SCHEMA), **kwargs)


def test_evaluate_completeness_blocks_placeholder_link_in_markdown_field():
    report = _evaluate({"body": "Six works: [Blue Heron](#), [Gone]()"})
    assert not report.ok
    assert report.blocking[0].kind == "link" and report.blocking[0].key == "body"
    assert "'Blue Heron', 'Gone'" in report.blocking_messages()[0]


def test_evaluate_completeness_allows_anchor_links():
    assert _evaluate({"body": "Jump to [prices](#prices)."}).ok


def test_evaluate_completeness_ignores_plain_text_fields():
    assert _evaluate({"caption": "[Blue Heron](#)"}).ok


def test_evaluate_completeness_scans_summary_and_description():
    report = _evaluate({}, summary="New: [Blue Heron](#)", description='<a href="">Gone</a>')
    assert [i.key for i in report.blocking] == ["summary", "description"]


def test_evaluate_completeness_unchanged_without_links():
    assert _evaluate({"body": "Nothing linked here."}, summary="A plain summary").ok


# --- the gate itself ------------------------------------------------------------------------------


@fixture
def draft(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"ph-{marker}", slug=f"ph-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json=SCHEMA)
    db_session.add(et)
    db_session.flush()
    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="October", slug=f"oct-{marker}", status="draft", data_json={})
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(gid=gid, entry=entry)
    db_session.rollback()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _gate(db_session, draft, data):
    from marvin.services.entries import EntryService

    svc = EntryService(db_session, draft.gid)
    svc._gate_publish(draft.entry.id, svc.repos.entries.get_one(draft.entry.id), {"status": "published", **data})


def test_publish_gate_rejects_placeholder_links_with_their_texts(db_session, draft):
    with pytest.raises(HTTPException) as exc:
        _gate(db_session, draft, {"data_json": {"body": "Works: [Blue Heron](#) and [Gone]()"}})
    assert exc.value.status_code == 422
    assert "'Blue Heron', 'Gone'" in exc.value.detail["issues"][0]


def test_publish_gate_rejects_stored_placeholder_in_summary(db_session, draft):
    draft.entry.summary = "See [Blue Heron](#)"
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        _gate(db_session, draft, {})
    assert "Summary" in exc.value.detail["issues"][0]


def test_publish_gate_allows_anchor_links(db_session, draft):
    _gate(db_session, draft, {"data_json": {"body": "Jump to [prices](#prices) or [the work](https://example.com/w)."}})


def test_publish_gate_allows_entries_without_links(db_session, draft):
    _gate(db_session, draft, {"data_json": {"body": "Plain body."}})
